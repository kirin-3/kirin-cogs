import asyncio
import io
from typing import Any

import aiohttp
import discord
from redbot.core import Config, app_commands, commands
from redbot.core.bot import Red

from .constants import DEFAULT_MODAL_PROMPT, HORDE_POSITIVE_PROMPT
from .loras import LORAS
from .models import MODELS
from .utils.horde import HordeClient
from .utils.modal_client import ModalClient
from .views import LoraListView


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
            "modal_prompt": DEFAULT_MODAL_PROMPT,
            "generation_limit": 1,
        }

        default_guild = {"premium_role_id": None}

        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)

        self._horde_client: HordeClient | None = None
        self._modal_client: ModalClient | None = None
        self._session: aiohttp.ClientSession | None = None
        self._init_lock = asyncio.Lock()

        # Global semaphore for concurrency, configurable default 1
        self._generation_semaphore = asyncio.Semaphore(1)
        self._active_generations = 0

    async def cog_load(self) -> None:
        raw_limit = await self.config.generation_limit()
        limit = raw_limit if isinstance(raw_limit, int) and 1 <= raw_limit <= 4 else 1
        if limit != raw_limit:
            await self.config.generation_limit.set(limit)
        self._generation_semaphore = asyncio.Semaphore(limit)

    async def cog_unload(self) -> None:
        if self._session:
            await self._session.close()

    def _get_session(self) -> aiohttp.ClientSession:
        # Try to retrieve bot session, fallback to creating one
        session = getattr(self.bot, "session", None) or getattr(self.bot, "_session", None)
        if session is None:
            # Check if we already created one in a race
            if self._session is None:
                import aiohttp

                self._session = aiohttp.ClientSession()
            session = self._session
        return session

    async def get_horde_client(self) -> HordeClient:
        async with self._init_lock:
            if self._horde_client is None:
                api_key = await self.config.horde_api_key()
                session = self._get_session()
                self._horde_client = HordeClient(session, api_key)
            return self._horde_client

    async def get_modal_client(self) -> ModalClient:
        async with self._init_lock:
            if self._modal_client is None:
                app_name = await self.config.modal_app_name()
                # Run Modal lookup in thread to prevent blocking heartbeat
                self._modal_client = await asyncio.to_thread(ModalClient, app_name)
            return self._modal_client

    async def is_premium(self, ctx: commands.Context) -> bool:
        if await self.bot.is_owner(ctx.author):
            return True

        if not ctx.guild:
            return False

        role_id = await self.config.guild(ctx.guild).premium_role_id()
        if not role_id:
            return False  # No role configured, so no premium access

        role = ctx.guild.get_role(role_id)
        if not role:
            return False

        if not isinstance(ctx.author, discord.Member):
            return False

        return role in ctx.author.roles

    def _build_full_prompt(self, prompt: str, backend_prompt: str, lora_configs: list[dict[str, Any]]) -> str:
        prompt_parts = []

        # 1. LoRA Triggers & Prompt
        for config in lora_configs:
            if "trigger_words" in config:
                prompt_parts.extend(config["trigger_words"])
            if "prompt" in config:
                prompt_parts.append(config["prompt"])

        # 2. User Prompt
        prompt_parts.append(prompt)

        # 3. Global Backend Prompt
        if backend_prompt:
            prompt_parts.append(backend_prompt)

        return ", ".join(prompt_parts)

    def _parse_styles(
        self, styles: list[str], max_count: int, required_base: str, allow_hidden: bool = True
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not styles:
            return [], None

        if len(styles) > max_count:
            return [], f"❌ You can only use up to {max_count} styles."

        lora_configs = []
        for key in styles:
            if key not in LORAS:
                return [], f"❌ Style `{key}` not found."

            config = LORAS[key]
            if config.get("base") != required_base:
                return (
                    [],
                    f"❌ Style `{key}` (Base: {config.get('base')}) is incompatible with required base {required_base}.",
                )

            if not allow_hidden and config.get("hidden", False):
                return [], f"❌ Style `{key}` is not available for this command."

            lora_configs.append(config)

        return lora_configs, None

    @staticmethod
    def _gen_free_cooldown(ctx: commands.Context) -> commands.Cooldown | None:  # type: ignore[override]
        if ctx.author.id in ctx.bot.owner_ids:
            return None
        return commands.Cooldown(1, 3600)

    @commands.hybrid_command(name="genfree", description="Generate image using HordeAI (Free)")
    @commands.dynamic_cooldown(_gen_free_cooldown, commands.BucketType.user)  # type: ignore[arg-type]
    @app_commands.describe(
        prompt="Image description",
        style="Optional style (LoRA)",
        style2="Optional style (LoRA)",
        style3="Optional style (LoRA)",
        negative_prompt="Things to exclude from the image",
    )
    async def gen_free(
        self,
        ctx: commands.Context,
        prompt: str,
        style: str | None = None,
        style2: str | None = None,
        style3: str | None = None,
        negative_prompt: str | None = None,
    ):
        """
        Free generation command using HordeAI.
        """
        await ctx.defer()

        if len(prompt.encode("utf-8")) > 1500:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("❌ Prompt exceeds 1500 byte limit.", allowed_mentions=discord.AllowedMentions.none())

        # Parse and Validate styles
        raw_styles = [s for s in [style, style2, style3] if s]
        lora_configs, error = self._parse_styles(raw_styles, max_count=3, required_base="Pony", allow_hidden=False)
        if error:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send(error, allowed_mentions=discord.AllowedMentions.none())

        if self._generation_semaphore.locked():
            ctx.command.reset_cooldown(ctx)
            await ctx.send(
                "⏳ The generation queue is full. Please wait a moment...",
                allowed_mentions=discord.AllowedMentions.none(),
                ephemeral=True,
            )
            return

        try:
            full_prompt = self._build_full_prompt(prompt, HORDE_POSITIVE_PROMPT, lora_configs)

            horde_loras = []
            for config in lora_configs:
                model_id = config["model_id"]
                if model_id.startswith("civitai:"):
                    civit_id = model_id.split(":")[1]
                    horde_loras.append(
                        {
                            "name": civit_id,
                            "is_version": True,
                            "model": config.get("strength", 1.0),
                            "clip": 1.0,
                        }
                    )

            # Use API key from config directly in case it changed
            api_key = await self.config.horde_api_key()

            async with self._generation_semaphore:
                self._active_generations += 1
                try:
                    client = await self.get_horde_client()
                    images = await client.generate(
                        prompt=full_prompt,
                        negative_prompt=negative_prompt or "",
                        nsfw=False,  # Free is always SFW
                        loras=horde_loras,
                        api_key=api_key,
                    )
                finally:
                    self._active_generations -= 1

            if not images:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send("Failed to generate image.", allowed_mentions=discord.AllowedMentions.none())

            if len(images[0]) > 10 * 1024 * 1024:
                raise ValueError("Generated image exceeds the 10 MiB safety limit")

            with io.BytesIO(images[0]) as fp:
                raw_styles_str = ", ".join([s for s in [style, style2, style3] if s])
                await ctx.send(
                    content=f"🎨 **Prompt:** {prompt}" + (f" | **Styles:** {raw_styles_str}" if raw_styles_str else ""),
                    file=discord.File(fp, filename="generation.png"),
                    allowed_mentions=discord.AllowedMentions.none(),
                )

        except Exception:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(
                "The image backend failed. Your cooldown was restored; please try again later.",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @staticmethod
    def _gen_premium_cooldown(ctx: commands.Context) -> commands.Cooldown | None:  # type: ignore[override]
        if ctx.author.id in ctx.bot.owner_ids:
            return None
        return commands.Cooldown(1, 21600)

    @commands.hybrid_command(name="gen", description="[PREMIUM] Generate image using Modal")
    @commands.dynamic_cooldown(_gen_premium_cooldown, commands.BucketType.user)  # type: ignore[arg-type]
    @app_commands.describe(
        prompt="Image description",
        model="Base model to use",
        batch_size="Number of images (1-4)",
        style="Optional style (LoRA)",
        style2="Optional style (LoRA)",
        style3="Optional style (LoRA)",
        style4="Optional style (LoRA)",
        style5="Optional style (LoRA)",
        negative_prompt="Things to exclude from the image",
    )
    async def gen_premium(
        self,
        ctx: commands.Context,
        prompt: str,
        model: str,
        batch_size: commands.Range[int, 1, 4] = 1,
        style: str | None = None,
        style2: str | None = None,
        style3: str | None = None,
        style4: str | None = None,
        style5: str | None = None,
        negative_prompt: str | None = None,
    ):
        """
        Premium generation using Modal.
        """
        if not await self.is_premium(ctx):
            ctx.command.reset_cooldown(ctx)
            msg = "🔒 This command is a for Supporters only."
            if ctx.interaction:
                return await ctx.send(msg, ephemeral=True)
            return await ctx.send(msg)

        if len(prompt.encode("utf-8")) > 1500:
            ctx.command.reset_cooldown(ctx)
            msg = "❌ Prompt exceeds 1500 byte limit."
            if ctx.interaction:
                return await ctx.send(msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return await ctx.send(msg, allowed_mentions=discord.AllowedMentions.none())

        await ctx.defer()
        raw_styles = [s for s in [style, style2, style3, style4, style5] if s]
        await self._run_modal_gen(ctx, prompt, model, raw_styles, negative_prompt, batch_size)

    @commands.hybrid_command(name="gentest", description="[OWNER] Test generation with seed")  # type: ignore[arg-type]
    @commands.is_owner()
    @app_commands.describe(
        prompt="Image description",
        model="Base model to use",
        batch_size="Number of images (1-4)",
        seed="Random seed (Optional)",
        style="Optional style (LoRA)",
        style2="Optional style (LoRA)",
        style3="Optional style (LoRA)",
        style4="Optional style (LoRA)",
        style5="Optional style (LoRA)",
        negative_prompt="Things to exclude from the image",
    )
    async def gen_test(
        self,
        ctx: commands.Context,
        prompt: str,
        model: str,
        batch_size: commands.Range[int, 1, 4] = 1,
        seed: int | None = None,
        style: str | None = None,
        style2: str | None = None,
        style3: str | None = None,
        style4: str | None = None,
        style5: str | None = None,
        negative_prompt: str | None = None,
    ) -> None:
        """
        Owner test generation using Modal with seed support.
        """
        if len(prompt.encode("utf-8")) > 1500:
            await ctx.send("❌ Prompt exceeds 1500 byte limit.", allowed_mentions=discord.AllowedMentions.none())
            return

        await ctx.defer()
        raw_styles = [s for s in [style, style2, style3, style4, style5] if s]
        await self._run_modal_gen(ctx, prompt, model, raw_styles, negative_prompt, batch_size, seed=seed)

    async def _run_modal_gen(
        self,
        ctx: commands.Context,
        prompt: str,
        model_alias: str,
        raw_styles: list[str],
        negative_prompt: str | None,
        batch_size: int = 1,
        seed: int | None = None,
    ):
        # Validate Model
        if model_alias not in MODELS:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send(
                f"❌ Model `{model_alias}` not found. Available: {', '.join(MODELS.keys())}",
                allowed_mentions=discord.AllowedMentions.none(),
            )

        model_config = MODELS[model_alias]

        # Parse and Validate styles
        lora_configs, error = self._parse_styles(raw_styles, max_count=5, required_base=model_config["base"])
        if error:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send(error, allowed_mentions=discord.AllowedMentions.none())

        if self._generation_semaphore.locked():
            ctx.command.reset_cooldown(ctx)
            await ctx.send(
                "⏳ The generation queue is full. Please wait a moment...",
                allowed_mentions=discord.AllowedMentions.none(),
                ephemeral=True,
            )
            return

        try:
            modal_prompt = await self.config.modal_prompt()

            full_prompt = self._build_full_prompt(prompt, modal_prompt, lora_configs)

            modal_loras = []
            for config in lora_configs:
                modal_loras.append({"model_id": config["model_id"], "weight": config.get("strength", 1.0)})

            async with self._generation_semaphore:
                self._active_generations += 1
                try:
                    client = await self.get_modal_client()
                    images = await client.generate(
                        prompt=full_prompt,
                        negative_prompt=negative_prompt or "",
                        model_id=model_config["id"],
                        loras=modal_loras,
                        batch_size=batch_size,
                        seed=seed,
                        width=model_config.get("width", 1024),
                        height=model_config.get("height", 1024),
                        steps=model_config.get("steps", 30),
                        guidance_scale=model_config.get("cfg", 7.5),
                        clip_skip=model_config.get("clip_skip"),
                        scheduler=model_config.get("sampler"),
                    )
                finally:
                    self._active_generations -= 1

            if not images:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send("Failed to generate image.", allowed_mentions=discord.AllowedMentions.none())

            files = []
            for i, img_bytes in enumerate(images):
                if len(img_bytes) > 10 * 1024 * 1024:
                    raise ValueError("Generated image exceeds the 10 MiB safety limit")
                files.append(discord.File(io.BytesIO(img_bytes), filename=f"generation_{i}.png"))

            styles_str = ", ".join(raw_styles)
            content = f"🎨 **Prompt:** {prompt}" + (f" | **Styles:** {styles_str}" if styles_str else "")
            await ctx.send(content=content, files=files, allowed_mentions=discord.AllowedMentions.none())

        except Exception:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(
                "The image backend failed. Your cooldown was restored; please try again later.",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @commands.hybrid_command(name="loras", description="Preview available styles")
    async def list_loras(self, ctx: commands.Context):
        """
        Lists all available LoRA styles using V2 components.
        """
        if not LORAS:
            return await ctx.send("No styles are currently configured.")

        session = self._get_session()
        view = LoraListView(LORAS, session)
        await view.send_initial(ctx)

    @gen_free.autocomplete("style")
    @gen_free.autocomplete("style2")
    @gen_free.autocomplete("style3")
    @gen_premium.autocomplete("style")
    @gen_premium.autocomplete("style2")
    @gen_premium.autocomplete("style3")
    @gen_premium.autocomplete("style4")
    @gen_premium.autocomplete("style5")
    @gen_test.autocomplete("style")
    @gen_test.autocomplete("style2")
    @gen_test.autocomplete("style3")
    @gen_test.autocomplete("style4")
    @gen_test.autocomplete("style5")
    async def style_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        choices = []
        is_free_command = interaction.command is not None and interaction.command.name == "genfree"

        for key, data in LORAS.items():
            # Hide hidden loras from genfree command
            if is_free_command:
                if data.get("hidden", False):
                    continue
                # Genfree only supports Pony base
                if data.get("base") != "Pony":
                    continue

            if current.lower() in key.lower() or current.lower() in data.get("name", "").lower():
                choices.append(app_commands.Choice(name=data.get("name", key), value=key))
        return choices[:25]

    @gen_premium.autocomplete("model")
    @gen_test.autocomplete("model")
    async def model_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not MODELS:
            return []
        choices = []
        for key, data in MODELS.items():
            if current.lower() in key.lower() or current.lower() in data.get("name", "").lower():
                choices.append(app_commands.Choice(name=data["name"], value=key))
        return choices[:25]

    # --- Config Commands ---

    @commands.group(name="unicornimage")  # type: ignore[arg-type]
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def unicorn_config(self, ctx: commands.Context) -> None:
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
            await asyncio.to_thread(self._modal_client.reload_app, app_name)
        await ctx.send(f"Modal app name set to `{app_name}`.")

    @unicorn_config.command(name="setprompt")
    async def set_prompt(self, ctx, *, prompt: str):
        """Set the default positive prompt appended to Modal requests."""
        await self.config.modal_prompt.set(prompt)
        await ctx.send("Modal prompt updated.")

    @unicorn_config.command(name="concurrency")
    @commands.is_owner()
    async def set_concurrency(self, ctx: commands.Context, limit: commands.Range[int, 1, 4]) -> None:
        """Set the process-wide image generation concurrency limit."""
        if self._active_generations:
            await ctx.send("Wait for active generations to finish before changing this limit.")
            return
        await self.config.generation_limit.set(limit)
        self._generation_semaphore = asyncio.Semaphore(limit)
        await ctx.send(f"Global image generation concurrency set to {limit}.")
