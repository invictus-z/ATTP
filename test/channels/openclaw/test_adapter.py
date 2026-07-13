"""Tests for OpenclawATTPAdapter component wiring (translation of ATTPChannel.start)."""
import pytest
from unittest.mock import MagicMock, patch

from attp.channels.openclaw.adapter import OpenclawATTPAdapter


def _build_adapter(pn_enabled=False, tool_ads=None):
    """Run _build() with every ATTP component mocked; return (adapter, mocks)."""
    with patch("attp.channels.openclaw.adapter.ConfigManager") as CM, \
         patch("attp.channels.openclaw.adapter.AgentTracer"), \
         patch("attp.channels.openclaw.adapter.WebApp") as WebApp, \
         patch("attp.channels.openclaw.adapter.AppSessionManager"), \
         patch("attp.channels.openclaw.adapter.ATTPClient") as Client, \
         patch("attp.channels.openclaw.adapter.ATTPServer") as Server, \
         patch("attp.channels.openclaw.adapter.HeartbeatManager") as HB, \
         patch("attp.channels.openclaw.adapter.MCPToolBridge") as Bridge, \
         patch("attp.channels.openclaw.adapter.mount_reply_route") as mount, \
         patch("attp.protocol_node.ProtocolNode") as PN:
        cm = MagicMock()
        cm.attp_config.protocol_node.enabled = pn_enabled
        cm.attp_config.tool.tool_node_ads = tool_ads or []
        CM.return_value = cm

        a = OpenclawATTPAdapter(
            config_path="x", webhook_url="http://gw/attp/inbound", token="t"
        )
        a._build()
        return a, dict(WebApp=WebApp, Server=Server, Client=Client,
                       Bridge=Bridge, HB=HB, mount=mount, PN=PN, cm=cm)


def test_build_wires_u2a_forwarder_to_webapp():
    a, m = _build_adapter()
    assert m["WebApp"].call_args.kwargs["channel_callback"] is a._u2a_cb
    assert a._u2a_cb.direction == "U2A"


def test_build_wires_a2a_forwarder_to_server():
    a, m = _build_adapter()
    assert m["Server"].call_args.kwargs["attp_channel_callback"] is a._a2a_cb
    assert a._a2a_cb.direction == "A2A"


def test_build_mounts_reply_route():
    a, m = _build_adapter()
    m["mount"].assert_called_once_with(a._web_app)


def test_build_passes_send_callback_to_toolbridge():
    a, m = _build_adapter()
    assert m["Bridge"].call_args.kwargs["send_callback"] == m["Client"].return_value.send_message


def test_protocol_node_skipped_when_disabled():
    a, m = _build_adapter(pn_enabled=False)
    assert not m["PN"].called
    assert a._protocol_node is None


def test_protocol_node_built_when_enabled():
    a, m = _build_adapter(pn_enabled=True)
    assert m["PN"].called
    assert a._protocol_node is m["PN"].return_value


@pytest.mark.asyncio
async def test_forwarder_posts_correct_inbound_payload():
    with patch("attp.channels.openclaw.adapter.post_inbound") as post:
        a = OpenclawATTPAdapter(
            config_path="x", webhook_url="http://gw/attp/inbound", token="tok"
        )
        cb = a._make_forwarder("A2A")
        ret = await cb(sender="did:wba:host:nanobot", chat_id="S1", content="hi", media=[])
        assert ret == "ok"
        post.assert_awaited_once_with(
            "http://gw/attp/inbound", "tok",
            {"session_id": "S1", "sender_did": "did:wba:host:nanobot",
             "content": "hi", "direction": "A2A"},
        )
