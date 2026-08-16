import logging
import os
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.endpoints import config, data, discussion, ppt, rag, search, topic, visualization
from backend.app.core.config import PROJECT_ROOT, get_settings
from backend.app.core.errors import install_error_handlers
from backend.app.repositories.database import init_database
from backend.app.services.ppt import cleanup_expired


def configure_logging() -> None:
    log_dir = PROJECT_ROOT / "backend" / "logs"; log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", handlers=[logging.StreamHandler(), handler], force=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(); init_database(); cleanup_expired(); yield

app = FastAPI(
    title="Smart QC-Circle Generator API",
    description="Backend for QCmaker",
    version="1.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(topic.router, prefix="/api/topic", tags=["topic"])
app.include_router(data.router, prefix="/api/data", tags=["data"])
app.include_router(rag.router, prefix="/api/rag", tags=["rag"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(discussion.router, prefix="/api/discussion", tags=["discussion"])
app.include_router(visualization.router, prefix="/api/visualization", tags=["visualization"])
app.include_router(ppt.router, prefix="/api/ppt", tags=["ppt"])
install_error_handlers(app)

@app.get("/")
async def root():
    return {"message": "Welcome to Smart QC-Circle Generator API"}

@app.get("/api/health")
async def health_check():
    settings = get_settings(); llm = "ready" if (settings.USE_LOCAL_LLM or settings.OPENAI_API_KEY) else "missing"; chroma_dir = PROJECT_ROOT / "backend" / "data" / "chroma_db"; data_dir = PROJECT_ROOT / "backend" / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True); disk_writable = os.access(data_dir, os.W_OK)
    except OSError: disk_writable = False
    return {"status": "ok" if llm == "ready" and disk_writable else "degraded", "version": app.version, "llm": llm, "chromadb": "ready" if chroma_dir.exists() else "not_initialized", "disk_writable": disk_writable}
