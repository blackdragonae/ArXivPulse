#!/bin/bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8001}"

echo "Checking ${BASE_URL}..."
curl -fsS "${BASE_URL}/health" >/dev/null
curl -fsS "${BASE_URL}/api/papers?status=new&limit=1" >/dev/null
curl -fsS "${BASE_URL}/api/search?q=test&mode=keyword&limit=1" >/dev/null

echo "OK - health, papers, search all responded."
