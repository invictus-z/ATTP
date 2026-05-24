import { ref, type Component } from 'vue'
import { getActiveAgent, apiUrl } from '../agent_manager'
import { apiFetch } from '../transport'
import { Database, ShieldCheck, Server } from 'lucide-vue-next'

export interface AgentNode {
  name: string
  did: string
  ad_url: string
  description: string
  capabilities: string[]
  online: boolean
}

const agentNodes = ref<AgentNode[]>([])

export function useNodes() {
  const fetchNodes = async () => {
    if (!getActiveAgent()) return
    try {
      const result = await apiFetch(apiUrl('/api/nodes'))
      agentNodes.value = result.data?.agents || []
    } catch (e) {
      console.error('Failed to load nodes:', e)
    }
  }

  const getNodeIcon = (capabilities: string[]): Component => {
    if (capabilities.includes('data_storage')) return Database
    if (capabilities.includes('security_check')) return ShieldCheck
    return Server
  }

  return { agentNodes, fetchNodes, getNodeIcon }
}