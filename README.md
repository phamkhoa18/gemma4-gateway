# Gemma 4 Gateway

AI API Gateway for Gemma 4 31B with admin dashboard, API key management, and chat playground.

## Features
- 🎨 Premium admin dashboard (TailwindCSS)
- 🔑 API key creation & management
- 💬 Chat playground to test the model
- 📊 GPU monitoring & usage logs
- 🔒 PIN-based admin authentication
- 📖 Auto-generated API documentation
- 🔄 OpenAI-compatible API (`/v1/chat/completions`)

## Quick Start

### 1. Clone & Configure
```bash
git clone https://github.com/YOUR_USER/gemma4-gateway.git
cd gemma4-gateway
cp .env.example .env
nano .env  # Set ADMIN_PIN and HF_TOKEN
```

### 2. Run Setup
```bash
bash setup.sh
```

### 3. Open Dashboard
```
http://YOUR_SERVER_IP:3000
```

## API Usage

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://YOUR_SERVER_IP:3000/v1",
    api_key="gm4-your-api-key"  # Get from dashboard
)

response = client.chat.completions.create(
    model="gemma-4-31b",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

## Requirements
- NVIDIA GPU (32GB+ VRAM recommended)
- Ubuntu 22.04+
- Python 3.10+
- CUDA 12.0+

## Architecture
```
Client → Gateway (port 3000) → vLLM (port 8000) → GPU
             ↓
      API Key Auth + Logging
```
