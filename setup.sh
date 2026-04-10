#!/bin/bash
# ============================================================
# Gemma 4 Gateway — One-Click Setup
# Clone this repo, run: bash setup.sh
# ============================================================
set -e

echo ""
echo "  ⚡ Gemma 4 Gateway — Setup"
echo "  =========================="
echo ""

# === 1. Check GPU ===
if ! command -v nvidia-smi &> /dev/null; then
    echo "❌ nvidia-smi not found. Need NVIDIA GPU."
    exit 1
fi
GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
echo "✓ GPU: $GPU_NAME (${GPU_MEM}MB)"

# === 2. Install system deps ===
echo ""
echo "📦 Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3-pip python3-venv curl openssl > /dev/null 2>&1
echo "✓ System deps installed"

# === 3. Create venv & install Python deps ===
echo ""
echo "🐍 Setting up Python environment..."
python3 -m venv /opt/vllm-env
source /opt/vllm-env/bin/activate
pip install --upgrade pip > /dev/null 2>&1

echo "📥 Installing vLLM (this takes 5-10 min)..."
pip install vllm openai > /dev/null 2>&1
echo "✓ vLLM installed"

echo "📥 Upgrading transformers..."
pip install --upgrade transformers > /dev/null 2>&1
echo "✓ Transformers upgraded"

echo "📥 Installing Gateway deps..."
pip install -r requirements.txt > /dev/null 2>&1
echo "✓ Gateway deps installed"

# === 4. Setup .env ===
if [ ! -f .env ]; then
    cp .env.example .env
    VLLM_KEY="vllm-$(openssl rand -hex 16)"
    sed -i "s|VLLM_BASE_URL=.*|VLLM_BASE_URL=http://localhost:8000/v1|" .env
    echo "VLLM_API_KEY=$VLLM_KEY" >> .env
    echo "✓ .env created"
    echo ""
    echo "⚠️  Edit .env to set your ADMIN_PIN and HF_TOKEN:"
    echo "    nano .env"
    echo ""
else
    echo "✓ .env already exists"
    source .env
    VLLM_KEY=${VLLM_API_KEY:-""}
fi

# Read env
source .env
HF_TOKEN=${HF_TOKEN:-""}
VLLM_KEY=${VLLM_API_KEY:-""}

# === 5. Create systemd services ===
echo ""
echo "🔧 Creating systemd services..."

cat > /etc/systemd/system/vllm.service << VLLMEOF
[Unit]
Description=vLLM Gemma 4 31B Server
After=network.target

[Service]
Type=simple
User=root
Environment="PATH=/opt/vllm-env/bin:/usr/local/bin:/usr/bin:/bin"
Environment="HF_TOKEN=${HF_TOKEN}"
Environment="HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}"
ExecStart=/opt/vllm-env/bin/python -m vllm.entrypoints.openai.api_server \
    --model google/gemma-4-31B-it \
    --dtype bfloat16 \
    --kv-cache-dtype fp8 \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.95 \
    --host 0.0.0.0 \
    --port 8000 \
    --api-key ${VLLM_KEY} \
    --served-model-name gemma-4-31b \
    --trust-remote-code \
    --enforce-eager
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
VLLMEOF

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cat > /etc/systemd/system/gemma4-gateway.service << GWEOF
[Unit]
Description=Gemma 4 Gateway API
After=vllm.service

[Service]
Type=simple
User=root
WorkingDirectory=${SCRIPT_DIR}
Environment="PATH=/opt/vllm-env/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=${SCRIPT_DIR}/.env
ExecStart=/opt/vllm-env/bin/python app/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
GWEOF

systemctl daemon-reload
echo "✓ Services created"

# === 6. Start services ===
echo ""
echo "🚀 Starting vLLM (downloading model first time ~16GB)..."
systemctl enable vllm
systemctl start vllm

echo "🚀 Starting Gateway..."
systemctl enable gemma4-gateway
systemctl start gemma4-gateway

# === 7. Wait for vLLM ===
echo ""
echo "⏳ Waiting for vLLM to load model..."
for i in $(seq 1 180); do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo ""
        echo "✓ vLLM is READY!"
        break
    fi
    if [ $i -eq 180 ]; then
        echo ""
        echo "⚠️  vLLM not ready after 15 min. Check: journalctl -u vllm -f"
    fi
    sleep 5
    printf "\r  Loading... %ds" $((i*5))
done

# === 8. Done ===
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
GATEWAY_PORT=$(grep GATEWAY_PORT .env | cut -d= -f2)
ADMIN_PIN=$(grep ADMIN_PIN .env | cut -d= -f2)

echo ""
echo "============================================================"
echo "  ✅ SETUP COMPLETE!"
echo "============================================================"
echo ""
echo "  📡 Dashboard:  http://${PUBLIC_IP}:${GATEWAY_PORT}"
echo "  🔑 Admin PIN:  ${ADMIN_PIN}"
echo "  🤖 Model:      gemma-4-31b"
echo ""
echo "  📊 Commands:"
echo "    journalctl -u vllm -f            # vLLM logs"
echo "    journalctl -u gemma4-gateway -f   # Gateway logs"
echo "    systemctl restart vllm            # Restart model"
echo "    systemctl restart gemma4-gateway  # Restart gateway"
echo ""
echo "============================================================"
