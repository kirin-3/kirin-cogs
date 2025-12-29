"""
Club system for Unicornia - Logic for club management
"""

import discord
from typing import Optional, List, Dict, Any, Tuple
from redbot.core import commands
from ..database import DatabaseManager

class ClubSystem:
    """Handles club logic and management"""
    
    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot
    
    async def create_club(self, user: discord.Member, club_name: str) -> Tuple[bool, str]:
        """Create a new club"""
        # Check if name is valid
        if len(club_name) > 20:
            return False, "Club name is too long (max 20 chars)."
        
        # Check if user is already in a club
        user_club = await self.db.club.get_club_by_member(user.id)
        if user_club:
            return False, "You are already in a club."
        
        # Check if name is taken
        existing_club = await self.db.club.get_club_by_name(club_name)
        if existing_club:
            return False, "A club with that name already exists."
        
        # Create club
        try:
            club_id = await self.db.club.create_club(user.id, club_name)
            return True, f"Club **{club_name}** created successfully!"
        except Exception as e:
            return False, f"Error creating club: {e}"

    async def get_club_info(self, club_identifier: str = None, user: discord.Member = None) -> Tuple[Optional[Dict[str, Any]], str]:
        """Get club info by name or member"""
        club = None
        
        if club_identifier:
            club = await self.db.club.get_club_by_name(club_identifier)
            if not club:
                return None, "Club not found."
        elif user:
            club = await self.db.club.get_club_by_member(user.id)
            if not club:
                return None, "User is not in a club."
        else:
            return None, "Please specify a club name or user."
            
        # Club tuple: Id, Name, Description, ImageUrl, BannerUrl, Xp, OwnerId, DateAdded
        club_data = {
            'id': club[0],
            'name': club[1],
            'description': club[2],
            'image_url': club[3],
            'banner_url': club[4],
            'xp': club[5],
            'owner_id': club[6],
            'date_added': club[7]
        }
        
        return club_data, "Success"

    async def transfer_club(self, owner: discord.Member, new_owner: discord.Member) -> Tuple[bool, str]:
        """Transfer club ownership"""
        club = await self.db.club.get_club_by_member(owner.id)
        if not club:
            return False, "You are not in a club."
            
        if club[6] != owner.id:  # OwnerId
            return False, "You are not the owner of this club."
            
        target_club = await self.db.club.get_club_by_member(new_owner.id)
        if not target_club or target_club[0] != club[0]:
            return False, "Target user must be a member of your club."
            
        await self.db.club.update_club_settings(club[0], OwnerId=new_owner.id)
        
        # Update IsClubAdmin flags for consistency (Owner is always admin, others are not)
        await self.db.club.toggle_club_admin(owner.id, False)
        await self.db.club.toggle_club_admin(new_owner.id, True)
        
        return True, f"Club ownership transferred to **{new_owner.display_name}**."

    async def set_club_icon(self, user: discord.Member, url: str, is_admin: bool = False) -> Tuple[bool, str]:
        """Set club icon"""
        club = await self.db.club.get_club_by_member(user.id)
        if not club:
            return False, "You are not in a club."
            
        # is_admin passed from command is ctx.author.guild_permissions.administrator
        # We should also check manage_guild if passed or check owner
        if not is_admin and not user.guild_permissions.manage_guild and club[6] != user.id:
            return False, "You are not the owner of this club."
            
        await self.db.club.update_club_settings(club[0], ImageUrl=url)
        return True, "Club icon updated."

    async def set_club_banner(self, user: discord.Member, url: str, is_admin: bool = False) -> Tuple[bool, str]:
        """Set club banner"""
        club = await self.db.club.get_club_by_member(user.id)
        if not club:
            return False, "You are not in a club."
            
        if not is_admin and not user.guild_permissions.manage_guild and club[6] != user.id:
            return False, "You are not the owner of this club."
            
        await self.db.club.update_club_settings(club[0], BannerUrl=url)
        return True, "Club banner updated."

    async def set_club_description(self, user: discord.Member, desc: str, is_admin: bool = False) -> Tuple[bool, str]:
        """Set club description"""
        club = await self.db.club.get_club_by_member(user.id)
        if not club:
            return False, "You are not in a club."
            
        if not is_admin and not user.guild_permissions.manage_guild and club[6] != user.id:
            return False, "You are not the owner of this club."
            
        if len(desc) > 150:
            return False, "Description is too long (max 150 chars)."
            
        # Sanitize input
        desc = discord.utils.escape_mentions(desc)
            
        await self.db.club.update_club_settings(club[0], Description=desc)
        return True, "Club description updated."

    async def rename_club(self, user: discord.Member, new_name: str, is_admin: bool = False) -> Tuple[bool, str]:
        """Rename club"""
        club = await self.db.club.get_club_by_member(user.id)
        if not club:
            return False, "You are not in a club."
            
        if not is_admin and not user.guild_permissions.manage_guild and club[6] != user.id:
            return False, "You are not the owner of this club."
            
        if len(new_name) > 20:
            return False, "Name is too long (max 20 chars)."
            
        # Sanitize input
        new_name = discord.utils.escape_mentions(new_name)
            
        existing = await self.db.club.get_club_by_name(new_name)
        if existing:
            return False, "A club with that name already exists."
            
        await self.db.club.update_club_settings(club[0], Name=new_name)
        return True, f"Club renamed to **{new_name}**."

    async def disband_club(self, user: discord.Member) -> Tuple[bool, str]:
        """Disband club"""
        club = await self.db.club.get_club_by_member(user.id)
        
        is_server_mod = user.guild_permissions.manage_guild
        if not club:
             return False, "You are not in a club."

        if not is_server_mod and club[6] != user.id:
            return False, "You are not the owner of this club."
            
        await self.db.club.disband_club(club[0])
        return True, f"Club **{club[1]}** has been disbanded."

    async def leave_club(self, user: discord.Member) -> Tuple[bool, str]:
        """Leave club"""
        club = await self.db.club.get_club_by_member(user.id)
        if not club:
            return False, "You are not in a club."
            
        if club[6] == user.id:
            return False, "Owner cannot leave the club. Transfer ownership or disband."
            
        await self.db.club.leave_club(user.id)
        return True, f"You have left **{club[1]}**."

    async def apply_to_club(self, user: discord.Member, club_name: str) -> Tuple[bool, str]:
        """Apply to a club"""
        user_club = await self.db.club.get_club_by_member(user.id)
        if user_club:
            return False, "You are already in a club."
            
        target_club = await self.db.club.get_club_by_name(club_name)
        if not target_club:
            return False, "Club not found."
            
        if await self.db.club.check_club_ban(target_club[0], user.id):
            return False, "You are banned from this club."
            
        if await self.db.club.check_club_application(target_club[0], user.id):
            return False, "You have already applied to this club."
            
        await self.db.club.apply_to_club(user.id, target_club[0])
        return True, f"Applied to **{target_club[1]}**."

    async def accept_application(self, admin: discord.Member, applicant_name: str) -> Tuple[bool, str]:
        """Accept a club application"""
        club = await self.db.club.get_club_by_member(admin.id)
        if not club:
            return False, "You are not in a club."
            
        is_server_mod = admin.guild_permissions.manage_guild
        
        # Perms: Club Owner OR Server Mod
        if not is_server_mod and club[6] != admin.id:
            return False, "Only the club owner can accept applications."
            
        # Find applicant by name (simple search)
        applicants = await self.db.club.get_club_applicants(club[0])
        # applicant tuple: UserId, Username, AvatarId, TotalXp
        target = next((a for a in applicants if a[1].lower() == applicant_name.lower()), None)
        
        if not target:
            return False, "Applicant not found."
            
        await self.db.club.accept_club_application(club[0], target[0])
        return True, f"Accepted **{target[1]}** into the club."

    async def reject_application(self, admin: discord.Member, applicant_name: str) -> Tuple[bool, str]:
        """Reject a club application"""
        club = await self.db.club.get_club_by_member(admin.id)
        if not club:
            return False, "You are not in a club."
            
        is_server_mod = admin.guild_permissions.manage_guild
        
        # Perms: Club Owner OR Server Mod
        if not is_server_mod and club[6] != admin.id:
            return False, "Only the club owner can reject applications."
            
        applicants = await self.db.club.get_club_applicants(club[0])
        target = next((a for a in applicants if a[1].lower() == applicant_name.lower()), None)
        
        if not target:
            return False, "Applicant not found."
            
        await self.db.club.reject_club_application(club[0], target[0])
        return True, f"Rejected application from **{target[1]}**."

    async def kick_member(self, admin: discord.Member, member_name: str) -> Tuple[bool, str]:
        """Kick a member"""
        club = await self.db.club.get_club_by_member(admin.id)
        
        if not club:
            return False, "You are not in a club."
            
        is_server_mod = admin.guild_permissions.manage_guild
        if not is_server_mod and club[6] != admin.id:
            return False, "Only the club owner can kick members."
            
        members = await self.db.club.get_club_members(club[0])
        target = next((m for m in members if m[1].lower() == member_name.lower()), None)
        
        if not target:
            return False, "User not found in club."
            
        if target[0] == club[6]: # Owner
            return False, "Cannot kick the owner."
            
        await self.db.club.kick_club_member(target[0])
        return True, f"Kicked **{target[1]}** from the club."

    async def ban_member(self, admin: discord.Member, member_name: str) -> Tuple[bool, str]:
        """Ban a member"""
        club = await self.db.club.get_club_by_member(admin.id)
        if not club:
            return False, "You are not in a club."
            
        is_server_mod = admin.guild_permissions.manage_guild
        
        if not is_server_mod and club[6] != admin.id:
            return False, "Only the club owner can ban members."
            
        members = await self.db.club.get_club_members(club[0])
        target = next((m for m in members if m[1].lower() == member_name.lower()), None)
        
        if not target:
            return False, "User not found in club."
            
        if target[0] == club[6]:
            return False, "Cannot ban the owner."
            
        await self.db.club.ban_club_member(club[0], target[0])
        return True, f"Banned **{target[1]}** from the club."

    async def unban_member(self, admin: discord.Member, member_name: str) -> Tuple[bool, str]:
        """Unban a member"""
        club = await self.db.club.get_club_by_member(admin.id)
        if not club:
            return False, "You are not in a club."
            
        is_server_mod = admin.guild_permissions.manage_guild
        
        if not is_server_mod and club[6] != admin.id:
            return False, "Only the club owner can unban members."
            
        bans = await self.db.club.get_club_bans(club[0])
        target = next((b for b in bans if b[1].lower() == member_name.lower()), None)
        
        if not target:
            return False, "User not found in ban list."
            
        await self.db.club.unban_club_member(club[0], target[0])
        return True, f"Unbanned **{target[1]}**."

    async def get_members(self, club_id: int) -> List[Dict[str, Any]]:
        """Get formatted list of members"""
        members = await self.db.club.get_club_members(club_id)
        # Tuple: UserId, Username, AvatarId, TotalXp, IsClubAdmin
        return [
            {
                'user_id': m[0],
                'username': m[1],
                'avatar_id': m[2],
                'total_xp': m[3],
                'is_admin': bool(m[4])
            }
            for m in members
        ]

    async def get_leaderboard(self, page: int = 1) -> List[Tuple[str, int]]:
        """Get club leaderboard"""
        # page is 1-based index
        data = await self.db.club.get_club_leaderboard_page(page - 1)
        # Tuple: Id, Name, Xp
        return [(d[1], d[2]) for d in data]

    async def get_applicants(self, user: discord.Member) -> Tuple[Optional[List[Dict]], str]:
        """Get list of club applicants"""
        club = await self.db.club.get_club_by_member(user.id)
        if not club:
            return None, "You are not in a club."
            
        is_server_mod = user.guild_permissions.manage_guild
        if not is_server_mod and club[6] != user.id:
            return None, "Only the club owner can view applicants."
            
        applicants = await self.db.club.get_club_applicants(club[0])
        # applicant tuple: UserId, Username, AvatarId, TotalXp
        
        return [
            {
                'user_id': a[0],
                'username': a[1],
                'avatar_id': a[2],
                'total_xp': a[3]
            }
            for a in applicants
        ], "Success"

    async def get_banned_members(self, user: discord.Member) -> Tuple[Optional[List[Dict]], str]:
        """Get list of banned members"""
        club = await self.db.club.get_club_by_member(user.id)
        if not club:
            return None, "You are not in a club."
            
        is_server_mod = user.guild_permissions.manage_guild
        if not is_server_mod and club[6] != user.id:
            return None, "Only the club owner can view bans."
            
        bans = await self.db.club.get_club_bans(club[0])
        # ban tuple: UserId, Username, AvatarId, TotalXp
        
        return [
            {
                'user_id': b[0],
                'username': b[1],
                'avatar_id': b[2],
                'total_xp': b[3]
            }
            for b in bans
        ], "Success"