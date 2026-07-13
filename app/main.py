import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.database import engine, Base
from app.routers import agents, sessions, webhooks
from app.services.sandbox import sandbox_driver

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("outpost_cma.main")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Outpost Managed Agents: Kubernetes Execution Control Plane & Standalone Orchestration Server.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to specific dashboard origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Register Routers
app.include_router(agents.router, prefix=settings.API_V1_STR)
app.include_router(sessions.router, prefix=settings.API_V1_STR)
app.include_router(webhooks.router)

# Mount Frontend UI static files
app.mount("/ui", StaticFiles(directory="app/static", html=True), name="ui")

# Background task for reconciling the warm pool of sandbox pods
async def warm_pool_reconciler_loop():
    logger.info("Starting Kubernetes warm pod pool reconciliation loop...")
    while True:
        try:
            await sandbox_driver.reconcile_warm_pool()
        except Exception as e:
            logger.error(f"Error in warm pool reconciler loop: {e}")
        await asyncio.sleep(30) # check pool status every 30 seconds

@app.on_event("startup")
async def startup_event():
    # 1. Create DB schemas asynchronously
    logger.info("Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized.")

    # 2. Initialize Kubernetes client
    logger.info("Initializing Kubernetes sandbox client...")
    await sandbox_driver.initialize()

    # 3. Spawn warm pool reconciler in background
    asyncio.create_task(warm_pool_reconciler_loop())

@app.get("/")
def read_root():
    return {
        "project": settings.PROJECT_NAME,
        "status": "healthy",
        "kubernetes_mode": settings.SANDBOX_DRIVER
    }
