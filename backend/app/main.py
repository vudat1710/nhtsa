"""FastAPI app: the analyst's queue and case files, engineer reviews, evaluation reports.

    uv run uvicorn app.main:app --app-dir backend --port 8000
"""
from fastapi import FastAPI

from app.api import cases, deps, evals, reviews

app = FastAPI(title="Recall Match")
for module in (cases, reviews, evals):
    app.include_router(module.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    setup = deps.llm()
    return {"llm_mode": setup.cassette_mode, "model": setup.model_name or None, "live_model": bool(setup.model_name)}
