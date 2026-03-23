#!/usr/bin/env bash
set -euo pipefail

echo "=== Concerto TSS Demo ==="
echo ""

# 1. Start PostgreSQL
echo "[1/5] Starting PostgreSQL..."
docker compose up -d postgres
echo "Waiting for PostgreSQL to be ready..."
until docker compose exec postgres pg_isready -U concerto > /dev/null 2>&1; do
    sleep 1
done
echo "PostgreSQL ready."
echo ""

# 2. Start controller
echo "[2/5] Starting controller..."
uv run concerto-controller &
CONTROLLER_PID=$!
sleep 3
echo "Controller running (PID $CONTROLLER_PID)."
echo ""

# 3. Submit a batch of jobs
echo "[3/5] Submitting test jobs..."
for product in vehicle_gateway asset_gateway environmental_monitor vehicle_gateway asset_gateway; do
    curl -s -X POST http://localhost:8000/jobs \
        -H "Content-Type: application/json" \
        -d "{\"product\": \"$product\"}" | python3 -c "import sys,json; j=json.load(sys.stdin); print(f'  Job {j[\"id\"][:8]}... ({j[\"product\"]})')"
done
echo ""

# 4. Launch chaos simulator
echo "[4/5] Launching chaos simulator (5 agents, medium chaos)..."
uv run concerto-chaos --agents 5 --chaos-level medium &
CHAOS_PID=$!
echo "Chaos simulator running (PID $CHAOS_PID)."
echo ""

# 5. Launch TUI dashboard
echo "[5/5] Opening TUI dashboard..."
echo "Press 'q' in the dashboard to quit, then Ctrl+C to stop everything."
echo ""
uv run concerto-dashboard

# Cleanup on exit
echo ""
echo "Shutting down..."
kill $CHAOS_PID 2>/dev/null || true
kill $CONTROLLER_PID 2>/dev/null || true
docker compose down
echo "Done."
