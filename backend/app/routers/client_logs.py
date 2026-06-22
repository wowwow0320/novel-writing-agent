import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/client-log", tags=["client-log"])
logger = logging.getLogger("uvicorn.error")


class ClientLogRequest(BaseModel):
    action: str = Field(default="unknown", max_length=120)
    label: str | None = Field(default=None, max_length=240)
    path: str | None = Field(default=None, max_length=300)
    tag: str | None = Field(default=None, max_length=40)
    detail: dict[str, Any] | None = None


@router.post("")
async def client_log(body: ClientLogRequest) -> dict[str, bool]:
    logger.info(
        "[client-action] action=%s tag=%s label=%r path=%s detail=%s",
        body.action,
        body.tag or "-",
        body.label or "",
        body.path or "",
        body.detail or {},
    )
    return {"ok": True}
