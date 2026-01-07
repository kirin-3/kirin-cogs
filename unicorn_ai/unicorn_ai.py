import discord
import logging
import os
import asyncio
import time
from redbot.core import commands, app_commands, Config
from redbot.core.utils.chat_formatting import box, pagify
from discord.ext import tasks
from typing import Optional

from .vertex import VertexClient
from .persona import PersonaManager

log = logging.getLogger("red.unicorn_ai")

class UnicornAI(commands.Cog):
    """
    Autonomous AI persona using Google Vertex AI.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9988776655, force_registration=True)
        
        # Channel-specific config
        default_channel = {
            "enabled": False,
            "interval": 300, # 5 minutes default
            "active_persona": None,
            "last_run": 0
        }
        self.config.register_channel(**default_channel)

        # Global config for API/System settings
        default_global = {
            "history_limit": 50,
            "model": "gemini-3-pro-preview",
            "location": "us-central1",
            "api_version": "v1"
        }
        self.config.register_global(**default_global)

        # User config for opt-out
        default_user = {
            "opt_out": False
        }
        self.config.register_user(**default_user)

        self.cog_path = os.path.dirname(__file__)
        self.data_path = os.path.join(self.cog_path, "data", "personas")
        
        self.vertex = VertexClient(self.cog_path)
        self.personas = PersonaManager(self.data_path)
        
        # Start loop
        self.auto_message_loop.start()

    def cog_unload(self):
        self.auto_message_loop.cancel()

    @tasks.loop(seconds=60)
    async def auto_message_loop(self):
        """
        Background loop to trigger AI messages.
        Runs every minute and checks all channels.
        """
        await self.bot.wait_until_ready()
        
        all_channels = await self.config.all_channels()
        now = time.time()
        
        for channel_id, settings in all_channels.items():
            if not settings["enabled"]:
                continue
            
            # Check if it's time to run
            last_run = settings["last_run"]
            interval = settings["interval"]
            
            if (now - last_run) >= interval:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    await self._trigger_ai(channel=channel)

    @auto_message_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    async def _trigger_ai(self, channel: discord.TextChannel = None, ctx: commands.Context = None, persona_override: str = None):
        """
        Core logic to fetch history and generate response.
        Can be triggered by loop (passed channel) or manual command (passed ctx).
        """
        # Resolve target channel
        if ctx:
            target_channel = ctx.channel
        else:
            target_channel = channel

        if not target_channel:
            return

        # Fetch settings
        settings = await self.config.channel(target_channel).all()
        global_settings = await self.config.all()
        
        # If manual trigger, ignore 'enabled' check
        if not ctx and not settings["enabled"]:
            return

        persona_name = persona_override or settings["active_persona"]
        if not persona_name:
            if ctx: await ctx.send("No active persona set (and no override provided).")
            return

        persona = await asyncio.to_thread(self.personas.load_persona, persona_name)
        if not persona:
            if ctx: await ctx.send(f"Failed to load persona '{persona_name}'.")
            return

        # 2. Fetch History
        try:
            # Use persona limit if set, otherwise global
            limit = persona.history_limit if persona.history_limit is not None else global_settings["history_limit"]
            
            # Ensure we are in a text channel or thread
            if not hasattr(target_channel, "history"):
                 if ctx: await ctx.send("Cannot fetch history from this channel type.")
                 return

            messages = [m async for m in target_channel.history(limit=limit)]
            messages.reverse() # Oldest first
        except Exception as e:
            log.error(f"Failed to fetch history: {e}")
            if ctx: await ctx.send(f"Error fetching history: {e}")
            return

        # 3. Format History for Gemini (With Opt-Out Check)
        formatted_history = []
        for msg in messages:
            # Check opt-out status for user messages
            if msg.author.id != self.bot.user.id:
                if await self.config.user(msg.author).opt_out():
                    continue

            role = "model" if msg.author.id == self.bot.user.id else "user"
            content = msg.clean_content
            if not content:
                continue # Skip empty messages
            
            formatted_history.append({
                "role": role,
                "parts": [{"text": f"{msg.author.display_name}: {content}"}]
            })

        # 4. Generate Response
        if ctx:
            await ctx.send("Generating response...")
        
        response = await self.vertex.generate_response(
            model=global_settings["model"],
            location=global_settings["location"],
            api_version=global_settings.get("api_version", "v1"),
            system_instruction=persona.system_prompt,
            history=formatted_history,
            after_context=persona.after_context
        )

        if not response:
            if ctx: await ctx.send("Failed to generate response (empty or error).")
            return

        # 5. Send
        try:
            await self._send_response(target_channel, response, persona)
            # Update last_run only on success
            await self.config.channel(target_channel).last_run.set(time.time())
        except Exception as e:
            if ctx: await ctx.send(f"Failed to send message: {e}")

    async def _send_response(self, channel, content: str, persona):
        """
        Sends the response via Webhook if possible (for persona impersonation),
        otherwise falls back to standard message.
        """
        # Check if we can use webhooks (Guild channels only)
        if not hasattr(channel, "guild"):
             await channel.send(content)
             return

        perms = channel.permissions_for(channel.guild.me)
        if not perms.manage_webhooks:
            await channel.send(content)
            return

        try:
            # Handle Threads
            target_channel = channel
            thread_obj = discord.utils.MISSING
            
            if isinstance(channel, discord.Thread):
                target_channel = channel.parent
                thread_obj = channel

            # Fetch or create webhook
            webhooks = await target_channel.webhooks()
            webhook = next((w for w in webhooks if w.user.id == self.bot.user.id), None)
            
            if not webhook:
                webhook = await target_channel.create_webhook(name="UnicornAI Webhook")
            
            # Send via webhook
            await webhook.send(
                content=content, 
                username=persona.name, 
                avatar_url=persona.avatar_url or self.bot.user.display_avatar.url,
                thread=thread_obj
            )
        except Exception as e:
            log.error(f"Webhook send failed: {e}")
            # Fallback
            await channel.send(content)

    # --- Commands ---

    async def persona_autocomplete(self, interaction: discord.Interaction, current: str):
        """
        Autocomplete for summonable personas.
        Filters by 'allow_summon' flag.
        """
        try:
            # Run in thread to prevent blocking heartbeat during file I/O
            summonable_names = await asyncio.to_thread(self.personas.get_summonable_personas)
            
            choices = []
            for name in summonable_names:
                if current.lower() in name.lower():
                    choices.append(app_commands.Choice(name=name, value=name))
                    
                if len(choices) >= 25: # Discord limit
                    break
                    
            return choices
        except Exception:
            # Silently fail autocomplete rather than spamming logs/console
            return []

    # Dynamic cooldowns to allow owner bypass
    async def _summon_user_cd(ctx):
        if await ctx.bot.is_owner(ctx.author):
            return None
        return commands.Cooldown(1, 21600)

    async def _summon_channel_cd(ctx):
        if await ctx.bot.is_owner(ctx.author):
            return None
        return commands.Cooldown(1, 1800)

    @commands.hybrid_command(name="summon", description="Summon a specific persona to chat.")
    @app_commands.describe(persona="The name of the persona to summon")
    @app_commands.autocomplete(persona=persona_autocomplete)
    @commands.guild_only()
    @commands.dynamic_cooldown(_summon_user_cd, commands.BucketType.user)
    @commands.dynamic_cooldown(_summon_channel_cd, commands.BucketType.channel)
    async def ai_summon(self, ctx: commands.Context, persona: str):
        """
        Summons a specific persona to the current channel.
        Usage: [p]summon <persona_name>
        """
        # 1. Validation: Enabled Channel
        if not await self.config.channel(ctx.channel).enabled():
            return await ctx.send("AI is not enabled in this channel.", ephemeral=True)

        # 2. Validation: Persona Exists and is Summonable
        # We use asyncio.to_thread to avoid blocking event loop with I/O
        p_data = await asyncio.to_thread(self.personas.load_persona, persona)
        
        if not p_data:
            return await ctx.send(f"Persona `{persona}` not found.", ephemeral=True)
            
        if not p_data.allow_summon:
            # Security fail-safe: Even if they guessed the name, deny it.
            return await ctx.send(f"Persona `{persona}` cannot be summoned manually.", ephemeral=True)
            
        # 3. Trigger
        # Defer because API calls can take time
        await ctx.defer()
        
        try:
            # We pass the persona_override to _trigger_ai
            await self._trigger_ai(ctx.channel, ctx=ctx, persona_override=persona)
        except Exception as e:
            log.exception("Failed to summon persona")
            await ctx.send(f"Failed to summon persona: {e}")

    @commands.hybrid_command(name="aioptout", description="Toggle your opt-out status for the AI.")
    async def ai_optout(self, ctx: commands.Context):
        """
        Toggle your opt-out status.
        If opted out, your messages will be ignored by the AI context window.
        """
        current = await self.config.user(ctx.author).opt_out()
        new_state = not current
        await self.config.user(ctx.author).opt_out.set(new_state)
        
        if new_state:
            await ctx.send("You have opted out. Your messages will no longer be included in the AI context.", ephemeral=True)
        else:
            await ctx.send("You have opted in. The AI can now see your messages.", ephemeral=True)

    @commands.group(name="ai")
    async def ai_group(self, ctx):
        """Manage UnicornAI settings."""
        pass

    @ai_group.command(name="setup")
    @commands.is_owner()
    async def ai_setup(self, ctx):
        """Reloads credentials from local JSON file."""
        success = await self.vertex._load_credentials()
        if success:
            await ctx.send("Credentials loaded successfully.")
        else:
            await ctx.send("Failed to load credentials. Check logs and ensure `service_account.json` is in the cog folder.")

    @ai_group.command(name="toggle")
    @commands.is_owner()
    async def ai_toggle(self, ctx):
        """Toggle the auto-messaging loop for the current channel."""
        current = await self.config.channel(ctx.channel).enabled()
        new_state = not current
        await self.config.channel(ctx.channel).enabled.set(new_state)
        await ctx.send(f"UnicornAI is now {'**Enabled**' if new_state else '**Disabled**'} for {ctx.channel.mention}.")

    @ai_group.command(name="trigger")
    @commands.is_owner()
    async def ai_trigger(self, ctx, persona_name: Optional[str] = None):
        """
        Manually trigger a generation cycle in this channel.
        Optionally provide a persona name to test specifically.
        """
        await self._trigger_ai(ctx=ctx, persona_override=persona_name)

    @ai_group.command(name="interval")
    @commands.is_owner()
    async def ai_interval(self, ctx, seconds: int):
        """Set the loop interval for this channel (seconds)."""
        if seconds < 60:
            await ctx.send("Warning: Interval too short. Minimum recommended is 60 seconds.")
        
        await self.config.channel(ctx.channel).interval.set(seconds)
        await ctx.send(f"Interval set to {seconds} seconds for {ctx.channel.mention}.")

    @ai_group.command(name="history")
    @commands.is_owner()
    async def ai_history(self, ctx, limit: int):
        """Set the global history limit (max messages to read)."""
        await self.config.history_limit.set(limit)
        await ctx.send(f"Global history limit set to {limit} messages.")

    @ai_group.command(name="model")
    @commands.is_owner()
    async def ai_model(self, ctx, name: str):
        """Set the global Gemini model version."""
        await self.config.model.set(name)
        await ctx.send(f"Model set to `{name}`.")

    @ai_group.command(name="location")
    @commands.is_owner()
    async def ai_location(self, ctx, location: str):
        """
        Set the Google Cloud location (e.g., 'us-central1' or 'global').
        Default is 'us-central1'.
        """
        await self.config.location.set(location)
        await ctx.send(f"Location set to `{location}`.")

    @ai_group.command(name="api_version")
    @commands.is_owner()
    async def ai_api_version(self, ctx, version: str):
        """
        Set the Vertex AI API version (e.g., 'v1' or 'v1beta1').
        Default is 'v1'.
        """
        await self.config.api_version.set(version)
        await ctx.send(f"API Version set to `{version}`.")

    @ai_group.group(name="persona")
    @commands.is_owner()
    async def persona_group(self, ctx):
        """Manage Personas."""
        pass

    @persona_group.command(name="list")
    async def persona_list(self, ctx):
        """List available personas."""
        personas = await asyncio.to_thread(self.personas.list_personas)
        if not personas:
            await ctx.send("No personas found in `data/personas/`.")
            return
        await ctx.send(f"Available Personas: {', '.join(personas)}")

    @persona_group.command(name="load")
    async def persona_load(self, ctx, name: str):
        """Load a persona for the current channel."""
        persona = await asyncio.to_thread(self.personas.load_persona, name)
        if persona:
            await self.config.channel(ctx.channel).active_persona.set(name)
            await ctx.send(f"Loaded persona **{persona.name}** for {ctx.channel.mention}.")
        else:
            await ctx.send(f"Could not find or load persona `{name}`.")
