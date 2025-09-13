"""
XP Card Generator for Unicornia
Generates XP cards with custom backgrounds and frames like Nadeko
"""

import aiohttp
import asyncio
import io
import os
import yaml
from PIL import Image, ImageDraw, ImageFont
from typing import Optional, Dict, Any, Tuple
import logging

log = logging.getLogger("red.unicornia.xp_card")

class XPCardGenerator:
    """Handles XP card generation with custom backgrounds and frames"""
    
    def __init__(self, cog_dir: str):
        self.cog_dir = cog_dir
        self.xp_config = None
        self.fonts_cache = {}
        self.images_cache = {}
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
    
    async def _download_image(self, url: str) -> Optional[Image.Image]:
        """Download and cache an image from URL"""
        if url in self.images_cache:
            return self.images_cache[url]
        
        if not url:
            return None
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        image_data = await response.read()
                        image = Image.open(io.BytesIO(image_data))
                        image = image.convert("RGBA")
                        self.images_cache[url] = image
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
    
    def _create_xp_bar(self, current_xp: int, required_xp: int, width: int = 225, height: int = 20) -> Image.Image:
        """Create XP progress bar matching Nadeko template"""
        # Nadeko template uses color "00000066" for bar background (semi-transparent black)
        bar = Image.new('RGBA', (width, height), (0, 0, 0, 102))  # 66 hex = 102 decimal alpha
        draw = ImageDraw.Draw(bar)
        
        if required_xp > 0:
            progress = min(current_xp / required_xp, 1.0)
            progress_width = int(width * progress)
            
            # Draw progress bar with white fill to match template text color
            if progress_width > 0:
                draw.rectangle([0, 0, progress_width, height], fill=(255, 255, 255, 200))
        
        return bar
    
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
    ) -> io.BytesIO:
        """Generate XP card image"""
        
        # Ensure config is loaded
        if not self.xp_config:
            await self._load_xp_config()
        
        # Create base card
        card = Image.new('RGBA', (self.card_width, self.card_height), (47, 49, 54, 255))
        
        # Get background
        bg_config = self.xp_config.get("shop", {}).get("bgs", {}).get(background_key, {})
        bg_url = bg_config.get("url", "")
        
        if bg_url:
            background = await self._download_image(bg_url)
            if background:
                # Resize background to fit card
                background = background.resize((self.card_width, self.card_height), Image.Resampling.LANCZOS)
                card = Image.alpha_composite(card, background)
        
        # Frames removed - no longer needed
        
        # Create drawing context
        draw = ImageDraw.Draw(card)
        
        # Get fonts
        name_font = await self._get_font(25)
        level_font = await self._get_font(22) 
        rank_font = await self._get_font(20)
        xp_font = await self._get_font(25)
        
        # Draw user avatar
        avatar = await self._get_user_avatar(avatar_url)
        card.paste(avatar, (11, 11), avatar)
        
        # Draw username (position from template)
        draw.text((65, 8), username, font=name_font, fill=(255, 255, 255, 255))
        
        # Draw level
        draw.text((35, 101), f"Level {level}", font=level_font, fill=(255, 255, 255, 255))
        
        # Draw rank
        draw.text((100, 115), f"Rank #{rank}", font=rank_font, fill=(255, 255, 255, 255))
        
        # Draw XP bar based on Nadeko template
        # Template: PointA(202,66) to PointB(180,145), Length=225, Direction=3
        # This appears to be a diagonal bar, but we'll simplify to horizontal
        xp_bar = self._create_xp_bar(current_xp, required_xp)
        card.paste(xp_bar, (202, 66), xp_bar)
        
        # Draw XP text
        xp_text = f"{current_xp}/{required_xp} XP"
        draw.text((330, 104), xp_text, font=xp_font, fill=(255, 255, 255, 255))
        
        # Frames removed - no overlay needed
        
        # Convert to bytes
        output = io.BytesIO()
        card.save(output, format='PNG')
        output.seek(0)
        
        return output
    
    def get_available_backgrounds(self) -> Dict[str, Dict[str, Any]]:
        """Get available backgrounds from config"""
        if not self.xp_config:
            return {}
        return self.xp_config.get("shop", {}).get("bgs", {})
    
    def get_background_price(self, background_key: str) -> int:
        """Get price of a background"""
        bg_config = self.get_available_backgrounds().get(background_key, {})
        return bg_config.get("price", -1)
