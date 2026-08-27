import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from ..gambling import RAKEBACK_RATE, pooled_rake

log = logging.getLogger("red.kirin_cogs.unicornia.database")

POOL_SOURCE_HOUSE_BANKED = "house_banked"
POOL_SOURCE_POOLED = "pooled"
POOL_SOURCE_TRADE_TAX = "trade_tax"
PoolSource = Literal["house_banked", "pooled", "trade_tax"]

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


@dataclass(frozen=True)
class PoolSettlementOutcome:
    """Result of one atomic pooled-stake settlement."""

    settlement_id: str
    state: str
    payouts: dict[str, int] = field(default_factory=dict)
    rakeback: dict[str, int] = field(default_factory=dict)
    total_staked: int = 0
    paid_out: int = 0
    rake: int = 0
    pool_accrual: int = 0
    voided: bool = False
    winning_side: str | None = None


@dataclass(frozen=True)
class DividendRunOutcome:
    """Result of one attempted dividend period."""

    period_end: str
    state: str
    distributed: int = 0
    recipients: int = 0
    payouts: tuple[dict[str, Any], ...] = ()


class EconomyRepository:
    """Repository for Economy system database operations"""

    def __init__(self, db):
        self.db = db

    async def get_yield_pool(self, db=None) -> dict[str, Any]:
        """Read the single yield-pool row, optionally inside a caller transaction."""
        if db is None:
            async with self.db._get_connection() as connection:
                return await self.get_yield_pool(connection)
        row = await (
            await db.execute(
                """
                SELECT Balance, LifetimeHouseBanked, LifetimePooled,
                       LifetimeTradeTax, NextDistributionAt, UpdatedAt
                FROM YieldPool WHERE Id = 1
                """
            )
        ).fetchone()
        if row is None:
            await db.execute("INSERT OR IGNORE INTO YieldPool (Id) VALUES (1)")
            return await self.get_yield_pool(db)
        return {
            "balance": int(row[0]),
            "lifetime_house_banked": int(row[1]),
            "lifetime_pooled": int(row[2]),
            "lifetime_trade_tax": int(row[3]),
            "next_distribution_at": row[4],
            "updated_at": row[5],
        }

    async def accrue_yield_pool(self, db, amount: int, source: PoolSource) -> None:
        """Accrue a signed amount using an already-open caller transaction."""
        column = {
            POOL_SOURCE_HOUSE_BANKED: "LifetimeHouseBanked",
            POOL_SOURCE_POOLED: "LifetimePooled",
            POOL_SOURCE_TRADE_TAX: "LifetimeTradeTax",
        }.get(source)
        if column is None:
            raise ValueError(f"Unknown yield-pool source: {source}")
        await db.execute(
            f"""
            UPDATE YieldPool
            SET Balance = Balance + ?, {column} = {column} + ?,
                UpdatedAt = datetime('now')
            WHERE Id = 1
            """,
            (amount, amount),
        )

    async def get_global_gambling_stats(self) -> list[tuple]:
        """Return aggregate statistics for every game."""
        async with self.db._get_connection() as db:
            cursor = await db.execute(
                """
                SELECT Feature, BetAmount, WinAmount, LossAmount, Rounds,
                       StakedSinceEpoch, PaidOut, RakebackPaid, EpochStart
                FROM GamblingStats ORDER BY Feature
                """
            )
            return await cursor.fetchall()

    async def get_dividend_history(self, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """Return one user's dividend ledger, newest first."""
        async with self.db._get_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT PeriodEnd, Symbol, Weight, Amount, DateAdded
                    FROM DividendPayouts WHERE UserId = ?
                    ORDER BY PeriodEnd DESC, Symbol LIMIT ?
                    """,
                    (user_id, limit),
                )
            ).fetchall()
        return [
            {"period_end": row[0], "symbol": row[1], "weight": row[2], "amount": row[3], "date": row[4]} for row in rows
        ]

    async def get_recent_dividend_runs(self, limit: int = 5) -> list[dict[str, Any]]:
        async with self.db._get_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT PeriodEnd, Distributed, Recipients, CompletedAt
                    FROM DividendRuns ORDER BY PeriodEnd DESC LIMIT ?
                    """,
                    (limit,),
                )
            ).fetchall()
        return [
            {"period_end": row[0], "distributed": row[1], "recipients": row[2], "completed_at": row[3]} for row in rows
        ]

    async def distribute_dividends(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
        next_distribution_at: datetime,
    ) -> DividendRunOutcome:
        """Apply one floor-and-carry dividend run atomically."""
        period_key = period_end.isoformat(sep=" ")
        next_key = next_distribution_at.isoformat(sep=" ")
        async with self.db._get_connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                existing = await (
                    await db.execute(
                        "SELECT Distributed, Recipients FROM DividendRuns WHERE PeriodEnd = ?",
                        (period_key,),
                    )
                ).fetchone()
                if existing is not None:
                    await db.execute("ROLLBACK")
                    return DividendRunOutcome(period_key, OUTCOME_DUPLICATE, int(existing[0]), int(existing[1]))

                pool = await self.get_yield_pool(db)
                usage_rows = await (
                    await db.execute("SELECT Symbol, PeriodUsage FROM Stocks WHERE PeriodUsage > 0")
                ).fetchall()
                total_usage = sum(int(row[1]) for row in usage_rows)
                if int(pool["balance"]) <= 0 or total_usage <= 0:
                    await db.execute(
                        "UPDATE YieldPool SET NextDistributionAt = ?, UpdatedAt = datetime('now') WHERE Id = 1",
                        (next_key,),
                    )
                    await db.commit()
                    return DividendRunOutcome(period_key, "deferred")

                weights = await self.db.stock.get_time_weighted_holdings(period_start, period_end, db)
                payouts: list[dict[str, Any]] = []
                starting_balance = int(pool["balance"])
                for symbol, usage in usage_rows:
                    stock_slice = (starting_balance * int(usage)) // total_usage
                    holders = weights.get(str(symbol), {})
                    total_weight = sum(holders.values())
                    if stock_slice <= 0 or total_weight <= 0:
                        continue
                    remaining_slice = stock_slice
                    for user_id, weight in holders.items():
                        amount = min(int(stock_slice * weight / total_weight), remaining_slice)
                        if amount > 0:
                            payouts.append({"user_id": user_id, "symbol": symbol, "weight": weight, "amount": amount})
                            remaining_slice -= amount

                total_credit = sum(item["amount"] for item in payouts)
                for item in payouts:
                    await db.execute(
                        """
                        INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                        ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + excluded.CurrencyAmount
                        """,
                        (item["user_id"], item["amount"]),
                    )
                    await db.execute(
                        """
                        INSERT INTO DividendPayouts (PeriodEnd, UserId, Symbol, Weight, Amount, DateAdded)
                        VALUES (?, ?, ?, ?, ?, datetime('now'))
                        """,
                        (period_key, item["user_id"], item["symbol"], item["weight"], item["amount"]),
                    )
                    await db.execute(
                        """
                        INSERT INTO CurrencyTransactions
                            (UserId, Type, Amount, Reason, OtherId, Extra, DateAdded)
                        VALUES (?, 'stock_dividend', ?, ?, NULL, ?, datetime('now'))
                        """,
                        (
                            item["user_id"],
                            item["amount"],
                            f"{item['symbol']} dividend for period ending {period_key}",
                            str(item["symbol"]),
                        ),
                    )

                recipients = len({item["user_id"] for item in payouts})
                await db.execute(
                    """
                    INSERT INTO DividendRuns (PeriodEnd, Distributed, Recipients, CompletedAt)
                    VALUES (?, ?, ?, datetime('now'))
                    """,
                    (period_key, total_credit, recipients),
                )
                await db.execute("UPDATE Stocks SET PeriodUsage = 0")
                await db.execute(
                    """
                    INSERT INTO BotConfig (Key, Value, Description)
                    VALUES ('DividendAccumulationStart', ?, 'Start of the retained dividend usage window')
                    ON CONFLICT(Key) DO UPDATE SET Value = excluded.Value
                    """,
                    (period_key,),
                )
                await db.execute(
                    """
                    UPDATE YieldPool
                    SET Balance = Balance - ?, NextDistributionAt = ?, UpdatedAt = datetime('now')
                    WHERE Id = 1 AND Balance >= ?
                    """,
                    (total_credit, next_key, total_credit),
                )
                await db.commit()
                return DividendRunOutcome(
                    period_key,
                    OUTCOME_SETTLED,
                    total_credit,
                    recipients,
                    tuple(payouts),
                )
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def get_or_initialize_next_distribution(self, period_seconds: int, now: datetime) -> datetime:
        """Return persisted next-due time, seeding one period ahead if absent."""
        if period_seconds <= 0:
            raise ValueError("Distribution period must be positive.")
        async with self.db._get_connection() as db:
            pool = await self.get_yield_pool(db)
            raw = pool["next_distribution_at"]
            if raw:
                return datetime.fromisoformat(str(raw))
            next_at = now + timedelta(seconds=period_seconds)
            await db.execute(
                "UPDATE YieldPool SET NextDistributionAt = ?, UpdatedAt = datetime('now') WHERE Id = 1",
                (next_at.isoformat(sep=" "),),
            )
            await db.execute(
                """
                INSERT INTO BotConfig (Key, Value, Description)
                VALUES ('DividendAccumulationStart', ?, 'Start of the retained dividend usage window')
                ON CONFLICT(Key) DO NOTHING
                """,
                (now.isoformat(sep=" "),),
            )
            await db.commit()
            return next_at

    async def get_dividend_accumulation_start(self, default: datetime) -> datetime:
        """Return the usage window start, which advances only after a reset."""
        async with self.db._get_connection() as db:
            row = await (
                await db.execute("SELECT Value FROM BotConfig WHERE Key = 'DividendAccumulationStart'")
            ).fetchone()
            if row and row[0]:
                return datetime.fromisoformat(str(row[0]))
            await db.execute(
                """
                INSERT INTO BotConfig (Key, Value, Description)
                VALUES ('DividendAccumulationStart', ?, 'Start of the retained dividend usage window')
                ON CONFLICT(Key) DO UPDATE SET Value = excluded.Value
                """,
                (default.isoformat(sep=" "),),
            )
            await db.commit()
            return default

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
                INSERT INTO GamblingStats (Feature, BetAmount, WinAmount, LossAmount)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(Feature) DO UPDATE SET
                    BetAmount = BetAmount + excluded.BetAmount,
                    WinAmount = WinAmount + excluded.WinAmount,
                    LossAmount = LossAmount + excluded.LossAmount
                """,
                (feature, bet_amount, win_amount, loss_amount),
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

    async def reserve_stakes(
        self,
        *,
        stakes: Sequence[tuple[str, int, int]],
        game: str,
        guild_id: int | None = None,
        source: str = "gambling",
        note: str = "",
    ) -> dict[str, OperationOutcome]:
        """Reserve several users' stakes atomically, or reserve none of them."""
        if not stakes or any(amount <= 0 for _, _, amount in stakes):
            raise ValueError("At least one positive stake is required.")
        if len({key for key, _, _ in stakes}) != len(stakes):
            raise ValueError("Stake keys must be unique.")

        async with self.db._get_connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                for key, user_id, amount in stakes:
                    inserted = await db.execute(
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
                    if inserted.rowcount == 0:
                        await db.execute("ROLLBACK")
                        return {key: await self._duplicate_outcome(key, user_id, db)}
                    debited = await db.execute(
                        """
                        UPDATE DiscordUser SET CurrencyAmount = CurrencyAmount - ?
                        WHERE UserId = ? AND CurrencyAmount >= ?
                        """,
                        (amount, user_id, amount),
                    )
                    if debited.rowcount == 0:
                        balance = await self._get_user_currency(user_id, db)
                        await db.execute("ROLLBACK")
                        return {
                            key: OperationOutcome(
                                key=key,
                                state=OUTCOME_INSUFFICIENT_FUNDS,
                                new_balance=balance,
                                amount=0,
                            )
                        }
                    await db.execute(
                        """
                        INSERT INTO CurrencyTransactions
                            (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                        VALUES (?, ?, ?, 'stake', NULL, ?, datetime('now'))
                        """,
                        (user_id, -amount, game, note or f"{game} stake"),
                    )
                await db.commit()
                return {
                    key: OperationOutcome(
                        key=key,
                        state=OUTCOME_RESERVED,
                        new_balance=await self._get_user_currency(user_id, db),
                        amount=amount,
                    )
                    for key, user_id, amount in stakes
                }
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
        exclude_from_rtp: bool = False,
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

                if not exclude_from_rtp:
                    await db.execute(
                        """
                        INSERT INTO GamblingStats
                            (Feature, BetAmount, WinAmount, LossAmount, Rounds,
                             StakedSinceEpoch, PaidOut, RakebackPaid, EpochStart)
                        VALUES (?, ?, ?, ?, 1, ?, ?, ?, datetime('now'))
                        ON CONFLICT(Feature) DO UPDATE SET
                            BetAmount = BetAmount + excluded.BetAmount,
                            WinAmount = WinAmount + excluded.WinAmount,
                            LossAmount = LossAmount + excluded.LossAmount,
                            Rounds = Rounds + 1,
                            StakedSinceEpoch = StakedSinceEpoch + excluded.StakedSinceEpoch,
                            PaidOut = PaidOut + excluded.PaidOut,
                            RakebackPaid = RakebackPaid + excluded.RakebackPaid,
                            EpochStart = COALESCE(GamblingStats.EpochStart, excluded.EpochStart)
                        """,
                        (game, stake, win_amount, loss, stake, payout, rakeback_amount),
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
                    await self.accrue_yield_pool(
                        db,
                        stake - payout - rakeback_amount,
                        POOL_SOURCE_HOUSE_BANKED,
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

    async def settle_pool(
        self,
        *,
        settlement_id: str,
        stakes: Mapping[str, str],
        winning_side: str | None,
        game: str,
        transaction_type: str | None = None,
        void: bool = False,
        note: str = "",
    ) -> PoolSettlementOutcome:
        """Settle a set of reserved stakes as one atomic parimutuel pool.

        ``stakes`` maps each reservation key to its side. A void settlement
        refunds in full and is excluded from RTP statistics.
        """
        if not settlement_id or not stakes:
            raise ValueError("A settlement id and at least one stake are required.")
        if not void and winning_side is None:
            raise ValueError("A winning side is required for a non-void settlement.")

        async with self.db._get_connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                marker_key = f"pool-settlement:{settlement_id}"
                marker = await db.execute(
                    """
                    INSERT INTO EconomyOperations
                        (OperationKey, GuildId, UserId, Source, Direction, Amount,
                         State, Result, CreatedAt, SettledAt)
                    VALUES (?, NULL, 0, 'pooled_settlement', 'credit', 0,
                            'settled', '{}', datetime('now'), datetime('now'))
                    ON CONFLICT(OperationKey) DO NOTHING
                    """,
                    (marker_key,),
                )
                if marker.rowcount == 0:
                    existing_marker = await self._get_operation_row(marker_key, db)
                    stored = self._decode_result(existing_marker["Result"] if existing_marker else None)
                    await db.execute("ROLLBACK")
                    return PoolSettlementOutcome(
                        settlement_id=settlement_id,
                        state=OUTCOME_DUPLICATE,
                        total_staked=int(stored.get("total_staked", 0)),
                        paid_out=int(stored.get("paid_out", 0)),
                        rake=int(stored.get("rake", 0)),
                        pool_accrual=int(stored.get("pool_accrual", 0)),
                        voided=bool(stored.get("voided", False)),
                        winning_side=stored.get("winning_side"),
                    )

                operations: dict[str, dict[str, Any]] = {}
                for key in stakes:
                    operation = await self._get_operation_row(key, db)
                    if operation is None:
                        await db.execute("ROLLBACK")
                        return PoolSettlementOutcome(settlement_id, OUTCOME_NOT_FOUND)
                    operations[key] = operation

                if any(op["State"] != OP_STATE_RESERVED for op in operations.values()):
                    await db.execute("ROLLBACK")
                    return PoolSettlementOutcome(settlement_id, OUTCOME_DUPLICATE)

                amounts = {key: int(op["Amount"]) for key, op in operations.items()}
                total_staked = sum(amounts.values())
                winner_keys = [key for key, side in stakes.items() if side == winning_side]
                loser_keys = [key for key, side in stakes.items() if side != winning_side]
                if not void and (not winner_keys or not loser_keys):
                    void = True

                payouts: dict[str, int]
                rakebacks: dict[str, int]
                rake = 0
                if void:
                    payouts = dict(amounts)
                    rakebacks = {key: 0 for key in amounts}
                else:
                    losing_stake = sum(amounts[key] for key in loser_keys)
                    rake = pooled_rake(total_staked, losing_stake)
                    post_rake_pool = total_staked - rake
                    winning_stake = sum(amounts[key] for key in winner_keys)
                    payouts = {
                        key: (post_rake_pool * amounts[key]) // winning_stake if key in winner_keys else 0
                        for key in amounts
                    }
                    rakebacks = {key: int(amounts[key] * RAKEBACK_RATE) if key in loser_keys else 0 for key in amounts}

                paid_out = sum(payouts.values())
                total_rakeback = sum(rakebacks.values())
                pool_accrual = 0 if void else total_staked - paid_out - total_rakeback
                summary = {
                    "settlement_id": settlement_id,
                    "voided": void,
                    "winning_side": None if void else winning_side,
                    "total_staked": total_staked,
                    "paid_out": paid_out,
                    "rake": rake,
                    "pool_accrual": pool_accrual,
                }
                await db.execute(
                    "UPDATE EconomyOperations SET Result = ? WHERE OperationKey = ?",
                    (json.dumps(summary), marker_key),
                )
                tx_type = transaction_type or game

                for key, operation in operations.items():
                    payout = payouts[key]
                    user_id = int(operation["UserId"])
                    claim = await db.execute(
                        """
                        UPDATE EconomyOperations
                        SET State = ?, SettledAt = datetime('now'), Result = ?
                        WHERE OperationKey = ? AND State = ?
                        """,
                        (OP_STATE_SETTLED, json.dumps({**summary, "payout": payout}), key, OP_STATE_RESERVED),
                    )
                    if claim.rowcount == 0:
                        raise RuntimeError("Pooled reservation changed during settlement.")
                    if payout:
                        await db.execute(
                            """
                            INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                            ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + excluded.CurrencyAmount
                            """,
                            (user_id, payout),
                        )
                        await db.execute(
                            """
                            INSERT INTO CurrencyTransactions
                                (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                            VALUES (?, ?, ?, ?, NULL, ?, datetime('now'))
                            """,
                            (user_id, payout, tx_type, "void" if void else "pooled", note),
                        )
                    rakeback_amount = rakebacks[key]
                    if rakeback_amount:
                        await db.execute(
                            """
                            INSERT INTO Rakeback (UserId, RakebackBalance) VALUES (?, ?)
                            ON CONFLICT(UserId) DO UPDATE SET
                                RakebackBalance = RakebackBalance + excluded.RakebackBalance
                            """,
                            (user_id, rakeback_amount),
                        )
                    if not void:
                        stake = amounts[key]
                        loss = max(0, stake - payout)
                        win_amount = payout if payout > stake else 0
                        await db.execute(
                            """
                            INSERT INTO GamblingStats
                                (Feature, BetAmount, WinAmount, LossAmount, Rounds,
                                 StakedSinceEpoch, PaidOut, RakebackPaid, EpochStart)
                            VALUES (?, ?, ?, ?, 1, ?, ?, ?, datetime('now'))
                            ON CONFLICT(Feature) DO UPDATE SET
                                BetAmount = BetAmount + excluded.BetAmount,
                                WinAmount = WinAmount + excluded.WinAmount,
                                LossAmount = LossAmount + excluded.LossAmount,
                                Rounds = Rounds + 1,
                                StakedSinceEpoch = StakedSinceEpoch + excluded.StakedSinceEpoch,
                                PaidOut = PaidOut + excluded.PaidOut,
                                RakebackPaid = RakebackPaid + excluded.RakebackPaid,
                                EpochStart = COALESCE(GamblingStats.EpochStart, excluded.EpochStart)
                            """,
                            (game, stake, win_amount, loss, stake, payout, rakeback_amount),
                        )
                        await db.execute(
                            """
                            INSERT INTO UserBetStats
                                (UserId, Game, BetAmount, WinAmount, LossAmount, MaxWin)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(UserId, Game) DO UPDATE SET
                                BetAmount = BetAmount + excluded.BetAmount,
                                WinAmount = WinAmount + excluded.WinAmount,
                                LossAmount = LossAmount + excluded.LossAmount,
                                MaxWin = MAX(MaxWin, excluded.MaxWin)
                            """,
                            (user_id, game, stake, win_amount, loss, win_amount),
                        )

                if pool_accrual:
                    await self.accrue_yield_pool(db, pool_accrual, POOL_SOURCE_POOLED)
                await db.commit()
                return PoolSettlementOutcome(
                    settlement_id=settlement_id,
                    state=OUTCOME_SETTLED,
                    payouts=payouts,
                    rakeback=rakebacks,
                    total_staked=total_staked,
                    paid_out=paid_out,
                    rake=rake,
                    pool_accrual=pool_accrual,
                    voided=void,
                    winning_side=None if void else winning_side,
                )
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def get_stale_reservations(self, threshold_seconds: int) -> list[dict[str, Any]]:
        """Return reservations older than the configured recovery threshold."""
        if threshold_seconds < 0:
            raise ValueError("Threshold must be non-negative.")
        modifier = f"-{threshold_seconds} seconds"
        async with self.db._get_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT OperationKey, UserId, Amount, Source, CreatedAt
                    FROM EconomyOperations
                    WHERE State = ? AND CreatedAt <= datetime('now', ?)
                    ORDER BY CreatedAt, Id
                    """,
                    (OP_STATE_RESERVED, modifier),
                )
            ).fetchall()
        return [
            {"key": row[0], "user_id": row[1], "amount": row[2], "source": row[3], "created_at": row[4]} for row in rows
        ]

    async def refund_stale_reservations(self, threshold_seconds: int) -> tuple[int, int]:
        """Refund stale reservations through ordinary, pool-neutral settlement."""
        reservations = await self.get_stale_reservations(threshold_seconds)
        return await self.refund_reservations(reservations)

    async def refund_reservations(self, reservations: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
        """Refund an explicit reservation snapshot without sweeping newer games."""
        count = 0
        total = 0
        for reservation in reservations:
            outcome = await self.settle_stake(
                key=str(reservation["key"]),
                payout=int(reservation["amount"]),
                transaction_type="gambling_refund",
                extra="restart_reconciliation",
                note="Refunded interrupted game stake",
                result={"result": "restart_refund"},
                exclude_from_rtp=True,
            )
            if outcome.state == OUTCOME_SETTLED:
                count += 1
                total += int(reservation["amount"])
        if count:
            log.warning("Refunded %s stale gambling reservation(s), total=%s", count, total)
        return count, total

    async def create_spectator_market(self, hand_key: str) -> int:
        """Open one side-wagering market for a live blackjack hand."""
        async with self.db._get_connection() as db:
            cursor = await db.execute(
                """
                INSERT INTO SpectatorMarkets (HandKey, State, OpenedAt)
                VALUES (?, 'open', datetime('now'))
                """,
                (hand_key,),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def place_spectator_bet(
        self,
        *,
        market_id: int,
        player_id: int,
        user_id: int,
        side: str,
        amount: int,
        market_cap: int,
        guild_id: int | None = None,
    ) -> dict[str, Any]:
        """Reserve a side wager atomically under one shared whole-market cap."""
        if side not in {"win", "lose"}:
            raise ValueError("Side must be 'win' or 'lose'.")
        if amount <= 0 or market_cap <= 0:
            raise ValueError("Amount and market cap must be positive.")
        if user_id == player_id:
            return {"state": "player_forbidden"}

        async with self.db._get_connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                market = await (
                    await db.execute("SELECT State FROM SpectatorMarkets WHERE Id = ?", (market_id,))
                ).fetchone()
                if market is None or market[0] != "open":
                    await db.execute("ROLLBACK")
                    return {"state": "closed"}
                total = int(
                    (
                        await (
                            await db.execute(
                                "SELECT COALESCE(SUM(Amount), 0) FROM SpectatorBets WHERE MarketId = ?",
                                (market_id,),
                            )
                        ).fetchone()
                    )[0]
                )
                # D5a: one total cap across both sides. Refuse the full incoming
                # stake; partial fills would obscure whether the market is full.
                # This bounds profitable player/confederate collusion. The
                # residual risk is deliberate tanking for non-economic motives.
                if total + amount > market_cap:
                    await db.execute("ROLLBACK")
                    return {"state": "full", "remaining": max(0, market_cap - total)}

                existing = await (
                    await db.execute(
                        "SELECT Side, Amount, StakeKey FROM SpectatorBets WHERE MarketId = ? AND UserId = ?",
                        (market_id, user_id),
                    )
                ).fetchone()
                if existing is not None and existing[0] != side:
                    await db.execute("ROLLBACK")
                    return {"state": "opposite_side"}

                debit = await db.execute(
                    """
                    UPDATE DiscordUser SET CurrencyAmount = CurrencyAmount - ?
                    WHERE UserId = ? AND CurrencyAmount >= ?
                    """,
                    (amount, user_id, amount),
                )
                if debit.rowcount == 0:
                    balance = await self._get_user_currency(user_id, db)
                    await db.execute("ROLLBACK")
                    return {"state": OUTCOME_INSUFFICIENT_FUNDS, "balance": balance}

                if existing is None:
                    stake_key = f"spectator:{market_id}:{user_id}"
                    await db.execute(
                        """
                        INSERT INTO EconomyOperations
                            (OperationKey, GuildId, UserId, Source, Direction, Amount, State, Result, CreatedAt)
                        VALUES (?, ?, ?, 'spectator', 'debit', ?, 'reserved', ?, datetime('now'))
                        """,
                        (stake_key, guild_id, user_id, amount, json.dumps({"game": "spectator"})),
                    )
                    await db.execute(
                        """
                        INSERT INTO SpectatorBets (MarketId, UserId, Side, Amount, StakeKey)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (market_id, user_id, side, amount, stake_key),
                    )
                    position = amount
                else:
                    stake_key = str(existing[2])
                    position = int(existing[1]) + amount
                    await db.execute(
                        "UPDATE SpectatorBets SET Amount = ? WHERE MarketId = ? AND UserId = ?",
                        (position, market_id, user_id),
                    )
                    await db.execute(
                        "UPDATE EconomyOperations SET Amount = Amount + ? WHERE OperationKey = ? AND State = 'reserved'",
                        (amount, stake_key),
                    )
                await db.execute(
                    """
                    INSERT INTO CurrencyTransactions
                        (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                    VALUES (?, ?, 'spectator', 'stake', NULL, ?, datetime('now'))
                    """,
                    (user_id, -amount, f"Blackjack spectator wager: player {side}s"),
                )
                await db.commit()
                return {
                    "state": OUTCOME_RESERVED,
                    "stake_key": stake_key,
                    "position": position,
                    "market_total": total + amount,
                }
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def close_spectator_market(self, market_id: int) -> list[dict[str, Any]]:
        """Close a market once and return all durable positions."""
        async with self.db._get_connection() as db:
            await db.execute(
                """
                UPDATE SpectatorMarkets SET State = 'closed', ClosedAt = datetime('now')
                WHERE Id = ? AND State = 'open'
                """,
                (market_id,),
            )
            rows = await (
                await db.execute(
                    "SELECT UserId, Side, Amount, StakeKey FROM SpectatorBets WHERE MarketId = ? ORDER BY Id",
                    (market_id,),
                )
            ).fetchall()
            await db.commit()
        return [{"user_id": row[0], "side": row[1], "amount": row[2], "stake_key": row[3]} for row in rows]

    async def settle_spectator_market(self, market_id: int, winning_side: str | None) -> PoolSettlementOutcome | None:
        """Settle or void a closed blackjack side market idempotently."""
        async with self.db._get_connection() as db:
            market = await (
                await db.execute("SELECT State, Outcome FROM SpectatorMarkets WHERE Id = ?", (market_id,))
            ).fetchone()
        if market is None:
            return None
        if market[0] in {"settled", "void"}:
            return PoolSettlementOutcome(
                settlement_id=f"spectator:{market_id}",
                state=OUTCOME_DUPLICATE,
                voided=market[0] == "void",
                winning_side=market[1],
            )
        positions = await self.close_spectator_market(market_id)
        if not positions:
            return None
        sides = {str(position["side"]) for position in positions}
        void = winning_side is None or len(sides) < 2
        outcome = await self.settle_pool(
            settlement_id=f"spectator:{market_id}",
            stakes={str(position["stake_key"]): str(position["side"]) for position in positions},
            winning_side=winning_side,
            game="spectator",
            void=void,
            note="Blackjack spectator market settlement",
        )
        async with self.db._get_connection() as db:
            await db.execute(
                """
                UPDATE SpectatorMarkets
                SET State = ?, Outcome = ?, ClosedAt = COALESCE(ClosedAt, datetime('now'))
                WHERE Id = ?
                """,
                ("void" if outcome.voided else "settled", outcome.winning_side, market_id),
            )
            await db.commit()
        return outcome
