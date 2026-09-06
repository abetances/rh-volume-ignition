#!/bin/bash
# Run RH Volume Ignition with dashboard

set -e

echo "=========================================="
echo "  🔥 RH Volume Ignition Launcher"
echo "=========================================="

# Safety check
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Assert project boundary
if [ -f ".rhvolume-boundary" ]; then
    echo "✓ Project boundary verified"
else
    echo "ERROR: Boundary file missing"
    exit 1
fi

# Check Python environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Activating environment..."
source venv/bin/activate

# Install flask if needed
pip install flask flask-cors --quiet 2>/dev/null || true

# Get port from env or default
PORT=${PORT:-5555}

echo ""
echo "Starting backend API on http://localhost:$PORT"
echo ""

# Start the app
python src/api/app.py &
API_PID=$!

# Wait for server to start
sleep 2

# Open browser only when explicitly requested.
if [ "${OPEN_BROWSER:-0}" = "1" ]; then
    if command -v xdg-open &> /dev/null; then
        echo "Opening browser..."
        xdg-open "http://localhost:$PORT" &
    elif command -v open &> /dev/null; then
        echo "Opening browser..."
        open "http://localhost:$PORT" &
    else
        echo "Browser auto-open not supported"
    fi
fi

echo ""
echo "=========================================="
echo "  🚀 Dashboard available at:"
echo ""
echo "     http://localhost:$PORT"
echo ""
echo "  Press Ctrl+C to stop"
echo "=========================================="

# Wait for interrupt
trap "kill $API_PID 2>/dev/null; exit" INT TERM

wait
