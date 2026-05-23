from fastapi import FastAPI

from app import __version__
from app.config import get_settings
from app.routers import health

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Agentic production manager for window cleaning companies.",
)

app.include_router(health.router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Production Agent API",
        "version": __version__,
        "docs": "/docs",
    }
