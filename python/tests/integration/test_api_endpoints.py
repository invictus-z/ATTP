"""API 查询端点集成测试。"""

import pytest

from attp.core.authentication.signatures import sign_hash
from attp.core.message.event import RecordedHop
from tests.integration.conftest import _make_signed_bp
from tests.fixtures.sample_data import (
    make_session_id, make_nonce,
    TEST_AGENT_DID, TEST_TOOL_DID, TEST_USER_DID,
)

FIXED_TS = 1000000.0


def _content_sig(priv, sid, sender, target, hc=None, ts=FIXED_TS, content="hello") -> str:
    hop = RecordedHop(session_id=sid, sender_did=sender, target_did=target,
                      content=content, timestamp=ts, hop_count=hc or [0, 0])
    return sign_hash(hop.content_hash(), priv)


class TestStatus:
    @pytest.mark.asyncio
    async def test_status_returns_ok(self, client):
        resp = await client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "protocol_node"


class TestBehavior:
    @pytest.mark.asyncio
    async def test_empty_session(self, client):
        resp = await client.get("/api/behavior/nonexistent-session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []

    @pytest.mark.asyncio
    async def test_with_traces(self, client, user_keys, agent_keys):
        nonce = make_nonce()
        sid = make_session_id()
        sig = _content_sig(user_keys[0], sid, TEST_USER_DID, TEST_AGENT_DID, hc=[0, 0])

        bp1 = _make_signed_bp(
            node_did=TEST_USER_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=user_keys[0], hop_count=[0, 0], content_sig=sig,
            timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp1)

        bp2 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=agent_keys[0], hop_count=[0, 0], content_sig=sig,
            timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp2)

        resp = await client.get(f"/api/behavior/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) >= 1


class TestAnalysis:
    @pytest.mark.asyncio
    async def test_no_reports(self, client):
        resp = await client.get("/api/analysis/nonexistent-session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reports"] == []

    @pytest.mark.asyncio
    async def test_aggregate_combines_data(self, client):
        resp = await client.get("/api/analysis/aggregate/nonexistent-session")
        assert resp.status_code == 200
        data = resp.json()
        assert "traces" in data
        assert "reports" in data
        assert "alerts" in data

    @pytest.mark.asyncio
    async def test_trigger_disabled(self, client):
        resp = await client.post("/api/analysis/trigger/some-session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["triggered"] is False

    @pytest.mark.asyncio
    async def test_analysis_status_not_found(self, client):
        resp = await client.get("/api/analysis/status/some-session")
        assert resp.status_code == 200


class TestMalicious:
    @pytest.mark.asyncio
    async def test_session_empty(self, client):
        resp = await client.get("/api/malicious/session/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_did_empty(self, client):
        resp = await client.get("/api/malicious/did/did:test:1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_dossier_not_found(self, client):
        resp = await client.get("/api/malicious/dossier/did:test:1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is False

    @pytest.mark.asyncio
    async def test_dossiers_all(self, client):
        resp = await client.get("/api/malicious/dossiers")
        assert resp.status_code == 200
        data = resp.json()
        assert "dossiers" in data

    @pytest.mark.asyncio
    async def test_dossier_with_malicious(self, client, agent_keys):
        nonce = make_nonce()
        sid = make_session_id()
        sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_AGENT_DID, hc=[0, 0])

        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_AGENT_DID,
            private_key=agent_keys[0], hop_count=[0, 0], content_sig=sig,
            timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp1)

        bp2 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_AGENT_DID,
            private_key=agent_keys[0], hop_count=[0, 0], content_sig=sig,
            timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp2)

        resp = await client.get(f"/api/malicious/session/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

        # 验证通过普通路径参数（FastAPI 自动 URL-decode）也能正确查询
        did_resp = await client.get(f"/api/malicious/did/{TEST_AGENT_DID}")
        assert did_resp.status_code == 200
        assert did_resp.json()["total"] >= 1

        dossier_resp = await client.get(f"/api/malicious/dossier/{TEST_AGENT_DID}")
        assert dossier_resp.status_code == 200
        assert dossier_resp.json()["found"] is True
        assert dossier_resp.json()["total_violations"] >= 1
