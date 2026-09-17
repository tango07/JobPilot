#!/bin/bash
# JobPilot — One-time setup script
set -e

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   JobPilot Setup                     ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Check Python 3.9+
if ! command -v python3 &>/dev/null; then
  echo "❌  Python 3.9+ is required. Install from https://python.org"
  exit 1
fi

PY_VER=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PY_VER" -lt 9 ]; then
  echo "❌  Python 3.9+ required (found 3.$PY_VER)"
  exit 1
fi

echo "✓  Python 3.$(python3 -c 'import sys; print(sys.version_info.minor)') found"

# Create virtual environment
if [ ! -d "venv" ]; then
  echo "→  Creating virtual environment…"
  python3 -m venv venv
fi

# Activate
source venv/bin/activate

# Install packages
echo "→  Installing dependencies…"
pip install -q -r requirements.txt

# Install Playwright browsers
echo "→  Installing Playwright browsers (this may take a moment)…"
playwright install chromium

echo ""
echo "✅  Setup complete!"
echo ""
echo "   To start JobPilot, run:  ./run.sh"
echo ""
