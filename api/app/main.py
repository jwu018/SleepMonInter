"""The FastAPI application. Run it with:  uvicorn app.main:app --reload

Interactive docs (generated from the code): http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import patients, recordings, uploads
from .schemas import Health
from .security import require_api_key

API_VERSION = "0.3.0"

app = FastAPI(
    title="Night Night API",
    version=API_VERSION,
    description="Prototype API for the Night Night dashboard. Synthetic data only.",
)

# CORS: a browser refuses to let a page on one site read responses from another site unless
# that other site says it is allowed. This lists the sites (origins) that may call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Every data route requires the shared secret. /health below does not, so a hosting
# service can check that the process is alive without knowing the secret.
app.include_router(patients.router, dependencies=[Depends(require_api_key)])
# uploads first: its fixed path /recordings/upload must be matched before /recordings/{id}.
app.include_router(uploads.router, dependencies=[Depends(require_api_key)])
app.include_router(recordings.router, dependencies=[Depends(require_api_key)])


@app.get("/health", response_model=Health, tags=["status"])
def health() -> Health:
    """Liveness check: answers if the API process is running. It does not touch the database."""
    return Health(status="ok", service="night-night-api", version=API_VERSION)
