"""行为记录控制器 — 按 node_type 分发已验证的行为记录。"""

from __future__ import annotations

from attp.app.logging import get_logger

logger = get_logger("BehaviorCtrl")


class BehaviorController:
    """根据 node_type 将已验证的行为记录分发到对应处理器。"""

    async def handle(self, node_type: str, body: dict, intercept_result, stored_msg=None) -> dict:
        """分发行为记录到对应类型的处理器。

        Args:
            node_type: 节点类型（agent/tool/user）。
            body: 原始请求 body。
            intercept_result: InterceptResult 实例。
            stored_msg: Branch B 时携带的 PendingMessage（可选）。

        Returns:
            处理结果 dict。
        """
        handler = {
            "agent": self._handle_agent,
            "tool": self._handle_tool,
            "user": self._handle_user,
        }.get(node_type, self._handle_unknown)
        return await handler(body, intercept_result, stored_msg)

    async def _handle_agent(self, body: dict, result, stored_msg=None) -> dict:
        """Agent 类型行为记录。"""
        return {"status": "ok", "routed_to": "agent"}

    async def _handle_tool(self, body: dict, result, stored_msg=None) -> dict:
        """Tool 类型行为记录（预留）。"""
        return {"status": "ok", "routed_to": "tool"}

    async def _handle_user(self, body: dict, result, stored_msg=None) -> dict:
        """User 类型行为记录（预留）。"""
        return {"status": "ok", "routed_to": "user"}

    async def _handle_unknown(self, body: dict, result, stored_msg=None) -> dict:
        """未知类型行为记录。"""
        node_type = getattr(result, "node_type", None) if result else None
        logger.warning("Unknown node_type in behavior controller: {}", node_type)
        return {"status": "ok", "routed_to": "unknown"}
