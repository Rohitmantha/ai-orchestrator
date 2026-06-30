from fastapi import FastAPI
from app.api.v1.endpoints import workflow

app = FastAPI(
    title="Enterprise Multi-Agent AI Orchestration Platform",
    description="REST API for coordinating AI agents, managing workflows, and tracking execution graphs.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Include the router for workflow endpoints
app.include_router(workflow.router, prefix="/api/v1")

@app.get("/health", tags=["System"])
async def health_check():
    """System health check endpoint."""
    return {"status": "ok", "message": "Orchestrator API is running."}

# To run: uvicorn app.main:app --reload
