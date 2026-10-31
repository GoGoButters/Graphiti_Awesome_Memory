from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from app.core.config import settings
from app.api.v1 import memory, admin
from datetime import datetime, timedelta, timezone
import asyncio
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Background Retry Logic
from app.services.graphiti_client import graphiti_client


async def _retry_episode(ep: dict):
    metadata = {"source": ep.get("source") or "User Input", "role": "user", "retry": True}
    if ep.get("file_name"):
        metadata["file_name"] = ep["file_name"]
    try:
        await graphiti_client.add_episode(
            user_id=ep["user_id"],
            text=ep["content"],
            metadata=metadata,
            pending_uuid=ep["uuid"],
        )
    except Exception as e:
        logger.error(f"Retry of episode {ep.get('uuid')} failed: {e}")


async def retry_pending_episodes_loop():
    """
    Retry PendingEpisodes waiting longer than EPISODE_RETRY_AFTER_MINUTES.
    Each retry marks the node 'processing' (attempts+1), so an episode is never
    picked twice while running; after EPISODE_MAX_ATTEMPTS it becomes 'failed'.
    """
    # Wait for startup
    await asyncio.sleep(60)
    while True:
        try:
            logger.info("Checking for stuck pending episodes...")
            stuck_episodes = await graphiti_client.get_stuck_pending_episodes(
                minutes=settings.EPISODE_RETRY_AFTER_MINUTES
            )

            if stuck_episodes:
                logger.info(f"Found {len(stuck_episodes)} stuck episodes. Retrying...")
                for ep in stuck_episodes:
                    logger.info(f"Retrying episode {ep.get('uuid')} for user {ep.get('user_id')}")
                    asyncio.create_task(_retry_episode(ep))
            else:
                logger.info("No stuck episodes found.")

        except Exception as e:
            logger.error(f"Error in retry loop: {e}")

        await asyncio.sleep(settings.EPISODE_RETRY_AFTER_MINUTES * 60)


def _seconds_until_hour_utc(hour: int) -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def consolidation_loop():
    """Nightly sleep-time consolidation (see GraphitiWrapper.consolidate)."""
    while True:
        await asyncio.sleep(_seconds_until_hour_utc(settings.CONSOLIDATION_HOUR_UTC))
        try:
            await graphiti_client.consolidate()
        except Exception as e:
            logger.error(f"Consolidation failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup maintenance runs in background so the API is available immediately
    background = [
        asyncio.create_task(graphiti_client.run_startup_maintenance()),
        asyncio.create_task(retry_pending_episodes_loop()),
    ]
    if settings.CONSOLIDATION_ENABLED:
        background.append(asyncio.create_task(consolidation_loop()))
    yield
    for task in background:
        task.cancel()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add validation error handler to log details
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger.error(f"Validation error for {request.method} {request.url.path}")
    logger.error(f"Request body: {await request.body()}")
    logger.error(f"Validation errors: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body},
    )

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(memory.router, prefix="/memory", tags=["memory"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
