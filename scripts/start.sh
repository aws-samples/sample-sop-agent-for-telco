#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# Quick start script for SOP Executor Web UI

echo "🚀 Starting SOP Executor Web UI..."

# Environment config
export BEDROCK_PROFILE="${BEDROCK_PROFILE:-default}"
export BEDROCK_REGION="${BEDROCK_REGION:-us-west-2}"

# Navigate to webui directory
cd "$(dirname "$0")/../webui" || exit 1

# Check if backend dependencies are installed
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "📦 Installing backend dependencies..."
    pip install -r backend/requirements.txt
fi

# Start backend
echo "🔧 Starting backend on port 8000..."
cd backend
python3 api.py &
BACKEND_PID=$!
cd ..

# Wait for backend to start
sleep 3

# Check if node_modules exists
if [ ! -d "frontend/node_modules" ]; then
    echo "📦 Installing frontend dependencies..."
    cd frontend
    npm install
    cd ..
fi

# Start frontend
echo "🎨 Starting frontend on port 3000..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "✅ Services started!"
echo "   Backend:  http://localhost:8000"
echo "   Frontend: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop all services"

# Trap Ctrl+C to kill both processes
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT

# Wait for both processes
wait
