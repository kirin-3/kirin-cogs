"""
Database models and operations for Unicornia
"""

import logging
from .db import CoreDB, ClubRepository, EconomyRepository, XPRepository, WaifuRepository, ShopRepository, LevelStats, StockRepository

log = logging.getLogger("red.kirin_cogs.unicornia.database")

class DatabaseManager(CoreDB):
    """Handles all database operations for Unicornia"""
    
    def __init__(self, db_path: str, nadeko_db_path: str = None):
        super().__init__(db_path, nadeko_db_path)
        self.club = ClubRepository(self)
        self.economy = EconomyRepository(self)
        self.xp = XPRepository(self)
        self.waifu = WaifuRepository(self)
        self.shop = ShopRepository(self)
        self.stock = StockRepository(self)
