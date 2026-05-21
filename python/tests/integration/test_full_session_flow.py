"""端到端多跳会话 + 恶意检测集成测试。"""

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


class TestMultiHopSession:
    @pytest.mark.asyncio
    async def test_full_u2a_a2t_flow(self, client, user_keys, agent_keys, tool_keys):
        sid = make_session_id()

        # Hop 1: U2A [0,0] - User sends to Agent
        n1 = make_nonce()
        sig1 = _content_sig(user_keys[0], sid, TEST_USER_DID, TEST_AGENT_DID, hc=[0, 0])

        bp1 = _make_signed_bp(
            node_did=TEST_USER_DID, nonce=n1, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=user_keys[0], hop_count=[0, 0], content_sig=sig1,
            timestamp=FIXED_TS,
        )
        r1 = await client.post("/record", json=bp1)
        assert r1.json()["status"] == "stored"

        bp2 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=n1, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=agent_keys[0], hop_count=[0, 0], content_sig=sig1,
            timestamp=FIXED_TS,
        )
        r2 = await client.post("/record", json=bp2)
        assert "verified" in r2.json()["status"]

        # Hop 2: A2T [0,1] - Agent sends to Tool
        n2 = make_nonce()
        ts2 = FIXED_TS + 1
        sig2 = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID, hc=[0, 1], ts=ts2)

        bp3 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=n2, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=[0, 1], content_sig=sig2,
            timestamp=ts2,
        )
        r3 = await client.post("/record", json=bp3)
        assert r3.json()["status"] == "stored"

        bp4 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=n2, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=[0, 1], content_sig=sig2,
            timestamp=ts2,
        )
        r4 = await client.post("/record", json=bp4)
        assert "verified" in r4.json()["status"]

        resp = await client.get(f"/api/behavior/{sid}")
        data = resp.json()
        assert len(data["nodes"]) >= 2

    @pytest.mark.asyncio
    async def test_behavior_trace_ordering(self, client, user_keys, agent_keys):
        sid = make_session_id()
        n1 = make_nonce()
        sig1 = _content_sig(user_keys[0], sid, TEST_USER_DID, TEST_AGENT_DID, hc=[0, 0])

        bp1 = _make_signed_bp(
            node_did=TEST_USER_DID, nonce=n1, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=user_keys[0], hop_count=[0, 0], content_sig=sig1,
            timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp1)

        bp2 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=n1, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=agent_keys[0], hop_count=[0, 0], content_sig=sig1,
            timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp2)

        resp = await client.get(f"/api/behavior/{sid}")
        data = resp.json()
        nodes = data["nodes"]
        assert len(nodes) >= 1
        for node in nodes:
            assert "hop_count" in node


class TestMaliciousDetectionE2E:
    @pytest.mark.asyncio
    async def test_identity_tampering_e2e(self, client, agent_keys, p256_keys):
        nonce = make_nonce()
        sid = make_session_id()

        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_TOOL_DID,
            private_key=p256_keys[0], hop_count=[0, 1], timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp1)

        bp2 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=[0, 1], timestamp=FIXED_TS,
        )
        r2 = await client.post("/record", json=bp2)
        assert r2.status_code == 403

    @pytest.mark.asyncio
    async def test_same_did_e2e(self, client, agent_keys):
        nonce = make_nonce()
        sid = make_session_id()
        sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID, hc=[0, 1])

        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=[0, 1], content_sig=sig,
            timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp1)

        bp2 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=[0, 1], content_sig=sig,
            timestamp=FIXED_TS,
        )
        r2 = await client.post("/record", json=bp2)
        assert r2.status_code == 403
        assert r2.json().get("evidence_type") == "same_did_duplicate"

    @pytest.mark.asyncio
    async def test_severity_escalation(self, client, agent_keys):
        did = TEST_AGENT_DID

        for i in range(4):
            nonce = make_nonce()
            sid = make_session_id()
            sig = _content_sig(agent_keys[0], sid, did, did, hc=[0, 0])
            bp1 = _make_signed_bp(
                node_did=did, nonce=nonce, session_id=sid,
                sender_did=did, target_did=did,
                private_key=agent_keys[0], hop_count=[0, 0], content_sig=sig,
                timestamp=FIXED_TS + i,
            )
            await client.post("/record", json=bp1)
            bp2 = _make_signed_bp(
                node_did=did, nonce=nonce, session_id=sid,
                sender_did=did, target_did=did,
                private_key=agent_keys[0], hop_count=[0, 0], content_sig=sig,
                timestamp=FIXED_TS + i,
            )
            await client.post("/record", json=bp2)

        dossier = await client.get(f"/api/malicious/dossier/{did}")
        data = dossier.json()
        assert data["found"] is True
        assert data["total_violations"] >= 4
        assert data["severity_level"] in ("dangerous", "banned")
