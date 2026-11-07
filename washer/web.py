"""The admin page (Home Assistant ingress, admins only): status and the cloud switch.

Links are relative and the page sets <base> from X-Ingress-Path, so it works
behind ingress and on a plain port. The page shows no device secrets.
"""
from __future__ import annotations

import html
import logging
import time
from typing import Callable
from urllib.parse import urlparse

from aiohttp import web

from .cloud import CloudControl
from .mqtt import cloud_text, state_payload
from .state import WasherState
from .store import Store

PHASE_NAMES = {"off": "Off", "idle": "Idle", "delayed": "Delay start", "washing": "Washing",
               "rinsing": "Rinsing", "spinning": "Spinning", "done": "Done", "unknown": "Unknown"}

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base href="{base}">
<title>Washer (admin)</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 16px; max-width: 720px; color: #222; }}
h1 {{ font-size: 1.3em; }} h2 {{ font-size: 1.05em; margin-top: 1.6em; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ text-align: left; padding: 4px 8px; border-bottom: 1px solid #ddd; }}
form {{ display: inline-block; margin-right: 8px; }}
button {{ padding: 6px 12px; }}
.warn {{ color: #b00; }}
@media (prefers-color-scheme: dark) {{ body {{ background: #111; color: #ddd; }}
  td, th {{ border-color: #333; }} }}
</style></head><body>
<h1>Hisense washer</h1>
<table>{rows}</table>
<h2>Cloud</h2>
<p>Cloud: <b>{cloud}</b>. {cloud_note}</p>
<form method="post" action="cloud/on">
  <label>Turn the cloud on for
    <input name="hours" type="number" min="0.5" max="{max_hours}" step="0.5" value="{max_hours}"> hours</label>
  <button type="submit">Cloud on</button>
</form>
<form method="post" action="cloud/off"><button type="submit">Cloud off</button></form>
<p>Login recorded: {login}</p>
<h2>Last cycles</h2>
<table><tr><th>Start</th><th>End</th><th>Energy</th><th>Water</th><th>Confirmed</th></tr>{cycles}</table>
</body></html>
"""


log = logging.getLogger(__name__)

def _t(epoch: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch)) if epoch else "-"


def _row(name: str, value) -> str:
    return f"<tr><th>{html.escape(name)}</th><td>{html.escape(str(value))}</td></tr>"


def _base(request: web.Request) -> str:
    return request.headers.get("X-Ingress-Path", "").rstrip("/") + "/"


def _same_origin(request: web.Request) -> bool:
    origin = request.headers.get("Origin")
    if not origin or origin == "null":
        return True
    return urlparse(origin).netloc == request.host


def make_app(state: WasherState, cloud: CloudControl, store: Store, device,
             on_change: Callable[[], None] = lambda: None,
             allowed: set[str] | None = None) -> web.Application:
    """allowed: the only peer addresses that may use the page. In the app this
    is the ingress gateway, so only Home Assistant admins reach it. None
    allows every peer (the Mac run, bound to 127.0.0.1)."""
    def payload() -> dict:
        return state_payload(state.view(time.time()), store.load_totals(),
                             cloud.info(device.login_ready))

    async def index(request: web.Request) -> web.Response:
        v = state.view(time.time())
        rows = "".join([
            _row("Connected", "yes" if v["connected"] else ("no (keeping the last state)"
                                                            if v["stale"] else "no")),
            _row("Phase", f'{PHASE_NAMES.get(v["phase"], v["phase"])} ({v["phase_raw"] or "-"})'),
            _row("Minutes left", v["minutes_left"] if v["minutes_left"] is not None else "-"),
            _row("Ends at", _t(v["end_time"])),
            _row("Spin speed", f'{v["spin_rpm"]} rpm' if v["spin_rpm"] is not None else "-"),
            _row("Door locked", {True: "yes", False: "no", None: "-"}[v["door_locked"]]),
            _row("This cycle", f'{v["cycle_energy_kwh"] or 0:.2f} kWh, {v["cycle_water_l"] or 0:.2f} L'),
            _row("Last status", _t(v["last_status"])),
        ])
        info = cloud.info(device.login_ready)
        if info["mode"] == "on":
            note = "The washer talks to the ConnectLife cloud. The cloud turns off by itself."
        elif not info["login_ready"]:
            note = ('<span class="warn">No recorded login. Turn the cloud on once, '
                    "so the washer can log in with the cloud off later.</span>")
        else:
            note = "The washer talks only to this server."
        error = getattr(device, "cloud_error", None)
        if info["mode"] == "on" and error:
            note += f'<br><span class="warn">{html.escape(error)}. The server answers the washer locally.</span>'
        recorded = store.login_recorded_at()
        cycles = "".join(
            f"<tr><td>{_t(c.started)}</td><td>{_t(c.ended)}</td><td>{c.energy_kwh:.2f} kWh</td>"
            f"<td>{c.water_l:.2f} L</td><td>{'yes' if c.confirmed else 'no'}</td></tr>"
            for c in reversed(store.recent_cycles(20)))
        body = PAGE.format(
            base=html.escape(_base(request)), rows=rows, cloud=html.escape(cloud_text(info)),
            cloud_note=note, max_hours=cloud.max_hours,
            login=f"yes, {_t(recorded)}" if recorded else "no",
            cycles=cycles or '<tr><td colspan="5">No cycles yet</td></tr>')
        return web.Response(text=body, content_type="text/html")

    async def change_cloud(request: web.Request, turn_on: bool) -> web.Response:
        if not _same_origin(request):
            raise web.HTTPForbidden(text="Cross-site request refused")
        if turn_on:
            form = await request.post()
            try:
                hours = float(form.get("hours", cloud.max_hours))
            except ValueError:
                raise web.HTTPBadRequest(text="hours must be a number")
            cloud.turn_on(hours)
        else:
            cloud.turn_off()
        await cloud.notify()
        on_change()
        raise web.HTTPSeeOther(_base(request))

    async def cloud_on(request):
        return await change_cloud(request, True)

    async def cloud_off(request):
        return await change_cloud(request, False)

    async def api_status(request: web.Request) -> web.Response:
        return web.json_response(payload())

    @web.middleware
    async def only_allowed(request, handler):
        if allowed is not None and request.remote not in allowed:
            log.warning("Refused a web request from %s", request.remote)
            raise web.HTTPForbidden(text="Use the Washer (admin) page in Home Assistant")
        return await handler(request)

    app = web.Application(middlewares=[only_allowed])
    app.add_routes([web.get("/", index), web.post("/cloud/on", cloud_on),
                    web.post("/cloud/off", cloud_off), web.get("/api/status", api_status)])
    return app


async def start_web(state, cloud, store, device, host: str, port: int,
                    on_change: Callable[[], None] = lambda: None,
                    allowed: set[str] | None = None) -> web.AppRunner:
    runner = web.AppRunner(make_app(state, cloud, store, device, on_change, allowed))
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner
