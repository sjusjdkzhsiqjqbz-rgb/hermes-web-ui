# Hermes Web UI

> ⚠️ **Vibe Coded** — This project was born in an AI-agent coding session and evolved iteratively through prompts. The code works but may surprise you. Found a bug? Fix it, laugh about it, or open a PR. All contributions welcome.

A web interface for [Hermes Agent CLI](https://github.com/nousresearch/hermes-agent). FastAPI + vanilla HTML/CSS/JS. ChatGPT-like chat UI that calls `hermes chat -Q -q` under the hood.

## Features

- **AI Chat** — full chat interface with markdown rendering and code highlighting
- **SSE Streaming** — responses stream token-by-token via Server-Sent Events
- **Real-time streaming** — `/api/chat/{id}/stream` endpoint using `asyncio.create_subprocess_exec`
- **Session management** — create, rename, delete, switch between chat sessions
- **Live model list** — parses `hermes config show` + loads custom providers from DB
- **Custom providers** — add API keys and base URLs through the UI (stored in SQLite)
- **Personalities** — Mariko, Helpful, Technical, Pirate, Noir, Philosopher, Hype
- **Dark/Light theme** — persisted server-side
- **Export** — JSON and Markdown
- **File uploads** — up to 50MB via `/api/upload`
- **ANSI stripping** — all those colored escape codes from Hermes CLI are cleaned up

## Project Structure

```
hermes-web-ui/
├── app.py                 # FastAPI — the heart (SQLite, SSE, CLI bridge)
├── AGENTS.md              # Rules for AI coding agents (OpenCode, Claude Code, etc.)
├── requirements.txt       # fastapi, uvicorn, jinja2, aiofiles
├── LICENSE                # BSD 2-Clause
├── templates/
│   └── index.html        # Jinja2 — main chat page
├── static/
│   ├── style.css         # Dark + light themes
│   └── script.js         # ES6+, Fetch API, SSE via EventSource
├── data/                  # SQLite database (gitignored)
├── uploads/               # Uploaded files (gitignored)
└── __pycache__/
```

## Quick Start

```bash
pip install -r requirements.txt
python app.py
# → http://localhost:8000
```

Or with uvicorn directly:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Chat UI |
| GET | `/api/models` | Models from Hermes config + custom providers |
| GET | `/api/personalities` | Available personalities |
| GET/POST | `/api/sessions` | List/create sessions |
| GET/PUT/DELETE | `/api/sessions/{id}` | Get/update/delete session |
| POST | `/api/chat` | Send message → Hermes CLI → response |
| GET | `/api/chat/{id}/stream` | SSE streaming |
| GET | `/api/sessions/{id}/export/json` | Export as JSON |
| GET | `/api/sessions/{id}/export/markdown` | Export as Markdown |
| GET/POST/DELETE | `/api/providers` | CRUD for custom providers |
| POST | `/api/upload` | File upload (≤50MB) |
| GET/POST | `/api/settings/theme` | Theme (dark/light) |

## Looking to Contribute?

Check out the [open issues](https://github.com/sjusjdkzhsiqjqbz-rgb/hermes-web-ui/issues) — there's plenty to work on:

- Authentication / login system
- Docker support (Dockerfile + compose)
- WebSocket streaming (alongside SSE)
- Full-text search across chat history
- One-click deploy (Railway / Render / Fly.io)
- System prompt editor per session
- PDF / image export for chat transcripts
- Voice input (Whisper + browser mic)
- Usage dashboard — token counts, sessions, favorite models

Pick one, fork it, send a PR. Sempai will be grateful.

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, SQLite, Jinja2, Uvicorn
- **Frontend**: Vanilla HTML/CSS/JS, `marked.js` + `highlight.js` via CDN
- **CLI**: `hermes chat -Q -q` via `subprocess` / `asyncio.create_subprocess_exec`
- **Storage**: SQLite (`data/hermes_web.db`)

## Known Quirks

- `Jinja2Templates.TemplateResponse` requires **3 arguments** in Starlette 1.0.0 (not 2) — old 2-arg signature crashes with `TypeError: unhashable type: 'dict'`
- ANSI escape codes from Hermes CLI are stripped with a regex before returning to the client
- `hermes chat -q` without `-Q` prints a banner — we always use `-Q` to suppress it
- SQLite is not production-ready without migrations — this is a toy project
- Vibe coded means "test coverage? what tests?" — tread carefully in production

## License

BSD 2-Clause License. Do what you want but don't say you weren't warned.
