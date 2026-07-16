/**
 * 回传消息发送 — 将 BackMessage POST 到协议节点的 /record 端点。
 *
 * 从 python/attp/core/message/back_sender.py 翻译而来。
 * 任何失败（协议节点拒绝、非 200 状态、网络异常）统一抛出 BackPropagationError。
 */

import { BackMessage, RecordedHop } from "./event.js";
import type { AnyKey } from "../authentication/keys.js";

/**
 * 回传传播错误：协议节点拒绝、HTTP 非 200，或网络层失败时抛出。
 */
export class BackPropagationError extends Error {}

/**
 * sendBackMessage 参数。
 *
 * protocolUrl:  协议节点根地址（不含 /record）
 * nodeDid:      回传节点的 DID 身份
 * nonce:        唯一标识，用于匹配回传消息
 * recordedHop:  单跳记录内容
 * privateKey:   回传节点私钥（LoadedKey / AnyKey）
 * timeoutMs:    请求超时（毫秒），默认 10000
 */
export interface SendBackParams {
  protocolUrl: string;
  nodeDid: string;
  nonce: string;
  recordedHop: RecordedHop;
  privateKey: AnyKey;
  timeoutMs?: number;
}

/**
 * 将签名后的 BackMessage POST 到 {protocolUrl}/record。
 *
 * - 200 且响应体无 error / status 非 error|rejected → 成功
 * - 200 但响应体含 error / status 为 error|rejected → BackPropagationError
 * - 非 200 → BackPropagationError
 * - 网络异常 / 超时 → BackPropagationError
 */
export async function sendBackMessage(p: SendBackParams): Promise<void> {
  const back = new BackMessage({
    protocolUrl: p.protocolUrl,
    nodeDid: p.nodeDid,
    nonce: p.nonce,
    recordedHop: p.recordedHop,
  });
  await back.signIdentity(p.privateKey);

  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), p.timeoutMs ?? 10000);
  try {
    const resp = await fetch(`${p.protocolUrl}/record`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(back.toDict()),
      signal: ctrl.signal,
    });
    if (resp.status === 200) {
      const data = await resp.json().catch(() => ({} as Record<string, unknown>));
      const status = (data as Record<string, unknown>).status as string | undefined;
      if (data.error || status === "error" || status === "rejected") {
        throw new BackPropagationError(
          `Protocol node rejected - ${(data as Record<string, unknown>).error ?? "unknown"}`,
        );
      }
      return;
    }
    throw new BackPropagationError(`Protocol node returned HTTP ${resp.status}`);
  } catch (e) {
    if (e instanceof BackPropagationError) throw e;
    throw new BackPropagationError(
      `Failed to send back-propagation - ${(e as Error).message}`,
    );
  } finally {
    clearTimeout(t);
  }
}
