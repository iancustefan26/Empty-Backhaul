from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.loads import router as loads_router
from app.api.match import router as match_router
from app.api.trucks import router as trucks_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Optimizer Agentic de Backhaul Frigorific",
    description=(
        "Sistem multi-agent care potriveste camioanele frigorifice goale "
        "cu incarcaturi de retur validate din punct de vedere al conformitatii "
        "HACCP/ANSVSA/GDP pe teritoriul Romaniei."
    ),
    version="0.4.0",
    swagger_ui_parameters={
        "docExpansion": "list",
        "defaultModelsExpandDepth": -1,
        "tryItOutEnabled": True,
    },
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
app.include_router(admin_router, prefix="/api")


@app.get("/health", tags=["Meta"], summary="Verificare stare server")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


@app.get("/", tags=["Meta"], summary="Informatii despre API")
def root() -> dict[str, str]:
    return {
        "name": "optimizer-agentic-backhaul-frigorific",
        "phase": "4 — Endpoint-uri FastAPI + documente mock",
        "docs": "/docs",
    }
