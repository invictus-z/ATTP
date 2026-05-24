# 配置示例

本目录包含 ATTP 各端的配置文件示例，供参考使用。

## 文件说明

### agent_config_demo.json
Agent 端配置文件示例，包含：
- DID 配置
- ATTP 客户端/服务端配置
- Web 应用配置
- 工具客户端配置
- 心跳配置
- 协议节点配置

使用方法：
```bash
# 复制示例配置到实际位置
cp examples/agent_config_demo.json ~/.attp/agent/nanobot/config.json

# 根据实际情况修改配置项
# - 修改 did 为你的节点 DID
# - 修改路径为你的 DID 文档和密钥路径
# - 修改 nodeAds 为其他节点的 ad.json 地址
```

### protocol_node_config_demo.json
协议节点配置文件示例，包含：
- Web 服务配置
- 数据存储配置
- 分析配置（可选）

使用方法：
```bash
# 复制示例配置到实际位置
cp examples/protocol_node_config_demo.json ~/.attp/protocol_node/config.json

# 根据实际情况修改配置项
# - 修改 host 和 port 为实际监听地址
# - 如需启用分析，配置 analysis 相关参数
```

## 注意事项

1. 所有配置文件中的路径都支持 `~` 展开，会自动替换为用户主目录
2. 配置文件使用 JSON 格式，确保格式正确
3. 修改配置后，相关服务可能需要重启才能生效
4. 敏感信息（如 API Key）建议通过环境变量或配置管理工具管理