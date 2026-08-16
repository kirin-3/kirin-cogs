"""
Database models and operations for Unicornia
"""

import logging

from .db import (
    ClubRepository,
    CoreDB,
    EconomyRepository,
    ShopRepository,
    StockRepository,
    WaifuRepository,
    XPRepository,
)

log = logging.getLogger("red.kirin_cogs.unicornia.database")


class DatabaseManager(CoreDB):
    """Handles all database operations for Unicornia"""

    def __init__(
        self,
        db_path: str,
        nadeko_db_path: str | None = None,
        *,
        reconcile_reserved_on_initialize: bool = True,
    ):
        super().__init__(
            db_path,
            nadeko_db_path,
            reconcile_reserved_on_initialize=reconcile_reserved_on_initialize,
        )
        self.club = ClubRepository(self)
        self.economy = EconomyRepository(self)
        self.xp = XPRepository(self)
        self.waifu = WaifuRepository(self)
        self.shop = ShopRepository(self)
        self.stock = StockRepository(self)
