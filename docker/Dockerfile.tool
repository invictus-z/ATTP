# 工具节点（Tool Node）镜像
# 运行 test/demo_tool_node.py（计算器 add 工具），需最先启动以便 agent 发现。
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY python ./python
RUN pip install --no-cache-dir .

# 预置工具身份（容器内 ~/.attp/tool/）
COPY examples/.attp/tool /root/.attp/tool
COPY test/demo_tool_node.py ./demo_tool_node.py

EXPOSE 9999

# healthcheck 复用 GET /attp/ad.json
HEALTHCHECK --interval=10s --timeout=5s --start-period=8s --retries=6 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:9999/attp/ad.json',timeout=4).status==200 else 1)"

CMD ["python", "demo_tool_node.py"]
