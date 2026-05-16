"""ToolSessionManager — 工具节点侧 session 存储，按 session_id 索引。"""

from __future__ import annotations

from .session import ToolSession


class ToolSessionManager:
    """In-memory session store keyed by session_id — tool node layer only."""

    def __init__(self):
        self._sessions: dict[str, ToolSession] = {}

    def get_or_create(self, session_id: str) -> ToolSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = ToolSession(key=session_id)
        return self._sessions[session_id]

    def get(self, session_id: str) -> ToolSession | None:
        return self._sessions.get(session_id)

    def save(self, session: ToolSession) -> None:
        self._sessions[session.key] = session

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)