from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from hasesa_api.db import DbDep

router = APIRouter(prefix="/health", tags=["health"])


class Health(BaseModel):
    status: str


@router.get("")
async def liveness() -> Health:
    """The process is up. Does not touch the database."""
    return Health(status="ok")


@router.get("/ready")
async def readiness(db: DbDep) -> Health:
    """The process can reach the database."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(status_code=503, detail="database unavailable") from e
    return Health(status="ok")
