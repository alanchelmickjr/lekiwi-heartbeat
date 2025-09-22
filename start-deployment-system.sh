#!/bin/bash

# LeKiwi Deployment System Startup Script
# This script starts the deployment server with web GUI

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║        🚀 LeKiwi Deployment System Startup 🚀         ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if running on Mac
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo -e "${GREEN}✓${NC} Running on macOS"
else
    echo -e "${YELLOW}⚠${NC} Warning: This system is optimized for macOS"
fi

# Create necessary directories
echo -e "${BLUE}Creating directories...${NC}"
LOCAL_DEPLOY_DIR="$HOME/.lekiwi-deploy"
mkdir -p "$LOCAL_DEPLOY_DIR"/{deployments,packages,repos,logs}
mkdir -p deployment-server/static
echo -e "${GREEN}✓${NC} Using local directory: $LOCAL_DEPLOY_DIR"

# Check Python installation
if command -v python3 &> /dev/null; then
    echo -e "${GREEN}✓${NC} Python3 found: $(python3 --version)"
else
    echo -e "${RED}✗${NC} Python3 not found. Please install Python 3.8+"
    exit 1
fi

# Check sshpass installation
if command -v sshpass &> /dev/null; then
    echo -e "${GREEN}✓${NC} sshpass found"
else
    echo -e "${YELLOW}⚠${NC} sshpass not found. Installing..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install hudochenkov/sshpass/sshpass 2>/dev/null || echo "sshpass install failed"
    else
        sudo apt-get install -y sshpass 2>/dev/null || echo "sshpass install failed"
    fi
fi

# Install Python dependencies
echo -e "${BLUE}Installing Python dependencies...${NC}"
pip3 install -q fastapi uvicorn aiohttp pydantic 2>/dev/null || {
    echo -e "${YELLOW}Installing with --user flag...${NC}"
    pip3 install --user fastapi uvicorn aiohttp pydantic
}

# Copy deployment scripts to local directory
echo -e "${BLUE}Setting up deployment scripts...${NC}"
if [ -d "deployment-master" ]; then
    cp -r deployment-master "$LOCAL_DEPLOY_DIR/" 2>/dev/null || echo -e "${GREEN}✓${NC} Scripts copied"
fi

# Environment variables
export DEPLOY_PORT=8000
export DEPLOYMENTS_DIR="$LOCAL_DEPLOY_DIR/deployments"
export PACKAGES_DIR="$LOCAL_DEPLOY_DIR/packages"
export REPOS_DIR="$LOCAL_DEPLOY_DIR/repos"
export GITHUB_REPO="https://github.com/huggingface/lerobot.git"

# Check if server is already running
if lsof -i:8000 &> /dev/null; then
    echo -e "${YELLOW}⚠${NC} Port 8000 is already in use"
    echo -e "Kill existing process? (y/n)"
    read -r response
    if [[ "$response" == "y" ]]; then
        kill $(lsof -t -i:8000) 2>/dev/null || true
        sleep 2
    else
        echo -e "${RED}Exiting...${NC}"
        exit 1
    fi
fi

# Start the deployment server
echo -e "${GREEN}Starting LeKiwi Deployment Server...${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "🌐 Web Dashboard: ${GREEN}http://localhost:8000${NC}"
echo -e "📡 API Endpoint: ${GREEN}http://localhost:8000/api${NC}"
echo -e "📊 Health Check: ${GREEN}http://localhost:8000/health${NC}"
echo ""
echo -e "🤖 Known Robots:"
echo -e "   • ${YELLOW}192.168.88.21${NC} (lekiwi_67222140) - Working"
echo -e "   • ${YELLOW}192.168.88.57${NC} (lekiwi_67223052) - Fixed"
echo -e "   • ${YELLOW}192.168.88.64${NC} (Unknown) - Needs checking"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Press Ctrl+C to stop the server${NC}"
echo ""

# Run the server
cd deployment-server
python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload --log-level info