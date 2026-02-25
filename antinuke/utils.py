"""Utility classes and functions for the AntiNuke cog."""

import time
from collections import defaultdict
from typing import Dict, List, Optional

import discord


class ActionCache:
    """
    In-memory cache for tracking user actions within timeframes.
    
    This avoids disk I/O on every monitored action. Data is ephemeral
    and expires naturally based on timeframe windows.
    """

    def __init__(self) -> None:
        # Structure: {guild_id: {user_id: {action_type: [timestamps]}}}
        self._cache: Dict[int, Dict[int, Dict[str, List[float]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )

    def record_action(
        self, guild_id: int, user_id: int, action_type: str, timeframe: int
    ) -> int:
        """
        Record an action and return count within timeframe.
        
        Automatically cleans expired entries.
        
        Parameters
        ----------
        guild_id : int
            The guild ID where the action occurred.
        user_id : int
            The user ID who performed the action (0 for unknown).
        action_type : str
            The type of action (e.g., "channel_delete").
        timeframe : int
            The timeframe in seconds to consider.
        
        Returns
        -------
        int
            The number of actions within the timeframe.
        """
        current_time = time.time()
        cutoff = current_time - timeframe

        # Get the action list for this guild/user/action
        action_list = self._cache[guild_id][user_id][action_type]

        # Remove expired entries (in-place filter)
        action_list[:] = [ts for ts in action_list if ts > cutoff]

        # Add new action
        action_list.append(current_time)

        return len(action_list)

    def get_count(
        self, guild_id: int, user_id: int, action_type: str, timeframe: int
    ) -> int:
        """
        Get current count without adding a new action.
        
        Parameters
        ----------
        guild_id : int
            The guild ID.
        user_id : int
            The user ID.
        action_type : str
            The type of action.
        timeframe : int
            The timeframe in seconds.
        
        Returns
        -------
        int
            The count of actions within the timeframe.
        """
        current_time = time.time()
        cutoff = current_time - timeframe
        action_list = self._cache[guild_id][user_id][action_type]
        return sum(1 for ts in action_list if ts > cutoff)

    def clear_user(self, guild_id: int, user_id: int) -> None:
        """
        Clear all actions for a user (e.g., after quarantine).
        
        Parameters
        ----------
        guild_id : int
            The guild ID.
        user_id : int
            The user ID to clear.
        """
        if guild_id in self._cache and user_id in self._cache[guild_id]:
            del self._cache[guild_id][user_id]

    def clear_guild(self, guild_id: int) -> None:
        """
        Clear all actions for a guild.
        
        Parameters
        ----------
        guild_id : int
            The guild ID to clear.
        """
        if guild_id in self._cache:
            del self._cache[guild_id]


def has_dangerous_permission(
    before: discord.Permissions, after: discord.Permissions, dangerous_perms: List[str]
) -> Optional[str]:
    """
    Check if dangerous permissions were added to a role.
    
    Parameters
    ----------
    before : discord.Permissions
        Permissions before the change.
    after : discord.Permissions
        Permissions after the change.
    dangerous_perms : List[str]
        List of dangerous permission names.
    
    Returns
    -------
    Optional[str]
        The name of the dangerous permission added, or None.
    """
    for perm_name in dangerous_perms:
        # Check if the permission exists on Permissions object
        if not hasattr(after, perm_name):
            continue
        # Check if permission was NOT in before but IS in after
        if not getattr(before, perm_name, False) and getattr(after, perm_name, False):
            return perm_name
    return None


def get_permission_diff(
    before: discord.Permissions, after: discord.Permissions
) -> List[str]:
    """
    Get list of permissions that were added.
    
    Parameters
    ----------
    before : discord.Permissions
        Permissions before the change.
    after : discord.Permissions
        Permissions after the change.
    
    Returns
    -------
    List[str]
        List of permission names that were added.
    """
    added = []
    for perm_name, perm_value in discord.Permissions.VALID_FLAGS.items():
        if not getattr(before, perm_name) and getattr(after, perm_name):
            added.append(perm_name)
    return added


def format_permission_name(perm_name: str) -> str:
    """
    Format a permission name for display.
    
    Parameters
    ----------
    perm_name : str
        The internal permission name.
    
    Returns
    -------
    str
        Human-readable permission name.
    """
    return perm_name.replace("_", " ").title()


def is_above_in_hierarchy(bot_member: discord.Member, target: discord.Member) -> bool:
    """
    Check if the bot is above the target in role hierarchy.
    
    Parameters
    ----------
    bot_member : discord.Member
        The bot's member object.
    target : discord.Member
        The target member to check against.
    
    Returns
    -------
    bool
        True if bot is above target, False otherwise.
    """
    return bot_member.top_role > target.top_role
