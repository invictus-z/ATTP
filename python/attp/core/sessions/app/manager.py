"""AppSessionManager — App 层 session 存储，按 chat_id 索引。"""

from __future__ import annotations

from .session import AppSession


class AppSessionManager:
    """In-memory session store keyed by chat_id — App layer only."""

    def __init__(self):
        self._sessions: dict[str, AppSession] = {}

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
