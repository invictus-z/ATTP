"""AppSessionManager — App 层 session 存储，按 chat_id 索引。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from .session import AppSession


class AppSessionManager:
    """In-memory session store keyed by chat_id — App layer only.

    Provides per-session async locking via ``locked_session`` to prevent
    concurrent read-modify-write races (e.g. hop_count corruption).
    """

    def __init__(self):
        self._sessions: dict[str, AppSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, chat_id: str) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    def get_or_create(self, chat_id: str) -> AppSession:
        if chat_id not in self._sessions:
            self._sessions[chat_id] = AppSession(key=chat_id)
        return self._sessions[chat_id]

    def get(self, chat_id: str) -> AppSession | None:
        return self._sessions.get(chat_id)

    def save(self, session: AppSession) -> None:
        self._sessions[session.key] = session

    def delete(self, chat_id: str) -> None:
        self._sessions.pop(chat_id, None)
        self._locks.pop(chat_id, None)

    @asynccontextmanager
    async def locked_session(
        self, chat_id: str, *, create: bool = True
    ) -> AsyncGenerator[AppSession | None, None]:
        """Async context manager providing **exclusive** access to a session.

        Acquires a per-session lock so that only one coroutine can perform
        read-compute-write cycles on the same session at a time.

        Args:
            chat_id: Session key.
            create: If *True* (default), the session is created when missing.
                    If *False*, ``None`` is yielded for non-existent sessions.

        Usage::

            async with manager.locked_session(chat_id) as session:
                trace = session.get_trace_metadata()
                # ... compute hop, do I/O ...
                session.set_trace_metadata(new_trace)
                # save() is called automatically on exit
        """
        lock = self._get_lock(chat_id)
        async with lock:
            if create:
                session = self.get_or_create(chat_id)
            else:
                session = self.get(chat_id)
            yield session
            if session:
                self.save(session)
