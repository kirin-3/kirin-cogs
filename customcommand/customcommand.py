from redbot.core import commands, Config
import discord

class CustomCommand(commands.Cog):
    """
    Allows users with a specific role to create custom commands.
    """

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
        self._cooldown = commands.CooldownMapping.from_cooldown(1, 60, commands.BucketType.user)

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

    @customcommand.command(name="create")
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def customcommand_create(self, ctx, trigger: str, response: str):
        """
        Create a custom command.

        The trigger must be a single word and not conflict with existing commands.
        To use multi-word triggers or responses, wrap them in quotes.
        Example: `[p]cc create "hello world" "Hello there!"`
        """
        author = ctx.author
        guild = ctx.guild

        if not any(role.id == self.role_id for role in author.roles):
            await ctx.send("You don't have the required role to create a custom command.")
            return

        # Check limit
        limits = await self.config.guild(guild).user_limits()
        limit = limits.get(str(author.id), 1)

        command_owners = await self.config.guild(guild).command_owners()
        user_commands = command_owners.get(str(author.id), [])

        # Migration: handle if stored as string (legacy)
        if isinstance(user_commands, str):
            user_commands = [user_commands]

        if len(user_commands) >= limit:
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

        await ctx.send(f"Custom command `{trigger}` has been created.")

    @customcommand.command(name="delete")
    async def customcommand_delete(self, ctx, trigger: str = None):
        """Delete your custom command."""
        author = ctx.author
        guild = ctx.guild

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
