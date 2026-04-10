"""
Gemma 4 Gateway — FastAPI Backend
API Gateway with key management, usage tracking, and admin dashboard.
"""
import os
import json
import time
import uuid
import hashlib
import httpx
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# === Configuration ===
ADMIN_PIN = os.getenv("ADMIN_PIN", "123456")
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gemma-4-26b-a4b")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "3000"))
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
KEYS_FILE = DATA_DIR / "api_keys.json"
LOGS_FILE = DATA_DIR / "usage_logs.json"

# Internal vLLM API key (read from vLLM's config)
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "")

app = FastAPI(title="Gemma 4 Gateway", docs_url=None, redoc_url=None)

# === Data Management ===
def load_keys() -> dict:
    if KEYS_FILE.exists():
        return json.loads(KEYS_FILE.read_text())
    return {}

def save_keys(keys: dict):
    KEYS_FILE.write_text(json.dumps(keys, indent=2, ensure_ascii=False))

def load_logs() -> list:
    if LOGS_FILE.exists():
        return json.loads(LOGS_FILE.read_text())
    return []

def save_log(entry: dict):
    logs = load_logs()
    logs.append(entry)
    # Keep last 1000 logs
    if len(logs) > 1000:
        logs = logs[-1000:]
    LOGS_FILE.write_text(json.dumps(logs, indent=2, ensure_ascii=False))


# === Models ===
class CreateKeyRequest(BaseModel):
    name: str
    rate_limit: int = 60  # requests per minute

class ChatRequest(BaseModel):
    model: str = MODEL_NAME
    messages: list
    temperature: float = 0.7
    max_tokens: int = 2048
    stream: bool = False

class AdminAuth(BaseModel):
    pin: str


# === Admin Auth ===
def verify_admin(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(401, "Missing authorization")
    pin = authorization.replace("Bearer ", "").replace("Admin ", "")
    if pin != ADMIN_PIN:
        raise HTTPException(403, "Invalid admin PIN")
    return True


def verify_api_key(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(401, "Missing API key. Use: Authorization: Bearer gm4-xxx")
    key = authorization.replace("Bearer ", "")
    keys = load_keys()
    if key not in keys:
        raise HTTPException(403, "Invalid API key")
    key_data = keys[key]
    if not key_data.get("active", True):
        raise HTTPException(403, "API key is disabled")
    # Update usage
    key_data["last_used"] = datetime.now().isoformat()
    key_data["total_requests"] = key_data.get("total_requests", 0) + 1
    keys[key] = key_data
    save_keys(keys)
    return key_data


# === Admin Endpoints ===
@app.post("/api/admin/login")
async def admin_login(auth: AdminAuth):
    if auth.pin != ADMIN_PIN:
        raise HTTPException(403, "Wrong PIN")
    return {"success": True, "message": "Login successful"}


@app.get("/api/admin/keys")
async def list_keys(admin=Depends(verify_admin)):
    keys = load_keys()
    result = []
    for key, data in keys.items():
        result.append({
            "key": key[:12] + "..." + key[-4:],
            "full_key": key,
            "name": data["name"],
            "created": data["created"],
            "last_used": data.get("last_used", "Never"),
            "total_requests": data.get("total_requests", 0),
            "active": data.get("active", True),
            "rate_limit": data.get("rate_limit", 60),
        })
    return {"keys": result}


@app.post("/api/admin/keys")
async def create_key(req: CreateKeyRequest, admin=Depends(verify_admin)):
    key = f"gm4-{uuid.uuid4().hex[:32]}"
    keys = load_keys()
    keys[key] = {
        "name": req.name,
        "created": datetime.now().isoformat(),
        "rate_limit": req.rate_limit,
        "active": True,
        "total_requests": 0,
    }
    save_keys(keys)
    return {"key": key, "name": req.name}


@app.delete("/api/admin/keys/{key}")
async def delete_key(key: str, admin=Depends(verify_admin)):
    keys = load_keys()
    if key in keys:
        del keys[key]
        save_keys(keys)
        return {"success": True}
    raise HTTPException(404, "Key not found")


@app.patch("/api/admin/keys/{key}/toggle")
async def toggle_key(key: str, admin=Depends(verify_admin)):
    keys = load_keys()
    if key in keys:
        keys[key]["active"] = not keys[key].get("active", True)
        save_keys(keys)
        return {"active": keys[key]["active"]}
    raise HTTPException(404, "Key not found")


@app.get("/api/admin/logs")
async def get_logs(admin=Depends(verify_admin)):
    logs = load_logs()
    return {"logs": logs[-100:]}  # Last 100


@app.get("/api/admin/stats")
async def get_stats(admin=Depends(verify_admin)):
    keys = load_keys()
    logs = load_logs()
    total_requests = sum(k.get("total_requests", 0) for k in keys.values())
    active_keys = sum(1 for k in keys.values() if k.get("active", True))
    
    # GPU status
    gpu_info = {"status": "unknown"}
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            gpu_info = {
                "name": parts[0],
                "memory_used": f"{parts[1]} MB",
                "memory_total": f"{parts[2]} MB",
                "temperature": f"{parts[3]}°C",
                "utilization": f"{parts[4]}%",
                "status": "online"
            }
    except:
        pass
    
    # vLLM health
    vllm_status = "offline"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{VLLM_BASE_URL.replace('/v1','')}/health")
            if r.status_code == 200:
                vllm_status = "online"
    except:
        pass
    
    return {
        "total_keys": len(keys),
        "active_keys": active_keys,
        "total_requests": total_requests,
        "recent_logs": len(logs),
        "gpu": gpu_info,
        "vllm_status": vllm_status,
        "model": MODEL_NAME,
    }


# === OpenAI-Compatible API Endpoints ===
@app.get("/v1/models")
async def list_models(key_data=Depends(verify_api_key)):
    return {
        "object": "list",
        "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "gemma4-gateway"}]
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, key_data=Depends(verify_api_key)):
    body = await request.json()
    body["model"] = MODEL_NAME  # Force correct model name
    
    start_time = time.time()
    
    headers = {"Content-Type": "application/json"}
    if VLLM_API_KEY:
        headers["Authorization"] = f"Bearer {VLLM_API_KEY}"
    
    is_stream = body.get("stream", False)
    
    try:
        if is_stream:
            async def stream_generator():
                async with httpx.AsyncClient(timeout=120) as client:
                    async with client.stream(
                        "POST",
                        f"{VLLM_BASE_URL}/chat/completions",
                        json=body,
                        headers=headers,
                    ) as response:
                        async for chunk in response.aiter_bytes():
                            yield chunk
                
                # Log after stream completes
                save_log({
                    "time": datetime.now().isoformat(),
                    "user": key_data["name"],
                    "model": MODEL_NAME,
                    "type": "stream",
                    "latency": f"{time.time() - start_time:.2f}s",
                })
            
            return StreamingResponse(stream_generator(), media_type="text/event-stream")
        else:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{VLLM_BASE_URL}/chat/completions",
                    json=body,
                    headers=headers,
                )
            
            latency = time.time() - start_time
            result = response.json()
            
            # Log usage
            tokens = result.get("usage", {})
            save_log({
                "time": datetime.now().isoformat(),
                "user": key_data["name"],
                "model": MODEL_NAME,
                "prompt_tokens": tokens.get("prompt_tokens", 0),
                "completion_tokens": tokens.get("completion_tokens", 0),
                "latency": f"{latency:.2f}s",
            })
            
            return JSONResponse(content=result, status_code=response.status_code)
    
    except httpx.ConnectError:
        raise HTTPException(503, "vLLM server is not running. Start it first.")
    except httpx.ReadTimeout:
        raise HTTPException(504, "Model response timed out")
    except Exception as e:
        raise HTTPException(500, f"Gateway error: {str(e)}")


# === Playground Test (no auth needed, uses admin PIN) ===
@app.post("/api/playground/chat")
async def playground_chat(request: Request):
    body = await request.json()
    admin_pin = body.pop("admin_pin", "")
    if admin_pin != ADMIN_PIN:
        raise HTTPException(403, "Invalid admin PIN")
    
    body["model"] = MODEL_NAME
    
    headers = {"Content-Type": "application/json"}
    if VLLM_API_KEY:
        headers["Authorization"] = f"Bearer {VLLM_API_KEY}"
    
    try:
        is_stream = body.get("stream", False)
        
        if is_stream:
            async def stream_gen():
                async with httpx.AsyncClient(timeout=120) as client:
                    async with client.stream(
                        "POST",
                        f"{VLLM_BASE_URL}/chat/completions",
                        json=body,
                        headers=headers,
                    ) as response:
                        async for chunk in response.aiter_bytes():
                            yield chunk
            
            return StreamingResponse(stream_gen(), media_type="text/event-stream")
        else:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{VLLM_BASE_URL}/chat/completions",
                    json=body,
                    headers=headers,
                )
            return JSONResponse(content=response.json(), status_code=response.status_code)
    except httpx.ConnectError:
        raise HTTPException(503, "vLLM server is not running")
    except Exception as e:
        raise HTTPException(500, str(e))


# === Serve Frontend ===
app.mount("/", StaticFiles(directory=str(Path(__file__).parent / "static"), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    print(f"\n🚀 Gemma 4 Gateway starting on port {GATEWAY_PORT}")
    print(f"📡 vLLM backend: {VLLM_BASE_URL}")
    print(f"🔑 Admin PIN: {ADMIN_PIN}\n")
    uvicorn.run(app, host="0.0.0.0", port=GATEWAY_PORT)
