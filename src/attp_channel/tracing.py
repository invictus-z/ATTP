import json
import sqlite3
import hashlib
import time
from pathlib import Path
import base64
from cryptography.hazmat.primitives import hashes

from attp_channel.logging import get_logger
from cryptography.hazmat.primitives.asymmetric import padding, rsa, ec
from cryptography.hazmat.primitives import serialization

logger = get_logger("Tracing")

class MessageTracer:
    def __init__(self, db_path: str = "attp_traces.db"):
        self.db_path = Path.home() / ".nanobot" / db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_did TEXT,
                    target_did TEXT,
                    entry_hash TEXT,
                    prev_hash TEXT,
                    session_id TEXT,
                    hop_count INTEGER,
                    content_snapshot TEXT,
                    signature TEXT,
                    timestamp REAL
                )
            ''')
            conn.commit()

    def _load_private_key(self, key_path: str):
        pth = Path(key_path).expanduser().resolve()
        if not pth.exists():
            raise FileNotFoundError(f"Private key not found at {pth}")
        with open(pth, "rb") as key_file:
            return serialization.load_pem_private_key(key_file.read(), password=None)

    def _sign_hash(self, entry_hash: str, private_key) -> str:
        if isinstance(private_key, rsa.RSAPrivateKey):
            signature = private_key.sign(
                entry_hash.encode('utf-8'),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256()
            )
        elif isinstance(private_key, ec.EllipticCurvePrivateKey):
            signature = private_key.sign(
                entry_hash.encode('utf-8'),
                ec.ECDSA(hashes.SHA256())
            )
        else:
            return ""
        return base64.b64encode(signature).decode('utf-8')

    def _calculate_entry_hash(self, prev_hash: str, log_data: dict) -> str:
        raw_data = json.dumps({
            "prev_hash": prev_hash,
            "session_id": log_data.get("session_id"),
            "hop_count": log_data.get("hop_count"),
            "content_snapshot": log_data.get("content_snapshot"),
            "timestamp": log_data.get("timestamp"),
            "node_did": log_data.get("node_did")
        }, sort_keys=True)
        return hashlib.sha256(raw_data.encode('utf-8')).hexdigest()

    def _save_to_db(self, node_did: str, target_did: str, entry_hash: str, prev_hash: str,
                    session_id: str, hop_count: int, content_snapshot: str, signature: str, timestamp: float) -> None:
        """将日志条目存入数据库（统一的私有方法）"""
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute('''
                INSERT INTO traces (node_did, target_did, entry_hash, prev_hash, session_id, hop_count, content_snapshot, signature, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (node_did, target_did, entry_hash, prev_hash, session_id, hop_count, content_snapshot, signature, timestamp))
            conn.commit()

    def append_hop(self, metadata: dict, content_snapshot: str, node_did: str, target_did: str, private_key_path: str, save_to_db: bool = True) -> dict:
        metadata = metadata.copy() 
        session_id = metadata.get("Session_ID")
        if not session_id or session_id == "UNKNOWN_SESSION":
            session_id = f"session_{int(time.time()*1000)}"
        path = metadata.get("Path", [])

        hop_count = len(path)
        prev_hash = path[-1]["Log"]["Entry_Hash"] if hop_count > 0 else "Genesis"
        timestamp = time.time()

        snapshot = content_snapshot[:100] if content_snapshot else ""

        log_data = {
            "session_id": session_id,
            "hop_count": hop_count,
            "content_snapshot": snapshot,
            "timestamp": timestamp,
            "node_did": node_did
        }

        entry_hash = self._calculate_entry_hash(prev_hash, log_data)

        private_key = self._load_private_key(private_key_path)
        signature = self._sign_hash(entry_hash, private_key)

        log_entry = {
            "node_did": node_did,
            "target_did": target_did,
            "Entry_Hash": entry_hash,
            "Prev_Hash": prev_hash,
            "Session_ID": session_id,
            "Hop_Count": hop_count,
            "Content_Snapshot": snapshot,
            "Signature": signature,
            "Timestamp": timestamp
        }

        if save_to_db:
            self._save_to_db(node_did, target_did, entry_hash, prev_hash, session_id, hop_count, snapshot, signature, timestamp)

        metadata["Session_ID"] = session_id

        new_path = list(path)
        new_path.append({"Log": log_entry})
        metadata["Path"] = new_path
        return metadata

    def validate_chain(self, metadata: dict) -> bool:
        path = metadata.get("Path", [])
        if not path:
            return True
        
        if time.time() - path[-1]["Log"]["Timestamp"] > 300:
            logger.error("Security Alert: Message TTL expired.")
            return False
            
        for i in range(1, len(path)):
            prev_log = path[i-1]["Log"]
            curr_log = path[i]["Log"]
            
            if curr_log.get("Prev_Hash") != prev_log.get("Entry_Hash"):
                logger.error("Security Alert: Broken chain between {} and {}", prev_log.get("node_did"), curr_log.get("node_did"))
                return False
                
            recomputed = self._calculate_entry_hash(curr_log.get("Prev_Hash"), {
                "session_id": curr_log.get("Session_ID"),
                "hop_count": curr_log.get("Hop_Count"),
                "content_snapshot": curr_log.get("Content_Snapshot"),
                "timestamp": curr_log.get("Timestamp"),
                "node_did": curr_log.get("node_did")
            })
            if recomputed != curr_log.get("Entry_Hash"):
                logger.error("Security Alert: Hash manipulation detected at node {}", curr_log.get("node_did"))
                return False
        return True

    def recover_trace(self, session_id: str) -> list:
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM traces WHERE session_id = ? ORDER BY hop_count DESC", (session_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_origin_did(self, metadata: dict) -> str | None:
        """获取metadata中Path的第一个节点DID（消息最初发出者）"""
        path = metadata.get("Path", [])
        if path:
            return path[0]["Log"].get("node_did")
        return None

    def save_log_to_db(self, log_entry: dict) -> bool:
        """将单个log条目存入数据库（用于record类型消息）

        Args:
            log_entry: 包含日志信息的字典，格式为:
                {
                    "node_did": str,
                    "target_did": str,
                    "Entry_Hash": str,
                    "Prev_Hash": str,
                    "Session_ID": str,
                    "Hop_Count": int,
                    "Content_Snapshot": str,
                    "Signature": str,
                    "Timestamp": float
                }

        Returns:
            bool: 存储成功返回True，失败返回False
        """
        try:
            self._save_to_db(
                node_did=log_entry.get("node_did"),
                target_did=log_entry.get("target_did"),
                entry_hash=log_entry.get("Entry_Hash"),
                prev_hash=log_entry.get("Prev_Hash"),
                session_id=log_entry.get("Session_ID"),
                hop_count=log_entry.get("Hop_Count"),
                content_snapshot=log_entry.get("Content_Snapshot"),
                signature=log_entry.get("Signature"),
                timestamp=log_entry.get("Timestamp")
            )
            logger.info("Saved log to db: {} -> {}", log_entry.get("node_did"), log_entry.get("target_did"))
            return True
        except Exception as e:
            logger.error("Failed to save log to db: {}", e)
            return False

tracer = MessageTracer()
