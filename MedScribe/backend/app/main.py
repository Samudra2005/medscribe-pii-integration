"""
Application entrypoint. Run with:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
from the backend/ directory, with the venv active.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.lifespan import lifespan
from app.core.logging_config import configure_logging, get_logger
from app.middleware.request_logging import RequestLoggingMiddleware

from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.admin_users import router as admin_users_router

from app.api.patients import router as patients_router
from app.api.hitl import router as hitl_router
from app.api.audit_logs import router as audit_logs_router

from app.api import appointments
from app.api import audio
from app.api import intake_forms
from app.api import prescriptions
from app.api import metrics

from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.rate_limiting import limiter

from app.middleware.request_size_limit import RequestSizeLimitMiddleware

configure_logging()
logger = get_logger(__name__)
settings = get_settings()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Medical STT/NER assisted clinical documentation system",
    version="0.1.0",
    lifespan=lifespan,
)

# Request logging must be added before routers so it wraps every request.
app.add_middleware(RequestLoggingMiddleware)

app.add_middleware(RequestSizeLimitMiddleware)

# CORS: permissive for now during local dev (frontend on a different
# port). MUST be tightened to explicit allowed origins before any real
# deployment -- flagged now, addressed properly in Phase 16 (hardening).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(admin_users_router)

app.include_router(patients_router)
app.include_router(hitl_router)
app.include_router(audit_logs_router)

app.include_router(appointments.router)
app.include_router(audio.router) 
app.include_router(intake_forms.router)
app.include_router(prescriptions.router) 
app.include_router(metrics.router)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please wait before trying again."},
    )
    
@app.get("/")
async def root() -> dict:
    return {"message": f"{settings.PROJECT_NAME} API", "docs": "/docs"}

