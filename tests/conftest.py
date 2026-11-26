from __future__ import annotations

import shutil
from pathlib import Path

import subprocess
import pytest
from fastapi.testclient import TestClient

from server_core.app import create_app
from server_core.config import Settings
from server_core.runtime import ServerRuntime

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def temp_runtime(tmp_path: Path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    for name in ("implant_plugins", "server_plugins", "transport_plugins"):
        shutil.copytree(ROOT / name, workdir / name)
    (workdir / "config").mkdir()
    cert_src = ROOT / "config" / "server.crt"
    key_src = ROOT / "config" / "server.key"
    if cert_src.exists() and key_src.exists():
        shutil.copy2(cert_src, workdir / "config" / "server.crt")
        shutil.copy2(key_src, workdir / "config" / "server.key")
    else:
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(workdir / "config" / "server.key"),
            "-out", str(workdir / "config" / "server.crt"),
            "-days", "1", "-subj", "/CN=pyexec2-test",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    settings = Settings(
        workdir=workdir,
        data_dir=workdir / "data",
        runtime_dir=workdir / "runtime",
        logs_dir=workdir / "logs",
        config_dir=workdir / "config",
        token_file=workdir / "data" / "server_token.txt",
        host="127.0.0.1",
        port=18081,
        token="test-token",
        ai_token="test-ai-token",
        ai_approval_token="test-ai-approval-token",
    )
    runtime = ServerRuntime(settings)
    return runtime


@pytest.fixture()
def client(temp_runtime):
    app = create_app(temp_runtime)
    with TestClient(app) as test_client:
        yield test_client
