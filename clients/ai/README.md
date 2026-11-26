# PyExec2 AI Client Tutorial

`client_ai.py` is a one-shot HTTP JSON client. It uses the same server action API as the Web client.

Approval policy is role-aware with three tokens:

- Human/Web token: every action is allowed directly and bypasses approval policy.
- AI worker token: actions follow `all_allow` or `per_action`; worker cannot decide approvals.
- AI approval token: an independent AI approver can approve/reject AI worker operations.
- In `per_action` mode, AI worker actions wait for an AI approver or human.

## Configure

Create `config.json` next to `client_ai.py`:

```json
{"server":"http://SERVER:18080","token":"SERVER_TOKEN"}
```

The server prints three tokens on startup:

- Human/Web token in `data/server_token.txt`
- AI worker token in `data/ai_token.txt`
- AI approval token in `data/ai_approval_token.txt`

Typical two-AI workflow:

```text
AI worker  -> clients/ai/config.json
AI approver -> clients/ai/approval_config.json
```

## Call

```bash
python3 client_ai.py --action server.status
python3 client_ai.py --action beacon.list
python3 client_ai.py --action task.create --args '{"beacon_id":"...","plugin":"luname","args":{}}'
python3 client_ai.py --action task.show --args '{"task_id":"..."}'
python3 client_ai.py --request request.json
python3 client_ai.py --action task.create --args '{"beacon_id":"...","plugin":"lps","args":{}}' --wait
```

All output is JSON on stdout.

## Full Human/AI Parity

AI uses the same token and the same action API as the Web client. It can list and execute every control action, including approvals.

Discover the complete action catalog:

```bash
python3 client_ai.py --list-actions
```

Approval workflow:

```bash
python3 client_ai.py --action server.config.set --args '{"approval_mode":"per_action"}'
python3 client_ai.py --action task.create --args '{"beacon_id":"...","plugin":"luname","args":{}}'
python3 client_ai.py --pending
python3 client_ai.py --show-approval appr_xxx
# AI approver uses the approval config/token:
python3 client_ai.py --config approval_config.json --pending
python3 client_ai.py --config approval_config.json --approve appr_xxx
python3 client_ai.py --config approval_config.json --reject appr_xxx
python3 client_ai.py --config approval_config.json --approve-all
python3 client_ai.py --config approval_config.json --reject-all
```

Wait for an existing task:

```bash
python3 client_ai.py --wait-task task_xxx
```

Generic actions remain available:

```bash
python3 client_ai.py --action plugin.create --args '{"kind":"implant","name":"common/foo","command":"foo"}'
python3 client_ai.py --action proxy.start --args '{"beacon_id":"...","port":1080}'
python3 client_ai.py --action task.cancel --args '{"task_id":"..."}'
```

The Web approval page and the AI CLI call the exact same actions:

```text
approval.list
approval.pending
approval.show
approval.approve
approval.reject
approval.approve_all
approval.reject_all
```

## Payload and Beacon Settings

Payload generation accepts runtime settings:

```bash
python3 client_ai.py --action payload.generate --args '{
  "listener_id":"lst_xxx",
  "name":"ai-payload",
  "fast_interval":5,
  "slow_interval":600,
  "finish_delay":5,
  "jitter":0.2,
  "max_concurrent_tasks":8
}'
```

Update a live Beacon's runtime settings:

```bash
python3 client_ai.py --action beacon.settings --args '{
  "beacon_id":"beacon_xxx",
  "settings":{
    "fast_interval":4,
    "slow_interval":120,
    "finish_delay":3,
    "jitter":0.15,
    "max_concurrent_tasks":6,
    "current_interval":5
  }
}'
```

Upgrade a Beacon to another listener/protocol:

```bash
python3 client_ai.py --action protocol.upgrade --args '{
  "beacon_id":"beacon_xxx",
  "protocol":"tcp",
  "host":"127.0.0.1",
  "port":19022
}'
```

These are the same actions used by the Web control panel; the difference is only the authenticated role and approval policy.
