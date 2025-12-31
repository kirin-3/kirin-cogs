import discord
from redbot.core import commands, app_commands
from discord import ui
from typing import Optional
from redbot.core.utils.views import ConfirmView
from ..utils import validate_club_name, validate_url, validate_text_input
from ..views import ApplicantProcessView
import asyncio

class ClubManageModal(ui.Modal, title="Manage Club"):
    name = ui.TextInput(label="Club Name", style=discord.TextStyle.short, max_length=20, required=True)
    description = ui.TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=150, required=False)
    
    # We can add a Select here if we had options like "Banner Color" or "Privacy"
    # For now, let's keep it simple with text inputs which covers rename/desc
    
    def __init__(self, cog, ctx, current_name, current_desc):
        super().__init__()
        self.cog = cog
        self.ctx = ctx
        self.name.default = current_name
        self.description.default = current_desc

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.name.value
        new_desc = self.description.value
        
        # Validate name
        if not validate_club_name(new_name):
            await interaction.response.send_message("❌ Invalid club name.", ephemeral=True)
            return

        # Pass True for admin_override because Modal is only accessible if checks passed?
        # Actually, ClubInfoView handles the button visibility logic:
        # is_owner = ctx.author.id == club_data['owner_id']
        # is_admin = ctx.author.guild_permissions.manage_guild
        # So if they see the button, they are authorized.
        # We can safely pass True for admin_override here.
        
        # Update Name
        if new_name != self.name.default:
            success, msg = await self.cog.club_system.rename_club(self.ctx.author, new_name, True)
            if not success:
                await interaction.response.send_message(f"❌ Failed to rename: {msg}", ephemeral=True)
                return
        
        # Update Description
        if new_desc != self.description.default:
            success, msg = await self.cog.club_system.set_club_description(self.ctx.author, new_desc, True)
            if not success:
                await interaction.response.send_message(f"❌ Failed to update description: {msg}", ephemeral=True)
                return
                
        await interaction.response.send_message("✅ Club updated successfully!", ephemeral=True)

class ClubInfoView(ui.View):
    def __init__(self, cog, ctx, club_data):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.club_data = club_data
        
        # Only show Manage button if owner or admin
        is_owner = ctx.author.id == club_data['owner_id']
        is_admin = ctx.author.guild_permissions.manage_guild
        
        if not (is_owner or is_admin):
            # Remove the manage button if not authorized
            # Note: We need to find the item associated with the callback
            # self.manage_button is the method.
            # In dpy 2.0+, we can just remove the item from self.children if we didn't save a ref?
            # Or simpler:
            for item in self.children:
                if isinstance(item, ui.Button) and item.custom_id == "manage_club":
                    self.remove_item(item)
                    break

    @ui.button(label="Manage Club", style=discord.ButtonStyle.primary, custom_id="manage_club")
    async def manage_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This is not your session.", ephemeral=True)
            return
        
        # Double-check permissions in case status changed
        is_owner = interaction.user.id == self.club_data['owner_id']
        is_admin = interaction.user.guild_permissions.manage_guild
        
        if not (is_owner or is_admin):
            await interaction.response.send_message("❌ You are not authorized to manage this club.", ephemeral=True)
            return
            
        modal = ClubManageModal(self.cog, self.ctx, self.club_data['name'], self.club_data['description'])
        await interaction.response.send_modal(modal)

class ClubCommands:
    @commands.hybrid_group(name="club")
    @commands.guild_only()
    async def club_group(self, ctx):
        """Club system commands"""
        pass

    @club_group.command(name="create")
    @commands.cooldown(1, 86400, commands.BucketType.user)
    async def club_create(self, ctx, club_name: str):
        """Create a new club"""
            
        if not validate_club_name(club_name):
            await ctx.send("❌ Invalid club name. Must be under 20 chars and contain only letters, numbers, and safe symbols.")
            return

        success, message = await self.club_system.create_club(ctx.author, club_name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="info", aliases=["profile"])
    @app_commands.describe(club_name="Name of the club to view (optional)")
    async def club_info(self, ctx, club_name: Optional[str] = None):
        """Get club information"""
            
        data, message = await self.club_system.get_club_info(club_name, ctx.author if not club_name else None)
        if not data:
            await ctx.reply(f"❌ {message}", mention_author=False)
            return
            
        # Format info embed
        embed = discord.Embed(
            title=f"🛡️ {data['name']}",
            description=data['description'] or "No description.",
            color=discord.Color.blue()
        )
        
        owner = ctx.guild.get_member(data['owner_id'])
        owner_name = owner.display_name if owner else f"Unknown ({data['owner_id']})"
        
        embed.add_field(name="Owner", value=owner_name, inline=True)
        embed.add_field(name="XP", value=f"{data['xp']:,}", inline=True)
        # embed.add_field(name="Level", value=str(data['level']), inline=True) # Calculate if needed
        
        if data['image_url']:
            embed.set_thumbnail(url=data['image_url'])
        if data['banner_url']:
            embed.set_image(url=data['banner_url'])
            
        # Get members
        members = await self.db.club.get_club_members(data['id'])
        member_list = []
        for m in members[:10]: # Limit display
            name = m[1]
            if m[4]: # IsAdmin
                name += " ⭐"
            if m[0] == data['owner_id']:
                name += " 👑"
            member_list.append(name)
            
        embed.add_field(name=f"Members ({len(members)})", value="\n".join(member_list) if member_list else "None", inline=False)
        
        view = ClubInfoView(self, ctx, data)
        await ctx.reply(embed=embed, view=view, mention_author=False)

    @club_group.command(name="leave")
    async def club_leave(self, ctx):
        """Leave your current club"""
            
        success, message = await self.club_system.leave_club(ctx.author)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="apply")
    async def club_apply(self, ctx, club_name: str):
        """Apply to join a club"""
            
        success, message = await self.club_system.apply_to_club(ctx.author, club_name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="accept")
    async def club_accept(self, ctx, user: discord.Member):
        """Accept a user's application (Owner only)"""
            
        success, message = await self.club_system.accept_application(ctx.author, user.name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="reject", aliases=["deny"])
    async def club_reject(self, ctx, user: discord.Member):
        """Reject a user's application (Owner only)"""
            
        success, message = await self.club_system.reject_application(ctx.author, user.name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="kick")
    async def club_kick(self, ctx, user: discord.Member):
        """Kick a user from the club (Owner/Server Mod)"""
            
        success, message = await self.club_system.kick_member(ctx.author, user.name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="ban")
    async def club_ban(self, ctx, user: discord.Member):
        """Ban a user from the club (Owner/Server Mod)"""
            
        success, message = await self.club_system.ban_member(ctx.author, user.name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="unban")
    async def club_unban(self, ctx, user: discord.Member):
        """Unban a user from the club (Owner/Server Mod)"""
            
        success, message = await self.club_system.unban_member(ctx.author, user.name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="transfer")
    async def club_transfer(self, ctx, new_owner: discord.Member):
        """Transfer club ownership (Owner only)"""
            
        success, message = await self.club_system.transfer_club(ctx.author, new_owner)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="applicants", aliases=["apps"])
    async def club_applicants(self, ctx):
        """View pending club applications (Owner only)"""
            
        applicants, message = await self.club_system.get_applicants(ctx.author)
        
        if applicants is None:
            await ctx.send(f"❌ {message}")
            return
            
        if not applicants:
            await ctx.send("📋 No pending applications.")
            return

        view = ApplicantProcessView(ctx, applicants, self.club_system)

        embed = discord.Embed(
            title="📋 Club Applications",
            description=f"There are **{len(applicants)}** pending applications.\nUse the menu below to accept or reject them.",
            color=discord.Color.blue()
        )
        view.message = await ctx.send(embed=embed, view=view)

    @club_group.command(name="bans")
    async def club_bans(self, ctx):
        """View banned members (Owner only)"""
            
        bans, message = await self.club_system.get_banned_members(ctx.author)
        
        if bans is None:
            await ctx.send(f"❌ {message}")
            return
            
        if not bans:
            await ctx.send("📋 No banned members.")
            return
            
        embed = discord.Embed(
            title="🚫 Banned Members",
            color=discord.Color.red()
        )
        
        desc = []
        for b in bans:
            desc.append(f"• **{b['username']}**")
            
        embed.description = "\n".join(desc)
        embed.set_footer(text="Use [p]club unban <user> to unban")
        
        await ctx.send(embed=embed)

    @club_group.command(name="rename")
    @commands.cooldown(1, 86400, commands.BucketType.user)
    @commands.admin_or_permissions(manage_guild=True)
    async def club_rename(self, ctx, *, new_name: str):
        """Rename the club (Owner/Server Mod)"""
        # Immediate length check to prevent DoS from massive input strings
        if len(new_name) > 20:
            await ctx.send("❌ Club name is too long (max 20 chars).")
            return

        if not validate_club_name(new_name):
            await ctx.send("❌ Invalid club name. Must be under 20 chars and contain only letters, numbers, and safe symbols.")
            return

        # Passed checks (Owner via logic or Mod via permission decorator)
        # We pass True to allow override if they have permissions
        success, message = await self.club_system.rename_club(ctx.author, new_name, True)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="icon")
    @commands.admin_or_permissions(manage_guild=True)
    async def club_icon(self, ctx, url: str):
        """Set club icon URL (Owner/Server Mod)"""
            
        if not validate_url(url):
            await ctx.send("❌ Invalid URL. Please provide a valid HTTP/HTTPS image URL.")
            return

        success, message = await self.club_system.set_club_icon(ctx.author, url, True)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="banner")
    @commands.admin_or_permissions(manage_guild=True)
    async def club_banner(self, ctx, url: str):
        """Set club banner URL (Owner/Server Mod)"""
            
        if not validate_url(url):
            await ctx.send("❌ Invalid URL. Please provide a valid HTTP/HTTPS image URL.")
            return

        success, message = await self.club_system.set_club_banner(ctx.author, url, True)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="desc")
    @commands.admin_or_permissions(manage_guild=True)
    async def club_desc(self, ctx, *, description: str):
        """Set club description (Owner/Server Mod)"""
        # Immediate length check to prevent DoS from massive input strings
        if len(description) > 150:
            await ctx.send("❌ Description is too long (max 150 chars).")
            return

        if not validate_text_input(description, max_length=150):
            await ctx.send("❌ Description is too long (max 150 chars).")
            return

        success, message = await self.club_system.set_club_description(ctx.author, description, True)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="disband")
    @commands.cooldown(1, 86400, commands.BucketType.user)
    @commands.admin_or_permissions(manage_guild=True)
    async def club_disband(self, ctx):
        """Disband the club (Owner/Server Mod)"""
            
        view = ConfirmView(ctx.author)
        msg = await ctx.send("⚠️ Are you sure you want to disband your club? This cannot be undone.", view=view)
        await view.wait()
        
        if not view.result:
            await msg.edit(content="❌ Disband cancelled.")
            return

        success, message = await self.club_system.disband_club(ctx.author)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="leaderboard", aliases=["lb"])
    @app_commands.describe(page="Page number")
    async def club_leaderboard(self, ctx, page: int = 1):
        """Show club leaderboard"""
            
        clubs = await self.club_system.get_leaderboard(page)
        if not clubs:
            await ctx.reply("No clubs found.", mention_author=False)
            return
            
        embed = discord.Embed(
            title=f"🏆 Club Leaderboard (Page {page})",
            color=discord.Color.gold()
        )
        
        for i, (name, xp) in enumerate(clubs):
            idx = (page - 1) * 9 + i + 1
            embed.add_field(name=f"#{idx} {name}", value=f"{xp:,} XP", inline=False)
            
        await ctx.send(embed=embed)
