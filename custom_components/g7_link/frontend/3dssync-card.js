/* 3DSSync cards + sidebar panel (0.6.0) — printers, filament stock, storage boxes and connected sensors from your 3DS site.
 * Reads the 3DSSync sensors (attribute "g7" marks them), so it needs no setup: add "3DSSync" from the card picker.
 *   type: custom:g7-3dssync-card          everything
 *   show: [summary, printers, stock, boxes, sensors]   (optional — pick parts)
 *   box_look: list                       (optional — the earlier text tiles instead of box pictures)
 *   spools: separate                     (optional — box pictures show only temperature · humidity; rolls in the stock list)
 *   type: custom:g7-3dssync-printer-card | g7-3dssync-stock-card | g7-3dssync-sensors-card   one part
 */
(() => {
  const VER = "0.8.13";
  const T = {
    ko: { printers: "프린터", stock: "필라멘트 재고", boxes: "보관함", sensors: "연결된 센서", rolls: "롤", all: "모두 보기", less: "접기",
      idle: "대기", printing: "출력 중", paused: "일시 정지", done: "끝남", failed: "실패", offline: "꺼짐", left: "남음", nozzle: "노즐", bed: "베드",
      unread: "알림", orders: "주문", bids: "입찰", low: "조금 남음", live: "통신 중", lost: "끊김", never: "안 옴", none: "아직 없어요",
      over: "습도 높음", nodata: "3DSSync 센서를 찾지 못했어요 — 통합을 먼저 연결하세요.", ago_m: "분 전", ago_h: "시간 전", ago_d: "일 전", now: "방금", min: "분", h: "시간", company: "업체", inbox: "보관함에 든 {n}롤은 아래 보관함 그림에", outside: "보관함 밖", nosensor: "센서 없음", resin: "레진", bottles: "병" },
    en: { printers: "Printers", stock: "Filament stock", boxes: "Storage boxes", sensors: "Connected sensors", rolls: "rolls", all: "Show all", less: "Show less",
      idle: "Idle", printing: "Printing", paused: "Paused", done: "Done", failed: "Failed", offline: "Off", left: "left", nozzle: "Nozzle", bed: "Bed",
      unread: "Notices", orders: "Orders", bids: "Bids", low: "Low", live: "Live", lost: "Lost", never: "Never", none: "Nothing yet",
      over: "Too humid", nodata: "No 3DSSync sensors found — set up the integration first.", ago_m: "min ago", ago_h: "h ago", ago_d: "d ago", now: "just now", min: "min", h: "h", company: "Company", inbox: "{n} rolls in storage boxes are drawn in the boxes below", outside: "Not in a box", nosensor: "No sensor", resin: "resin", bottles: " bottles" },
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
  // 0.8.4 storage box pictures — the box name picks the look:
  //   건조 · dry · 드라이 (dryer)  → a filament dryer: white body, handle, dark window with the rolls face-on, screen strip
  //   선반 · 랙 · shelf · rack · 진열   → an open wall shelf: rolls standing face-on on a plank, a digital tag on the edge
  //   anything else                    → a clear storage bin: rolls side-on, blue lid with clips, analogue hygrometer dial
  // rolls: real colour, how full = what is left · humidity colour green < 50 · orange ≥ 50 · red (blinks) over the limit · grey no sensor
  let boxN = 0;
  const shade = (hex, k) => {   // lighten (k>0) / darken (k<0) a #rrggbb
    const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || "")); if (!m) return hex;
    const n = parseInt(m[1], 16), c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.round(k > 0 ? v + (255 - v) * k : v * (1 + k)));
    return "#" + c.map((v) => Math.max(0, Math.min(255, v)).toString(16).padStart(2, "0")).join("");
  };
  const boxKind = (name) => {
    const n = String(name || "").toLowerCase();
    if (/건조|드라이|dry/.test(n)) return "dryer";
    if (/선반|랙|진열|shelf|rack/.test(n)) return "shelf";
    return "bin";
  };
  // 0.8.12 warning colours on the picture itself: lid / body / back turn orange (50 %+) or red (over the limit)
  const TONE = { "": { lid: "#5b8def", lid2: "#3f6fd1", tint: "transparent", edge: "rgba(150,165,180,.6)" },
    warn: { lid: "#f59e0b", lid2: "#d97706", tint: "rgba(245,158,11,.16)", edge: "rgba(245,158,11,.85)" },
    bad: { lid: "#ef4444", lid2: "#c53030", tint: "rgba(239,68,68,.22)", edge: "rgba(239,68,68,.9)" } };
  // 0.8.13 🎨 the site's box colour (IoT link 1.19.13+) paints the lid / edges; a humidity warning still wins
  const siteTone = (c) => /^#[0-9a-f]{6}$/i.test(String(c || "")) ? { lid: c, lid2: shade(c, -0.22), tint: c + "14", edge: c } : TONE[""];
  const toneOf = (h, over) => over ? "bad" : h !== null && h >= 50 ? "warn" : "";
  const humCol = (h, over) => h === null ? "#8a929c" : over ? "#ef4444" : h >= 50 ? "#f59e0b" : "#22c55e";
  const pctOf = (p) => Math.max(0, Math.min(100, p.pct ?? 100));
  const shadow = `<ellipse cx="110" cy="127" rx="100" ry="4" fill="rgba(0,0,0,.15)"/>`;
  // a roll seen face-on (dryer window · shelf)
  const faceRoll = (id, p, cx, cy, r, rim) => {
    const col = esc(colorOf(p)), f = r * (0.52 + 0.46 * pctOf(p) / 100);
    return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${rim}"/><circle cx="${cx}" cy="${cy}" r="${f}" fill="${col}"/><circle cx="${cx}" cy="${cy}" r="${f}" fill="url(#${id}r)"/>
      <circle cx="${cx}" cy="${cy}" r="${r * .3}" fill="#2b3038"/><circle cx="${cx}" cy="${cy}" r="${r * .14}" fill="#d7dce2"/>`;
  };
  // 0.8.11 🧪 resin is drawn as a bottle: dark cap, amber body, the resin's colour filled by what is left, a label band
  const isResin = (p) => p && p.kind === "resin";
  const bottle = (x, bot, w, ht, p) => {
    const col = esc(colorOf(p)), capH = ht * 0.16, by = bot - ht + capH, bh = ht - capH, lv = (bh - 3) * (0.1 + 0.9 * pctOf(p) / 100);
    return `<rect x="${x + w * 0.28}" y="${bot - ht}" width="${w * 0.44}" height="${capH + 2}" rx="2" fill="#2b3038"/>
      <rect x="${x}" y="${by}" width="${w}" height="${bh}" rx="${w * 0.18}" fill="rgba(214,150,60,.28)" stroke="rgba(150,100,40,.75)"/>
      <rect x="${x + 1.5}" y="${bot - 1.5 - lv}" width="${w - 3}" height="${lv}" rx="${w * 0.14}" fill="${col}" opacity=".85"/>
      <rect x="${x}" y="${by + bh * 0.34}" width="${w}" height="${bh * 0.2}" fill="rgba(255,255,255,.6)"/>`;
  };
  const bottleSvg = (p, size = 34) => `<svg width="${size}" height="${size}" viewBox="0 0 34 34" aria-hidden="true">${bottle(9, 32, 16, 30, p)}</svg>`;
  const itemSvg = (p, size) => isResin(p) ? bottleSvg(p, size) : spoolSvg(colorOf(p), p.pct, size);
  const rollGrad = (id) => `<radialGradient id="${id}r" cx=".4" cy=".35" r=".7"><stop offset="0" stop-color="#fff" stop-opacity=".35"/><stop offset="1" stop-color="#000" stop-opacity=".2"/></radialGradient>`;

  // 0.8.10 the box's sensor on one line at the top (💧 humidity · 🌡 temperature, side by side), rolls across the full width below;
  // no rolls drawn (spools: separate) → the same line, bigger, in the middle
  let NOSENSOR = "no sensor";
  const readout = (cx, y, h, t, hc, tc, size = 14) => {
    if (h === null && t === null) return `<text x="${cx}" y="${y}" font-size="${size * 0.85}" font-weight="700" text-anchor="middle" fill="#8a929c">📡 ${esc(NOSENSOR)}</text>`;
    return `<text class="lcd" x="${cx}" y="${y}" font-size="${size}" font-weight="800" text-anchor="middle">
      <tspan fill="${hc}">💧${h === null ? "--" : Math.round(h)}<tspan font-size="${size * 0.7}">%</tspan></tspan><tspan dx="${size * 0.6}" fill="${tc}">🌡${t === null ? "--" : t.toFixed(1)}<tspan font-size="${size * 0.7}">°C</tspan></tspan></text>`;
  };

  const binSvg = (id, show, slots, count, h, t, hc, big, tn = TONE[""]) => {
    const X0 = 18, X1 = 202, gap = (X1 - X0) / Math.max(slots, 1), w = Math.min(30, gap - 6), top = 60, ht = 56, mid = top + ht / 2;
    let rolls = "";
    for (let i = 0; i < slots; i++) {
      const p = show[i], x = X0 + gap * i + (gap - w) / 2;
      if (!p) { rolls += `<rect x="${x}" y="${top}" width="${w}" height="${ht}" rx="4" fill="none" stroke="#b8c0ca" stroke-dasharray="3 3"/>`; continue; }
      if (isResin(p)) { rolls += bottle(x, top + ht, w, ht, p); continue; }
      const col = esc(colorOf(p)), fh = 22 + 26 * pctOf(p) / 100, fy = mid - fh / 2;
      let lines = "";
      for (let k = 1; k < 6; k++) lines += `<line x1="${x + 3}" x2="${x + w - 3}" y1="${fy + k * fh / 6}" y2="${fy + k * fh / 6}" stroke="${esc(shade(colorOf(p), -0.25))}" stroke-width=".7"/>`;
      rolls += `<rect x="${x + 3}" y="${fy}" width="${w - 6}" height="${fh}" fill="${col}"/>${lines}<rect x="${x + 3}" y="${fy}" width="${w - 6}" height="${fh}" fill="url(#${id}c)"/>
        <rect x="${x}" y="${top}" width="4" height="${ht}" rx="2" fill="#3a4049"/><rect x="${x + w - 4}" y="${top}" width="4" height="${ht}" rx="2" fill="#3a4049"/>`;
    }
    const more = slots && count > slots ? `<text x="200" y="121" font-size="10" font-weight="700" text-anchor="end" fill="var(--g7-dim)">+${count - slots}</text>` : "";
    const nums = !big ? readout(110, 53, h, t, hc, "var(--g7-text)") : readout(110, 86, h, t, hc, "var(--g7-text)", 22);
    const body = "M10 34 L210 34 L204 120 Q203 124 199 124 L21 124 Q17 124 16 120 Z";
    return `<defs>
      <linearGradient id="${id}c" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#000" stop-opacity=".25"/><stop offset=".35" stop-color="#fff" stop-opacity=".3"/><stop offset="1" stop-color="#000" stop-opacity=".3"/></linearGradient>
      <linearGradient id="${id}g" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#e8f3fb" stop-opacity=".3"/><stop offset=".5" stop-color="#e8f3fb" stop-opacity=".06"/><stop offset="1" stop-color="#e8f3fb" stop-opacity=".22"/></linearGradient></defs>
      ${shadow}<path d="${body}" fill="rgba(214,228,240,.16)" stroke="rgba(150,165,180,.6)"/>${rolls}<path d="${body}" fill="url(#${id}g)" stroke="${tn.edge}"/><path d="${body}" fill="${tn.tint}"/>${nums}
      <rect x="4" y="22" width="212" height="14" rx="5" fill="${tn.lid}"/><rect x="4" y="32" width="212" height="4" fill="${tn.lid2}"/>
      <rect x="30" y="30" width="20" height="16" rx="3" fill="${tn.lid2}"/><rect x="170" y="30" width="20" height="16" rx="3" fill="${tn.lid2}"/>${more}`;
  };

  const dryerSvg = (id, show, slots, count, h, t, hc, big, tn = TONE[""]) => {
    const X0 = 22, X1 = 198, gap = (X1 - X0) / Math.max(slots, 1), cy = 76, r = Math.min(23, gap / 2 - 3);
    let rolls = "";
    for (let i = 0; i < slots; i++) {
      const p = show[i], cx = X0 + gap * i + gap / 2;
      rolls += p ? isResin(p) ? bottle(cx - r * 0.7, cy + r, r * 1.4, r * 2, p) : faceRoll(id, p, cx, cy, r, "#2b3038") : `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#6b7480" stroke-dasharray="3 3"/>`;
    }
    const nums = !big ? readout(110, 44, h, t, hc, "#e5e7eb") : readout(110, 72, h, t, hc, "#e5e7eb", 22);
    return `<defs>${rollGrad(id)}
      <linearGradient id="${id}b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#dfe6ee" stop-opacity=".26"/><stop offset="1" stop-color="#9aa6b2" stop-opacity=".14"/></linearGradient>
      <linearGradient id="${id}g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".35"/><stop offset=".4" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>
      ${shadow}<path d="M78 16 v-6 a6 6 0 0 1 6 -6 h52 a6 6 0 0 1 6 6 v6" fill="none" stroke="#9aa3ad" stroke-width="5" stroke-linecap="round"/>
      <rect x="8" y="14" width="204" height="110" rx="16" fill="url(#${id}b)" stroke="${tn.edge}"/><rect x="8" y="14" width="204" height="110" rx="16" fill="${tn.tint}"/>
      <rect x="18" y="26" width="184" height="76" rx="10" fill="#1d2229"/>${rolls}<rect x="18" y="26" width="184" height="76" rx="10" fill="url(#${id}g)"/>${nums}
      ${slots && count > slots ? `<text x="196" y="44" font-size="10" font-weight="700" text-anchor="end" fill="#cfd5dc">+${count - slots}</text>` : ""}
      <circle cx="58" cy="113.5" r="2.5" fill="${hc}"/><circle cx="164" cy="113.5" r="3.5" fill="rgba(150,165,180,.7)"/><circle cx="176" cy="113.5" r="3.5" fill="rgba(150,165,180,.7)"/>`;
  };

  const shelfSvg = (id, show, slots, count, h, t, hc, big, tn = TONE[""]) => {
    const X0 = 12, X1 = 208, gap = (X1 - X0) / Math.max(slots, 1), r = Math.min(28, gap / 2 - 3), cy = 98 - r;
    let rolls = "";
    for (let i = 0; i < slots; i++) {
      const p = show[i], cx = X0 + gap * i + gap / 2;
      rolls += p ? isResin(p) ? bottle(cx - r * 0.7, cy + r, r * 1.4, r * 2, p) : faceRoll(id, p, cx, cy, r, "#3a4049") : `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#b8c0ca" stroke-dasharray="3 3"/>`;
    }
    const nums = !big ? readout(110, 30, h, t, hc, "var(--g7-text)") : readout(110, 64, h, t, hc, "var(--g7-text)", 22);
    return `<defs>${rollGrad(id)}
      <linearGradient id="${id}w" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d9b48a"/><stop offset="1" stop-color="#a97a4e"/></linearGradient></defs>
      <rect x="4" y="10" width="212" height="88" rx="4" fill="rgba(200,206,214,.16)" stroke="${tn.edge}"/><rect x="4" y="10" width="212" height="88" rx="4" fill="${tn.tint}"/>
      <rect x="12" y="98" width="8" height="22" fill="#8b9099"/><rect x="200" y="98" width="8" height="22" fill="#8b9099"/>
      <path d="M12 110 L28 98 L20 98 Z M208 110 L192 98 L200 98 Z" fill="#8b9099"/>
      ${rolls}${nums}
      ${slots && count > slots ? `<text x="208" y="30" font-size="10" font-weight="700" text-anchor="end" fill="var(--g7-dim)">+${count - slots}</text>` : ""}
      <rect x="2" y="98" width="216" height="10" rx="2" fill="url(#${id}w)"/><rect x="2" y="106" width="216" height="2" fill="rgba(0,0,0,.18)"/>`;
  };

  const boxSvg = (name, spools, count, h, t, over, color) => {
    const id = "g7b" + (++boxN), kind = boxKind(name), max = kind === "bin" ? 5 : 4;
    const show = spools ? spools.slice(0, max) : [], slots = spools ? Math.max(show.length, Math.min(count, max)) : 0;   // 0.8.11 an empty box draws no empty slot
    const draw = kind === "dryer" ? dryerSvg : kind === "shelf" ? shelfSvg : binSvg;
    return `<svg viewBox="0 0 220 132" width="100%" aria-hidden="true" class="${over ? "over" : ""}">${draw(id, show, slots, count, h, t, humCol(h, over), spools === null, toneOf(h, over) ? TONE[toneOf(h, over)] : siteTone(color))}</svg>`;
  };
  // 0.8.5 rolls in no storage box: standing on a bare desk, a dashed outline where a box would be (no humidity — open air)
  const looseSvg = (spools, count) => {
    const id = "g7b" + (++boxN), show = spools ? spools.slice(0, 5) : [], slots = show.length;
    const X0 = 12, X1 = 208, gap = (X1 - X0) / Math.max(slots, 1), r = Math.min(26, gap / 2 - 3), cy = 104 - r;
    let rolls = "";
    show.forEach((p, i) => { const cx = X0 + gap * i + gap / 2; rolls += isResin(p) ? bottle(cx - r * 0.7, cy + r, r * 1.4, r * 2, p) : faceRoll(id, p, cx, cy, r, "#3a4049"); });
    const label = slots ? "" : `<text x="110" y="84" font-size="26" font-weight="700" text-anchor="middle" fill="#8a929c">${count}</text>`;
    return `<svg viewBox="0 0 220 132" width="100%" aria-hidden="true"><defs>${rollGrad(id)}</defs>
      <rect x="6" y="20" width="208" height="84" rx="10" fill="none" stroke="#b8c0ca" stroke-width="1.5" stroke-dasharray="6 5"/>
      ${rolls}${label}${count > slots && slots ? `<text x="208" y="34" font-size="10" font-weight="700" text-anchor="end" fill="#6b7480">+${count - slots}</text>` : ""}
      <path d="M0 104 H220 L212 116 H8 Z" fill="rgba(160,172,184,.4)"/><rect x="8" y="116" width="204" height="4" rx="2" fill="rgba(130,142,154,.5)"/>
      <text x="110" y="129" font-size="8.5" text-anchor="middle" fill="#8a929c">💧 --</text></svg>`;
  };
  const printerSvg = (busy) => `<svg viewBox="0 0 64 64" width="56" height="56" aria-hidden="true" class="${busy ? "busy" : ""}">
    <rect x="6" y="6" width="52" height="52" rx="7" fill="var(--g7-soft)" stroke="var(--g7-line)"/>
    <rect x="12" y="11" width="40" height="4" rx="2" fill="var(--g7-dim)"/>
    <g class="head"><rect x="27" y="15" width="10" height="9" rx="2" fill="var(--g7-accent)"/><path d="M30 24h4l-2 4z" fill="var(--g7-dim)"/></g>
    <rect x="15" y="46" width="34" height="4" rx="1.5" fill="var(--g7-dim)"/>
    <rect class="part" x="25" y="${busy ? 38 : 44}" width="14" height="${busy ? 8 : 2}" rx="1" fill="var(--g7-accent)" opacity=".55"/></svg>`;

  const CSS = `:host{--g7-accent:var(--primary-color,#e0902a);--g7-text:var(--primary-text-color,#1b1f27);--g7-dim:var(--secondary-text-color,#6b7280);--g7-line:var(--divider-color,rgba(0,0,0,.1));--g7-soft:var(--secondary-background-color,#f2f3f5);--g7-ok:var(--success-color,#2e9d55);--g7-bad:var(--error-color,#d33)}
    ha-card{padding:16px;overflow:hidden}.where{font-size:.75rem;color:var(--g7-dim);margin:-4px 0 10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sec{margin-top:14px}.sec:first-child{margin-top:0}
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
    .sp .s{font-size:.78rem;color:var(--g7-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sp .s em{font-style:normal;color:var(--g7-accent)}.sp .s em.out{color:var(--g7-dim)}
    .sp .g{text-align:right;width:76px;font-weight:600;font-size:.9rem;color:var(--g7-text)}
    .more{width:100%;margin-top:8px;padding:9px;border-radius:10px;border:1px solid var(--g7-line);background:none;color:var(--g7-accent);font-weight:600;cursor:pointer;font:inherit}
    .boxes{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}.bx .art{margin:4px 0 2px}.boxes.list{grid-template-columns:repeat(auto-fill,minmax(140px,1fr))}.mini{display:flex;flex-wrap:wrap;gap:2px;align-items:center;margin:2px 0 4px}.mini small{font-size:.7rem;color:var(--g7-dim)}.bx.loose{border-style:dashed}
    .bx svg.over .lcd{animation:g7glow 1.6s ease-in-out infinite}@keyframes g7glow{50%{opacity:.55}}
    .inbox{font-size:.78rem;color:var(--g7-dim);padding:8px 0 0}
    .bx{border:1px solid var(--g7-line);border-radius:12px;padding:10px}.bx.over{border-color:var(--g7-bad);background:color-mix(in srgb,var(--g7-bad) 7%,transparent)}.bx.warn{border-color:#f59e0b;background:color-mix(in srgb,#f59e0b 6%,transparent)}
    .bx .t .bxc{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}.bx .t{font-weight:600;font-size:.88rem;color:var(--g7-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
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

  // 0.7.0 site × scope groups ("3ds.liveon.synology.me · 🏢 경방3D") — most data first
  const groups = (h) => {
    const score = {};
    for (const id in (h && h.states) || {}) {
      const a = h.states[id].attributes || {};
      if (!id.startsWith("sensor.") || !a.g7) continue;
      const k = a.site || "";
      score[k] = (score[k] || 0) + 1 + ((a.devices || []).length + (a.spools || []).length + (a.printers || []).length) * 2;
    }
    return Object.keys(score).sort((x, y) => score[y] - score[x]);
  };

  class G7Card extends HTMLElement {
    static getStubConfig(h) { const g = groups(h); return g.length > 1 ? { site: g[0] } : {}; }
    static getConfigElement() { return document.createElement("g7-3dssync-card-editor"); }
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
      const all = this._ours(this._hass), list = groups(this._hass);
      const site = this._cfg.site && list.includes(this._cfg.site) ? this._cfg.site : list[0];
      this._site = site;
      this._many = list.length > 1;
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
      NOSENSOR = L.nosensor;
      const parts = Object.keys(by).length ? this._show.map((k) => this["_" + k] ? this["_" + k](L, by, boxes) : "").join("") : `<div class="empty">${esc(L.nodata)}</div>`;
      const where = this._many && !this._cfg.hide_where ? `<div class="where">📍 ${esc(this._site)}</div>` : "";   // 0.7.0 which server · scope this card shows
      this.shadowRoot.innerHTML = `<style>${CSS}</style><ha-card>${where}${parts}</ha-card>`;
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

    _mini(sp) {   // list look: the rolls as small coloured spools
      if (!sp || !sp.length) return "";
      return `<div class="mini">${sp.slice(0, 8).map((p) => itemSvg(p, 18)).join("")}${sp.length > 8 ? `<small>+${sp.length - 8}</small>` : ""}</div>`;
    }
    _sep() { return this._cfg.spools === "separate"; }   // 0.8.7 default = rolls in the box picture, sensor numbers on the right
    _stock(L, by, boxes = []) {
      const s = by.filament_total; if (!s) return "";
      const every = s.attributes.spools || [], grams = num(s.attributes.grams), open = this._open.stock;
      const names = new Set(boxes.map((b) => String(b.attributes.name || "").trim()).filter(Boolean));
      const fold = !this._sep() && this._show.includes("boxes") && names.size;   // 0.8.3 spools: in_boxes (default) — boxes draw theirs
      const list = fold ? every.filter((p) => !(p.box && names.has(String(p.box).trim()))) : every, boxed = every.length - list.length;
      const shown = open ? list : list.slice(0, 8);
      const rows = shown.map((p) => `<div class="sp">${itemSvg(p)}<div class="b"><div class="t">${esc([p.material, p.color].filter(Boolean).join(" · "))}</div>
        <div class="s">${[p.brand ? esc(p.brand) : "", p.box && names.has(String(p.box).trim()) ? `<em>📦 ${esc(p.box)}</em>` : `<em class="out">${esc(L.outside)}</em>`].filter(Boolean).join(" · ") || "&nbsp;"}</div></div>
        <div class="g">${num(p.grams) !== null ? p.grams.toLocaleString() + " g" : p.pct + "%"}<div class="bar ${p.low ? "low" : ""}"><i style="width:${Math.max(3, Math.min(100, p.pct))}%"></i></div></div></div>`).join("");
      const resin = num(s.attributes.resin) ?? every.filter(isResin).length, resinG = every.filter(isResin).reduce((a, p) => a + (num(p.grams) || 0), 0);
      const kg = grams ? Math.max(0, grams - resinG) : 0, rollsN = Math.max(0, this._val(s) - resin);   // 0.8.11 🧪 resin counted apart
      const big = kg ? `<strong>${(kg / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}</strong> <small>kg</small>` : `<strong>${this._val(s)}</strong> <small>${esc(L.rolls)}</small>`;
      return `<div class="sec"><h3>🧵 ${esc(L.stock)}</h3><div class="big"><span>${big}</span><small>${rollsN} ${esc(L.rolls)}${resin ? ` · 🧪 ${esc(L.resin)} ${resin}${esc(L.bottles)}` : ""}</small></div>${rows || (boxed ? "" : `<div class="empty">${esc(L.none)}</div>`)}
        ${boxed ? `<div class="inbox">📦 ${esc(L.inbox.replace("{n}", boxed))}</div>` : ""}
        ${list.length > 8 ? `<button class="more" data-more="stock">${open ? esc(L.less) : `${esc(L.all)} (${list.length})`}</button>` : ""}</div>`;
    }

    _boxes(L, by, boxes) {
      if (!boxes.length) return "";
      const list = this._cfg.box_look === "list";   // 0.8.5 box_look: list — the earlier text tiles
      const all = (by.filament_total && by.filament_total.attributes.spools) || [];
      const tiles = boxes.map((s) => {
        const a = s.attributes, h = num(a.humidity), t = num(a.temp);
        const inside = this._sep() ? null : all.filter((p) => p.box && a.name && String(p.box).trim() === String(a.name).trim());
        return `<div class="bx ${a.over ? "over" : toneOf(h, false)}" data-ent="${esc(s.entity_id)}" style="cursor:pointer"><div class="t">${a.color ? `<i class="bxc" style="background:${esc(a.color)}"></i>` : "📦 "}${esc(a.name || s.attributes.friendly_name)}</div>
          ${list ? `<div class="h">💧 ${h !== null ? Math.round(h) + "%" : "—"}</div>${this._mini(inside)}<div class="s">${t !== null ? `🌡 ${t.toFixed(1)}°C · ` : ""}`
            : `<div class="art">${boxSvg(a.name, inside, this._val(s), h, t, !!a.over, a.color)}</div><div class="s">`}🧵 ${this._val(s)} ${esc(L.rolls)}${a.low ? ` (${esc(L.low)} ${a.low})` : ""}</div>${a.over ? `<div class="s warn">⚠ ${esc(L.over)}</div>` : ""}</div>`;
      }).join("");
      // 0.8.5 rolls in no box (no box set, or a box name the site has no storage box for) — their own tile
      const names = new Set(boxes.map((b) => String(b.attributes.name || "").trim()).filter(Boolean));
      const loose = all.filter((p) => !(p.box && names.has(String(p.box).trim())));
      const out = loose.length ? `<div class="bx loose" ${by.filament_total ? `data-ent="${esc(by.filament_total.entity_id)}" style="cursor:pointer"` : ""}><div class="t">🧵 ${esc(L.outside)}</div>
          ${list ? `<div class="h">💧 —</div>${this._mini(this._sep() ? null : loose)}` : `<div class="art">${looseSvg(this._sep() ? null : loose, loose.length)}</div>`}
          <div class="s">🧵 ${loose.length} ${esc(L.rolls)}${loose.some((p) => p.low) ? ` (${esc(L.low)} ${loose.filter((p) => p.low).length})` : ""}</div></div>` : "";
      return `<div class="sec"><h3>📦 ${esc(L.boxes)} <b>${boxes.length}</b></h3><div class="boxes ${list ? "list" : ""}">${tiles}${out}</div></div>`;
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

  // 0.7.0 card editor: which server · scope (personal / company) and which parts
  if (!customElements.get("g7-3dssync-card-editor")) {
    customElements.define("g7-3dssync-card-editor", class extends HTMLElement {
      setConfig(cfg) { this._cfg = { ...(cfg || {}) }; this._draw(); }
      set hass(h) { const first = !this._hass; this._hass = h; if (first) this._draw(); }
      _draw() {
        if (!this._cfg || !this._hass) return;
        const ko = String(this._hass.language || "").startsWith("ko"), g = groups(this._hass);
        const show = Array.isArray(this._cfg.show) ? this._cfg.show : [];
        const names = ko ? { summary: "요약 (알림 · 주문 · 입찰)", printers: "프린터", stock: "필라멘트 재고", boxes: "보관함", sensors: "연결된 센서" }
          : { summary: "Summary (notices · orders · bids)", printers: "Printers", stock: "Filament stock", boxes: "Storage boxes", sensors: "Connected sensors" };
        this.innerHTML = `<style>.g7e{display:grid;gap:12px;padding:4px 0}.g7e label{display:flex;gap:8px;align-items:center;font-size:14px}
          .g7e select{width:100%;padding:8px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);font-size:14px}
          .g7e b{font-size:13px;color:var(--secondary-text-color)}</style><div class="g7e">
          <b>${ko ? "보여 줄 서버 · 위치 (개인 / 업체)" : "Server · scope to show (personal / company)"}</b>
          <select id="site"><option value="">${ko ? "자동 — 데이터가 가장 많은 것" : "Automatic — the one with the most data"}</option>
          ${g.map((k) => `<option value="${esc(k)}" ${this._cfg.site === k ? "selected" : ""}>${esc(k)}</option>`).join("")}</select>
          <b>${ko ? "보여 줄 것 (아무것도 안 고르면 카드 기본)" : "Parts (none = the card's default)"}</b>
          ${SECTIONS.map((k) => `<label><input type="checkbox" data-k="${k}" ${show.includes(k) ? "checked" : ""}> ${esc(names[k])}</label>`).join("")}
          <b>${ko ? "보관함 모양" : "Storage box look"}</b>
          <select id="box_look"><option value="">${ko ? "그림 (건조기 · 선반 · 수납함)" : "Pictures (dryer · shelf · bin)"}</option>
          <option value="list" ${this._cfg.box_look === "list" ? "selected" : ""}>${ko ? "목록 (예전 모양 — 습도 숫자 크게)" : "List (the earlier look — big humidity number)"}</option></select>
          <b>${ko ? "필라멘트 롤 보여 주기" : "Filament rolls"}</b>
          <select id="spools"><option value="">${ko ? "보관함 그림 안에 롤 + 오른쪽에 온습도 (재고 목록엔 보관함 밖 롤만)" : "Rolls inside the box pictures, temperature · humidity on the right (stock list: rolls outside boxes)"}</option>
          <option value="separate" ${this._cfg.spools === "separate" ? "selected" : ""}>${ko ? "따로 — 보관함 그림엔 온습도만 크게, 롤은 재고 목록에" : "Separate — box pictures show temperature · humidity big, rolls in the stock list"}</option></select></div>`;
        this.querySelector("#site").addEventListener("change", (e) => this._set("site", e.target.value || undefined));
        this.querySelector("#box_look").addEventListener("change", (e) => this._set("box_look", e.target.value || undefined));
        this.querySelector("#spools").addEventListener("change", (e) => this._set("spools", e.target.value || undefined));
        this.querySelectorAll("input[data-k]").forEach((c) => c.addEventListener("change", () => {
          const v = [...this.querySelectorAll("input[data-k]:checked")].map((x) => x.dataset.k);
          this._set("show", v.length ? v : undefined);
        }));
      }
      _set(k, v) {
        const cfg = { ...this._cfg };
        if (v === undefined) delete cfg[k]; else cfg[k] = v;
        this._cfg = cfg;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: cfg }, bubbles: true, composed: true }));
      }
    });
  }

  // sidebar panel: the same parts on a wide grid · 0.7.0 a tab per server · scope
  if (!customElements.get("g7-3dssync-panel")) {
    customElements.define("g7-3dssync-panel", class extends HTMLElement {
      _tabs(h) {
        const g = groups(h), key = g.join("|");
        if (key === this._tabKey) return;
        this._tabKey = key;
        let pick = null;
        try { pick = localStorage.getItem("g7-3dssync-site"); } catch (e) { /* private mode */ }
        this._pick = g.includes(this._pick) ? this._pick : (g.includes(pick) ? pick : g[0]);
        const bar = this.querySelector(".g7p-tabs");
        bar.innerHTML = g.length > 1 ? g.map((k) => `<button data-k="${esc(k)}" class="${k === this._pick ? "on" : ""}">${esc(k)}</button>`).join("") : "";
        bar.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
          this._pick = b.dataset.k;
          try { localStorage.setItem("g7-3dssync-site", this._pick); } catch (e) { /* private mode */ }
          this._tabKey = null; this._tabs(this._hass); this._apply();
        }));
      }
      _apply() {
        this.querySelectorAll("g7-3dssync-card").forEach((c) => c.setConfig({ show: c.dataset.s.split(","), site: this._pick, hide_where: true }));
        this.querySelectorAll("g7-3dssync-card").forEach((c) => { c.hass = this._hass; });
      }
      set hass(h) {
        this._hass = h;
        if (!this._built) {
          this._built = true;
          this.innerHTML = `<style>g7-3dssync-panel{display:block;min-height:100vh;background:var(--primary-background-color)}
            .g7p-top{display:flex;align-items:center;gap:10px;height:56px;padding:0 16px;background:var(--app-header-background-color,var(--primary-color));color:var(--app-header-text-color,#fff);font-size:20px}
            .g7p-top button{background:none;border:0;color:inherit;font-size:22px;cursor:pointer;padding:6px}
            .g7p{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px;padding:16px;max-width:1400px;margin:0 auto;align-items:start}
            .g7p>div{display:grid;gap:16px}
            .g7p-tabs{display:flex;gap:8px;flex-wrap:wrap;padding:12px 16px 0;max-width:1400px;margin:0 auto}
            .g7p-tabs button{border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);border-radius:999px;padding:7px 14px;font-size:14px;cursor:pointer}
            .g7p-tabs button.on{background:var(--primary-color);border-color:var(--primary-color);color:#fff;font-weight:600}</style>
            <div class="g7p-top"><button title="Menu">☰</button><span>3DSSync</span><small style="opacity:.7;font-size:12px">${VER}</small></div>
            <div class="g7p-tabs"></div>
            <div class="g7p"><div><g7-3dssync-card data-s="summary,printers"></g7-3dssync-card><g7-3dssync-card data-s="boxes"></g7-3dssync-card></div>
            <div><g7-3dssync-card data-s="stock"></g7-3dssync-card></div><div><g7-3dssync-card data-s="sensors"></g7-3dssync-card></div></div>`;
          this.querySelector(".g7p-top button").addEventListener("click", () => this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true })));
        }
        const before = this._pick;
        this._tabs(h);
        if (!this._applied || before !== this._pick) { this._applied = true; this._apply(); return; }
        this.querySelectorAll("g7-3dssync-card").forEach((c) => { c.hass = h; });
      }
      set narrow(v) { this._narrow = v; }
      set panel(v) { this._panel = v; }
    });
  }
  console.info(`%c 3DSSync %c ${VER} `, "background:#e0902a;color:#fff;border-radius:3px 0 0 3px", "background:#333;color:#fff;border-radius:0 3px 3px 0");
})();
