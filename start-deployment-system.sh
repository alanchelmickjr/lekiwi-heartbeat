#!/bin/bash

# LeKiwi Deployment System Startup Script
# This script starts the deployment server with web GUI

set -e

# Parse arguments
DEV_MODE=false
LOG_LEVEL="error"
RELOAD_FLAG=""

for arg in "$@"; do
    case $arg in
        --dev)
            DEV_MODE=true
            LOG_LEVEL="info"
            RELOAD_FLAG="--reload"
            shift
            ;;
        --help)
            echo "Usage: $0 [--dev] [--help]"
            echo "  --dev    Enable development mode with verbose logging"
            echo "  --help   Show this help message"
            exit 0
            ;;
    esac
done

# Colors for output (only if not in production mode)
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Only show banner in dev mode
if [ "$DEV_MODE" = true ]; then
    echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║        🚀 LeKiwi Deployment System Startup 🚀         ║${NC}"
    echo -e "${BLUE}║                  DEVELOPMENT MODE                      ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""
else
    # Minimal production output
    echo -e "${GREEN}Starting LeKiwi Deployment System...${NC}"
fi

# Create necessary directories (silent unless dev mode)
LOCAL_DEPLOY_DIR="$HOME/.lekiwi-deploy"
mkdir -p "$LOCAL_DEPLOY_DIR"/{deployments,packages,repos,logs} 2>/dev/null
mkdir -p deployment-server/static 2>/dev/null

if [ "$DEV_MODE" = true ]; then
    # Check if running on Mac
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo -e "${GREEN}✓${NC} Running on macOS"
    else
        echo -e "${YELLOW}⚠${NC} Warning: This system is optimized for macOS"
    fi
    
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
    
    echo -e "${BLUE}Installing Python dependencies...${NC}"
else
    # Silent dependency checks and installation
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}Error: Python3 not found${NC}"
        exit 1
    fi
    
    if ! command -v sshpass &> /dev/null; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            brew install hudochenkov/sshpass/sshpass &>/dev/null
        else
            sudo apt-get install -y sshpass &>/dev/null
        fi
    fi
fi

# Install Python dependencies (always quiet)
pip3 install -q fastapi uvicorn aiohttp pydantic 2>/dev/null || {
    pip3 install --user -q fastapi uvicorn aiohttp pydantic 2>/dev/null
}

# Copy deployment scripts to local directory (silent)
if [ -d "deployment-master" ]; then
    cp -r deployment-master "$LOCAL_DEPLOY_DIR/" 2>/dev/null
fi

# Environment variables
export DEPLOY_PORT=8000
export DEPLOYMENTS_DIR="$LOCAL_DEPLOY_DIR/deployments"
export PACKAGES_DIR="$LOCAL_DEPLOY_DIR/packages"
export REPOS_DIR="$LOCAL_DEPLOY_DIR/repos"
export GITHUB_REPO="https://github.com/huggingface/lerobot.git"

# Check if server is already running
if lsof -i:8000 &> /dev/null; then
    if [ "$DEV_MODE" = true ]; then
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
    else
        # In production, silently kill the old process
        kill $(lsof -t -i:8000) 2>/dev/null || true
        sleep 1
    fi
fi

# Start the deployment server
if [ "$DEV_MODE" = true ]; then
    echo -e "${GREEN}Starting LeKiwi Deployment Server...${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "🌐 Web Dashboard: ${GREEN}http://localhost:8000${NC}"
    echo -e "📡 API Endpoint: ${GREEN}http://localhost:8000/api${NC}"
    echo -e "📊 Health Check: ${GREEN}http://localhost:8000/health${NC}"
    echo ""
    echo -e "🤖 Known Robots:"
    echo -e "   • ${YELLOW}192.168.88.21${NC} (lekiwi_67222140)"
    echo -e "   • ${YELLOW}192.168.88.57${NC} (lekiwi_67223052)"
    echo -e "   • ${YELLOW}192.168.88.58${NC} (lekiwi_672230e8)"
    echo -e "   • ${YELLOW}192.168.88.62${NC} (lekiwi_6722309c)"
    echo -e "   • ${YELLOW}192.168.88.64${NC} (lekiwi_672230be)"
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}Press Ctrl+C to stop the server${NC}"
    echo ""
else
    # Minimal production output
    echo -e "${GREEN}🚀 LeKiwi Server: http://localhost:8000${NC}"
    echo -e "${GREEN}Press Ctrl+C to stop${NC}"
fi

# Run the server
cd deployment-server
python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 $RELOAD_FLAG --log-level $LOG_LEVEL