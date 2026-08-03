import asyncio
import logging
from datetime import UTC, datetime

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red

from .migrations import migrate_global_schema
from .models import PROFILE_CHANNEL_ID, UNIQUE_ID, ProfileData, canonicalize_profile_data
from .views import ProfileBuilderView, ProfileDeleteConfirmView, ProfileStickyView

log = logging.getLogger("red.kirin_cogs.profile")


class Profile(commands.Cog):
    """Create and manage user profiles in a specific channel."""

    def __init__(self, bot: Red):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=UNIQUE_ID, force_registration=True)

        # Legacy global configuration (kept registered so pre-guild-scope
        # installs remain readable for lazy per-guild adoption and rollback).
        default_global = {
            "schema_version": 0,  # marker for migrations.py; 0 = legacy unmigrated record
            "channel_id": PROFILE_CHANNEL_ID,
            "sticky_message_id": None,
            "sticky_locked": False,
            "cooldown": 3,
        }
        # Guild-scoped configuration (canonical since guild-scope migration).
        default_guild = {
            "channel_id": None,
            "sticky_message_id": None,
            "cooldown": 3,
            "legacy_adopted": False,
        }
        # Member-scoped profile answers (canonical since guild-scope migration).
        default_member = {"profile_data": {}, "message_id": None, "last_delete": None}
        # Legacy user-scope records (kept registered for adoption and rollback).
        default_user = {"profile_data": {}, "message_id": None, "last_delete": None}

        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)
        self.config.register_user(**default_user)

        self.locked_channels = set()
        self._channel_cvs: dict[discord.TextChannel, asyncio.Condition] = {}
        self.bot.add_view(ProfileStickyView(self))

    async def cog_load(self):
        await migrate_global_schema(self.config)
        # We don't necessarily need to repost on load,
        # but we should ensure the view is active.

    async def red_delete_data_for_user(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, *, requester, user_id: int
    ) -> None:
        """Delete legacy and guild-scoped profile records for a Discord user ID."""
        await self.config.user_from_id(user_id).clear()
        for guild_id, members in (await self.config.all_members()).items():
            if isinstance(members, dict) and (user_id in members or str(user_id) in members):
                await self.config.member_from_ids(guild_id, user_id).clear()

    async def _ensure_guild_data(self, guild: discord.Guild) -> None:
        """Lazily adopt legacy global/user data into this guild's scopes.

        Legacy Profile configuration was global and answers were user-scoped.
        On first use per guild, the legacy configuration is copied into guild
        scope and legacy answers into guild-aware member records (canonical
        ``picture_url`` field). Copies never overwrite guild data, legacy
        sources are left in place (rollback-safe), and the adoption flag makes
        repeats no-ops.
        """
        group = self.config.guild(guild)
        if await group.legacy_adopted():
            return

        legacy_channel = await self.config.channel_id()
        legacy_sticky = await self.config.sticky_message_id()
        legacy_cooldown = await self.config.cooldown()

        if await group.channel_id() is None and legacy_channel is not None:
            await group.channel_id.set(legacy_channel)
        if await group.sticky_message_id() is None and legacy_sticky is not None:
            await group.sticky_message_id.set(legacy_sticky)
        current_cooldown = await group.cooldown()
        if legacy_cooldown is not None and legacy_cooldown != 3 and (current_cooldown is None or current_cooldown == 3):
            await group.cooldown.set(legacy_cooldown)

        legacy_users = await self.config.all_users()
        if isinstance(legacy_users, dict):
            for user_id, data in legacy_users.items():
                if not isinstance(data, dict):
                    continue
                member_group = self.config.member_from_ids(guild.id, user_id)
                profile_data = data.get("profile_data")
                if isinstance(profile_data, dict) and profile_data and not await member_group.profile_data():
                    await member_group.profile_data.set(canonicalize_profile_data(profile_data))
                message_id = data.get("message_id")
                if message_id is not None and await member_group.message_id() is None:
                    await member_group.message_id.set(message_id)
                last_delete = data.get("last_delete")
                if last_delete is not None and await member_group.last_delete() is None:
                    await member_group.last_delete.set(last_delete)

        await group.legacy_adopted.set(True)

    async def get_profile_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel_id = await self.config.guild(guild).channel_id()
        channel = self.bot.get_channel(channel_id) if channel_id else None
        return channel if isinstance(channel, discord.TextChannel) else None

    @commands.group()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def profileset(self, ctx: commands.Context):
        """Settings for the profile cog."""
        pass

    @profileset.command(name="channel")
    async def profileset_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel for profiles."""
        assert ctx.guild is not None
        await self._ensure_guild_data(ctx.guild)
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"Profile channel set to {channel.mention}")
        await self._maybe_repost_sticky(ctx.guild, channel)

    @profileset.command(name="fix")
    async def profileset_fix(self, ctx: commands.Context):
        """Force a repost of the sticky message in the profile channel."""
        assert ctx.guild is not None
        await self._ensure_guild_data(ctx.guild)
        channel = await self.get_profile_channel(ctx.guild)
        if not channel:
            return await ctx.send("Profile channel not found.")
        await self._repost_sticky(ctx.guild, channel)
        await ctx.tick()

    async def handle_create_edit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
            return
        member = interaction.user
        guild = interaction.guild
        await self._ensure_guild_data(guild)

        # Check 24h cooldown after deletion
        user_conf = await self.config.member(member).all()
        last_delete = user_conf.get("last_delete")

        if last_delete:
            last_delete_dt = datetime.fromtimestamp(last_delete, UTC)
            now = datetime.now(UTC)
            diff = now - last_delete_dt
            if diff.total_seconds() < 86400 and not await self.bot.is_owner(member):  # 24 hours
                hours_remaining = int((86400 - diff.total_seconds()) / 3600)
                return await interaction.response.send_message(
                    f"You must wait 24 hours after deleting your profile to create a new one. (~{hours_remaining} hours remaining)",
                    ephemeral=True,
                )

        # Legacy `picture` values are read (and later stored) as `picture_url`
        user_data = canonicalize_profile_data(user_conf.get("profile_data") or {})
        view = ProfileBuilderView(member, user_data)

        msg = "Welcome to the Profile Builder! Fill out the fields below. Required fields are marked with *."
        await interaction.response.send_message(msg, view=view, ephemeral=True)

        await view.wait()
        if view.submitted:
            await self.config.member(member).profile_data.set(view.data)
            await self._update_profile_embed(member, view.data)
            await interaction.followup.send("Profile updated successfully!", ephemeral=True)

    async def handle_delete_request(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
            return
        member = interaction.user
        guild = interaction.guild
        await self._ensure_guild_data(guild)

        user_conf = await self.config.member(member).all()
        if not user_conf.get("profile_data"):
            return await interaction.response.send_message("You don't have a profile to delete.", ephemeral=True)

        view = ProfileDeleteConfirmView(member)
        await interaction.response.send_message(
            "Are you sure you want to delete your profile?", view=view, ephemeral=True
        )

        await view.wait()
        if view.value:
            # Delete message
            channel = await self.get_profile_channel(guild)
            if channel and user_conf.get("message_id"):
                try:
                    msg = channel.get_partial_message(user_conf["message_id"])
                    await msg.delete()
                except discord.NotFound:
                    pass
                except Exception as e:
                    log.error(f"Failed to delete profile message for {member.id}: {e}")

            await self.config.member(member).clear()
            await self.config.member(member).last_delete.set(datetime.now(UTC).timestamp())
            await interaction.followup.send("Your profile has been deleted.", ephemeral=True)

    async def _update_profile_embed(self, user: discord.Member, data: ProfileData):
        channel = await self.get_profile_channel(user.guild)
        if not channel:
            return

        embed = discord.Embed(title=data.get("name", user.display_name), color=user.color, timestamp=datetime.now(UTC))
        embed.set_author(name=f"{user.display_name}", icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)

        # Inline fields
        embed.add_field(name="Age", value=data.get("age", "Unknown"), inline=True)
        embed.add_field(name="Location", value=data.get("location", "Unknown"), inline=True)
        embed.add_field(name="Gender", value=data.get("gender", "Unknown"), inline=True)
        embed.add_field(name="Sexuality", value=data.get("sexuality", "Unknown"), inline=True)

        if role := data.get("role"):
            embed.add_field(name="Role", value=role, inline=True)

        # Block fields
        if likes := data.get("likes"):
            embed.add_field(name="Likes", value=likes, inline=False)
        if dislikes := data.get("dislikes"):
            embed.add_field(name="Dislikes", value=dislikes, inline=False)
        if kinks := data.get("kinks"):
            embed.add_field(name="Kinks", value=kinks, inline=False)
        if limits := data.get("limits"):
            embed.add_field(name="Limits", value=limits, inline=False)
        if about_me := data.get("about_me"):
            embed.add_field(name="About Me", value=about_me, inline=False)

        if picture_url := data.get("picture_url"):
            embed.set_image(url=picture_url)

        embed.set_footer(text=f"Profile created by {user.display_name}")

        content = f"{user.mention}"  # User mention as requested

        message_id = await self.config.member(user).message_id()
        if message_id:
            try:
                msg = channel.get_partial_message(message_id)
                await msg.edit(content=content, embed=embed)
                return
            except discord.NotFound:
                pass

        # Create new message if none exists or old one was deleted
        new_msg = await channel.send(content=content, embed=embed)
        await self.config.member(user).message_id.set(new_msg.id)

        # After sending a profile, we might need to repost the sticky
        await self._maybe_repost_sticky(user.guild, channel)

    # Sticky Logic
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        await self._ensure_guild_data(message.guild)
        channel_id = await self.config.guild(message.guild).channel_id()
        if message.channel.id != channel_id:
            return

        if isinstance(message.channel, discord.TextChannel):
            await self._maybe_repost_sticky(message.guild, message.channel, responding_to_message=message)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        await self._ensure_guild_data(guild)
        channel_id = await self.config.guild(guild).channel_id()
        if payload.channel_id != channel_id:
            return

        sticky_id = await self.config.guild(guild).sticky_message_id()
        if payload.message_id == sticky_id:
            channel = self.bot.get_channel(payload.channel_id)
            if isinstance(channel, discord.TextChannel):
                await self._maybe_repost_sticky(guild, channel)

    async def _maybe_repost_sticky(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        responding_to_message: discord.Message | None = None,
    ) -> None:
        cv = self._channel_cvs.setdefault(channel, asyncio.Condition())

        async with cv:
            await cv.wait_for(lambda: channel not in self.locked_channels)

            sticky_id = await self.config.guild(guild).sticky_message_id()
            if sticky_id is None:
                # No sticky exists, send one if this is the right channel
                channel_id = await self.config.guild(guild).channel_id()
                if channel.id != channel_id:
                    return
                await self._do_repost_sticky(guild, channel, cv)
                return

            last_message_created_at = discord.utils.snowflake_time(sticky_id)
            if responding_to_message and (
                responding_to_message.id == sticky_id or responding_to_message.created_at < last_message_created_at
            ):
                return

            # Cooldown check
            utcnow = datetime.now(UTC)
            # Since we don't have the last message object easily available with timestamp
            # without fetching, we'll fetch it if needed or just use a simpler check.
            # But let's try to be accurate.
            try:
                last_msg_timestamp = discord.utils.snowflake_time(sticky_id)
                time_since = utcnow - last_msg_timestamp
                cooldown = await self.config.guild(guild).cooldown()
                time_to_wait = cooldown - time_since.total_seconds()
            except Exception:
                time_to_wait = 0

        if time_to_wait > 0:
            await asyncio.sleep(time_to_wait)

        async with cv:
            await cv.wait_for(lambda: channel not in self.locked_channels)
            # Re-check if still needed
            new_sticky_id = await self.config.guild(guild).sticky_message_id()
            if new_sticky_id != sticky_id:
                return  # Changed during sleep

            # Check if it's already at the bottom
            if channel.last_message_id == sticky_id:
                return

            await self._do_repost_sticky(guild, channel, cv)

    async def _repost_sticky(self, guild: discord.Guild, channel: discord.TextChannel):
        cv = self._channel_cvs.setdefault(channel, asyncio.Condition())
        async with cv:
            await self._do_repost_sticky(guild, channel, cv)

    async def _do_repost_sticky(self, guild: discord.Guild, channel: discord.TextChannel, cv: asyncio.Condition):
        self.locked_channels.add(channel)
        try:
            # Re-fetch sticky ID after acquiring lock
            old_sticky_id = await self.config.guild(guild).sticky_message_id()

            # Delete old sticky
            if old_sticky_id:
                try:
                    msg = channel.get_partial_message(old_sticky_id)
                    await msg.delete()
                except discord.NotFound:
                    pass
                except Exception as e:
                    log.error(f"Failed to delete old sticky: {e}")

            # Send new sticky
            view = ProfileStickyView(self)
            embed = discord.Embed(
                title="User Profiles",
                description="Click the buttons below to create, edit, or delete your profile in this channel.",
                color=discord.Color.blue(),
            )
            new_sticky = await channel.send(embed=embed, view=view)
            await self.config.guild(guild).sticky_message_id.set(new_sticky.id)
        finally:
            self.locked_channels.remove(channel)
            cv.notify_all()
