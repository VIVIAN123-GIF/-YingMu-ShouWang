import logging
import uuid

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.service.errors import ServiceError

logger = logging.getLogger("backend.errors")


async def validation_error_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    confidence_missing = any(error.get("type") == "missing" and
                             error.get("loc", ())[-1:] == ("confidence",) for error in exc.errors())
    return JSONResponse(status_code=422, content={"error": {
        "code": "CONFIDENCE_REQUIRED" if confidence_missing else "VALIDATION_ERROR",
        "message": "confidence is required" if confidence_missing else "Request validation failed",
        "request_id": request_id, "details": [
            {"type": item.get("type"), "location": list(item.get("loc", ())), "message": item.get("msg")}
            for item in exc.errors()
        ]}})


async def service_error_handler(request: Request, exc: ServiceError):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    error = {"code": exc.code, "message": exc.message, "request_id": request_id}
    if exc.debug is not None:
        error["debug"] = exc.debug
        logger.warning(
            "service_error_debug request_id=%s code=%s debug=%s",
            request_id,
            exc.code,
            exc.debug,
        )
    return JSONResponse(status_code=exc.status_code, content={"error": error})


async def unexpected_error_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.exception("internal_error request_id=%s error_type=%s", request_id, type(exc).__name__)
    return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR",
        "message": "Internal server error", "request_id": request_id}})
