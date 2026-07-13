import type { OpenClawConfig } from "openclaw/plugin-sdk/channel-core";

export interface AttpChannelConfig {
  /** Python interpreter (ATTP venv) used to spawn the adapter. */
  pythonPath: string;
  /** ATTP openclaw profile config path (~/.attp/agent/openclaw/config.json). */
  configPath: string;
  /** ATTP WebApp port — where POST /openclaw/reply is served. Default 8001. */
  webAppPort: number;
}

export function readAttpConfig(cfg: OpenClawConfig): AttpChannelConfig {
  const section = (cfg.channels as Record<string, any>)?.["attp"] ?? {};
  if (!section.pythonPath) {
    throw new Error("channels.attp.pythonPath is required (point it at the ATTP venv python)");
  }
  if (!section.configPath) {
    throw new Error("channels.attp.configPath is required (ATTP openclaw profile config)");
  }
  return {
    pythonPath: String(section.pythonPath),
    configPath: String(section.configPath),
    webAppPort: Number(section.webAppPort ?? 8001),
  };
}
