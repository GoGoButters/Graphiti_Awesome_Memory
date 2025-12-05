from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.api.v1 import memory, admin
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
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

# Background Retry Logic
import asyncio
from app.services.graphiti_client import graphiti_client

async def retry_pending_episodes_loop():
    """
    Background task to retry stuck pending episodes every 30 minutes.
    """
    while True:
        try:
            # Wait for startup
            await asyncio.sleep(60) 
            
            logger.info("Checking for stuck pending episodes...")
            stuck_episodes = await graphiti_client.get_stuck_pending_episodes(minutes=30)
            
            if stuck_episodes:
                logger.info(f"Found {len(stuck_episodes)} stuck episodes. Retrying...")
                for ep in stuck_episodes:
                    logger.info(f"Retrying episode {ep.get('uuid')} for user {ep.get('user_id')}")
                    # Run in background to not block the loop
                    asyncio.create_task(
                        graphiti_client.add_episode(
                            user_id=ep["user_id"],
                            text=ep["content"],
                            metadata={"source": ep["source"], "role": "user", "retry": True}
                        )
                    )
            else:
                logger.info("No stuck episodes found.")
            
        except Exception as e:
            logger.error(f"Error in retry loop: {e}")
            
        # Wait 30 minutes before next check
        await asyncio.sleep(30 * 60)

@app.on_event("startup")
async def startup_event():
    # Start the background retry loop
    asyncio.create_task(retry_pending_episodes_loop())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
