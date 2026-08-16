"""
Economy and currency system for Unicornia
"""

from datetime import UTC

import discord

from ..database import DatabaseManager


class EconomySystem:
    """Handles currency transactions, banking, and economy features"""

    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot

    async def get_balance(self, user_id: int) -> tuple[int, int]:
        """Get user's wallet and bank balance.

        Args:
            user_id: User ID.

        Returns:
            Tuple of (wallet, bank) balance.
        """
        wallet = await self.db.economy.get_user_currency(user_id)
        bank = await self.db.economy.get_bank_balance(user_id)
        return wallet, bank

    async def give_currency(self, from_user: int, to_user: int, amount: int, note: str = "") -> bool:
        """Transfer currency between users.

        Args:
            from_user: Sender ID.
            to_user: Receiver ID.
            amount: Amount to transfer.
            note: Transaction note.

        Returns:
            Success boolean.
        """
        if from_user == to_user:
            return False

        # Use atomic transfer
        return await self.db.economy.transfer_currency(from_user, to_user, amount, note)

    async def award_currency(self, user_id: int, amount: int, note: str = "") -> bool:
        """Award currency to a user (admin only).

        Args:
            user_id: User ID.
            amount: Amount to award.
            note: Transaction note.

        Returns:
            Success boolean.
        """
        if amount <= 0:
            return False

        # The repository writes the single canonical transaction-log row.
        return await self.db.economy.add_currency(user_id, amount, "award", "admin", note=note)

    async def take_currency(self, user_id: int, amount: int, note: str = "") -> bool:
        """Take currency from a user (admin only).

        Args:
            user_id: User ID.
            amount: Amount to take.
            note: Transaction note.

        Returns:
            Success boolean.
        """
        if amount <= 0:
            return False

        # The repository writes the single canonical transaction-log row.
        return await self.db.economy.remove_currency(user_id, amount, "take", "admin", note=note)

    async def add_currency(
        self, user_id: int, amount: int, transaction_type: str = "api_add", extra: str = "external", note: str = ""
    ) -> bool:
        """Add currency to a user (Generic API).

        Args:
            user_id: User ID.
            amount: Amount to add.
            transaction_type: Type of transaction.
            extra: Additional metadata (e.g. source).
            note: Transaction note.

        Returns:
            Success boolean.
        """
        return await self.db.economy.add_currency(user_id, amount, transaction_type, extra, note=note)

    async def remove_currency(
        self, user_id: int, amount: int, transaction_type: str = "api_remove", extra: str = "external", note: str = ""
    ) -> bool:
        """Remove currency from a user (Generic API).

        Args:
            user_id: User ID.
            amount: Amount to remove.
            transaction_type: Type of transaction.
            extra: Additional metadata (e.g. source).
            note: Transaction note.

        Returns:
            Success boolean.
        """
        return await self.db.economy.remove_currency(user_id, amount, transaction_type, extra, note=note)

    async def deposit_bank(self, user_id: int, amount: int) -> bool:
        """Deposit currency to bank.

        Args:
            user_id: User ID.
            amount: Amount to deposit.

        Returns:
            Success boolean.
        """
        # The repository writes the single canonical transaction-log row.
        return await self.db.economy.deposit_bank(user_id, amount)

    async def withdraw_bank(self, user_id: int, amount: int) -> bool:
        """Withdraw currency from bank.

        Args:
            user_id: User ID.
            amount: Amount to withdraw.

        Returns:
            Success boolean.
        """
        # The repository writes the single canonical transaction-log row.
        return await self.db.economy.withdraw_bank(user_id, amount)

    async def get_bank_info(self, user_id: int) -> int:
        """Get bank balance.

        Args:
            user_id: User ID.

        Returns:
            Bank balance.
        """
        result = await self.db.economy.get_bank_user(user_id)
        return result[0]

    async def claim_timely(self, user: discord.Member) -> tuple[bool, int, int, dict[str, int]]:
        """Claim daily timely reward with streak tracking.

        Args:
            user: Discord member.

        Returns:
            Tuple of (success, total_amount, streak, breakdown).
        """
        user_id = user.id
        from datetime import datetime, timedelta

        # Get cooldown from config
        cooldown_hours = await self.config.timely_cooldown()
        cooldown_seconds = cooldown_hours * 3600

        # Attempt atomic claim
        new_streak = await self.db.economy.attempt_timely_claim(user_id, cooldown_seconds)

        if new_streak is None:
            # Failed (Cooldown)
            # Fetch info to return next claim time
            last_claim, streak = await self.db.economy.get_timely_info(user_id)
            if last_claim:
                try:
                    last_claim_dt = datetime.fromisoformat(last_claim)
                    # Ensure UTC for correct timestamp calculation since DB stores UTC
                    if last_claim_dt.tzinfo is None:
                        last_claim_dt = last_claim_dt.replace(tzinfo=UTC)

                    next_claim_dt = last_claim_dt + timedelta(seconds=cooldown_seconds)
                    next_claim_ts = int(next_claim_dt.timestamp())
                    return False, next_claim_ts, streak, {}
                except ValueError:
                    pass
            return False, 0, 0, {}

        # Success! Calculate reward amount (base + streak bonus)
        base_amount = await self.config.timely_amount()
        streak_bonus = min(new_streak * 10, 300)  # Max 300 bonus

        # Supporter Bonus
        supporter_bonus = 0
        supporter_role_id = 700121551483437128
        if any(r.id == supporter_role_id for r in user.roles):
            supporter_bonus = 100

        # Server Booster Bonus
        booster_bonus = 0
        if user.premium_since is not None:
            booster_bonus = 100

        total_amount = base_amount + streak_bonus + supporter_bonus + booster_bonus

        breakdown = {
            "base": base_amount,
            "streak": streak_bonus,
            "supporter": supporter_bonus,
            "booster": booster_bonus,
        }

        # Award currency; the repository writes the single canonical
        # transaction-log row (streak info is carried in its note).
        await self.db.economy.add_currency(
            user_id, total_amount, "timely", "system", note=f"Daily reward (streak: {new_streak})"
        )

        return True, total_amount, new_streak, breakdown

    async def get_leaderboard(self, limit: int = 10, offset: int = 0) -> list[tuple]:
        """Get currency leaderboard.

        Args:
            limit: Limit results.
            offset: Offset results.

        Returns:
            List of leaderboard entries.
        """
        return await self.db.economy.get_top_currency_users(limit, offset)

    @staticmethod
    def _eligible_leaderboard_user_ids(guild: discord.Guild) -> list[int]:
        return [member.id for member in guild.members if not member.bot]

    async def get_filtered_leaderboard(
        self, guild: discord.Guild, limit: int = 10, offset: int = 0
    ) -> list[tuple[int, int]]:
        """Get one filtered currency leaderboard page for a guild.

        Args:
            guild: Discord guild.

        Returns:
            List of filtered leaderboard entries.
        """
        return await self.db.economy.get_total_currency_page(self._eligible_leaderboard_user_ids(guild), limit, offset)

    async def get_filtered_leaderboard_count(self, guild: discord.Guild) -> int:
        return await self.db.economy.count_total_currency_users(self._eligible_leaderboard_user_ids(guild))

    async def get_filtered_leaderboard_rank(self, guild: discord.Guild, user_id: int) -> int | None:
        return await self.db.economy.get_total_currency_rank(self._eligible_leaderboard_user_ids(guild), user_id)

    async def get_transaction_history(self, user_id: int, limit: int = 50) -> list[tuple]:
        """Get user's transaction history.

        Args:
            user_id: User ID.
            limit: Limit results.

        Returns:
            List of transactions.
        """
        return await self.db.economy.get_currency_transactions(user_id, limit)

    async def get_gambling_stats(self, user_id: int | None = None) -> list[tuple]:
        """Get gambling statistics.

        Args:
            user_id: User ID (optional).

        Returns:
            List of stats.
        """
        if user_id:
            return await self.db.economy.get_user_bet_stats(user_id)
        else:
            # Return global stats - would need to implement in database
            return []

    async def get_rakeback_info(self, user_id: int) -> int:
        """Get user's rakeback balance.

        Args:
            user_id: User ID.

        Returns:
            Rakeback balance.
        """
        return await self.db.economy.get_rakeback_balance(user_id)

    async def claim_rakeback(self, user_id: int) -> int:
        """Claim rakeback balance.

        Args:
            user_id: User ID.

        Returns:
            Claimed amount.
        """
        balance = await self.db.economy.claim_rakeback(user_id)
        if balance > 0:
            # The repository writes the single canonical transaction-log row.
            await self.db.economy.add_currency(user_id, balance, "rakeback", "system", note="Claimed rakeback")
        return balance
