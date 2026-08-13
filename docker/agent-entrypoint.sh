#!/bin/sh
# Agent 容器入口：用 .env 注入的 LLM_* 渲染 nanobot 配置，再启动 gateway。
# 工作区已在构建期由 `nanobot onboard` 生成，此处仅覆盖 config（不调 onboard，避免 confirm 卡住）。
set -e

TEMPLATE=/root/.nanobot-template/config.json
TARGET=/root/.nanobot/config.json

if [ -z "${LLM_API_KEY}" ]; then
    echo "[agent-entrypoint] 警告：LLM_API_KEY 未设置，agent 将无法调用 LLM。请在 .env 中配置 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL。" >&2
fi

# envsubst 仅替换 ${VAR} 形式的占位（JSON 中无其他 $ 符号，安全）
envsubst < "$TEMPLATE" > "$TARGET"

echo "[agent-entrypoint] nanobot config 已渲染，启动 gateway..."
exec nanobot gateway --config "$TARGET"
