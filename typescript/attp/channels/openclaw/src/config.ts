/**
 * openclaw `channels.attp` 配置读取 — Plan 3, Task 2。
 *
 * 这是 openclaw 的简洁渠道配置（`{ enabled, config_path }`，与 nanobot 同形）
 * 与 ATTP agent 配置之间的桥梁：从 `config_path` 指向的 ATTP agent 配置文件
 * 加载完整身份/协议信息，交给 Plan 2 T1 的 `loadAgentConfig` 做字段选取。
 *
 * `enabled` 默认为 true（仅当显式写 `false` 时才关闭）——与 nanobot 渠道一致，
 * 便于在 openclaw 配置里仅写 `config_path` 即可启用。
 */

import { readFileSync } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { loadAgentConfig, type AgentConfig } from "../../../app/config.js";

/** openclaw `channels.attp` 解析后的渠道配置视图。 */
export interface ChannelConfig {
  /** 是否启用 ATTP 渠道（默认 true）。 */
  enabled: boolean;
  /** 从 config_path 加载并选取字段后的 ATTP agent 配置。 */
  agent: AgentConfig;
}

/**
 * 从 openclaw 配置对象读取 ATTP 渠道配置。
 *
 * 入参 `cfg` 为 openclaw 的配置根（包含 `channels.attp`）。
 * `channels.attp` 缺省时按空 section 处理：`enabled` 默认 true，
 * 但此时 `config_path` 也会缺省 → `readFileSync` 会抛错（调用方需在
 * 渠道实际启用时提供 `config_path`，与 nanobot 一致）。
 */
export async function readChannelConfig(cfg: any): Promise<ChannelConfig> {
  const section = cfg?.channels?.attp ?? {};
  const raw = JSON.parse(readFileSync(expandHome(section.config_path), "utf8"));
  return {
    enabled: section.enabled !== false,
    agent: loadAgentConfig(raw),
  };
}

/**
 * 展开 `~` / `~/` 为用户 home 目录；其余路径原样返回。
 * 与 app/config.ts 的 expandHome 行为对齐。
 */
function expandHome(p: string): string {
  if (!p) return p;
  if (p === "~") return os.homedir();
  if (p.startsWith("~/") || p.startsWith("~\\")) {
    return path.join(os.homedir(), p.slice(1));
  }
  return p;
}
