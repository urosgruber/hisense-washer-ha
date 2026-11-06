# Hisense washer: local control for Home Assistant

A local server for a Hisense washer (ConnectLife device protocol). The washer
logs in to this server instead of the ConnectLife cloud. Home Assistant gets
the washer's phase, time left, end time, energy and water over MQTT, a
dashboard card, and a "wash done" notification.

The cloud is off by default. An admin can turn it on for a limited time.
The server only reads: it cannot start or stop a wash.

## Install in Home Assistant

Add this repository in Settings → Apps → App store → ⋮ → Repositories:

    https://github.com/urosgruber/hisense-washer-ha#release

Then install **Hisense Washer** and read its Documentation tab.

## Layout

| Path | What |
|---|---|
| `washer/` | The server (Python, asyncio) |
| `dist/hisense-washer-card.js` | The dashboard card |
| `ha-app/` | The Home Assistant app: config, Dockerfile, run.sh, helpers |
| `tests/` | Unit tests, fixtures from a recorded wash, card smoke test |
| `scripts/` | Capture tools: make a fixture, import login replies |
| `home/` | Run the server on a Mac |

## Test

```bash
python3 -m unittest discover -s tests -t . -v
node tests/card-smoke.js dist/hisense-washer-card.js
```
