from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.routers import chat, data, health, optimizer_lab, schedules

settings = get_settings()

if settings.langfuse_public_key and settings.langfuse_secret_key:
    print(
        f"Langfuse tracing enabled (host={settings.langfuse_host})",
        flush=True,
    )
else:
    print("Langfuse tracing disabled (missing LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY)", flush=True)

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Agentic production manager for window cleaning companies.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(data.router)
app.include_router(chat.router)
app.include_router(schedules.router)
app.include_router(optimizer_lab.router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Production Agent API",
        "version": __version__,
        "docs": "/docs",
    }
