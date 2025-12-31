import discord
from redbot.core import commands, checks, app_commands
from redbot.core.utils.views import SimpleMenu
from typing import Optional
from ..views import LeaderboardView

class LevelCommands:
    # Level commands
    @commands.hybrid_command(name="xplb")
    async def xplb_shortcut(self, ctx):
        """Show the XP leaderboard for this server"""
        await self.level_leaderboard(ctx)

    @commands.hybrid_group(name="level", aliases=["lvl", "xp"], invoke_without_command=True)
    async def level_group(self, ctx, member: Optional[discord.Member] = None):
        """Level and XP commands"""
        # If no subcommand is invoked, behave like the check command
        if ctx.invoked_subcommand is None:
            await self._level_check_logic(ctx, member)

    @commands.hybrid_command(name="xp")
    @app_commands.describe(member="The user to check XP for")
    async def xp_command(self, ctx, member: Optional[discord.Member] = None):
        """Check your or another user's level and XP"""
        await self._level_check_logic(ctx, member)
    
    @level_group.command(name="check", aliases=["me"])
    @app_commands.describe(member="The user to check XP for")
    async def level_check(self, ctx, member: discord.Member = None):
        """Check your or another user's level and XP"""
        await self._level_check_logic(ctx, member)

    async def _level_check_logic(self, ctx, member: discord.Member = None):
        """Logic for checking level/XP"""
        if not await self.config.xp_enabled():
            await ctx.reply("❌ XP system is disabled.", mention_author=False)
            return
        
        member = member or ctx.author
        
        try:
            level_stats = await self.xp_system.get_user_level_stats(member.id, ctx.guild.id)
            user_rank = await self.db.xp.get_user_rank_in_guild(member.id, ctx.guild.id)
            
            # Get user's active background
            active_background = await self.db.xp.get_active_xp_item(member.id, 1)  # 1 = Background
            
            # Get club info for card
            club_icon_url = None
            club_name = None
            club = await self.db.club.get_club_by_member(member.id)
            if club:
                # Club tuple: Id, Name, Description, ImageUrl, BannerUrl, Xp, OwnerId, DateAdded
                club_name = club[1]
                club_icon_url = club[3]
            
            # Generate XP card
            try:
                card_image_bytes, ext = await self.xp_system.card_generator.generate_xp_card(
                    member.id,
                    member.display_name,
                    str(member.avatar.url) if member.avatar else str(member.default_avatar.url),
                    level_stats.level,
                    level_stats.level_xp,
                    level_stats.required_xp,
                    level_stats.total_xp,
                    user_rank,
                    active_background,
                    club_icon_url,
                    club_name
                )
                
                if card_image_bytes:
                    file = discord.File(card_image_bytes, filename=f"xp_card.{ext}")
                    await ctx.reply(file=file, mention_author=False)
                    return
                    
            except Exception as e:
                import logging
                log = logging.getLogger("red.unicornia")
                log.error(f"Error generating XP card for {member.display_name}: {e}")
                # Fall back to embed if card generation fails
            
            # Fallback embed if XP card generation fails
            embed = discord.Embed(
                title=f"{member.display_name}'s Level",
                color=member.color or discord.Color.blue()
            )
            embed.add_field(name="Level", value=level_stats.level, inline=True)
            embed.add_field(name="XP", value=f"{level_stats.level_xp:,}/{level_stats.required_xp:,}", inline=True)
            embed.add_field(name="Total XP", value=f"{level_stats.total_xp:,}", inline=True)
            embed.add_field(name="Rank", value=f"#{user_rank}", inline=True)
            
            # Progress bar
            progress_bar = self.xp_system.get_progress_bar(level_stats.level_xp, level_stats.required_xp)
            embed.add_field(name="Progress", value=f"`{progress_bar}` {level_stats.level_xp/level_stats.required_xp:.1%}", inline=False)
            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
            embed.set_footer(text=f"Active background: {active_background}")
            
            await ctx.reply(embed=embed, mention_author=False)
            
        except Exception as e:
            import logging
            log = logging.getLogger("red.unicornia")
            log.error(f"Error in level check for {member.display_name}: {e}", exc_info=True)
            await ctx.reply(f"❌ Error retrieving level data: {e}", mention_author=False)
    
    @level_group.command(name="leaderboard", aliases=["lb", "top"])
    @app_commands.describe(limit="Number of users to show")
    async def level_leaderboard(self, ctx, limit: int = 10):
        """Show the XP leaderboard for this server"""
        if not await self.config.xp_enabled():
            await ctx.reply("❌ XP system is disabled.", mention_author=False)
            return
        
        try:
            # Use filtered leaderboard (only members in server)
            top_users = await self.xp_system.get_filtered_leaderboard(ctx.guild)
            
            if not top_users:
                await ctx.reply("No XP data found for this server.", mention_author=False)
                return
            
            # Find user position
            user_position = None
            for i, (uid, _) in enumerate(top_users):
                if uid == ctx.author.id:
                    user_position = i
                    break
            
            def xp_formatter(rank, rank_str, member, user_id, xp):
                username = member.display_name if member else f"User ID: {user_id}"
                level_stats = self.db.calculate_level_stats(xp)
                return f"{rank_str} **{username}**\nLevel **{level_stats.level}** • {xp:,} XP\n"

            view = LeaderboardView(
                ctx,
                top_users,
                user_position=user_position,
                currency_symbol="",
                title=f"XP Leaderboard - {ctx.guild.name}",
                formatter=xp_formatter
            )
            embed = await view.get_embed()
            view.message = await ctx.reply(embed=embed, view=view, mention_author=False)
            
        except Exception as e:
            import logging
            log = logging.getLogger("red.unicornia")
            log.error(f"Error in xp leaderboard: {e}", exc_info=True)
            await ctx.reply(f"❌ Error retrieving leaderboard: {e}", mention_author=False)
