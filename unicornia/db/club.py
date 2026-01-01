from typing import List, Optional, Tuple

class ClubRepository:
    """Repository for Club system database operations"""
    
    def __init__(self, db):
        self.db = db

    async def create_club(self, owner_id: int, name: str) -> int:
        """Create a new club.
        
        Args:
            owner_id: Discord user ID of the owner.
            name: Name of the club.
            
        Returns:
            The ID of the newly created club.
        """
        async with self.db._get_connection() as db:
            
            # Insert club
            cursor = await db.execute("""
                INSERT INTO Clubs (Name, OwnerId, Xp) VALUES (?, ?, 0)
            """, (name, owner_id))
            club_id = cursor.lastrowid
            
            # Update user
            await db.execute("""
                UPDATE DiscordUser
                SET ClubId = ?, IsClubAdmin = 1
                WHERE UserId = ?
            """, (club_id, owner_id))
            
            await db.commit()
            return club_id

    async def get_club(self, club_id: int) -> Optional[Tuple]:
        """Get club by ID.
        
        Args:
            club_id: Club ID.
            
        Returns:
            Club tuple or None.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, Name, Description, ImageUrl, BannerUrl, Xp, OwnerId, DateAdded
                FROM Clubs WHERE Id = ?
            """, (club_id,))
            return await cursor.fetchone()

    async def get_club_by_name(self, name: str) -> Optional[Tuple]:
        """Get club by name.
        
        Args:
            name: Club name.
            
        Returns:
            Club tuple or None.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, Name, Description, ImageUrl, BannerUrl, Xp, OwnerId, DateAdded
                FROM Clubs WHERE Name = ? COLLATE NOCASE
            """, (name,))
            return await cursor.fetchone()

    async def get_club_by_member(self, user_id: int) -> Optional[Tuple]:
        """Get club by member user ID.
        
        Args:
            user_id: Discord user ID.
            
        Returns:
            Club tuple or None.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT c.Id, c.Name, c.Description, c.ImageUrl, c.BannerUrl, c.Xp, c.OwnerId, c.DateAdded
                FROM Clubs c
                JOIN DiscordUser u ON c.Id = u.ClubId
                WHERE u.UserId = ?
            """, (user_id,))
            return await cursor.fetchone()

    async def get_club_members(self, club_id: int) -> List[Tuple]:
        """Get all members of a club.
        
        Args:
            club_id: Club ID.
            
        Returns:
            List of member tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT UserId, Username, AvatarId, TotalXp, IsClubAdmin
                FROM DiscordUser WHERE ClubId = ?
            """, (club_id,))
            return await cursor.fetchall()

    async def get_club_applicants(self, club_id: int) -> List[Tuple]:
        """Get applicants for a club.
        
        Args:
            club_id: Club ID.
            
        Returns:
            List of applicant tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT u.UserId, u.Username, u.AvatarId, u.TotalXp
                FROM ClubApplicants ca
                JOIN DiscordUser u ON ca.UserId = u.UserId
                WHERE ca.ClubId = ?
            """, (club_id,))
            return await cursor.fetchall()

    async def get_club_bans(self, club_id: int) -> List[Tuple]:
        """Get banned users for a club.
        
        Args:
            club_id: Club ID.
            
        Returns:
            List of banned user tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT u.UserId, u.Username, u.AvatarId, u.TotalXp
                FROM ClubBans cb
                JOIN DiscordUser u ON cb.UserId = u.UserId
                WHERE cb.ClubId = ?
            """, (club_id,))
            return await cursor.fetchall()

    async def check_club_application(self, club_id: int, user_id: int) -> bool:
        """Check if user applied to club"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT 1 FROM ClubApplicants WHERE ClubId = ? AND UserId = ?
            """, (club_id, user_id))
            return await cursor.fetchone() is not None

    async def check_club_ban(self, club_id: int, user_id: int) -> bool:
        """Check if user is banned from club"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT 1 FROM ClubBans WHERE ClubId = ? AND UserId = ?
            """, (club_id, user_id))
            return await cursor.fetchone() is not None

    async def check_club_invitation(self, club_id: int, user_id: int) -> bool:
        """Check if user is invited to club"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT 1 FROM ClubInvitations WHERE ClubId = ? AND UserId = ?
            """, (club_id, user_id))
            return await cursor.fetchone() is not None

    async def get_user_invitations(self, user_id: int) -> List[Tuple]:
        """Get list of clubs inviting the user.
        
        Args:
            user_id: Discord user ID.
            
        Returns:
            List of club tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT c.Id, c.Name, c.Description, c.ImageUrl, c.BannerUrl, c.Xp, c.OwnerId, c.DateAdded
                FROM ClubInvitations ci
                JOIN Clubs c ON ci.ClubId = c.Id
                WHERE ci.UserId = ?
            """, (user_id,))
            return await cursor.fetchall()

    async def invite_to_club(self, club_id: int, user_id: int) -> None:
        """Invite user to club.
        
        Args:
            club_id: Club ID.
            user_id: Discord user ID.
        """
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT OR IGNORE INTO ClubInvitations (ClubId, UserId) VALUES (?, ?)
            """, (club_id, user_id))
            await db.commit()

    async def remove_invitation(self, club_id: int, user_id: int) -> None:
        """Remove invitation.
        
        Args:
            club_id: Club ID.
            user_id: Discord user ID.
        """
        async with self.db._get_connection() as db:
            await db.execute("""
                DELETE FROM ClubInvitations WHERE ClubId = ? AND UserId = ?
            """, (club_id, user_id))
            await db.commit()

    async def apply_to_club(self, user_id: int, club_id: int) -> None:
        """Apply to join a club.
        
        Args:
            user_id: Discord user ID.
            club_id: Club ID.
        """
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT OR IGNORE INTO ClubApplicants (ClubId, UserId) VALUES (?, ?)
            """, (club_id, user_id))
            await db.commit()

    async def accept_club_application(self, club_id: int, user_id: int) -> None:
        """Accept a club application.
        
        Args:
            club_id: Club ID.
            user_id: Discord user ID.
        """
        async with self.db._get_connection() as db:
            
            # Remove application
            await db.execute("""
                DELETE FROM ClubApplicants WHERE ClubId = ? AND UserId = ?
            """, (club_id, user_id))
            
            # Update user
            await db.execute("""
                UPDATE DiscordUser SET ClubId = ?, IsClubAdmin = 0 WHERE UserId = ?
            """, (club_id, user_id))
            
            await db.commit()

    async def reject_club_application(self, club_id: int, user_id: int) -> None:
        """Reject a club application.
        
        Args:
            club_id: Club ID.
            user_id: Discord user ID.
        """
        async with self.db._get_connection() as db:
            await db.execute("""
                DELETE FROM ClubApplicants WHERE ClubId = ? AND UserId = ?
            """, (club_id, user_id))
            await db.commit()

    async def leave_club(self, user_id: int) -> None:
        """Leave current club.
        
        Args:
            user_id: Discord user ID.
        """
        async with self.db._get_connection() as db:
            await db.execute("""
                UPDATE DiscordUser SET ClubId = NULL, IsClubAdmin = 0 WHERE UserId = ?
            """, (user_id,))
            await db.commit()

    async def kick_club_member(self, user_id: int) -> None:
        """Kick member from club.
        
        Args:
            user_id: Discord user ID.
        """
        await self.leave_club(user_id)

    async def ban_club_member(self, club_id: int, user_id: int) -> None:
        """Ban member from club.
        
        Args:
            club_id: Club ID.
            user_id: Discord user ID.
        """
        async with self.db._get_connection() as db:
            
            # Remove from club if member
            await db.execute("""
                UPDATE DiscordUser SET ClubId = NULL, IsClubAdmin = 0 WHERE UserId = ?
            """, (user_id,))
            
            # Remove application if exists
            await db.execute("""
                DELETE FROM ClubApplicants WHERE ClubId = ? AND UserId = ?
            """, (club_id, user_id))

            # Remove invitation if exists
            await db.execute("""
                DELETE FROM ClubInvitations WHERE ClubId = ? AND UserId = ?
            """, (club_id, user_id))
            
            # Add ban
            await db.execute("""
                INSERT OR IGNORE INTO ClubBans (ClubId, UserId) VALUES (?, ?)
            """, (club_id, user_id))
            
            await db.commit()

    async def unban_club_member(self, club_id: int, user_id: int) -> None:
        """Unban member from club.
        
        Args:
            club_id: Club ID.
            user_id: Discord user ID.
        """
        async with self.db._get_connection() as db:
            await db.execute("""
                DELETE FROM ClubBans WHERE ClubId = ? AND UserId = ?
            """, (club_id, user_id))
            await db.commit()

    async def disband_club(self, club_id: int) -> None:
        """Disband a club.
        
        Args:
            club_id: Club ID.
        """
        async with self.db._get_connection() as db:
            
            # Remove all members
            await db.execute("""
                UPDATE DiscordUser SET ClubId = NULL, IsClubAdmin = 0 WHERE ClubId = ?
            """, (club_id,))
            
            # Delete bans and applications
            await db.execute("DELETE FROM ClubApplicants WHERE ClubId = ?", (club_id,))
            await db.execute("DELETE FROM ClubBans WHERE ClubId = ?", (club_id,))
            await db.execute("DELETE FROM ClubInvitations WHERE ClubId = ?", (club_id,))
            
            # Delete club
            await db.execute("DELETE FROM Clubs WHERE Id = ?", (club_id,))
            
            await db.commit()

    async def update_club_settings(self, club_id: int, **kwargs) -> None:
        """Update club settings.
        
        Args:
            club_id: Club ID.
            **kwargs: Settings to update (Name, Description, ImageUrl, BannerUrl, OwnerId).
        """
        if not kwargs:
            return
            
        async with self.db._get_connection() as db:
            
            updates = []
            params = []
            allowed_columns = ['Name', 'Description', 'ImageUrl', 'BannerUrl', 'OwnerId']
            
            for column in allowed_columns:
                if column in kwargs:
                    updates.append(f"{column} = ?")
                    params.append(kwargs[column])
            
            if not updates:
                return
                
            params.append(club_id)
            query = f"UPDATE Clubs SET {', '.join(updates)} WHERE Id = ?"
            
            await db.execute(query, params)
            await db.commit()

    async def toggle_club_admin(self, user_id: int, is_admin: bool) -> None:
        """Toggle club admin status for a user.
        
        Args:
            user_id: Discord user ID.
            is_admin: Admin status.
        """
        async with self.db._get_connection() as db:
            await db.execute("""
                UPDATE DiscordUser SET IsClubAdmin = ? WHERE UserId = ?
            """, (1 if is_admin else 0, user_id))
            await db.commit()

    async def get_club_leaderboard_page(self, page: int = 0, limit: int = 9) -> List[Tuple]:
        """Get club leaderboard page.
        
        Args:
            page: Page number (0-based).
            limit: Items per page.
            
        Returns:
            List of club tuples (Id, Name, Xp).
        """
        offset = page * limit
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, Name, Xp FROM Clubs
                ORDER BY Xp DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))
            return await cursor.fetchall()

    async def get_club_rank(self, club_id: int) -> int:
        """Get club rank by XP"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT COUNT(*) + 1 FROM Clubs
                WHERE Xp > (SELECT Xp FROM Clubs WHERE Id = ?)
            """, (club_id,))
            rank = (await cursor.fetchone())[0]
            return rank
