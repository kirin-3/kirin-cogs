from redbot.core import commands

class UnicorniaError(commands.UserFeedbackCheckFailure):
    """Base exception for Unicornia errors."""
    pass

class DatabaseError(UnicorniaError):
    """Raised when a database operation fails."""
    pass

class SystemNotReadyError(UnicorniaError):
    """Raised when systems are not yet initialized."""
    def __init__(self):
        super().__init__("❌ Systems are still initializing. Please try again in a moment.")

class InsufficientFundsError(UnicorniaError):
    """Raised when a user has insufficient funds."""
    def __init__(self, required: int, current: int, currency_symbol: str = ""):
        super().__init__(f"❌ Insufficient funds. You need {required:,} {currency_symbol} but have {current:,} {currency_symbol}.")

class ItemNotFoundError(UnicorniaError):
    """Raised when a shop or inventory item is not found."""
    def __init__(self, item_name: str):
        super().__init__(f"❌ Item not found: {item_name}")

class InvalidOperationError(UnicorniaError):
    """Raised when an operation is invalid."""
    pass