import asyncio
import contextlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, cast

import discord
from redbot.core import Config, commands, checks
from redbot.core.bot import Red

from .models import PROFILE_CHANNEL_ID, UNIQUE_ID, QUESTIONS, ProfileData
from .views import ProfileStickyView, ProfileBuilderView, ProfileDeleteConfirmView

log = logging.getLogger("red.profile")

class Profile(commands.Cog):
    """Create and manage user profiles in a specific channel."""

    def __init__(self, bot: Red):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=UNIQUE_ID, force_registration=True)
        
        default_global = {
            "channel_id": PROFILE_CHANNEL_ID,
            "sticky_message_id": None,
            "sticky_locked": False
        }
        default_user = {
            "profile_data": {},
            "message_id": None
        }
        
        self.config.register_global(**default_global)
        self.config.register_user(**default_user)
        
        self._sticky_lock = asyncio.Lock()
        self.bot.add_view(ProfileStickyView(self))

    async def cog_load(self):
        # We don't necessarily need to repost on load, 
        # but we should ensure the view is active.
        pass

    async def get_profile_channel(self) -> Optional[discord.TextChannel]:
        channel_id = await self.config.channel_id()
        return self.bot.get_channel(channel_id)

    @commands.group()
    @checks.admin_or_permissions(manage_guild=True)
    async def profileset(self, ctx: commands.Context):
        """Settings for the profile cog."""
        pass

    @profileset.command(name="channel")
    async def profileset_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel for profiles."""
        await self.config.channel_id.set(channel.id)
        await ctx.send(f"Profile channel set to {channel.mention}")
        await self._maybe_repost_sticky(channel)

    @profileset.command(name="fix")
    async def profileset_fix(self, ctx: commands.Context):
        """Force a repost of the sticky message in the profile channel."""
        channel = await self.get_profile_channel()
        if not channel:
            return await ctx.send("Profile channel not found.")
        await self._repost_sticky(channel)
        await ctx.tick()

    async def handle_create_edit(self, interaction: discord.Interaction):
        user_data = await self.config.user(interaction.user).profile_data()
        view = ProfileBuilderView(interaction.user, user_data)
        
        msg = "Welcome to the Profile Builder! Fill out the fields below. Required fields are marked with *."
        await interaction.response.send_message(msg, view=view, ephemeral=True)
        
        await view.wait()
        if view.submitted:
            await self.config.user(interaction.user).profile_data.set(view.data)
            await self._update_profile_embed(interaction.user, view.data)
            await interaction.followup.send("Profile updated successfully!", ephemeral=True)

    async def handle_delete_request(self, interaction: discord.Interaction):
        user_conf = await self.config.user(interaction.user).all()
        if not user_conf["profile_data"]:
            return await interaction.response.send_message("You don't have a profile to delete.", ephemeral=True)
        
        view = ProfileDeleteConfirmView(interaction.user)
        await interaction.response.send_message("Are you sure you want to delete your profile?", view=view, ephemeral=True)
        
        await view.wait()
        if view.value:
            # Delete message
            channel = await self.get_profile_channel()
            if channel and user_conf["message_id"]:
                try:
                    msg = channel.get_partial_message(user_conf["message_id"])
                    await msg.delete()
                except discord.NotFound:
                    pass
                except Exception as e:
                    log.error(f"Failed to delete profile message for {interaction.user.id}: {e}")
            
            await self.config.user(interaction.user).clear()
            await interaction.followup.send("Your profile has been deleted.", ephemeral=True)

    async def _update_profile_embed(self, user: discord.Member, data: ProfileData):
        channel = await self.get_profile_channel()
        if not channel:
            return

        embed = discord.Embed(
            title=data.get("name", user.display_name),
            color=user.color,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=f"{user}", icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        # Inline fields
        embed.add_field(name="Age", value=data.get("age", "Unknown"), inline=True)
        embed.add_field(name="Location", value=data.get("location", "Unknown"), inline=True)
        embed.add_field(name="Gender", value=data.get("gender", "Unknown"), inline=True)
        embed.add_field(name="Sexuality", value=data.get("sexuality", "Unknown"), inline=True)
        
        if data.get("role"):
            embed.add_field(name="Role", value=data["role"], inline=True)
            
        # Block fields
        if data.get("likes"):
            embed.add_field(name="Likes", value=data["likes"], inline=False)
        if data.get("dislikes"):
            embed.add_field(name="Dislikes", value=data["dislikes"], inline=False)
        if data.get("kinks"):
            embed.add_field(name="Kinks", value=data["kinks"], inline=False)
        if data.get("limits"):
            embed.add_field(name="Limits", value=data["limits"], inline=False)
        if data.get("about_me"):
            embed.add_field(name="About Me", value=data["about_me"], inline=False)
            
        if data.get("picture_url"):
            embed.set_image(url=data["picture_url"])
        elif data.get("picture"): # In case field name is "picture" in data
             embed.set_image(url=data["picture"])

        embed.set_footer(text=f"Profile created by {user.name}")

        content = f"{user.mention}" # User mention as requested

        message_id = await self.config.user(user).message_id()
        if message_id:
            try:
                msg = channel.get_partial_message(message_id)
                await msg.edit(content=content, embed=embed)
                return
            except discord.NotFound:
                pass
        
        # Create new message if none exists or old one was deleted
        new_msg = await channel.send(content=content, embed=embed)
        await self.config.user(user).message_id.set(new_msg.id)
        
        # After sending a profile, we might need to repost the sticky
        await self._maybe_repost_sticky(channel)

    # Sticky Logic
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        channel_id = await self.config.channel_id()
        if message.channel.id != channel_id:
            return
        
        await self._maybe_repost_sticky(message.channel)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        channel_id = await self.config.channel_id()
        if payload.channel_id != channel_id:
            return
        
        sticky_id = await self.config.sticky_message_id()
        if payload.message_id == sticky_id:
            channel = self.bot.get_channel(payload.channel_id)
            if channel:
                await self._repost_sticky(channel)

    async def _maybe_repost_sticky(self, channel: discord.TextChannel):
        sticky_id = await self.config.sticky_message_id()
        
        # Check if the sticky is already at the bottom
        if sticky_id:
            # We check the last message ID. If it's the sticky, we do nothing.
            if channel.last_message_id == sticky_id:
                return

        await self._repost_sticky(channel)

    async def _repost_sticky(self, channel: discord.TextChannel):
        async with self._sticky_lock:
            # Re-fetch sticky ID after acquiring lock
            old_sticky_id = await self.config.sticky_message_id()
            
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
                color=discord.Color.blue()
            )
            new_sticky = await channel.send(embed=embed, view=view)
            await self.config.sticky_message_id.set(new_sticky.id)
