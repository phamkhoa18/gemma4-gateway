#!/bin/bash
# ============================================================
# Gemma 4 PM2 Gateway Setup (Model 26B A4B - Nhanh & Mượt)
# ============================================================
set -e

echo ""
echo "  ⚡ Gemma 4 Gateway (PM2) — Setup"
echo "  =========================="
echo ""

# === 1. Install system deps ===
echo "📦 Installing system dependencies (Node.js & PM2)..."
apt-get update -qq
apt-get install -y -qq python3-pip python3-venv curl openssl > /dev/null 2>&1

if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null 2>&1
    apt-get install -y nodejs > /dev/null 2>&1
fi

if ! command -v pm2 &> /dev/null; then
    npm install -g pm2 > /dev/null 2>&1
fi
echo "✓ Node.js & PM2 installed"

# === 2. Create venv & install Python deps ===
echo ""
echo "🐍 Setting up Python environment..."
python3 -m venv /opt/vllm-env
source /opt/vllm-env/bin/activate
pip install --upgrade pip > /dev/null 2>&1

echo "📥 Installing vLLM & Transformers..."
pip install vllm openai > /dev/null 2>&1
pip install --upgrade transformers > /dev/null 2>&1
echo "✓ vLLM installed"

echo "📥 Installing Gateway deps..."
pip install -r requirements.txt > /dev/null 2>&1
echo "✓ Gateway deps installed"

# === 3. Setup .env ===
if [ ! -f .env ]; then
    cp .env.example .env
    VLLM_KEY="vllm-$(openssl rand -hex 16)"
    sed -i "s|VLLM_BASE_URL=.*|VLLM_BASE_URL=http://localhost:8000/v1|" .env
    sed -i "s|MODEL_NAME=.*|MODEL_NAME=gemma-4-26b-a4b|" .env
    echo "VLLM_API_KEY=$VLLM_KEY" >> .env
else
    source .env
    VLLM_KEY=${VLLM_API_KEY:-""}
fi

# HuggingFace token from .env
source .env
HF_TOKEN=${HF_TOKEN:-""}

# Fix token in PM2 config dynamically
sed -i "s|HUGGING_FACE_HUB_TOKEN=.*|HUGGING_FACE_HUB_TOKEN=\"${HF_TOKEN}\"|g" ecosystem.config.js || true

echo "✓ Environment ready"

# === 4. Start services with PM2 ===
echo ""
echo "🚀 Starting vLLM and Gateway with PM2..."

# Stop any dangling processes
systemctl stop vllm 2>/dev/null || true
systemctl stop gemma4-gateway 2>/dev/null || true
pm2 delete all 2>/dev/null || true

# Important: inject HF Token into environment
export HF_TOKEN=$HF_TOKEN
export HUGGING_FACE_HUB_TOKEN=$HF_TOKEN

pm2 start ecosystem.config.js
pm2 save
pm2 startup | grep "sudo pm2" | bash || true

echo ""
echo "⏳ Waiting for vLLM to load model (~3-5 mins)..."
for i in $(seq 1 60); do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo ""
        echo "✓ vLLM is READY!"
        break
    fi
    sleep 5
    printf "\r  Loading... %ds" $((i*5))
done

# === 5. Done ===
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
echo "  🤖 Model:      gemma-4-26b-a4b"
echo ""
echo "  📊 PM2 Commands:"
echo "    pm2 status          # Xem trạng thái chạy"
echo "    pm2 logs            # Xem toàn bộ server log"
echo "    pm2 logs vllm-model # Xem log của model AI"
echo "    pm2 restart all     # Restart lại toàn bộ"
echo ""
echo "============================================================"
