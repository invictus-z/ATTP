"""Independent SessionManager – stores per-chat_id metadata."""

from __future__ import annotations

import logging
from .session import Session

logger = logging.getLogger(__name__)


class SessionManager:
    """In-memory session store keyed by chat_id."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def get_or_create(self, chat_id: str) -> Session:
        if chat_id not in self._sessions:
            self._sessions[chat_id] = Session(key=chat_id)
        return self._sessions[chat_id]

    def get(self, chat_id: str) -> Session | None:
        return self._sessions.get(chat_id)

    def save(self, session: Session) -> None:
        self._sessions[session.key] = session

    def delete(self, chat_id: str) -> None:
        self._sessions.pop(chat_id, None)
