# Hermes AI Web UI

## Overview

FastAPI web interface for [Hermes Agent CLI](https://github.com/nousresearch/hermes-agent). Provides a ChatGPT-like browser UI that calls `hermes chat -Q -q` under the hood.

## Tech Stack

- **Backend**: FastAPI 0.115+ (Starlette 1.0.0), Python 3.11+
- **Frontend**: Vanilla HTML/CSS/JS (no framework), marked.js + highlight.js via CDN
- **Storage**: SQLite (`data/hermes_web.db`)
- **CLI integration**: `hermes chat -Q -q "{message}"` via subprocess
- **Server**: uvicorn on 0.0.0.0:8000

## Project Structure

```
hermes-web-ui/
├── app.py                 # FastAPI application (main entry point)
├── AGENTS.md              # This file — project rules for AI coding agents
├── requirements.txt       # Python dependencies
├── templates/
│   └── index.html        # Jinja2 template — main page
├── static/
│   ├── style.css         # Dark + light theme CSS
│   └── script.js         # Frontend logic (ES6+, Fetch API)
├── data/                 # SQLite database (gitignored)
├── uploads/              # Uploaded files (gitignored)
└── .gitignore
```

## Critical Rules for AI Agents

### Starlette 1.0.0 Compatibility
- `Jinja2Templates.TemplateResponse` requires **3 args**: `TemplateResponse(request, "template.html", {"key": val})`
- Do NOT use old 2-arg signature — it will crash with `TypeError: unhashable type: 'dict'`

### Hermes CLI Invocation
- Command: `hermes chat -Q -q "{message}" [-m {model}]`
  - `-Q` = quiet mode (supress banner), ALWAYS include
  - `-q` = single query (non-interactive), ALWAYS include
- `--personality` flag does NOT exist on hermes CLI — do NOT use it
- `--model` is optional (skip for default model)
- `hermes list` does NOT exist — do NOT call it
- To get available models: parse `hermes config show` output (look for `Model:` line with a dict literal)
- Personality is stored in DB but NOT passed to CLI (hermes uses its own config for personality)

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve chat UI (HTML) |
| GET | `/api/models` | Models from hermes config + custom providers |
| GET | `/api/personalities` | Available personalities (mariko, helpful, etc.) |
| GET/POST | `/api/sessions` | List/create chat sessions |
| GET/PUT/DELETE | `/api/sessions/{id}` | Get/update/delete session |
| POST | `/api/chat` | Send message → hermes CLI → return response |
| GET | `/api/chat/{session_id}/stream` | SSE streaming endpoint |
| GET | `/api/sessions/{id}/export/json` | Export as JSON |
| GET | `/api/sessions/{id}/export/markdown` | Export as Markdown |
| GET | `/api/providers` | List providers |
| POST | `/api/providers` | Add provider (name, api_key, base_url) |
| DELETE | `/api/providers/{id}` | Remove provider |
| POST | `/api/upload` | File upload (max 50MB) |
| GET | `/api/uploads` | List uploaded files |
| GET/POST | `/api/settings/theme` | Get/set theme (dark/light) |

### Frontend Notes
- `state.currentPersonality` tracks selected personality in UI
- `state.currentModel` tracks selected model
- `__custom__` model option triggers a prompt for manual model name input
- Markdown rendered via `marked.js` + code highlighting via `highlight.js`
- Export buttons disabled when no active session
- Theme persisted via `/api/settings/theme` API

### Common Pitfalls
- Python f-strings with dict literals inside: use single quotes for keys: `f"... {d['key']} ..."` not `f"... {d["key"]} ..."`
- `json.dumps()` inside f-strings: wrap with single-quote dict: `f"... {json.dumps({'key': val})} ..."`
- SQLite connections must be closed after each request
- File upload path traversal: use `os.path.basename()` to sanitize filenames
- `hermes chat -q` output may contain ANSI escape codes — strip them
- Always set `capture_output=True, text=True, timeout=120` on subprocess calls

### Testing
```bash
# Start server
python3 app.py

# Test endpoints
curl -o /dev/null -w "%{http_code}" http://localhost:8000/
curl http://localhost:8000/api/models
curl -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" -d '{"message":"Hi"}'
curl http://localhost:8000/api/sessions/{id}/export/json
```
