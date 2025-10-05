import logging
import time
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import Config


logger = logging.getLogger(__name__)


def cors_allowed_origins() -> list[str]:
    return Config.allowed_origins()


async def add_cors_headers(request: Request, call_next: Callable):
    response = await call_next(request)
    origin = request.headers.get("origin")
    if origin and origin in cors_allowed_origins():
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
    return response


async def log_requests(request: Request, call_next: Callable):
    start_time = time.time()
    request_id = f"{int(time.time() * 1000)}-{id(request)}"

    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        # Only log slow requests (>1s) or errors
        if process_time > 1.0 or response.status_code >= 400:
            logger.info(f"[{request_id}] {request.method} {request.url.path} - {response.status_code} - {process_time:.2f}s")
        return response
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"[{request_id}] {request.method} {request.url.path} - ERROR: {str(e)} - {process_time:.2f}s")
        raise


async def global_exception_handler(request: Request, exc: Exception):
    request_id = f"{int(time.time() * 1000)}-{id(request)}"
    logger.error(f"[{request_id}] Unhandled exception in {request.method} {request.url.path}: {str(exc)}", exc_info=True)

    origin = request.headers.get("origin")
    response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
    if origin and origin in cors_allowed_origins():
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"

    return response


