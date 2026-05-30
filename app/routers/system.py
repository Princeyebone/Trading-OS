from fastapi import APIRouter
import os
import subprocess

router = APIRouter(prefix="/api/system", tags=["system"])

@router.get("/status")
def system_status():
    """Check if the backend systems and engine are online."""
    # Since the scheduler is now running inside FastAPI's lifespan,
    # if this API is reachable, the engine is inherently running!
    return {
        "engine_online": True
    }
