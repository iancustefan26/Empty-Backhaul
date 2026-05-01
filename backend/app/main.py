from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.loads import router as loads_router
from app.api.match import router as match_router
from app.api.trucks import router as trucks_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Agentic Cold Backhaul Optimizer",
    description=(
        "Multi-agent system that matches empty returning reefers with "
        "compliance-validated backhaul loads across Romania."
    ),
    version="0.4.0",
)

# CORS for the React/Vite dashboard (Phase 5).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(match_router, prefix="/api")
app.include_router(trucks_router, prefix="/api")
app.include_router(loads_router, prefix="/api")


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {
        "name": "agentic-cold-backhaul-optimizer",
        "phase": "4 — FastAPI endpoints + mock documents",
        "docs": "/docs",
    }
