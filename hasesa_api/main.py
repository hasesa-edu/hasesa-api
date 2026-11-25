from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hasesa_api.config import get_settings
from hasesa_api.db import get_engine
from hasesa_api.health.router import router as health_router
from hasesa_api.identity.router import router as identity_router
from hasesa_api.identity.router import well_known


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Close pooled connections cleanly when Cloud Run stops the instance.
    if get_settings().database_url:
        await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Hasesa API",
        version="0.1.0",
        lifespan=lifespan,
        # Interactive docs stay on outside production; the OpenAPI schema is
        # always served so clients can be generated from it.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url="/v1/openapi.json",
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
        )

    v1 = APIRouter(prefix="/v1")
    v1.include_router(health_router)
    v1.include_router(identity_router)
    app.include_router(v1)
    app.include_router(well_known)
    return app


app = create_app()
