"""Repository 基类，持有 Database 实例。"""

from __future__ import annotations

from attp.core.storage.database import Database


class BaseRepository:
    """所有 Repository 的基类，通过 self._db 访问数据库。"""

    def __init__(self, db: Database) -> None:
        self._db = db
