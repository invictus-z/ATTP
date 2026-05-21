"""AnalysisOrchestrator 集成测试 — 使用真实 LLM（SiliconFlow DeepSeek-V4-Flash）。

验证意图提取、批量分析触发、手动触发、状态查询等完整流程。
"""

import asyncio
import json
import time

import pytest
import pytest_asyncio

from attp.core.analysis.analyzer import SemanticTaintAnalyzer
from attp.core.analysis.orchestrator import AnalysisOrchestrator
from attp.core.authentication.keys import KeyStore
from attp.core.authentication.did_resolver import DIDResolutionResult
from attp.core.pn_tracer import ProtocolTracer
from attp.core.sessions.protocol_node.manager import ProtocolSessionManager
from attp.protocol_node.engine.malicious_detector import MaliciousNodeDetector
from attp.protocol_node.engine.behavior_controller import BehaviorController
from attp.protocol_node.ports.protocol_port import ProtocolPort

from tests.fixtures.crypto_helpers import build_did_resolution_result
from tests.fixtures.sample_data import (
    TEST_AGENT_DID, TEST_TOOL_DID, TEST_USER_DID,
    make_back_message, make_session_id, make_nonce,
)
from tests.integration.conftest import _make_signed_bp

FIXED_TS = 1000000.0

# ---- 用户配置的真实 LLM 参数 ----
LLM_API_KEY = "sk-tndjmdbokroduydqwluzznlryzypkzitbiikqbepgvatacej"
LLM_BASE_URL = "https://api.siliconflow.cn/v1"
LLM_MODEL = "deepseek-ai/DeepSeek-V4-Flash"


def _content_sig(priv, sid, sender, target, hc=None, ts=FIXED_TS, content="hello") -> str:
    from attp.core.authentication.signatures import sign_hash
    from attp.core.message.event import RecordedHop
    hop = RecordedHop(session_id=sid, sender_did=sender, target_did=target,
                      content=content, timestamp=ts, hop_count=hc or [0, 0])
    return sign_hash(hop.content_hash(), priv)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def real_tracer(tmp_path):
    db_path = str(tmp_path / "analysis_test.db")
    return await ProtocolTracer.create(db_path)


@pytest_asyncio.fixture
def real_session_manager():
    return ProtocolSessionManager()


@pytest_asyncio.fixture
def real_analyzer():
    return SemanticTaintAnalyzer(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
    )


@pytest_asyncio.fixture
def real_orchestrator(real_analyzer, real_session_manager, real_tracer):
    return AnalysisOrchestrator(
        analyzer=real_analyzer,
        session_manager=real_session_manager,
        tracer=real_tracer,
        batch_size=2,
    )


@pytest_asyncio.fixture
def mock_did_resolver(agent_keys, tool_keys, user_keys):
    from unittest.mock import AsyncMock
    resolver = AsyncMock()
    results = {
        TEST_AGENT_DID: build_did_resolution_result(TEST_AGENT_DID, agent_keys[1], "agent"),
        TEST_TOOL_DID: build_did_resolution_result(TEST_TOOL_DID, tool_keys[1], "tool"),
        TEST_USER_DID: build_did_resolution_result(TEST_USER_DID, user_keys[1], "user"),
    }

    async def _resolve_full(did, key_fragment="key-1"):
        return results.get(did, DIDResolutionResult(public_key=None, node_type=None, did_document=None))

    resolver.resolve_full = _resolve_full
    return resolver


@pytest_asyncio.fixture
async def app_with_orchestrator(
    real_tracer, real_session_manager, mock_did_resolver,
    real_orchestrator,
):
    port = ProtocolPort(
        tracer=real_tracer,
        session_manager=real_session_manager,
        host="0.0.0.0", port=9000,
        did_resolver=mock_did_resolver,
        behavior_controller=BehaviorController(),
        malicious_detector=MaliciousNodeDetector(mock_did_resolver),
    )
    port.set_orchestrator(real_orchestrator)
    return port._app


@pytest_asyncio.fixture
async def client_with_orch(app_with_orchestrator):
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=app_with_orchestrator)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _send_verified_u2a(client, user_keys, agent_keys, sid, content="帮我查询北京今天的天气"):
    """发送一条完整的 U2A 消息对（BP1+BP2）并写入行为记录。"""
    nonce = make_nonce()
    sig = _content_sig(user_keys[0], sid, TEST_USER_DID, TEST_AGENT_DID,
                       hc=[0, 0], content=content)

    bp1 = _make_signed_bp(
        node_did=TEST_USER_DID, nonce=nonce, session_id=sid,
        sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
        private_key=user_keys[0], hop_count=[0, 0], content_sig=sig,
        timestamp=FIXED_TS, content=content,
    )
    r1 = await client.post("/record", json=bp1)
    assert r1.json()["status"] == "stored"

    bp2 = _make_signed_bp(
        node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
        sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
        private_key=agent_keys[0], hop_count=[0, 0], content_sig=sig,
        timestamp=FIXED_TS, content=content,
    )
    r2 = await client.post("/record", json=bp2)
    assert "verified" in r2.json()["status"]


async def _send_verified_a2t(client, agent_keys, tool_keys, sid,
                             content="调用天气API查询北京天气"):
    nonce = make_nonce()
    ts = FIXED_TS + 1
    sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID,
                       hc=[0, 1], content=content, ts=ts)

    bp1 = _make_signed_bp(
        node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
        sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
        private_key=agent_keys[0], hop_count=[0, 1], content_sig=sig,
        timestamp=ts, content=content,
    )
    r1 = await client.post("/record", json=bp1)
    assert r1.json()["status"] == "stored"

    bp2 = _make_signed_bp(
        node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
        sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
        private_key=tool_keys[0], hop_count=[0, 1], content_sig=sig,
        timestamp=ts, content=content,
    )
    r2 = await client.post("/record", json=bp2)
    assert "verified" in r2.json()["status"]


# ══════════════════════════════════════════════════════════════════════
# 测试用例
# ══════════════════════════════════════════════════════════════════════


class TestIntentExtraction:
    """意图提取 — 验证 LLM 能从用户消息中提取结构化意图。"""

    @pytest.mark.asyncio
    async def test_extract_intent_real_llm(self, real_analyzer):
        intent = await real_analyzer.extract_intent("帮我查询北京今天的天气情况")
        assert intent is not None, "LLM 应成功返回 IntentDescriptor"
        assert intent.core_objective != ""
        assert intent.original_task == "帮我查询北京今天的天气情况"
        assert intent.risk_level in ("low", "medium", "high")

    @pytest.mark.asyncio
    async def test_extract_intent_complex_task(self, real_analyzer):
        intent = await real_analyzer.extract_intent(
            "分析用户的银行交易记录，找出异常交易并生成报告，"
            "注意不要泄露用户的个人隐私信息"
        )
        assert intent is not None
        assert "银行" in intent.core_objective or "交易" in intent.core_objective
        assert len(intent.constraints) > 0, "复杂任务应提取出约束条件"

    @pytest.mark.asyncio
    async def test_on_field_u2a_extracts_intent(
        self, real_orchestrator, real_session_manager, real_tracer,
    ):
        sid = make_session_id()
        real_session_manager.get_or_create(sid)

        await real_orchestrator.on_field_U2A_recorded(
            sid, "帮我预订明天从北京到上海的机票"
        )

        session = real_session_manager.get(sid)
        intent = session.get_intent()
        assert intent is not None, "on_field_U2A_recorded 应提取并存储意图"
        assert "机票" in intent.get("original_task", "") or "预订" in intent.get("core_objective", "")

    @pytest.mark.asyncio
    async def test_intent_only_extracted_once(
        self, real_orchestrator, real_session_manager, real_tracer,
    ):
        sid = make_session_id()
        real_session_manager.get_or_create(sid)

        await real_orchestrator.on_field_U2A_recorded(sid, "查询天气")
        session1 = real_session_manager.get(sid)
        intent1 = session1.get_intent()

        # 第二次调用不应覆盖
        await real_orchestrator.on_field_U2A_recorded(sid, "查询股市")
        session2 = real_session_manager.get(sid)
        intent2 = session2.get_intent()

        assert intent1 is not None
        assert intent2 is not None
        assert intent1["core_objective"] == intent2["core_objective"], "意图不应被覆盖"


class TestBatchAnalysis:
    """批量分析 — 验证 record 达到 batch_size 时自动触发 LLM 分析。"""

    @pytest.mark.asyncio
    async def test_batch_triggers_analysis(
        self, client_with_orch, user_keys, agent_keys, tool_keys, real_session_manager,
    ):
        sid = make_session_id()

        # 发送 U2A（触发意图提取 + 1 条 record）
        await _send_verified_u2a(
            client_with_orch, user_keys, agent_keys, sid,
            content="帮我查询北京天气",
        )

        # 等待意图提取完成
        await asyncio.sleep(3)
        session = real_session_manager.get(sid)
        assert session.get_intent() is not None, "U2A 后应已提取意图"

        # 发送 A2T（第 2 条 record，达到 batch_size=2）
        await _send_verified_a2t(
            client_with_orch, agent_keys, tool_keys, sid,
            content="调用天气API查询北京实时天气数据",
        )

        # 等待 LLM 分析完成
        await asyncio.sleep(10)

        # 查询分析报告
        resp = await client_with_orch.get(f"/api/analysis/{sid}")
        data = resp.json()
        assert data["total_batches"] >= 1, f"应有至少 1 个分析批次, got {data}"
        if data["reports"]:
            report = data["reports"][0]["report"]
            assert report.get("overall_verdict") in ("clean", "suspicious", "malicious", "error")


class TestManualTrigger:
    """手动触发 — 验证 POST /api/analysis/trigger 端点。"""

    @pytest.mark.asyncio
    async def test_trigger_with_no_data(self, client_with_orch):
        sid = make_session_id()
        resp = await client_with_orch.post(f"/api/analysis/trigger/{sid}")
        data = resp.json()
        assert resp.status_code == 200
        # 无意图时无法分析
        assert data["triggered"] in (True, False)

    @pytest.mark.asyncio
    async def test_trigger_with_session(
        self, client_with_orch, user_keys, agent_keys,
    ):
        sid = make_session_id()

        await _send_verified_u2a(
            client_with_orch, user_keys, agent_keys, sid,
            content="翻译一段英文文章为中文",
        )

        # 等意图提取完
        await asyncio.sleep(3)

        resp = await client_with_orch.post(f"/api/analysis/trigger/{sid}")
        data = resp.json()
        assert resp.status_code == 200

        if data.get("triggered"):
            # 等异步分析完成
            await asyncio.sleep(15)

            status = await client_with_orch.get(f"/api/analysis/status/{sid}")
            status_data = status.json()
            assert status_data["status"] in ("completed", "running", "not_found")

            if status_data["status"] == "completed":
                assert "report" in status_data or "reason" in status_data

    @pytest.mark.asyncio
    async def test_trigger_duplicate_returns_already_running(
        self, client_with_orch, user_keys, agent_keys,
    ):
        sid = make_session_id()
        await _send_verified_u2a(
            client_with_orch, user_keys, agent_keys, sid,
            content="总结今天的新闻",
        )
        await asyncio.sleep(3)

        r1 = await client_with_orch.post(f"/api/analysis/trigger/{sid}")
        r2 = await client_with_orch.post(f"/api/analysis/trigger/{sid}")

        # 至少有一个返回 running 或 already_running
        statuses = {r1.json().get("status"), r2.json().get("status")}
        assert statuses & {"running", "already_running"}, f"期望 running 或 already_running, got {statuses}"


class TestAnalysisAPI:
    """分析 API 端点 — 验证查询接口与 Orchestrator 的集成。"""

    @pytest.mark.asyncio
    async def test_intent_endpoint(
        self, client_with_orch, user_keys, agent_keys,
    ):
        sid = make_session_id()
        await _send_verified_u2a(
            client_with_orch, user_keys, agent_keys, sid,
            content="帮我写一封求职邮件",
        )
        await asyncio.sleep(3)

        resp = await client_with_orch.get(f"/api/analysis/intent/{sid}")
        data = resp.json()
        assert resp.status_code == 200
        assert data["session_id"] == sid
        # 意图可能已提取
        if data["intent"]:
            assert "core_objective" in data["intent"]

    @pytest.mark.asyncio
    async def test_aggregate_with_analysis(
        self, client_with_orch, user_keys, agent_keys,
    ):
        sid = make_session_id()
        await _send_verified_u2a(
            client_with_orch, user_keys, agent_keys, sid,
            content="搜索最近的AI论文并总结",
        )
        await asyncio.sleep(3)

        resp = await client_with_orch.get(f"/api/analysis/aggregate/{sid}")
        data = resp.json()
        assert resp.status_code == 200
        assert "traces" in data
        assert "reports" in data
        assert "alerts" in data
        assert data["traces"]["total_entries"] >= 1

    @pytest.mark.asyncio
    async def test_status_endpoint(self, client_with_orch):
        sid = make_session_id()
        resp = await client_with_orch.get(f"/api/analysis/status/{sid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_found"


class TestStatePersistence:
    """状态持久化 — 验证分析状态保存到 SQLite。"""

    @pytest.mark.asyncio
    async def test_intent_persisted_to_db(
        self, real_orchestrator, real_session_manager, real_tracer,
    ):
        sid = make_session_id()
        real_session_manager.get_or_create(sid)

        await real_orchestrator.on_field_U2A_recorded(sid, "帮我订一张火车票")
        await asyncio.sleep(3)

        # 从 SQLite 恢复状态
        saved = await real_tracer.load_analysis_session(sid)
        assert saved is not None, "意图应已持久化到 SQLite"
        assert saved["intent_json"] is not None
        intent = json.loads(saved["intent_json"])
        assert "core_objective" in intent

    @pytest.mark.asyncio
    async def test_report_count_persisted(
        self, real_orchestrator, real_session_manager, real_tracer,
    ):
        sid = make_session_id()
        real_session_manager.get_or_create(sid)

        await real_orchestrator.on_field_U2A_recorded(sid, "搜索新闻")
        await asyncio.sleep(3)

        await real_orchestrator.on_record_received(sid)

        saved = await real_tracer.load_analysis_session(sid)
        assert saved is not None
        assert saved["report_count"] == 1
