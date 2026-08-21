import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.api.exception_handlers import service_error_handler, unexpected_error_handler, validation_error_handler
from fastapi.exceptions import RequestValidationError
from backend.api.v1.router import router
from backend.db.init_db import init_default_config, init_tables
from backend.service.errors import ServiceError
from backend.static_frontend import mount_frontend

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_tables()
    await init_default_config()
    yield

app = FastAPI(title="萤目守望风险服务", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_exception_handler(ServiceError, service_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unexpected_error_handler)

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID", f"req-{uuid.uuid4().hex}")
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response

@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "schema_version": "1.0", "ruleset_version": "ruleset-v1.0"}

app.include_router(router)
mount_frontend(app)
