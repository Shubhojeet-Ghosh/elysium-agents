"""
Elysium Agents - Main Application Entry Point
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from logging_config import get_logger
from config.settings import settings
from routes.main_router import main_router
from services.redis_services import initialize_redis_client, close_redis_client
from sockets import socketio_app

logger = get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle (startup/shutdown)"""
    # Startup
    logger.info(f"Starting {settings.PROJECT_TITLE} in {settings.ENVIRONMENT} mode...")
    
    # Initialize Redis client connection
    initialize_redis_client()
    
    yield
    
    # Shutdown
    logger.info(f"Shutting down {settings.PROJECT_TITLE}...")
    
    # Close Redis client connection
    close_redis_client()


# Initialize FastAPI app
app = FastAPI(
    title=settings.PROJECT_TITLE,
    description="Core infrastructure for AI chat agents with multi-source data ingestion",
    version=settings.PROJECT_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.RELOAD else None,
    redoc_url="/redoc" if settings.RELOAD else None,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "version": settings.PROJECT_VERSION
    }


@app.get("/")
async def root():
    """Root endpoint"""
    logger.info(f"Hello. Welcome to {settings.PROJECT_TITLE}")
    return f"Welcome to {settings.PROJECT_TITLE} in {settings.ENVIRONMENT} environment, version {settings.PROJECT_VERSION}."

# Include the main router, which in turn includes all other route modules
app.include_router(main_router)

# Mount Socket.IO app
app.mount("/socket.io", socketio_app)

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        log_level="info"
    )