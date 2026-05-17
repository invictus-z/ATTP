/**
 * useAttpProtocol — Vue Composable
 *
 * 管理 User 端 ATTP 身份、密钥加载、协议消息构造与收发。
 * 配置文件存储于 ~/.attp/user/config.json，通过 Electron IPC 读写。
 */

import { ref, reactive } from 'vue'
import type { UserAttpConfig } from '../transport'
import { importPrivateKeyFromPem, type SignableKey } from '../attp/key_helper'
import { buildNodeMessage, sendBackMessage, parseIncomingNodeMessage } from '../attp/protocol'
import { UserSessionManager } from '@attp/core'
import type { RecordedHop } from '@attp/core'

// ---- Singleton State ----

const userConfig = reactive<UserAttpConfig>({
  did: '',
  didDocPath: '',
  didKeyPath: '',
  protocolNodes: [],
  agents: [],
})

/** 缓存的私钥（CryptoKey 或 Secp256k1PrivateKey） */
let cachedPrivateKey: SignableKey | null = null
let cachedKeyPath: string = ''

const initialized = ref(false)
const privateKeyLoaded = ref(false)
const loading = ref(false)
const saving = ref(false)

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

/** 获取 session 绑定的 protocol URL，若无则 fallback 到全局配置的第一个 */
export function getSessionProtocolUrl(sessionId: string): string | null {
  const session = attpSessionManager.get(sessionId)
  if (session?.protocolNodeAddress) return session.protocolNodeAddress
  return userConfig.protocolNodes.length > 0 ? userConfig.protocolNodes[0].url : null
}

/** 清除 session 的 protocol 绑定 */
export function clearSessionProtocolUrl(sessionId: string) {
  attpSessionManager.delete(sessionId)
  attpSessionManager.saveToStorage()
}

// ---- Config I/O ----

/** 从 ~/.attp/user/config.json 加载配置 */
async function loadUserConfig(): Promise<boolean> {
  loading.value = true
  console.log('[DEBUG-CONN][loadUserConfig] Loading user config from ~/.attp/user/config.json...')
  try {
    const result = await window.electronAPI.readUserConfig()
    if (result.ok && result.data) {
      Object.assign(userConfig, result.data)
      initialized.value = true

      console.log(`[DEBUG-CONN][loadUserConfig] ✓ Config loaded: did="${userConfig.did}", didKeyPath="${userConfig.didKeyPath}"`)
      console.log(`[DEBUG-CONN][loadUserConfig]   protocolNodes (${userConfig.protocolNodes.length}):`, userConfig.protocolNodes.map(n => `"${n.name}"=${n.url}`))
      console.log(`[DEBUG-CONN][loadUserConfig]   agents (${userConfig.agents.length}):`, userConfig.agents.map(a => `"${a.name}"=${a.baseUrl}`))

      // 如果密钥路径变了，清除缓存的私钥
      if (cachedKeyPath !== userConfig.didKeyPath) {
        cachedPrivateKey = null
        privateKeyLoaded.value = false
        console.log('[DEBUG-CONN][loadUserConfig]   Key path changed — cleared cached private key')
      }

      return true
    } else {
      console.warn(`[DEBUG-CONN][loadUserConfig] ✗ Failed: ${result.error || 'no data'}`)
      return false
    }
  } catch (e) {
    console.error('[DEBUG-CONN][loadUserConfig] !!! Exception:', e)
    return false
  } finally {
    loading.value = false
  }
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
 * 处理收到的包含 NodeMessage 的 Agent 响应。
 *
 * 收到 Agent 消息时的 ATTP 回传流程：
 *   1. 解析 Agent 返回的 NodeMessage（含 nonce, protocolUrl, recordedHop）
 *   2. 构造 BackMessage（userDid + nonce + recordedHop）
 *   3. 签名 identityHash(nodeDid, nonce) → sigIdentity
 *   4. HTTP POST 到 {protocolUrl}/record
 *
 * @param incomingData WS 收到的原始数据（可能含 NodeMessage 字段）
 * @returns 是否检测到 NodeMessage 并触发了回传
 */
async function handleReceivedNodeMessage(incomingData: any): Promise<boolean> {
  console.log('[ATTP] handleReceivedNodeMessage: 收到 WS 消息，检测 NodeMessage...')
  const nodeMessage = parseIncomingNodeMessage(incomingData)
  if (!nodeMessage) {
    console.log('[ATTP] handleReceivedNodeMessage: 未检测到 NodeMessage，跳过（非 ATTP 消息或 Agent 未包裹）')
    return false
  }

  console.log(`[ATTP] handleReceivedNodeMessage: 检测到 NodeMessage ✓ protocolUrl=${nodeMessage.protocolUrl}, nonce=${nodeMessage.nonce}`)

  if (!userConfig.did) {
    console.warn('[ATTP] handleReceivedNodeMessage: User DID 未配置，跳过回传')
    return false
  }

  const privateKey = await loadPrivateKey()
  if (!privateKey) {
    console.warn('[ATTP] handleReceivedNodeMessage: 私钥加载失败，跳过回传')
    return false
  }

  // 异步发送 BackMessage（不阻塞 UI / 消息渲染）
  sendBackMessage({
    protocolUrl: nodeMessage.protocolUrl,
    userDid: userConfig.did,
    nonce: nodeMessage.nonce,
    recordedHop: nodeMessage.recordedHop,
    privateKey,
  }).then(ok => {
    if (ok) console.log('[ATTP] BackMessage for received message sent successfully')
    else console.warn('[ATTP] BackMessage for received message failed')
  }).catch(e => {
    console.warn('[ATTP] BackMessage for received message error:', e)
  })

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
  let nodeMessageDict: Record<string, unknown>
  let nonce: string
  let recordedHop: RecordedHop

  try {
    const built = await buildNodeMessage({
      sessionId,
      userDid: userConfig.did,
      targetDid,
      content,
      protocolUrl,
      privateKey,
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

// ---- Protocol Node Management（协议节点 = 溯源节点）----

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

// ---- Composable ----

export function useAttpProtocol() {
  return {
    // State
    userConfig,
    initialized,
    privateKeyLoaded,
    loading,
    saving,

    // Config I/O
    loadUserConfig,
    saveUserConfig,

    // Key Management
    loadPrivateKey,

    // ATTP Messaging
    sendMessageWithAttp,
    handleReceivedNodeMessage,
    parseIncomingNodeMessage,

    // Agents Management
    addAgent,
    removeAgent,

    // Protocol Node Management（协议节点 = 溯源节点）
    addProtocolNode,
    updateProtocolNode,
    removeProtocolNode,
    saveProtocolNodes,
  }
}