#!/bin/bash

# Create virtual environment for deployment server
echo "🔧 Setting up LeKiwi Deployment Server Environment..."

# Go to deployment-server directory
cd "$(dirname "$0")"

# Create virtual environment
echo "📦 Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
echo "⬆️ Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo "📚 Installing dependencies..."
pip install \
    fastapi \
    uvicorn[standard] \
    paramiko \
    pydantic \
    aiofiles \
    python-multipart \
    websockets \
    requests

echo "✅ Environment setup complete!"
echo ""
echo "To activate the environment, run:"
echo "  source deployment-server/venv/bin/activate"
echo ""
echo "To run the discovery script:"
echo "  python3 smart_discover.py"