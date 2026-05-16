"""BackMessage 发送工具函数 — 统一所有回传逻辑。"""

from __future__ import annotations

import aiohttp
from attp.app.logging import get_logger
from attp.core.message.event import BackMessage, RecordedHop

logger = get_logger("BackSender")


async def send_back_message(
    protocol_url: str,
    node_did: str,
    nonce: str,
    recorded_hop: RecordedHop,
    private_key,
    timeout: float = 10.0,
) -> bool:
    """构造并签名 BackMessage，发送到协议节点 /record 端点。

    Args:
        protocol_url: 协议节点地址。
        node_did: 回传节点的 DID。
        nonce: 消息唯一标识。
        recorded_hop: 单跳记录。
        private_key: 已加载的私钥对象。
        timeout: HTTP 请求超时（秒）。

    Returns:
        True 发送成功，False 发送失败。
    """
    if not protocol_url or not private_key:
        return False

    try:
        back_msg = BackMessage(
            protocol_url=protocol_url,
            node_did=node_did,
            nonce=nonce,
            sig_identity="",
            recorded_hop=recorded_hop,
        )
        back_msg.sign_identity(private_key)

        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"{protocol_url}/record",
                json=back_msg.to_dict(),
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status == 200:
                    logger.debug("BackMessage sent to {}", protocol_url)
                    return True
                else:
                    logger.warning(
                        "BackMessage rejected by {}: HTTP {}",
                        protocol_url, resp.status,
                    )
                    return False
    except Exception as e:
        logger.warning("Failed to send BackMessage to {}: {}", protocol_url, e)
        return False