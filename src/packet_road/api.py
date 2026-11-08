import hmac
import logging
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field

from packet_road.core import PolicyError, diagnose, normalize_target

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger(__name__)
TOTAL = Counter("packet_road_diagnostics_total", "Accepted diagnostics", ["outcome"])
DURATION = Histogram("packet_road_diagnostic_duration_seconds", "Full diagnostic duration",
                     buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 45, 60))
STAGES = Counter("packet_road_stage_errors_total", "Stage errors", ["stage"])
ACTIVE = threading.BoundedSemaphore(2)
RATE_LOCK = threading.Lock()
STARTS = deque()


@asynccontextmanager
async def lifespan(app):
    if len(os.getenv("PACKET_ROAD_TOKEN", "")) < 32:
        raise RuntimeError("PACKET_ROAD_TOKEN must contain at least 32 characters")
    yield


app = FastAPI(title="Packet Road", version="0.2.0", lifespan=lifespan,
              docs_url=None, redoc_url=None)


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=1, max_length=253)
    port: int = Field(default=443, ge=1, le=65535)
    max_hops: int = Field(default=16, ge=1, le=20)


def authorize(authorization: str = Header(default="")):
    token = os.getenv("PACKET_ROAD_TOKEN", "")
    if not token or not hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "Bearer token required")


@app.get("/health/live")
def live():
    return {"status": "ok", "revision": os.getenv("APP_REVISION", "development")}


@app.get("/health/ready")
def ready():
    if len(os.getenv("PACKET_ROAD_TOKEN", "")) < 32:
        raise HTTPException(503, "Token not configured")
    return {"status": "ready"}


@app.get("/metrics")
def metrics():
    # Bind only on a trusted network; NetworkPolicy limits the metrics surface in K8s.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/diagnostics", dependencies=[Depends(authorize)])
def diagnostics(request: Request):
    try:
        target = normalize_target(request.target)
        allowed = {normalize_target(item) for item in
                   os.getenv("PACKET_ROAD_TARGETS", "").split(",") if item.strip()}
        if target not in allowed or request.port not in (80, 443):
            raise PolicyError("Target or port not allowed; configure exact PACKET_ROAD_TARGETS")
    except PolicyError as exc:
        raise HTTPException(403, str(exc)) from exc
    if not ACTIVE.acquire(blocking=False):
        raise HTTPException(429, "Two diagnostics already running")
    try:
        with RATE_LOCK:
            now = time.monotonic()
            while STARTS and STARTS[0] <= now - 60:
                STARTS.popleft()
            if len(STARTS) >= 10:
                raise HTTPException(429, "Limit: ten diagnostics per minute per process")
            STARTS.append(now)
        with DURATION.time():
            try:
                result = diagnose(target, request.port, request.max_hops)
            except PolicyError as exc:
                TOTAL.labels("rejected").inc()
                raise HTTPException(403, str(exc)) from exc
            except Exception:
                TOTAL.labels("error").inc()
                LOG.exception("Unexpected diagnostic failure")
                raise
        errors = [name for name, stage in result["stages"].items()
                  if stage["status"] == "error"]
        for name in errors:
            STAGES.labels(name).inc()
        TOTAL.labels("partial" if errors else "ok").inc()
        return result
    finally:
        ACTIVE.release()
