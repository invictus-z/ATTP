/**
 * useProtocolNodes — 协议节点共享状态与 CRUD。
 *
 * 模块级单例：三个视图共享同一份节点列表与当前选中节点。
 * 节点持久化经 useAttpProtocol 的 protocolNodes 配置。
 */

import { ref, computed } from 'vue'
import { apiFetch } from '../transport'
import { useAttpProtocol } from './useAttpProtocol'

export interface TraceNode {
  id: string
  name: string
  url: string
  status: 'online' | 'offline' | 'checking'
}

// ---- 模块级单例状态 ----

const traceNodes = ref<TraceNode[]>([])
const selectedNodeId = ref<string | null>(null)
let loaded = false

const { userConfig, saveProtocolNodes: configSaveProtocolNodes } = useAttpProtocol()

function makeId(url: string): string {
  return 'node_' + url.replace(/[^a-zA-Z0-9]/g, '_')
}

/** 从持久化配置加载节点列表（幂等，仅首次真正加载）。 */
function loadNodes(force = false): void {
  if (loaded && !force) return
  loaded = true
  const stored = userConfig.protocolNodes || []
  traceNodes.value = stored.map(n => ({
    id: makeId(n.url),
    name: n.name,
    url: n.url,
    status: 'checking' as const,
  }))
}

/** 把当前 traceNodes 写回持久化配置。 */
async function persist(): Promise<void> {
  await configSaveProtocolNodes(traceNodes.value.map(({ name, url }) => ({ name, url })))
}

async function checkNodeStatus(node: TraceNode): Promise<'online' | 'offline'> {
  node.status = 'checking'
  try {
    const result = await apiFetch(`${node.url}/api/status`)
    node.status = result.ok ? 'online' : 'offline'
  } catch {
    node.status = 'offline'
  }
  return node.status
}

function checkAllNodes(): void {
  traceNodes.value.forEach(node => { checkNodeStatus(node) })
}

async function addNode(name: string, url: string): Promise<boolean> {
  const cleanName = name.trim()
  const cleanUrl = url.trim().replace(/\/+$/, '')
  if (!cleanName || !cleanUrl) return false
  if (traceNodes.value.some(n => n.url === cleanUrl)) return false
  const node: TraceNode = { id: makeId(cleanUrl), name: cleanName, url: cleanUrl, status: 'checking' }
  traceNodes.value.push(node)
  await persist()
  checkNodeStatus(node)
  return true
}

async function updateNode(id: string, name: string, url: string): Promise<boolean> {
  const cleanName = name.trim()
  const cleanUrl = url.trim().replace(/\/+$/, '')
  if (!cleanName || !cleanUrl) return false
  const idx = traceNodes.value.findIndex(n => n.id === id)
  if (idx < 0) return false
  traceNodes.value[idx] = { ...traceNodes.value[idx], name: cleanName, url: cleanUrl, status: 'checking' }
  await persist()
  checkNodeStatus(traceNodes.value[idx])
  return true
}

async function removeNode(id: string): Promise<boolean> {
  const idx = traceNodes.value.findIndex(n => n.id === id)
  if (idx < 0) return false
  traceNodes.value.splice(idx, 1)
  if (selectedNodeId.value === id) selectedNodeId.value = null
  await persist()
  return true
}

async function testConnection(node: TraceNode): Promise<'online' | 'offline'> {
  return checkNodeStatus(node)
}

const selectedNode = computed<TraceNode | null>(
  () => traceNodes.value.find(n => n.id === selectedNodeId.value) || null,
)

/** 基于当前选中节点构造完整 URL；未选中返回空串。 */
function buildUrl(path: string): string {
  if (!selectedNode.value) return ''
  return `${selectedNode.value.url.replace(/\/+$/, '')}${path}`
}

/** 默认选中第一个在线节点（若无选中）。 */
function ensureSelection(): void {
  if (selectedNodeId.value) return
  const first = traceNodes.value.find(n => n.status === 'online') || traceNodes.value[0]
  if (first) selectedNodeId.value = first.id
}

export function useProtocolNodes() {
  return {
    // state
    traceNodes,
    selectedNodeId,
    selectedNode,
    // actions
    loadNodes,
    checkNodeStatus,
    checkAllNodes,
    addNode,
    updateNode,
    removeNode,
    testConnection,
    ensureSelection,
    // helpers
    buildUrl,
  }
}
