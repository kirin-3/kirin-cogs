import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import discord
from redbot.core import Config, commands
from redbot.core.utils.chat_formatting import box, pagify


@dataclass
class _LockEntry:
    """A keyed asyncio lock plus the number of coroutines holding or awaiting it."""

    lock: asyncio.Lock
    holders: int = 0


class CustomCommand(commands.Cog):
    """
    Allows users with a specific role to create custom commands.
    """

    LOG_CHANNEL_ID = 757582829571014737

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567891, force_registration=True)
        default_guild = {"commands": {}, "command_owners": {}, "user_limits": {}}
        self.config.register_guild(**default_guild)
        self.role_id = 700121551483437128
        self.trigger_cooldowns = {}  # (guild_id, trigger): CooldownMapping
        self.command_cache = {}  # guild_id: {trigger: response}
        # Per-guild creation locks; idle entries are removed.
        self._guild_locks: dict[int, _LockEntry] = {}

    async def red_delete_data_for_user(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, *, requester, user_id: int
    ) -> None:
        """Delete limits and custom commands owned by a Discord user ID."""
        user_key = str(user_id)
        for guild_id, data in (await self.config.all_guilds()).items():
            if not isinstance(data, dict):
                continue
            async with self._guild_lock(guild_id):
                group = self.config.guild_from_id(guild_id)
                current = await group.all()
                if not isinstance(current, dict):
                    continue
                owners = current.get("command_owners", {})
                commands_data = current.get("commands", {})
                limits = current.get("user_limits", {})
                owners = dict(owners) if isinstance(owners, dict) else {}
                commands_data = dict(commands_data) if isinstance(commands_data, dict) else {}
                limits = dict(limits) if isinstance(limits, dict) else {}

                raw_owned = owners.pop(user_key, owners.pop(user_id, []))
                owned = raw_owned if isinstance(raw_owned, list) else []
                for trigger in owned:
                    if isinstance(trigger, str):
                        commands_data.pop(trigger, None)
                limits.pop(user_key, None)
                limits.pop(user_id, None)
                current["command_owners"] = owners
                current["commands"] = commands_data
                current["user_limits"] = limits
                await group.set(current)
                self.command_cache[guild_id] = commands_data

    @asynccontextmanager
    async def _guild_lock(self, guild_id: int) -> AsyncGenerator[asyncio.Lock, None]:
        """Serialize command creation within one guild.

        Registry entries are removed once no coroutine holds or awaits them,
        so the registry cannot grow unboundedly.
        """
        entry = self._guild_locks.get(guild_id)
        if entry is None:
            entry = _LockEntry(asyncio.Lock())
            self._guild_locks[guild_id] = entry
        entry.holders += 1
        try:
            async with entry.lock:
                yield entry.lock
        finally:
            entry.holders -= 1
            if entry.holders == 0 and self._guild_locks.get(guild_id) is entry:
                del self._guild_locks[guild_id]

    async def cog_load(self):
        """Pre-populate the cache on cog load."""
        all_guilds_data = await self.config.all_guilds()
        for guild_id, guild_data in all_guilds_data.items():
            self.command_cache[guild_id] = guild_data.get("commands", {})

    async def cog_unload(self) -> None:
        """Clear cache on cog unload."""
        self.command_cache.clear()
        self.trigger_cooldowns.clear()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """Clear cache on guild remove."""
        if guild.id in self.command_cache:
            del self.command_cache[guild.id]

        # Clear cooldowns for this guild
        keys_to_remove = [k for k in self.trigger_cooldowns if k[0] == guild.id]
        for k in keys_to_remove:
            del self.trigger_cooldowns[k]

    async def log_action(self, ctx, action: str, trigger: str, response: str | None = None):
        """Log custom command actions to the hardcoded channel."""
        channel = self.bot.get_channel(self.LOG_CHANNEL_ID)
        if not channel:
            return

        embed = discord.Embed(
            title=f"Custom Command {action}",
            color=discord.Color.green() if action == "Created" else discord.Color.red(),
            timestamp=ctx.message.created_at,
        )
        embed.set_author(
            name=f"{ctx.author} ({ctx.author.id})", icon_url=ctx.author.avatar.url if ctx.author.avatar else None
        )
        embed.add_field(name="Trigger", value=trigger, inline=True)
        if response:
            if len(response) > 1024:
                response = response[:1021] + "..."
            embed.add_field(name="Response", value=response, inline=False)

        with contextlib.suppress(discord.HTTPException):
            await channel.send(embed=embed)

    @commands.group(aliases=["cc"])
    @commands.guild_only()
    async def customcommand(self, ctx):
        """Base command for custom commands."""
        pass

    @customcommand.command(name="limit")
    @commands.has_permissions(administrator=True)
    async def customcommand_limit(self, ctx, member: discord.Member, limit: int):
        """Set the custom command limit for a specific user."""
        if limit < 1:
            await ctx.send("Limit must be at least 1.")
            return
        await self.config.guild(ctx.guild).user_limits.set_raw(str(member.id), value=limit)  # pyright: ignore[reportAttributeAccessIssue]
        await ctx.send(f"Custom command limit for {member.display_name} set to {limit}.")

    @customcommand.command(name="list")
    async def customcommand_list(self, ctx):
        """
        List custom commands.

        If you are a moderator, lists all commands.
        Otherwise, lists only your commands.
        """
        command_owners = await self.config.guild(ctx.guild).command_owners()
        all_commands = await self.config.guild(ctx.guild).commands()

        if not command_owners:
            await ctx.send("No custom commands found.")
            return

        is_mod = ctx.author.guild_permissions.ban_members

        if not is_mod:
            user_id = str(ctx.author.id)
            if user_id in command_owners:
                command_owners = {user_id: command_owners[user_id]}
            else:
                await ctx.send("You don't have any custom commands.")
                return

        text = ""
        for user_id, triggers in command_owners.items():
            user = ctx.guild.get_member(int(user_id))
            username = str(user) if user else f"User ID: {user_id}"

            if isinstance(triggers, str):
                triggers = [triggers]

            for trigger in triggers:
                response = all_commands.get(trigger, "Response not found (Error)")
                text += f"Trigger: {trigger}\nOwner: {username}\nResponse: {response}\n\n"

        if not text:
            await ctx.send("No commands to list.")
            return

        pages = list(pagify(text))
        for page in pages:
            await ctx.send(box(page))

    @customcommand.command(name="create")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def customcommand_create(self, ctx, trigger: str, response: str | None = None):
        """
        Create a custom command.

        The trigger must be alphanumeric (spaces allowed) and not conflict with existing commands.
        To use multi-word triggers or responses, wrap them in quotes.
        You can also attach an image to this command.
        Example: `[p]cc create "hello world" "Hello there!"`
        """
        author = ctx.author
        guild = ctx.guild

        if not any(role.id == self.role_id for role in author.roles):
            await ctx.send("You don't have the required role to create a custom command.")
            return

        # Handle attachments
        if ctx.message.attachments:
            attachment_url = ctx.message.attachments[0].url
            if response:
                response = f"{response}\n{attachment_url}"
            else:
                response = attachment_url

        if not response:
            await ctx.send("Please provide a response or attach an image.")
            return

        # Prevent bot triggers
        if response.strip().startswith((".", "-", "&")):
            await ctx.send("Responses cannot start with '.', '-', or '&' to prevent bot conflicts.")
            return

        if not trigger.replace(" ", "").isalnum():
            await ctx.send("Trigger must be alphanumeric (spaces are allowed).")
            return

        if self.bot.get_command(trigger.lower()):
            await ctx.send("A command with this name already exists.")
            return

        is_owner = await self.bot.is_owner(author)

        # Serialize validation and persistence within the guild so command
        # limits, command content, and owner records change as one logical
        # operation: a single read-modify-write under the per-guild lock.
        async with self._guild_lock(guild.id):
            guild_group = self.config.guild(guild)
            guild_data = await guild_group.all()

            commands_map = dict(guild_data.get("commands") or {})
            owners_map = dict(guild_data.get("command_owners") or {})
            limits_map = guild_data.get("user_limits") or {}

            limit = limits_map.get(str(author.id), 1)
            user_commands = owners_map.get(str(author.id), [])

            # Migration: handle if stored as string (legacy)
            if isinstance(user_commands, str):
                user_commands = [user_commands]

            if len(user_commands) >= limit and not is_owner:
                await ctx.send(f"You have reached your limit of {limit} custom command(s).")
                return

            if trigger.lower() in commands_map:
                await ctx.send("A custom command with this trigger already exists.")
                return

            commands_map[trigger.lower()] = response
            owners_map[str(author.id)] = [*user_commands, trigger.lower()]

            guild_data["commands"] = commands_map
            guild_data["command_owners"] = owners_map
            await guild_group.set(guild_data)

        # Update cache
        self.command_cache.setdefault(guild.id, {})[trigger.lower()] = response

        await self.log_action(ctx, "Created", trigger.lower(), response)
        await ctx.send(f"Custom command `{trigger}` has been created.")

    @customcommand.command(name="delete")
    async def customcommand_delete(self, ctx, trigger: str | None = None):
        """
        Delete a custom command.

        If you have ban permissions, you can delete any command.
        Otherwise, you can only delete your own commands.
        """
        author = ctx.author
        guild = ctx.guild
        is_mod = author.guild_permissions.ban_members

        # Mod deletion logic
        if is_mod and trigger:
            trigger = trigger.lower()
            all_commands = self.command_cache.get(guild.id, {})

            if trigger in all_commands:
                # Find owner to clean up
                command_owners = await self.config.guild(guild).command_owners()
                owner_found = None

                for user_id, triggers in command_owners.items():
                    if isinstance(triggers, str):
                        triggers = [triggers]
                    if trigger in triggers:
                        owner_found = user_id
                        break

                # Delete from config
                async with self.config.guild(guild).commands() as commands:
                    if trigger in commands:
                        del commands[trigger]

                # Delete from cache
                if guild.id in self.command_cache and trigger in self.command_cache[guild.id]:
                    del self.command_cache[guild.id][trigger]

                # Cleanup cooldown
                if (guild.id, trigger) in self.trigger_cooldowns:
                    del self.trigger_cooldowns[(guild.id, trigger)]

                if owner_found:
                    triggers = command_owners[owner_found]
                    if isinstance(triggers, str):
                        triggers = [triggers]
                    if trigger in triggers:
                        triggers.remove(trigger)
                        if not triggers:
                            await self.config.guild(guild).command_owners.clear_raw(owner_found)  # pyright: ignore[reportAttributeAccessIssue]
                        else:
                            await self.config.guild(guild).command_owners.set_raw(owner_found, value=triggers)  # pyright: ignore[reportAttributeAccessIssue]

                await self.log_action(ctx, "Deleted (Mod)", trigger)
                await ctx.send(f"Custom command `{trigger}` has been deleted by moderator.")
                return
            elif trigger not in all_commands:
                await ctx.send("Command not found.")
                return

        # Regular user logic
        command_owners = await self.config.guild(guild).command_owners()
        user_commands = command_owners.get(str(author.id))

        if not user_commands:
            await ctx.send("You don't have a custom command to delete.")
            return

        if isinstance(user_commands, str):
            user_commands = [user_commands]

        if trigger is None:
            if len(user_commands) == 1:
                trigger = user_commands[0]
            else:
                cmd_list = ", ".join(f"`{c}`" for c in user_commands)
                await ctx.send(f"You have multiple commands: {cmd_list}. Please specify which one to delete.")
                return

        assert trigger is not None
        trigger = trigger.lower()
        if trigger not in user_commands:
            await ctx.send("You don't own a command with that name.")
            return

        # Delete from config and cache
        async with self.config.guild(guild).commands() as commands:
            if trigger in commands:
                del commands[trigger]
        if guild.id in self.command_cache and trigger in self.command_cache[guild.id]:
            del self.command_cache[guild.id][trigger]

        # Cleanup cooldown
        if (guild.id, trigger) in self.trigger_cooldowns:
            del self.trigger_cooldowns[(guild.id, trigger)]

        user_commands.remove(trigger)
        if not user_commands:
            await self.config.guild(guild).command_owners.clear_raw(str(author.id))  # pyright: ignore[reportAttributeAccessIssue]
        else:
            await self.config.guild(guild).command_owners.set_raw(str(author.id), value=user_commands)  # pyright: ignore[reportAttributeAccessIssue]

        await self.log_action(ctx, "Deleted", trigger)
        await ctx.send(f"Your custom command `{trigger}` has been deleted.")

    @commands.Cog.listener()
    async def on_message_without_command(self, message: discord.Message):
        """
        Listens for messages to check for custom command triggers.
        """
        if message.author.bot or not message.guild:
            return

        guild_commands = self.command_cache.get(message.guild.id, {})
        trigger = message.content.strip().lower()

        if trigger in guild_commands:
            cooldown_key = (message.guild.id, trigger)
            if cooldown_key not in self.trigger_cooldowns:
                self.trigger_cooldowns[cooldown_key] = commands.CooldownMapping.from_cooldown(
                    1, 60, commands.BucketType.channel
                )

            bucket = self.trigger_cooldowns[cooldown_key].get_bucket(message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                return
            response = guild_commands[trigger]
            # Stored responses are user-controlled text: never let them ping.
            await message.channel.send(response, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(CustomCommand(bot))
