"""FastAPI app. Two audiences, two routers:
- /api/...      the analyst's workspace (api/workspace.py)
- /api/ops/...  the operations portal: runs, audit trails, failure drills, evaluation (api/ops.py)

    uv run uvicorn app.main:app --app-dir backend --port 8000
"""
from fastapi import FastAPI

from app.api import ops, workspace

app = FastAPI(title="Recall Match")
app.include_router(workspace.router, prefix="/api")
app.include_router(ops.router, prefix="/api")
