"""POST /record 集成测试 — 完整管道。"""

import pytest

from attp.core.authentication.signatures import sign_hash
from attp.core.message.event import RecordedHop
from tests.integration.conftest import _make_signed_bp
from tests.fixtures.sample_data import (
    make_session_id, make_nonce,
    TEST_AGENT_DID, TEST_TOOL_DID, TEST_USER_DID,
)

FIXED_TS = 1000000.0


def _content_sig(sender_priv, sid, sender, target, hc=None, ts=FIXED_TS, content="hello") -> str:
    hop = RecordedHop(session_id=sid, sender_did=sender, target_did=target,
                      content=content, timestamp=ts, hop_count=hc or [0, 0])
    return sign_hash(hop.content_hash(), sender_priv)


class TestRecordEndpoint:
    @pytest.mark.asyncio
    async def test_invalid_json_body(self, client):
        resp = await client.post("/record", content=b"not json")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_backmessage(self, client):
        resp = await client.post("/record", json={"bad": "data"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_branch_a_stored(self, client, user_keys):
        nonce = make_nonce()
        sid = make_session_id()
        body = _make_signed_bp(
            node_did=TEST_USER_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=user_keys[0], hop_count=[0, 0], timestamp=FIXED_TS,
        )
        resp = await client.post("/record", json=body)
        assert resp.status_code == 200
        assert resp.json()["status"] == "stored"

    @pytest.mark.asyncio
    async def test_branch_b_verified_u2a(self, client, user_keys, agent_keys):
        nonce = make_nonce()
        sid = make_session_id()
        sig = _content_sig(user_keys[0], sid, TEST_USER_DID, TEST_AGENT_DID, hc=[0, 0])

        bp1 = _make_signed_bp(
            node_did=TEST_USER_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=user_keys[0], hop_count=[0, 0], content_sig=sig,
            timestamp=FIXED_TS,
        )
        r1 = await client.post("/record", json=bp1)
        assert r1.json()["status"] == "stored"

        bp2 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=agent_keys[0], hop_count=[0, 0], content_sig=sig,
            timestamp=FIXED_TS,
        )
        r2 = await client.post("/record", json=bp2)
        assert r2.status_code == 200
        assert "verified" in r2.json()["status"]

    @pytest.mark.asyncio
    async def test_branch_b_verified_a2t(self, client, agent_keys, tool_keys):
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
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=[0, 1], content_sig=sig,
            timestamp=FIXED_TS,
        )
        r2 = await client.post("/record", json=bp2)
        assert r2.status_code == 200

    @pytest.mark.asyncio
    async def test_branch_b_same_did_malicious(self, client, agent_keys):
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
        assert "malicious_detected" == r2.json()["status"]

    @pytest.mark.asyncio
    async def test_did_resolution_fails(self, client, agent_keys):
        sid = make_session_id()
        nonce = make_nonce()

        body = _make_signed_bp(
            node_did="did:wba:unknown%3A9999:agent:bad",
            nonce=nonce, session_id=sid,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID,
            private_key=agent_keys[0],
        )
        resp = await client.post("/record", json=body)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_hop_zero_not_u2a(self, client, agent_keys, tool_keys):
        nonce = make_nonce()
        sid = make_session_id()
        sig = _content_sig(agent_keys[0], sid, TEST_AGENT_DID, TEST_TOOL_DID, hc=[0, 0])

        bp1 = _make_signed_bp(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=agent_keys[0], hop_count=[0, 0], content_sig=sig,
            timestamp=FIXED_TS,
        )
        await client.post("/record", json=bp1)

        bp2 = _make_signed_bp(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=sid,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID,
            private_key=tool_keys[0], hop_count=[0, 0], content_sig=sig,
            timestamp=FIXED_TS,
        )
        r2 = await client.post("/record", json=bp2)
        assert r2.status_code == 400
        assert "U2A" in r2.json()["error"]
