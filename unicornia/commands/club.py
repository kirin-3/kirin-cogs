import discord
from redbot.core import commands
from typing import Optional
from ..utils import systems_ready

class ClubCommands:
    @commands.group(name="club")
    async def club_group(self, ctx):
        """Club system commands"""
        pass

    @club_group.command(name="create")
    @commands.cooldown(1, 86400, commands.BucketType.user)
    @systems_ready
    async def club_create(self, ctx, club_name: str):
        """Create a new club"""
            
        if not self._validate_club_name(club_name):
            await ctx.send("❌ Invalid club name. Must be under 20 chars and contain only letters, numbers, and safe symbols.")
            return

        success, message = await self.club_system.create_club(ctx.author, club_name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="info", aliases=["profile"])
    @systems_ready
    async def club_info(self, ctx, club_name: Optional[str] = None):
        """Get club information"""
            
        data, message = await self.club_system.get_club_info(club_name, ctx.author if not club_name else None)
        if not data:
            await ctx.send(f"❌ {message}")
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
        
        await ctx.send(embed=embed)

    @club_group.command(name="leave")
    @systems_ready
    async def club_leave(self, ctx):
        """Leave your current club"""
            
        success, message = await self.club_system.leave_club(ctx.author)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="apply")
    @systems_ready
    async def club_apply(self, ctx, club_name: str):
        """Apply to join a club"""
            
        success, message = await self.club_system.apply_to_club(ctx.author, club_name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="accept")
    @systems_ready
    async def club_accept(self, ctx, user: discord.Member):
        """Accept a user's application (Owner only)"""
            
        success, message = await self.club_system.accept_application(ctx.author, user.name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="reject", aliases=["deny"])
    @systems_ready
    async def club_reject(self, ctx, user: discord.Member):
        """Reject a user's application (Owner only)"""
            
        success, message = await self.club_system.reject_application(ctx.author, user.name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="kick")
    @systems_ready
    async def club_kick(self, ctx, user: discord.Member):
        """Kick a user from the club (Owner/Server Mod)"""
            
        success, message = await self.club_system.kick_member(ctx.author, user.name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="ban")
    @systems_ready
    async def club_ban(self, ctx, user: discord.Member):
        """Ban a user from the club (Owner/Server Mod)"""
            
        success, message = await self.club_system.ban_member(ctx.author, user.name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="unban")
    @systems_ready
    async def club_unban(self, ctx, user: discord.Member):
        """Unban a user from the club (Owner/Server Mod)"""
            
        success, message = await self.club_system.unban_member(ctx.author, user.name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="transfer")
    @systems_ready
    async def club_transfer(self, ctx, new_owner: discord.Member):
        """Transfer club ownership (Owner only)"""
            
        success, message = await self.club_system.transfer_club(ctx.author, new_owner)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="applicants", aliases=["apps"])
    @systems_ready
    async def club_applicants(self, ctx):
        """View pending club applications (Owner only)"""
            
        applicants, message = await self.club_system.get_applicants(ctx.author)
        
        if applicants is None:
            await ctx.send(f"❌ {message}")
            return
            
        if not applicants:
            await ctx.send("📋 No pending applications.")
            return
            
        embed = discord.Embed(
            title="📋 Club Applications",
            color=discord.Color.blue()
        )
        
        desc = []
        for a in applicants:
            desc.append(f"• **{a['username']}** (XP: {a['total_xp']:,})")
            
        embed.description = "\n".join(desc)
        embed.set_footer(text="Use [p]club accept <user> or [p]club reject <user>")
        
        await ctx.send(embed=embed)

    @club_group.command(name="bans")
    @systems_ready
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
    @systems_ready
    async def club_rename(self, ctx, *, new_name: str):
        """Rename the club (Owner/Server Mod)"""
            
        if not self._validate_club_name(new_name):
            await ctx.send("❌ Invalid club name. Must be under 20 chars and contain only letters, numbers, and safe symbols.")
            return

        is_admin = ctx.author.guild_permissions.administrator
        success, message = await self.club_system.rename_club(ctx.author, new_name, is_admin)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="icon")
    @commands.admin_or_permissions(manage_guild=True)
    @systems_ready
    async def club_icon(self, ctx, url: str):
        """Set club icon URL (Owner/Server Mod)"""
            
        if not self._validate_url(url):
            await ctx.send("❌ Invalid URL. Please provide a valid HTTP/HTTPS image URL.")
            return

        is_admin = ctx.author.guild_permissions.administrator
        success, message = await self.club_system.set_club_icon(ctx.author, url, is_admin)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="banner")
    @commands.admin_or_permissions(manage_guild=True)
    @systems_ready
    async def club_banner(self, ctx, url: str):
        """Set club banner URL (Owner/Server Mod)"""
            
        if not self._validate_url(url):
            await ctx.send("❌ Invalid URL. Please provide a valid HTTP/HTTPS image URL.")
            return

        is_admin = ctx.author.guild_permissions.administrator
        success, message = await self.club_system.set_club_banner(ctx.author, url, is_admin)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="desc")
    @commands.admin_or_permissions(manage_guild=True)
    @systems_ready
    async def club_desc(self, ctx, *, description: str):
        """Set club description (Owner/Server Mod)"""
            
        is_admin = ctx.author.guild_permissions.administrator
        success, message = await self.club_system.set_club_description(ctx.author, description, is_admin)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="disband")
    @commands.cooldown(1, 86400, commands.BucketType.user)
    @commands.admin_or_permissions(manage_guild=True)
    @systems_ready
    async def club_disband(self, ctx):
        """Disband the club (Owner/Server Mod)"""
            
        await ctx.send("⚠️ Are you sure you want to disband your club? Type `yes` to confirm.")
        try:
            msg = await self.bot.wait_for("message", check=lambda m: m.author == ctx.author and m.channel == ctx.channel, timeout=30)
            if msg.content.lower() != "yes":
                await ctx.send("❌ Disband cancelled.")
                return
        except asyncio.TimeoutError:
            await ctx.send("❌ Timed out. Disband cancelled.")
            return
            
        success, message = await self.club_system.disband_club(ctx.author)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @club_group.command(name="leaderboard", aliases=["lb"])
    @systems_ready
    async def club_leaderboard(self, ctx, page: int = 1):
        """Show club leaderboard"""
            
        clubs = await self.club_system.get_leaderboard(page)
        if not clubs:
            await ctx.send("No clubs found.")
            return
            
        embed = discord.Embed(
            title=f"🏆 Club Leaderboard (Page {page})",
            color=discord.Color.gold()
        )
        
        for i, (name, xp) in enumerate(clubs):
            idx = (page - 1) * 9 + i + 1
            embed.add_field(name=f"#{idx} {name}", value=f"{xp:,} XP", inline=False)
            
        await ctx.send(embed=embed)
