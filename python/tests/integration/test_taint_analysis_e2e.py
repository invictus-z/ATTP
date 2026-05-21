"""污点分析端到端测试 — 真实加密 + 真实 SQLite + 完整 FastAPI 管线。

覆盖：多跳会话、内容篡改检测、可信名单演化、hop_count 规则、
过期消息单回传、内容签名交叉验证、严重程度升级、并发会话隔离。
"""

from __future__ import annotations

import asyncio
import time

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from attp.core.authentication.did_resolver import DIDResolutionResult
from attp.core.authentication.signatures import sign_hash
from attp.core.message.event import RecordedHop
from attp.core.pn_tracer import ProtocolTracer
from attp.core.sessions.protocol_node.manager import ProtocolSessionManager
from attp.protocol_node.engine.behavior_controller import BehaviorController
from attp.protocol_node.engine.malicious_detector import MaliciousNodeDetector
from attp.protocol_node.ports.protocol_port import ProtocolPort

from tests.fixtures.crypto_helpers import (
    build_did_resolution_result,
    generate_secp256k1_keypair,
)
from tests.fixtures.sample_data import (
    TEST_AGENT_DID,
    TEST_TOOL_DID,
    TEST_USER_DID,
    make_back_message,
    make_session_id,
    make_nonce,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

FIXED_TS = 1_000_000.0
TEST_AGENT2_DID = "did:wba:localhost%3A8000:agent:agent02"
TEST_USER2_DID = "did:wba:localhost%3A8000:user:user02"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _content_sig(priv, sid, sender, target, hc=None, ts=FIXED_TS, content="hello"):
    hop = RecordedHop(session_id=sid, sender_did=sender, target_did=target,
                      content=content, timestamp=ts, hop_count=hc or [0, 0])
    return sign_hash(hop.content_hash(), priv)


def _make_signed_bp(
    node_did, nonce, session_id, sender_did, target_did,
    private_key, hop_count=None, content_sig=None, content_key=None,
    timestamp=FIXED_TS, content="hello", protocol_url="http://localhost:9000",
):
    """构造已签名的 BackMessage dict。"""
    msg = make_back_message(
        node_did=node_did, nonce=nonce, session_id=session_id,
        sender_did=sender_did, target_did=target_did,
        content=content, hop_count=hop_count or [0, 0],
        protocol_url=protocol_url,
    )
    if timestamp is not None:
        msg.recorded_hop.timestamp = timestamp
    msg.sign_identity(private_key)
    if content_sig is not None:
        msg.recorded_hop.sig_content = content_sig
    else:
        msg.sign_content(content_key if content_key is not None else private_key)
    return msg.to_dict()


async def _send_verified_hop(
    client, sender_priv, receiver_priv, content_key,
    sid, sender_did, target_did, sender_node_did, receiver_node_did,
    hop_count, content="hello", ts=FIXED_TS,
):
    """发送完整双 BP（Branch A + Branch B），返回 BP2 响应。"""
    nonce = make_nonce()
    sig = _content_sig(content_key, sid, sender_did, target_did, hc=hop_count, ts=ts, content=content)

    bp1 = _make_signed_bp(
        node_did=sender_node_did, nonce=nonce, session_id=sid,
        sender_did=sender_did, target_did=target_did,
        private_key=sender_priv, hop_count=hop_count,
        content_sig=sig, timestamp=ts, content=content,
    )
    r1 = await client.post("/record", json=bp1)
    assert r1.json()["status"] == "stored", f"BP1 failed: {r1.json()}"

    bp2 = _make_signed_bp(
        node_did=receiver_node_did, nonce=nonce, session_id=sid,
        sender_did=sender_did, target_did=target_did,
        private_key=receiver_priv, hop_count=hop_count,
        content_sig=sig, timestamp=ts, content=content,
    )
    r2 = await client.post("/record", json=bp2)
    return r2


def _force_expire_pending(session_manager, sid, nonce):
    """将指定 pending message 标记为过期。"""
    session = session_manager.get(sid)
    pending = session.pending_messages.get(nonce)
    if pending:
        pending.stored_at = time.time() - 600


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
def agent2_keys():
    return generate_secp256k1_keypair()


@pytest_asyncio.fixture
def user2_keys():
    return generate_secp256k1_keypair()


@pytest_asyncio.fixture
async def tracer(tmp_path):
    db_path = str(tmp_path / "taint_test.db")
    return await ProtocolTracer.create(db_path)


@pytest_asyncio.fixture
def session_manager():
    return ProtocolSessionManager()


@pytest_asyncio.fixture
def behavior_controller():
    return BehaviorController()


@pytest_asyncio.fixture
def mock_did_resolver(agent_keys, tool_keys, user_keys, agent2_keys, user2_keys):
    from unittest.mock import AsyncMock

    resolver = AsyncMock()
    results = {
        TEST_AGENT_DID: build_did_resolution_result(TEST_AGENT_DID, agent_keys[1], "agent"),
        TEST_TOOL_DID: build_did_resolution_result(TEST_TOOL_DID, tool_keys[1], "tool"),
        TEST_USER_DID: build_did_resolution_result(TEST_USER_DID, user_keys[1], "user"),
        TEST_AGENT2_DID: build_did_resolution_result(TEST_AGENT2_DID, agent2_keys[1], "agent"),
        TEST_USER2_DID: build_did_resolution_result(TEST_USER2_DID, user2_keys[1], "user"),
    }

    async def _resolve_full(did, key_fragment="key-1"):
        return results.get(did, DIDResolutionResult(public_key=None, node_type=None, did_document=None))

    resolver.resolve_full = _resolve_full
    return resolver


@pytest_asyncio.fixture
def malicious_detector(mock_did_resolver):
    return MaliciousNodeDetector(mock_did_resolver)


@pytest_asyncio.fixture
async def app(tracer, session_manager, mock_did_resolver, behavior_controller, malicious_detector):
    port = ProtocolPort(
        tracer=tracer, session_manager=session_manager,
        host="0.0.0.0", port=9000,
        did_resolver=mock_did_resolver,
        behavior_controller=behavior_controller,
        malicious_detector=malicious_detector,
    )
    return port._app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ═══════════════════════════════════════════════════════════════════════════
# 1. 完整多跳会话
# ═══════════════════════════════════════════════════════════════════════════


class TestCompleteMultiHopSession:
    """完整多跳会话：U2A → A2T → T2A → A2A → A2U"""

    @pytest.mark.asyncio
    async def test_full_5_hop_conversation(self, client, user_keys, agent_keys, tool_keys, agent2_keys):
        sid = make_session_id()

        # Hop 1: U2A [0,0] — 用户发送给 Agent
        r1 = await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID,
            [0, 0], content="帮我查北京天气", ts=FIXED_TS,
        )
        assert "verified" in r1.json()["status"]

        # Hop 2: A2T [0,1] — Agent 调用 Tool
        r2 = await _send_verified_hop(
            client, agent_keys[0], tool_keys[0], agent_keys[0],
            sid, TEST_AGENT_DID, TEST_TOOL_DID,
            TEST_AGENT_DID, TEST_TOOL_DID,
            [0, 1], content="调用天气API", ts=FIXED_TS + 1,
        )
        assert "verified" in r2.json()["status"]

        # Hop 3: T2A [0,2] — Tool 返回给 Agent
        r3 = await _send_verified_hop(
            client, tool_keys[0], agent_keys[0], tool_keys[0],
            sid, TEST_TOOL_DID, TEST_AGENT_DID,
            TEST_TOOL_DID, TEST_AGENT_DID,
            [0, 2], content="北京晴天 25°C", ts=FIXED_TS + 2,
        )
        assert "verified" in r3.json()["status"]

        # Hop 4: A2A [1,0] — Agent 转发给 Agent2
        r4 = await _send_verified_hop(
            client, agent_keys[0], agent2_keys[0], agent_keys[0],
            sid, TEST_AGENT_DID, TEST_AGENT2_DID,
            TEST_AGENT_DID, TEST_AGENT2_DID,
            [1, 0], content="请帮我润色回复", ts=FIXED_TS + 3,
        )
        assert "verified" in r4.json()["status"]

        # Hop 5: A2U [1,1] — Agent2 回复给 User
        r5 = await _send_verified_hop(
            client, agent2_keys[0], user_keys[0], agent2_keys[0],
            sid, TEST_AGENT2_DID, TEST_USER_DID,
            TEST_AGENT2_DID, TEST_USER_DID,
            [1, 1], content="北京今天晴天，气温25°C", ts=FIXED_TS + 4,
        )
        assert "verified" in r5.json()["status"]

        # 验证行为追踪
        resp = await client.get(f"/api/behavior/{sid}")
        data = resp.json()
        assert len(data["nodes"]) == 5

        # 验证 hop_count 排序
        nodes = data["nodes"]
        hcs = [n["hop_count"] for n in nodes]
        assert hcs == [[0, 0], [0, 1], [0, 2], [1, 0], [1, 1]]

    @pytest.mark.asyncio
    async def test_hop_count_progression_a2a_resets(self, client, user_keys, agent_keys, agent2_keys):
        sid = make_session_id()

        # U2A [0,0]
        await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID, [0, 0], ts=FIXED_TS,
        )
        # A2T [0,1]
        await _send_verified_hop(
            client, agent_keys[0], agent_keys[0], agent_keys[0],
            sid, TEST_AGENT_DID, TEST_TOOL_DID,
            TEST_AGENT_DID, TEST_TOOL_DID, [0, 1], ts=FIXED_TS + 1,
        )
        # A2A [1,0] — [0]从0→1, [1]归零
        r = await _send_verified_hop(
            client, agent_keys[0], agent2_keys[0], agent_keys[0],
            sid, TEST_AGENT_DID, TEST_AGENT2_DID,
            TEST_AGENT_DID, TEST_AGENT2_DID, [1, 0], ts=FIXED_TS + 2,
        )
        assert "verified" in r.json()["status"]

    @pytest.mark.asyncio
    async def test_hop_count_non_a2a_violation(self, client, user_keys, agent_keys, tool_keys):
        sid = make_session_id()

        # U2A [0,0]
        await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID, [0, 0], ts=FIXED_TS,
        )
        # 尝试 A2T [1,1]（[0]不应改变）
        nonce = make_nonce()
        sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID, hc=[1, 1], ts=FIXED_TS + 1)
        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=[1, 1], content_sig=sig, timestamp=FIXED_TS + 1,
        )
        await client.post("/record", json=bp1)
        bp2 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=[1, 1], content_sig=sig, timestamp=FIXED_TS + 1,
        )
        r = await client.post("/record", json=bp2)
        assert r.status_code == 400
        assert "Hop count violation" in r.json()["error"]
# ═══════════════════════════════════════════════════════════════════════════


class TestContentTamperingE2E:
    """ChainManager.verify_back_propagation 的真实篡改场景。"""

    @pytest.mark.asyncio
    async def test_tampered_content_same_sig(self, client, user_keys, agent_keys, tool_keys):
        """改内容但保留原签名 → verify_back_propagation 检测到篡改。"""
        sid = make_session_id()

        # 先完成 U2A，建立可信名单
        await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID, [0, 0], ts=FIXED_TS,
        )

        # A2T [0,1] — BP1 正常
        nonce = make_nonce()
        orig_content = "正常内容"
        sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID, hc=[0, 1], ts=FIXED_TS + 1, content=orig_content)

        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=[0, 1],
            content_sig=sig, timestamp=FIXED_TS + 1, content=orig_content,
        )
        await client.post("/record", json=bp1)

        # BP2 篡改内容但保留原签名
        bp2 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=[0, 1],
            content_sig=sig, timestamp=FIXED_TS + 1, content="被篡改的内容",
        )
        r = await client.post("/record", json=bp2)
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_tampered_content_resigned(self, client, user_keys, agent_keys, tool_keys):
        """改内容并用不同密钥重签 → verify_back_propagation 检测到篡改。"""
        sid = make_session_id()

        await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID, [0, 0], ts=FIXED_TS,
        )

        nonce = make_nonce()
        orig_content = "原始内容"
        sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID, hc=[0, 1], ts=FIXED_TS + 1, content=orig_content)

        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=[0, 1],
            content_sig=sig, timestamp=FIXED_TS + 1, content=orig_content,
        )
        await client.post("/record", json=bp1)

        # BP2 内容被篡改，且签名也用不同密钥重签
        tampered_sig = _content_sig(tool_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID, hc=[0, 1], ts=FIXED_TS + 1, content="被篡改的内容")
        bp2 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=[0, 1],
            content_sig=tampered_sig, timestamp=FIXED_TS + 1, content="被篡改的内容",
        )
        r = await client.post("/record", json=bp2)
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_previous_node_framing(self, client, user_keys, agent_keys, tool_keys):
        """BP1 的 content_sig 与 recorded_hop.sender_did 的公钥不匹配 → 栽赃检测。

        构造：sender_did=user 但 content_sig 用 agent 密钥签。
        verify_back_propagation 中 prev_public_key 是 user 的，
        用 user 公钥验证 agent 签名 → step1 失败。
        但签名相同 (step2=True)，内容哈希也相同 (step3=True)。
        结果："上一节点栽赃下一节点"
        """
        sid = make_session_id()

        await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID, [0, 0], ts=FIXED_TS,
        )

        nonce = make_nonce()
        content = "正常内容"
        # 用 agent 密钥签名，但 sender_did 声称是 user
        sig = _content_sig(agent_keys[0], sid, TEST_USER_DID, TEST_TOOL_DID, hc=[0, 1], ts=FIXED_TS + 1, content=content)

        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=[0, 1],
            content_sig=sig, timestamp=FIXED_TS + 1, content=content,
        )
        await client.post("/record", json=bp1)

        # BP2 携带相同的签名
        bp2 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=[0, 1],
            content_sig=sig, timestamp=FIXED_TS + 1, content=content,
        )
        r = await client.post("/record", json=bp2)
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# 3. 可信名单演化
# ═══════════════════════════════════════════════════════════════════════════


class TestTrustedListEvolution:
    """验证 trusted_did_list 在多跳验证中正确增长。"""

    @pytest.mark.asyncio
    async def test_trusted_list_grows(self, client, session_manager, user_keys, agent_keys, tool_keys):
        sid = make_session_id()

        # U2A → 可信名单追加 target (agent)
        await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID, [0, 0], ts=FIXED_TS,
        )
        session = session_manager.get(sid)
        assert session.get_trusted_did_list()[-1] == TEST_AGENT_DID

        # A2T → 可信名单追加 target (tool)
        await _send_verified_hop(
            client, agent_keys[0], tool_keys[0], agent_keys[0],
            sid, TEST_AGENT_DID, TEST_TOOL_DID,
            TEST_AGENT_DID, TEST_TOOL_DID, [0, 1], ts=FIXED_TS + 1,
        )
        session = session_manager.get(sid)
        assert session.get_trusted_did_list() == [TEST_AGENT_DID, TEST_TOOL_DID]

    @pytest.mark.asyncio
    async def test_trusted_list_violation_e2e(self, client, session_manager, user_keys, agent_keys, tool_keys):
        """跨跳可信名单违规 → 恶意检测。"""
        sid = make_session_id()

        # U2A → 可信名单: [agent]
        await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID, [0, 0], ts=FIXED_TS,
        )

        # 发送 BP1 (node_did=tool，与最新可信 agent 不匹配)
        nonce = make_nonce()
        sig = _content_sig(tool_keys[0], sid, TEST_TOOL_DID, TEST_TOOL_DID, hc=[0, 1], ts=FIXED_TS + 1)
        bp1 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_TOOL_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=[0, 1],
            content_sig=sig, timestamp=FIXED_TS + 1,
        )
        await client.post("/record", json=bp1)

        # BP2
        bp2 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_TOOL_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=[0, 1],
            content_sig=sig, timestamp=FIXED_TS + 1,
        )
        r = await client.post("/record", json=bp2)
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# 4. hop_count 规则
# ═══════════════════════════════════════════════════════════════════════════


class TestHopCountEnforcement:
    """详细的 hop_count 递增规则验证。"""

    async def _setup_u2a(self, client, user_keys, agent_keys, sid):
        await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID, [0, 0], ts=FIXED_TS,
        )

    @pytest.mark.asyncio
    async def test_a2a_correct_increment(self, client, user_keys, agent_keys, agent2_keys):
        sid = make_session_id()
        await self._setup_u2a(client, user_keys, agent_keys, sid)

        r = await _send_verified_hop(
            client, agent_keys[0], agent2_keys[0], agent_keys[0],
            sid, TEST_AGENT_DID, TEST_AGENT2_DID,
            TEST_AGENT_DID, TEST_AGENT2_DID, [1, 0], ts=FIXED_TS + 1,
        )
        assert "verified" in r.json()["status"]

    @pytest.mark.asyncio
    async def test_a2a_wrong_first(self, client, user_keys, agent_keys, agent2_keys):
        sid = make_session_id()
        await self._setup_u2a(client, user_keys, agent_keys, sid)

        nonce = make_nonce()
        hc = [2, 0]  # 错误：[0] 应该为 1（从 [0,0] +1）
        sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_AGENT2_DID, hc=hc, ts=FIXED_TS + 1)
        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_AGENT2_DID,
            private_key=agent_keys[0], hop_count=hc, content_sig=sig, timestamp=FIXED_TS + 1,
        )
        await client.post("/record", json=bp1)
        bp2 = _make_signed_bp(
            node_did=TEST_AGENT2_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_AGENT2_DID,
            private_key=agent2_keys[0], hop_count=hc, content_sig=sig, timestamp=FIXED_TS + 1,
        )
        r = await client.post("/record", json=bp2)
        assert r.status_code == 400
        assert "Hop count violation" in r.json()["error"]

    @pytest.mark.asyncio
    async def test_a2a_wrong_second(self, client, user_keys, agent_keys, agent2_keys):
        sid = make_session_id()
        await self._setup_u2a(client, user_keys, agent_keys, sid)

        nonce = make_nonce()
        hc = [1, 1]  # 错误：[1] 应该为 0
        sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_AGENT2_DID, hc=hc, ts=FIXED_TS + 1)
        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_AGENT2_DID,
            private_key=agent_keys[0], hop_count=hc, content_sig=sig, timestamp=FIXED_TS + 1,
        )
        await client.post("/record", json=bp1)
        bp2 = _make_signed_bp(
            node_did=TEST_AGENT2_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_AGENT2_DID,
            private_key=agent2_keys[0], hop_count=hc, content_sig=sig, timestamp=FIXED_TS + 1,
        )
        r = await client.post("/record", json=bp2)
        assert r.status_code == 400
        assert "Hop count violation" in r.json()["error"]

    @pytest.mark.asyncio
    async def test_non_a2a_wrong_first(self, client, user_keys, agent_keys, tool_keys):
        sid = make_session_id()
        await self._setup_u2a(client, user_keys, agent_keys, sid)

        nonce = make_nonce()
        hc = [1, 1]  # 错误：非A2A [0] 不能变
        sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID, hc=hc, ts=FIXED_TS + 1)
        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=hc, content_sig=sig, timestamp=FIXED_TS + 1,
        )
        await client.post("/record", json=bp1)
        bp2 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=hc, content_sig=sig, timestamp=FIXED_TS + 1,
        )
        r = await client.post("/record", json=bp2)
        assert r.status_code == 400
        assert "Hop count violation" in r.json()["error"]

    @pytest.mark.asyncio
    async def test_non_a2a_wrong_second(self, client, user_keys, agent_keys, tool_keys):
        sid = make_session_id()
        await self._setup_u2a(client, user_keys, agent_keys, sid)

        nonce = make_nonce()
        hc = [0, 2]  # 错误：[1] 应为 1（不是 2）
        sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID, hc=hc, ts=FIXED_TS + 1)
        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=hc, content_sig=sig, timestamp=FIXED_TS + 1,
        )
        await client.post("/record", json=bp1)
        bp2 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=hc, content_sig=sig, timestamp=FIXED_TS + 1,
        )
        r = await client.post("/record", json=bp2)
        assert r.status_code == 400
        assert "Hop count violation" in r.json()["error"]


# ═══════════════════════════════════════════════════════════════════════════
# 5. 过期消息单回传判定
# ═══════════════════════════════════════════════════════════════════════════


class TestPendingMessageExpiry:
    """PendingMessage 过期后触发单回传恶意判定。"""

    @pytest.mark.asyncio
    async def test_expired_identity_fail(self, client, session_manager, agent_keys, tool_keys):
        """过期 + 身份验证失败 → IDENTITY_TAMPERING。"""
        sid = make_session_id()

        # 先建立可信名单
        nonce_setup = make_nonce()
        sig_setup = _content_sig(tool_keys[0], sid, TEST_TOOL_DID, TEST_TOOL_DID, hc=[0, 0], ts=FIXED_TS)
        bp_setup1 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce_setup, session_id=sid,
            sender_did=TEST_TOOL_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=[0, 0], content_sig=sig_setup, timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp_setup1)
        bp_setup2 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce_setup, session_id=sid,
            sender_did=TEST_TOOL_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=[0, 0], content_sig=sig_setup, timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp_setup2)

        # 发送 BP1，用错误密钥签名身份
        nonce = make_nonce()
        sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID, hc=[0, 1], ts=FIXED_TS + 1)
        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0],  # 错误密钥签名身份
            hop_count=[0, 1], content_sig=sig, timestamp=FIXED_TS + 1,
        )
        await client.post("/record", json=bp1)

        # 手动过期
        _force_expire_pending(session_manager, sid, nonce)

        # 发送一条新消息触发 sweep
        trigger_nonce = make_nonce()
        trigger_sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID, hc=[0, 2], ts=FIXED_TS + 2)
        trigger = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=trigger_nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=[0, 2], content_sig=trigger_sig, timestamp=FIXED_TS + 2,
        )
        await client.post("/record", json=trigger)

        # 验证恶意报告已生成
        resp = await client.get(f"/api/malicious/session/{sid}")
        data = resp.json()
        assert data["total"] >= 1
        assert data["reports"][0]["evidence_type"] == "identity_tampering"

    @pytest.mark.asyncio
    async def test_expired_trusted_list_violation(self, client, session_manager, user_keys, agent_keys, tool_keys):
        """过期 + DID 不匹配 → TRUSTED_LIST_VIOLATION。"""
        sid = make_session_id()

        # U2A → 可信名单: [agent]
        await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID, [0, 0], ts=FIXED_TS,
        )

        # BP1 node_did=tool（与最新可信 agent 不匹配），身份签名正确
        nonce = make_nonce()
        sig = _content_sig(tool_keys[0], sid, TEST_TOOL_DID, TEST_TOOL_DID, hc=[0, 1], ts=FIXED_TS + 1)
        bp1 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_TOOL_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=[0, 1], content_sig=sig, timestamp=FIXED_TS + 1,
        )
        await client.post("/record", json=bp1)

        _force_expire_pending(session_manager, sid, nonce)

        # 触发 sweep
        trigger_nonce = make_nonce()
        trigger_sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID, hc=[0, 1], ts=FIXED_TS + 2)
        trigger = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=trigger_nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=[0, 1], content_sig=trigger_sig, timestamp=FIXED_TS + 2,
        )
        await client.post("/record", json=trigger)

        resp = await client.get(f"/api/malicious/session/{sid}")
        data = resp.json()
        assert data["total"] >= 1
        assert data["reports"][0]["evidence_type"] == "trusted_list_violation"

    @pytest.mark.asyncio
    async def test_expired_no_subsequent_discarded(self, client, session_manager, mock_did_resolver, user_keys, agent_keys):
        """过期 + 无后续 → 静默丢弃不产生报告。"""
        sid = make_session_id()

        # U2A → 可信名单: [agent]
        await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID, [0, 0], ts=FIXED_TS,
        )

        # BP1 node_did=agent（匹配可信名单），身份签名正确
        nonce = make_nonce()
        sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID, hc=[0, 1], ts=FIXED_TS + 1)
        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=[0, 1], content_sig=sig, timestamp=FIXED_TS + 1,
        )
        await client.post("/record", json=bp1)

        _force_expire_pending(session_manager, sid, nonce)

        # 手动进行单回传判定
        session = session_manager.get(sid)
        expired = session.pop_expired_pending_messages()
        assert len(expired) == 1

        detector = MaliciousNodeDetector(mock_did_resolver)
        report = await detector.evaluate_single_back_prop(expired[0][1], session)
        assert report is None


# ═══════════════════════════════════════════════════════════════════════════
# 6. 内容签名交叉验证
# ═══════════════════════════════════════════════════════════════════════════


class TestContentSignatureCrossVerification:
    """MaliciousNodeDetector 的双回传内容签名交叉验证端到端。"""

    @pytest.mark.asyncio
    async def test_cross_verify_passes(self, client, user_keys, agent_keys):
        """发送方公钥验证通过 → 无恶意报告。"""
        sid = make_session_id()
        nonce = make_nonce()

        # U2A: user 发给 agent。BP1 由 user 回传，BP2 由 agent 回传。
        sig = _content_sig(user_keys[0], sid, TEST_USER_DID, TEST_AGENT_DID, hc=[0, 0], ts=FIXED_TS)
        bp1 = _make_signed_bp(
            node_did=TEST_USER_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=user_keys[0], hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp1)

        bp2 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=agent_keys[0], hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS,
        )
        r = await client.post("/record", json=bp2)
        assert "verified" in r.json()["status"]

    @pytest.mark.asyncio
    async def test_indistinguishable_pair_e2e(self, client, user_keys, agent_keys, tool_keys):
        """BP1 和 BP2 的 content_sig 用不同密钥签 → INDISTINGUISHABLE_PAIR。"""
        sid = make_session_id()
        nonce = make_nonce()

        # BP1: content_sig 由 user 签
        sig1 = _content_sig(user_keys[0], sid, TEST_USER_DID, TEST_AGENT_DID, hc=[0, 0], ts=FIXED_TS)
        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=agent_keys[0], hop_count=[0, 0], content_sig=sig1, timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp1)

        # BP2: content_sig 由 tool 签（与 sender 的 user 不匹配）
        sig2 = _content_sig(tool_keys[0], sid, TEST_USER_DID, TEST_AGENT_DID, hc=[0, 0], ts=FIXED_TS)
        bp2 = _make_signed_bp(
            node_did=TEST_USER_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=user_keys[0], hop_count=[0, 0], content_sig=sig2, timestamp=FIXED_TS,
        )
        r = await client.post("/record", json=bp2)
        assert r.status_code == 403
        assert r.json().get("evidence_type") == "indistinguishable_pair"

    @pytest.mark.asyncio
    async def test_content_tampering_e2e(self, client, user_keys, agent_keys, tool_keys):
        """BP1 的 content_sig 与 sender_did 不匹配 → CONTENT_TAMPERING。"""
        sid = make_session_id()
        nonce = make_nonce()

        # BP1: sender_did=user 但 content_sig 由 agent 签（不是 sender）
        sig = _content_sig(agent_keys[0], sid, TEST_USER_DID, TEST_AGENT_DID, hc=[0, 0], ts=FIXED_TS)
        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=agent_keys[0], hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp1)

        bp2 = _make_signed_bp(
            node_did=TEST_USER_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=user_keys[0], hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS,
        )
        r = await client.post("/record", json=bp2)
        assert r.status_code == 403
        assert r.json().get("evidence_type") == "content_tampering"

    @pytest.mark.asyncio
    async def test_bp1_identity_tampering_e2e(self, client, agent_keys, tool_keys, user_keys):
        """BP1 身份签名验证失败 → IDENTITY_TAMPERING。"""
        sid = make_session_id()
        nonce = make_nonce()
        sig = _content_sig(user_keys[0], sid, TEST_USER_DID, TEST_AGENT_DID, hc=[0, 0], ts=FIXED_TS)

        # BP1: 用错误密钥签身份（用 tool 的密钥但声称是 agent）
        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=tool_keys[0], hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp1)

        bp2 = _make_signed_bp(
            node_did=TEST_USER_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=user_keys[0], hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS,
        )
        r = await client.post("/record", json=bp2)
        assert r.status_code == 403
        assert r.json().get("evidence_type") == "identity_tampering"


# ═══════════════════════════════════════════════════════════════════════════
# 7. 严重程度升级
# ═══════════════════════════════════════════════════════════════════════════


class TestSeverityEscalation:
    """不同证据类型累积升级。"""

    @pytest.mark.asyncio
    async def test_mixed_evidence_escalate(self, client, agent_keys, tool_keys):
        """不同类型的证据累积 → severity 升级到 dangerous。"""
        did = TEST_AGENT_DID

        # 违规 1: same_did_duplicate
        sid1 = make_session_id()
        sig1 = _content_sig(agent_keys[0], sid1, did, did, hc=[0, 0])
        bp1_1 = _make_signed_bp(node_did=did, nonce=make_nonce(), session_id=sid1,
                                sender_did=did, target_did=did, private_key=agent_keys[0],
                                hop_count=[0, 0], content_sig=sig1, timestamp=FIXED_TS)
        await client.post("/record", json=bp1_1)
        bp1_2 = _make_signed_bp(node_did=did, nonce=bp1_1["nonce"], session_id=sid1,
                                sender_did=did, target_did=did, private_key=agent_keys[0],
                                hop_count=[0, 0], content_sig=sig1, timestamp=FIXED_TS)
        await client.post("/record", json=bp1_2)

        # 违规 2-4: identity_tampering（用错误密钥签身份）
        for i in range(3):
            sid = make_session_id()
            nonce = make_nonce()
            sig = _content_sig(tool_keys[0], sid, did, TEST_TOOL_DID, hc=[0, 0])
            bp1 = _make_signed_bp(
                node_did=did, nonce=nonce, session_id=sid,
                sender_did=did, target_did=TEST_TOOL_DID,
                private_key=tool_keys[0],  # 错误密钥
                hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS + i,
            )
            await client.post("/record", json=bp1)
            bp2 = _make_signed_bp(
                node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
                sender_did=did, target_did=TEST_TOOL_DID,
                private_key=tool_keys[0],
                hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS + i,
            )
            await client.post("/record", json=bp2)

        dossier = await client.get(f"/api/malicious/dossier/{did}")
        data = dossier.json()
        assert data["found"] is True
        assert data["total_violations"] >= 4
        assert data["severity_level"] in ("dangerous", "banned")

    @pytest.mark.asyncio
    async def test_dossier_evidence_breakdown(self, client, agent_keys, tool_keys):
        """档案包含各类型证据的明细。"""
        did = TEST_AGENT_DID

        # same_did_duplicate ×2
        for _ in range(2):
            sid = make_session_id()
            sig = _content_sig(agent_keys[0], sid, did, did, hc=[0, 0])
            bp1 = _make_signed_bp(node_did=did, nonce=make_nonce(), session_id=sid,
                                  sender_did=did, target_did=did, private_key=agent_keys[0],
                                  hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS)
            await client.post("/record", json=bp1)
            bp2 = _make_signed_bp(node_did=did, nonce=bp1["nonce"], session_id=sid,
                                  sender_did=did, target_did=did, private_key=agent_keys[0],
                                  hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS)
            await client.post("/record", json=bp2)

        dossier = await client.get(f"/api/malicious/dossier/{did}")
        data = dossier.json()
        assert data["found"] is True
        breakdown = data.get("evidence_breakdown", {})
        assert breakdown.get("same_did_duplicate", 0) >= 2


# ═══════════════════════════════════════════════════════════════════════════
# 8. 并发会话隔离
# ═══════════════════════════════════════════════════════════════════════════


class TestConcurrentSessions:
    """两个并发会话互不干扰。"""

    @pytest.mark.asyncio
    async def test_two_sessions_isolated(self, client, user_keys, agent_keys, tool_keys):
        sid_a = make_session_id()
        sid_b = make_session_id()

        # Session A: U2A
        await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid_a, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID, [0, 0], ts=FIXED_TS,
        )
        # Session B: U2A
        await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid_b, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID, [0, 0], ts=FIXED_TS,
        )
        # Session A: A2T
        await _send_verified_hop(
            client, agent_keys[0], tool_keys[0], agent_keys[0],
            sid_a, TEST_AGENT_DID, TEST_TOOL_DID,
            TEST_AGENT_DID, TEST_TOOL_DID, [0, 1], ts=FIXED_TS + 1,
        )

        # 验证各自的行为追踪独立
        ra = await client.get(f"/api/behavior/{sid_a}")
        rb = await client.get(f"/api/behavior/{sid_b}")
        assert len(ra.json()["nodes"]) == 2
        assert len(rb.json()["nodes"]) == 1

    @pytest.mark.asyncio
    async def test_cross_session_no_nonce_leakage(self, client, user_keys, agent_keys):
        """相同 nonce 不同 session 不匹配。"""
        sid_a = make_session_id()
        sid_b = make_session_id()
        shared_nonce = make_nonce()

        sig_a = _content_sig(user_keys[0], sid_a, TEST_USER_DID, TEST_AGENT_DID, hc=[0, 0])
        bp_a = _make_signed_bp(
            node_did=TEST_USER_DID, nonce=shared_nonce, session_id=sid_a,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=user_keys[0], hop_count=[0, 0], content_sig=sig_a, timestamp=FIXED_TS,
        )
        r_a = await client.post("/record", json=bp_a)
        assert r_a.json()["status"] == "stored"

        sig_b = _content_sig(user_keys[0], sid_b, TEST_USER_DID, TEST_AGENT_DID, hc=[0, 0])
        bp_b = _make_signed_bp(
            node_did=TEST_USER_DID, nonce=shared_nonce, session_id=sid_b,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=user_keys[0], hop_count=[0, 0], content_sig=sig_b, timestamp=FIXED_TS,
        )
        r_b = await client.post("/record", json=bp_b)
        assert r_b.json()["status"] == "stored"  # 不同 session，不会匹配

    @pytest.mark.asyncio
    async def test_malicious_detection_isolated(self, client, user_keys, agent_keys):
        """恶意检测只影响对应 session。"""
        sid_clean = make_session_id()
        sid_malicious = make_session_id()
        did = TEST_AGENT_DID

        # Clean session: 正常 U2A
        sig_clean = _content_sig(user_keys[0], sid_clean, TEST_USER_DID, did, hc=[0, 0])
        bp_c1 = _make_signed_bp(node_did=TEST_USER_DID, nonce=make_nonce(), session_id=sid_clean,
                                sender_did=TEST_USER_DID, target_did=did, private_key=user_keys[0],
                                hop_count=[0, 0], content_sig=sig_clean, timestamp=FIXED_TS)
        await client.post("/record", json=bp_c1)
        bp_c2 = _make_signed_bp(node_did=did, nonce=bp_c1["nonce"], session_id=sid_clean,
                                sender_did=TEST_USER_DID, target_did=did, private_key=agent_keys[0],
                                hop_count=[0, 0], content_sig=sig_clean, timestamp=FIXED_TS)
        await client.post("/record", json=bp_c2)

        # Malicious session: same_did
        sig_m = _content_sig(agent_keys[0], sid_malicious, did, did, hc=[0, 0])
        bp_m1 = _make_signed_bp(node_did=did, nonce=make_nonce(), session_id=sid_malicious,
                                sender_did=did, target_did=did, private_key=agent_keys[0],
                                hop_count=[0, 0], content_sig=sig_m, timestamp=FIXED_TS)
        await client.post("/record", json=bp_m1)
        bp_m2 = _make_signed_bp(node_did=did, nonce=bp_m1["nonce"], session_id=sid_malicious,
                                sender_did=did, target_did=did, private_key=agent_keys[0],
                                hop_count=[0, 0], content_sig=sig_m, timestamp=FIXED_TS)
        await client.post("/record", json=bp_m2)

        r_clean = await client.get(f"/api/malicious/session/{sid_clean}")
        r_mal = await client.get(f"/api/malicious/session/{sid_malicious}")
        assert r_clean.json()["total"] == 0
        assert r_mal.json()["total"] >= 1


# ═══════════════════════════════════════════════════════════════════════════
# 9. 所有行为类型
# ═══════════════════════════════════════════════════════════════════════════


class TestAllBehaviorTypes:
    """5 种合法行为类型 + 无效组合。"""

    @pytest.mark.asyncio
    async def test_all_five_types(self, client, user_keys, agent_keys, tool_keys, agent2_keys):
        sid = make_session_id()

        # U2A: user → agent [0,0]
        r1 = await _send_verified_hop(
            client, user_keys[0], agent_keys[0], user_keys[0],
            sid, TEST_USER_DID, TEST_AGENT_DID,
            TEST_USER_DID, TEST_AGENT_DID, [0, 0], ts=FIXED_TS,
        )
        assert "verified" in r1.json()["status"]

        # A2T: agent → tool [0,1]
        r2 = await _send_verified_hop(
            client, agent_keys[0], tool_keys[0], agent_keys[0],
            sid, TEST_AGENT_DID, TEST_TOOL_DID,
            TEST_AGENT_DID, TEST_TOOL_DID, [0, 1], ts=FIXED_TS + 1,
        )
        assert "verified" in r2.json()["status"]

        # T2A: tool → agent [0,2]
        r3 = await _send_verified_hop(
            client, tool_keys[0], agent_keys[0], tool_keys[0],
            sid, TEST_TOOL_DID, TEST_AGENT_DID,
            TEST_TOOL_DID, TEST_AGENT_DID, [0, 2], ts=FIXED_TS + 2,
        )
        assert "verified" in r3.json()["status"]

        # A2A: agent → agent2 [1,0]
        r4 = await _send_verified_hop(
            client, agent_keys[0], agent2_keys[0], agent_keys[0],
            sid, TEST_AGENT_DID, TEST_AGENT2_DID,
            TEST_AGENT_DID, TEST_AGENT2_DID, [1, 0], ts=FIXED_TS + 3,
        )
        assert "verified" in r4.json()["status"]

        # A2U: agent2 → user [1,1]
        r5 = await _send_verified_hop(
            client, agent2_keys[0], user_keys[0], agent2_keys[0],
            sid, TEST_AGENT2_DID, TEST_USER_DID,
            TEST_AGENT2_DID, TEST_USER_DID, [1, 1], ts=FIXED_TS + 4,
        )
        assert "verified" in r5.json()["status"]

        # 验证所有类型都记录了
        resp = await client.get(f"/api/behavior/{sid}")
        nodes = resp.json()["nodes"]
        # API 按行为类型将 entries 分组到 A2T/A2U/U2A/A2A/T2A 字段中
        active_types = set()
        for n in nodes:
            for ft in ("U2A", "A2T", "T2A", "A2A", "A2U"):
                if n.get(ft):
                    active_types.add(ft)
        assert active_types == {"U2A", "A2T", "T2A", "A2A", "A2U"}

    @pytest.mark.asyncio
    async def test_invalid_combination(self, client, tool_keys):
        """tool → tool 不在 BEHAVIOR_TYPE_MAP 中 → 被拒绝。"""
        sid = make_session_id()
        nonce = make_nonce()
        sig = _content_sig(tool_keys[0], sid, TEST_TOOL_DID, TEST_TOOL_DID, hc=[0, 0])
        bp1 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_TOOL_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp1)
        bp2 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_TOOL_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS,
        )
        r = await client.post("/record", json=bp2)
        # same_did 检测会先触发（两个BP node_did 相同），但如果过了恶意检测，行为类型也会失败
        assert r.status_code in (400, 403)


# ═══════════════════════════════════════════════════════════════════════════
# 10. 档案查询 API
# ═══════════════════════════════════════════════════════════════════════════


class TestDossierAndQueryAPI:
    """档案查询端点完整测试。"""

    @pytest.mark.asyncio
    async def test_dossier_severity_filter(self, client, agent_keys, tool_keys):
        """按 severity 筛选档案。"""
        # 创建 warning 级别（1 次违规）
        did1 = TEST_AGENT_DID
        sid1 = make_session_id()
        sig1 = _content_sig(agent_keys[0], sid1, did1, did1, hc=[0, 0])
        bp1 = _make_signed_bp(node_did=did1, nonce=make_nonce(), session_id=sid1,
                              sender_did=did1, target_did=did1, private_key=agent_keys[0],
                              hop_count=[0, 0], content_sig=sig1, timestamp=FIXED_TS)
        await client.post("/record", json=bp1)
        bp1b = _make_signed_bp(node_did=did1, nonce=bp1["nonce"], session_id=sid1,
                               sender_did=did1, target_did=did1, private_key=agent_keys[0],
                               hop_count=[0, 0], content_sig=sig1, timestamp=FIXED_TS)
        await client.post("/record", json=bp1b)

        resp = await client.get("/api/malicious/dossiers")
        data = resp.json()
        assert data["total"] >= 1
        # 所有档案都有 severity_level
        for d in data["dossiers"]:
            assert "severity_level" in d

    @pytest.mark.asyncio
    async def test_dossier_incidents_detail(self, client, agent_keys):
        """档案包含完整的违规明细。"""
        did = TEST_AGENT_DID

        for i in range(3):
            sid = make_session_id()
            sig = _content_sig(agent_keys[0], sid, did, did, hc=[0, 0])
            bp1 = _make_signed_bp(node_did=did, nonce=make_nonce(), session_id=sid,
                                  sender_did=did, target_did=did, private_key=agent_keys[0],
                                  hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS + i)
            await client.post("/record", json=bp1)
            bp2 = _make_signed_bp(node_did=did, nonce=bp1["nonce"], session_id=sid,
                                  sender_did=did, target_did=did, private_key=agent_keys[0],
                                  hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS + i)
            await client.post("/record", json=bp2)

        dossier = await client.get(f"/api/malicious/dossier/{did}")
        data = dossier.json()
        assert data["found"] is True
        assert len(data["incidents"]) >= 3
        for inc in data["incidents"]:
            assert "session_id" in inc
            assert "evidence_type" in inc
            assert "timestamp" in inc

    @pytest.mark.asyncio
    async def test_query_by_did_cross_session(self, client, agent_keys):
        """按 DID 查询跨会话的恶意报告。"""
        did = TEST_AGENT_DID

        for _ in range(2):
            sid = make_session_id()
            sig = _content_sig(agent_keys[0], sid, did, did, hc=[0, 0])
            bp1 = _make_signed_bp(node_did=did, nonce=make_nonce(), session_id=sid,
                                  sender_did=did, target_did=did, private_key=agent_keys[0],
                                  hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS)
            await client.post("/record", json=bp1)
            bp2 = _make_signed_bp(node_did=did, nonce=bp1["nonce"], session_id=sid,
                                  sender_did=did, target_did=did, private_key=agent_keys[0],
                                  hop_count=[0, 0], content_sig=sig, timestamp=FIXED_TS)
            await client.post("/record", json=bp2)

        resp = await client.get(f"/api/malicious/did/{did}")
        data = resp.json()
        assert data["total"] >= 2
        sessions = {r["session_id"] for r in data["reports"]}
        assert len(sessions) >= 2
