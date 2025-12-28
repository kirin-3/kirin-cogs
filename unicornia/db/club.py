from typing import List, Dict, Any, Tuple

class ClubRepository:
    """Repository for Club system database operations"""
    
    def __init__(self, db):
        self.db = db

    async def create_club(self, owner_id: int, name: str):
        """Create a new club"""
        async with self.db._get_connection() as db:
            
            # Insert club
            cursor = await db.execute("""
                INSERT INTO ClubInfo (Name, OwnerId, Xp) VALUES (?, ?, 0)
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

    async def get_club(self, club_id: int):
        """Get club by ID"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, Name, Description, ImageUrl, BannerUrl, Xp, OwnerId, DateAdded 
                FROM ClubInfo WHERE Id = ?
            """, (club_id,))
            return await cursor.fetchone()

    async def get_club_by_name(self, name: str):
        """Get club by name"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, Name, Description, ImageUrl, BannerUrl, Xp, OwnerId, DateAdded 
                FROM ClubInfo WHERE Name = ? COLLATE NOCASE
            """, (name,))
            return await cursor.fetchone()

    async def get_club_by_member(self, user_id: int):
        """Get club by member user ID"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT c.Id, c.Name, c.Description, c.ImageUrl, c.BannerUrl, c.Xp, c.OwnerId, c.DateAdded 
                FROM ClubInfo c
                JOIN DiscordUser u ON c.Id = u.ClubId
                WHERE u.UserId = ?
            """, (user_id,))
            return await cursor.fetchone()

    async def get_club_members(self, club_id: int):
        """Get all members of a club"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT UserId, Username, AvatarId, TotalXp, IsClubAdmin 
                FROM DiscordUser WHERE ClubId = ?
            """, (club_id,))
            return await cursor.fetchall()

    async def get_club_applicants(self, club_id: int):
        """Get applicants for a club"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT u.UserId, u.Username, u.AvatarId, u.TotalXp 
                FROM ClubApplicants ca
                JOIN DiscordUser u ON ca.UserId = u.UserId
                WHERE ca.ClubId = ?
            """, (club_id,))
            return await cursor.fetchall()

    async def get_club_bans(self, club_id: int):
        """Get banned users for a club"""
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

    async def apply_to_club(self, user_id: int, club_id: int):
        """Apply to join a club"""
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT OR IGNORE INTO ClubApplicants (ClubId, UserId) VALUES (?, ?)
            """, (club_id, user_id))
            await db.commit()

    async def accept_club_application(self, club_id: int, user_id: int):
        """Accept a club application"""
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

    async def reject_club_application(self, club_id: int, user_id: int):
        """Reject a club application"""
        async with self.db._get_connection() as db:
            await db.execute("""
                DELETE FROM ClubApplicants WHERE ClubId = ? AND UserId = ?
            """, (club_id, user_id))
            await db.commit()

    async def leave_club(self, user_id: int):
        """Leave current club"""
        async with self.db._get_connection() as db:
            await db.execute("""
                UPDATE DiscordUser SET ClubId = NULL, IsClubAdmin = 0 WHERE UserId = ?
            """, (user_id,))
            await db.commit()

    async def kick_club_member(self, user_id: int):
        """Kick member from club"""
        await self.leave_club(user_id)

    async def ban_club_member(self, club_id: int, user_id: int):
        """Ban member from club"""
        async with self.db._get_connection() as db:
            
            # Remove from club if member
            await db.execute("""
                UPDATE DiscordUser SET ClubId = NULL, IsClubAdmin = 0 WHERE UserId = ?
            """, (user_id,))
            
            # Remove application if exists
            await db.execute("""
                DELETE FROM ClubApplicants WHERE ClubId = ? AND UserId = ?
            """, (club_id, user_id))
            
            # Add ban
            await db.execute("""
                INSERT OR IGNORE INTO ClubBans (ClubId, UserId) VALUES (?, ?)
            """, (club_id, user_id))
            
            await db.commit()

    async def unban_club_member(self, club_id: int, user_id: int):
        """Unban member from club"""
        async with self.db._get_connection() as db:
            await db.execute("""
                DELETE FROM ClubBans WHERE ClubId = ? AND UserId = ?
            """, (club_id, user_id))
            await db.commit()

    async def disband_club(self, club_id: int):
        """Disband a club"""
        async with self.db._get_connection() as db:
            
            # Remove all members
            await db.execute("""
                UPDATE DiscordUser SET ClubId = NULL, IsClubAdmin = 0 WHERE ClubId = ?
            """, (club_id,))
            
            # Delete bans and applications
            await db.execute("DELETE FROM ClubApplicants WHERE ClubId = ?", (club_id,))
            await db.execute("DELETE FROM ClubBans WHERE ClubId = ?", (club_id,))
            
            # Delete club
            await db.execute("DELETE FROM ClubInfo WHERE Id = ?", (club_id,))
            
            await db.commit()

    async def update_club_settings(self, club_id: int, **kwargs):
        """Update club settings (name, desc, icon, banner, owner)"""
        if not kwargs:
            return
            
        async with self.db._get_connection() as db:
            
            updates = []
            params = []
            
            for key, value in kwargs.items():
                if key in ['Name', 'Description', 'ImageUrl', 'BannerUrl', 'OwnerId']:
                    updates.append(f"{key} = ?")
                    params.append(value)
            
            if not updates:
                return
                
            params.append(club_id)
            query = f"UPDATE ClubInfo SET {', '.join(updates)} WHERE Id = ?"
            
            await db.execute(query, params)
            await db.commit()

    async def toggle_club_admin(self, user_id: int, is_admin: bool):
        """Toggle club admin status for a user"""
        async with self.db._get_connection() as db:
            await db.execute("""
                UPDATE DiscordUser SET IsClubAdmin = ? WHERE UserId = ?
            """, (1 if is_admin else 0, user_id))
            await db.commit()

    async def get_club_leaderboard_page(self, page: int = 0, limit: int = 9):
        """Get club leaderboard page"""
        offset = page * limit
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, Name, Xp FROM ClubInfo 
                ORDER BY Xp DESC 
                LIMIT ? OFFSET ?
            """, (limit, offset))
            return await cursor.fetchall()

    async def get_club_rank(self, club_id: int) -> int:
        """Get club rank by XP"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT COUNT(*) + 1 FROM ClubInfo 
                WHERE Xp > (SELECT Xp FROM ClubInfo WHERE Id = ?)
            """, (club_id,))
            rank = (await cursor.fetchone())[0]
            return rank
