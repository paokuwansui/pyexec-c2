from __future__ import annotations

import argparse
import sys

import uvicorn

from .app import create_app
from .config import load_settings
from .runtime import ServerRuntime


def main() -> None:
    parser = argparse.ArgumentParser(description="PyExec2 Rebuild server")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    settings = load_settings(host=args.host, port=args.port)
    runtime = ServerRuntime(settings)
    app = create_app(runtime)
    print("=" * 68)
    print(" PyExec2 Rebuild — server")
    print(f" Workdir: {settings.workdir}")
    print(f" Listen:  {settings.host}:{settings.port}")
    print(f" Human:   {settings.token}")
    print(f" AI Work: {settings.ai_token}")
    print(f" AI Appr: {settings.ai_approval_token}")
    print(f" SOCKS5:  on demand — run 'proxy start [port]' in Beacon console  user={runtime.proxy.username} pass={runtime.proxy.password}")
    print(" Web UI:  client-only — run clients/web_backend.py on the operator machine")
    print("=" * 68, flush=True)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info", server_header=False, date_header=False)


if __name__ == "__main__":
    main()
