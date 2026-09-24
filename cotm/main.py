"""This module defines the `ContestCog` class

ContestCog is a Redbot cog for managing and posting information about
the Cutie of the Month Contest.
The cog includes methods for importing text from files, creating Discord
embeds, retrieving contest channels, formatting text with contest-specific
details, and posting contest information to a designated channel.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import discord
from discord import ui
from redbot.core import Config, commands
from redbot.core.bot import Red

from . import __version__, const
from .cotm_views import ContestDashboardView, StandingsView
from .unicornia import strings


class ContestCog(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot

        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.logger.setLevel(const.LOGGER_LEVEL)

        self._contest_number: int = 1

        # Shared "Check Standings" result: (monotonic time, ranked entries, tallied at)
        self._standings_cache: tuple[float, list[dict[str, Any]], datetime] | None = None
        self._standings_lock = asyncio.Lock()
        self._reward_lock = asyncio.Lock()

        self.config = Config.get_conf(self, identifier=906144832, force_registration=True)
        # payouts: contest number -> {"channel_id", "placements"}, saved before the first deposit
        self.config.register_global(contest_number=1, payouts={})

        self.logger.info("-" * 32)
        self.logger.info(f"{self.__class__.__name__} v({__version__}) initialized!")
        self.logger.info("-" * 32)

    async def cog_load(self) -> None:
        """Restores persisted state and registers the persistent view with the bot.

        This ensures the contest dashboard buttons remain interactive across bot restarts.
        """
        self._contest_number = await self.config.contest_number()
        texts = self._load_texts()
        self.bot.add_view(ContestDashboardView(self, self._contest_number, texts))
        self.logger.info(f"Registered persistent ContestDashboardView (contest #{self._contest_number})")

    @property
    def contest_number(self) -> str:
        return strings.add_ordinal_suffix(self._contest_number)

    @contest_number.setter
    def contest_number(self, number: int):
        self._contest_number = number

    def _import_txt(self, filename: Path):
        """Imports text from a specified file.

        Args:
            filename (Path): The path to the file to be imported.

        Returns:
            str: The content of the file as a string. Returns an empty string if the file is not found or an error occurs.
        """
        try:
            with open(filename, encoding="utf-8") as file:
                text = file.read()
            self.logger.debug(f"{filename=} loaded successfully.")
            return text
        except FileNotFoundError:
            self.logger.warning(f"{filename=} not found. Starting with empty data.")
        except Exception as e:
            self.logger.error(f"An error occurred while loading {filename=}: {e}")
        return ""

    def _create_embed(
        self,
        title: str,
        description: str,
    ) -> discord.Embed:
        """Creates a Discord embed with the given title and description.

        Args:
            title (str): The title of the embed.
            description (str): The description of the embed.

        Returns:
            discord.Embed: The created embed with the specified title, description, footer, and color.
        """
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color(const.UNICORNIA_BOT_COLOR),
        )

        footer_text = strings.format_string(const.FOOTER_TEXT, contest_number=self.contest_number)
        embed.set_footer(text=footer_text, icon_url=const.FOOTER_ICON_URL)

        return embed

    def _format_text(self, text: str) -> str:
        """
        Formats the given text with contest-specific details.

        Args:
            text (str): The text to be formatted.

        Returns:
            str: The formatted text with contest details.
        """
        return strings.format_string(
            text,
            contest_number=self.contest_number,
            cutie_role=const.CUTIE_ROLE_MENTION,
            entries_channel=const.ENTRIES_CHANNEL_MENTION,
            winners_channel=const.WINNERS_CHANNEL_MENTION,
        )

    def _load_texts(self) -> dict[str, str]:
        """Loads and formats all contest text sections from disk.

        Returns:
            dict[str, str]: Mapping of section name to formatted text content.
        """
        return {
            "description": self._format_text(self._import_txt(const.CONTEST_DESCRIPTION)),
            "terms": self._format_text(self._import_txt(const.TERMS_DESCRIPTION)),
            "prizes": self._format_text(self._import_txt(const.PRIZES_DESCRIPTION)),
            "votes": self._format_text(self._import_txt(const.VOTES_DESCRIPTION)),
        }

    async def _post_contest_info(self, ctx: commands.Context, contest_number: int | None = None) -> None:
        """Posts information about the Cutie of the Month Contest to the designated channel.

        This method sends a unified V2 Components Dashboard to the specific channel, detailing
        the contest description, terms and conditions, prizes, and voting instructions via interactive tabs.

        Args:
            ctx (commands.Context): The context in which the command was invoked.
            contest_number (int, optional): The contest number to be posted. Defaults to None.
        """

        # this updates property as an integer, and gets it as a string with ordinal suffix
        # ex: "52nd", "53rd", etc
        if contest_number is not None:
            self.contest_number = contest_number
            await self.config.contest_number.set(self._contest_number)

        texts = self._load_texts()

        dashboard_view = ContestDashboardView(self, self._contest_number, texts)
        await cast(discord.TextChannel, ctx.channel).send(view=dashboard_view)

    @commands.command(aliases=["cotm"])  # pyright: ignore[reportArgumentType]
    @commands.admin_or_permissions(administrator=True)
    async def contest(self, ctx: commands.Context, contest_number: int | None = None) -> None:
        """Handles the contest command.

        Parameters:
            ctx (commands.Context): The context in which the command was invoked.
            contest_number (int, optional): The number of the contest to retrieve information for. Defaults to None.
        """
        await self._post_contest_info(ctx, contest_number)

    async def _tally_entries(
        self,
        channel: discord.TextChannel,
        emote: str = const.COTM_VOTE_EMOJI,
        voter_server_age: timedelta | None = None,
        *other_emotes: str,
    ) -> list[dict[str, Any]]:
        """Tally votes in a channel and rank authors, most valid votes first.

        A voter counts once per entry, however many of the vote emojis they used on it.
        Each author is ranked once, by their best entry, so extra entries never earn extra places.
        """
        timenow = datetime.now(UTC)
        vote_emotes = {emote, *other_emotes}

        def valid_user_vote(u) -> bool:
            return not (
                not hasattr(u, "joined_at")
                or u.joined_at is None
                or (voter_server_age is not None and u.joined_at >= timenow - voter_server_age)
            )

        best_by_author: dict[int, dict[str, Any]] = {}
        async for message in channel.history(limit=None):
            valid_voters: set[int] = set()
            invalid_voters: set[int] = set()
            for r in message.reactions:
                if str(r.emoji) not in vote_emotes:
                    continue
                async for u in r.users():
                    (valid_voters if valid_user_vote(u) else invalid_voters).add(u.id)

            entry = {
                "user": message.author,
                "name": str(message.author),
                "valid_votes": len(valid_voters),
                "invalid_votes": len(invalid_voters),
            }
            best = best_by_author.get(message.author.id)
            if best is None or entry["valid_votes"] > best["valid_votes"]:
                best_by_author[message.author.id] = entry

        return sorted(best_by_author.values(), key=lambda e: e["valid_votes"], reverse=True)

    async def _get_contest_results(
        self,
        channel: discord.TextChannel,
        emote: str = const.COTM_VOTE_EMOJI,
        voter_server_age: timedelta | None = None,
        *other_emotes: str,
    ) -> list[dict[str, Any]]:
        """Top 10 authors in a channel, one row per author."""
        entries = await self._tally_entries(channel, emote, voter_server_age, *other_emotes)
        return entries[:10]

    async def get_standings(self, channel: discord.TextChannel) -> tuple[list[dict[str, Any]], datetime]:
        """Top 10 for the public standings button, re-tallied at most every STANDINGS_CACHE_SECONDS.

        Presses that arrive while a tally is running wait for it instead of starting their own.
        """
        async with self._standings_lock:
            cached = self._standings_cache
            if cached is not None and time.monotonic() - cached[0] < const.STANDINGS_CACHE_SECONDS:
                return cached[1], cached[2]
            entries = await self._get_contest_results(channel)
            tallied_at = datetime.now(UTC)
            self._standings_cache = (time.monotonic(), entries, tallied_at)
            return entries, tallied_at

    def _build_standings_container(
        self,
        top_entries: list,
        title: str,
        channel: discord.TextChannel | None = None,
        show_invalid: bool = True,
    ) -> ui.Container:
        """Builds a V2 Container for displaying the Top 10 standings."""
        container = ui.Container(accent_color=discord.Color.from_rgb(175, 126, 235))

        header_text = f"## {title}"
        if channel:
            header_text += f"\nTop {len(top_entries)} results for {channel.mention}"

        container.add_item(ui.TextDisplay(content=header_text))
        container.add_item(ui.Separator())

        standings_text = ""
        for i, entry in enumerate(top_entries):
            if show_invalid:
                val = f"{entry['valid_votes']} valid votes ({entry['invalid_votes']} invalid)"
            else:
                val = f"{entry['valid_votes']} votes"
            standings_text += f"**#{i + 1} {entry['name']}** - {val}\n"

        if not standings_text:
            standings_text = "_No valid entries found._"

        container.add_item(ui.TextDisplay(content=standings_text))
        return container

    @commands.command()  # pyright: ignore[reportArgumentType]
    @commands.admin_or_permissions(administrator=True)
    async def contestcount(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        emote: str = const.COTM_VOTE_EMOJI,
        show_invalid: bool = False,
        voter_server_age: commands.TimedeltaConverter | None = None,
        *other_emotes,
    ) -> None:
        """
        Counts reactions in a channel and displays a leaderboard.
        """
        age_td = cast(timedelta | None, voter_server_age)
        top_entries = await self._get_contest_results(channel, emote, age_td, *other_emotes)

        if not top_entries:
            await ctx.send(f"No entries found for channel {channel.mention}")
            return

        container = self._build_standings_container(top_entries, "Contest Leaderboard", channel, show_invalid)
        await cast(discord.TextChannel, ctx.channel).send(view=StandingsView(container))

    async def red_delete_data_for_user(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, *, requester, user_id: int
    ) -> None:
        """Forget a winner in saved contest results; their place stays, so the other places keep their amounts."""
        async with self.config.payouts() as payouts:
            for saved in payouts.values():
                for placement in saved["placements"]:
                    if placement["user_id"] == user_id:
                        placement["user_id"] = None
                        placement["name"] = "Deleted user"

    async def _reward_placements(self, contest: int, channel: discord.TextChannel) -> list[dict[str, Any]] | int | None:
        """The paid places for a contest, decided once and then reused.

        The first run tallies the channel and saves the places before any deposit, so a rerun
        pays the same people the same amounts even if votes changed in between. Returns None
        when there is nothing to pay, or the saved channel ID when `channel` is a different one.
        """
        saved = (await self.config.payouts()).get(str(contest))
        if saved is not None:
            if saved["channel_id"] != channel.id:
                return saved["channel_id"]
            return saved["placements"]

        entries = [entry for entry in await self._tally_entries(channel) if entry["valid_votes"] > 0]
        if not entries:
            return None
        placements = [
            {"user_id": entry["user"].id, "name": entry["name"], "votes": entry["valid_votes"], "amount": amount}
            for entry, amount in zip(entries, const.COTM_REWARDS, strict=False)
        ]
        async with self.config.payouts() as payouts:
            payouts[str(contest)] = {"channel_id": channel.id, "placements": placements}
        return placements

    @commands.guild_only()
    @commands.is_owner()
    @commands.command()
    async def cotmreward(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        contest_number: int | None = None,
    ) -> None:
        """
        Pays the tiered Unicornia currency rewards to the top contestants in a contest channel.

        Places are ranked by author using the contest vote emoji, and only the places in
        prizes.txt are paid. The first run saves the places, so running this again (for example
        after a failed deposit) pays the same winners and only what is still missing, even if
        the votes have changed since.
        `contest_number` defaults to the number set with `[p]contest`.

        This command is restricted to bot owners.
        """
        assert ctx.guild is not None
        unicornia: Any = self.bot.get_cog("Unicornia")
        if not unicornia:
            await ctx.send(
                "❌ **Error:** The `Unicornia` cog is not currently loaded or available. Cannot distribute rewards."
            )
            return

        contest = contest_number if contest_number is not None else self._contest_number

        async with self._reward_lock, ctx.typing():
            placements = await self._reward_placements(contest, channel)
            if placements is None:
                await ctx.send(f"No valid entries found for channel {channel.mention}")
                return
            if isinstance(placements, int):
                await ctx.send(
                    f"❌ Rewards for contest {contest} were already decided from <#{placements}>. "
                    "Run the command on that channel, or pass the right contest number."
                )
                return

            contest_label = strings.add_ordinal_suffix(contest)
            container = self._build_standings_container(
                [{"name": p["name"], "valid_votes": p["votes"]} for p in placements],
                f"Contest Rewards — {contest_label} Cutie of the Month",
                channel,
                show_invalid=False,
            )

            # Add a separator and the payout logs
            container.add_item(ui.Separator())
            payout_text = "### 💸 Payout Log\n"

            for rank, placement in enumerate(placements, 1):
                user_id, name, reward_amount = placement["user_id"], placement["name"], placement["amount"]
                if user_id is None:
                    payout_text += f"**#{rank} {name}**: not paid, their data was deleted\n"
                    continue
                try:
                    outcome = await unicornia.apply_operation(
                        key=f"cotm:{contest}:{user_id}",
                        user_id=user_id,
                        amount=reward_amount,
                        direction="credit",
                        source="ContestCog",
                        guild_id=ctx.guild.id,
                        reason=f"COTM {contest_label} Reward (Rank {rank})",
                    )
                except Exception:
                    self.logger.exception(f"COTM {contest} payout to {user_id} failed")
                    outcome = None
                state = getattr(outcome, "state", None)

                if state == "settled":
                    payout_text += f"**#{rank} {name}**: +{reward_amount:,} <:slut:686148402941001730>\n"
                elif state == "duplicate":
                    payout_text += f"**#{rank} {name}**: already paid for this contest\n"
                else:
                    payout_text += f"**#{rank} {name}**: ❌ Failed to deposit\n"

            container.add_item(ui.TextDisplay(content=payout_text))

            await cast(discord.TextChannel, ctx.channel).send(view=StandingsView(container))
