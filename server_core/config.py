from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    workdir: Path
    data_dir: Path
    runtime_dir: Path
    logs_dir: Path
    config_dir: Path
    token_file: Path
    host: str
    port: int
    token: str
    ai_token_file: Path | None = None
    ai_token: str = ""
    ai_approval_token_file: Path | None = None
    ai_approval_token: str = ""

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_settings(workdir: Path | None = None, host: str | None = None, port: int | None = None) -> Settings:
    root = Path.cwd() if workdir is None else Path(workdir).resolve()
    data_dir = root / "data"
    runtime_dir = root / "runtime"
    logs_dir = root / "logs"
    config_dir = root / "config"
    for path in (data_dir, runtime_dir, logs_dir, config_dir):
        path.mkdir(parents=True, exist_ok=True)
    token_file = data_dir / "server_token.txt"
    token = os.environ.get("PYEXEC2_TOKEN", "").strip()
    if not token and token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        token = secrets.token_urlsafe(32)
        token_file.write_text(token + "\n", encoding="utf-8")
        try:
            token_file.chmod(0o600)
        except OSError:
            pass
    ai_token_file = data_dir / "ai_token.txt"
    ai_token = os.environ.get("PYEXEC2_AI_TOKEN", "").strip()
    if not ai_token and ai_token_file.exists():
        ai_token = ai_token_file.read_text(encoding="utf-8").strip()
    if not ai_token:
        ai_token = secrets.token_urlsafe(32)
        ai_token_file.write_text(ai_token + "\n", encoding="utf-8")
        try:
            ai_token_file.chmod(0o600)
        except OSError:
            pass
    ai_approval_token_file = data_dir / "ai_approval_token.txt"
    ai_approval_token = os.environ.get("PYEXEC2_AI_APPROVAL_TOKEN", "").strip()
    if not ai_approval_token and ai_approval_token_file.exists():
        ai_approval_token = ai_approval_token_file.read_text(encoding="utf-8").strip()
    if not ai_approval_token:
        ai_approval_token = secrets.token_urlsafe(32)
        ai_approval_token_file.write_text(ai_approval_token + "\n", encoding="utf-8")
        try:
            ai_approval_token_file.chmod(0o600)
        except OSError:
            pass
    server_config = config_dir / "server.json"
    cfg = {}
    if server_config.exists():
        try:
            cfg = json.loads(server_config.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    cfg.setdefault("host", "0.0.0.0")
    cfg.setdefault("port", 8080)
    _atomic_json(server_config, cfg)
    return Settings(
        workdir=root,
        data_dir=data_dir,
        runtime_dir=runtime_dir,
        logs_dir=logs_dir,
        config_dir=config_dir,
        token_file=token_file,
        host=host or os.environ.get("PYEXEC2_HOST", cfg["host"]),
        port=int(port or os.environ.get("PYEXEC2_PORT", cfg["port"])),
        token=token,
        ai_token_file=ai_token_file,
        ai_token=ai_token,
        ai_approval_token_file=ai_approval_token_file,
        ai_approval_token=ai_approval_token,
    )
