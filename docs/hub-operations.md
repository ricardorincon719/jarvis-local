# PEARL Hub Operations

Version: `0.7.0-beta.1`

## Install

Create the local environment once:

```bash
cd ~/asistente_local
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

Install and start the user service:

```bash
./scripts/install_hub_service.sh
```

The installer keeps private scene memory outside Git:

```text
~/.local/share/pearl-home/scene-memory
```

Local overrides belong in:

```text
~/.config/pearl-home/hub.env
```

## Start Without Login

Run once with the required system permissions:

```bash
loginctl enable-linger "$USER"
```

## Verify

```bash
systemctl --user status pearl-hub.service
curl http://127.0.0.1:5006/api/v1/status
journalctl --user -u pearl-hub.service -n 100 --no-pager
```

## Scene Prompts

PEARL Hub persists pending proposals in the private scene memory directory. Candidate
approval decisions are idempotent and never execute physical actions.

```bash
curl http://127.0.0.1:5006/api/v1/scene-prompts/pending
```

Legacy endpoints remain available during the Beta.
