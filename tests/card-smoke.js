// Smoke test for dist/hisense-washer-card.js, outside a browser:
//   node tests/card-smoke.js dist/hisense-washer-card.js
// It renders the card in several washer states with fake entities and
// checks the HTML. CI runs it on every push.
global.window = { addEventListener() {}, customCards: [] };
global.HTMLElement = class { dispatchEvent() {} };
let Card;
global.customElements = { define: (_, c) => { Card = c; } };
const root = () => ({ html: "", set innerHTML(v) { this.html = v; }, get innerHTML() { return this.html; },
  querySelector: () => null, addEventListener() {} });
HTMLElement.prototype.attachShadow = function () { this.shadowRoot = root(); return this.shadowRoot; };
require(require("path").resolve(process.argv[2]));

const P = "hisense_washer";
const st = (v, a = {}) => ({ state: v, attributes: a });
const inMinutes = (m) => new Date(Date.now() + m * 60000).toISOString();

function hass(over = {}, lastCycle = null) {
  const v = {
    "sensor.phase": "idle", "sensor.minutes_left": "218", "sensor.end_time": "unknown",
    "sensor.cycle_energy": "0.0", "sensor.cycle_water": "0.0", "binary_sensor.connected": "on",
    "binary_sensor.door_locked": "off", "sensor.cloud": "off", ...over,
  };
  const states = {};
  for (const [k, x] of Object.entries(v)) { const [d, n] = k.split("."); states[`${d}.${P}_${n}`] = st(x); }
  states[`event.${P}_cycle`] = lastCycle
    ? st("2026-11-06T18:45:34.000+00:00", { event_type: "done", ...lastCycle })
    : st("unknown", {});
  return { states, locale: { language: "en" } };
}

const c = new Card();
c.setConfig({ type: "custom:hisense-washer-card" });
const html = () => c.shadowRoot.innerHTML;
const check = (name, ok) => { console.log(`${ok ? "ok  " : "FAIL"} ${name}`); if (!ok) process.exitCode = 1; };

c.hass = hass({ "sensor.phase": "washing", "sensor.minutes_left": "37", "sensor.end_time": inMinutes(37),
  "sensor.cycle_energy": "0.2", "sensor.cycle_water": "7.84", "binary_sensor.door_locked": "on" });
check("washing shows the end time", html().includes("Ends at"));
check("washing shows the minutes left", html().includes("37 min left"));
check("washing shows the phase name", html().includes("Washing"));
check("washing marks the wash step", /class="step on"[^>]*>[^<]*Wash/.test(html()));
check("washing shows this wash's water", html().includes("7.84 L"));

c.hass = hass({ "sensor.phase": "spinning", "sensor.minutes_left": "5", "sensor.end_time": inMinutes(5) });
check("spinning marks wash and rinse done", (html().match(/class="step done"/g) || []).length === 2);

c.hass = hass({ "sensor.phase": "idle" }, { energy_kwh: 0.45, water_l: 54.76, confirmed: true });
check("idle shows the last wash", html().includes("Last wash") && html().includes("0.45 kWh") && html().includes("54.76 L"));
check("idle shows no end time", !html().includes("Ends at"));

c.hass = hass({ "sensor.phase": "done" }, { energy_kwh: 0.45, water_l: 54.76, confirmed: true });
check("done renders", html().includes("Done"));

c.hass = hass({ "sensor.phase": "delayed", "sensor.minutes_left": "240" });
check("delayed renders", html().includes("Delay start"));

c.hass = hass({ "sensor.phase": "washing", "sensor.minutes_left": "20", "sensor.end_time": inMinutes(20),
  "binary_sensor.connected": "off" });
check("a drop keeps the end time and says No connection", html().includes("No connection") && html().includes("Ends at"));

c.hass = hass({ "sensor.cloud": "on until 21:30" });
check("cloud on shows the cloud mark", html().includes("Cloud on until 21:30"));

c.hass = hass({ "sensor.phase": "unavailable" });
check("unavailable renders without a crash", html().includes("Washer"));

const c2 = new Card();
c2.setConfig({});
c2.hass = { states: {}, locale: { language: "en" } };
check("missing entities explain the problem", c2.shadowRoot.innerHTML.includes("not found"));
