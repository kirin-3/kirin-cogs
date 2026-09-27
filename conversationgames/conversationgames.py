import asyncio
import logging
import random
import re

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from . import questions
from .views import NAMES, Question, ReviewView, TruthOrDareCard, VoteCard, card_embed, read_review, review_embed

log = logging.getLogger("red.kirin_cogs.conversationgames")

BUILT_IN: dict[str, list[Question]] = {
    "truth": list(questions.TRUTHS),
    "dare": list(questions.DARES),
    "wyr": list(questions.WYR),
    "nhie": list(questions.NHIE),
}


def clean(kind: str, parts: list[str]) -> Question | None:
    """A suggestion as it will be stored: WYR as two options, NHIE starting with "...". None if it's empty."""
    if kind == "wyr":
        options = []
        for part in parts:
            part = re.sub(r"^\s*(?:would you rather|or)\b", "", part.strip(), flags=re.IGNORECASE)
            options.append(part.strip(" .?"))
        return (options[0], options[1]) if len(options) == 2 and all(options) else None
    text = " ".join(parts).strip()
    if kind == "nhie":
        text = re.sub(r"^never have i ever\b", "", text, flags=re.IGNORECASE).lstrip(" .")
        return f"...{text}" if text else None
    return text or None


def _stored(kind: str, value: object) -> Question | None:
    """A question from Config, or None if the record is malformed."""
    if kind == "wyr":
        if isinstance(value, list | tuple) and len(value) == 2 and all(isinstance(v, str) and v for v in value):
            return (value[0], value[1])
        return None
    return value if isinstance(value, str) and value else None


class ConversationGames(commands.Cog):
    """Truth or dare, would you rather and never have I ever, with buttons, live votes and member suggestions."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x6B69726E4347, force_registration=True)
        self.config.register_guild(review_channel=None, custom={kind: [] for kind in BUILT_IN})
        # ponytail: decks live in memory, so a restart reshuffles them; store drawn questions in Config if that bites
        self.decks: dict[tuple[int, str], list[Question]] = {}
        self.lock = asyncio.Lock()
        self.review_view = ReviewView(self)
        bot.add_view(self.review_view)

    async def cog_unload(self) -> None:
        self.review_view.stop()

    # --- questions ---------------------------------------------------------------------------------

    async def pool(self, guild: discord.Guild, kind: str) -> list[Question]:
        """The built-in questions plus the server's approved suggestions."""
        custom = await self.config.guild(guild).custom()
        stored = custom.get(kind) if isinstance(custom, dict) else None
        extra = [q for q in (_stored(kind, v) for v in stored or []) if q is not None]
        return [*BUILT_IN[kind], *extra]

    async def draw(self, guild: discord.Guild, kind: str) -> Question:
        """The next question from the server's shuffled deck; nothing repeats until the whole deck has been drawn."""
        deck = self.decks.get((guild.id, kind))
        if not deck:
            deck = await self.pool(guild, kind)
            random.shuffle(deck)
            self.decks[guild.id, kind] = deck
        return deck.pop()

    async def add_question(self, guild: discord.Guild, kind: str, question: Question) -> bool:
        """Save an approved suggestion. False if the deck already has it."""
        async with self.lock:
            if question in await self.pool(guild, kind):
                return False
            async with self.config.guild(guild).custom() as custom:
                custom.setdefault(kind, []).append(list(question) if isinstance(question, tuple) else question)
            deck = self.decks.get((guild.id, kind))
            if deck:
                deck.insert(random.randrange(len(deck) + 1), question)
            return True

    # --- cards -------------------------------------------------------------------------------------

    async def post(
        self,
        where: commands.Context | discord.Interaction,
        kind: str,
        asker: discord.abc.User,
        target: discord.abc.User | None = None,
    ) -> None:
        """Send a new card, as a command reply or as the answer to a button press. ``tod`` picks truth or dare."""
        guild = where.guild
        assert guild is not None
        if kind == "tod":
            kind = random.choice(("truth", "dare"))
        view = TruthOrDareCard(self, kind) if kind in ("truth", "dare") else VoteCard(self, kind)
        embed = card_embed(kind, await self.draw(guild, kind), asker, target)
        content = target.mention if target else None
        mentions = discord.AllowedMentions(everyone=False, roles=False, users=[target]) if target else None
        if isinstance(where, discord.Interaction):
            await where.response.send_message(
                content, embed=embed, view=view, allowed_mentions=mentions or discord.AllowedMentions.none()
            )
            view.message = await where.original_response()
        else:
            view.message = await where.send(
                content, embed=embed, view=view, allowed_mentions=mentions or discord.AllowedMentions.none()
            )

    @commands.hybrid_command()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def truth(self, ctx: commands.GuildContext, member: discord.Member | None = None) -> None:
        """Ask a truth question, to someone or to whoever wants it."""
        await self.post(ctx, "truth", ctx.author, member)

    @commands.hybrid_command()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def dare(self, ctx: commands.GuildContext, member: discord.Member | None = None) -> None:
        """Dare someone, or whoever wants it."""
        await self.post(ctx, "dare", ctx.author, member)

    @commands.hybrid_command(aliases=["tod"])  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def truthordare(self, ctx: commands.GuildContext, member: discord.Member | None = None) -> None:
        """A random truth or dare."""
        await self.post(ctx, "tod", ctx.author, member)

    @commands.hybrid_command(aliases=["wyr"])  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def wouldyourather(self, ctx: commands.GuildContext) -> None:
        """Would you rather...? Everyone can vote."""
        await self.post(ctx, "wyr", ctx.author)

    @commands.hybrid_command(aliases=["nhie"])  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def neverhaveiever(self, ctx: commands.GuildContext) -> None:
        """Never have I ever... Everyone can say whether they have."""
        await self.post(ctx, "nhie", ctx.author)

    # --- suggestions -------------------------------------------------------------------------------

    async def submit(self, interaction: discord.Interaction, kind: str, parts: list[str]) -> None:
        """Send a member's suggestion to the review channel."""
        guild = interaction.guild
        assert guild is not None
        question = clean(kind, parts)
        if question is None:
            await interaction.response.send_message("That suggestion is empty.", ephemeral=True)
            return
        channel_id = await self.config.guild(guild).review_channel()
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Suggestions aren't open right now.", ephemeral=True)
            return
        if question in await self.pool(guild, kind):
            await interaction.response.send_message("That one's already in the deck.", ephemeral=True)
            return
        try:
            await channel.send(
                f"Suggested by {interaction.user.mention}",
                embed=review_embed(kind, question, interaction.user),
                view=self.review_view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as e:
            log.warning(f"Could not post a suggestion in {channel.id}: {e}")
            await interaction.response.send_message(
                "I couldn't pass that on to staff. Try again later.", ephemeral=True
            )
            return
        await interaction.response.send_message("Thanks! Staff will look at your suggestion.", ephemeral=True)

    async def review(self, interaction: discord.Interaction, *, approved: bool) -> None:
        member, message = interaction.user, interaction.message
        if not isinstance(member, discord.Member) or not (
            member.guild_permissions.manage_guild or await self.bot.is_mod(member)
        ):
            await interaction.response.send_message("Only staff can review suggestions.", ephemeral=True)
            return
        found = read_review(message.embeds[0]) if message and message.embeds else None
        if message is None or found is None:
            await interaction.response.send_message("I can't read this suggestion anymore.", ephemeral=True)
            return
        kind, question = found
        embed = message.embeds[0]
        if approved:
            added = await self.add_question(member.guild, kind, question)
            embed.title = f"{'Approved' if added else 'Already in the deck'}: {NAMES[kind]}"
            embed.colour = discord.Colour.green()
        else:
            embed.title = f"Denied: {NAMES[kind]}"
            embed.colour = discord.Colour.red()
        embed.add_field(name="Reviewed by", value=member.mention, inline=False)
        await interaction.response.edit_message(embed=embed, view=None)

    @commands.group()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def cgset(self, ctx: commands.GuildContext) -> None:
        """Conversation games settings."""

    @cgset.command(name="reviewchannel")
    async def cgset_reviewchannel(self, ctx: commands.GuildContext, channel: discord.TextChannel | None = None) -> None:
        """Where member suggestions go for staff to approve. Leave the channel out to stop taking suggestions."""
        if channel is None:
            await self.config.guild(ctx.guild).review_channel.clear()
            await ctx.send("Members can't suggest questions anymore.")
            return
        permissions = channel.permissions_for(ctx.me)
        if not (permissions.send_messages and permissions.embed_links):
            await ctx.send(f"I need Send Messages and Embed Links in {channel.mention} first.")
            return
        await self.config.guild(ctx.guild).review_channel.set(channel.id)
        await ctx.send(f"Suggestions now go to {channel.mention} for staff to approve.")
