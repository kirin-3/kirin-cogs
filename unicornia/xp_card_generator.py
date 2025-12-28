"""
XP Card Generator for Unicornia
Generates XP cards with custom backgrounds and frames like Nadeko
"""

import aiohttp
import asyncio
import io
import os
import yaml
import functools
import socket
import ipaddress
from urllib.parse import urlparse
from PIL import Image, ImageDraw, ImageFont
from typing import Dict, Any, Tuple
from collections import OrderedDict
import logging

log = logging.getLogger("red.unicornia.xp_card")

class XPCardGenerator:
    """Handles XP card generation with custom backgrounds and frames"""
    
    def __init__(self, cog_dir: str):
        self.cog_dir = cog_dir
        self.xp_config = None
        self.fonts_cache = {}
        self.images_cache = OrderedDict()
        self.default_font_size = 25
        
        # Card dimensions (matching Nadeko's template)
        self.card_width = 500
        self.card_height = 245
        
        # Load XP configuration
        asyncio.create_task(self._load_xp_config())
    
    async def _load_xp_config(self):
        """Load XP configuration from local config file"""
        try:
            # Look for local xp_config.yml in cog directory
            local_config_path = os.path.join(self.cog_dir, "xp_config.yml")
            
            if os.path.exists(local_config_path):
                with open(local_config_path, 'r', encoding='utf-8') as f:
                    self.xp_config = yaml.safe_load(f)
                log.info(f"Loaded XP configuration from {local_config_path}")
            else:
                log.info("Creating default XP configuration file")
                self.xp_config = self._get_default_config()
                await self._save_default_config()
                
        except Exception as e:
            log.error(f"Error loading XP config: {e}")
            self.xp_config = self._get_default_config()
    
    async def _save_default_config(self):
        """Save default configuration to local file"""
        try:
            config_path = os.path.join(self.cog_dir, "xp_config.yml")
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.xp_config, f, default_flow_style=False, allow_unicode=True)
            log.info(f"Created default XP configuration at {config_path}")
        except Exception as e:
            log.error(f"Error saving default config: {e}")
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default XP configuration with your custom backgrounds"""
        return {
            "shop": {
                "isEnabled": True,
                "bgs": {
                    "default": {
                        "name": "Default Background", 
                        "price": 0,
                        "url": "https://unicornia.net/botimages/defaultxp1.png",
                        "preview": "",
                        "desc": "Free default background for everyone"
                    },
                    "shadow": {
                        "name": "Shadow",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/shadow1.gif",
                        "preview": "",
                        "desc": "Shadow from the Eminence in Shadow"
                    },
                    "jinwoo": {
                        "name": "jin-woo",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/jinwoo.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "astolfo": {
                        "name": "Astolfo",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/Astolfo.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "edward": {
                        "name": "Edward Elric",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/edward-elric.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "light": {
                        "name": "Light Yagami",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/light-yagami.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "chainsawman": {
                        "name": "Chainsaw Man",
                        "price": 15000,
                        "url": "https://unicornia.net/botimages/chainsawman.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "makima1": {
                        "name": "Makima 1",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/makima1.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "makima2": {
                        "name": "Makima 2",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/makima2.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "archer": {
                        "name": "Archer",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/archer.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "rintohsaka": {
                        "name": "Rin Tohsaka",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/rintohsaka.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "dandadan": {
                        "name": "Dan Da Dan",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/dandadan.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "aki-csm": {
                        "name": "Aki",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/aki-csm.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "saber": {
                        "name": "Saber",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/saber.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "saber2": {
                        "name": "Saber 2",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/saber2.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "lucy": {
                        "name": "Lucyna Kushinada",
                        "price": 20000,
                        "url": "https://unicornia.net/botimages/Lucyna-Kushinada.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "butt": {
                        "name": "Butt",
                        "price": 25000,
                        "url": "https://unicornia.net/botimages/butt.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "butts-jiggle": {
                        "name": "Butts jiggle",
                        "price": 25000,
                        "url": "https://unicornia.net/botimages/butts-jiggle.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "pindown": {
                        "name": "Pindown",
                        "price": 25000,
                        "url": "https://unicornia.net/botimages/pin-down.gif",
                        "preview": "",
                        "desc": ""
                    },
                    "hypno-femdom": {
                        "name": "Femdom Hypno",
                        "price": 25000,
                        "url": "https://unicornia.net/botimages/hypno-femdom.gif",
                        "preview": "",
                        "desc": ""
                    }
                }
            }
        }
    
    async def _get_font(self, size: int = None) -> ImageFont.FreeTypeFont:
        """Get font for text rendering"""
        if size is None:
            size = self.default_font_size
            
        if size in self.fonts_cache:
            return self.fonts_cache[size]
        
        # Try to load fonts in order of preference
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/arial.ttf", 
            "/System/Library/Fonts/Arial.ttf",
            "arial.ttf"
        ]
        
        font = None
        for font_path in font_paths:
            try:
                font = ImageFont.truetype(font_path, size)
                break
            except (OSError, IOError):
                continue
        
        if font is None:
            font = ImageFont.load_default()
            
        self.fonts_cache[size] = font
        return font
    
    async def _download_image(self, url: str) -> Image.Image | None:
        """Download and cache an image from URL (with SSRF protection and Cache Limit)"""
        if not url:
            return None

        # Check cache (LRU)
        if url in self.images_cache:
            # Move to end to mark as recently used
            self.images_cache.move_to_end(url)
            return self.images_cache[url]
        
        # Evict oldest if cache is full
        if len(self.images_cache) > 100:
            self.images_cache.popitem(last=False)
            
        # SSRF Protection
        try:
            parsed = urlparse(url)
            if not parsed.hostname:
                return None
            
            # Resolve hostname (run in executor to avoid blocking)
            loop = asyncio.get_running_loop()
            addr_info = await loop.run_in_executor(None, socket.getaddrinfo, parsed.hostname, None)
            
            for family, _, _, _, sockaddr in addr_info:
                ip = ipaddress.ip_address(sockaddr[0])
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    log.warning(f"Blocked potential SSRF attempt to {url} ({ip})")
                    return None
                    
        except Exception as e:
            log.warning(f"Invalid URL or resolution failed: {url} - {e}")
            return None
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        image_data = await response.read()
                        image = Image.open(io.BytesIO(image_data))
                        image = image.convert("RGBA")
                        self.images_cache[url] = image
                        self.images_cache.move_to_end(url)
                        return image
        except Exception as e:
            log.error(f"Error downloading image from {url}: {e}")
            
        return None
    
    async def _get_user_avatar(self, user_avatar_url: str) -> Image.Image:
        """Get user avatar, with fallback to default"""
        avatar = await self._download_image(user_avatar_url)
        if avatar:
            # Resize and make circular
            avatar = avatar.resize((38, 38), Image.Resampling.LANCZOS)
            
            # Create circular mask
            mask = Image.new('L', (38, 38), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, 38, 38), fill=255)
            
            # Apply mask
            avatar.putalpha(mask)
            return avatar
        
        # Create default avatar
        default_avatar = Image.new('RGBA', (38, 38), (128, 128, 128, 255))
        mask = Image.new('L', (38, 38), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, 38, 38), fill=255)
        default_avatar.putalpha(mask)
        return default_avatar
    
    def _create_xp_bar(self, current_xp: int, required_xp: int, width: int = 275, height: int = 20) -> Image.Image:
        """Create XP progress bar matching Nadeko C# template"""
        # C# template uses Color(0, 0, 0, 0.4f) = 40% transparency = 102 alpha
        bar = Image.new('RGBA', (width, height), (0, 0, 0, 102))
        draw = ImageDraw.Draw(bar)
        
        if required_xp > 0:
            progress = min(current_xp / required_xp, 1.0)
            progress_width = int(width * progress)
            
            # Draw progress bar with white fill to match template text color
            if progress_width > 0:
                draw.rectangle([0, 0, progress_width, height], fill=(255, 255, 255, 200))
        
        return bar

    def _draw_card_sync(
        self,
        username: str,
        avatar: Image.Image,
        background: Image.Image | None,
        club_icon: Image.Image | None,
        level: int,
        current_xp: int,
        required_xp: int,
        total_xp: int,
        rank: int,
        club_name: str | None,
        fonts: Dict[str, ImageFont.FreeTypeFont]
    ) -> io.BytesIO:
        """Synchronous method to draw the XP card (runs in thread)"""
        # Create base card
        card = Image.new('RGBA', (self.card_width, self.card_height), (47, 49, 54, 255))
        
        # Draw background
        if background:
            # Resize background to fit card
            # Note: background might be already resized if we did it in async, but let's do it here to be safe if not
            if background.size != (self.card_width, self.card_height):
                background = background.resize((self.card_width, self.card_height), Image.Resampling.LANCZOS)
            card = Image.alpha_composite(card, background)
            
        # Draw user avatar
        card.paste(avatar, (11, 11), avatar)
        
        # Create drawing context
        draw = ImageDraw.Draw(card)
        
        # Use passed fonts
        name_font = fonts['name']
        level_font = fonts['level']
        rank_font = fonts['rank']
        xp_font = fonts['xp']
        club_font = fonts.get('club')
        
        # Draw username (position from template)
        draw.text((65, 8), username, font=name_font, fill=(255, 255, 255, 255))
        
        # Draw level
        draw.text((35, 101), f"Level {level}", font=level_font, fill=(255, 255, 255, 255))
        
        # Draw rank
        draw.text((100, 145), f"Rank #{rank}", font=rank_font, fill=(255, 255, 255, 255))
        
        # Draw XP bar
        xp_bar = self._create_xp_bar(current_xp, required_xp, width=275)
        card.paste(xp_bar, (202, 66), xp_bar)
        
        # Draw XP text
        xp_text = f"{current_xp}/{required_xp} XP"
        draw.text((330, 104), xp_text, font=xp_font, fill=(255, 255, 255, 255))
        
        # Draw Club Info
        if club_icon:
            # Resize to 29x29 if needed
            if club_icon.size != (29, 29):
                club_icon = club_icon.resize((29, 29), Image.Resampling.LANCZOS)
            card.paste(club_icon, (451, 15), club_icon)
        
        if club_name and club_font:
            draw.text((394, 40), club_name, font=club_font, fill=(255, 255, 255, 255))
            
        # Convert to bytes
        output = io.BytesIO()
        card.save(output, format='PNG')
        output.seek(0)
        
        return output
    
    async def generate_xp_card(
        self, 
        user_id: int,
        username: str, 
        avatar_url: str,
        level: int,
        current_xp: int, 
        required_xp: int,
        total_xp: int,
        rank: int,
        background_key: str = "default",
        club_icon_url: str = None,
        club_name: str = None
    ) -> io.BytesIO:
        """Generate XP card image (Non-blocking)"""
        
        # Ensure config is loaded
        if not self.xp_config:
            await self._load_xp_config()
        
        # 1. Fetch all resources asynchronously (I/O bound)
        bg_config = self.xp_config.get("shop", {}).get("bgs", {}).get(background_key, {})
        bg_url = bg_config.get("url", "")
        
        # Parallel downloads
        tasks = [
            self._get_user_avatar(avatar_url),
            self._download_image(bg_url) if bg_url else asyncio.sleep(0, result=None),
            self._download_image(club_icon_url) if club_icon_url else asyncio.sleep(0, result=None)
        ]
        
        avatar, background, club_icon = await asyncio.gather(*tasks)
        
        # Get fonts (likely cached, but keep async interface)
        fonts = {
            'name': await self._get_font(25),
            'level': await self._get_font(22),
            'rank': await self._get_font(20),
            'xp': await self._get_font(25),
            'club': await self._get_font(20) if club_name else None
        }
        
        # 2. Run blocking image manipulation in executor (CPU bound)
        loop = asyncio.get_running_loop()
        
        # Use functools.partial to pass arguments to the synchronous function
        draw_func = functools.partial(
            self._draw_card_sync,
            username=username,
            avatar=avatar,
            background=background,
            club_icon=club_icon,
            level=level,
            current_xp=current_xp,
            required_xp=required_xp,
            total_xp=total_xp,
            rank=rank,
            club_name=club_name,
            fonts=fonts
        )
        
        return await loop.run_in_executor(None, draw_func)
    
    def get_available_backgrounds(self) -> Dict[str, Dict[str, Any]]:
        """Get available backgrounds from config"""
        if not self.xp_config:
            return {}
        return self.xp_config.get("shop", {}).get("bgs", {})
    
    def get_background_price(self, background_key: str) -> int:
        """Get price of a background"""
        bg_config = self.get_available_backgrounds().get(background_key, {})
        return bg_config.get("price", -1)
