# ArXiv Pulse

ArXiv Pulse is a local-first research inbox for arXiv papers.
It fetches daily papers, ranks and enriches them, and serves an interactive FastAPI + frontend workspace for triage, review, and synthesis.

## Highlights

- Daily arXiv fetch + local library storage (SQLite)
- Search modes: local keyword, semantic/vector, and global arXiv search
- Triage states (`new`, `liked`, `dismissed`, bookmarks) with inbox automation
- AI-assisted workflows (structure extraction, synthesis, digests, ranking support)
- Reading plan, follow-ups, alerts, and unified inbox views
- Export/share utilities and version-update tracking

## Tech Stack

- Backend: Python, FastAPI, Uvicorn
- Storage: SQLite
- Frontend: Vanilla JS/CSS/HTML
- ML/AI utilities: scikit-learn + local/remote AI service integrations in `arxivc/ai_service.py`

## Quick Start

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
./run_server.sh
```

Alternative:

```bash
.venv/bin/uvicorn arxivc.server:app --reload --host 0.0.0.0 --port 8001
```

4. Open:

`http://localhost:8001`

## Validation Commands

- Smoke checks:

```bash
make smoke
```

- Full validation (Python compile + JS syntax + smoke):

```bash
make validate
```

- Hot-path profiling:

```bash
make profile
```

## Project Layout

```text
arxivc/                 # Backend services, API routes, storage, ranking, exports
frontend/               # Web UI (app.js, style.css, index.html)
scripts/                # Smoke tests and profiling scripts
run_server.sh           # Local dev server launcher
Makefile                # Smoke/profile/validate helpers
```

## CI

GitHub Actions is configured in `.github/workflows/ci.yml` to run on push and pull requests to `main`:

- dependency install
- Python compile checks
- frontend JS syntax check
- API smoke suite
