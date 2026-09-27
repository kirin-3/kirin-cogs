from redbot.core import commands


class UnicorniaError(commands.UserFeedbackCheckFailure):
    """Base exception for Unicornia errors. Red's error handler shows the message to the user."""

    pass


class SystemNotReadyError(UnicorniaError):
    """Raised when systems are not yet initialized."""

    def __init__(self):
        super().__init__("❌ Systems are still initializing. Please try again in a moment.")
