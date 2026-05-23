from fastapi import FastAPI

from app import __version__
from app.config import get_settings
from app.routers import chat, data, health, schedules

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Agentic production manager for window cleaning companies.",
)

app.include_router(health.router)
app.include_router(data.router)
app.include_router(chat.router)
app.include_router(schedules.router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Production Agent API",
        "version": __version__,
        "docs": "/docs",
    }
