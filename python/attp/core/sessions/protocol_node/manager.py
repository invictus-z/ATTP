"""ProtocolSessionManager — 协议节点层 session 存储，按 session_id 索引。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .session import ProtocolSession

if TYPE_CHECKING:
    from attp.core.storage import SqliteStore


class ProtocolSessionManager:
    """Session store keyed by session_id — protocol node layer only.

    When ``storage`` is provided, ``save()`` persists verification state
    (completed_nonces, last_hop_count, trusted_dids) to SQLite, and
    ``get_or_create()`` lazily restores it on first access.

    Without ``storage``, behaves as a pure in-memory dict (backward compatible).
    """

    def __init__(self, storage: SqliteStore | None = None):
        self._sessions: dict[str, ProtocolSession] = {}
        self._storage = storage

    async def get_or_create(self, session_id: str) -> ProtocolSession:
        if session_id not in self._sessions:
            session = ProtocolSession(key=session_id)
            if self._storage:
                saved = await self._storage.load_verification_state(session_id)
                if saved:
                    session.completed_nonces = saved["completed_nonces"]
                    if saved["last_hop_count"] is not None:
                        session.set_last_completed_hop_count(saved["last_hop_count"])
                    session.trusted_did_list = list(saved["trusted_dids"])
            self._sessions[session_id] = session
        return self._sessions[session_id]

    def get(self, session_id: str) -> ProtocolSession | None:
        return self._sessions.get(session_id)

    async def save(self, session: ProtocolSession) -> None:
        self._sessions[session.key] = session
        if self._storage:
            await self._storage.save_verification_state(
                session.key,
                {
                    "completed_nonces": session.completed_nonces,
                    "last_hop_count": session.get_last_completed_hop_count(),
                    "trusted_dids": session.get_trusted_did_list(),
                },
            )

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
