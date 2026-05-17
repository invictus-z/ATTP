"""BackMessage 发送工具函数 — 统一所有回传逻辑。"""

from __future__ import annotations

import aiohttp
from attp.app.logging import get_logger
from attp.core.message.event import BackMessage, RecordedHop

logger = get_logger("BackSender")


class BackPropagationError(Exception):
    """回传协议节点失败时抛出。"""


async def send_back_message(
    protocol_url: str,
    node_did: str,
    nonce: str,
    recorded_hop: RecordedHop,
    private_key,
    timeout: float = 10.0,
) -> None:
    """构造并签名 BackMessage，发送到协议节点 /record 端点。

    Args:
        protocol_url: 协议节点地址。
        node_did: 回传节点的 DID。
        nonce: 消息唯一标识。
        recorded_hop: 单跳记录。
        private_key: 已加载的私钥对象。
        timeout: HTTP 请求超时（秒）。

    Raises:
        BackPropagationError: 回传失败（协议节点拒绝、HTTP 错误、网络异常）。
    """
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
                    resp_data = await resp.json()
                    if resp_data.get("status") not in ("stored", "ok"):
                        logger.warning(
                            "Protocol node rejected back-propagation: {}",
                            resp_data,
                        )
                        raise BackPropagationError(
                            f"Protocol node rejected - {resp_data.get('error', 'unknown')}"
                        )
                    logger.debug("Back-propagation confirmed by protocol node")
                else:
                    logger.warning("Protocol node returned HTTP {}", resp.status)
                    raise BackPropagationError(
                        f"Protocol node returned HTTP {resp.status}"
                    )
    except BackPropagationError:
        raise
    except Exception as e:
        logger.warning("Failed to send back-propagation to protocol node: {}", e)
        raise BackPropagationError(f"Failed to send back-propagation - {e}") from e
