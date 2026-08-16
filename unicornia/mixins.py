"""
Mixin base class for Unicornia command mixins.

Declares the shared attributes that all command mixin classes access via
self.*, which are defined in Unicornia.__init__ and fully populated in
cog_load. All command handlers are protected by cog_check (which calls
_check_systems_ready), so every attribute is guaranteed to be initialized
when any mixin method runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redbot.core import Config
    from redbot.core.bot import Red

    from .database import DatabaseManager
    from .systems.club_system import ClubSystem
    from .systems.currency_systems import CurrencyDecay, CurrencyGeneration
    from .systems.economy_system import EconomySystem
    from .systems.gambling_system import GamblingSystem
    from .systems.market_system import MarketSystem
    from .systems.nitro_system import NitroSystem
    from .systems.shop_system import ShopSystem
    from .systems.waifu_system import WaifuSystem
    from .systems.xp_system import XPSystem


class UnicorniaMixinBase:
    """Base class that declares all shared Unicornia attributes for type checking.

    Attributes are declared as non-optional because cog_check enforces that all
    systems are initialized before any command handler is invoked.
    """

    if TYPE_CHECKING:
        bot: Red
        config: Config
        db: DatabaseManager
        xp_system: XPSystem
        economy_system: EconomySystem
        gambling_system: GamblingSystem
        currency_generation: CurrencyGeneration
        currency_decay: CurrencyDecay
        shop_system: ShopSystem
        club_system: ClubSystem
        waifu_system: WaifuSystem
        nitro_system: NitroSystem
        market_system: MarketSystem

        def invalidate_whitelist_cache(self, guild_id: int) -> None: ...
