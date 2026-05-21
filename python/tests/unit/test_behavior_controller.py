"""行为控制器单元测试。"""

from unittest.mock import MagicMock

import pytest

from attp.protocol_node.engine.behavior_controller import BehaviorController


class TestBehaviorController:
    @pytest.fixture
    def controller(self):
        return BehaviorController()

    @pytest.mark.asyncio
    async def test_handle_agent(self, controller):
        result = await controller.handle("agent", {}, None)
        assert result["routed_to"] == "agent"
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_handle_tool(self, controller):
        result = await controller.handle("tool", {}, None)
        assert result["routed_to"] == "tool"

    @pytest.mark.asyncio
    async def test_handle_user(self, controller):
        result = await controller.handle("user", {}, None)
        assert result["routed_to"] == "user"

    @pytest.mark.asyncio
    async def test_handle_unknown(self, controller):
        mock_result = MagicMock()
        mock_result.node_type = "unknown_type"
        result = await controller.handle("unknown_type", {}, mock_result)
        assert result["routed_to"] == "unknown"
