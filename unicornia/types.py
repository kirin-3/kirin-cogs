"""
Type definitions for Unicornia cog.
"""

from typing import TypedDict, Optional, List, Tuple, Dict, Any
from dataclasses import dataclass

@dataclass
class LevelStats:
    """Represents a user's level statistics.

    Attributes:
        level: Current level.
        level_xp: XP gained towards the next level.
        required_xp: Total XP required to reach the next level.
        total_xp: Total accumulated XP.
    """
    level: int
    level_xp: int
    required_xp: int
    total_xp: int

class ShopEntryData(TypedDict):
    """Represents a raw shop entry from the database.
    
    Attributes:
        id: Unique identifier for the entry.
        index: Display order index.
        price: Cost of the item.
        name: Name of the item.
        author_id: ID of the user who created the item.
        type: Item type identifier.
        role_name: Name of the role (if applicable).
        role_id: ID of the role (if applicable).
        role_requirement: ID of required role to purchase (if applicable).
        command: Command to execute (deprecated).
    """
    id: int
    index: int
    price: int
    name: str
    author_id: int
    type: int
    role_name: Optional[str]
    role_id: Optional[int]
    role_requirement: Optional[int]
    command: Optional[str]

class ShopItem(ShopEntryData):
    """Represents a full shop item including additional items.
    
    Attributes:
        additional_items: List of (id, text) tuples for additional item details.
    """
    additional_items: List[Tuple[int, str]]

class UserInventoryItem(TypedDict):
    """Represents an item in a user's inventory.
    
    Attributes:
        id: Shop entry ID.
        quantity: Amount owned.
        index: Display order index.
        name: Name of the item.
        price: Value of the item.
        type: Item type identifier.
    """
    id: int
    quantity: int
    index: int
    name: str
    price: int
    type: int

class ClubData(TypedDict):
    """Represents club information.
    
    Attributes:
        id: Unique identifier.
        name: Club name.
        description: Club description.
        image_url: URL to club icon.
        banner_url: URL to club banner.
        xp: Total club XP.
        owner_id: ID of the club owner.
        date_added: Creation timestamp.
    """
    id: int
    name: str
    description: Optional[str]
    image_url: Optional[str]
    banner_url: Optional[str]
    xp: int
    owner_id: int
    date_added: str

class ClubMember(TypedDict):
    """Represents a club member.
    
    Attributes:
        user_id: Discord user ID.
        username: Discord username.
        avatar_id: Avatar hash.
        total_xp: User's total XP.
        is_admin: Whether the user is a club admin.
    """
    user_id: int
    username: str
    avatar_id: Optional[str]
    total_xp: int
    is_admin: bool

class ClubUserInfo(TypedDict):
    """Represents basic user information in club context.
    
    Attributes:
        user_id: Discord user ID.
        username: Discord username.
        avatar_id: Avatar hash.
        total_xp: User's total XP.
    """
    user_id: int
    username: str
    avatar_id: Optional[str]
    total_xp: int

class WaifuData(TypedDict):
    """Represents waifu information.
    
    Attributes:
        waifu_id: ID of the waifu (User ID).
        claimer_id: ID of the user who claimed this waifu.
        price: Current price/value.
        affinity: ID of affinity partner.
        date_added: Last update timestamp.
    """
    waifu_id: int
    claimer_id: Optional[int]
    price: int
    affinity: Optional[int]
    date_added: str

class WaifuGift(TypedDict):
    """Represents a waifu gift configuration.
    
    Attributes:
        name: Name of the gift.
        emoji: Emoji representation.
        price: Cost of the gift.
        negative: Whether it decreases value.
    """
    name: str
    emoji: str
    price: int
    negative: bool

class TimelyInfo(TypedDict):
    """Represents timely claim information.
    
    Attributes:
        last_claim: ISO timestamp of last claim.
        streak: Current streak count.
    """
    last_claim: str
    streak: int

class GamblingResult(TypedDict, total=False):
    """Represents the result of a gambling game.
    
    Attributes:
        won: Whether the user won.
        result: Win/Loss/Draw string.
        roll: Dice roll value.
        threshold: Required roll to win.
        win_amount: Amount won.
        loss_amount: Amount lost.
        profit: Net gain/loss.
        error: Error key if game failed.
        balance: Current balance if insufficient funds.
        user_choice: RPS choice of user.
        bot_choice: RPS choice of bot.
        rolls: Slot machine result rolls.
        win_type: Category of slot win.
        rung: Lucky ladder rung reached.
        multiplier: Payout multiplier.
        guess: Betflip guess.
    """
    won: bool
    result: str
    roll: int
    threshold: int
    win_amount: int
    loss_amount: int
    profit: int
    error: str
    balance: int
    user_choice: str
    bot_choice: str
    rolls: List[int]
    win_type: str
    rung: int
    multiplier: float
    guess: str

class DecayStats(TypedDict):
    """Represents currency decay configuration and stats.
    
    Attributes:
        decay_percent: Percentage to decay.
        max_decay: Maximum decay amount.
        min_threshold: Minimum wealth to trigger decay.
        interval_hours: Interval between runs.
        enabled: Whether decay is active.
    """
    decay_percent: float
    max_decay: int
    min_threshold: int
    interval_hours: int
    enabled: bool