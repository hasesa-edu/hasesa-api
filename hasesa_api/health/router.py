from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hasesa_api.db import get_db

router = APIRouter(prefix="/health", tags=["health"])


class Health(BaseModel):
    status: str


@router.get("", response_model=Health)
async def liveness() -> Health:
    """The process is up. Does not touch the database."""
    return Health(status="ok")


@router.get("/ready", response_model=Health)
async def readiness(db: AsyncSession = Depends(get_db)) -> Health:
    """The process can reach the database."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(status_code=503, detail="database unavailable") from e
    return Health(status="ok")
