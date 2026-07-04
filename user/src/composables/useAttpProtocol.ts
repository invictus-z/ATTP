/**
 * useAttpProtocol — Vue Composable
 *
 * 管理 User 端 ATTP 身份、密钥加载、协议消息构造与收发。
 * 配置文件存储于 ~/.attp/user/config.json，通过 Electron IPC 读写。
 */

import { ref, reactive, computed } from 'vue'
import type { UserAttpConfig, LlmConfig } from '../transport'
import { importPrivateKeyFromPem, type SignableKey } from '../attp/key_helper'
import { buildNodeMessage, sendBackMessage, parseIncomingNodeMessage } from '../attp/protocol'
import { UserSessionManager } from '@attp/core'
import type { RecordedHop } from '@attp/core'

// ---- Singleton State ----

const userConfig = reactive<UserAttpConfig>({
  mode: null,
  did: '',
  didDocPath: '',
  didKeyPath: '',
  protocolNodes: [],
  toolNodes: [],
  agents: [],
})

/** 缓存的私钥（CryptoKey 或 Secp256k1PrivateKey） */
let cachedPrivateKey: SignableKey | null = null
let cachedKeyPath: string = ''

const initialized = ref(false)
const privateKeyLoaded = ref(false)
const loading = ref(false)
const saving = ref(false)

/** 尚未初始化（mode=null）→ 前端进入模式选择页 */
const needsInit = ref(false)
/** LLM 配置（持久于 app-state.llm，两模式共用；用于注入 docker compose） */
const llm = ref<LlmConfig>({ apiKey: '', baseUrl: 'https://api.deepseek.com', model: 'deepseek-chat' })
/** 当前是否为演示模式 */
const isDemoMode = computed(() => userConfig.mode === 'demo')

/** 演示模式下把宿主侧协议节点 url 改写为 docker 服务名，供容器内 agent 回传。
 *  仅替换 host（localhost/127.0.0.1 → protocol），保留端口与路径；
 *  非 localhost 的地址（如自由模式里用户配的远程地址）原样返回。
 *  user 节点自己访问协议节点仍用宿主侧 url（localhost），不受此改写影响。 */
function toDockerServiceUrl(url: string): string {
  return url.replace(/\/\/(localhost|127\.0\.0\.1)([:\/]|$)/, '//protocol$2')
}

// ---- Session Manager（基于 @attp/core UserSessionManager）----

/** ATTP 会话管理器单例，持久化到 localStorage */
const attpSessionManager = new UserSessionManager()

// 初始化时从 localStorage 恢复
attpSessionManager.loadFromStorage()

/** 绑定 session 的 protocol URL */
export function bindSessionProtocolUrl(sessionId: string, protocolUrl: string) {
  console.log(`[ATTP] bindSessionProtocolUrl: session=${sessionId} → protocol=${protocolUrl}`)
  const session = attpSessionManager.getOrCreate(sessionId)
  session.protocolNodeAddress = protocolUrl
  session.userDid = userConfig.did || undefined
  attpSessionManager.save(session)
  attpSessionManager.saveToStorage()
}

/** 获取 session 绑定的 protocol URL，仅返回 session 级别绑定 */
export function getSessionProtocolUrl(sessionId: string): string | null {
  const session = attpSessionManager.get(sessionId)
  return session?.protocolNodeAddress || null
}

/** 清除 session 的 protocol 绑定 */
export function clearSessionProtocolUrl(sessionId: string) {
  attpSessionManager.delete(sessionId)
  attpSessionManager.saveToStorage()
}

// ---- Config I/O（基于 app-state：mode + llm + 按模式分流的 userConfig）----

/** 把 read-app-state / set-app-mode 返回应用到内存 */
function applyState(result: {
  ok: boolean; mode?: 'demo' | 'free' | null;
  llm?: LlmConfig; userConfig?: UserAttpConfig | null; needsInit?: boolean;
}) {
  if (result.llm) llm.value = { ...llm.value, ...result.llm }
  if (result.userConfig) {
    if (cachedKeyPath !== result.userConfig.didKeyPath) {
      cachedPrivateKey = null
      privateKeyLoaded.value = false
    }
    Object.assign(userConfig, result.userConfig)
    initialized.value = true
    needsInit.value = false
  } else {
    initialized.value = false
    needsInit.value = !!result.needsInit
  }
}

/** 启动：读 app-state（mode + llm + 按模式分流的 userConfig） */
async function loadAppState(): Promise<boolean> {
  loading.value = true
  try {
    const result = await window.electronAPI.readAppState()
    if (!result.ok) { console.warn('[ATTP] readAppState failed:', result.error); return false }
    applyState(result)
    return !needsInit.value
  } catch (e) {
    console.error('[ATTP] loadAppState exception:', e)
    return false
  } finally {
    loading.value = false
  }
}

/** 设置模式：首启选择 + 演示↔自由双向切换统一入口；完成后重读 state */
async function setMode(mode: 'demo' | 'free'): Promise<boolean> {
  const result = await window.electronAPI.setAppMode(mode)
  if (!result.ok) { console.warn('[ATTP] setAppMode failed:', result.error); return false }
  applyState(result)
  return true
}

/** 保存 LLM 配置（持久于 app-state.llm，两模式共用） */
async function saveLlm(): Promise<boolean> {
  // 浅拷贝剥离 Vue reactive proxy（llm.value 是 Proxy，不可经 Electron IPC 结构化克隆，否则报 "An object could not be cloned"）
  const result = await window.electronAPI.saveLlm({ ...llm.value })
  if (!result.ok) { console.warn('[ATTP] saveLlm failed:', result.error); return false }
  if (result.data) llm.value = { ...llm.value, ...(result.data as LlmConfig) }
  return true
}

/** 保存配置到 ~/.attp/user/config.json */
async function saveUserConfig(): Promise<boolean> {
  saving.value = true
  try {
    // Deep-clone to strip Vue reactive proxies (not serializable through Electron IPC)
    const config: UserAttpConfig = JSON.parse(JSON.stringify({
      did: userConfig.did,
      didDocPath: userConfig.didDocPath,
      didKeyPath: userConfig.didKeyPath,
      protocolNodes: userConfig.protocolNodes,
      toolNodes: userConfig.toolNodes,
      agents: userConfig.agents,
    }))
    const result = await window.electronAPI.saveUserConfig(config)
    if (!result.ok) {
      console.warn('[ATTP] saveUserConfig failed:', result.error)
    }
    return result.ok
  } catch (e) {
    console.error('[ATTP] saveUserConfig error:', e)
    return false
  } finally {
    saving.value = false
  }
}

// ---- Key Management ----

/** 读取 PEM 私钥文件并导入为可签名密钥（带缓存） */
async function loadPrivateKey(): Promise<SignableKey | null> {
  if (!userConfig.didKeyPath) {
    console.warn('[ATTP] No private key path configured')
    return null
  }

  // 使用缓存
  if (cachedPrivateKey && cachedKeyPath === userConfig.didKeyPath) {
    return cachedPrivateKey
  }

  try {
    const fileResult = await window.electronAPI.readFile(userConfig.didKeyPath)
    if (!fileResult.ok || !fileResult.data) {
      console.warn('[ATTP] Failed to read private key file:', fileResult.error)
      return null
    }

    const privateKey = await importPrivateKeyFromPem(fileResult.data)
    cachedPrivateKey = privateKey
    cachedKeyPath = userConfig.didKeyPath
    privateKeyLoaded.value = true
    return privateKey
  } catch (e) {
    console.error('[ATTP] loadPrivateKey error:', e)
    return null
  }
}

// ---- ATTP Received Message Handling ----

/**
 * 处理收到的 NodeMessage（Agent → User 回复）。
 *
 * WS 消息现在直接是 NodeMessage dict，无需额外解析。
 * ATTP 回传流程：
 *   1. 从 NodeMessage 提取 nonce, protocolUrl, recordedHop
 *   2. 构造 BackMessage（userDid + nonce + recordedHop）
 *   3. 签名 identityHash(nodeDid, nonce) → sigIdentity
 *   4. HTTP POST 到 {protocolUrl}/record
 *
 * @param incomingData WS 收到的原始数据（直接是 NodeMessage dict）
 * @returns 是否成功解析 NodeMessage 并触发了回传
 */
async function handleReceivedNodeMessage(incomingData: any): Promise<boolean> {
  console.log('[ATTP] handleReceivedNodeMessage: 解析收到的 NodeMessage...')
  const nodeMessage = parseIncomingNodeMessage(incomingData)
  if (!nodeMessage) {
    console.log('[ATTP] handleReceivedNodeMessage: 解析 NodeMessage 失败，跳过')
    return false
  }

  console.log(`[ATTP] handleReceivedNodeMessage: 解析成功 ✓ protocolUrl=${nodeMessage.protocolUrl}, nonce=${nodeMessage.nonce}`)

  // 保存 Agent 回复中的 hop_count
  const session = attpSessionManager.getOrCreate(nodeMessage.recordedHop.sessionId)
  session.setHopCount(nodeMessage.recordedHop.hopCount)
  attpSessionManager.save(session)
  attpSessionManager.saveToStorage()

  if (!userConfig.did) {
    console.warn('[ATTP] handleReceivedNodeMessage: User DID 未配置，跳过回传')
    return false
  }

  const privateKey = await loadPrivateKey()
  if (!privateKey) {
    console.warn('[ATTP] handleReceivedNodeMessage: 私钥加载失败，跳过回传')
    return false
  }

  // 发送 BackMessage，等待协议节点确认收到。
  // 用 session 绑定的宿主侧 protocolUrl（演示模式下 agent 响应里回填的是 docker 服务名
  // protocol:9000，宿主解析不了）；自由模式下与 nodeMessage.protocolUrl 等价。
  const sessionProtocolUrl = getSessionProtocolUrl(nodeMessage.recordedHop.sessionId) || nodeMessage.protocolUrl
  const backOk = await sendBackMessage({
    protocolUrl: sessionProtocolUrl,
    userDid: userConfig.did,
    nonce: nodeMessage.nonce,
    recordedHop: nodeMessage.recordedHop,
    privateKey,
  })

  if (!backOk) {
    console.warn('[ATTP] BackMessage for received message failed — 协议节点未确认')
    return false
  }

  console.log('[ATTP] BackMessage for received message confirmed by protocol node')
  return true
}

// ---- ATTP Message Send ----

export interface SendMessageResult {
  success: boolean;
  nodeMessageDict?: Record<string, unknown>;
  error?: string;
}

/**
 * 完整的 ATTP U2A 发送流程：
 *   1. 加载私钥
 *   2. 构造 NodeMessage + 签名
 *   3. 先发送 BackMessage 到协议节点，等待确认
 *   4. 确认后返回 NodeMessage dict（由调用方通过 WS 发送给 Agent）
 *
 * 时序规则：先回传协议节点，再发给 Agent。
 */
async function sendMessageWithAttp(
  content: string,
  sessionId: string,
  targetDid: string,
): Promise<SendMessageResult> {
  console.log(`[ATTP] sendMessageWithAttp called: sessionId=${sessionId}, targetDid=${targetDid}, contentLen=${content.length}`)

  if (!userConfig.did) {
    console.error('[ATTP] sendMessageWithAttp FAILED: User DID 未配置')
    return { success: false, error: 'User DID 未配置 — 请先在 Settings 中配置 ATTP Identity' }
  }

  // 优先从 session 绑定取 protocolUrl，否则取全局配置
  const protocolUrl = getSessionProtocolUrl(sessionId)
  if (!protocolUrl) {
    console.error('[ATTP] sendMessageWithAttp FAILED: Protocol Node URL 未配置（无 session 绑定也无全局配置）')
    return { success: false, error: 'Protocol Node URL 未配置 — 请先在 Settings 中添加 Protocol Node，或在创建会话时绑定' }
  }

  const privateKey = await loadPrivateKey()
  if (!privateKey) {
    console.error('[ATTP] sendMessageWithAttp FAILED: 私钥加载失败')
    return { success: false, error: '私钥加载失败 — 请检查 DID Key Path 配置' }
  }

  // 1. 构造 NodeMessage + 签名
  //    塞进 NodeMessage 的 protocolUrl 是「容器内 agent 回传用的地址」：
  //    演示模式 → docker 服务名（agent 容器内可达，localhost 在容器里指它自己）；
  //    自由模式 → 原样透传用户配置的 url（通常为远程真实地址，host 与容器都可达）。
  //    注意：user 自己的 sendBack（step 2）仍用宿主侧 protocolUrl，与此处无关。
  const embeddedProtocolUrl = isDemoMode.value ? toDockerServiceUrl(protocolUrl) : protocolUrl

  let nodeMessageDict: Record<string, unknown>
  let nonce: string
  let recordedHop: RecordedHop

  try {
    const built = await buildNodeMessage({
      sessionId,
      userDid: userConfig.did,
      targetDid,
      content,
      protocolUrl: embeddedProtocolUrl,
      privateKey,
      sessionManager: attpSessionManager,  // 传递 sessionManager
    })
    nodeMessageDict = built.nodeMessage.toDict()
    nonce = built.nonce
    recordedHop = built.recordedHop
  } catch (e) {
    console.error('[ATTP] buildNodeMessage error:', e)
    return { success: false, error: `构建 NodeMessage 失败 - ${String(e)}` }
  }

  // ========== 时序规则：先回传协议节点，再发给 Agent ==========
  // 2. 回传：向协议节点发送 BackMessage，等待确认
  const backOk = await sendBackMessage({
    protocolUrl,
    userDid: userConfig.did,
    nonce,
    recordedHop,
    privateKey,
  })

  if (!backOk) {
    return { success: false, error: '协议节点未确认回传' }
  }

  // 3. 回传确认后，返回 NodeMessage dict 供调用方发送
  return { success: true, nodeMessageDict }
}

// ---- Agents Management ----

async function addAgent(name: string, baseUrl: string, did?: string): Promise<boolean> {
  const exists = userConfig.agents.some(a => a.baseUrl === baseUrl)
  if (exists) return false
  userConfig.agents.push({ name, baseUrl, did: did || '' })
  return saveUserConfig()
}

async function removeAgent(index: number): Promise<boolean> {
  if (index < 0 || index >= userConfig.agents.length) return false
  userConfig.agents.splice(index, 1)
  return saveUserConfig()
}

// ---- Protocol Node Management----

async function addProtocolNode(name: string, url: string): Promise<boolean> {
  const exists = userConfig.protocolNodes.some(n => n.url === url)
  if (exists) return false
  userConfig.protocolNodes.push({ name, url })
  return saveUserConfig()
}

async function updateProtocolNode(index: number, name: string, url: string): Promise<boolean> {
  if (index < 0 || index >= userConfig.protocolNodes.length) return false
  userConfig.protocolNodes[index] = { name, url }
  return saveUserConfig()
}

async function removeProtocolNode(index: number): Promise<boolean> {
  if (index < 0 || index >= userConfig.protocolNodes.length) return false
  userConfig.protocolNodes.splice(index, 1)
  return saveUserConfig()
}

async function saveProtocolNodes(nodes: { name: string; url: string }[]): Promise<boolean> {
  userConfig.protocolNodes = nodes.map(({ name, url }) => ({ name, url }))
  return saveUserConfig()
}

// ---- Tool Node Management（工具节点）----

async function saveToolNodes(nodes: { name: string; url: string }[]): Promise<boolean> {
  userConfig.toolNodes = nodes.map(({ name, url }) => ({ name, url }))
  return saveUserConfig()
}

// ---- Composable ----

export function useAttpProtocol() {
  return {
    // State
    userConfig,
    initialized,
    privateKeyLoaded,
    loading,
    saving,
    needsInit,
    isDemoMode,
    llm,

    // Config I/O（app-state）
    loadAppState,
    saveUserConfig,
    setMode,
    saveLlm,

    // Key Management
    loadPrivateKey,

    // ATTP Messaging
    sendMessageWithAttp,
    handleReceivedNodeMessage,
    parseIncomingNodeMessage,

    // Agents Management
    addAgent,
    removeAgent,

    // Protocol Node Management
    addProtocolNode,
    updateProtocolNode,
    removeProtocolNode,
    saveProtocolNodes,

    // Tool Node Management（工具节点）
    saveToolNodes,
  }
}
