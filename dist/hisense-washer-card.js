// Hisense Washer card for Home Assistant. Read-only: it shows when the wash
// ends, the phase, and the energy and water. It reads the MQTT entities of
// the Hisense Washer app. Visual language follows the Anova Oven card.
//
//   type: custom:hisense-washer-card
//   prefix: hisense_washer      # optional, the entity id prefix
//   name: Washer                # optional

const PHASE_NAMES = {
  off: "Off", idle: "Idle", delayed: "Delay start", washing: "Washing", rinsing: "Rinsing",
  spinning: "Spinning", done: "Done", unknown: "Unknown",
};
const STEPS = [["washing", "Wash"], ["rinsing", "Rinse"], ["spinning", "Spin"]];
const RUNNING = new Set(["washing", "rinsing", "spinning"]);
const WATCHED = ["sensor.phase", "sensor.minutes_left", "sensor.end_time", "sensor.cycle_energy",
  "sensor.cycle_water", "binary_sensor.connected", "binary_sensor.door_locked", "sensor.cloud",
  "event.cycle"];

const esc = (s) => String(s).replace(/[&<>"']/g, (ch) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

class HisenseWasherCard extends HTMLElement {
  static getStubConfig() {
    return { prefix: "hisense_washer" };
  }

  setConfig(config) {
    this._config = { prefix: "hisense_washer", name: "Washer", ...config };
    this._watch = WATCHED.map((w) => this._id(...w.split(".")));
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  set hass(hass) {
    const before = this._hass;
    this._hass = hass;
    if (!before || this._watch.some((id) => before.states[id] !== hass.states[id])) this._render();
  }

  getCardSize() {
    return 3;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: 3, min_rows: 3 };
  }

  _id(domain, name) {
    return `${domain}.${this._config.prefix}_${name}`;
  }

  _state(domain, name) {
    const s = this._hass && this._hass.states[this._id(domain, name)];
    return s ? s : null;
  }

  _value(domain, name) {
    const s = this._state(domain, name);
    if (!s || s.state === "unknown" || s.state === "unavailable") return null;
    return s.state;
  }

  _time(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    const lang = (this._hass && this._hass.locale && this._hass.locale.language) || undefined;
    return d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    if (!this._hass) {
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card><div class="secondary">Loading…</div></ha-card>`;
      return;
    }
    const phaseState = this._state("sensor", "phase");
    if (!phaseState) {
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card><div class="secondary warn">
        Entity ${esc(this._id("sensor", "phase"))} not found. Is the Hisense Washer app running with MQTT on?
        </div></ha-card>`;
      return;
    }
    const phase = this._value("sensor", "phase") || "off";
    const running = RUNNING.has(phase);
    const connected = this._value("binary_sensor", "connected") === "on";
    const locked = this._value("binary_sensor", "door_locked") === "on";
    const minutes = this._value("sensor", "minutes_left");
    const endIso = this._value("sensor", "end_time");
    const cloud = this._value("sensor", "cloud") || "off";
    const energy = Number(this._value("sensor", "cycle_energy") || 0);
    const water = Number(this._value("sensor", "cycle_water") || 0);
    const last = this._state("event", "cycle");
    const lastAttrs = last && last.attributes && last.attributes.event_type ? last.attributes : null;

    const tone = running ? "active" : phase === "done" ? "done" : "";
    const status = [PHASE_NAMES[phase] || phase];
    if (running && locked) status.push("door locked");

    let main;
    if (running && endIso) {
      main = `<div class="big"><span class="label">Ends at</span>
          <span class="value">${esc(this._time(endIso) || "–")}</span></div>
        <div class="big right"><span class="label">Time left</span>
          <span class="value">${minutes !== null ? `${esc(minutes)} min left` : "–"}</span></div>`;
    } else if (phase === "delayed") {
      main = `<div class="big"><span class="label">Delay start</span>
          <span class="value">Waiting</span></div>`;
    } else if (lastAttrs) {
      const when = this._time(last.state);
      main = `<div class="big"><span class="label">Last wash${when ? ` · ended ${esc(when)}` : ""}</span>
          <span class="value">${Number(lastAttrs.energy_kwh || 0).toFixed(2)} kWh · ${Number(lastAttrs.water_l || 0).toFixed(2)} L</span></div>`;
    } else {
      main = `<div class="big"><span class="label">Washer</span>
          <span class="value">${esc(PHASE_NAMES[phase] || phase)}</span></div>`;
    }

    const idx = STEPS.findIndex(([p]) => p === phase);
    const steps = STEPS.map(([p, label], i) => {
      let cls = "step";
      if (phase === "done" || (idx >= 0 && i < idx)) cls += " done";
      else if (i === idx) cls += " on";
      return `<div class="${cls}">${phase === "done" || (idx >= 0 && i < idx) ? "✓ " : ""}${label}</div>`;
    }).join("");

    const icons = [];
    if (!connected) {
      icons.push(`<div class="icon-state warn" title="No connection"><ha-icon icon="mdi:wifi-off"></ha-icon></div>`);
    }
    if (cloud.startsWith("on")) {
      icons.push(`<div class="icon-state warn" title="Cloud ${esc(cloud.slice(3))}"><ha-icon icon="mdi:cloud-outline"></ha-icon></div>`);
    }

    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <ha-card class="${tone}">
        <div class="header">
          <div class="shape"><ha-icon icon="mdi:washing-machine"></ha-icon></div>
          <div class="info">
            <div class="primary">${esc(this._config.name)}</div>
            <div class="secondary">${esc(status.join(" · "))}${!connected ? " · No connection" : ""}${cloud.startsWith("on") ? ` · Cloud ${esc(cloud)}` : ""}</div>
          </div>
          ${icons.join("")}
        </div>
        <div class="feature tile">${main}</div>
        ${running || phase === "done" ? `<div class="feature steps">${steps}</div>` : ""}
        ${running ? `<div class="footer">This wash: ${energy.toFixed(2)} kWh · ${water.toFixed(2)} L</div>` : ""}
      </ha-card>`;
  }
}

const STYLE = `
  :host {
    --wash-rgb: 3, 169, 244;
    --done-rgb: var(--rgb-success-color, 76, 175, 80);
    --tone-rgb: var(--rgb-disabled-color, 158, 158, 158);
    --h: var(--feature-height, 42px);
    --r: var(--feature-border-radius, 12px);
    --gap: var(--feature-button-spacing, 12px);
    --track: rgba(var(--rgb-primary-text-color, 33, 33, 33), .06);
    --selected-bg: var(--card-background-color, #fff);
    --selected-shadow: 0 1px 3px rgba(0, 0, 0, .16);
    display: block;
  }
  ha-card { padding: 12px; display: flex; flex-direction: column; gap: var(--gap); height: 100%; box-sizing: border-box; }
  ha-card.active { --tone-rgb: var(--wash-rgb); }
  ha-card.done { --tone-rgb: var(--done-rgb); }
  .header { display: flex; align-items: center; gap: 4px; height: 40px; }
  .shape { flex: none; width: 36px; height: 36px; border-radius: 50%; display: grid; place-items: center;
    background: rgba(var(--tone-rgb), .2); color: rgb(var(--tone-rgb)); }
  .shape ha-icon { --mdc-icon-size: 20px; }
  .info { flex: 1; min-width: 0; margin: 0 6px; }
  .primary { font-size: 14px; font-weight: 500; line-height: 20px; color: var(--primary-text-color); }
  .secondary { font-size: 12px; line-height: 16px; color: var(--secondary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
  .secondary.warn { color: var(--error-color, #db4437); font-weight: 500; white-space: normal; }
  .icon-state { flex: none; width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center;
    color: var(--secondary-text-color); }
  .icon-state ha-icon { --mdc-icon-size: 20px; }
  .icon-state.warn { color: var(--warning-color, #e69500); }
  .feature { border-radius: var(--r); box-sizing: border-box; background: var(--track); }
  .tile { display: flex; align-items: center; justify-content: space-between; gap: var(--gap);
    min-height: calc(var(--h) * 1.6); padding: 8px 14px; }
  .big { display: flex; flex-direction: column; min-width: 0; }
  .big.right { text-align: right; }
  .big .label { font-size: 12px; color: var(--secondary-text-color); }
  .big .value { font-size: 22px; font-weight: 500; color: var(--primary-text-color);
    font-variant-numeric: tabular-nums; white-space: nowrap; }
  .steps { height: var(--h); display: flex; gap: 4px; padding: 4px; }
  .step { flex: 1; display: grid; place-items: center; border-radius: calc(var(--r) - 4px);
    font-size: 13px; font-weight: 500; color: var(--secondary-text-color); }
  .step.on { background: var(--selected-bg); color: var(--primary-text-color); box-shadow: var(--selected-shadow); }
  .footer { font-size: 12px; color: var(--secondary-text-color); padding: 0 4px; font-variant-numeric: tabular-nums; }
`;

customElements.define("hisense-washer-card", HisenseWasherCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "hisense-washer-card",
  name: "Hisense Washer",
  description: "When the wash ends, the phase, and energy and water.",
});
