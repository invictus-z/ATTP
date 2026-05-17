import { ref, reactive } from 'vue'
import { apiUrl } from '../agent_manager'
import { apiFetch } from '../transport'

export interface AttpConfig {
  did: string
  attpClient: {
    didDocPath: string
    didKeyPath: string
    nodeAds: string[]
  }
  attpServer: {
    name: string
    prefix: string
    description: string
    serverHost: string
    serverPort: number
    privateKeyPath: string
    publicKeyPath: string
  }
  webApp: {
    host: string
    port: number
  }
  tool: {
    host: string
    port: number
  }
  heartbeat: {
    interval: number
    timeout: number
    maxFail: number
  }
}

type ConfigStatus = 'loading' | 'active' | 'disabled' | 'error'

const config = reactive<AttpConfig>({
  did: '',
  attpClient: { didDocPath: '', didKeyPath: '', nodeAds: [] },
  attpServer: { name: '', prefix: '', description: '', serverHost: '', serverPort: 0, privateKeyPath: '', publicKeyPath: '' },
  webApp: { host: '', port: 0 },
  tool: { host: '', port: 0 },
  heartbeat: { interval: 0, timeout: 0, maxFail: 0 },
})

const configStatus = ref<ConfigStatus>('loading')
const configSaving = ref(false)
const configReloading = ref(false)

// Toast state
const toastVisible = ref(false)
const toastMessage = ref('')
const toastType = ref<'success' | 'error' | 'warning'>('success')

// Original webApp config for change detection
let _originalWebAppConfig: { host: string; port: number } | null = null

function showToast(message: string, type: 'success' | 'error' | 'warning', duration = 3000) {
  toastMessage.value = message
  toastType.value = type
  toastVisible.value = true
  setTimeout(() => { toastVisible.value = false }, duration)
}

function fillConfig(cfg: any) {
  config.did = cfg.did || ''
  config.attpClient.didDocPath = cfg.attpClient?.didDocPath || ''
  config.attpClient.didKeyPath = cfg.attpClient?.didKeyPath || ''
  config.attpClient.nodeAds = cfg.attpClient?.nodeAds || []
  config.attpServer.name = cfg.attpServer?.name || ''
  config.attpServer.prefix = cfg.attpServer?.prefix || ''
  config.attpServer.description = cfg.attpServer?.description || ''
  config.attpServer.serverHost = cfg.attpServer?.serverHost || ''
  config.attpServer.serverPort = cfg.attpServer?.serverPort || 0
  config.attpServer.privateKeyPath = cfg.attpServer?.privateKeyPath || ''
  config.attpServer.publicKeyPath = cfg.attpServer?.publicKeyPath || ''
  config.webApp.host = cfg.webApp?.host || ''
  config.webApp.port = cfg.webApp?.port || 0
  config.tool.host = cfg.tool?.host || ''
  config.tool.port = cfg.tool?.port || 0
  config.heartbeat.interval = cfg.heartbeat?.interval || 0
  config.heartbeat.timeout = cfg.heartbeat?.timeout || 0
  config.heartbeat.maxFail = cfg.heartbeat?.maxFail || 0
}

export function useSettings() {
  const loadConfig = async () => {
    configStatus.value = 'loading'
    const configUrl = apiUrl('/api/config')
    console.log(`[DEBUG-CONN][useSettings] loadConfig → ${configUrl}`)
    try {
      const result = await apiFetch(configUrl)
      const data = result.data

      if (result.error || data?.error || !data?.config) {
        console.warn(`[DEBUG-CONN][useSettings] loadConfig FAIL: error="${result.error}", data.error="${data?.error}", hasConfig=${!!data?.config}`)
        configStatus.value = 'disabled'
        return
      }

      fillConfig(data.config)
      _originalWebAppConfig = { host: config.webApp.host, port: config.webApp.port }
      configStatus.value = 'active'
      console.log(`[DEBUG-CONN][useSettings] loadConfig OK: did="${config.did}", webApp=${config.webApp.host}:${config.webApp.port}`)
    } catch (e) {
      console.error('[DEBUG-CONN][useSettings] loadConfig EXCEPTION:', e)
      configStatus.value = 'error'
    }
  }

  const saveConfig = async () => {
    configSaving.value = true
    const payload = {
      did: config.did,
      attpClient: { ...config.attpClient },
      attpServer: { ...config.attpServer },
      webApp: { ...config.webApp },
      tool: { ...config.tool },
      heartbeat: { ...config.heartbeat },
    }

    try {
      const result = await apiFetch(apiUrl('/api/config'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = result.data

      if (data?.success) {
        _originalWebAppConfig = { host: config.webApp.host, port: config.webApp.port }
        showToast('Configuration saved (not yet applied)', 'success')
      } else {
        showToast(data.error || 'Failed to save configuration', 'error')
      }
    } catch (e) {
      showToast('Network error: failed to save', 'error')
    } finally {
      configSaving.value = false
    }
  }

  const refreshConfig = async () => {
    try {
      const result = await apiFetch(apiUrl('/api/config?refresh=true'))
      const data = result.data

      if (result.error || data?.error) {
        showToast('Failed to refresh configuration', 'error')
        return
      }

      fillConfig(data.config)
      _originalWebAppConfig = { host: config.webApp.host, port: config.webApp.port }
      showToast('Configuration refreshed from disk', 'success')
    } catch (e) {
      showToast('Network error: failed to refresh', 'error')
    }
  }

  const reloadConfig = async () => {
    configReloading.value = true
    const prevWebAppConfig = _originalWebAppConfig ? { ..._originalWebAppConfig } : null

    try {
      const result = await apiFetch(apiUrl('/api/config/reload'), { method: 'POST' })
      const data = result.data

      if (data?.success) {
        fillConfig(data.config)

        // Warn if WebApp host/port changed
        const newWebApp = { host: config.webApp.host, port: config.webApp.port }
        if (prevWebAppConfig && (
          prevWebAppConfig.host !== newWebApp.host || prevWebAppConfig.port !== newWebApp.port
        )) {
          setTimeout(() => {
            showToast('Web App host/port 已变更，需要手动重启 agent 使其完全生效', 'warning', 5000)
          }, 500)
        }
        _originalWebAppConfig = newWebApp
        showToast('Configuration reloaded and applied', 'success')
      } else {
        showToast(data.error || 'Failed to reload configuration', 'error')
      }
    } catch (e) {
      showToast('Network error: failed to reload', 'error')
    } finally {
      configReloading.value = false
    }
  }

  const addNodeAd = () => {
    config.attpClient.nodeAds.push('')
  }

  const removeNodeAd = (index: number) => {
    config.attpClient.nodeAds.splice(index, 1)
  }

  return {
    config,
    configStatus,
    configSaving,
    configReloading,
    toastVisible,
    toastMessage,
    toastType,
    loadConfig,
    saveConfig,
    refreshConfig,
    reloadConfig,
    addNodeAd,
    removeNodeAd,
  }
}