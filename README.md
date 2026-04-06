```bash
uv venv
uv pip install -e .
```

8000 ATTP server
8001 web app server
8002 mcp tool

"attp-send-message": {
  "type": "sse",
  "url": "http://127.0.0.1:8002/sse",
  "enabledTools": ["send_message_tool"]
}