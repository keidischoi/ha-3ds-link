/* 3DSSync cards + sidebar panel (0.6.0) — printers, filament stock, storage boxes and connected sensors from your 3DS site.
 * Reads the 3DSSync sensors (attribute "g7" marks them), so it needs no setup: add "3DSSync" from the card picker.
 *   type: custom:g7-3dssync-card          everything
 *   show: [summary, printers, stock, boxes, sensors]   (optional — pick parts)
 *   type: custom:g7-3dssync-printer-card | g7-3dssync-stock-card | g7-3dssync-sensors-card   one part
 */
(() => {
  const VER = "0.6.1";
  const T = {
    ko: { printers: "프린터", stock: "필라멘트 재고", boxes: "보관함", sensors: "연결된 센서", rolls: "롤", all: "모두 보기", less: "접기",
      idle: "대기", printing: "출력 중", paused: "일시 정지", done: "끝남", failed: "실패", offline: "꺼짐", left: "남음", nozzle: "노즐", bed: "베드",
      unread: "알림", orders: "주문", bids: "입찰", low: "조금 남음", live: "통신 중", lost: "끊김", never: "안 옴", none: "아직 없어요",
      over: "습도 높음", nodata: "3DSSync 센서를 찾지 못했어요 — 통합을 먼저 연결하세요.", ago_m: "분 전", ago_h: "시간 전", ago_d: "일 전", now: "방금", min: "분", h: "시간", company: "업체" },
    en: { printers: "Printers", stock: "Filament stock", boxes: "Storage boxes", sensors: "Connected sensors", rolls: "rolls", all: "Show all", less: "Show less",
      idle: "Idle", printing: "Printing", paused: "Paused", done: "Done", failed: "Failed", offline: "Off", left: "left", nozzle: "Nozzle", bed: "Bed",
      unread: "Notices", orders: "Orders", bids: "Bids", low: "Low", live: "Live", lost: "Lost", never: "Never", none: "Nothing yet",
      over: "Too humid", nodata: "No 3DSSync sensors found — set up the integration first.", ago_m: "min ago", ago_h: "h ago", ago_d: "d ago", now: "just now", min: "min", h: "h", company: "Company" },
  };
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v) => (typeof v === "number" && isFinite(v) ? v : null);
  const COLORS = { 흰: "#f4f4f0", 화이트: "#f4f4f0", white: "#f4f4f0", 검: "#222", 블랙: "#222", black: "#222", 빨: "#d33", 레드: "#d33", red: "#d33", 파: "#2f5fd0", 블루: "#2f5fd0", blue: "#2f5fd0",
    초: "#3a9a3a", 그린: "#3a9a3a", green: "#3a9a3a", 노: "#f2c418", 옐로: "#f2c418", yellow: "#f2c418", 주황: "#f08a24", 오렌지: "#f08a24", orange: "#f08a24", 회: "#9a9a9a", 그레이: "#9a9a9a", grey: "#9a9a9a", gray: "#9a9a9a",
    보라: "#8a4fd0", 퍼플: "#8a4fd0", purple: "#8a4fd0", 분홍: "#f28ab0", 핑크: "#f28ab0", pink: "#f28ab0", 갈: "#8a5a2b", 브라운: "#8a5a2b", brown: "#8a5a2b", 은: "#c8ccd2", 실버: "#c8ccd2", silver: "#c8ccd2", 금: "#d4af37", 골드: "#d4af37", gold: "#d4af37",
    투명: "#dfeef5", clear: "#dfeef5", 하늘: "#7cc4f0", 민트: "#8fe0c8", 남: "#23306b", 네이비: "#23306b" };
  const colorOf = (s) => {
    if (s.hex) return s.hex;
    const c = String(s.color || "").toLowerCase();
    for (const k in COLORS) if (c.includes(k)) return COLORS[k];
    return "#b9bec6";
  };
  const spoolSvg = (hex, pct, size = 34) => {
    const r = 15, fill = Math.max(4, Math.min(15, 5 + (pct ?? 100) / 10));
    return `<svg width="${size}" height="${size}" viewBox="0 0 34 34" aria-hidden="true"><circle cx="17" cy="17" r="${r + 1}" fill="#8b9099"/><circle cx="17" cy="17" r="${r}" fill="#d9dce1"/>` +
      `<circle cx="17" cy="17" r="${fill}" fill="${esc(hex)}" stroke="rgba(0,0,0,.18)" stroke-width=".6"/><circle cx="17" cy="17" r="4.4" fill="#5b616b"/><circle cx="17" cy="17" r="1.8" fill="#e8eaee"/></svg>`;
  };
  const printerSvg = (busy) => `<svg viewBox="0 0 64 64" width="56" height="56" aria-hidden="true" class="${busy ? "busy" : ""}">
    <rect x="6" y="6" width="52" height="52" rx="7" fill="var(--g7-soft)" stroke="var(--g7-line)"/>
    <rect x="12" y="11" width="40" height="4" rx="2" fill="var(--g7-dim)"/>
    <g class="head"><rect x="27" y="15" width="10" height="9" rx="2" fill="var(--g7-accent)"/><path d="M30 24h4l-2 4z" fill="var(--g7-dim)"/></g>
    <rect x="15" y="46" width="34" height="4" rx="1.5" fill="var(--g7-dim)"/>
    <rect class="part" x="25" y="${busy ? 38 : 44}" width="14" height="${busy ? 8 : 2}" rx="1" fill="var(--g7-accent)" opacity=".55"/></svg>`;

  const CSS = `:host{--g7-accent:var(--primary-color,#e0902a);--g7-text:var(--primary-text-color,#1b1f27);--g7-dim:var(--secondary-text-color,#6b7280);--g7-line:var(--divider-color,rgba(0,0,0,.1));--g7-soft:var(--secondary-background-color,#f2f3f5);--g7-ok:var(--success-color,#2e9d55);--g7-bad:var(--error-color,#d33)}
    ha-card{padding:16px;overflow:hidden}.sec{margin-top:14px}.sec:first-child{margin-top:0}
    h3{margin:0 0 10px;font-size:.78rem;letter-spacing:.06em;text-transform:uppercase;color:var(--g7-dim);font-weight:600;display:flex;justify-content:space-between;align-items:baseline}
    h3 b{font-size:.8rem;text-transform:none;letter-spacing:0;color:var(--g7-dim);font-weight:500}
    .chips{display:flex;flex-wrap:wrap;gap:8px}.chip{display:flex;align-items:center;gap:6px;background:var(--g7-soft);border-radius:999px;padding:6px 12px;font-size:.88rem;color:var(--g7-text)}
    .chip strong{font-size:1rem}.chip.hot{background:color-mix(in srgb,var(--g7-accent) 18%,transparent)}
    .pr{display:flex;gap:12px;padding:12px;border:1px solid var(--g7-line);border-radius:14px;margin-bottom:10px;align-items:flex-start}
    .pr img{width:56px;height:56px;object-fit:contain;border-radius:10px;background:var(--g7-soft)}
    .pr .b{flex:1;min-width:0}.pr .n{font-weight:600;color:var(--g7-text);display:flex;justify-content:space-between;gap:8px}
    .pr .m{font-size:.82rem;color:var(--g7-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .pill{font-size:.75rem;font-weight:600;border-radius:999px;padding:2px 9px;background:var(--g7-soft);color:var(--g7-dim);white-space:nowrap}
    .pill.printing{background:color-mix(in srgb,var(--g7-accent) 20%,transparent);color:var(--g7-accent)}.pill.done{background:color-mix(in srgb,var(--g7-ok) 18%,transparent);color:var(--g7-ok)}
    .pill.failed{background:color-mix(in srgb,var(--g7-bad) 15%,transparent);color:var(--g7-bad)}
    .job{font-size:.85rem;color:var(--g7-text);margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .bar{height:5px;border-radius:3px;background:var(--g7-soft);overflow:hidden;margin-top:5px}.bar i{display:block;height:100%;background:var(--g7-accent);border-radius:3px}
    .bar.low i{background:var(--g7-bad)}
    .row2{display:flex;justify-content:space-between;font-size:.78rem;color:var(--g7-dim);margin-top:3px}
    .temps{display:flex;gap:6px;margin-top:8px}.temps span{font-size:.78rem;background:var(--g7-soft);border-radius:8px;padding:3px 8px;color:var(--g7-text)}
    svg.busy .head{animation:g7slide 2.4s ease-in-out infinite}@keyframes g7slide{0%,100%{transform:translateX(-9px)}50%{transform:translateX(9px)}}
    .big{display:flex;justify-content:space-between;align-items:baseline;margin:-4px 0 6px}.big strong{font-size:2rem;color:var(--g7-text)}.big small{font-size:.9rem;color:var(--g7-dim)}
    .sp{display:flex;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--g7-line)}.sp:last-of-type{border-bottom:0}
    .sp .b{flex:1;min-width:0}.sp .t{font-weight:600;font-size:.92rem;color:var(--g7-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .sp .s{font-size:.78rem;color:var(--g7-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sp .s em{font-style:normal;color:var(--g7-accent)}
    .sp .g{text-align:right;width:76px;font-weight:600;font-size:.9rem;color:var(--g7-text)}
    .more{width:100%;margin-top:8px;padding:9px;border-radius:10px;border:1px solid var(--g7-line);background:none;color:var(--g7-accent);font-weight:600;cursor:pointer;font:inherit}
    .boxes{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px}
    .bx{border:1px solid var(--g7-line);border-radius:12px;padding:10px}.bx.over{border-color:var(--g7-bad);background:color-mix(in srgb,var(--g7-bad) 7%,transparent)}
    .bx .t{font-weight:600;font-size:.88rem;color:var(--g7-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .bx .h{display:flex;align-items:center;gap:4px;font-size:1.25rem;font-weight:700;color:var(--g7-text);margin:4px 0 2px}.bx.over .h{color:var(--g7-bad)}
    .bx .s{font-size:.75rem;color:var(--g7-dim)}.bx .s.warn{color:var(--g7-bad);font-weight:600;margin-top:2px}
    .dv{display:flex;gap:10px;align-items:center;padding:7px 0;border-bottom:1px solid var(--g7-line)}.dv:last-of-type{border-bottom:0}
    .dot{width:10px;height:10px;border-radius:50%;background:var(--g7-dim);flex:none;opacity:.5}.dot.on{background:var(--g7-ok);opacity:1;box-shadow:0 0 0 3px color-mix(in srgb,var(--g7-ok) 22%,transparent)}
    .dv .b{flex:1;min-width:0}.dv .t{font-size:.9rem;font-weight:600;color:var(--g7-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .dv .s{font-size:.76rem;color:var(--g7-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .dv .v{text-align:right;font-size:.85rem;color:var(--g7-text);white-space:nowrap}.dv .v small{display:block;font-size:.72rem;color:var(--g7-dim)}
    .dv.over .v{color:var(--g7-bad)}
    .src{font-size:.68rem;border:1px solid var(--g7-line);border-radius:6px;padding:0 5px;margin-left:4px;color:var(--g7-dim);font-weight:500}
    .empty{color:var(--g7-dim);font-size:.85rem;padding:6px 0}`;

  const SECTIONS = ["summary", "printers", "stock", "boxes", "sensors"];

  class G7Card extends HTMLElement {
    static getStubConfig() { return {}; }
    setConfig(cfg) {
      this._cfg = cfg || {};
      this._show = Array.isArray(this._cfg.show) && this._cfg.show.length ? this._cfg.show : this.constructor.DEFAULT || SECTIONS;
      this._open = this._open || {};
      if (this._hass) this._render();
    }
    set hass(h) {
      const prev = this._hass;
      this._hass = h;
      const sig = this._sig(h);
      if (!prev || sig !== this._lastSig) { this._lastSig = sig; this._render(); }
    }
    getCardSize() { return 3 + this._show.length * 2; }
    _sig(h) {   // re-render only when one of our sensors changed
      return this._ours(h).map((s) => s.entity_id + s.last_updated).join("|");
    }
    _ours(h) {
      const out = [];
      for (const id in (h && h.states) || {}) {
        const s = h.states[id];
        if (id.startsWith("sensor.") && s.attributes && s.attributes.g7) out.push(s);
      }
      return out;
    }
    _t() { return T[String((this._hass && this._hass.language) || "en").startsWith("ko") ? "ko" : "en"]; }
    _data() {
      // 0.6.1 several sites (mini PC · NAS …): the configured one, else the one with the most to show
      const all = this._ours(this._hass), score = {};
      for (const s of all) {
        const a = s.attributes, k = a.site || "";
        score[k] = (score[k] || 0) + 1 + ((a.devices || []).length + (a.spools || []).length + (a.printers || []).length) * 2;
      }
      const site = this._cfg.site || Object.keys(score).sort((x, y) => score[y] - score[x])[0];
      const by = {}, boxes = [];
      for (const s of all) {
        if (s.attributes.site !== site || s.attributes.g7 === "site_device") continue;
        if (s.attributes.g7 === "box") boxes.push(s); else if (!by[s.attributes.g7]) by[s.attributes.g7] = s;
      }
      return { by, boxes };
    }
    _render() {
      if (!this.shadowRoot) this.attachShadow({ mode: "open" });
      const L = this._t(), { by, boxes } = this._data();
      const parts = Object.keys(by).length ? this._show.map((k) => this["_" + k] ? this["_" + k](L, by, boxes) : "").join("") : `<div class="empty">${esc(L.nodata)}</div>`;
      this.shadowRoot.innerHTML = `<style>${CSS}</style><ha-card>${parts}</ha-card>`;
      this.shadowRoot.querySelectorAll("[data-more]").forEach((b) => b.addEventListener("click", () => { const k = b.dataset.more; this._open[k] = !this._open[k]; this._render(); }));
      this.shadowRoot.querySelectorAll("[data-ent]").forEach((el) => el.addEventListener("click", () => {
        this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId: el.dataset.ent } }));
      }));
    }
    _val(s) { const n = Number(s && s.state); return isFinite(n) ? n : 0; }
    _ago(v, L) {
      if (!v) return "";
      const t = Date.parse(String(v).replace(" ", "T"));
      if (!isFinite(t)) return "";
      const m = Math.max(0, Math.round((Date.now() - t) / 60000));
      return m < 1 ? L.now : m < 60 ? `${m}${L.ago_m}` : m < 1440 ? `${Math.round(m / 60)}${L.ago_h}` : `${Math.round(m / 1440)}${L.ago_d}`;
    }

    _summary(L, by) {
      const c = (k, icon, label) => by[k] ? `<span class="chip ${this._val(by[k]) > 0 ? "hot" : ""}" data-ent="${esc(by[k].entity_id)}" style="cursor:pointer">${icon} ${esc(label)} <strong>${this._val(by[k])}</strong></span>` : "";
      return `<div class="sec"><div class="chips">${c("unread", "🔔", L.unread)}${c("orders_active", "🛒", L.orders)}${c("bids_waiting", "🔨", L.bids)}${c("filament_low", "🧵", L.low)}</div></div>`;
    }

    _printers(L, by) {
      const s = by.printers; if (!s) return "";
      const list = s.attributes.printers || [];
      const rows = list.map((p) => {
        const busy = p.state === "printing" || p.state === "paused", prog = num(p.progress);
        const img = p.image ? `<img src="${esc(p.image)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : printerSvg(p.state === "printing");
        const left = num(p.left_min) !== null ? (p.left_min >= 60 ? `${Math.floor(p.left_min / 60)}${L.h} ${p.left_min % 60}${L.min}` : `${p.left_min}${L.min}`) + " " + L.left : "";
        const temps = [num(p.nozzle) !== null ? `<span>🔥 ${esc(L.nozzle)} ${Math.round(p.nozzle)}°C</span>` : "", num(p.bed) !== null ? `<span>▤ ${esc(L.bed)} ${Math.round(p.bed)}°C</span>` : ""].join("");
        return `<div class="pr">${img}<div class="b"><div class="n"><span>${esc(p.name)}</span><span class="pill ${esc(p.state)}">${esc(L[p.state] || p.state)}</span></div>
          <div class="m">${esc(p.model)}</div>
          ${busy ? `<div class="job">${esc(p.job || "")}</div><div class="bar"><i style="width:${prog ?? 0}%"></i></div><div class="row2"><span>${prog !== null ? prog.toFixed(prog % 1 ? 1 : 0) + "%" : ""}</span><span>${esc(left)}</span></div>` : ""}
          ${temps ? `<div class="temps">${temps}</div>` : ""}</div></div>`;
      }).join("");
      return `<div class="sec"><h3>🖨️ ${esc(L.printers)} <b>${list.length}</b></h3>${rows || `<div class="empty">${esc(L.none)}</div>`}</div>`;
    }

    _stock(L, by) {
      const s = by.filament_total; if (!s) return "";
      const list = s.attributes.spools || [], grams = num(s.attributes.grams), open = this._open.stock;
      const shown = open ? list : list.slice(0, 8);
      const rows = shown.map((p) => `<div class="sp">${spoolSvg(colorOf(p), p.pct)}<div class="b"><div class="t">${esc([p.material, p.color].filter(Boolean).join(" · "))}</div>
        <div class="s">${[p.brand ? esc(p.brand) : "", p.box ? `<em>${esc(p.box)}</em>` : ""].filter(Boolean).join(" · ") || "&nbsp;"}</div></div>
        <div class="g">${num(p.grams) !== null ? p.grams.toLocaleString() + " g" : p.pct + "%"}<div class="bar ${p.low ? "low" : ""}"><i style="width:${Math.max(3, Math.min(100, p.pct))}%"></i></div></div></div>`).join("");
      const big = grams ? `<strong>${(grams / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}</strong> <small>kg</small>` : `<strong>${this._val(s)}</strong> <small>${esc(L.rolls)}</small>`;
      return `<div class="sec"><h3>🧵 ${esc(L.stock)}</h3><div class="big"><span>${big}</span><small>${this._val(s)} ${esc(L.rolls)}</small></div>${rows || `<div class="empty">${esc(L.none)}</div>`}
        ${list.length > 8 ? `<button class="more" data-more="stock">${open ? esc(L.less) : `${esc(L.all)} (${list.length})`}</button>` : ""}</div>`;
    }

    _boxes(L, by, boxes) {
      if (!boxes.length) return "";
      const tiles = boxes.map((s) => {
        const a = s.attributes, h = num(a.humidity), t = num(a.temp);
        return `<div class="bx ${a.over ? "over" : ""}" data-ent="${esc(s.entity_id)}" style="cursor:pointer"><div class="t">📦 ${esc(a.name || s.attributes.friendly_name)}</div>
          <div class="h">💧 ${h !== null ? Math.round(h) + "%" : "—"}</div>
          <div class="s">${t !== null ? `🌡 ${t.toFixed(1)}°C · ` : ""}🧵 ${this._val(s)} ${esc(L.rolls)}${a.low ? ` (${esc(L.low)} ${a.low})` : ""}</div>${a.over ? `<div class="s warn">⚠ ${esc(L.over)}</div>` : ""}</div>`;
      }).join("");
      return `<div class="sec"><h3>📦 ${esc(L.boxes)} <b>${boxes.length}</b></h3><div class="boxes">${tiles}</div></div>`;
    }

    _sensors(L, by) {
      const s = by.devices; if (!s) return "";
      const list = (s.attributes.devices || []).slice().sort((a, b) => (b.live - a.live) || String(a.name).localeCompare(String(b.name)));
      const open = this._open.sensors, shown = open ? list : list.slice(0, 10);
      const SRC = { ha: "HA", smartthings: "ST", st: "ST", matter: "Matter", mqtt: "MQTT", ble: "BLE", app: "App" };
      const rows = shown.map((d) => {
        const vals = [num(d.temp) !== null ? `${Number(d.temp).toFixed(1)}°C` : "", num(d.humidity) !== null ? `${Math.round(d.humidity)}%` : ""].filter(Boolean).join(" · ") || esc(d.state || "");
        const where = [d.company ? L.company : "", d.where, d.server].filter(Boolean).join(" · ");
        return `<div class="dv ${d.over ? "over" : ""}"><span class="dot ${d.live ? "on" : ""}" title="${esc(d.live ? L.live : d.never ? L.never : L.lost)}"></span>
          <div class="b"><div class="t">${esc(d.name)}${d.source ? `<span class="src">${esc(SRC[d.source] || d.source)}</span>` : ""}</div><div class="s">${esc(where)}</div></div>
          <div class="v">${vals}<small>${d.never ? esc(L.never) : esc(this._ago(d.seen, L))}</small></div></div>`;
      }).join("");
      const live = list.filter((d) => d.live).length;
      return `<div class="sec"><h3>📡 ${esc(L.sensors)} <b>${esc(L.live)} ${live} / ${list.length}</b></h3>${rows || `<div class="empty">${esc(L.none)}</div>`}
        ${list.length > 10 ? `<button class="more" data-more="sensors">${open ? esc(L.less) : `${esc(L.all)} (${list.length})`}</button>` : ""}</div>`;
    }
  }

  const def = (name, DEFAULT, title, desc) => {
    if (customElements.get(name)) return;
    customElements.define(name, class extends G7Card { static get DEFAULT() { return DEFAULT; } });
    (window.customCards = window.customCards || []).push({ type: name, name: title, description: desc, preview: true, documentationURL: "https://github.com/keidischoi/ha-3ds-link" });
  };
  def("g7-3dssync-card", SECTIONS, "3DSSync", "Printers, filament stock, storage boxes and connected sensors from your 3DS site");
  def("g7-3dssync-printer-card", ["printers"], "3DSSync — printers", "Your printers with progress and temperatures");
  def("g7-3dssync-stock-card", ["stock"], "3DSSync — filament stock", "Every spool in its colour with what is left");
  def("g7-3dssync-sensors-card", ["boxes", "sensors"], "3DSSync — sensors", "Storage boxes and which sensors are talking to the site");

  // sidebar panel: the same parts on a wide grid
  if (!customElements.get("g7-3dssync-panel")) {
    customElements.define("g7-3dssync-panel", class extends HTMLElement {
      set hass(h) {
        this._hass = h;
        if (!this._built) {
          this._built = true;
          this.innerHTML = `<style>g7-3dssync-panel{display:block;min-height:100vh;background:var(--primary-background-color)}
            .g7p-top{display:flex;align-items:center;gap:10px;height:56px;padding:0 16px;background:var(--app-header-background-color,var(--primary-color));color:var(--app-header-text-color,#fff);font-size:20px}
            .g7p-top button{background:none;border:0;color:inherit;font-size:22px;cursor:pointer;padding:6px}
            .g7p{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px;padding:16px;max-width:1400px;margin:0 auto;align-items:start}
            .g7p>div{display:grid;gap:16px}</style>
            <div class="g7p-top"><button title="Menu">☰</button><span>3DSSync</span><small style="opacity:.7;font-size:12px">${VER}</small></div>
            <div class="g7p"><div><g7-3dssync-card data-s="summary,printers"></g7-3dssync-card><g7-3dssync-card data-s="boxes"></g7-3dssync-card></div>
            <div><g7-3dssync-card data-s="stock"></g7-3dssync-card></div><div><g7-3dssync-card data-s="sensors"></g7-3dssync-card></div></div>`;
          this.querySelector(".g7p-top button").addEventListener("click", () => this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true })));
          this.querySelectorAll("g7-3dssync-card").forEach((c) => c.setConfig({ show: c.dataset.s.split(",") }));
        }
        this.querySelectorAll("g7-3dssync-card").forEach((c) => { c.hass = h; });
      }
      set narrow(v) { this._narrow = v; }
      set panel(v) { this._panel = v; }
    });
  }
  console.info(`%c 3DSSync %c ${VER} `, "background:#e0902a;color:#fff;border-radius:3px 0 0 3px", "background:#333;color:#fff;border-radius:0 3px 3px 0");
})();
