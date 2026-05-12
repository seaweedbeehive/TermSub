#!/bin/bash
#
# setup_env.sh - TermSub Environment Setup Script
#
# This script synchronizes the virtual environment with the locked
# dependencies in requirements.txt. Run this after pulling new code
# or when encountering dependency issues.
#

set -e  # Exit on any error

echo "=============================================="
echo "  TermSub Environment Sync"
echo "=============================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check Python version
echo -e "${BLUE}▶ Checking Python version...${NC}"
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "  Found Python $PYTHON_VERSION"

# Verify Python 3.11+ (required for some dependencies)
REQUIRED_VERSION="3.11"
CURRENT_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$CURRENT_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo -e "${RED}✗ Python 3.11+ is required (found $CURRENT_VERSION)${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ Python version OK${NC}"
echo ""

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "${BLUE}▶ Creating virtual environment...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}  ✓ Virtual environment created${NC}"
else
    echo -e "${BLUE}▶ Virtual environment exists${NC}"
fi
echo ""

# Activate virtual environment
echo -e "${BLUE}▶ Activating virtual environment...${NC}"
source venv/bin/activate
echo -e "${GREEN}  ✓ Activated$(which python)${NC}"
echo ""

# Clear pip cache
echo -e "${BLUE}▶ Clearing pip cache...${NC}"
pip cache purge 2>/dev/null || echo "  (No cache to purge)"
echo -e "${GREEN}  ✓ Pip cache cleared${NC}"
echo ""

# Upgrade pip, setuptools, and wheel
echo -e "${BLUE}▶ Upgrading pip, setuptools, wheel...${NC}"
pip install --upgrade pip setuptools wheel -q
echo -e "${GREEN}  ✓ Build tools upgraded${NC}"
echo ""

# Install dependencies
echo -e "${BLUE}▶ Installing dependencies from requirements.txt...${NC}"
echo "  This may take a few minutes..."
echo ""

if pip install -r requirements.txt --no-cache-dir; then
    echo ""
    echo -e "${GREEN}  ✓ All dependencies installed successfully${NC}"
else
    echo ""
    echo -e "${RED}✗ Failed to install dependencies${NC}"
    exit 1
fi
echo ""

# Verify critical imports
echo -e "${BLUE}▶ Verifying critical imports...${NC}"

python3 << 'EOF'
import sys

def check_import(module_name, package_name=None):
    package_name = package_name or module_name
    try:
        __import__(module_name)
        print(f"  ✓ {package_name}")
        return True
    except ImportError as e:
        print(f"  ✗ {package_name}: {e}")
        return False

all_ok = True
all_ok &= check_import("fastapi")
all_ok &= check_import("starlette")
all_ok &= check_import("uvicorn")
all_ok &= check_import("sqlalchemy")
all_ok &= check_import("pydantic")
all_ok &= check_import("pydantic_settings", "pydantic-settings")
all_ok &= check_import("google.genai", "google-genai")
all_ok &= check_import("faster_whisper", "faster-whisper")
all_ok &= check_import("aiofiles")
all_ok &= check_import("jinja2")
all_ok &= check_import("dotenv", "python-dotenv")
all_ok &= check_import("httpx")
all_ok &= check_import("multipart", "python-multipart")

sys.exit(0 if all_ok else 1)
EOF

if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}✗ Import verification failed${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}  ✓ All critical imports verified${NC}"
echo ""

# Summary
echo "=============================================="
echo -e "${GREEN}  ✓ Environment sync complete!${NC}"
echo "=============================================="
echo ""
echo "To activate the environment, run:"
echo "  source venv/bin/activate"
echo ""
echo "To start the application:"
echo "  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
echo ""
