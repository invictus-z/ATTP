/**
 * 出站路由 —— Plan 4 三端口改造版（原 Plan 3, Task 3 的演进）。
 *
 * openclaw agent 的回复（delivery.deliver / outbound.attachedResults.sendText）
 * 全程 in-process，按目标前缀分流到对应出站链路：
 *
 *   - `attp:<sid>`  → 构造 A2U NodeMessage（发送方私钥签名）+ hub.broadcast
 *                     （推给订阅该 session 的浏览器 WS）；best-effort 触发 Phase-1
 *                     反向传播（失败只记日志，不阻断广播）。
 *   - `did:...`     → didToAdUrl(did) → discoverAgent 拉对端 ad.json/OpenRPC
 *                     → sendMessage（DID-wba 签名 JSON-RPC POST 到 receive_message）。
 *                     不再依赖入站时的 rpcUrl 缓存——A2A 回复路径现场发现。
 *
 * 旧版（gateway-routes 时代）的 cachePeerRpcUrl / getPeerRpcUrl /
 * extractReceiveRpcUrlFromDidDoc 一并移除：A2A 接收已由 attp-server.ts 的
 * POST /receive 托管，回复路径现场 rediscover 即可。
 */

import { randomUUID } from "node:crypto";
import { runtime } from "./runtime.js";
import { NodeMessage, RecordedHop } from "../../../core/message/event.js";
import { nodeMessageFrame } from "../../../app/web.js";
import { sendMessage, discoverAgent } from "../../../app/client.js";
import { sendBackMessage } from "../../../core/message/back-sender.js";

/**
 * 出站路由：`attp:<sid>` → A2U NodeMessage + hub.broadcast；`did:...` → A2A
 * discoverAgent + sendMessage。其它前缀原样占位返回。
 *
 * 返回 { messageId } —— A2U 分支用 sid 作为占位 messageId（广播无单条回执）；
 * A2A 分支用目标 DID 作为占位。
 */
export async function deliverOutbound(
  to: string,
  text: string,
): Promise<{ messageId: string }> {
  // A2U：用 session 溯源轨迹续链（appendHop behavior_type=A2U），构造签名 NodeMessage
  //       推给本会话的浏览器 WS 订阅者。对齐 Python WebApp.send_message_to_user。
  if (to.startsWith("attp:")) {
    const sid = to.slice("attp:".length);
    const rt = runtime;
    if (!rt.hub || !rt.privateKey || !rt.agentConfig?.did || !rt.tracer) {
      console.warn(
        `[attp/outbound] A2U identity/hub/tracer not ready for ${to}; skipping broadcast`,
      );
      return { messageId: sid };
    }
    // 取 session 轨迹（U2A 入站时存）：用其 protocol_url + 上一跳 sender_did 续链
    const trace = rt.sessionTraces?.get(sid);
    const protocolUrl = trace?.protocolUrl ?? rt.agentConfig.protocolUrl ?? "";
    const userDid = trace?.recordedHop?.sender_did ?? "did:user";
    const prevMetadata = trace
      ? { recordedHop: RecordedHop.fromDict(trace.recordedHop), sessionId: sid }
      : { sessionId: sid };
    // appendHop 续链并签名（对齐 Python:216-223）；A2U → intra hop_count +1
    let newHop: RecordedHop;
    try {
      const m = await rt.tracer.appendHop(
        prevMetadata,
        text,
        rt.agentConfig.did,
        userDid,
        rt.privateKey,
        "A2U",
      );
      newHop = m.recordedHop!;
    } catch (e) {
      console.error(
        `[attp/outbound] A2U appendHop failed for sid=${sid}:`,
        (e as Error).message,
      );
      return { messageId: sid };
    }
    const nodeMsg = new NodeMessage({
      protocolUrl,
      nonce: randomUUID().replace(/-/g, ""),
      recordedHop: newHop,
    });
    // best-effort Phase-1 回传（时序与 Python 一致：先回传，再发送）
    if (protocolUrl) {
      try {
        await sendBackMessage({
          protocolUrl,
          nodeDid: rt.agentConfig.did,
          nonce: nodeMsg.nonce,
          recordedHop: newHop,
          privateKey: rt.privateKey,
        });
        console.log(`[attp/outbound] A2U back-prop OK -> ${protocolUrl}`);
      } catch (e) {
        console.warn(
          `[attp/outbound] A2U back-prop to ${protocolUrl} failed:`,
          (e as Error).message,
        );
      }
    }
    // 更新 session 轨迹为新的 A2U 跳（供下一轮续链）
    if (rt.sessionTraces) {
      rt.sessionTraces.set(sid, { protocolUrl, recordedHop: newHop.toDict() });
    }
    rt.hub.broadcast(sid, nodeMessageFrame(nodeMsg));
    console.log(
      `[attp/outbound] A2U delivered sid=${sid} hopCount=[${newHop.hopCount.join(",")}] target=${userDid}`,
    );
    return { messageId: sid };
  }

  // A2A 回复：发往远端 agent 的 receive_message（现场 rediscover rpcUrl）
  if (to.startsWith("did:")) {
    if (!runtime.didDocument || !runtime.privateKey || !runtime.agentConfig?.did) {
      console.warn(
        "[attp/outbound] runtime identity not ready (didDocument/privateKey/agentConfig); skipping A2A reply",
      );
      return { messageId: to };
    }
    // adUrl 优先级：nodeAds 预发现注册表 > DID best-effort 推导
    const adUrl = runtime.peerRegistry?.get(to) || didToAdUrl(to);
    if (!adUrl) {
      console.warn(
        `[attp/outbound] cannot derive ad.json URL from ${to}; skipping A2A reply`,
      );
      return { messageId: to };
    }
    try {
      const peer = await discoverAgent(adUrl);
      await sendMessage({
        rpcUrl: peer.rpcUrl,
        didDocument: runtime.didDocument,
        privateKey: runtime.privateKey,
        senderDid: runtime.agentConfig.did,
        targetDid: to,
        content: text,
        messageType: "agent_reply",
      });
    } catch (e) {
      // best-effort：回复投递失败不抛回 openclaw（避免污染 turn 流水线）
      console.error(
        `[attp/outbound] A2A reply to ${to} failed:`,
        (e as Error).message,
      );
    }
    return { messageId: to };
  }

  // 未知前缀：原样占位返回（不抛）
  return { messageId: to };
}

/**
 * 由 did:wba/web best-effort 推导对端 ad.json URL。
 *
 * 刻意与 attp/app/mcp-node.ts 的 didToAdUrl 同实现，避免 channel 层跨包反向
 * 依赖 app/mcp-node（mcp-node 是 host-agnostic 的服务节点，channel 是 openclaw
 * 专属适配）。两边任何一处升级请保持同步。
 *
 *   did:wba:host:p1:p2        → https://host/p1/p2/ad.json
 *   did:wba:host:p1:p2:e1_key → https://host/p1/p2/ad.json（剥离末尾 key id 段）
 *   did:wba:host              → https://host/.well-known/ad.json
 *   非 did:wba/web / 格式非法 → ""（调用方 best-effort 处理）
 */
export function didToAdUrl(did: string): string {
  const parts = String(did ?? "").split(":");
  if (parts.length < 3 || parts[0] !== "did") return "";
  const method = parts[1];
  if (method !== "wba" && method !== "web") return "";
  const domain = decodeURIComponent(parts[2]);
  const segs = parts.slice(3);
  // 剥离末尾连续的 did:wba key id 段（e1_/k1_ 前缀）
  while (segs.length > 0 && /^(e1_|k1_)/.test(segs[segs.length - 1])) {
    segs.pop();
  }
  const pathSegments = segs.map((s) => decodeURIComponent(s));
  const base = `https://${domain}`.replace(/\/+$/, "");
  if (pathSegments.length > 0) return `${base}/${pathSegments.join("/")}/ad.json`;
  return `${base}/.well-known/ad.json`;
}
