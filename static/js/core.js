/* JobRadar front-end core (shared with TableTap): DOM builder, icons, API client, toasts, modals, formatting. */
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // ---------------------------------------------------------------- icons (lucide-style, 24px, stroke)
  const ICONS = {
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    receipt: '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><path d="M12 17.5v-11"/>',
    bag: '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    chef: '<path d="M17 21a1 1 0 0 0 1-1v-5.35c0-.46.31-.85.74-1.03A4 4 0 0 0 17.3 6 5 5 0 0 0 6.7 6a4 4 0 0 0-1.44 7.62c.43.18.74.57.74 1.03V20a1 1 0 0 0 1 1Z"/><path d="M6 17h12"/>',
    trash: '<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
    edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    eyeOff: '<path d="M9.9 4.2A10 10 0 0 1 12 4c6.5 0 10 8 10 8a17 17 0 0 1-2.2 3.2M6.6 6.6A17 17 0 0 0 2 12s3.5 8 10 8a9.7 9.7 0 0 0 5.4-1.6"/><path d="m2 2 20 20"/><path d="M14.1 14.1a3 3 0 0 1-4.2-4.2"/>',
    grip: '<circle cx="9" cy="6" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="18" r="1"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
    qr: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3zM20 14v.01M14 20h.01M17 17h4v4h-4"/>',
    printer: '<path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    refresh: '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M8 16H3v5"/>',
    settings: '<path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.3a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.7l-.2.4a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.7v.5a2 2 0 0 1-1 1.7l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.3a2 2 0 0 1 1 1.7v.2a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.3a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.7v-.5a2 2 0 0 1 1-1.7l.2-.1a2 2 0 0 0 .7-2.7l-.2-.4a2 2 0 0 0-2.7-.7l-.2.1a2 2 0 0 1-2 0l-.4-.3a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2Z"/><circle cx="12" cy="12" r="3"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
    chart: '<path d="M3 3v18h18"/><path d="M7 16v-4M12 16V8M17 16v-7"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
    home: '<path d="m3 10 9-7 9 7v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="M9 22V12h6v10"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>',
    store: '<path d="m2 7 1.6-4h16.8L22 7"/><path d="M2 7h20v3a3 3 0 0 1-5 2 3 3 0 0 1-5 0 3 3 0 0 1-5 0 3 3 0 0 1-5-2Z"/><path d="M4 12v9h16v-9"/><path d="M10 21v-5h4v5"/>',
    wifi: '<path d="M5 13a10 10 0 0 1 14 0"/><path d="M8.5 16.5a5 5 0 0 1 7 0"/><path d="M2 8.8a15 15 0 0 1 20 0"/><path d="M12 20h.01"/>',
    phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2Z"/>',
    pin: '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
    chevronRight: '<path d="m9 18 6-6-6-6"/>',
    chevronLeft: '<path d="m15 18-6-6 6-6"/>',
    chevronDown: '<path d="m6 9 6 6 6-6"/>',
    alert: '<path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z"/><path d="M12 9v4M12 17h.01"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    flame: '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.4-.5-2-1-3-1.1-2.1-.2-4 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.2.4-2.3 1-3.3.3 1.5 1.3 2.8 2.5 2.8Z"/>',
    leaf: '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.5 19 2c1 2 2 4.2 2 8 0 5.5-4.8 10-10 10Z"/><path d="M2 21c0-3 1.9-5.4 5.1-6"/>',
    star: '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1Z"/>',
    sparkles: '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>',
    external: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    volume: '<path d="M11 5 6 9H2v6h4l5 4Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/>',
    volumeX: '<path d="M11 5 6 9H2v6h4l5 4Z"/><path d="m22 9-6 6M16 9l6 6"/>',
    maximize: '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/>',
    lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    utensils: '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2M7 2v20M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/>',
    dollar: '<path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    hand: '<path d="M18 11V6a2 2 0 0 0-4 0v5M14 10V4a2 2 0 0 0-4 0v2M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.9-5.9-2.4l-3.6-3.6a2 2 0 0 1 2.8-2.8L7 15"/>',
    card: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
    cash: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2"/><path d="M6 12h.01M18 12h.01"/>',
    undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    arrowRight: '<path d="M5 12h14M12 5l7 7-7 7"/>',
    arrowUp: '<path d="m18 15-6-6-6 6"/>',
    arrowDown: '<path d="m6 9 6 6 6-6"/>',
    trendUp: '<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
    trendDown: '<path d="m22 17-8.5-8.5-5 5L2 7"/><path d="M16 17h6v-6"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 4 10 15 15 0 0 1-4 10 15 15 0 0 1-4-10 15 15 0 0 1 4-10Z"/>',
    note: '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5Z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/>',
    zap: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8Z"/>',
    wifiOff: '<path d="m2 2 20 20M8.5 16.5a5 5 0 0 1 7 0M2 8.8a15 15 0 0 1 4.2-2.7M10.7 5.1A15 15 0 0 1 22 8.8M16.9 10.5a10 10 0 0 1 2.1 1.9M5 12.9a10 10 0 0 1 5.2-2.8M12 20h.01"/>',
    shield: '<path d="M20 13c0 5-3.5 7.5-7.7 9a1 1 0 0 1-.7 0C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.2-2.7a1.2 1.2 0 0 1 1.6 0C14.5 3.8 17 5 19 5a1 1 0 0 1 1 1Z"/>',
    database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
    moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    ban: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
    activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    briefcase: '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
    building: '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4M8 6h.01M16 6h.01M12 6h.01M12 10h.01M12 14h.01M16 10h.01M16 14h.01M8 10h.01M8 14h.01"/>',
    mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
    radar: '<path d="M19.07 4.93A10 10 0 0 0 6.99 3.34"/><path d="M4 6h.01"/><path d="M2.29 9.62A10 10 0 1 0 21.31 8.35"/><path d="M16.24 7.76A6 6 0 1 0 8.23 16.67"/><path d="M12 18h.01"/><path d="M17.99 11.66A6 6 0 0 1 15.77 16.67"/><circle cx="12" cy="12" r="2"/><path d="m13.41 10.59 5.66-5.66"/>',
    kanban: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 7v7M12 7v4M16 7v9"/>',
    filter: '<path d="M22 3H2l8 9.46V19l4 2v-8.54Z"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    play: '<path d="m6 3 14 9-14 9Z"/>',
    bookmark: '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2Z"/>',
    send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    wand: '<path d="m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72"/><path d="m14 7 3 3M5 6v4M19 14v4M10 2v2M7 8H3M21 16h-4M11 3H9"/>',
    sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/>',
    linkedin: '<path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-4 0v7h-4v-7a6 6 0 0 1 6-6Z"/><rect x="2" y="9" width="4" height="12"/><circle cx="4" cy="4" r="2"/>',
  };

  function icon(name, cls) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", cls || "icon");
    svg.innerHTML = ICONS[name] || ICONS.info; // trusted static markup only
    return svg;
  }

  // ---------------------------------------------------------------- DOM builder
  // h("button.btn.btn-primary", {onclick, disabled}, "Save", icon("check"))
  function h(tag, attrs, ...children) {
    let [name, ...classes] = tag.split(".");
    let id = null;
    if (name.includes("#")) [name, id] = name.split("#");
    const el = document.createElement(name || "div");
    if (id) el.id = id;
    if (classes.length) el.className = classes.join(" ");
    if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) {
      children.unshift(attrs);
      attrs = null;
    }
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === undefined || v === null || v === false) continue;
        if (k === "class") el.className += (el.className ? " " : "") + v;
        else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
        else if (k === "dataset") Object.assign(el.dataset, v);
        else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
        else if (k === "text") el.textContent = v;
        else if (k in el && k !== "list" && k !== "form" && typeof v !== "string") el[k] = v;
        else if (v === true) el.setAttribute(k, "");
        else el.setAttribute(k, v);
      }
    }
    append(el, children);
    return el;
  }

  function append(el, children) {
    for (const c of children.flat(Infinity)) {
      if (c === null || c === undefined || c === false || c === "") continue;
      el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }

  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
  function mount(el, ...children) { clear(el); return append(el, children); }

  // ---------------------------------------------------------------- API
  class ApiError extends Error {
    constructor(message, data, status) {
      super(message);
      this.data = data || {};
      this.status = status;
      this.code = this.data.code;
      this.field = this.data.field;
    }
  }

  let csrf = null;
  function setCsrf(t) { csrf = t; }

  async function api(method, url, data, opts = {}) {
    const init = { method, credentials: "same-origin", headers: { Accept: "application/json", "X-JobRadar": "1" } };
    if (csrf) init.headers["X-CSRF-Token"] = csrf;
    if (data instanceof FormData) init.body = data;
    else if (data !== undefined && method !== "GET") {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(data);
    }
    if (opts.signal) init.signal = opts.signal;
    let res;
    try {
      res = await fetch(url, init);
    } catch (e) {
      if (e.name === "AbortError") throw e;
      throw new ApiError("No connection. Check the Wi-Fi and try again.", { code: "network" }, 0);
    }
    let json = null;
    try { json = await res.json(); } catch (_) { /* non-JSON */ }
    if (!res.ok || (json && json.ok === false)) {
      throw new ApiError((json && json.error) || ("Request failed (" + res.status + ")"), json, res.status);
    }
    return json || {};
  }
  api.get = (u, o) => api("GET", u, undefined, o);
  api.post = (u, d, o) => api("POST", u, d, o);
  api.put = (u, d, o) => api("PUT", u, d, o);
  api.del = (u, d, o) => api("DELETE", u, d, o);

  // ---------------------------------------------------------------- toasts
  let toastBox = null;
  function toast(message, type = "ok", opts = {}) {
    if (!toastBox) {
      toastBox = h("div.toasts", { role: "status", "aria-live": "polite" });
      document.body.appendChild(toastBox);
    }
    const ic = type === "error" ? "alert" : type === "info" ? "info" : "check";
    const t = h("div.toast." + type, icon(ic), h("span", message));
    if (opts.action) {
      t.appendChild(h("button.t-action", { onclick: () => { opts.action.run(); dismiss(); } }, opts.action.label));
    }
    toastBox.appendChild(t);
    let gone = false;
    function dismiss() {
      if (gone) return;
      gone = true;
      t.classList.add("out");
      setTimeout(() => t.remove(), 260);
    }
    setTimeout(dismiss, opts.duration || (type === "error" ? 5200 : 3000));
    return dismiss;
  }

  // ---------------------------------------------------------------- modal
  const modalStack = [];
  function modal({ title, body, foot, size, onClose, dismissible = true, className } = {}) {
    const closeBtn = h("button.btn.btn-ghost.btn-icon.btn-sm", { "aria-label": "Close", onclick: () => close() }, icon("x"));
    const box = h("div.modal" + (size ? "." + size : "") + (className ? "." + className : ""),
      { role: "dialog", "aria-modal": "true" },
      h("div.modal-head", h("h3", title || ""), h("div.spacer"), dismissible ? closeBtn : null),
      h("div.modal-body", body),
      foot ? h("div.modal-foot", foot) : null);
    const back = h("div.modal-backdrop", box);
    const prevFocus = document.activeElement;
    back.addEventListener("mousedown", (e) => { if (e.target === back && dismissible) close(); });
    document.body.appendChild(back);
    document.body.style.overflow = "hidden";
    const entry = { close, dismissible };
    modalStack.push(entry);
    setTimeout(() => {
      const f = box.querySelector("[autofocus], input:not([type=hidden]):not([type=checkbox]):not([type=file]), select, textarea");
      (f || box.querySelector("button"))?.focus();
    }, 30);
    let closed = false;
    function close(result) {
      if (closed) return;
      closed = true;
      const i = modalStack.indexOf(entry);
      if (i >= 0) modalStack.splice(i, 1);
      back.classList.add("out");
      setTimeout(() => back.remove(), 170);
      if (!modalStack.length) document.body.style.overflow = "";
      if (prevFocus && prevFocus.focus) prevFocus.focus();
      if (onClose) onClose(result);
    }
    return { el: box, body: box.querySelector(".modal-body"), close };
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modalStack.length) {
      const top = modalStack[modalStack.length - 1];
      if (top.dismissible) { e.preventDefault(); top.close(); }
    }
  });

  // typeText: the user must type this word (e.g. "DELETE") before OK is enabled. extra: more nodes in the body.
  function confirmDialog({ title = "Are you sure?", message = "", ok = "Confirm", danger = false, cancel = "Cancel", typeText = null, extra = null } = {}) {
    return new Promise((resolve) => {
      let result = false;
      const okBtn = h("button.btn" + (danger ? ".btn-danger" : ".btn-primary"), { disabled: !!typeText, onclick: () => { result = true; m.close(); } }, ok);
      const inp = typeText ? h("input.input.confirm-type", { placeholder: "Type " + typeText + " to confirm", autocomplete: "off",
        oninput: (e) => { okBtn.disabled = e.target.value.trim() !== typeText; } }) : null;
      const m = modal({
        title, size: "narrow",
        body: h("div", h("p.muted", message), extra, inp),
        foot: [h("button.btn.btn-ghost", { onclick: () => m.close() }, cancel), okBtn],
        onClose: () => resolve(result),
      });
      setTimeout(() => (inp || okBtn).focus(), 40);
    });
  }

  // ---------------------------------------------------------------- formatting
  function moneyFormatter(r) {
    const dec = r && Number.isInteger(r.decimals) ? r.decimals : 2;
    const sym = (r && r.currency_symbol) || "$";
    const suffix = !!(r && r.currency_suffix);
    const nf = new Intl.NumberFormat(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
    const fmt = (minor) => {
      const v = (Number(minor) || 0) / Math.pow(10, dec);
      const s = nf.format(Math.abs(v));
      const signed = (v < 0 ? "−" : "");
      return suffix ? signed + s + " " + sym : signed + sym + s;
    };
    fmt.plain = (minor) => ((Number(minor) || 0) / Math.pow(10, dec)).toFixed(dec);
    fmt.decimals = dec;
    fmt.symbol = sym;
    return fmt;
  }

  function timeAgo(ts, now = Date.now() / 1000) {
    const s = Math.max(0, Math.round(now - ts));
    if (s < 45) return "just now";
    const m = Math.round(s / 60);
    if (m < 60) return m + " min ago";
    const hh = Math.round(m / 60);
    if (hh < 24) return hh + " h ago";
    const d = Math.round(hh / 24);
    return d + (d === 1 ? " day ago" : " days ago");
  }

  function elapsed(ts, now = Date.now() / 1000) {
    const s = Math.max(0, Math.floor(now - ts));
    const m = Math.floor(s / 60);
    if (m >= 60) return Math.floor(m / 60) + "h " + String(m % 60).padStart(2, "0") + "m";
    return m + ":" + String(s % 60).padStart(2, "0");
  }

  function fmtTime(ts) {
    return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  function fmtDate(ts) {
    return new Date(ts * 1000).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
  }
  function fmtDateTime(ts) {
    const d = new Date(ts * 1000);
    const today = new Date();
    const sameDay = d.toDateString() === today.toDateString();
    return (sameDay ? "Today" : d.toLocaleDateString([], { day: "numeric", month: "short" })) + ", " + fmtTime(ts);
  }

  function debounce(fn, ms) {
    let t;
    return function (...a) { clearTimeout(t); t = setTimeout(() => fn.apply(this, a), ms); };
  }

  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* private mode */ } },
    del(k) { try { localStorage.removeItem(k); } catch (_) { /* ignore */ } },
  };

  function readBoot() {
    const el = document.getElementById("boot");
    if (!el) return {};
    try { return JSON.parse(el.textContent); } catch (_) { return {}; }
  }

  // Field-level errors for forms built with .field wrappers and [name] inputs.
  function fieldError(form, name, message) {
    clearErrors(form);
    const input = name && form.querySelector('[name="' + name + '"]');
    if (!input) return false;
    input.classList.add("invalid");
    const wrap = input.closest(".field") || input.parentElement;
    wrap.appendChild(h("div.field-error", message));
    input.focus();
    input.addEventListener("input", () => clearErrors(form), { once: true });
    return true;
  }
  function clearErrors(form) {
    $$(".invalid", form).forEach((e) => e.classList.remove("invalid"));
    $$(".field-error", form).forEach((e) => e.remove());
  }

  async function withBusy(btn, fn) {
    if (btn) { btn.classList.add("loading"); btn.disabled = true; }
    try { return await fn(); }
    finally { if (btn) { btn.classList.remove("loading"); btn.disabled = false; } }
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (_) {
      const ta = h("textarea", { style: { position: "fixed", opacity: "0" } }, text);
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (_) { /* ignore */ }
      ta.remove();
      return ok;
    }
  }

  // Tiny chime with WebAudio (no audio files needed). Browsers require one user gesture first.
  let audioCtx = null;
  function unlockAudio() {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === "suspended") audioCtx.resume();
      return true;
    } catch (_) { return false; }
  }
  function chime(kind = "order") {
    if (!audioCtx || audioCtx.state !== "running") return false;
    const notes = kind === "call" ? [880, 660, 880] : [660, 880, 1175];
    const t0 = audioCtx.currentTime;
    notes.forEach((f, i) => {
      const o = audioCtx.createOscillator();
      const g = audioCtx.createGain();
      o.type = "sine";
      o.frequency.value = f;
      const s = t0 + i * 0.16;
      g.gain.setValueAtTime(0.0001, s);
      g.gain.exponentialRampToValueAtTime(0.35, s + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, s + 0.5);
      o.connect(g).connect(audioCtx.destination);
      o.start(s);
      o.stop(s + 0.55);
    });
    return true;
  }
  function audioReady() { return !!audioCtx && audioCtx.state === "running"; }

  window.TT = {
    $, $$, h, icon, append, clear, mount, api, ApiError, setCsrf, toast, modal, confirmDialog,
    moneyFormatter, timeAgo, elapsed, fmtTime, fmtDate, fmtDateTime, debounce, store, readBoot,
    fieldError, clearErrors, withBusy, copyText, unlockAudio, chime, audioReady,
  };
})();
