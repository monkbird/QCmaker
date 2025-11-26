from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Smart QC-Circle Generator API",
    description="Backend for QCmaker",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend.app.api.endpoints import config, topic, data, rag, search, discussion, visualization, ppt

app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(topic.router, prefix="/api/topic", tags=["topic"])
app.include_router(data.router, prefix="/api/data", tags=["data"])
app.include_router(rag.router, prefix="/api/rag", tags=["rag"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(discussion.router, prefix="/api/discussion", tags=["discussion"])
app.include_router(visualization.router, prefix="/api/visualization", tags=["visualization"])
app.include_router(ppt.router, prefix="/api/ppt", tags=["ppt"])

@app.get("/")
async def root():
    return {"message": "Welcome to Smart QC-Circle Generator API"}

@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
