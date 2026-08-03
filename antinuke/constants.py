"""Constants and default configuration for the AntiNuke cog."""

from typing import Any

# Config identifier - unique int for this cog
CONFIG_IDENTIFIER = 789234561

# Dangerous permissions that trigger monitoring
DANGEROUS_PERMISSIONS = [
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
    "ban_members",
    "kick_members",
    "manage_nicknames",
    "mention_everyone",
    "view_audit_log",
]

# Default monitor configuration for each action type
DEFAULT_MONITOR_CONFIG = {
    "enabled": True,
    "threshold": 2,
    "timeframe": 60,
    "action": "quarantine",
}

# Default guild configuration schema
DEFAULT_GUILD: dict[str, Any] = {
    # Schema version marker (see migrations.py); 0 = legacy unmigrated record
    "schema_version": 0,
    # Core Settings
    "enabled": False,
    "log_channel": None,
    "quarantine_role": None,
    # Trust System
    "trusted_users": [],
    "trusted_roles": [],
    # Monitored Actions with Thresholds
    "monitor": {
        # Channel Events
        "channel_create": {
            "enabled": True,
            "threshold": 3,
            "timeframe": 60,
            "action": "quarantine",
        },
        "channel_delete": {
            "enabled": True,
            "threshold": 2,
            "timeframe": 60,
            "action": "quarantine",
        },
        # Role Events
        "role_create": {
            "enabled": True,
            "threshold": 3,
            "timeframe": 60,
            "action": "quarantine",
        },
        "role_delete": {
            "enabled": True,
            "threshold": 2,
            "timeframe": 60,
            "action": "quarantine",
        },
        # Ban/Kick Events
        "ban": {
            "enabled": True,
            "threshold": 3,
            "timeframe": 120,
            "action": "quarantine",
        },
        "kick": {
            "enabled": True,
            "threshold": 3,
            "timeframe": 120,
            "action": "quarantine",
        },
        # Guild Prune - CRITICAL: Instant action
        "guild_prune": {
            "enabled": True,
            "threshold": 0,
            "timeframe": 60,
            "action": "quarantine",
        },
        # Webhook Events
        "webhook_create": {
            "enabled": True,
            "threshold": 2,
            "timeframe": 60,
            "action": "quarantine",
        },
        "webhook_delete": {
            "enabled": True,
            "threshold": 2,
            "timeframe": 60,
            "action": "quarantine",
        },
        # Permission Events
        "dangerous_permission_add": {
            "enabled": True,
            "threshold": 1,
            "timeframe": 60,
            "action": "quarantine",
            "permissions": DANGEROUS_PERMISSIONS.copy(),
        },
        # Vanity URL
        "vanity_change": {
            "enabled": True,
            "threshold": 1,
            "timeframe": 60,
            "action": "quarantine",
        },
        # Bot Add Events
        "bot_add": {
            "enabled": True,
            "threshold": 1,
            "timeframe": 60,
            "action": "quarantine",
            "kick_bot": True,
        },
    },
    # Quarantine Data (persistent)
    "quarantined_users": {},
}

# Global config (if needed for bot-wide settings)
DEFAULT_GLOBAL: dict[str, Any] = {}

# Action type to AuditLogAction mapping
AUDIT_LOG_ACTION_MAP = {
    "channel_create": "channel_create",
    "channel_delete": "channel_delete",
    "role_create": "role_create",
    "role_delete": "role_delete",
    "ban": "ban",
    "kick": "kick",
    "webhook_create": "webhook_create",
    "webhook_delete": "webhook_delete",
    "guild_prune": "guild_prune",
    "bot_add": "bot_add",
}

# Human-readable action names
ACTION_NAMES = {
    "channel_create": "Channel Creation",
    "channel_delete": "Channel Deletion",
    "role_create": "Role Creation",
    "role_delete": "Role Deletion",
    "ban": "Member Ban",
    "kick": "Member Kick",
    "guild_prune": "Guild Prune",
    "webhook_create": "Webhook Creation",
    "webhook_delete": "Webhook Deletion",
    "dangerous_permission_add": "Dangerous Permission Addition",
    "vanity_change": "Vanity URL Change",
    "bot_add": "Bot Addition",
}
