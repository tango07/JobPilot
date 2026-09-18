#!/bin/bash
# JobPilot — Start the app
set -e

# Check setup was run
if [ ! -d "venv" ]; then
  echo "→  Running setup first…"
  bash setup.sh
fi

source venv/bin/activate
PORT=${PORT:-8765}

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   JobPilot is starting…              ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "   Open in browser:  http://127.0.0.1:${PORT}"
echo "   Press Ctrl+C to stop."
echo ""

cd backend
PORT="${PORT}" python app.py
