import discord
import io
import asyncio
from typing import Optional, List, Literal, Dict, Any

from redbot.core import commands, Config, app_commands
from redbot.core.bot import Red

from .utils.horde import HordeClient
from .utils.modal_client import ModalClient
from .loras import LORAS
from .constants import DEFAULT_MODAL_PROMPT, HORDE_POSITIVE_PROMPT

class UnicornImage(commands.Cog):
    """
    Text-to-Image generation using HordeAI (Free) and Modal (Premium).
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)
        
        default_global = {
            "horde_api_key": "0000000000",
            "modal_app_name": "text2image",
            "modal_prompt": DEFAULT_MODAL_PROMPT
        }
        
        default_guild = {
            "premium_role_id": None
        }

        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)

        self._horde_client: Optional[HordeClient] = None
        self._modal_client: Optional[ModalClient] = None

    async def get_horde_client(self) -> HordeClient:
        if self._horde_client is None:
            api_key = await self.config.horde_api_key()
            self._horde_client = HordeClient(self.bot.session, api_key)
        return self._horde_client

    async def get_modal_client(self) -> ModalClient:
        if self._modal_client is None:
            app_name = await self.config.modal_app_name()
            self._modal_client = ModalClient(app_name)
        return self._modal_client

    async def is_premium(self, ctx: commands.Context) -> bool:
        if await self.bot.is_owner(ctx.author):
            return True
            
        role_id = await self.config.guild(ctx.guild).premium_role_id()
        if not role_id:
            return False # No role configured, so no premium access
        
        if not ctx.guild:
            return False

        role = ctx.guild.get_role(role_id)
        if not role:
            return False
            
        return role in ctx.author.roles

    def _build_full_prompt(self, prompt: str, style: Optional[str], backend_prompt: str, lora_config: Optional[Dict[str, Any]]) -> str:
        prompt_parts = []
        
        # 1. LoRA Triggers & Prompt
        if lora_config:
            if "trigger_words" in lora_config:
                prompt_parts.extend(lora_config["trigger_words"])
            if "prompt" in lora_config:
                prompt_parts.append(lora_config["prompt"])
        
        # 2. User Prompt
        prompt_parts.append(prompt)

        # 3. Global Backend Prompt
        if backend_prompt:
            prompt_parts.append(backend_prompt)

        return ", ".join(prompt_parts)

    @commands.hybrid_command(name="genfree", description="Generate image using HordeAI (Free)")
    @app_commands.describe(prompt="Image description", style="Optional style (LoRA)")
    @commands.cooldown(1, 120, commands.BucketType.user)
    async def gen_free(self, ctx: commands.Context, prompt: str, style: Optional[str] = None):
        """
        Free generation command using HordeAI.
        """
        await ctx.defer()
        
        # Validate style
        if style and style not in LORAS:
             return await ctx.send(f"❌ Style `{style}` not found. Use `/loras` to see available styles.")

        try:
            client = await self.get_horde_client()
            
            lora_config = LORAS[style] if style else None
            full_prompt = self._build_full_prompt(prompt, style, HORDE_POSITIVE_PROMPT, lora_config)
            
            horde_loras = None
            if lora_config:
                model_id = lora_config["model_id"]
                if model_id.startswith("civitai:"):
                    civit_id = model_id.split(":")[1]
                    horde_loras = [{
                        "name": civit_id,
                        "is_version": True,
                        "model": lora_config.get("strength", 1.0),
                        "clip": 1.0,
                    }]

            # Use API key from config directly in case it changed
            api_key = await self.config.horde_api_key()

            images = await client.generate(
                prompt=full_prompt,
                nsfw=False, # Free is always SFW
                loras=horde_loras,
                api_key=api_key
            )
            
            if not images:
                 return await ctx.send("Failed to generate image.")

            with io.BytesIO(images[0]) as fp:
                await ctx.send(
                    content=f"🎨 **Prompt:** {prompt}" + (f" | **Style:** {style}" if style else ""),
                    file=discord.File(fp, filename="generation.png")
                )

        except Exception as e:
            await ctx.send(f"An error occurred: {str(e)}")

    @commands.hybrid_command(name="gen", description="[PREMIUM] Generate image using Modal")
    @app_commands.describe(prompt="Image description", style="Optional style (LoRA)")
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def gen_premium(self, ctx: commands.Context, prompt: str, style: Optional[str] = None):
        """
        Premium SFW generation using Modal.
        """
        if not await self.is_premium(ctx):
             return await ctx.send("🔒 This command is a Premium feature.", ephemeral=True)
        
        await ctx.defer()
        await self._run_modal_gen(ctx, prompt, style, nsfw=False)

    @commands.hybrid_command(name="gennsfw", description="[PREMIUM] Generate NSFW image using Modal")
    @app_commands.describe(prompt="Image description", style="Optional style (LoRA)")
    @commands.is_nsfw()
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def gen_nsfw(self, ctx: commands.Context, prompt: str, style: Optional[str] = None):
        """
        Premium NSFW generation using Modal.
        """
        if not await self.is_premium(ctx):
             return await ctx.send("🔒 This command is a Premium feature.", ephemeral=True)

        await ctx.defer()
        await self._run_modal_gen(ctx, prompt, style, nsfw=True)

    async def _run_modal_gen(self, ctx: commands.Context, prompt: str, style: Optional[str], nsfw: bool):
        # Validate style
        if style and style not in LORAS:
             return await ctx.send(f"❌ Style `{style}` not found. Use `/loras` to see available styles.")
        
        try:
            client = await self.get_modal_client()
            modal_prompt = await self.config.modal_prompt()
            
            lora_config = LORAS[style] if style else None
            full_prompt = self._build_full_prompt(prompt, style, modal_prompt, lora_config)
            
            modal_loras = []
            if lora_config:
                 modal_loras = [{
                     "model_id": lora_config["model_id"],
                     "weight": lora_config.get("strength", 1.0)
                 }]
            
            images = await client.generate(
                prompt=full_prompt,
                nsfw=nsfw,
                loras=modal_loras
            )
            
            if not images:
                 return await ctx.send("Failed to generate image.")

            with io.BytesIO(images[0]) as fp:
                content = f"🎨 **Prompt:** {prompt}" + (f" | **Style:** {style}" if style else "")
                if nsfw:
                    content += " | 🔞 [NSFW]"
                await ctx.send(content=content, file=discord.File(fp, filename="generation.png"))

        except Exception as e:
            await ctx.send(f"An error occurred: {str(e)}")

    @commands.hybrid_command(name="loras", description="Preview available styles")
    async def list_loras(self, ctx: commands.Context):
        """
        Lists all available LoRA styles.
        """
        if not LORAS:
            return await ctx.send("No styles are currently configured.")
            
        embeds = []
        intro_embed = discord.Embed(
            title="Available Styles",
            description="Use these styles with `/gen` commands.\nExample: `/gen prompt:cat style:anime`",
            color=discord.Color.blue()
        )
        embeds.append(intro_embed)
        
        for style_key, data in list(LORAS.items())[:9]:
            name = data.get("name", style_key)
            desc = data.get("description", "No description")
            img_url = data.get("image_url")
            
            embed = discord.Embed(
                title=f"Style: {name} (`{style_key}`)",
                description=desc,
                color=discord.Color.green()
            )
            if img_url:
                embed.set_image(url=img_url)
            embeds.append(embed)
            
        await ctx.send(embeds=embeds)

    @gen_free.autocomplete('style')
    @gen_premium.autocomplete('style')
    @gen_nsfw.autocomplete('style')
    async def style_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=data.get("name", key), value=key)
            for key, data in LORAS.items()
            if current.lower() in key.lower() or current.lower() in data.get("name", "").lower()
        ][:25]

    # --- Config Commands ---
    
    @commands.group(name="unicornimage")
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def unicorn_config(self, ctx):
        """Configure UnicornImage settings."""
        pass

    @unicorn_config.command(name="setapi")
    async def set_api(self, ctx, key: str):
        """Set the HordeAI API key."""
        await self.config.horde_api_key.set(key)
        # Update client if exists
        if self._horde_client:
            self._horde_client.api_key = key
        await ctx.send("HordeAI API key updated.")

    @unicorn_config.command(name="setrole")
    async def set_role(self, ctx, role: discord.Role):
        """Set the Premium Role for this server."""
        await self.config.guild(ctx.guild).premium_role_id.set(role.id)
        await ctx.send(f"Premium role set to {role.mention}.")

    @unicorn_config.command(name="setapp")
    async def set_app(self, ctx, app_name: str):
        """Set the Modal App name."""
        await self.config.modal_app_name.set(app_name)
        # Reload client
        if self._modal_client:
            self._modal_client.reload_app(app_name)
        await ctx.send(f"Modal app name set to `{app_name}`.")

    @unicorn_config.command(name="setprompt")
    async def set_prompt(self, ctx, *, prompt: str):
        """Set the default positive prompt appended to Modal requests."""
        await self.config.modal_prompt.set(prompt)
        await ctx.send(f"Modal prompt updated.")
