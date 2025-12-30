from redbot.core import commands, Config
import discord
from typing import Optional
from redbot.core.utils.chat_formatting import pagify, box

class CustomCommand(commands.Cog):
    """
    Allows users with a specific role to create custom commands.
    """

    LOG_CHANNEL_ID = 757582829571014737

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567891, force_registration=True)
        default_guild = {
            "commands": {},
            "command_owners": {},
            "user_limits": {}
        }
        self.config.register_guild(**default_guild)
        self.role_id = 700121551483437128
        self._cooldown = commands.CooldownMapping.from_cooldown(1, 10, commands.BucketType.user)

    async def log_action(self, ctx, action: str, trigger: str, response: str = None):
        """Log custom command actions to the hardcoded channel."""
        channel = self.bot.get_channel(self.LOG_CHANNEL_ID)
        if not channel:
            return

        embed = discord.Embed(
            title=f"Custom Command {action}",
            color=discord.Color.green() if action == "Created" else discord.Color.red(),
            timestamp=ctx.message.created_at
        )
        embed.set_author(name=f"{ctx.author} ({ctx.author.id})", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        embed.add_field(name="Trigger", value=trigger, inline=True)
        if response:
            if len(response) > 1024:
                response = response[:1021] + "..."
            embed.add_field(name="Response", value=response, inline=False)
        
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass # Fail silently if permission error or other issue

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
        await self.config.guild(ctx.guild).user_limits.set_raw(str(member.id), value=limit)
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
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def customcommand_create(self, ctx, trigger: str, response: Optional[str] = None):
        """
        Create a custom command.

        The trigger must be a single word and not conflict with existing commands.
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
        if response.strip().startswith(('.', '-', '&')):
            await ctx.send("Responses cannot start with '.', '-', or '&' to prevent bot conflicts.")
            return

        # Check limit
        limits = await self.config.guild(guild).user_limits()
        limit = limits.get(str(author.id), 1)

        command_owners = await self.config.guild(guild).command_owners()
        user_commands = command_owners.get(str(author.id), [])

        # Migration: handle if stored as string (legacy)
        if isinstance(user_commands, str):
            user_commands = [user_commands]

        if len(user_commands) >= limit and not await self.bot.is_owner(author):
            await ctx.send(f"You have reached your limit of {limit} custom command(s).")
            return

        if self.bot.get_command(trigger.lower()):
            await ctx.send("A command with this name already exists.")
            return
            
        all_commands = await self.config.guild(guild).commands()
        if trigger.lower() in all_commands:
            await ctx.send("A custom command with this trigger already exists.")
            return

        # Save new command
        await self.config.guild(guild).commands.set_raw(trigger.lower(), value=response)
        
        # Update owner list
        user_commands.append(trigger.lower())
        await self.config.guild(guild).command_owners.set_raw(str(author.id), value=user_commands)

        await self.log_action(ctx, "Created", trigger.lower(), response)
        await ctx.send(f"Custom command `{trigger}` has been created.")

    @customcommand.command(name="delete")
    async def customcommand_delete(self, ctx, trigger: str = None):
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
            all_commands = await self.config.guild(guild).commands()
            
            if trigger in all_commands:
                # Find owner to clean up
                command_owners = await self.config.guild(guild).command_owners()
                owner_found = None
                
                for user_id, triggers in command_owners.items():
                    if isinstance(triggers, str): triggers = [triggers]
                    if trigger in triggers:
                        owner_found = user_id
                        break
                
                # Delete
                await self.config.guild(guild).commands.clear_raw(trigger)
                
                if owner_found:
                    triggers = command_owners[owner_found]
                    if isinstance(triggers, str): triggers = [triggers]
                    if trigger in triggers:
                        triggers.remove(trigger)
                        if not triggers:
                            await self.config.guild(guild).command_owners.clear_raw(owner_found)
                        else:
                            await self.config.guild(guild).command_owners.set_raw(owner_found, value=triggers)
                
                await self.log_action(ctx, "Deleted (Mod)", trigger)
                await ctx.send(f"Custom command `{trigger}` has been deleted by moderator.")
                return
            # If trigger provided but not found, check if it's user's own command (fall through)
            # Actually, if it's not in all_commands, it doesn't exist at all.
            elif trigger not in all_commands:
                 await ctx.send("Command not found.")
                 return

        # Regular user logic (or mod deleting own without args)
        command_owners = await self.config.guild(guild).command_owners()
        user_commands = command_owners.get(str(author.id))

        if not user_commands:
            await ctx.send("You don't have a custom command to delete.")
            return

        # Migration: handle if stored as string (legacy)
        if isinstance(user_commands, str):
            user_commands = [user_commands]

        if trigger is None:
            if len(user_commands) == 1:
                trigger = user_commands[0]
            else:
                cmd_list = ", ".join(f"`{c}`" for c in user_commands)
                await ctx.send(f"You have multiple commands: {cmd_list}. Please specify which one to delete.")
                return

        trigger = trigger.lower()
        if trigger not in user_commands:
            await ctx.send("You don't own a command with that name.")
            return

        # Delete
        await self.config.guild(guild).commands.clear_raw(trigger)
        
        user_commands.remove(trigger)
        if not user_commands:
            await self.config.guild(guild).command_owners.clear_raw(str(author.id))
        else:
            await self.config.guild(guild).command_owners.set_raw(str(author.id), value=user_commands)

        await self.log_action(ctx, "Deleted", trigger)
        await ctx.send(f"Your custom command `{trigger}` has been deleted.")

    @commands.Cog.listener()
    async def on_message_without_command(self, message: discord.Message):
        """
        Listens for messages to check for custom command triggers.
        This will not trigger if the message is a valid command.
        """
        if message.author.bot or not message.guild:
            return

        # This is necessary to check for custom command triggers on every message.
        # It's designed to be as efficient as possible by only reading from config.
        all_commands = await self.config.guild(message.guild).commands()
        trigger = message.content.strip().lower()

        if trigger in all_commands:
            bucket = self._cooldown.get_bucket(message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                return
            response = all_commands[trigger]
            await message.channel.send(response)

async def setup(bot):
    await bot.add_cog(CustomCommand(bot))
