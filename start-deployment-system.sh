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

# Clean up hung services and stale files
if [ "$DEV_MODE" = true ]; then
    echo -e "${BLUE}Cleaning up previous sessions...${NC}"
else
    echo -e "${YELLOW}Cleaning up...${NC}"
fi

# Kill any hung uvicorn/python processes from previous runs (force with -9)
pkill -9 -f "uvicorn server:app" 2>/dev/null || true
pkill -9 -f "python.*server.py" 2>/dev/null || true
pkill -9 -f "python.*smart_discover.py" 2>/dev/null || true
pkill -9 -f "python3.*uvicorn" 2>/dev/null || true

# Clean up stale temp files (with proper permissions)
if [ -d "/tmp/robot_comparisons" ]; then
    if [ "$DEV_MODE" = true ]; then
        echo -e "${YELLOW}Cleaning up /tmp/robot_comparisons...${NC}"
    fi
    sudo rm -rf /tmp/robot_comparisons 2>/dev/null || rm -rf /tmp/robot_comparisons 2>/dev/null || true
fi

# Don't delete discovery files - we need them to detect all robots!
# Only clean up if explicitly requested via --clean-discovery flag
if [[ "$*" == *"--clean-discovery"* ]]; then
    if [ "$DEV_MODE" = true ]; then
        echo -e "${YELLOW}Cleaning discovery files as requested...${NC}"
    fi
    rm -f /tmp/discovery_results.json 2>/dev/null || true
    rm -f /tmp/smart_discovered.txt 2>/dev/null || true
    rm -f /tmp/discovered_robots.txt 2>/dev/null || true
    rm -f /tmp/lekiwi_fleet.json 2>/dev/null || true
    rm -f /tmp/robot_types.json 2>/dev/null || true
fi

# Run discovery if fleet file doesn't exist
if [ ! -f "/tmp/lekiwi_fleet.json" ]; then
    if [ "$DEV_MODE" = true ]; then
        echo -e "${BLUE}Fleet configuration not found. Running robot discovery...${NC}"
    else
        echo -e "${GREEN}Discovering robots...${NC}"
    fi
    
    # Run smart discovery to find all robots
    cd deployment-server
    python3 smart_discover.py 2>/dev/null || {
        if [ "$DEV_MODE" = true ]; then
            echo -e "${YELLOW}⚠ Discovery failed, retrying with full output...${NC}"
            python3 smart_discover.py
        fi
    }
    
    # Convert discovery results to fleet configuration
    if [ -f "/tmp/smart_discovered.txt" ]; then
        python3 add_discovered_robots.py 2>/dev/null || {
            if [ "$DEV_MODE" = true ]; then
                echo -e "${YELLOW}⚠ Fleet conversion failed${NC}"
            fi
        }
    fi
    
    # Return to parent directory
    cd ..
    
    if [ -f "/tmp/lekiwi_fleet.json" ]; then
        if [ "$DEV_MODE" = true ]; then
            ROBOT_COUNT=$(python3 -c "import json; print(json.load(open('/tmp/lekiwi_fleet.json'))['total'])" 2>/dev/null || echo "0")
            echo -e "${GREEN}✓${NC} Discovered $ROBOT_COUNT robots"
        fi
    else
        if [ "$DEV_MODE" = true ]; then
            echo -e "${YELLOW}⚠${NC} No robots discovered, will use defaults"
        fi
    fi
fi

# Create fresh directories
mkdir -p /tmp/robot_comparisons 2>/dev/null || true

# Check if server is already running on port 8000 and kill it
# Use both lsof and fuser for better compatibility
if lsof -i:8000 &> /dev/null; then
    if [ "$DEV_MODE" = true ]; then
        echo -e "${YELLOW}⚠${NC} Port 8000 is already in use"
        echo -e "Kill existing process? (y/n)"
        read -r response
        if [[ "$response" == "y" ]]; then
            # Force kill all processes on port 8000
            lsof -ti:8000 | xargs kill -9 2>/dev/null || true
            fuser -k 8000/tcp 2>/dev/null || true
            sleep 2
        else
            echo -e "${RED}Exiting...${NC}"
            exit 1
        fi
    else
        # In production, forcefully kill all processes on port 8000
        echo -e "${YELLOW}Cleaning up port 8000...${NC}"
        lsof -ti:8000 | xargs kill -9 2>/dev/null || true
        fuser -k 8000/tcp 2>/dev/null || true
        sleep 2
    fi
fi

# Double check the port is free
if lsof -i:8000 &> /dev/null; then
    echo -e "${RED}Failed to free port 8000. Please manually kill the process:${NC}"
    echo -e "${YELLOW}  sudo lsof -ti:8000 | xargs kill -9${NC}"
    exit 1
fi

# Clean up any hung SSH processes to robots
for ip in 21 57 58 62 64; do
    pkill -f "ssh.*192.168.88.$ip" 2>/dev/null || true
done

if [ "$DEV_MODE" = true ]; then
    echo -e "${GREEN}✓${NC} Cleanup complete"
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
    echo -e "   • ${YELLOW}192.168.88.21${NC} (offline)"
    echo -e "   • ${YELLOW}192.168.88.57${NC} (xlerobot1 - ${RED}Bimanual/3-cam${NC})"
    echo -e "   • ${YELLOW}192.168.88.58${NC} (lekiwi5)"
    echo -e "   • ${YELLOW}192.168.88.62${NC} (lekiwi5)"
    echo -e "   • ${YELLOW}192.168.88.64${NC} (lekiwi5)"
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