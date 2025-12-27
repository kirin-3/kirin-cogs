from redbot.core import commands, Config
import discord

class CustomCommand(commands.Cog):
    """
    Allows users with a specific role to create a single custom command.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567891, force_registration=True)
        default_guild = {
            "commands": {},
            "command_owners": {}
        }
        self.config.register_guild(**default_guild)
        self.role_id = 700121551483437128
        self._cooldown = commands.CooldownMapping.from_cooldown(1, 60, commands.BucketType.user)

    @commands.group(aliases=["cc"])
    @commands.guild_only()
    async def customcommand(self, ctx):
        """Base command for custom commands."""
        pass

    @customcommand.command(name="create")
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def customcommand_create(self, ctx, trigger: str, *, response: str):
        """
        Create a custom command.

        The trigger must be a single word and not conflict with existing commands.
        The response can be text or a link to an image.
        """
        author = ctx.author
        guild = ctx.guild

        if not any(role.id == self.role_id for role in author.roles):
            await ctx.send("You don't have the required role to create a custom command.")
            return

        command_owners = await self.config.guild(guild).command_owners()
        if str(author.id) in command_owners:
            await ctx.send("You have already created a custom command. You can only have one.")
            return

        if self.bot.get_command(trigger.lower()):
            await ctx.send("A command with this name already exists.")
            return
            
        all_commands = await self.config.guild(guild).commands()
        if trigger.lower() in all_commands:
            await ctx.send("A custom command with this trigger already exists.")
            return

        await self.config.guild(guild).commands.set_raw(trigger.lower(), value=response)
        await self.config.guild(guild).command_owners.set_raw(str(author.id), value=trigger.lower())

        await ctx.send(f"Custom command `{trigger}` has been created.")

    @customcommand.command(name="delete")
    async def customcommand_delete(self, ctx):
        """Delete your custom command."""
        author = ctx.author
        guild = ctx.guild

        command_owners = await self.config.guild(guild).command_owners()
        if str(author.id) not in command_owners:
            await ctx.send("You don't have a custom command to delete.")
            return

        trigger = command_owners[str(author.id)]
        await self.config.guild(guild).commands.clear_raw(trigger)
        await self.config.guild(guild).command_owners.clear_raw(str(author.id))

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
        trigger = message.content.lower()

        if trigger in all_commands:
            bucket = self._cooldown.get_bucket(message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                return
            response = all_commands[trigger]
            await message.channel.send(response)

async def setup(bot):
    await bot.add_cog(CustomCommand(bot))