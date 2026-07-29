#!/usr/bin/env bash
# 构建并导出 protocol/tool/agent 三镜像为 tarball，供 GitHub Release 离线分发。
# 评委 docker load 后镜像以 attp-*:latest tag 进本地，docker compose up 直接命中。
#
# 用法:  bash docker/save-images.sh [version]
set -e
cd "$(dirname "$0")/.."   # 切到仓库根

VER="${1:-0.2.0-alpha.1.demo}"
IMAGES=(
  attp-protocol:latest
  attp-tool:latest
  attp-agent:latest
)

echo "▶ docker compose build"
docker compose -f docker-compose.yml build

mkdir -p docker/release
OUT="docker/release/attp-images-${VER}.tar.gz"
echo "▶ docker save → ${OUT}"
docker save "${IMAGES[@]}" | gzip > "${OUT}"

echo "✓ ${OUT} ($(du -h "${OUT}" | cut -f1))"
echo "  上传到 GitHub Release；评委用：docker load -i ${OUT}"
