"""Isolated local API for browser acceptance; never reads deployment credentials."""
import os
from pathlib import Path
from contextlib import asynccontextmanager

ROOT = Path(__file__).resolve().parents[2]
os.environ['QCMAKER_ENV_FILE'] = str(ROOT / '.venv' / 'acceptance' / 'absent.env')
from backend.app.core import config
from backend.app.repositories import database
from backend.app.services import ppt
from backend.app.services.materials import material_service

scratch = ROOT / '.venv' / 'acceptance'
scratch.mkdir(parents=True, exist_ok=True)
config.settings = config.Settings(_env_file=None, OPENAI_API_KEY=None, TAVILY_API_KEY=None,
    API_ACCESS_TOKEN=None, ROLE_MODELS='{}', PROVIDER_CREDENTIALS='{}', RATE_LIMIT_PER_MINUTE=10000)
database.DATA_DIR = scratch
database.DB_PATH = scratch / 'acceptance.sqlite3'
ppt.OUTPUT_DIR = scratch / 'ppts'
material_service.storage_root = scratch / 'materials'
from backend.main import app

@asynccontextmanager
async def lifespan(app):
    database.init_database()
    yield

app.router.lifespan_context = lifespan
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=52889)
