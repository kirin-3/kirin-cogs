"""This module defines the `ContestCog` class

ContestCog is a Redbot cog for managing and posting information about
the Cutie of the Month Contest.
The cog includes methods for importing text from files, creating Discord
embeds, retrieving contest channels, formatting text with contest-specific
details, and posting contest information to a designated channel.
"""

from pathlib import Path
import logging
from datetime import datetime, timezone

import discord
from discord import ui

from redbot.core import commands
from redbot.core.bot import Red

from . import __version__, const
from .unicornia import strings


class ContestCog(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot

        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.logger.setLevel(const.LOGGER_LEVEL)

        self._contest_number: int = 1

        self.logger.info("-" * 32)
        self.logger.info(f"{self.__class__.__name__} v({__version__}) initialized!")
        self.logger.info("-" * 32)

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
            with open(filename, "r", encoding="utf-8") as file:
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
        embed = discord.Embed(title=title, description=description)

        footer_text = strings.format_string(
            const.FOOTER_TEXT, contest_number=self.contest_number
        )
        embed.set_footer(text=footer_text, icon_url=const.FOOTER_ICON_URL)
        embed.color = const.UNICORNIA_BOT_COLOR

        return embed

    def _get_channel(self, ctx: commands.Context) -> discord.TextChannel:
        """Retrieves the contest information channel for the given context.

        Args:
            ctx (commands.Context): The context from which to retrieve the channel.

        Returns:
            discord.TextChannel: The contest information channel if found, otherwise None.
        """
        channel_id = const.CONTEST_CHANNEL_IDS[ctx.guild.id]["info"]
        if channel_id is None:
            self.logger.error(
                f"Unable to find contest channel id for Guild ID:{ctx.guild.id}"
            )
            return None

        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            self.logger.error(f"Channel with ID {const.CONTEST_CHANNEL_ID} not found.")
            return

        return channel

    def _format_text(self, ctx: commands.Context, text: str) -> str:
        """
        Formats the given text with contest-specific details.

        Args:
            ctx (commands.Context): The context in which the command was invoked.
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

    async def _post_contest_info(
        self, ctx: commands.Context, contest_number: int = None
    ):
        """Posts information about the Cutie of the Month Contest to the designated channel.

        This method sends a unified V2 Components Dashboard to the specific channel, detailing
        the contest description, terms and conditions, prizes, and voting instructions via interactive tabs.

        Args:
            ctx (commands.Context): The context in which the command was invoked.
            contest_number (int, optional): The contest number to be posted. Defaults to None.
        """
        channel = self._get_channel(ctx)
        if channel is None:
            return await ctx.send(f"Unable to find contest channel on this server!")

        # this updates property as an integer, and gets it a a string with ordinal suffix
        # ex: "52nd", "53rd", etc
        if contest_number is not None:
            self.contest_number = contest_number

        # Load and format the texts
        texts = {
            "description": self._format_text(ctx, self._import_txt(const.CONTEST_DESCRIPTION)),
            "terms": self._format_text(ctx, self._import_txt(const.TERMS_DESCRIPTION)),
            "prizes": self._format_text(ctx, self._import_txt(const.PRIZES_DESCRIPTION)),
            "votes": self._format_text(ctx, self._import_txt(const.VOTES_DESCRIPTION))
        }

        # Import the view (doing it here to avoid circular imports if needed, though top level is fine)
        from .cotm_views import ContestDashboardView

        dashboard_view = ContestDashboardView(self, self.contest_number, texts)
        await channel.send(view=dashboard_view)

    @commands.command(aliases=["cotm"])
    @commands.admin_or_permissions(administrator=True)
    async def contest(self, ctx: commands.Context, contest_number: int = None):
        """Handles the contest command.

        Parameters:
            ctx (commands.Context): The context in which the command was invoked.
            contest_number (int, optional): The number of the contest to retrieve information for. Defaults to None.
        """
        return await self._post_contest_info(ctx, contest_number)

    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    @commands.command()
    async def contestcount(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        emote: str = const.COTM_VOTE_EMOJI,
        show_invalid: bool = True,
        voter_server_age: commands.TimedeltaConverter = None,
        *other_emotes,
    ):
        """
        Counts reactions in a channel and displays a leaderboard.
        """
    async def _get_contest_results(
        self,
        channel: discord.TextChannel,
        emote: str = const.COTM_VOTE_EMOJI,
        voter_server_age: commands.TimedeltaConverter = None,
        *other_emotes,
    ) -> list:
        """Helper to tally valid votes from a channel."""
        timenow = datetime.now(timezone.utc)

        def valid_user_vote(u):
            if not hasattr(u, "joined_at") or u.joined_at is None:
                return False
            # Filter out users younger than the required age (joined after the cutoff)
            elif (
                voter_server_age is not None
                and u.joined_at >= timenow - voter_server_age
            ):
                return False
            return True

        entries = []
        async for message in channel.history(limit=None):
            entry = {
                "name": str(message.author),
                "valid_votes": 0,
                "invalid_votes": 0,
            }
            for r in message.reactions:
                if str(r.emoji) == emote or str(r.emoji) in other_emotes:
                    all_votes = [u async for u in r.users()]
                    valid_votes_list = list(filter(valid_user_vote, all_votes))
                    entry["valid_votes"] = len(valid_votes_list)
                    entry["invalid_votes"] = len(all_votes) - entry["valid_votes"]
            entries.append(entry)

        if entries:
            entries = sorted(entries, key=lambda e: e["valid_votes"], reverse=True)
            return entries[:10] # Return Top 10
        return []

    def _build_standings_container(self, top_entries: list, title: str, channel: discord.TextChannel = None, show_invalid: bool = True) -> ui.Container:
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
            standings_text += f"**#{i+1} {entry['name']}** - {val}\n"
            
        if not standings_text:
             standings_text = "_No valid entries found._"
             
        container.add_item(ui.TextDisplay(content=standings_text))
        return container

    @commands.command()
    @commands.admin_or_permissions(administrator=True)
    async def contestcount(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        emote: str = const.COTM_VOTE_EMOJI,
        show_invalid: bool = True,
        voter_server_age: commands.TimedeltaConverter = None,
        *other_emotes,
    ):
        """
        Counts reactions in a channel and displays a leaderboard.
        """
        top_entries = await self._get_contest_results(channel, emote, voter_server_age, *other_emotes)
        
        if not top_entries:
            return await ctx.send(f"No entries found for channel {channel.mention}")

        container = self._build_standings_container(top_entries, f"Contest Leaderboard", channel, show_invalid)
        
        # Create a simple LayoutView to hold the container
        class StandingsView(ui.LayoutView):
             def __init__(self, container):
                  super().__init__(timeout=180)
                  self.add_item(container)
                  
        await ctx.send(view=StandingsView(container))

    @commands.guild_only()
    @commands.is_owner()
    @commands.command()
    async def cotmreward(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
    ):
        """
        Counts the Top 10 users in a contest channel using the predetermined emoji
        and automatically distributes the tiered Unicornia currency rewards to them.

        This command is restricted to bot owners.
        """
        unicornia = self.bot.get_cog("Unicornia")
        if not unicornia:
            return await ctx.send(
                "❌ **Error:** The `Unicornia` cog is not currently loaded or available. "
                "Cannot distribute rewards."
            )

        async with ctx.typing():
            timenow = datetime.now(timezone.utc)

            def valid_user_vote(u):
                if not hasattr(u, "joined_at") or u.joined_at is None:
                    return False
                return True

            entries = []
            async for message in channel.history(limit=None):
                entry = {
                    "user": message.author,
                    "name": str(message.author),
                    "valid_votes": 0,
                }
                for r in message.reactions:
                    if str(r.emoji) == const.COTM_VOTE_EMOJI:
                        all_votes = [u async for u in r.users()]
                        valid_votes_list = list(filter(valid_user_vote, all_votes))
                        entry["valid_votes"] += len(valid_votes_list)
                
                # We only want entries that actually got votes
                if entry["valid_votes"] > 0:
                    entries.append(entry)

            if not entries:
                return await ctx.send(f"No valid entries found for channel {channel.mention}")

            # Sort users by valid votes descending
            entries = sorted(entries, key=lambda e: e["valid_votes"], reverse=True)
            top_entries = entries[:10]

            # --- Build Confirmation V2 Container ---
            # Reuse the container builder but append the payout details
            container = self._build_standings_container(top_entries, f"Contest Rewards Distributed", channel, show_invalid=False)
            
            # Add a separator and the payout logs
            container.add_item(ui.Separator())
            payout_text = "### 💸 Payout Log\n"
            
            for i, entry in enumerate(top_entries):
                if i >= len(const.COTM_REWARDS):
                    break # Safety bounds check just in case

                reward_amount = const.COTM_REWARDS[i]
                rank = i + 1
                user = entry["user"]

                # Payout 
                success = await unicornia.add_balance(
                    user_id=user.id,
                    amount=reward_amount,
                    reason=f"COTM Top 10 Reward (Rank {rank})",
                    source="ContestCog"
                )

                if success:
                    payout_text += f"**#{rank} {entry['name']}**: +{reward_amount:,} 🦄\n"
                else:
                    payout_text += f"**#{rank} {entry['name']}**: ❌ Failed to deposit\n"
                    
            container.add_item(ui.TextDisplay(content=payout_text))
            
            class StandingsView(ui.LayoutView):
                 def __init__(self, container):
                      super().__init__(timeout=180)
                      self.add_item(container)
                      
            await ctx.send(view=StandingsView(container))
