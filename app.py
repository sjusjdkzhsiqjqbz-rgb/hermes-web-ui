from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Dict, List, Optional
import uuid
import asyncio
import json
import sqlite3
import subprocess
import os
import shutil
import re
from datetime import datetime
from pathlib import Path

app = FastAPI(title="Hermes AI CLI Web Interface")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")

# Database setup
DB_PATH = Path("data") / "hermes_web.db"
UPLOADS_DIR = Path("uploads")

# Constants
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB max file size
ALLOWED_FILENAME_PATTERN = re.compile(r'^[a-zA-Z0-9._-]+$')

# Hermes config paths
HERMES_CONFIG_PATH = Path.home() / ".hermes" / "config.yaml"
MODELS_CACHE_PATH = Path.home() / ".hermes" / "models_dev_cache.json"

# Cache for models (refresh every 5 minutes)
_models_cache = None
_models_cache_time = 0
MODELS_CACHE_TTL = 300  # 5 minutes

def init_db():
    """Initialize SQLite database with required tables."""
    DB_PATH.parent.mkdir(exist_ok=True)
    UPLOADS_DIR.mkdir(exist_ok=True)
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Chat sessions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            model TEXT,
            personality TEXT DEFAULT 'helpful',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')
    
    # Messages table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
        )
    ''')
    
    # Providers table for API keys
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS providers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            api_key TEXT NOT NULL,
            base_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')
    
    # Settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    
    # Insert default settings if not exists
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) VALUES ('theme', 'dark')
    ''')
    
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()

def get_db():
    """Get database connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def sanitize_input(text: str) -> str:
    """Sanitize user input to prevent command injection."""
    if not text:
        return ""
    # Remove any characters that could be used for command injection
    # Only allow alphanumeric, spaces, and common punctuation
    sanitized = re.sub(r'[;&|`$(){}[\]\\]', '', text)
    return sanitized.strip()

def validate_model_name(model: str) -> bool:
    """Validate model name to prevent injection."""
    if not model:
        return True  # Default is allowed
    # Allow alphanumeric, hyphens, dots, slashes, and underscores (for provider/model format)
    return bool(re.match(r'^[a-zA-Z0-9._/-]+$', model))

def secure_filename(filename: str) -> str:
    """Secure a filename to prevent path traversal."""
    # Remove any path components
    filename = os.path.basename(filename)
    # Remove any null bytes
    filename = filename.replace('\x00', '')
    # Replace any suspicious characters
    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    # Ensure it's not empty
    if not filename:
        filename = 'unnamed_file'
    return filename

# Connected WebSocket clients
connected_clients: Dict[str, WebSocket] = {}

# Available personalities
PERSONALITIES = [
    {"id": "mariko", "name": "Mariko", "description": "Thoughtful and introspective"},
    {"id": "helpful", "name": "Helpful", "description": "Friendly and accommodating"},
    {"id": "concise", "name": "Concise", "description": "Brief and to the point"},
    {"id": "technical", "name": "Technical", "description": "Precise and detailed"},
    {"id": "pirate", "name": "Pirate", "description": "Arr, matey! Swashbuckling speech"},
    {"id": "noir", "name": "Noir", "description": "Hardboiled detective style"},
    {"id": "philosopher", "name": "Philosopher", "description": "Contemplative and wise"},
    {"id": "hype", "name": "Hype", "description": "Enthusiastic and energetic"},
]

class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None

class ChatSession(BaseModel):
    id: str
    name: str
    model: str
    personality: str = "helpful"
    messages: List[ChatMessage] = []
    created_at: str
    updated_at: str

class Provider(BaseModel):
    id: str
    name: str
    api_key: str
    base_url: Optional[str] = None

def get_hermes_config():
    """Read hermes config from yaml file."""
    if not HERMES_CONFIG_PATH.exists():
        return {}
    try:
        import yaml
        with open(HERMES_CONFIG_PATH, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error reading hermes config: {e}")
        return {}


def get_hermes_configured_providers():
    """Get providers configured in hermes."""
    config = get_hermes_config()
    providers = []

    # Main model provider
    model_cfg = config.get('model', {})
    if model_cfg and model_cfg.get('provider'):
        providers.append({
            'id': model_cfg['provider'],
            'name': model_cfg['provider'],
            'base_url': model_cfg.get('base_url', ''),
            'api_key': model_cfg.get('api_key', ''),
            'source': 'main'
        })

    # Custom providers
    for cp in config.get('custom_providers', []):
        pid = cp.get('name', 'unknown').lower().replace(' ', '-')
        providers.append({
            'id': pid,
            'name': cp.get('name', 'unknown'),
            'base_url': cp.get('base_url', ''),
            'api_key': cp.get('api_key', ''),
            'source': 'custom'
        })

    return providers


def match_provider_to_cache(provider_name: str, base_url: str = '') -> str:
    """Map a configured provider to a provider ID in the model cache."""
    if not MODELS_CACHE_PATH.exists():
        return ''

    try:
        with open(MODELS_CACHE_PATH, encoding='utf-8') as f:
            cache = json.load(f)
    except Exception:
        return ''

    name_lower = provider_name.lower().replace(' ', '').replace('-', '').replace('_', '').replace('.', '')
    url_lower = base_url.lower()

    # Direct match (normalized)
    for pid in cache:
        pid_norm = pid.lower().replace(' ', '').replace('-', '').replace('_', '').replace('.', '')
        if pid_norm == name_lower:
            return pid

    # Special case mappings (before URL/substring to avoid false matches)
    special = {
        'apistepfunai': 'stepfun',
        'stepfun': 'stepfun',
        'apiopenaicom': 'openai',
        'apiperplexityai': 'perplexity',
        'apianthropiccom': 'anthropic',
    }
    if name_lower in special:
        return special[name_lower]

    # Match by base_url (non-empty only)
    if url_lower:
        for pid, prov in cache.items():
            api_url = prov.get('api', '').lower()
            if api_url and (url_lower in api_url or api_url in url_lower):
                return pid

    # Substring matching
    for pid in cache:
        pid_norm = pid.lower().replace(' ', '').replace('-', '').replace('_', '').replace('.', '')
        if pid_norm in name_lower or name_lower in pid_norm:
            return pid

    return ''


def get_model_family(model_name: str) -> str:
    """Extract model family from model name."""
    name_lower = model_name.lower()
    families = [
        'kimi', 'deepseek', 'qwen', 'gpt', 'claude', 'llama',
        'mistral', 'gemini', 'mixtral', 'phi', 'codellama',
        'command', 'jamba', 'dbrx', 'grok', 'nova', 'glm',
        'minimax', 'step', 'yi', 'cohere', 'solar', 'wizard',
        'vicuna', 'starcoder', 'neural', 'hunyuan', 'ernie',
        'zephyr', 'nous', 'mpt', 'falcon', 'palm'
    ]
    for fam in families:
        if fam in name_lower:
            return fam
    # Fallback: first alphabetic prefix
    m = re.match(r'^([a-zA-Z]+)', model_name)
    return m.group(1).lower() if m else 'other'


def get_provider_models():
    """Get models from configured providers with metadata."""
    global _models_cache, _models_cache_time

    current_time = datetime.now().timestamp()
    if _models_cache and (current_time - _models_cache_time) < MODELS_CACHE_TTL:
        return _models_cache

    providers = get_hermes_configured_providers()
    result = []
    seen_models = set()

    if MODELS_CACHE_PATH.exists():
        try:
            with open(MODELS_CACHE_PATH, encoding='utf-8') as f:
                cache = json.load(f)
        except Exception as e:
            print(f"Error reading model cache: {e}")
            cache = {}
    else:
        cache = {}

    # Also get default model from config
    config = get_hermes_config()
    model_cfg = config.get('model', {})
    default_model = model_cfg.get('default', '')
    default_provider = model_cfg.get('provider', '')

    for prov in providers:
        cache_id = match_provider_to_cache(prov['name'], prov.get('base_url', ''))
        if not cache_id:
            cache_id = prov['id']

        models_list = []

        if cache_id in cache:
            cache_prov = cache[cache_id]
            cache_models = cache_prov.get('models', {})

            for mid, minfo in cache_models.items():
                if (cache_id, mid) in seen_models:
                    continue
                seen_models.add((cache_id, mid))

                cost = minfo.get('cost', {})
                family = minfo.get('family', '') or get_model_family(mid)

                models_list.append({
                    'id': f"{cache_id}/{mid}",
                    'name': mid,
                    'provider': cache_id,
                    'provider_name': cache_prov.get('name', cache_id),
                    'configured_provider': prov['name'],  # actual name from hermes config
                    'family': family,
                    'price_input': cost.get('input'),
                    'price_output': cost.get('output'),
                    'context_length': minfo.get('limit', {}).get('context', '')
                })
        else:
            # Fallback: explicit models from custom_providers config
            for cp in config.get('custom_providers', []):
                if cp.get('name') == prov['name']:
                    explicit_models = cp.get('models', {})
                    for emid, eminfo in explicit_models.items():
                        if (prov['id'], emid) in seen_models:
                            continue
                        seen_models.add((prov['id'], emid))

                        models_list.append({
                            'id': f"{prov['id']}/{emid}",
                            'name': emid,
                            'provider': prov['id'],
                            'provider_name': prov['name'],
                            'configured_provider': prov['name'],
                            'family': get_model_family(emid),
                            'price_input': None,
                            'price_output': None,
                            'context_length': eminfo.get('context_length', '')
                        })

        if models_list:
            # Mark default model
            for m in models_list:
                if m['provider'] == default_provider and m['name'] == default_model:
                    m['is_default'] = True

            # Group by family for sorting
            models_list.sort(key=lambda x: (x['family'], x['name']))

            result.append({
                'id': cache_id if cache_id in cache else prov['id'],
                'name': cache[cache_id].get('name', cache_id) if cache_id in cache else prov['name'],
                'models': models_list
            })

    # Sort providers by name
    result.sort(key=lambda x: x['name'].lower())

    _models_cache = result
    _models_cache_time = current_time
    return result


def apply_ansi_strip(text: str) -> str:
    """Strip ANSI escape codes and hermes CLI warnings from output."""
    ansi_escape = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    text = ansi_escape.sub('', text)
    # Strip hermes normalization warnings
    text = re.sub(r'^\s*⚠️\s*.*\n', '', text, flags=re.MULTILINE)
    return text.strip()


def resolve_model_for_cli(model: str) -> tuple[str, str]:
    """
    Given a stored model ID like 'deepinfra/anthropic/claude-4-opus',
    return (configured_provider_name, actual_model_name) for hermes CLI.
    """
    if not model or model == 'default' or model.startswith('__'):
        return ('', '')

    if '/' not in model:
        return ('', model)

    # Split on first '/' to get cache provider id and actual model name
    cache_id, actual_model = model.split('/', 1)

    # Find configured provider that maps to this cache_id
    providers = get_hermes_configured_providers()
    for prov in providers:
        matched = match_provider_to_cache(prov['name'], prov.get('base_url', ''))
        if matched == cache_id:
            return (prov['name'], actual_model)

    # Fallback: use cache_id as provider name
    return (cache_id, actual_model)


async def generate_chat_title(first_message: str) -> str:
    """Generate a short, catchy title for a chat based on the first message."""
    try:
        # Truncate message if too long
        truncated_message = first_message[:500] if len(first_message) > 500 else first_message
        
        prompt = f"""Generate a short, catchy title (2-4 words) for a chat that starts with this message. 
        Respond with ONLY the title, no quotes, no explanation.

        Message: {truncated_message}

        Title:"""
        
        cmd = ["hermes", "chat", "-Q", "-q", prompt]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env=dict(os.environ, PYTHONUNBUFFERED="1")
        )
        
        if result.returncode == 0:
            title = apply_ansi_strip(result.stdout)
            # Clean up the title
            title = re.sub(r'^["\']|["\']$', '', title)  # Remove quotes
            title = re.sub(r'\s+', ' ', title)  # Normalize whitespace
            
            # Validate title length
            if len(title) > 60:
                title = title[:57] + "..."
            
            return title if title else "New Chat"
        else:
            return "New Chat"
    except Exception as e:
        print(f"Error generating chat title: {e}")
        return "New Chat"

@app.get("/", response_class=HTMLResponse)
async def get_chat_interface(request: Request):
    """Serve the main chat interface."""
    return templates.TemplateResponse(request, "index.html", {})

@app.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    return {"status": "ok"}

@app.get("/api/models")
async def get_models():
    """Get available AI models from configured hermes providers."""
    providers = get_provider_models()

    # Always add custom option
    providers.append({
        "id": "__custom__",
        "name": "Custom model...",
        "models": [{
            "id": "__custom__",
            "name": "Type model manually",
            "provider": "__custom__",
            "provider_name": "Custom",
            "family": "custom",
            "price_input": None,
            "price_output": None
        }]
    })

    # Also try to get default from hermes config show for any runtime overrides
    try:
        result = subprocess.run(
            ["hermes", "config", "show"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line.startswith('Model:'):
                    import ast
                    model_dict_str = line.split('Model:', 1)[1].strip()
                    try:
                        model_dict = ast.literal_eval(model_dict_str)
                        default_model = model_dict.get('default', '')
                        default_provider = model_dict.get('provider', '')
                        if default_model and default_provider:
                            # Mark default in providers if present
                            for prov in providers:
                                if prov['id'] == '__custom__':
                                    continue
                                for m in prov.get('models', []):
                                    if m['provider'] == default_provider and m['name'] == default_model:
                                        m['is_default'] = True
                    except Exception:
                        pass
    except Exception as e:
        print(f"Error parsing hermes config show: {e}")

    return {"providers": providers}

@app.get("/api/personalities")
async def get_personalities():
    """Get available personalities."""
    return {"personalities": PERSONALITIES}

@app.get("/api/sessions")
async def get_sessions():
    """Get all chat sessions."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.*, COUNT(m.id) as message_count 
        FROM sessions s 
        LEFT JOIN messages m ON s.id = m.session_id 
        GROUP BY s.id 
        ORDER BY s.updated_at DESC
    ''')
    sessions = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"sessions": sessions}

@app.post("/api/sessions")
async def create_session(request: Request):
    """Create a new chat session."""
    data = await request.json()
    session_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    
    # Sanitize inputs
    name = sanitize_input(data.get("name", "New Chat"))
    model = data.get("model", "default")
    if model != "default" and not validate_model_name(model):
        model = "default"
    personality = sanitize_input(data.get("personality", "helpful"))
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO sessions (id, name, model, personality, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        session_id,
        name,
        model,
        personality,
        now, now
    ))
    conn.commit()
    conn.close()
    
    return {
        "session": {
            "id": session_id,
            "name": name,
            "model": model,
            "personality": personality,
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }
    }

@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get a specific chat session with messages."""
    # Validate UUID format
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get session
    cursor.execute('SELECT * FROM sessions WHERE id = ?', (session_id,))
    session_row = cursor.fetchone()
    
    if not session_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = dict(session_row)
    
    # Get messages
    cursor.execute('''
        SELECT role, content, timestamp FROM messages 
        WHERE session_id = ? 
        ORDER BY timestamp ASC
    ''', (session_id,))
    session["messages"] = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return {"session": session}

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session."""
    # Validate UUID format
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
    conn.commit()
    conn.close()
    return {"message": "Session deleted"}

@app.put("/api/sessions/{session_id}")
async def update_session(session_id: str, request: Request):
    """Update a chat session (name, model, or personality)."""
    # Validate UUID format
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")
    
    data = await request.json()
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Build update query dynamically
    updates = []
    values = []
    if "name" in data:
        updates.append("name = ?")
        values.append(sanitize_input(data["name"]))
    if "model" in data:
        model = data["model"]
        if model != "default" and not validate_model_name(model):
            model = "default"
        updates.append("model = ?")
        values.append(model)
    if "personality" in data:
        updates.append("personality = ?")
        values.append(sanitize_input(data["personality"]))
    
    if updates:
        updates.append("updated_at = ?")
        values.append(datetime.now().isoformat())
        values.append(session_id)
        
        query = f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, values)
        conn.commit()
    
    conn.close()
    return {"message": "Session updated"}

@app.post("/api/sessions/{session_id}/messages")
async def add_message(session_id: str, request: Request):
    """Add a message to a session."""
    # Validate UUID format
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")
    
    data = await request.json()
    now = datetime.now().isoformat()
    
    # Sanitize content
    role = sanitize_input(data.get("role", "user"))
    content = data.get("content", "")
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO messages (session_id, role, content, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (session_id, role, content, now))
    
    cursor.execute('''
        UPDATE sessions SET updated_at = ? WHERE id = ?
    ''', (now, session_id))
    
    conn.commit()
    conn.close()
    
    return {"message": {"role": role, "content": content, "timestamp": now}}

@app.post("/api/chat")
async def chat_completion(request: Request):
    """Send a message to the AI via hermes CLI and get a response."""
    data = await request.json()
    session_id = data.get("session_id")
    message = data.get("message", "").strip()
    model = data.get("model")
    personality = data.get("personality", "helpful")
    stream = data.get("stream", False)
    
    # Validate and sanitize inputs
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    if model and model != "default" and not validate_model_name(model):
        model = "default"
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Create session if it doesn't exist
    if not session_id:
        session_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        
        # Generate a title for the new chat
        chat_title = await generate_chat_title(message)
        
        cursor.execute('''
            INSERT INTO sessions (id, name, model, personality, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session_id, chat_title, model or "default", sanitize_input(personality), now, now))
        conn.commit()
    else:
        # Validate session_id format
        try:
            uuid.UUID(session_id)
        except ValueError:
            conn.close()
            raise HTTPException(status_code=400, detail="Invalid session ID format")
        
        # Get session details
        cursor.execute('SELECT model, personality, name FROM sessions WHERE id = ?', (session_id,))
        row = cursor.fetchone()
        if row:
            model = model or row["model"] or "default"
            personality = personality or row["personality"] or "helpful"
            
            # Check if this is the first message (only user message)
            cursor.execute('SELECT COUNT(*) as count FROM messages WHERE session_id = ?', (session_id,))
            msg_count = cursor.fetchone()["count"]
            
            # If first message and title is generic, generate a new title
            if msg_count == 0 and row["name"] and (row["name"].startswith("Chat ") or row["name"] == "New Chat"):
                new_title = await generate_chat_title(message)
                cursor.execute('UPDATE sessions SET name = ? WHERE id = ?', (new_title, session_id))
                conn.commit()
    
    now = datetime.now().isoformat()
    
    # Add user message to database
    cursor.execute('''
        INSERT INTO messages (session_id, role, content, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (session_id, "user", message, now))
    
    conn.commit()
    
    # Call hermes CLI
    try:
        cmd = ["hermes", "chat", "-Q", "-q", message]
        
        # Add model and provider if specified
        if model and model != "default" and not model.startswith('__'):
            cli_provider, cli_model = resolve_model_for_cli(model)
            if cli_provider:
                cmd.extend(["--provider", cli_provider])
            if cli_model and validate_model_name(cli_model):
                cmd.extend(["--model", cli_model])
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=dict(os.environ, PYTHONUNBUFFERED="1")
        )
        
        if result.returncode == 0:
            ai_response = apply_ansi_strip(result.stdout)
        else:
            stderr_msg = apply_ansi_strip(result.stderr)
            ai_response = f"Error from Hermes CLI: {stderr_msg or 'Unknown error'}"
            
    except subprocess.TimeoutExpired:
        ai_response = "Error: Hermes CLI timed out. Please try again."
    except FileNotFoundError:
        ai_response = "Error: 'hermes' command not found. Please ensure Hermes CLI is installed and in PATH."
    except Exception as e:
        ai_response = f"Error calling Hermes CLI: {str(e)}"
    
    # Add AI response to database
    now = datetime.now().isoformat()
    cursor.execute('''
        INSERT INTO messages (session_id, role, content, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (session_id, "assistant", ai_response, now))
    
    cursor.execute('''
        UPDATE sessions SET updated_at = ? WHERE id = ?
    ''', (now, session_id))
    
    conn.commit()
    
    # Get all messages for response
    cursor.execute('''
        SELECT role, content, timestamp FROM messages 
        WHERE session_id = ? 
        ORDER BY timestamp ASC
    ''', (session_id,))
    messages = [dict(row) for row in cursor.fetchall()]
    
    # Get updated session info
    cursor.execute('SELECT name FROM sessions WHERE id = ?', (session_id,))
    session_row = cursor.fetchone()
    session_name = session_row["name"] if session_row else "Chat"
    
    conn.close()
    
    return {
        "response": ai_response,
        "session_id": session_id,
        "session_name": session_name,
        "session": {
            "id": session_id,
            "messages": messages
        }
    }

@app.get("/api/chat/stream")
async def chat_stream(request: Request):
    """Stream AI response word by word using SSE."""
    session_id = request.query_params.get("session_id")
    message = request.query_params.get("message", "").strip()
    model = request.query_params.get("model")
    personality = request.query_params.get("personality", "helpful")
    
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    if model and model != "default" and not validate_model_name(model):
        model = "default"
    
    async def event_generator():
        conn = get_db()
        cursor = conn.cursor()
        
        # Create or get session
        if not session_id:
            new_session_id = str(uuid.uuid4())
            now = datetime.now().isoformat()
            
            # Generate a title for the new chat
            chat_title = await generate_chat_title(message)
            
            cursor.execute('''
                INSERT INTO sessions (id, name, model, personality, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (new_session_id, chat_title, model or "default", sanitize_input(personality), now, now))
            conn.commit()
            
            yield f"event: session_info\ndata: {json.dumps({'session_id': new_session_id, 'session_name': chat_title})}\n\n"
            current_session_id = new_session_id
        else:
            try:
                uuid.UUID(session_id)
            except ValueError:
                conn.close()
                yield f"event: error\ndata: {json.dumps({'error': 'Invalid session ID'})}\n\n"
                return
            
            current_session_id = session_id
            
            # Get session details
            cursor.execute('SELECT model, personality, name FROM sessions WHERE id = ?', (session_id,))
            row = cursor.fetchone()
            if row:
                model = model or row["model"] or "default"
                
                # Check if this is the first message
                cursor.execute('SELECT COUNT(*) as count FROM messages WHERE session_id = ?', (session_id,))
                msg_count = cursor.fetchone()["count"]
                
                # If first message and title is generic, generate a new title
                if msg_count == 0 and row["name"] and (row["name"].startswith("Chat ") or row["name"] == "New Chat"):
                    new_title = await generate_chat_title(message)
                    cursor.execute('UPDATE sessions SET name = ? WHERE id = ?', (new_title, session_id))
                    conn.commit()
                    yield f"event: session_info\ndata: {json.dumps({'session_id': session_id, 'session_name': new_title})}\n\n"
                else:
                    yield f"event: session_info\ndata: {json.dumps({'session_id': session_id, 'session_name': row['name']})}\n\n"
        
        now = datetime.now().isoformat()
        
        # Add user message to database
        cursor.execute('''
            INSERT INTO messages (session_id, role, content, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (current_session_id, "user", message, now))
        conn.commit()
        
        # Call hermes CLI with streaming simulation
        full_response = ""
        try:
            cmd = ["hermes", "chat", "-Q", "-q", message]
            
            if model and model != "default" and not model.startswith('__'):
                cli_provider, cli_model = resolve_model_for_cli(model)
                if cli_provider:
                    cmd.extend(["--provider", cli_provider])
                if cli_model and validate_model_name(cli_model):
                    cmd.extend(["--model", cli_model])
            
            # Use asyncio subprocess for streaming
            env = dict(os.environ, PYTHONUNBUFFERED="1")
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            
            # Read output line by line, strip ANSI codes
            buffer = ""
            word_buffer = []
            
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                
                decoded = apply_ansi_strip(line.decode('utf-8', errors='replace'))
                if not decoded:
                    continue
                buffer += decoded + ' '
                
                # Split into words and stream them
                words = buffer.split(' ')
                buffer = words[-1]  # Keep incomplete word in buffer
                
                for word in words[:-1]:
                    word_buffer.append(word)
                    full_response += word + ' '
                    
                    # Send word every few words to simulate streaming
                    if len(word_buffer) >= 2:
                        text_to_send = ' '.join(word_buffer)
                        yield f"event: token\ndata: {json.dumps({'token': text_to_send + ' '})}\n\n"
                        word_buffer = []
                        await asyncio.sleep(0.01)  # Small delay for effect
            
            # Wait for process to complete
            await process.wait()
            
            # Send remaining words
            if word_buffer or buffer:
                remaining = ' '.join(word_buffer) + (' ' if word_buffer else '') + buffer
                full_response += remaining
                yield f"event: token\ndata: {json.dumps({'token': remaining})}\n\n"
            
            if process.returncode != 0:
                stderr = await process.stderr.read()
                error_msg = stderr.decode('utf-8', errors='replace').strip() or 'Unknown error'
                full_response = f"Error from Hermes CLI: {error_msg}"
                yield f"event: token\ndata: {json.dumps({'token': full_response})}\n\n"
                
        except FileNotFoundError:
            full_response = "Error: 'hermes' command not found. Please ensure Hermes CLI is installed and in PATH."
            yield f"event: token\ndata: {json.dumps({'token': full_response})}\n\n"
        except Exception as e:
            full_response = f"Error calling Hermes CLI: {str(e)}"
            yield f"event: token\ndata: {json.dumps({'token': full_response})}\n\n"
        
        # Save AI response to database
        now = datetime.now().isoformat()
        cursor.execute('''
            INSERT INTO messages (session_id, role, content, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (current_session_id, "assistant", full_response.strip(), now))
        
        cursor.execute('''
            UPDATE sessions SET updated_at = ? WHERE id = ?
        ''', (now, current_session_id))
        
        conn.commit()
        conn.close()
        
        # Signal completion
        yield f"event: done\ndata: {json.dumps({'session_id': current_session_id})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

# Provider Management Endpoints
@app.get("/api/providers")
async def get_providers():
    """Get all configured providers."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, base_url, created_at, updated_at FROM providers ORDER BY name')
    providers = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"providers": providers}

@app.post("/api/providers")
async def create_provider(request: Request):
    """Add a new provider."""
    data = await request.json()
    provider_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    
    # Sanitize inputs
    name = sanitize_input(data.get("name", ""))
    api_key = data.get("api_key", "").strip()
    base_url = sanitize_input(data.get("base_url", ""))
    
    if not name or not api_key:
        raise HTTPException(status_code=400, detail="Name and API key are required")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO providers (id, name, api_key, base_url, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        provider_id,
        name,
        api_key,
        base_url if base_url else None,
        now, now
    ))
    conn.commit()
    conn.close()
    
    return {"provider": {"id": provider_id, "name": name, "base_url": base_url if base_url else None}}

@app.delete("/api/providers/{provider_id}")
async def delete_provider(provider_id: str):
    """Delete a provider."""
    # Validate UUID format
    try:
        uuid.UUID(provider_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid provider ID format")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM providers WHERE id = ?', (provider_id,))
    conn.commit()
    conn.close()
    return {"message": "Provider deleted"}

# Export Endpoints
@app.get("/api/sessions/{session_id}/export/json")
async def export_session_json(session_id: str):
    """Export a session as JSON."""
    # Validate UUID format
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM sessions WHERE id = ?', (session_id,))
    session_row = cursor.fetchone()
    
    if not session_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = dict(session_row)
    cursor.execute('''
        SELECT role, content, timestamp FROM messages 
        WHERE session_id = ? 
        ORDER BY timestamp ASC
    ''', (session_id,))
    session["messages"] = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return JSONResponse(
        content=session,
        headers={"Content-Disposition": f"attachment; filename=chat_{session_id[:8]}.json"}
    )

@app.get("/api/sessions/{session_id}/export/markdown")
async def export_session_markdown(session_id: str):
    """Export a session as Markdown."""
    # Validate UUID format
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM sessions WHERE id = ?', (session_id,))
    session_row = cursor.fetchone()
    
    if not session_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = dict(session_row)
    cursor.execute('''
        SELECT role, content, timestamp FROM messages 
        WHERE session_id = ? 
        ORDER BY timestamp ASC
    ''', (session_id,))
    messages = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    # Build markdown
    md_lines = [
        f"# {session['name']}",
        "",
        f"**Model:** {session.get('model', 'default')}",
        f"**Personality:** {session.get('personality', 'helpful')}",
        f"**Created:** {session['created_at']}",
        "",
        "---",
        "",
    ]
    
    for msg in messages:
        role = msg['role'].capitalize()
        md_lines.append(f"## {role} ({msg['timestamp']})")
        md_lines.append("")
        md_lines.append(msg['content'])
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")
    
    content = "\n".join(md_lines)
    
    # Save to temp file for download
    temp_path = f"/tmp/chat_{session_id[:8]}.md"
    with open(temp_path, "w") as f:
        f.write(content)
    
    return FileResponse(
        temp_path,
        media_type="text/markdown",
        filename=f"chat_{session_id[:8]}.md"
    )

# File Upload Endpoints
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file to the uploads directory."""
    try:
        # Validate file size before reading
        file_size = 0
        chunk_size = 1024 * 1024  # 1MB chunks
        chunks = []
        
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            file_size += len(chunk)
            if file_size > MAX_FILE_SIZE:
                return JSONResponse(
                    status_code=413,
                    content={"error": f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB"}
                )
            chunks.append(chunk)
        
        # Secure the filename
        safe_name = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{safe_name}"
        file_path = UPLOADS_DIR / safe_filename
        
        # Ensure the resolved path is within UPLOADS_DIR (prevent path traversal)
        resolved_path = file_path.resolve()
        resolved_uploads = UPLOADS_DIR.resolve()
        if not str(resolved_path).startswith(str(resolved_uploads)):
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid filename"}
            )
        
        # Write file
        with open(file_path, "wb") as buffer:
            for chunk in chunks:
                buffer.write(chunk)
        
        return {
            "filename": safe_filename,
            "original_name": file.filename,
            "path": str(file_path),
            "size": file_size
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.get("/api/uploads")
async def list_uploads():
    """List all uploaded files."""
    files = []
    for file_path in UPLOADS_DIR.iterdir():
        if file_path.is_file():
            stat = file_path.stat()
            files.append({
                "filename": file_path.name,
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat()
            })
    return {"files": sorted(files, key=lambda x: x["created"], reverse=True)}

# Theme Settings
@app.get("/api/settings/theme")
async def get_theme():
    """Get current theme setting."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', ('theme',))
    row = cursor.fetchone()
    conn.close()
    return {"theme": row["value"] if row else "dark"}

@app.post("/api/settings/theme")
async def set_theme(request: Request):
    """Set theme setting."""
    data = await request.json()
    theme = data.get("theme", "dark")
    
    if theme not in ["dark", "light"]:
        raise HTTPException(status_code=400, detail="Theme must be 'dark' or 'light'")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)
    ''', ('theme', theme))
    conn.commit()
    conn.close()
    
    return {"theme": theme}

# WebSocket for real-time chat with streaming
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    # Validate session_id format
    try:
        uuid.UUID(session_id)
    except ValueError:
        await websocket.close(code=4000, reason="Invalid session ID format")
        return
    
    await websocket.accept()
    connected_clients[session_id] = websocket
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            if message_data.get("type") == "chat":
                content = message_data.get("content", "").strip()
                personality = sanitize_input(message_data.get("personality", "helpful"))
                model = message_data.get("model")
                stream = message_data.get("stream", False)
                
                # Validate inputs
                if not content:
                    await websocket.send_json({
                        "type": "error",
                        "content": "Message cannot be empty",
                    })
                    continue
                
                if model and model != "default" and not validate_model_name(model):
                    model = "default"
                
                conn = get_db()
                cursor = conn.cursor()
                
                # Check if first message for auto-naming
                cursor.execute('SELECT COUNT(*) as count FROM messages WHERE session_id = ?', (session_id,))
                msg_count = cursor.fetchone()["count"]
                
                if msg_count == 0:
                    # Get current session name
                    cursor.execute('SELECT name FROM sessions WHERE id = ?', (session_id,))
                    session_row = cursor.fetchone()
                    if session_row and (session_row["name"].startswith("Chat ") or session_row["name"] == "New Chat"):
                        new_title = await generate_chat_title(content)
                        cursor.execute('UPDATE sessions SET name = ? WHERE id = ?', (new_title, session_id))
                        conn.commit()
                        await websocket.send_json({
                            "type": "session_name_update",
                            "name": new_title
                        })
                
                now = datetime.now().isoformat()
                
                # Save user message
                cursor.execute('''
                    INSERT INTO messages (session_id, role, content, timestamp)
                    VALUES (?, ?, ?, ?)
                ''', (session_id, "user", content, now))
                conn.commit()
                
                try:
                    cmd = ["hermes", "chat", "-Q", "-q", content]
                    if model and model != "default" and not model.startswith('__'):
                        cli_provider, cli_model = resolve_model_for_cli(model)
                        if cli_provider:
                            cmd.extend(["--provider", cli_provider])
                        if cli_model and validate_model_name(cli_model):
                            cmd.extend(["--model", cli_model])
                    
                    if stream:
                        # Streaming mode
                        env = dict(os.environ, PYTHONUNBUFFERED="1")
                        process = await asyncio.create_subprocess_exec(
                            *cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            env=env
                        )
                        
                        full_response = ""
                        buffer = ""
                        word_buffer = []
                        
                        await websocket.send_json({"type": "stream_start"})
                        
                        while True:
                            line = await process.stdout.readline()
                            if not line:
                                break
                            
                            decoded = apply_ansi_strip(line.decode('utf-8', errors='replace'))
                            if not decoded:
                                continue
                            buffer += decoded + ' '
                            
                            words = buffer.split(' ')
                            buffer = words[-1]
                            
                            for word in words[:-1]:
                                word_buffer.append(word)
                                full_response += word + ' '
                                
                                if len(word_buffer) >= 2:
                                    text_to_send = ' '.join(word_buffer)
                                    await websocket.send_json({
                                        "type": "stream_token",
                                        "token": text_to_send + ' '
                                    })
                                    word_buffer = []
                                    await asyncio.sleep(0.01)
                        
                        await process.wait()
                        
                        if word_buffer or buffer:
                            remaining = ' '.join(word_buffer) + (' ' if word_buffer else '') + buffer
                            full_response += remaining
                            await websocket.send_json({
                                "type": "stream_token",
                                "token": remaining
                            })
                        
                        if process.returncode != 0:
                            stderr = await process.stderr.read()
                            error_msg = stderr.decode('utf-8', errors='replace').strip() or 'Unknown error'
                            full_response = f"Error from Hermes CLI: {error_msg}"
                            await websocket.send_json({
                                "type": "stream_token",
                                "token": full_response
                            })
                        
                        # Save to database
                        now = datetime.now().isoformat()
                        cursor.execute('''
                            INSERT INTO messages (session_id, role, content, timestamp)
                            VALUES (?, ?, ?, ?)
                        ''', (session_id, "assistant", full_response.strip(), now))
                        cursor.execute('''
                            UPDATE sessions SET updated_at = ? WHERE id = ?
                        ''', (now, session_id))
                        conn.commit()
                        
                        await websocket.send_json({
                            "type": "stream_end",
                            "timestamp": now
                        })
                        
                    else:
                        # Non-streaming mode
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=120,
                            env=dict(os.environ, PYTHONUNBUFFERED="1")
                        )
                        
                        if result.returncode == 0:
                            response = apply_ansi_strip(result.stdout)
                        else:
                            response = f"Error: {result.stderr.strip() or 'Unknown error'}"
                        
                        # Save to database
                        now = datetime.now().isoformat()
                        cursor.execute('''
                            INSERT INTO messages (session_id, role, content, timestamp)
                            VALUES (?, ?, ?, ?)
                        ''', (session_id, "assistant", response, now))
                        cursor.execute('''
                            UPDATE sessions SET updated_at = ? WHERE id = ?
                        ''', (now, session_id))
                        conn.commit()
                        
                        await websocket.send_json({
                            "type": "response",
                            "content": response,
                            "timestamp": now,
                        })
                        
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "content": f"Error: {str(e)}",
                    })
                finally:
                    conn.close()
                
    except WebSocketDisconnect:
        if session_id in connected_clients:
            del connected_clients[session_id]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
