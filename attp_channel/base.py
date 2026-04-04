"""Protocol plugin interface for decoupling agent-to-agent communication from the agent core."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import InboundMessage

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.session.manager import Session, SessionManager


@dataclass
class ProtocolContext:
    """Runtime resources provided by the host to every plugin.

    Populated by the gateway startup and passed once at initialize().
    Plugins store this reference and use it throughout their lifetime.
    """

    bus: MessageBus
    session_manager: SessionManager
    workspace: Path


class ProtocolPlugin(ABC):
    """Base class for protocol integration plugins.

    Lifecycle:
      1. Constructor receives protocol-specific config/resources.
      2. initialize(context) is called once at startup (async).
      3. Agent loop calls the other methods as needed during runtime.
      4. shutdown() is called on graceful exit (async).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin identifier (e.g. 'anp')."""
        ...

    async def initialize(self, context: ProtocolContext) -> None:
        """One-time async setup. Store context for later use."""
        self._context = context

    async def shutdown(self) -> None:
        """One-time async teardown."""
        pass

    # -- Tool contribution --

    def get_tools(self) -> list[Tool]:
        """Return Tool instances to register in the agent's ToolRegistry.

        Called once during AgentLoop.__init__ after default tools.
        If a plugin returns a tool whose name collides with a default tool,
        the plugin's version wins (it is registered second, overwriting).
        """
        return []

    def update_tool_context(
        self,
        channel: str,
        chat_id: str,
        message_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Called when the current message context changes.

        Plugins that contribute tools can update tool routing state here.
        """
        pass

    # -- System prompt contribution --

    def get_system_prompt_extension(self) -> str | None:
        """Return markdown to append to the system prompt, or None."""
        return None

    # -- Message preprocessing --

    async def on_inbound_message(
        self, msg: InboundMessage, session: Session
    ) -> InboundMessage | None:
        """Preprocess or intercept an inbound message.

        Receives the original message and the resolved session.
        Return:
          - The (possibly modified) InboundMessage to continue processing.
          - None to swallow the message entirely (plugin handled it).
        """
        return msg

    # -- API routes for Web UI --

    def get_api_router(self) -> Any | None:
        """Return a FastAPI APIRouter to mount on the WebUI app, or None.

        Called once after initialize(). Routes are mounted with include_router().
        """
        return None

    # -- Background tasks --

    def get_background_tasks(self) -> list:
        """Return coroutines to run as background asyncio tasks.

        Called by the gateway after initialize(). Each returned coroutine
        is wrapped in an asyncio.Task and gathered with other tasks.
        """
        return []

    # -- Status --

    def get_status(self) -> dict[str, Any]:
        """Return a status dict for display/debugging."""
        return {"name": self.name, "status": "active"}
