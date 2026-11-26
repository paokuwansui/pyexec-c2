# pyexec2

pyexec2 is a plugin-first, file-backed Python C2 / remote Python execution platform for authorized security testing and lab environments.

## Architecture

- `server_core/` — control plane, file-backed storage, action registry, task engine, listeners, proxy gateway.
- `transport_plugins/` — UDP, TCP, HTTP, HTTPS, DNS transport implementations.
- `implant_plugins/` — Python capabilities delivered to Beacons.
- `server_plugins/` — server-local extensions.
- `clients/web/` — React operator workbench.
- `clients/web_backend.py` — local-only Web backend between the browser and the control API.
- `clients/ai/` — AI worker/approval command-line client and example configuration.
- `clients/default_redteam_notes/` — initial built-in red-team notes shipped with the project.
- `tests/` — Python test suite.

## Requirements

- Python 3.12+
- Node.js 18+ and npm for the React client
- OpenSSL for a local development TLS certificate

Install Python dependencies:

```bash
python3 -m pip install -e '.[dev]'
```

Build the Web client:

```bash
cd clients/web
npm install
npm run build
cd ../..
```

## First Run

### 1. Generate a local development TLS certificate

HTTPS transport and HTTPS payloads need a local certificate:

```bash
bash scripts/gen_dev_cert.sh
```

The generated key is only for local development and must not be used as a production certificate.

### 2. Start the control API

```bash
python3 run.py --host 0.0.0.0 --port 18080
```

On first run the server creates and prints the Human, AI Worker, and AI Approval tokens. Store them securely. The browser UI never receives the API token from the local backend.

### 3. Configure the local Web client

Copy the example:

```bash
cp config/web.json.example config/web.json
```

Edit `config/web.json`:

```json
{
  "server": "http://127.0.0.1:18080",
  "token": "PASTE_HUMAN_TOKEN_HERE"
}
```

Start it:

```bash
python3 clients/web_backend.py --config config/web.json --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`.

## AI Configuration

The local AI config is stored under `clients/local_data/ai_agent/` and is encrypted at rest with Fernet. Do not commit that directory.

Worker/approval client examples:

```bash
cp clients/ai/config.json.example clients/ai/config.json
cp clients/ai/approval_config.json.example clients/ai/approval_config.json
```

Set the generated AI Worker and AI Approval tokens in those files.

Default AI provider settings:

```text
Base URL: https://api.deepseek.com
Model: deepseek-flash
Thinking: max
API format: OpenAI-compatible
```

## Approval Model

- Human token: full operator access; bypasses action approval.
- AI Worker token: subject to `all_allow` or `per_action`.
- AI Approval token: may approve/reject AI operations, but cannot approve its own operation.
- In `per_action` mode, AI writes enter the approval queue.
- AI tool calls wait for human approval and resume with the real result after approval.
- A rejection can include a suggestion; the suggestion is returned to the AI as a tool result so it can revise its plan.

## Payload Delivery

Payload generation supports these delivery methods in this order:

1. Direct Echo
2. Short Python Downloader
3. Curl Download Execution

Each delivery row has an independent `混淆模式` control. Enabling it only changes that row:

- Direct Echo embeds a randomly obfuscated launcher.
- Short Downloader and Curl use the obfuscated variant URL only for their own row.
- Normal payload URL remains unchanged.
- Obfuscation layers include zlib compression, per-operation random XOR, Base64, randomized identifiers, and split module/builtin names.

Obfuscation reduces static string signatures; it does not guarantee bypass of endpoint security products, sandboxes, or network inspection.

## Built-in Red-Team Notes

The initial project does not require a pre-populated notebook database. On first launch, the local Web backend seeds the files under:

```text
clients/default_redteam_notes/
```

These notes are part of the initial project and are re-created automatically when the default-note content changes.

## Tests

Run from the project root:

```bash
python3 -m pytest -q
```

The test fixture generates a temporary development certificate if `config/server.crt` and `config/server.key` are missing.

## Security Notes

- Never commit real API keys, tokens, private keys, runtime data, logs, or operator history.
- The included configuration examples contain placeholders only.
- `config/web.json`, `config/proxy.json`, `clients/ai/config.json`, `clients/ai/approval_config.json`, and `clients/local_data/` are intentionally excluded by `.gitignore`.
- Rotate tokens after a shared deployment.
- Use this software only against systems you are explicitly authorized to test.
