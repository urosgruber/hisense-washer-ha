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

c.hass = hass({ "sensor.phase": "washing", "sensor.minutes_left": "68", "sensor.end_time": inMinutes(68),
  "sensor.program": "Synthetics", "sensor.temperature": "40", "sensor.spin_speed": "1000",
  "binary_sensor.door_locked": "on", "sensor.quicker": "2", "binary_sensor.steam": "off",
  "binary_sensor.extra_rinse": "on", "binary_sensor.pre_wash": "on",
  "binary_sensor.anti_crease": "on", "binary_sensor.cold_wash": "off" });
check("shows the program, temperature and spin", html().includes("Synthetics · 40 °C · 1000 rpm"));
check("shows the door lock icon", html().includes("mdi:lock"));
check("shows the options that are on", html().includes("Quicker 2") && html().includes("Extra rinse")
  && !html().includes(">Steam<"));
check("shows pre-wash and anti crease, not cold wash", html().includes(">Pre-wash<")
  && html().includes(">Anti crease<") && !html().includes(">Cold wash<"));
check("shows the connection icon when connected", html().includes("mdi:wifi\""));

c.hass = hass({ "sensor.phase": "idle", "sensor.program": "Auto", "sensor.temperature": "0",
  "sensor.spin_speed": "0" });
check("cold and no spin read as words", html().includes("Auto · Cold · No spin"));

c.hass = hass({ "sensor.phase": "idle", "sensor.program": "Eco 40-60", "sensor.temperature": "0",
  "sensor.spin_speed": "1400" });
check("Eco hides the temperature", html().includes("Eco 40-60 · 1400 rpm"));

c.hass = hass({ "sensor.phase": "delayed", "sensor.minutes_left": "300", "sensor.end_time": inMinutes(300) });
check("delayed shows when it ends", html().includes("Delay start") && html().includes("Ends at")
  && html().includes("5 h 0 min"));

// A tap on the icon or name: admins go to the device page, others get more-info.
const pushed = [];
global.history = { pushState: (_s, _t, url) => pushed.push(url) };
window.dispatchEvent = () => {};
global.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
const events = [];
c.dispatchEvent = (e) => events.push(e);
const h = hass();
h.entities = { [`sensor.${P}_phase`]: { device_id: "dev123" } };
c.hass = { ...h, user: { is_admin: true } };
c._openDevice();
check("an admin tap opens the device page", pushed[0] === "/config/devices/device/dev123");
c.hass = { ...h, user: { is_admin: false } };
c._openDevice();
check("a non-admin tap opens more-info", events.some((e) => e.type === "hass-more-info"
  && e.detail.entityId === `sensor.${P}_phase`));
check("the icon and name are clickable", html().includes('id="open-device"') && html().includes('id="open-device-name"'));

const c2 = new Card();
c2.setConfig({});
c2.hass = { states: {}, locale: { language: "en" } };
check("missing entities explain the problem", c2.shadowRoot.innerHTML.includes("not found"));
