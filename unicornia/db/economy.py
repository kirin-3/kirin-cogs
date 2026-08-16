import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from ..gambling import RAKEBACK_RATE

# Economy operation states
OP_STATE_RESERVED = "reserved"
OP_STATE_SETTLED = "settled"

# Economy operation directions
DIRECTION_CREDIT = "credit"
DIRECTION_DEBIT = "debit"

OperationDirection = Literal["credit", "debit"]

# OperationOutcome.state values
OUTCOME_SETTLED = "settled"
OUTCOME_RESERVED = "reserved"
OUTCOME_DUPLICATE = "duplicate"
OUTCOME_INSUFFICIENT_FUNDS = "insufficient_funds"
OUTCOME_NOT_FOUND = "not_found"


@dataclass(frozen=True)
class OperationOutcome:
    """Result of an idempotent economy operation.

    Attributes:
        key: The caller-supplied idempotency key.
        state: What happened for this call — see OUTCOME_* constants.
        new_balance: Wallet balance after the call (None if not applicable).
        amount: Amount applied by this call (payout for settlements, 0 otherwise).
        result: Caller-supplied result payload (from the original call on duplicates).
        existing_state: For duplicates, the state of the stored operation row.
    """

    key: str
    state: str
    new_balance: int | None
    amount: int
    result: dict[str, Any] = field(default_factory=dict)
    existing_state: str | None = None


class EconomyRepository:
    """Repository for Economy system database operations"""

    def __init__(self, db):
        self.db = db

    # Currency methods
    async def get_user_currency(self, user_id: int) -> int:
        """Get user's wallet currency.

        Args:
            user_id: Discord user ID

        Returns:
            int: Current wallet balance (or 0 if new user).
        """
        async with self.db._get_connection() as db:
            return await self._get_user_currency(user_id, db)

    async def _get_user_currency(self, user_id: int, db) -> int:
        """Internal get user currency."""
        cursor = await db.execute("SELECT CurrencyAmount FROM DiscordUser WHERE UserId = ?", (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def add_currency(
        self,
        user_id: int,
        amount: int,
        transaction_type: str,
        extra: str = "",
        other_id: int | None = None,
        note: str = "",
    ) -> bool:
        """Add currency to user's wallet.

        Args:
            user_id: Discord user ID
            amount: Amount to add
            transaction_type: Type of transaction (e.g. "award", "shop")
            extra: Additional metadata
            other_id: Related user ID (if transfer)
            note: Human readable note

        Returns:
            bool: Always True (success)
        """
        if amount <= 0:
            raise ValueError("Amount must be a positive integer.")
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                # Update user currency
                await db.execute(
                    """
                    INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                    ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + ?
                """,
                    (user_id, amount, amount),
                )

                # Log transaction
                await db.execute(
                    """
                    INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                    (user_id, amount, transaction_type, extra, other_id, note),
                )

                await db.commit()
                return True
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def remove_currency(
        self,
        user_id: int,
        amount: int,
        transaction_type: str,
        extra: str = "",
        other_id: int | None = None,
        note: str = "",
    ) -> bool:
        """Remove currency from user's wallet.

        Args:
            user_id: Discord user ID
            amount: Amount to remove
            transaction_type: Type of transaction
            extra: Metadata
            other_id: Related user ID
            note: Human readable note

        Returns:
            bool: True if successful, False if insufficient funds.
        """
        if amount <= 0:
            raise ValueError("Amount must be a positive integer.")
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                # Atomic update with WHERE clause to prevent race conditions
                cursor = await db.execute(
                    """
                    UPDATE DiscordUser
                    SET CurrencyAmount = CurrencyAmount - ?
                    WHERE UserId = ? AND CurrencyAmount >= ?
                """,
                    (amount, user_id, amount),
                )

                if cursor.rowcount == 0:
                    # Update failed - insufficient funds or user doesn't exist
                    # Check if user exists but has no money, or doesn't exist
                    check = await db.execute("SELECT 1 FROM DiscordUser WHERE UserId = ?", (user_id,))
                    if not await check.fetchone():
                        # Create user if doesn't exist (starts with 0, so still fails check)
                        await db.execute(
                            "INSERT OR IGNORE INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, 0)", (user_id,)
                        )

                    await db.commit()
                    return False

                # Log transaction
                await db.execute(
                    """
                    INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                    (user_id, -amount, transaction_type, extra, other_id, note),
                )

                await db.commit()
                return True
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def transfer_currency(self, from_user: int, to_user: int, amount: int, note: str = "") -> bool:
        """Atomically transfer currency between two users.

        Args:
            from_user: Sender Discord ID
            to_user: Receiver Discord ID
            amount: Amount to transfer
            note: Transfer note

        Returns:
            bool: True if successful, False if insufficient funds.
        """
        if amount <= 0:
            raise ValueError("Amount must be a positive integer.")
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                # Atomic update with WHERE clause to prevent race conditions
                cursor = await db.execute(
                    """
                    UPDATE DiscordUser
                    SET CurrencyAmount = CurrencyAmount - ?
                    WHERE UserId = ? AND CurrencyAmount >= ?
                """,
                    (amount, from_user, amount),
                )

                if cursor.rowcount == 0:
                    # Update failed - insufficient funds or user doesn't exist
                    await db.execute("ROLLBACK")
                    return False

                # Add to receiver
                await db.execute(
                    """
                    INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                    ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + ?
                """,
                    (to_user, amount, amount),
                )

                # Log transactions for both
                await db.execute(
                    """
                    INSERT INTO CurrencyTransactions (UserId, Amount, Type, OtherId, Reason, DateAdded)
                    VALUES (?, ?, 'give', ?, ?, datetime('now'))
                """,
                    (from_user, -amount, to_user, f"Given to user {to_user}: {note}"),
                )

                await db.execute(
                    """
                    INSERT INTO CurrencyTransactions (UserId, Amount, Type, OtherId, Reason, DateAdded)
                    VALUES (?, ?, 'receive', ?, ?, datetime('now'))
                """,
                    (to_user, amount, from_user, f"Received from user {from_user}: {note}"),
                )

                await db.commit()
                return True
            except Exception:
                await db.execute("ROLLBACK")
                raise

    # Bank methods
    async def get_bank_balance(self, user_id: int) -> int:
        """Get user's bank balance.

        Args:
            user_id: Discord user ID.

        Returns:
            Current bank balance.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT Balance FROM BankUsers WHERE UserId = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def deposit_bank(self, user_id: int, amount: int) -> bool:
        """Deposit currency to bank.

        Args:
            user_id: Discord user ID.
            amount: Amount to deposit.

        Returns:
            True if successful, False otherwise.
        """
        if amount <= 0:
            raise ValueError("Amount must be a positive integer.")
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                # Atomic deduct from wallet
                cursor = await db.execute(
                    """
                    UPDATE DiscordUser
                    SET CurrencyAmount = CurrencyAmount - ?
                    WHERE UserId = ? AND CurrencyAmount >= ?
                """,
                    (amount, user_id, amount),
                )

                if cursor.rowcount == 0:
                    await db.execute("ROLLBACK")
                    return False

                # Add to bank
                await db.execute(
                    """
                    INSERT INTO BankUsers (UserId, Balance) VALUES (?, ?)
                    ON CONFLICT(UserId) DO UPDATE SET Balance = Balance + ?
                """,
                    (user_id, amount, amount),
                )

                # Log transaction
                await db.execute(
                    """
                    INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, Reason, DateAdded)
                    VALUES (?, ?, 'bank_deposit', 'bank', ?, datetime('now'))
                """,
                    (user_id, -amount, f"Deposited {amount} to bank"),
                )

                await db.commit()
                return True
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def withdraw_bank(self, user_id: int, amount: int) -> bool:
        """Withdraw currency from bank.

        Args:
            user_id: Discord user ID.
            amount: Amount to withdraw.

        Returns:
            True if successful, False otherwise.
        """
        if amount <= 0:
            raise ValueError("Amount must be a positive integer.")
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                # Atomic deduct from bank
                cursor = await db.execute(
                    """
                    UPDATE BankUsers
                    SET Balance = Balance - ?
                    WHERE UserId = ? AND Balance >= ?
                """,
                    (amount, user_id, amount),
                )

                if cursor.rowcount == 0:
                    await db.execute("ROLLBACK")
                    return False

                # Add to wallet
                await db.execute(
                    """
                    INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                    ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + ?
                """,
                    (user_id, amount, amount),
                )

                # Log transaction
                await db.execute(
                    """
                    INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, Reason, DateAdded)
                    VALUES (?, ?, 'bank_withdraw', 'bank', ?, datetime('now'))
                """,
                    (user_id, amount, f"Withdrew {amount} from bank"),
                )

                await db.commit()
                return True
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def _remove_currency(
        self, user_id: int, amount: int, transaction_type: str, extra: str, other_id: int, note: str, db
    ) -> bool:
        """Internal remove currency (no transaction control).

        Used by ShopRepository to participate in existing transactions.
        """
        # Atomic update with WHERE clause to prevent race conditions
        cursor = await db.execute(
            """
            UPDATE DiscordUser
            SET CurrencyAmount = CurrencyAmount - ?
            WHERE UserId = ? AND CurrencyAmount >= ?
        """,
            (amount, user_id, amount),
        )

        if cursor.rowcount == 0:
            # Update failed - insufficient funds or user doesn't exist
            # Check if user exists but has no money, or doesn't exist
            check = await db.execute("SELECT 1 FROM DiscordUser WHERE UserId = ?", (user_id,))
            if not await check.fetchone():
                # Create user if doesn't exist (starts with 0, so still fails check)
                await db.execute("INSERT OR IGNORE INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, 0)", (user_id,))
            return False

        # Log transaction
        await db.execute(
            """
            INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """,
            (user_id, -amount, transaction_type, extra, other_id, note),
        )

        return True

    async def get_bank_user(self, user_id: int) -> tuple[int]:
        """Get or create bank user.

        Args:
            user_id: Discord user ID.

        Returns:
            Tuple containing bank balance.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute(
                """
                SELECT Balance FROM BankUsers WHERE UserId = ?
            """,
                (user_id,),
            )
            result = await cursor.fetchone()

            if not result:
                await db.execute(
                    """
                    INSERT INTO BankUsers (UserId, Balance) VALUES (?, 0)
                """,
                    (user_id,),
                )
                await db.commit()
                return (0,)

            return result

    async def update_bank_balance(self, user_id: int, new_balance: int) -> None:
        """Update bank balance.

        Args:
            user_id: Discord user ID.
            new_balance: New balance amount.
        """
        if new_balance < 0:
            raise ValueError("Balance must be a non-negative integer.")
        async with self.db._get_connection() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO BankUsers (UserId, Balance)
                VALUES (?, ?)
            """,
                (user_id, new_balance),
            )
            await db.commit()

    # Timely methods
    async def check_timely_cooldown(self, user_id: int, cooldown_hours: int) -> bool:
        """Check if user can claim timely reward.

        Args:
            user_id: Discord user ID.
            cooldown_hours: Hours for cooldown.

        Returns:
            True if available, False if on cooldown.
        """
        cooldown_seconds = cooldown_hours * 3600

        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT LastClaim FROM TimelyCooldown WHERE UserId = ?", (user_id,))
            row = await cursor.fetchone()

            if not row:
                return True

            last_claim = datetime.fromisoformat(row[0])
            return (datetime.utcnow() - last_claim).total_seconds() >= cooldown_seconds

    async def attempt_timely_claim(self, user_id: int, cooldown_seconds: int = 86400) -> int | None:
        """Attempt to claim timely reward atomically.

        Args:
            user_id: Discord user ID.
            cooldown_seconds: Cooldown in seconds.

        Returns:
            New streak if successful, None if on cooldown.
        """
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                # 1. Ensure user exists in TimelyCooldown
                await db.execute(
                    """
                    INSERT OR IGNORE INTO TimelyCooldown (UserId, LastClaim, Streak)
                    VALUES (?, datetime('now', '-100 years'), 0)
                """,
                    (user_id,),
                )

                # 2. Update if eligible
                cursor = await db.execute(
                    """
                    UPDATE TimelyCooldown
                    SET
                        Streak = CASE
                            WHEN datetime('now') <= datetime(LastClaim, '+48 hours') THEN Streak + 1
                            ELSE 1
                        END,
                        LastClaim = datetime('now')
                    WHERE UserId = ?
                      AND (
                          datetime('now') >= datetime(LastClaim, '+' || ? || ' seconds')
                          OR LastClaim IS NULL
                      )
                """,
                    (user_id, cooldown_seconds),
                )

                if cursor.rowcount == 0:
                    await db.commit()
                    return None

                # 3. Retrieve new streak
                cursor = await db.execute("SELECT Streak FROM TimelyCooldown WHERE UserId = ?", (user_id,))
                row = await cursor.fetchone()

                await db.commit()

                if row:
                    return row[0]
                return None

            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def claim_timely(self, user_id: int, amount: int, cooldown_hours: int) -> bool:
        """Claim timely reward.

        Args:
            user_id: Discord user ID.
            amount: Amount to claim.
            cooldown_hours: Cooldown in hours.

        Returns:
            True if claimed, False if on cooldown.
        """
        if amount <= 0:
            raise ValueError("Amount must be a positive integer.")

        # Use atomic check-and-update
        streak = await self.attempt_timely_claim(user_id, cooldown_hours * 3600)

        if streak is None:
            return False

        # If successful, award currency
        await self.add_currency(user_id, amount, "timely", "daily", note="Daily timely reward")

        return True

    async def get_timely_info(self, user_id: int) -> tuple[str | None, int]:
        """Get timely cooldown info.

        Args:
            user_id: Discord user ID.

        Returns:
            Tuple of (LastClaim timestamp, Streak count).
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute(
                """
                SELECT LastClaim, Streak FROM TimelyCooldown WHERE UserId = ?
            """,
                (user_id,),
            )
            result = await cursor.fetchone()

            if not result:
                return None, 0

            return result

    async def update_timely_claim(self, user_id: int, streak: int) -> None:
        """Update timely claim info.

        Args:
            user_id: Discord user ID.
            streak: New streak count.
        """
        if streak < 0:
            raise ValueError("Streak must be a non-negative integer.")
        async with self.db._get_connection() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO TimelyCooldown (UserId, LastClaim, Streak)
                VALUES (?, datetime('now'), ?)
            """,
                (user_id, streak),
            )
            await db.commit()

    # Leaderboard methods
    async def get_top_currency_users(self, limit: int = 10, offset: int = 0) -> list[tuple]:
        """Get top currency users globally.

        Args:
            limit: Limit results.
            offset: Offset results.

        Returns:
            List of (UserId, CurrencyAmount) tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute(
                """
                SELECT UserId, CurrencyAmount FROM DiscordUser
                ORDER BY CurrencyAmount DESC
                LIMIT ? OFFSET ?
            """,
                (limit, offset),
            )
            return await cursor.fetchall()

    async def get_top_total_currency(self, limit: int = 1000) -> list[tuple]:
        """Get top users by total currency (Wallet + Bank).

        Args:
            limit: Limit results.

        Returns:
            List of (UserId, TotalAmount) tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute(
                """
                SELECT u.UserId, (u.CurrencyAmount + COALESCE(b.Balance, 0)) as Total
                FROM DiscordUser u
                LEFT JOIN BankUsers b ON u.UserId = b.UserId
                ORDER BY Total DESC
                LIMIT ?
            """,
                (limit,),
            )
            return await cursor.fetchall()

    @staticmethod
    async def _populate_eligible_leaderboard_users(db, user_ids: list[int]) -> None:
        await db.execute("CREATE TEMP TABLE IF NOT EXISTS EligibleLeaderboardUsers (UserId INTEGER PRIMARY KEY)")
        await db.execute("DELETE FROM EligibleLeaderboardUsers")
        if user_ids:
            await db.executemany(
                "INSERT OR IGNORE INTO EligibleLeaderboardUsers (UserId) VALUES (?)",
                ((user_id,) for user_id in user_ids),
            )

    async def get_total_currency_page(self, user_ids: list[int], limit: int, offset: int) -> list[tuple[int, int]]:
        """Return one stable wallet-plus-bank leaderboard page."""
        if limit <= 0 or offset < 0:
            raise ValueError("Limit must be positive and offset cannot be negative.")
        async with self.db._get_connection() as db:
            await self._populate_eligible_leaderboard_users(db, user_ids)
            cursor = await db.execute(
                """
                SELECT u.UserId, u.CurrencyAmount + COALESCE(b.Balance, 0) AS Total
                FROM EligibleLeaderboardUsers e
                JOIN DiscordUser u ON u.UserId = e.UserId
                LEFT JOIN BankUsers b ON b.UserId = u.UserId
                ORDER BY Total DESC, u.UserId ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            return [(int(row[0]), int(row[1])) for row in await cursor.fetchall()]

    async def count_total_currency_users(self, user_ids: list[int]) -> int:
        """Count eligible leaderboard users."""
        async with self.db._get_connection() as db:
            await self._populate_eligible_leaderboard_users(db, user_ids)
            row = await (
                await db.execute(
                    """
                    SELECT COUNT(*) FROM EligibleLeaderboardUsers e
                    JOIN DiscordUser u ON u.UserId = e.UserId
                    """
                )
            ).fetchone()
            return int(row[0]) if row else 0

    async def get_total_currency_rank(self, user_ids: list[int], user_id: int) -> int | None:
        """Return a zero-based stable rank for an eligible user."""
        async with self.db._get_connection() as db:
            await self._populate_eligible_leaderboard_users(db, user_ids)
            row = await (
                await db.execute(
                    """
                    WITH Ranked AS (
                        SELECT u.UserId,
                               ROW_NUMBER() OVER (
                                   ORDER BY u.CurrencyAmount + COALESCE(b.Balance, 0) DESC, u.UserId ASC
                               ) - 1 AS Rank
                        FROM EligibleLeaderboardUsers e
                        JOIN DiscordUser u ON u.UserId = e.UserId
                        LEFT JOIN BankUsers b ON b.UserId = u.UserId
                    )
                    SELECT Rank FROM Ranked WHERE UserId = ?
                    """,
                    (user_id,),
                )
            ).fetchone()
            return int(row[0]) if row else None

    # Currency Transaction Methods
    async def log_currency_transaction(
        self,
        user_id: int,
        transaction_type: str,
        amount: int,
        reason: str | None = None,
        other_id: int | None = None,
        extra: str | None = None,
    ) -> None:
        """Log a currency transaction.

        Args:
            user_id: User ID.
            transaction_type: Type of transaction.
            amount: Amount involved.
            reason: Reason string.
            other_id: Other user ID involved.
            extra: Extra metadata.
        """
        async with self.db._get_connection() as db:
            await db.execute(
                """
                INSERT INTO CurrencyTransactions (UserId, Type, Amount, Reason, OtherId, Extra, DateAdded)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
                (user_id, transaction_type, amount, reason, other_id, extra),
            )
            await db.commit()

    async def get_currency_transactions(self, user_id: int, limit: int | None = 50) -> list[tuple]:
        """Get recent currency transactions for a user.

        Args:
            user_id: User ID.
            limit: Limit results.

        Returns:
            List of transaction tuples.
        """
        async with self.db._get_connection() as db:
            if limit is None:
                cursor = await db.execute(
                    """
                    SELECT Type, Amount, Reason, DateAdded FROM CurrencyTransactions
                    WHERE UserId = ? ORDER BY DateAdded DESC
                    """,
                    (user_id,),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT Type, Amount, Reason, DateAdded FROM CurrencyTransactions
                    WHERE UserId = ? ORDER BY DateAdded DESC LIMIT ?
                    """,
                    (user_id, limit),
                )
            return await cursor.fetchall()

    # Gambling Stats Methods
    async def update_gambling_stats(self, feature: str, bet_amount: int, win_amount: int, loss_amount: int) -> None:
        """Update global gambling statistics.

        Args:
            feature: Feature name (e.g. "slots").
            bet_amount: Amount bet.
            win_amount: Amount won.
            loss_amount: Amount lost.
        """
        if bet_amount < 0 or win_amount < 0 or loss_amount < 0:
            raise ValueError("Amounts must be non-negative integers.")
        if bet_amount == 0 and win_amount == 0 and loss_amount == 0:
            return  # Nothing to do

        async with self.db._get_connection() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO GamblingStats (Feature, BetAmount, WinAmount, LossAmount)
                VALUES (?,
                    COALESCE((SELECT BetAmount FROM GamblingStats WHERE Feature = ?), 0) + ?,
                    COALESCE((SELECT WinAmount FROM GamblingStats WHERE Feature = ?), 0) + ?,
                    COALESCE((SELECT LossAmount FROM GamblingStats WHERE Feature = ?), 0) + ?)
            """,
                (feature, feature, bet_amount, feature, win_amount, feature, loss_amount),
            )
            await db.commit()

    async def update_user_bet_stats(
        self, user_id: int, game: str, bet_amount: int, win_amount: int, loss_amount: int, current_win: int = 0
    ) -> None:
        """Update user betting statistics.

        Args:
            user_id: User ID.
            game: Game name.
            bet_amount: Amount bet.
            win_amount: Amount won.
            loss_amount: Amount lost.
            current_win: Current win amount (for max win check).
        """
        if bet_amount < 0 or win_amount < 0 or loss_amount < 0 or current_win < 0:
            raise ValueError("Amounts must be non-negative integers.")
        if bet_amount == 0 and win_amount == 0 and loss_amount == 0 and current_win == 0:
            return  # Nothing to do

        async with self.db._get_connection() as db:
            # Get current max win
            cursor = await db.execute(
                """
                SELECT MaxWin FROM UserBetStats WHERE UserId = ? AND Game = ?
            """,
                (user_id, game),
            )
            result = await cursor.fetchone()
            max_win = max(result[0] if result else 0, current_win)

            await db.execute(
                """
                INSERT OR REPLACE INTO UserBetStats (UserId, Game, BetAmount, WinAmount, LossAmount, MaxWin)
                VALUES (?, ?,
                    COALESCE((SELECT BetAmount FROM UserBetStats WHERE UserId = ? AND Game = ?), 0) + ?,
                    COALESCE((SELECT WinAmount FROM UserBetStats WHERE UserId = ? AND Game = ?), 0) + ?,
                    COALESCE((SELECT LossAmount FROM UserBetStats WHERE UserId = ? AND Game = ?), 0) + ?,
                    ?)
            """,
                (
                    user_id,
                    game,
                    user_id,
                    game,
                    bet_amount,
                    user_id,
                    game,
                    win_amount,
                    user_id,
                    game,
                    loss_amount,
                    max_win,
                ),
            )
            await db.commit()

    async def get_user_bet_stats(self, user_id: int) -> list[tuple]:
        """Get user betting statistics.

        Args:
            user_id: User ID.

        Returns:
            List of stat tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute(
                """
                SELECT Game, BetAmount, WinAmount, LossAmount, MaxWin FROM UserBetStats
                WHERE UserId = ? ORDER BY BetAmount DESC
            """,
                (user_id,),
            )
            return await cursor.fetchall()

    # Rakeback Methods
    async def get_rakeback_balance(self, user_id: int) -> int:
        """Get user's rakeback balance.

        Args:
            user_id: User ID.

        Returns:
            Rakeback balance amount.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute(
                """
                SELECT RakebackBalance FROM Rakeback WHERE UserId = ?
            """,
                (user_id,),
            )
            result = await cursor.fetchone()
            return result[0] if result else 0

    async def add_rakeback(self, user_id: int, amount: int) -> None:
        """Add to user's rakeback balance.

        Args:
            user_id: User ID.
            amount: Amount to add.
        """
        if amount <= 0:
            raise ValueError("Amount must be a positive integer.")
        async with self.db._get_connection() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO Rakeback (UserId, RakebackBalance)
                VALUES (?, COALESCE((SELECT RakebackBalance FROM Rakeback WHERE UserId = ?), 0) + ?)
            """,
                (user_id, user_id, amount),
            )
            await db.commit()

    async def claim_rakeback(self, user_id: int) -> int:
        """Claim and reset rakeback balance.

        Args:
            user_id: User ID.

        Returns:
            Claimed amount.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute(
                """
                SELECT RakebackBalance FROM Rakeback WHERE UserId = ?
            """,
                (user_id,),
            )
            result = await cursor.fetchone()
            balance = result[0] if result else 0

            if balance > 0:
                await db.execute(
                    """
                    UPDATE Rakeback SET RakebackBalance = 0 WHERE UserId = ?
                """,
                    (user_id,),
                )
                await db.commit()

            return balance

    # Currency generation channel methods
    async def get_currency_generation_channels(self, guild_id: int | None = None) -> list[tuple]:
        """Get currency generation channels.

        Args:
            guild_id: Guild ID (optional).

        Returns:
            List of channel tuples.
        """
        async with self.db._get_connection() as db:
            if guild_id:
                cursor = await db.execute(
                    """
                    SELECT Id, GuildId, ChannelId FROM GCChannelId WHERE GuildId = ?
                """,
                    (guild_id,),
                )
            else:
                cursor = await db.execute("""
                    SELECT Id, GuildId, ChannelId FROM GCChannelId
                """)
            return await cursor.fetchall()

    async def add_currency_generation_channel(self, guild_id: int, channel_id: int) -> None:
        """Add a channel for currency generation.

        Args:
            guild_id: Guild ID.
            channel_id: Channel ID.
        """
        async with self.db._get_connection() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO GCChannelId (GuildId, ChannelId) VALUES (?, ?)
            """,
                (guild_id, channel_id),
            )
            await db.commit()

    async def remove_currency_generation_channel(self, guild_id: int, channel_id: int) -> None:
        """Remove a channel from currency generation.

        Args:
            guild_id: Guild ID.
            channel_id: Channel ID.
        """
        async with self.db._get_connection() as db:
            await db.execute(
                """
                DELETE FROM GCChannelId WHERE GuildId = ? AND ChannelId = ?
            """,
                (guild_id, channel_id),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Idempotent economy operations
    # ------------------------------------------------------------------

    async def _get_operation_row(self, key: str, db) -> dict[str, Any] | None:
        """Fetch an operation row by idempotency key (internal)."""
        cursor = await db.execute(
            """
            SELECT OperationKey, GuildId, UserId, Source, Direction, Amount, State, Result, CreatedAt, SettledAt
            FROM EconomyOperations WHERE OperationKey = ?
        """,
            (key,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "OperationKey": row[0],
            "GuildId": row[1],
            "UserId": row[2],
            "Source": row[3],
            "Direction": row[4],
            "Amount": row[5],
            "State": row[6],
            "Result": row[7],
            "CreatedAt": row[8],
            "SettledAt": row[9],
        }

    async def get_operation(self, key: str) -> dict[str, Any] | None:
        """Fetch a stored economy operation by idempotency key.

        Returns:
            The operation row as a dict, or None if the key was never used
            (or its transaction rolled back).
        """
        async with self.db._get_connection() as db:
            return await self._get_operation_row(key, db)

    @staticmethod
    def _decode_result(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            decoded = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    async def _duplicate_outcome(self, key: str, user_id: int, db) -> OperationOutcome:
        """Build the outcome for an already-existing operation key."""
        existing = await self._get_operation_row(key, db)
        if existing is None:
            # Row vanished between conflict and read; treat as not found.
            return OperationOutcome(key=key, state=OUTCOME_NOT_FOUND, new_balance=None, amount=0)
        return OperationOutcome(
            key=key,
            state=OUTCOME_DUPLICATE,
            new_balance=await self._get_user_currency(user_id, db),
            amount=0,
            result=self._decode_result(existing["Result"]),
            existing_state=existing["State"],
        )

    async def apply_operation(
        self,
        *,
        key: str,
        user_id: int,
        amount: int,
        direction: OperationDirection,
        source: str,
        transaction_type: str,
        guild_id: int | None = None,
        extra: str = "",
        note: str = "",
        result: dict[str, Any] | None = None,
    ) -> OperationOutcome:
        """Apply a balance effect and its transaction log entry atomically.

        One database transaction: claim the idempotency key, mutate the
        balance, write exactly one transaction-log row, and mark the operation
        settled. Repeating a settled key returns the original result without
        changing the balance or writing another log row. Any step failing
        rolls back all steps, leaving the operation safe to retry.

        Args:
            key: Unique idempotency key supplied by the caller.
            user_id: Discord user ID whose wallet is mutated.
            amount: Absolute amount to apply.
            direction: "credit" to add, "debit" to remove.
            source: Subsystem identity (e.g. "patron", "nitroaward", "gambling").
            transaction_type: CurrencyTransactions type for the canonical row.
            guild_id: Optional guild context for the operation.
            extra: CurrencyTransactions extra metadata.
            note: Human readable reason for the log row.
            result: Optional payload stored and returned on duplicate retries.

        Returns:
            OperationOutcome with state "settled", "duplicate", or
            "insufficient_funds".
        """
        if amount <= 0:
            raise ValueError("Amount must be a positive integer.")
        if direction not in (DIRECTION_CREDIT, DIRECTION_DEBIT):
            raise ValueError("Direction must be 'credit' or 'debit'.")

        payload = json.dumps(result or {})
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                cursor = await db.execute(
                    """
                    INSERT INTO EconomyOperations
                        (OperationKey, GuildId, UserId, Source, Direction, Amount, State, Result, CreatedAt, SettledAt)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                    ON CONFLICT(OperationKey) DO NOTHING
                """,
                    (key, guild_id, user_id, source, direction, amount, OP_STATE_SETTLED, payload),
                )

                if cursor.rowcount == 0:
                    await db.execute("ROLLBACK")
                    return await self._duplicate_outcome(key, user_id, db)

                if direction == DIRECTION_CREDIT:
                    await db.execute(
                        """
                        INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                        ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + ?
                    """,
                        (user_id, amount, amount),
                    )
                else:
                    debit_cursor = await db.execute(
                        """
                        UPDATE DiscordUser
                        SET CurrencyAmount = CurrencyAmount - ?
                        WHERE UserId = ? AND CurrencyAmount >= ?
                    """,
                        (amount, user_id, amount),
                    )
                    if debit_cursor.rowcount == 0:
                        # Insufficient funds: roll back the key claim as well,
                        # so the operation stays safe to retry after funding.
                        await db.execute("ROLLBACK")
                        return OperationOutcome(
                            key=key,
                            state=OUTCOME_INSUFFICIENT_FUNDS,
                            new_balance=await self._get_user_currency(user_id, db),
                            amount=0,
                        )

                signed = amount if direction == DIRECTION_CREDIT else -amount
                await db.execute(
                    """
                    INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                    VALUES (?, ?, ?, ?, NULL, ?, datetime('now'))
                """,
                    (user_id, signed, transaction_type, extra, note),
                )

                await db.commit()
                return OperationOutcome(
                    key=key,
                    state=OUTCOME_SETTLED,
                    new_balance=await self._get_user_currency(user_id, db),
                    amount=amount,
                    result=result or {},
                )
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def reserve_stake(
        self,
        *,
        key: str,
        user_id: int,
        amount: int,
        game: str,
        guild_id: int | None = None,
        source: str = "gambling",
        note: str = "",
    ) -> OperationOutcome:
        """Reserve an affordable stake atomically before producing an outcome.

        The stake is deducted and logged in the same transaction that claims
        the idempotency key with state "reserved". Only affordable
        reservations succeed; a failed reservation claims nothing and can
        never produce winnings.

        Args:
            key: Unique idempotency key for the game operation.
            user_id: Discord user ID.
            amount: Stake to reserve.
            game: Game identifier used for the transaction-log type.
            guild_id: Optional guild context.
            source: Subsystem identity (default "gambling").
            note: Human readable reason for the log row.

        Returns:
            OperationOutcome with state "reserved", "duplicate", or
            "insufficient_funds".
        """
        if amount <= 0:
            raise ValueError("Stake must be a positive integer.")

        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                cursor = await db.execute(
                    """
                    INSERT INTO EconomyOperations
                        (OperationKey, GuildId, UserId, Source, Direction, Amount, State, Result, CreatedAt)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(OperationKey) DO NOTHING
                """,
                    (
                        key,
                        guild_id,
                        user_id,
                        source,
                        DIRECTION_DEBIT,
                        amount,
                        OP_STATE_RESERVED,
                        json.dumps({"game": game}),
                    ),
                )

                if cursor.rowcount == 0:
                    await db.execute("ROLLBACK")
                    return await self._duplicate_outcome(key, user_id, db)

                debit_cursor = await db.execute(
                    """
                    UPDATE DiscordUser
                    SET CurrencyAmount = CurrencyAmount - ?
                    WHERE UserId = ? AND CurrencyAmount >= ?
                """,
                    (amount, user_id, amount),
                )
                if debit_cursor.rowcount == 0:
                    await db.execute("ROLLBACK")
                    return OperationOutcome(
                        key=key,
                        state=OUTCOME_INSUFFICIENT_FUNDS,
                        new_balance=await self._get_user_currency(user_id, db),
                        amount=0,
                    )

                await db.execute(
                    """
                    INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                    VALUES (?, ?, ?, ?, NULL, ?, datetime('now'))
                """,
                    (user_id, -amount, game, "stake", note or f"{game} stake"),
                )

                await db.commit()
                return OperationOutcome(
                    key=key,
                    state=OUTCOME_RESERVED,
                    new_balance=await self._get_user_currency(user_id, db),
                    amount=amount,
                )
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def settle_stake(
        self,
        *,
        key: str,
        payout: int,
        transaction_type: str,
        extra: str = "",
        note: str = "",
        result: dict[str, Any] | None = None,
    ) -> OperationOutcome:
        """Settle a reserved game operation at most once.

        Atomically transitions the operation from "reserved" to "settled" and,
        when payout > 0, credits the payout and writes one transaction-log row.
        A payout of 0 records a lost stake (the reservation already logged the
        deduction). Settling with the full reserved amount refunds the stake.
        Repeating a settled key returns the original result without further
        balance changes.

        Args:
            key: Idempotency key used at reservation time.
            payout: Amount to credit back (0 for a loss).
            transaction_type: CurrencyTransactions type for the payout row.
            extra: CurrencyTransactions extra metadata.
            note: Human readable reason for the log row.
            result: Optional payload stored and returned on duplicate retries.

        Returns:
            OperationOutcome with state "settled", "duplicate", or
            "not_found".
        """
        if payout < 0:
            raise ValueError("Payout must be a non-negative integer.")

        payload = json.dumps(result or {})
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                reserved_operation = await self._get_operation_row(key, db)
                # Claim the reservation atomically; only one settler wins.
                cursor = await db.execute(
                    """
                    UPDATE EconomyOperations
                    SET State = ?, SettledAt = datetime('now'), Result = ?
                    WHERE OperationKey = ? AND State = ?
                """,
                    (OP_STATE_SETTLED, payload, key, OP_STATE_RESERVED),
                )

                if cursor.rowcount == 0:
                    existing = await self._get_operation_row(key, db)
                    await db.execute("ROLLBACK")
                    if existing is None:
                        return OperationOutcome(key=key, state=OUTCOME_NOT_FOUND, new_balance=None, amount=0)
                    return OperationOutcome(
                        key=key,
                        state=OUTCOME_DUPLICATE,
                        new_balance=await self._get_user_currency(existing["UserId"], db),
                        amount=0,
                        result=self._decode_result(existing["Result"]),
                        existing_state=existing["State"],
                    )

                assert reserved_operation is not None, "reserved operation vanished during settlement"
                user_id: int = reserved_operation["UserId"]
                stake: int = reserved_operation["Amount"]
                reservation_result = self._decode_result(reserved_operation["Result"])
                game = str(reservation_result.get("game") or transaction_type)
                loss = max(0, stake - payout)
                win_amount = payout if payout > stake else 0

                if payout > 0:
                    await db.execute(
                        """
                        INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                        ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + ?
                    """,
                        (user_id, payout, payout),
                    )
                    await db.execute(
                        """
                        INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                        VALUES (?, ?, ?, ?, NULL, ?, datetime('now'))
                    """,
                        (user_id, payout, transaction_type, extra, note),
                    )

                rakeback_amount = int(loss * RAKEBACK_RATE)
                if rakeback_amount > 0:
                    await db.execute(
                        """
                        INSERT INTO Rakeback (UserId, RakebackBalance)
                        VALUES (?, ?)
                        ON CONFLICT(UserId) DO UPDATE SET
                            RakebackBalance = RakebackBalance + excluded.RakebackBalance
                        """,
                        (user_id, rakeback_amount),
                    )

                await db.execute(
                    """
                    INSERT INTO GamblingStats (Feature, BetAmount, WinAmount, LossAmount)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(Feature) DO UPDATE SET
                        BetAmount = BetAmount + excluded.BetAmount,
                        WinAmount = WinAmount + excluded.WinAmount,
                        LossAmount = LossAmount + excluded.LossAmount
                    """,
                    (game, stake, win_amount, loss),
                )
                await db.execute(
                    """
                    INSERT INTO UserBetStats (UserId, Game, BetAmount, WinAmount, LossAmount, MaxWin)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(UserId, Game) DO UPDATE SET
                        BetAmount = BetAmount + excluded.BetAmount,
                        WinAmount = WinAmount + excluded.WinAmount,
                        LossAmount = LossAmount + excluded.LossAmount,
                        MaxWin = MAX(MaxWin, excluded.MaxWin)
                    """,
                    (user_id, game, stake, win_amount, loss, win_amount),
                )

                await db.commit()
                return OperationOutcome(
                    key=key,
                    state=OUTCOME_SETTLED,
                    new_balance=await self._get_user_currency(user_id, db),
                    amount=payout,
                    result=result or {},
                )
            except Exception:
                await db.execute("ROLLBACK")
                raise
