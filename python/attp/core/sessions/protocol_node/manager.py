"""ProtocolSessionManager — 协议节点层 session 存储，按 session_id 索引。"""

from __future__ import annotations

from .session import ProtocolSession


class ProtocolSessionManager:
    """In-memory session store keyed by session_id — protocol node layer only.

    NOTE: ``save()`` currently re-assigns the same in-memory reference and is
    therefore a no-op (mutations on the returned object are immediately visible).
    It is retained as a hook for future persistence backends (Redis, DB, etc.).
    """

    def __init__(self):
        self._sessions: dict[str, ProtocolSession] = {}

    def get_or_create(self, session_id: str) -> ProtocolSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = ProtocolSession(key=session_id)
        return self._sessions[session_id]

    def get(self, session_id: str) -> ProtocolSession | None:
        return self._sessions.get(session_id)

    def save(self, session: ProtocolSession) -> None:
        self._sessions[session.key] = session

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
