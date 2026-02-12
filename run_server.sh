#!/bin/bash
pkill -f uvicorn || true
sleep 1
.venv/bin/uvicorn arxivc.server:app --reload --host 0.0.0.0 --port 8001
