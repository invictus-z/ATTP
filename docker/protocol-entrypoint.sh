#!/bin/sh
# Protocol 容器入口：用 .env / docker-compose 注入的 LLM_* 渲染 analysis 配置，再启动。
# ProtocolNodeConfigFile 不支持 ${VAR}，故构建期把 config 存为 .tmpl，运行期 envsubst 覆盖。
set -e

TEMPLATE=/root/.attp/protocol_node/config.json.tmpl
TARGET=/root/.attp/protocol_node/config.json

if [ -z "${LLM_API_KEY}" ]; then
    echo "[protocol-entrypoint] 警告：LLM_API_KEY 未设置，意图追踪分析将无法调用 LLM（协议节点仍启动、预置数据可展示）。" >&2
fi

envsubst < "$TEMPLATE" > "$TARGET"

echo "[protocol-entrypoint] protocol config 已渲染，启动..."
exec attp protocol-node start --config "$TARGET"
