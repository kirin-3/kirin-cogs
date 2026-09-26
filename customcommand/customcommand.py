import asyncio
import contextlib
import logging
import math
import re
import shutil
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import discord
from redbot.core import Config, commands
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.chat_formatting import box, pagify

log = logging.getLogger("red.kirin_cogs.customcommand")

MESSAGE_LIMIT = 2000
# Attachments are stored on disk and re-uploaded; keep them under the bot's upload limit
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
# Seconds between one member's creations, counted across the commands and the member site
CREATE_COOLDOWN = 5


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
    # Saved attachments live here (set in cog_load), one folder per guild and trigger.
    # A Discord attachment link dies with its message, so the file itself is kept.
    attachments_root: Path | None = None

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
        self._cooldowns: dict[int, float] = {}  # user_id: monotonic time of their last create

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
                        await self._delete_attachment(guild_id, trigger)
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

    def _attachment_dir(self, guild_id: int, trigger: str) -> Path | None:
        if self.attachments_root is None:
            return None
        # Triggers are lowercase letters, digits and spaces, so this name is safe and unique
        return self.attachments_root / str(guild_id) / trigger.replace(" ", "_")

    async def _delete_attachment(self, guild_id: int, trigger: str) -> None:
        folder = self._attachment_dir(guild_id, trigger)
        if folder is not None:
            await asyncio.to_thread(shutil.rmtree, folder, True)

    async def _save_attachment(self, guild_id: int, trigger: str, filename: str, data: bytes) -> None:
        folder = self._attachment_dir(guild_id, trigger)
        if folder is None:
            raise RuntimeError("Attachment storage is not available")

        def write() -> None:
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True)
            (folder / filename).write_bytes(data)

        await asyncio.to_thread(write)

    def _stored_attachment(self, guild_id: int, trigger: str) -> Path | None:
        folder = self._attachment_dir(guild_id, trigger)
        if folder is None or not folder.is_dir():
            return None
        return next((path for path in folder.iterdir() if path.is_file()), None)

    async def cog_load(self):
        """Pre-populate the cache on cog load."""
        self.attachments_root = cog_data_path(self) / "attachments"
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

    async def log_action(
        self,
        guild: discord.Guild,
        author: discord.abc.User,
        action: str,
        trigger: str,
        response: str | None = None,
        source: str = "command",
    ):
        """Log custom command actions to the hardcoded channel."""
        channel = self.bot.get_channel(self.LOG_CHANNEL_ID)
        if not channel:
            return

        embed = discord.Embed(
            title=f"Custom Command {action}",
            color=discord.Color.green() if action == "Created" else discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=f"{author} ({author.id})", icon_url=author.avatar.url if author.avatar else None)
        embed.add_field(name="Trigger", value=trigger, inline=True)
        if response:
            if len(response) > 1024:
                response = response[:1021] + "..."
            embed.add_field(name="Response", value=response, inline=False)
        if source == "web":
            embed.set_footer(text="Made on the member site")

        with contextlib.suppress(discord.HTTPException):
            await channel.send(embed=embed)

    # --- Shared rules, used by the commands and the member site ---

    def _cooldown(self, user_id: int, *, stamp: bool) -> None:
        """Refuse within CREATE_COOLDOWN of the member's last create; stamp now when asked.

        Synchronous, so a check-and-stamp can't interleave with another create.
        """
        now = time.monotonic()
        last = self._cooldowns.get(user_id)
        if last is not None and now - last < CREATE_COOLDOWN:
            wait = math.ceil(CREATE_COOLDOWN - (now - last))
            raise ValueError(f"You're creating commands too fast. Try again in {wait} second(s).")
        if stamp:
            self._cooldowns = {uid: t for uid, t in self._cooldowns.items() if now - t < CREATE_COOLDOWN}
            self._cooldowns[user_id] = now

    def can_create(self, member: discord.Member) -> bool:
        """Only active supporters create commands; anyone can delete their own."""
        return any(role.id == self.role_id for role in member.roles)

    def _check_create(self, member: discord.Member, trigger: str, response: str, has_attachment: bool) -> None:
        if not self.can_create(member):
            raise ValueError("You don't have the required role to create a custom command.")
        if not response and not has_attachment:
            raise ValueError("Please provide a response or attach an image.")
        if len(response) > MESSAGE_LIMIT:
            raise ValueError(
                f"Responses can be at most {MESSAGE_LIMIT} characters (yours is {len(response)}), "
                "because that's the most the bot can send in one message."
            )
        # Prevent bot triggers
        if response.strip().startswith((".", "-", "&")):
            raise ValueError("Responses cannot start with '.', '-', or '&' to prevent bot conflicts.")
        if not trigger.replace(" ", "").isalnum():
            raise ValueError("Trigger must be alphanumeric (spaces are allowed).")
        if self.bot.get_command(trigger.lower()):
            raise ValueError("A command with this name already exists.")
        self._cooldown(member.id, stamp=False)

    @staticmethod
    def _owned(owners: dict, user_id: int | str) -> list[str]:
        owned = owners.get(str(user_id)) or []
        # Legacy records stored a single trigger as a string
        return [owned] if isinstance(owned, str) else [t for t in owned if isinstance(t, str)]

    async def limit_for(self, member: discord.Member) -> int:
        limits = await self.config.guild(member.guild).user_limits()
        return limits.get(str(member.id), 1) if isinstance(limits, dict) else 1

    async def commands_for(self, member: discord.Member) -> list[dict]:
        """The member's commands as trigger, response and attachment filename (or None)."""
        guild = member.guild
        owners = await self.config.guild(guild).command_owners()
        responses = await self.config.guild(guild).commands()
        result = []
        for trigger in self._owned(owners, member.id):
            stored = self._stored_attachment(guild.id, trigger)
            result.append(
                {
                    "trigger": trigger,
                    "response": responses.get(trigger, ""),
                    "attachment": stored.name if stored is not None else None,
                }
            )
        return result

    async def create_command(
        self,
        member: discord.Member,
        trigger: str,
        response: str,
        attachment: tuple[str, bytes] | None,
        *,
        source: str,
    ) -> None:
        """Create a command for the member, or raise ValueError with the reason.

        `attachment` is (filename, data). The file itself is saved: a Discord
        link stops working once its message is deleted.
        """
        guild = member.guild
        self._check_create(member, trigger, response, attachment is not None)
        if attachment is not None and len(attachment[1]) > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"Attachments can be at most {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB.")
        self._cooldown(member.id, stamp=True)
        trigger = trigger.lower()
        if attachment is not None:
            name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(attachment[0]).name).lstrip(".") or "attachment"
            attachment = (name, attachment[1])

        is_owner = await self.bot.is_owner(member)

        # Serialize validation and persistence within the guild so command
        # limits, command content, and owner records change as one logical
        # operation: a single read-modify-write under the per-guild lock.
        async with self._guild_lock(guild.id):
            guild_group = self.config.guild(guild)
            guild_data = await guild_group.all()

            commands_map = dict(guild_data.get("commands") or {})
            owners_map = dict(guild_data.get("command_owners") or {})
            limits_map = guild_data.get("user_limits") or {}

            limit = limits_map.get(str(member.id), 1)
            user_commands = self._owned(owners_map, member.id)

            if len(user_commands) >= limit and not is_owner:
                raise ValueError(f"You have reached your limit of {limit} custom command(s).")
            if trigger in commands_map:
                raise ValueError("A custom command with this trigger already exists.")

            commands_map[trigger] = response
            owners_map[str(member.id)] = [*user_commands, trigger]

            guild_data["commands"] = commands_map
            guild_data["command_owners"] = owners_map
            try:
                if attachment is not None:
                    await self._save_attachment(guild.id, trigger, *attachment)
                else:
                    await self._delete_attachment(guild.id, trigger)
                await guild_group.set(guild_data)
            except Exception:
                await self._delete_attachment(guild.id, trigger)
                raise

        # Update cache
        self.command_cache.setdefault(guild.id, {})[trigger] = response

        log_response = response
        if attachment is not None:
            log_response = f"{response}\n[Attachment: {attachment[0]}]".strip()
        await self.log_action(guild, member, "Created", trigger, log_response, source)

    async def _remove(self, guild: discord.Guild, trigger: str, owner_key: str | None, owned: list[str]) -> None:
        """Remove a command, its file, its cooldown and its owner record. Call under the guild lock."""
        async with self.config.guild(guild).commands() as commands:
            commands.pop(trigger, None)
        self.command_cache.get(guild.id, {}).pop(trigger, None)
        self.trigger_cooldowns.pop((guild.id, trigger), None)
        await self._delete_attachment(guild.id, trigger)
        if owner_key is not None:
            remaining = [t for t in owned if t != trigger]
            owners = self.config.guild(guild).command_owners
            if remaining:
                await owners.set_raw(owner_key, value=remaining)  # pyright: ignore[reportAttributeAccessIssue]
            else:
                await owners.clear_raw(owner_key)  # pyright: ignore[reportAttributeAccessIssue]

    async def delete_command(self, member: discord.Member, trigger: str, *, source: str) -> None:
        """Delete one of the member's own commands, or raise ValueError."""
        guild = member.guild
        trigger = trigger.lower()
        # Same lock as creation: both rewrite the guild's commands and owner records.
        async with self._guild_lock(guild.id):
            owned = self._owned(await self.config.guild(guild).command_owners(), member.id)
            if not owned:
                raise ValueError("You don't have a custom command to delete.")
            if trigger not in owned:
                raise ValueError("You don't own a command with that name.")
            await self._remove(guild, trigger, str(member.id), owned)
        await self.log_action(guild, member, "Deleted", trigger, source=source)

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
        async with self._guild_lock(ctx.guild.id):  # creation rewrites the whole guild record
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
                if self._stored_attachment(ctx.guild.id, trigger) is not None:
                    response = f"{response}\n[Attachment]".strip()
                text += f"Trigger: {trigger}\nOwner: {username}\nResponse: {response}\n\n"

        if not text:
            await ctx.send("No commands to list.")
            return

        pages = list(pagify(text))
        for page in pages:
            await ctx.send(box(page))

    @customcommand.command(name="create")
    async def customcommand_create(self, ctx, trigger: str, response: str | None = None):
        """
        Create a custom command.

        The trigger must be alphanumeric (spaces allowed) and not conflict with existing commands.
        To use multi-word triggers or responses, wrap them in quotes.
        You can also attach an image to this command.
        Example: `[p]cc create "hello world" "Hello there!"`
        """
        response = response or ""
        attachments = ctx.message.attachments
        try:
            # Checked before downloading too, so a refusal costs no download
            self._check_create(ctx.author, trigger, response, bool(attachments))
            attachment_file: tuple[str, bytes] | None = None
            if attachments:
                attachment = attachments[0]
                if attachment.size > MAX_ATTACHMENT_BYTES:
                    raise ValueError(f"Attachments can be at most {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB.")
                try:
                    attachment_file = (attachment.filename, await attachment.read())
                except discord.HTTPException:
                    log.exception("Could not download a custom command attachment")
                    raise ValueError("I couldn't download that attachment. Please try again.") from None
            await self.create_command(ctx.author, trigger, response, attachment_file, source="command")
        except ValueError as e:
            await ctx.send(str(e))
            return
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

        if author.guild_permissions.ban_members and trigger:
            trigger = trigger.lower()
            async with self._guild_lock(guild.id):
                if trigger not in self.command_cache.get(guild.id, {}):
                    await ctx.send("Command not found.")
                    return
                command_owners = await self.config.guild(guild).command_owners()
                owner_key = next((uid for uid in command_owners if trigger in self._owned(command_owners, uid)), None)
                owned = self._owned(command_owners, owner_key) if owner_key is not None else []
                await self._remove(guild, trigger, owner_key, owned)
            await self.log_action(guild, author, "Deleted (Mod)", trigger)
            await ctx.send(f"Custom command `{trigger}` has been deleted by moderator.")
            return

        if trigger is None:
            owned = self._owned(await self.config.guild(guild).command_owners(), author.id)
            if len(owned) > 1:
                cmd_list = ", ".join(f"`{c}`" for c in owned)
                await ctx.send(f"You have multiple commands: {cmd_list}. Please specify which one to delete.")
                return
            trigger = owned[0] if owned else ""
        try:
            await self.delete_command(author, trigger, source="command")
        except ValueError as e:
            await ctx.send(str(e))
            return
        await ctx.send(f"Your custom command `{trigger.lower()}` has been deleted.")

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
            no_pings = discord.AllowedMentions.none()
            # Responses saved before the length check could exceed one message; send those in parts
            parts = list(pagify(response, page_length=MESSAGE_LIMIT)) if len(response) > MESSAGE_LIMIT else [response]
            stored = self._stored_attachment(message.guild.id, trigger)
            for part in parts[:-1]:
                await message.channel.send(part, allowed_mentions=no_pings)
            if stored is not None:
                await message.channel.send(parts[-1] or None, file=discord.File(stored), allowed_mentions=no_pings)
            else:
                await message.channel.send(parts[-1], allowed_mentions=no_pings)


async def setup(bot):
    await bot.add_cog(CustomCommand(bot))
