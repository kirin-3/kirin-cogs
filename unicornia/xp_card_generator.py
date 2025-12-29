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
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence
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
        self.fallback_fonts_cache = {}
        
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
                    }
                }
            }
        }
    
    async def _get_font(self, size: int = None, bold: bool = False) -> ImageFont.FreeTypeFont:
        """Get font for text rendering"""
        if size is None:
            size = self.default_font_size
            
        cache_key = (size, bold)
        if cache_key in self.fonts_cache:
            return self.fonts_cache[cache_key]
        
        # Try to load fonts in order of preference
        font_paths = []
        if bold:
            font_paths.extend([
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/TTF/arialbd.ttf",
                "arialbd.ttf"
            ])
            
        font_paths.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/arial.ttf",
            "/System/Library/Fonts/Arial.ttf",
            "arial.ttf"
        ])
        
        font = None
        for font_path in font_paths:
            try:
                font = ImageFont.truetype(font_path, size)
                break
            except (OSError, IOError):
                continue
        
        if font is None:
            # Fallback to default, though default doesn't support size on older Pillow versions
            # But let's assume standard environment
            try:
                font = ImageFont.truetype("arial.ttf", size)
            except IOError:
                font = ImageFont.load_default()
            
        self.fonts_cache[cache_key] = font
        return font
    
    async def _get_fallback_fonts(self, size: int) -> list[ImageFont.FreeTypeFont]:
        """Get a list of fallback fonts for special characters"""
        if size in self.fallback_fonts_cache:
            return self.fallback_fonts_cache[size]
            
        # List of fonts known to have good unicode support (Linux & Windows)
        fallback_paths = [
            # Linux / Standard
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/truetype/unifont/unifont.ttf",
            # Windows
            "C:\\Windows\\Fonts\\seguiemj.ttf", # Segoe UI Emoji
            "C:\\Windows\\Fonts\\seguisym.ttf", # Segoe UI Symbol
            "C:\\Windows\\Fonts\\arialuni.ttf", # Arial Unicode MS
            "arialuni.ttf"
        ]
        
        loaded_fonts = []
        for path in fallback_paths:
            try:
                # Try to load
                font = ImageFont.truetype(path, size)
                loaded_fonts.append(font)
            except (OSError, IOError):
                continue
                
        self.fallback_fonts_cache[size] = loaded_fonts
        return loaded_fonts

    def _has_glyph(self, font: ImageFont.FreeTypeFont, char: str) -> bool:
        """Check if a font supports a specific character"""
        if not hasattr(self, "_missing_glyph_mask"):
            # Cache the mask of a definitely missing character (Private Use Area)
            try:
                # Use a dummy font for the baseline if possible, or just the current font
                # We assume the missing glyph representation is consistent for the font instance
                pass
            except:
                pass

        try:
            # Get mask of the character
            mask = font.getmask(char)
            
            # If mask is empty/zero size, it might be whitespace (valid) or missing
            # But usually missing glyph is a box (tofu) which has a size
            
            # Compare with a definitely missing character for THIS font
            # \U0010FFFF is Max Unicode, likely missing
            mask_missing = font.getmask("\U0010FFFF")
            
            # If the masks are identical, it's likely using the fallback 'tofu' or empty glyph
            if mask.size == mask_missing.size and mask.tobytes() == mask_missing.tobytes():
                return False
                
            return True
        except Exception:
            return False

    def _draw_text_with_fallback(
        self,
        draw: ImageDraw.Draw,
        xy: Tuple[int, int],
        text: str,
        primary_font: ImageFont.FreeTypeFont,
        fallback_fonts: list[ImageFont.FreeTypeFont],
        fill: Any,
        anchor: str = None
    ):
        """Draw text handling missing glyphs by switching to fallback fonts"""
        x, y = xy
        
        # Current drawing position
        current_x = x
        
        # We need to handle anchors manually if we draw segment by segment
        # For simplicity, we'll calculate total width first if anchor is involved
        # But 'mm' (middle-middle) and 'rs' (right-baseline) are used in this file
        
        # 1. Segment the text by font availability
        segments = [] # List of (text_chunk, font_to_use)
        
        current_segment = ""
        current_font = primary_font
        
        for char in text:
            # Check if current font has it
            if self._has_glyph(current_font, char):
                current_segment += char
            else:
                # Push previous segment
                if current_segment:
                    segments.append((current_segment, current_font))
                    current_segment = ""
                
                # Find a font that has it
                found_font = primary_font # Default back to primary if none found
                
                # Check primary again (redundant but clean logic) -> already checked above
                # Check fallbacks
                for fb_font in fallback_fonts:
                    if self._has_glyph(fb_font, char):
                        found_font = fb_font
                        break
                
                # Start new segment with this char and this font
                current_segment = char
                current_font = found_font
                
        # Append last segment
        if current_segment:
            segments.append((current_segment, current_font))
            
        # 2. Calculate offsets for anchors
        total_width = 0
        max_height = 0
        segment_widths = []
        
        for seg_text, seg_font in segments:
            w = seg_font.getlength(seg_text)
            segment_widths.append(w)
            total_width += w
            
            # Height approximation (ascent - descent)
            # ascent, descent = seg_font.getmetrics()
            # max_height = max(max_height, ascent + descent)
            
        # Adjust starting X based on anchor
        # Pillow anchors:
        # 'mm': Middle horizontal, Middle vertical
        # 'rs': Right horizontal, Baseline vertical (Standard for text)
        # None/Default: Left, Top (or baseline depending on mode)
        
        start_x = x
        start_y = y
        
        if anchor:
            if 'm' in anchor[0]: # Middle horizontal
                start_x = x - (total_width / 2)
            elif 'r' in anchor[0]: # Right horizontal
                start_x = x - total_width
                
            # Vertical alignment handling is tricky with mixed fonts
            # We will trust the passed Y and anchor for the primary font's baseline
            # and align other fonts to that baseline
            
        # 3. Draw segments
        current_draw_x = start_x
        
        for i, (seg_text, seg_font) in enumerate(segments):
            # We use 'ls' (Left, Baseline) or 'la' (Left, Ascender) equivalent
            # But since we already adjusted start_x, we can just use default position with specific anchor?
            # No, 'draw.text' with anchor applies to the whole string relative to xy.
            # Here we are drawing parts. We must draw them left-aligned at the calculated position.
            
            # To match the vertical alignment of the requested anchor (e.g. 'mm'),
            # we need to know the baseline.
            # If anchor was 'mm', y was the middle.
            # If anchor was 'rs', y was the baseline.
            
            # Simplification: Assume most text is single line and we want baseline alignment.
            # If anchor was 'mm', we need to shift y down by half height to get baseline?
            # Pillow's 'mm' centers the bounding box.
            
            draw_anchor = "ls" # Left, Baseline (standard)
            draw_y = y
            
            if anchor == "mm":
                # If original request was Center-Middle, we calculated start_x.
                # But Y is still Middle. We need to shift to baseline?
                # Actually, if we use 'lm' (Left-Middle) for each segment, they might jitter if fonts have diff heights.
                # Better to align by baseline.
                # But we don't know the exact baseline offset from 'mm' center easily without metrics.
                # Let's fallback to 'lm' (Left-Middle) if input was 'mm' to keep it vertically centered?
                draw_anchor = "lm"
                draw_y = y
            elif anchor == "rs":
                draw_anchor = "ls"
                draw_y = y
            elif anchor is None: # Default top-left
                draw_anchor = "lt" # Left-Top? Or 'la'?
                # Pillow default is Top-Left of bounding box
                pass
            
            draw.text((current_draw_x, draw_y), seg_text, font=seg_font, fill=fill, anchor=draw_anchor)
            current_draw_x += segment_widths[i]

    async def _download_image(self, url: str) -> bytes | None:
        """Download and cache image bytes from URL (with SSRF protection and Cache Limit)"""
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
                        self.images_cache[url] = image_data
                        self.images_cache.move_to_end(url)
                        return image_data
        except Exception as e:
            log.error(f"Error downloading image from {url}: {e}")
            
        return None
    
    async def _get_user_avatar(self, user_avatar_url: str) -> Image.Image:
        """Get user avatar, with fallback to default"""
        avatar_bytes = await self._download_image(user_avatar_url)
        if avatar_bytes:
            try:
                avatar = Image.open(io.BytesIO(avatar_bytes))
                avatar = avatar.convert("RGBA")
                
                # Resize and make circular
                avatar = avatar.resize((38, 38), Image.Resampling.LANCZOS)
                
                # Create circular mask
                mask = Image.new('L', (38, 38), 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, 38, 38), fill=255)
                
                # Apply mask
                avatar.putalpha(mask)
                return avatar
            except Exception as e:
                log.error(f"Error processing avatar image: {e}")
        
        # Create default avatar
        default_avatar = Image.new('RGBA', (38, 38), (128, 128, 128, 255))
        mask = Image.new('L', (38, 38), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, 38, 38), fill=255)
        default_avatar.putalpha(mask)
        return default_avatar
    
    def _draw_skewed_bar(self, draw: ImageDraw.Draw, x: int, y: int, width: int, height: int, progress: float):
        """Draws a skewed XP bar directly onto the card"""
        skew_offset = 20  # This controls how much the bar leans to the right
        
        # 1. Draw the background track (Unfilled/Remaining XP)
        # White with low opacity (~10%)
        track_poly = [
            (x + skew_offset, y),              # Top Left
            (x + width + skew_offset, y),      # Top Right
            (x + width, y + height),           # Bottom Right
            (x, y + height)                    # Bottom Left
        ]
        draw.polygon(track_poly, fill=(255, 255, 255, 25))
        
        # 2. Draw the progress fill (Earned XP)
        # Black with medium opacity (~50%)
        if progress > 0:
            # Ensure progress doesn't exceed 1.0
            progress = min(progress, 1.0)
            fill_w = int(width * progress)
            
            # Define points for the filled portion
            fill_poly = [
                (x + skew_offset, y),              # Top Left
                (x + fill_w + skew_offset, y),     # Top Right (variable)
                (x + fill_w, y + height),          # Bottom Right (variable)
                (x, y + height)                    # Bottom Left
            ]
            
            # Draw the shape with transparency (Black with ~50% opacity)
            draw.polygon(fill_poly, fill=(0, 0, 0, 128))

    def _create_card_overlay(
        self,
        avatar: Image.Image,
        level: int,
        current_xp: int,
        required_xp: int,
        rank: int,
        username: str,
        club_icon: Image.Image | None,
        club_name: str | None,
        fonts: Dict[str, ImageFont.FreeTypeFont],
        fallback_fonts: Dict[str, list[ImageFont.FreeTypeFont]] = None
    ) -> Image.Image:
        """Create the overlay with user info (Avatar, Text, XP Bar)"""
        if fallback_fonts is None:
            fallback_fonts = {}

        # Create transparent overlay
        overlay = Image.new('RGBA', (self.card_width, self.card_height), (0, 0, 0, 0))
        
        # Draw user avatar
        overlay.paste(avatar, (11, 11), avatar)
        
        draw = ImageDraw.Draw(overlay)
        
        # Use passed fonts
        name_font = fonts['name']
        level_big_font = fonts.get('level_big', fonts['level']) # Fallback if missing
        label_font = fonts.get('label', fonts['level'])
        rank_font = fonts['rank']
        xp_font = fonts['xp']
        club_font = fonts.get('club')
        
        # Draw username (position from template)
        # Use fallback drawing for username to support special chars
        name_fallbacks = fallback_fonts.get('name', [])
        self._draw_text_with_fallback(draw, (66, 10), username, name_font, name_fallbacks, (0, 0, 0, 128)) # Shadow
        self._draw_text_with_fallback(draw, (65, 9), username, name_font, name_fallbacks, (255, 255, 255, 255))
        
        # Draw Level Number ONLY (Remove "lv." label drawing)
        # Position: Left side, big number
        draw.text((28, 98), str(level), font=level_big_font, fill=(255, 255, 255, 255))
        
        # Draw Rank Number ONLY (Remove "Rank" word)
        # Position: Slightly to the right of Level, smaller
        draw.text((90, 107), f"{rank}", font=rank_font, fill=(255, 255, 255, 255))
        
        # Draw XP Bar
        progress = 0
        if required_xp > 0:
            progress = current_xp / required_xp
            
        # Updated coordinates to fill the whole box
        # Shifted left to match the background track outline
        bar_x = 181
        bar_y = 67
        bar_w = 279
        bar_h = 79
        self._draw_skewed_bar(draw, x=bar_x, y=bar_y, width=bar_w, height=bar_h, progress=progress)
        
        # Draw XP Text (Centered in the large bar)
        xp_text = f"{current_xp}/{required_xp} XP"
        
        # Calculate center of the bar for text placement
        # skew_offset is 20, so we add half of it (10) to center horizontally
        text_x = bar_x + (bar_w // 2) + 10
        text_y = bar_y + (bar_h // 2)
        
        # Draw shadow/outline for readability (Black shadow)
        draw.text((text_x + 1, text_y + 1), xp_text, font=xp_font, fill=(0, 0, 0, 128), anchor="mm")
        # Draw main text
        draw.text((text_x, text_y), xp_text, font=xp_font, fill=(255, 255, 255, 255), anchor="mm")
        
        # Draw Club Info
        if club_icon:
            # Resize to 29x29 if needed
            if club_icon.size != (29, 29):
                club_icon = club_icon.resize((29, 29), Image.Resampling.LANCZOS)
            overlay.paste(club_icon, (451, 15), club_icon)
            
            # Draw Club Name (Right Aligned)
            if club_name and club_font:
                icon_x = 451 # The X position of the club icon
                icon_y = 34
                
                # "rs" anchor = Right align, baseline vertical alignment
                # We draw the text slightly to the left of the icon
                club_fallbacks = fallback_fonts.get('club', [])
                self._draw_text_with_fallback(
                    draw,
                    (icon_x - 10, icon_y + 10),
                    club_name,
                    club_font,
                    club_fallbacks,
                    fill=(255, 255, 255, 255),
                    anchor="rs"
                )
        
        return overlay

    def _draw_card_sync(
        self,
        username: str,
        avatar: Image.Image,
        background_bytes: bytes | None,
        club_icon: Image.Image | None,
        level: int,
        current_xp: int,
        required_xp: int,
        total_xp: int,
        rank: int,
        club_name: str | None,
        fonts: Dict[str, ImageFont.FreeTypeFont],
        fallback_fonts: Dict[str, list[ImageFont.FreeTypeFont]] = None
    ) -> Tuple[io.BytesIO, str]:
        """Synchronous method to draw the XP card (runs in thread)"""
        
        # 1. Create the overlay with all static content
        overlay = self._create_card_overlay(
            avatar, level, current_xp, required_xp, rank, username, club_icon, club_name, fonts, fallback_fonts
        )
        
        # 2. Handle Background
        if background_bytes:
            try:
                bg_image = Image.open(io.BytesIO(background_bytes))
                
                # Check if animated GIF
                is_animated = getattr(bg_image, "is_animated", False)
                
                if is_animated:
                    frames = []
                    duration = bg_image.info.get('duration', 100)
                    
                    for frame in ImageSequence.Iterator(bg_image):
                        frame = frame.convert("RGBA")
                        # Resize frame to card size (cover)
                        frame = ImageOps.fit(frame, (self.card_width, self.card_height))
                        
                        # Composite overlay on top
                        frame.alpha_composite(overlay)
                        
                        frames.append(frame)
                        
                    output = io.BytesIO()
                    # Save as GIF
                    frames[0].save(
                        output, 
                        format='GIF', 
                        save_all=True, 
                        append_images=frames[1:], 
                        loop=0, 
                        duration=duration,
                        disposal=2  # Restore to background color. 
                    )
                    output.seek(0)
                    return output, "gif"
                    
                else:
                    # Static Image
                    bg_image = bg_image.convert("RGBA")
                    bg_resized = ImageOps.fit(bg_image, (self.card_width, self.card_height))
                    
                    # Create base
                    card = Image.new('RGBA', (self.card_width, self.card_height))
                    card.paste(bg_resized, (0, 0))
                    card.alpha_composite(overlay)
                    
                    output = io.BytesIO()
                    card.save(output, format='PNG')
                    output.seek(0)
                    return output, "png"
                    
            except Exception as e:
                log.error(f"Error processing background image: {e}")
                # Fallthrough to default background color if image fails
                
        # Fallback / No background image
        card = Image.new('RGBA', (self.card_width, self.card_height), (47, 49, 54, 255))
        card.alpha_composite(overlay)
        
        output = io.BytesIO()
        card.save(output, format='PNG')
        output.seek(0)
        
        return output, "png"
    
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
    ) -> Tuple[io.BytesIO, str]:
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
        
        avatar, background_bytes, club_icon_bytes = await asyncio.gather(*tasks)
        
        # Process club icon if bytes
        club_icon = None
        if club_icon_bytes:
            try:
                club_icon = Image.open(io.BytesIO(club_icon_bytes)).convert("RGBA")
            except Exception:
                pass
        
        # Get fonts (likely cached, but keep async interface)
        fonts = {
            'name': await self._get_font(25),
            'level': await self._get_font(22),
            'level_big': await self._get_font(24, bold=True), # Big size for the number
            'label': await self._get_font(20),                # Small size for "lv."
            'rank': await self._get_font(20),
            'xp': await self._get_font(25),
            'club': await self._get_font(20) if club_name else None
        }
        
        # Prepare fallback fonts (matched to sizes used in overlay)
        fallback_fonts = {
            'name': await self._get_fallback_fonts(25),
            'club': await self._get_fallback_fonts(20) if club_name else []
        }

        # 2. Run blocking image manipulation in executor (CPU bound)
        loop = asyncio.get_running_loop()
        
        # Use functools.partial to pass arguments to the synchronous function
        draw_func = functools.partial(
            self._draw_card_sync,
            username=username,
            avatar=avatar,
            background_bytes=background_bytes,
            club_icon=club_icon,
            level=level,
            current_xp=current_xp,
            required_xp=required_xp,
            total_xp=total_xp,
            rank=rank,
            club_name=club_name,
            fonts=fonts,
            fallback_fonts=fallback_fonts
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
