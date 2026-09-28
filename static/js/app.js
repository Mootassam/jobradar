/* JobRadar UI — search, jobs database, pipeline, companies, alerts, sources, settings. */
(function () {
  "use strict";
  const { h, icon, api, toast, modal, confirmDialog, mount, clear, $, $$, withBusy, debounce } = TT;
  const LS = TT.store;

  let META = null;
  let STATS = null;
  const SRC = {};                     // source id -> name
  const STATUS = {
    new: ["New", "zap"], saved: ["Saved", "bookmark"], applied: ["Applied", "send"],
    interview: ["Interview", "users"], offer: ["Offer", "star"], rejected: ["Rejected", "x"],
  };
  const theme = LS.get("jr_theme", "system");
  if (theme !== "system") document.documentElement.dataset.theme = theme;

  // ================================================================ helpers
  function hue(s) { let x = 0; for (const c of s || "") x = (x * 31 + c.charCodeAt(0)) % 360; return x; }
  function initials(s) { return (s || "?").replace(/[^\p{L}\p{N} ]/gu, "").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?"; }
  function logo(name, size) {
    const el = h("div.logo", { style: { background: "linear-gradient(135deg, hsl(" + hue(name) + " 62% 52%), hsl(" + ((hue(name) + 40) % 360) + " 62% 42%))" } }, initials(name));
    if (size) Object.assign(el.style, { width: size + "px", height: size + "px", fontSize: Math.round(size / 2.8) + "px" });
    return el;
  }
  function flagOf(cc) { return cc && cc.length === 2 ? String.fromCodePoint(...[...cc.toUpperCase()].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65)) : "🌍"; }
  function countryName(cc) { const c = META && META.countries.find((x) => x.code === cc); return c ? c.name : cc; }
  function nfmt(n) { return new Intl.NumberFormat().format(n || 0); }
  function money(v, cur) {
    if (v == null) return "";
    const k = v >= 1000 ? Math.round(v / 1000) + "k" : String(Math.round(v));
    const sym = { USD: "$", EUR: "€", GBP: "£", INR: "₹", TND: "DT ", MAD: "DH ", DZD: "DA ", AED: "AED ", SAR: "SAR ", CHF: "CHF " }[cur] || (cur ? cur + " " : "");
    return sym + k;
  }
  function salary(j) {
    if (j.salary_min || j.salary_max) return money(j.salary_min || j.salary_max, j.salary_currency) + (j.salary_max && j.salary_min && j.salary_max !== j.salary_min ? "–" + money(j.salary_max, j.salary_currency).replace(/^[^\d]+/, "") : "");
    return j.salary_text || "";
  }
  function when(j) { const t = j.posted_at || j.first_seen; return t ? TT.timeAgo(t) : ""; }
  function locText(j) {
    const parts = [];
    if (j.city) parts.push(j.city);
    if (j.region && j.region !== j.city) parts.push(j.region);
    if (j.country) parts.push(countryName(j.country));
    return parts.join(", ") || j.location || (j.remote ? "Remote" : "");
  }
  function srcLabel(s) { return SRC[s] || s.replace(/-alert$/, " alert"); }
  function statusBadge(st) { return st && st !== "new" ? h("span.st-badge.st-" + st, STATUS[st][0]) : null; }
  function empty(ic, title, text, action) {
    return h("div.empty", h("div.empty-icon", icon(ic)), h("h3", title), text ? h("p", text) : null, action ? h("div", { style: { marginTop: "14px" } }, action) : null);
  }
  function spin() { return h("div", { style: { display: "grid", placeItems: "center", padding: "50px" } }, h("div.spinner")); }
  function field(label, ctl, hint) { return h("div.field", h("label", label), ctl, hint ? h("span.hint", hint) : null); }
  function sel(options, value, onchange, cls) {
    const s = h("select.select" + (cls ? "." + cls : ""), { onchange: (e) => onchange(e.target.value) }, options.map(([v, l]) => h("option", { value: v }, l)));
    s.value = value == null ? "" : String(value);
    return s;
  }
  function popMenu(anchor, items) {
    $$(".menu-pop").forEach((m) => m.remove());
    const pop = h("div.menu-pop", items.filter(Boolean).map((it) => h("button", { onclick: () => { pop.remove(); it.run(); } }, icon(it.icon), it.label)));
    document.body.append(pop);
    const r = anchor.getBoundingClientRect();
    pop.style.left = Math.max(8, Math.min(window.innerWidth - pop.offsetWidth - 8, r.right - pop.offsetWidth)) + "px";
    pop.style.top = (r.bottom + 6 + window.scrollY) + "px";
    setTimeout(() => document.addEventListener("pointerdown", function off(e) { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener("pointerdown", off); } }), 0);
  }
  function download(url) { const a = h("a", { href: url, download: "" }); document.body.append(a); a.click(); a.remove(); }

  // Typo-tolerant country matching: "tunisa" -> Tunisia, "morroco" -> Morocco, "usa"/"uk" aliases.
  const fold = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  const ALIAS = { usa: "US", america: "US", uk: "GB", england: "GB", britain: "GB", uae: "AE", emirates: "AE", ksa: "SA", holland: "NL",
    maroc: "MA", tunisie: "TN", algerie: "DZ", deutschland: "DE", espana: "ES", turkiye: "TR", korea: "KR", czechia: "CZ" };
  function editDistance(a, b) {
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    return d[a.length][b.length];
  }
  function countryScore(c, q) {
    const n = fold(c.name), qq = fold(q);
    if (c.code.toLowerCase() === qq || ALIAS[qq] === c.code) return 100;
    if (n.startsWith(qq)) return 90;
    if (n.split(/[\s-]+/).some((w) => w.startsWith(qq))) return 80;
    if (n.includes(qq)) return 70;
    if (qq.length >= 3) {
      const tol = qq.length >= 6 ? 2 : 1;
      if (editDistance(qq, n.slice(0, qq.length)) <= tol || editDistance(qq, n) <= tol) return 50;
      let i = 0;
      for (const ch of n) if (ch === qq[i]) i++;
      if (i === qq.length && n[0] === qq[0]) return 40;
    }
    return 0;
  }

  // Country combobox with flags + search
  function countryCombo(value, onChange, opts = {}) {
    let cur = value || "";
    const input = h("input.input", { placeholder: opts.placeholder || "🌍 Anywhere", autocomplete: "off", spellcheck: false });
    const wrap = h("div.combo", input);
    let list = null, hl = 0, items = [];
    const label = (cc) => (cc ? flagOf(cc) + "  " + countryName(cc) : "");
    input.value = label(cur);
    function close() { if (list) { list.remove(); list = null; } }
    function pick(cc) { cur = cc; input.value = label(cc); close(); onChange(cc); }
    function render(qs) {
      const q = (qs || "").toLowerCase().replace(/^[^\p{L}]+/u, "").trim();
      const matches = !q ? META.countries : META.countries
        .map((c) => [c, countryScore(c, q)]).filter(([, s]) => s > 0)
        .sort((a, b) => b[1] - a[1] || a[0].name.localeCompare(b[0].name)).map(([c]) => c);
      items = (q ? matches : [{ code: "", name: "Anywhere (worldwide)", flag: "🌍" }].concat(matches)).slice(0, 80);
      hl = Math.min(hl, items.length - 1);
      if (!list) { list = h("div.combo-list"); wrap.append(list); }
      mount(list, items.map((c, i) => h("button" + (i === hl ? ".hl" : ""), { type: "button", onmousedown: (e) => { e.preventDefault(); pick(c.code); } },
        h("span.fl", c.flag), c.name, h("span.cc", c.code))));
    }
    input.addEventListener("focus", () => { input.select(); hl = 0; render(""); });
    input.addEventListener("input", () => { hl = 0; render(input.value); });
    input.addEventListener("blur", () => setTimeout(() => { close(); input.value = label(cur); }, 120));
    input.addEventListener("keydown", (e) => {
      if (!list) return;
      if (e.key === "ArrowDown") { hl = Math.min(items.length - 1, hl + 1); render(input.value); e.preventDefault(); }
      else if (e.key === "ArrowUp") { hl = Math.max(0, hl - 1); render(input.value); e.preventDefault(); }
      else if (e.key === "Enter") { e.preventDefault(); if (items[hl]) pick(items[hl].code); }
      else if (e.key === "Escape") { close(); input.blur(); }
    });
    wrap.set = (cc) => { cur = cc || ""; input.value = label(cur); };
    return wrap;
  }

  function highlight(text, terms) {
    const frag = document.createDocumentFragment();
    const rx = new RegExp("(" + ["[\\w.+-]+@[\\w-]+\\.[\\w.-]+", ...terms.filter((t) => t.length > 2).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))].join("|") + ")", "gi");
    let last = 0;
    String(text).replace(rx, (m, _g, idx) => {
      frag.append(text.slice(last, idx), h("mark", m));
      last = idx + m.length;
      return m;
    });
    frag.append(text.slice(last));
    return frag;
  }

  // ================================================================ insights & people (recruiter finder)
  const ROLE = { hr: ["HR / Recruiting", "ok"], leader: ["Leadership", "accent"], manager: ["Hiring manager", "info"], other: ["Team", ""] };
  const ETYPE = { recruiting: ["Recruiting inbox", "ok"], personal: ["Personal", "info"], general: ["General", ""], other: ["Other", ""] };

  function insightChips(ins, compact) {
    if (!ins || typeof ins !== "object") return null;
    const chips = [];
    if (ins.experience_years != null) chips.push(h("span.ichip", icon("clock"), ins.experience_years + "+ yrs"));
    if (ins.seniority) chips.push(h("span.ichip", ins.seniority));
    (ins.contract || []).slice(0, compact ? 1 : 3).forEach((c) => chips.push(h("span.ichip", c)));
    if ((ins.benefits || []).includes("Visa sponsorship")) chips.push(h("span.ichip.good", icon("send"), "Visa"));
    else if ((ins.benefits || []).includes("Relocation")) chips.push(h("span.ichip.good", "Relocation"));
    if (ins.deadline) chips.push(h("span.ichip.warn", icon("calendar"), "Apply by " + TT.fmtDate(ins.deadline)));
    return chips.length ? h("div.ichips", chips) : null;
  }

  function insightsCard(ins) {
    if (!ins || !Object.keys(ins).length) return null;
    const row = (label, value) => value ? h("div.irow2", h("span.faint", label), h("div", value)) : null;
    return h("div.contact-card",
      h("h4", icon("sparkles", "icon"), "Job insights"),
      row("Experience", ins.experience_years != null ? ins.experience_years + "+ years" : ""),
      row("Seniority", ins.seniority || ""),
      row("Education", ins.education || ""),
      row("Contract", (ins.contract || []).join(" · ")),
      row("Languages", (ins.languages || []).join(", ")),
      row("Deadline", ins.deadline ? TT.fmtDate(ins.deadline) : ""),
      (ins.skills || []).length ? row("Skills", h("div.chips", ins.skills.map((s) => h("span.skill", s)))) : null,
      (ins.benefits || []).length ? row("Benefits", h("div.chips", ins.benefits.map((s) => h("span.skill.good", s)))) : null);
  }

  function personRow(p, opts = {}) {
    const [rl, rc] = ROLE[p.role] || ROLE.other;
    const copyBtn = (v) => h("button.btn.btn-ghost.btn-sm.copy", { title: "Copy", onclick: async (e) => { e.stopPropagation(); await TT.copyText(v); toast("Copied", "ok", { duration: 1200 }); } }, icon("copy"));
    return h("div.person",
      h("div.pav", { style: { background: "hsl(" + hue(p.name) + " 55% 50%)" } }, initials(p.name)),
      h("div.pbody",
        h("div.pname", p.name, h("span.badge" + (rc ? "." + rc : ""), rl), p.source === "job post" ? h("span.badge.warn", "Contact for this job") : null),
        p.title ? h("div.ptitle", p.title) : null,
        opts.company ? h("div.tiny.muted", h("a", { href: "#/companies?open=" + encodeURIComponent(p.company_key) }, p.company || p.company_key)) : null,
        h("div.plinks",
          p.email ? h("span.plink", icon("mail"), h("a", { href: "mailto:" + p.email }, p.email), copyBtn(p.email)) : null,
          p.phone ? h("span.plink", icon("phone"), h("a", { href: "tel:" + p.phone.replace(/\s/g, "") }, p.phone)) : null,
          p.linkedin ? h("span.plink", icon("linkedin"), h("a", { href: p.linkedin, target: "_blank", rel: "noopener" }, "LinkedIn")) : null,
          p.url ? h("span.plink.faint", icon("link"), h("a", { href: p.url, target: "_blank", rel: "noopener", title: p.url }, "found on " + (p.source || "page"))) : null)));
  }

  function emailGroups(c) {
    const types = c.email_types || {};
    const groups = {};
    (c.emails || []).forEach((e) => { const t = types[e] || "other"; (groups[t] = groups[t] || []).push(e); });
    return ["recruiting", "personal", "general", "other"].filter((t) => groups[t]).map((t) =>
      h("div.egroup", h("span.badge" + (ETYPE[t][1] ? "." + ETYPE[t][1] : ""), ETYPE[t][0]),
        h("div.egroup-list", groups[t].map((e) => h("span.plink", icon("mail"), h("a", { href: "mailto:" + e }, e),
          h("button.btn.btn-ghost.btn-sm.copy", { onclick: async () => { await TT.copyText(e); toast("Copied", "ok", { duration: 1200 }); } }, icon("copy")))))));
  }

  // Full company profile (modal)
  async function openCompany(key) {
    const m = modal({ title: "Company", size: "wide", body: spin() });
    async function load() {
      let c;
      try { c = (await api.get("/api/companies/" + encodeURIComponent(key))).company; }
      catch (e) { mount(m.body, h("p.field-error", e.message)); return; }
      m.el.querySelector(".modal-head h3").textContent = c.name;
      const btn = h("button.btn.btn-primary", { onclick: () => withBusy(btn, async () => {
        try { await api.post("/api/companies/" + encodeURIComponent(key) + "/enrich", {}); toast("Updated " + c.name, "ok"); load(); }
        catch (e) { toast(e.message, "error"); }
      }) }, icon("wand"), c.enriched_at ? "Search again" : "Find recruiters & contacts");
      const people = c.people || [];
      mount(m.body,
        h("div.cprofile",
          c.logo ? h("img.clogo", { src: c.logo, alt: "", referrerpolicy: "no-referrer", onerror: (e) => e.target.remove() }) : logo(c.name, 56),
          h("div", { style: { flex: 1, minWidth: 0 } },
            h("div.row.wrap", c.domain ? h("a", { href: "https://" + c.domain, target: "_blank", rel: "noopener" }, icon("globe", "icon"), " ", c.domain) : h("span.faint", "No website yet"),
              c.founded ? h("span.badge", "Founded " + c.founded) : null, c.employees ? h("span.badge", c.employees + " employees") : null),
            c.description ? h("p.note", { style: { marginTop: "6px" } }, c.description) : null,
            c.address ? h("div.small.muted", { style: { marginTop: "4px" } }, icon("pin", "icon"), " ", c.address) : null,
            (c.socials || []).length ? h("div.row.wrap", { style: { marginTop: "6px" } }, c.socials.map((s) => h("a.small", { href: s, target: "_blank", rel: "noopener" }, s.replace(/^https?:\/\/(www\.)?/, "").split("/")[0]))) : null),
          h("div", btn)),
        h("div.sec-title", icon("users", "icon"), "People to contact", h("span.badge", String(people.length))),
        people.length ? h("div.people", people.map((p) => personRow(p))) :
          h("p.note", c.enriched_at ? "No named people are published on this company's website." : "Click “Find recruiters & contacts” to scan the company website."),
        (c.emails || []).length ? [h("div.sec-title", icon("mail", "icon"), "Emails"), emailGroups(c)] : null,
        (c.phones || []).length ? [h("div.sec-title", icon("phone", "icon"), "Phones"), h("div.row.wrap", c.phones.map((p) => h("a.plink", { href: "tel:" + p.replace(/\s/g, "") }, icon("phone"), p)))] : null,
        h("div.row", { style: { marginTop: "16px" } }, h("a.btn", { href: "#/jobs?company=" + encodeURIComponent(key), onclick: () => m.close() }, icon("briefcase"), "See their jobs"),
          h("span.spacer"), c.enriched_at ? h("span.tiny.faint", (c.enrich_status || "") + " · " + TT.timeAgo(c.enriched_at) + " · " + (c.pages || []).length + " pages read") : null));
    }
    load();
  }

  // ================================================================ job list component
  function JobList(opts) {
    const init = opts.initial || {};
    const state = { page: 1, per: 50, sort: init.sort || LS.get("jr_sort", "newest"), q: "", has_email: false, has_phone: false, has_salary: false,
      has_recruiter: false, visa: false, remote: "", min_match: +init.min_match || 0 };
    const selected = new Set();
    const listBox = h("div.card.jlist");
    const bulkBox = h("div");
    const countEl = h("span.muted.small");
    const tg = (key, ic, label) => {
      const b = h("button.tgl", { onclick: () => { state[key] = !state[key]; b.classList.toggle("on", state[key]); state.page = 1; load(); } }, icon(ic), label);
      return b;
    };
    const remoteTg = h("button.tgl", { onclick: () => { state.remote = state.remote === "remote" ? "" : "remote"; remoteTg.classList.toggle("on", !!state.remote); state.page = 1; load(); } }, icon("globe"), "Remote");
    const sortSel = sel([["newest", "Newest posted"], ["found", "Recently found"], ["match", "Best match (my CV)"], ["salary", "Highest salary"], ["company", "Company A–Z"]], state.sort,
      (v) => { state.sort = v; LS.set("jr_sort", v); state.page = 1; load(); });
    const matchSel = sel([[0, "Any match"], [40, "Match 40%+"], [60, "Match 60%+"], [75, "Match 75%+"], [85, "Match 85%+"]], state.min_match,
      (v) => { state.min_match = +v; state.page = 1; load(); });
    const exportBtn = h("button.btn.btn-sm", { onclick: (e) => popMenu(e.currentTarget, [
      { icon: "download", label: "Export to Excel (.xlsx)", run: () => download("/api/export?format=xlsx&" + qs(true)) },
      { icon: "download", label: "Export to CSV", run: () => download("/api/export?format=csv&" + qs(true)) },
    ]) }, icon("download"), "Export");
    const fbar = h("div.fbar",
      opts.extraFilters || null,
      h("div.search-input", icon("search"), h("input.input", { placeholder: opts.searchPlaceholder || "Search in these jobs…", oninput: debounce((e) => { state.q = e.target.value; state.page = 1; load(); }, 250) })),
      tg("has_email", "mail", "Email"), tg("has_phone", "phone", "Phone"), tg("has_recruiter", "users", "Recruiter"),
      tg("has_salary", "dollar", "Salary"), tg("visa", "send", "Visa / relocation"), remoteTg,
      matchSel, sortSel, exportBtn, countEl);
    const el = h("div", fbar, bulkBox, listBox);

    function qs(forExport) {
      const p = Object.assign({}, opts.filters ? opts.filters() : {}, {
        page: state.page, per: state.per, sort: state.sort, q: state.q || (opts.filters && opts.filters().q) || "",
        has_email: state.has_email ? 1 : "", has_phone: state.has_phone ? 1 : "", has_salary: state.has_salary ? 1 : "",
        has_recruiter: state.has_recruiter ? 1 : "", visa: state.visa ? 1 : "", min_match: state.min_match || "",
      });
      if (state.remote) p.remote = state.remote;
      if (forExport && selected.size) p.ids = [...selected].join(",");
      Object.keys(p).forEach((k) => (p[k] === "" || p[k] == null || p[k] === false) && delete p[k]);
      return new URLSearchParams(p).toString();
    }

    function drawBulk() {
      if (!selected.size) return clear(bulkBox);
      const ids = [...selected];
      mount(bulkBox, h("div.bulkbar", h("b", selected.size + " selected"), h("span.spacer"),
        h("button.btn.btn-sm", { onclick: () => bulk({ status: "saved" }, "Saved") }, icon("bookmark"), "Save"),
        h("button.btn.btn-sm", { onclick: () => bulk({ status: "applied" }, "Marked applied") }, icon("send"), "Applied"),
        h("button.btn.btn-sm", { onclick: async () => { const r = await api.post("/api/enrich/bulk", { from_jobs: ids }); toast("Finding contacts for " + r.queued + " companies…", "info"); } }, icon("wand"), "Find contacts"),
        h("button.btn.btn-sm", { onclick: () => download("/api/export?format=xlsx&ids=" + ids.join(",") + "&" + qs(false)) }, icon("download"), "Export"),
        h("button.btn.btn-sm", { onclick: () => bulk({ hidden: true }, "Hidden") }, icon("eyeOff"), "Hide"),
        h("button.btn.btn-sm", { onclick: () => { selected.clear(); drawBulk(); $$(".jrow.sel", listBox).forEach((r) => { r.classList.remove("sel"); r.querySelector("input").checked = false; }); } }, "Clear")));
      async function bulk(payload, msg) {
        await api.post("/api/jobs/bulk", Object.assign({ ids }, payload));
        toast(msg + " · " + ids.length + " job(s)", "ok");
        selected.clear();
        drawBulk();
        load();
      }
    }

    function row(j) {
      const cb = h("input", { type: "checkbox", checked: selected.has(j.id), onclick: (e) => e.stopPropagation(), onchange: (e) => {
        e.target.checked ? selected.add(j.id) : selected.delete(j.id);
        r.classList.toggle("sel", e.target.checked);
        drawBulk();
      } });
      const hasMail = j.emails.length || j.c_emails.length;
      const hasPhone = j.phones.length || j.c_phones.length;
      const sal = salary(j);
      const r = h("div.jrow" + (selected.has(j.id) ? ".sel" : ""), { onclick: () => openJob(j.id, load) },
        cb, logo(j.company || j.title),
        h("div", { style: { minWidth: 0 } },
          h("div.jt", j.status === "new" && j.first_seen > Date.now() / 1000 - 86400 ? [h("span.new-dot", { title: "Found in the last 24h" }), " "] : null, j.title),
          h("div.jmeta",
            j.company ? h("span.co", j.company) : null,
            h("span", flagOf(j.country), " ", locText(j)),
            j.remote ? h("span.badge.info", "Remote") : null,
            j.job_type ? h("span", j.job_type) : null,
            sal ? h("span.sal", sal) : null,
            statusBadge(j.status),
            j.closed_at ? h("span.badge.danger", "Closed") : null),
          insightChips(j.insights, true)),
        h("div.jright",
          h("div.row", { style: { gap: "8px" } }, j.match_score != null ? ring(j.match_score, 34) : null, h("span.when", when(j))),
          h("div.icons",
            h("span.ci" + (hasMail ? ".on" : ""), { title: hasMail ? "Email available" : "No email yet" }, icon("mail")),
            h("span.ci" + (hasPhone ? ".on" : ""), { title: hasPhone ? "Phone available" : "No phone yet" }, icon("phone")),
            h("span.ci" + (j.people_count ? ".on" : ""), { title: j.people_count ? j.people_count + " people to contact" : "No recruiter found yet" }, icon("users"))),
          h("div", { style: { display: "flex", gap: "4px" } }, j.sources.slice(0, 2).map((s) => h("span.srcb", srcLabel(s))))));
      return r;
    }

    let loading = false, again = false;
    async function load(silent) {
      if (loading) { again = true; return; }
      loading = true;
      if (!silent && !listBox.childElementCount) mount(listBox, spin());
      try {
        const res = await api.get("/api/jobs?" + qs(false));
        countEl.textContent = nfmt(res.total) + " jobs";
        if (!res.jobs.length) mount(listBox, opts.emptyState ? opts.emptyState() : empty("search", "No jobs match", "Try fewer filters."));
        else mount(listBox, res.jobs.map(row), res.pages > 1 ? h("div.pager",
          h("span", "Page " + res.page + " of " + nfmt(res.pages)),
          h("div.row", h("button.btn.btn-sm", { disabled: res.page <= 1, onclick: () => { state.page--; load(); window.scrollTo(0, 0); } }, icon("chevronLeft"), "Prev"),
            h("button.btn.btn-sm", { disabled: res.page >= res.pages, onclick: () => { state.page++; load(); window.scrollTo(0, 0); } }, "Next", icon("chevronRight")))) : null);
      } catch (e) { mount(listBox, empty("alert", "Couldn't load jobs", e.message)); }
      loading = false;
      if (again) { again = false; load(true); }
    }
    return { el, reload: (reset) => { if (reset) state.page = 1; return load(!reset); } };
  }

  // ================================================================ job drawer
  async function openJob(id, onChange) {
    $$(".drawer, .drawer-back").forEach((x) => x.remove());
    const back = h("div.drawer-back", { onclick: close });
    const dr = h("aside.drawer", { role: "dialog" }, spin());
    document.body.append(back, dr);
    function close() { dr.classList.add("out"); back.remove(); setTimeout(() => dr.remove(), 200); document.removeEventListener("keydown", esc); }
    function esc(e) { if (e.key === "Escape") close(); }
    document.addEventListener("keydown", esc);
    let j;
    async function load() {
      try { j = (await api.get("/api/jobs/" + id)).job; }
      catch (e) { mount(dr, h("div.dr-body", empty("alert", "Couldn't open this job", e.message))); return; }
      draw();
    }
    function contactLines(items, type) {
      return items.map((v) => h("div.cline", icon(type === "mail" ? "mail" : "phone"),
        h("a", { href: (type === "mail" ? "mailto:" : "tel:") + v.replace(/\s/g, "") }, v),
        h("button.btn.btn-ghost.btn-sm.copy", { onclick: async () => { await TT.copyText(v); toast("Copied", "ok", { duration: 1200 }); } }, icon("copy"))));
    }
    function draw() {
      const c = j.company_info || {};
      const sal = salary(j);
      const statusSel = sel(Object.entries(STATUS).map(([k, [l]]) => [k, l]), j.status, async (v) => {
        j = (await api("PATCH", "/api/jobs/" + id, { status: v })).job;
        toast("Moved to " + STATUS[v][0], "ok", { duration: 1400 });
        if (onChange) onChange(true);
      });
      statusSel.style.width = "auto";
      const notes = h("textarea.textarea", { placeholder: "Your notes — contacts, interview dates, follow-ups…", oninput: debounce(async (e) => {
        await api("PATCH", "/api/jobs/" + id, { notes: e.target.value });
      }, 600) }, j.notes || "");
      const terms = (LS.get("jr_last_query", {}).keywords || "").split(/[ ,]+/);
      const findBtn = h("button.btn.btn-sm.btn-primary", { onclick: () => withBusy(findBtn, async () => {
        try { await api.post("/api/companies/" + encodeURIComponent(j.company_key) + "/enrich", {}); await load(); toast("Company contacts updated", "ok"); }
        catch (e) { toast(e.message, "error"); }
      }) }, icon("wand"), c.enriched_at ? "Search again" : "Find recruiters & contacts");
      const people = j.people || [];
      const jobContacts = (j.contacts || []).map((p) => Object.assign({}, p, { source: "job post" }));
      const shown = [...jobContacts, ...people.filter((p) => !jobContacts.some((x) => x.name === p.name))];
      mount(dr,
        h("div.dr-head",
          h("div.dr-co", logo(j.company || j.title, 46), h("div", h("b", j.company || "Unknown company"),
            h("div.small.muted", c.domain ? h("a", { href: "https://" + c.domain, target: "_blank", rel: "noopener" }, c.domain) : (j.company_domain || ""))),
            h("span.spacer"), h("button.btn.btn-ghost.btn-icon", { "aria-label": "Close", onclick: close }, icon("x"))),
          h("h2", j.title),
          h("div.dr-chips",
            h("span.badge", j.flag + " " + (locText(j) || "—")),
            j.remote ? h("span.badge.info", j.worldwide ? "Remote · worldwide" : "Remote") : null,
            j.job_type ? h("span.badge", j.job_type) : null,
            sal ? h("span.badge.ok", sal) : null,
            h("span.badge", "Posted " + (when(j) || "—")),
            j.sources.map((s) => h("span.badge.accent", srcLabel(s)))),
          h("div.dr-actions",
            j.apply_url || j.url ? h("a.btn.btn-primary", { href: j.apply_url || j.url, target: "_blank", rel: "noopener" }, icon("external"), "Open & apply") : null,
            j.status === "new" ? h("button.btn", { onclick: async () => { j = (await api("PATCH", "/api/jobs/" + id, { status: "saved" })).job; draw(); toast("Saved", "ok"); if (onChange) onChange(true); } }, icon("bookmark"), "Save") : null,
            statusSel, h("span.spacer"),
            h("button.btn.btn-ghost.btn-sm", { onclick: async () => { await api("PATCH", "/api/jobs/" + id, { hidden: true }); toast("Hidden", "info"); close(); if (onChange) onChange(true); } }, icon("eyeOff"), "Hide"))),
        h("div.dr-body",
          h("div.contact-card",
            h("h4", icon("mail", "icon"), "Contacts in this job post"),
            j.emails.length || j.phones.length ? [contactLines(j.emails, "mail"), contactLines(j.phones, "phone")] : h("p.note", "The job post doesn't list an email or phone number.")),
          h("div.contact-card",
            h("h4", icon("users", "icon"), "People to contact", shown.length ? h("span.badge", String(shown.length)) : null, h("span.spacer"),
              j.company_key ? h("button.btn.btn-sm.btn-ghost", { onclick: () => openCompany(j.company_key) }, icon("building"), "Company profile") : null),
            shown.length ? h("div.people", shown.slice(0, 8).map((p) => personRow(p))) :
              h("p.note", c.enriched_at ? "This company doesn't publish named recruiters or managers on its website — use the emails below." :
                "Find the recruiter, HR team or hiring manager this company publishes on its website (team, about, imprint, contact pages)."),
            shown.length > 8 ? h("button.btn.btn-sm.btn-ghost", { onclick: () => openCompany(j.company_key) }, "+ " + (shown.length - 8) + " more") : null),
          matchCard(j),
          insightsCard(j.insights),
          h("div.contact-card",
            h("h4", icon("building", "icon"), "Company contacts", h("span.spacer"), findBtn),
            c.enriched_at ? [
              (c.emails || []).length ? emailGroups(c) : null,
              (c.phones || []).length ? contactLines(c.phones || [], "phone") : null,
              (c.socials || []).length ? h("div.cline", icon("link"), h("div.row.wrap", (c.socials || []).map((s) => h("a", { href: s, target: "_blank", rel: "noopener" }, s.replace(/^https?:\/\/(www\.)?/, ""))))) : null,
              h("p.tiny.faint", { style: { marginTop: "6px" } }, (c.enrich_status || "") + " · checked " + TT.timeAgo(c.enriched_at)),
            ] : h("p.note", "Search the company's public website (contact, about and imprint pages) for emails, phones and social profiles.")),
          h("h3", { style: { fontSize: "16px", margin: "6px 0 10px" } }, "Description"),
          j.description ? h("div.desc", highlight(j.description, terms)) : h("p.note", "No description provided by this source — open the job to read it."),
          h("h3", { style: { fontSize: "16px", margin: "22px 0 10px" } }, "Notes"), notes,
          h("p.tiny.faint", { style: { marginTop: "14px" } }, "First found " + TT.fmtDateTime(j.first_seen) + " · last seen " + TT.timeAgo(j.last_seen) + " · " + (j.url || ""))));
    }
    load();
  }

  // ================================================================ shell
  const content = h("div.content");
  const titleEl = h("h1");
  const subEl = h("div.sub");
  const actionsEl = h("div.top-actions");
  const side = h("aside.side");
  let cleanup = null;
  const ROUTES = [
    { id: "search", title: "Search", icon: "radar", render: pageSearch },
    { id: "jobs", title: "All jobs", icon: "briefcase", render: pageJobs },
    { id: "pipeline", title: "My pipeline", icon: "kanban", render: pagePipeline },
    { id: "cvmatch", title: "CV check & match", icon: "sparkles", render: pageCv },
    { id: "signals", title: "Hiring signals", icon: "flame", render: pageSignals },
    { id: "outreach", title: "Spontaneous applications", icon: "send", render: pageOutreach },
    { id: "night", title: "Night scan", icon: "moon", render: pageNight },
    { id: "profile", title: "My profile & autofill", icon: "note", render: pageProfile },
    { id: "companies", title: "Companies", icon: "building", render: pageCompanies },
    { id: "recruiters", title: "Recruiters", icon: "users", render: pageRecruiters },
    { id: "alerts", title: "Alerts & inbox", icon: "bell", render: pageAlerts },
    { id: "sources", title: "Sources", icon: "database", render: pageSources },
    { id: "settings", title: "Settings", icon: "settings", render: pageSettings },
  ];

  function buildSide() {
    const nav = h("nav.nav", ROUTES.map((r) => h("a", { href: "#/" + r.id, dataset: { r: r.id } }, icon(r.icon), r.title,
      r.id === "jobs" ? h("span.count", { id: "jobs-count", hidden: true }) : r.id === "alerts" ? h("span.count", { id: "alerts-count", hidden: true }) : null)));
    mount(side, h("div.brand", h("span.brand-mark", icon("radar")), h("div", "JobRadar", h("small", "Worldwide job search"))), nav,
      h("div.side-foot", h("div#run-mini"), h("div.tiny.faint", { style: { padding: "0 8px" } }, "v" + META.version + " · personal use")));
  }

  function renderShell() {
    const notifBtn = h("button.btn.btn-ghost.btn-icon.bell", { "aria-label": "Notifications", onclick: showNotifs }, icon("bell"), h("span.dotn", { id: "notif-dot", hidden: true }));
    mount($("#app"), h("div.shell", side, h("div.main",
      h("header.topbar", h("button.btn.btn-ghost.btn-icon.hamb", { onclick: () => { side.classList.add("open"); document.body.append(h("div.scrim", { onclick: (e) => { side.classList.remove("open"); e.target.remove(); } })); } }, icon("menu")),
        h("div", titleEl, subEl), actionsEl, notifBtn),
      content)));
    buildSide();
  }

  async function showNotifs(e) {
    $$(".notif-pop").forEach((x) => x.remove());
    const res = await api.get("/api/notifications");
    const pop = h("div.notif-pop", res.notifications.length ? res.notifications.map((n) => h("a", { href: n.link || "#/jobs", onclick: () => pop.remove() },
      h("b", n.text), h("small", TT.timeAgo(n.created_at)))) : h("p.note", { style: { padding: "14px" } }, "No notifications yet. Saved searches that run on a schedule will notify you here."));
    document.querySelector(".main").append(pop);
    api.post("/api/notifications", {});
    $("#notif-dot").hidden = true;
    setTimeout(() => document.addEventListener("pointerdown", function off(ev) { if (!pop.contains(ev.target)) { pop.remove(); document.removeEventListener("pointerdown", off); } }), 0);
  }

  async function refreshStats() {
    try {
      STATS = (await api.get("/api/stats")).stats;
      const jc = $("#jobs-count");
      if (jc) { jc.hidden = !STATS.today; jc.textContent = STATS.today > 999 ? "999+" : STATS.today; jc.title = "Found today"; }
      const nd = $("#notif-dot");
      if (nd) nd.hidden = !STATS.unread;
      const rm = $("#run-mini");
      if (rm) mount(rm, STATS.active_runs.length ? h("div.run-mini", { onclick: () => { location.hash = "#/search"; } }, h("div.spinner"), STATS.active_runs.length + " search running…") : null);
    } catch (_) { /* offline */ }
  }

  function route() {
    const [id, qstr] = location.hash.replace(/^#\/?/, "").split("?");
    let r = ROUTES.find((x) => x.id === id);
    if (!r) { r = ROUTES[0]; history.replaceState(null, "", "#/search"); }
    if (cleanup) { try { cleanup(); } catch (_) { /* ignore */ } cleanup = null; }
    side.classList.remove("open");
    $$(".scrim, .menu-pop, .notif-pop").forEach((x) => x.remove());
    $$(".nav a", side).forEach((a) => a.classList.toggle("active", a.dataset.r === r.id));
    titleEl.textContent = r.title;
    subEl.textContent = "";
    clear(actionsEl);
    mount(content, spin());
    document.title = r.title + " · JobRadar";
    Promise.resolve(r.render(new URLSearchParams(qstr || ""))).then((c) => { cleanup = typeof c === "function" ? c : null; })
      .catch((e) => mount(content, empty("alert", "Something went wrong", e.message, h("button.btn", { onclick: route }, "Retry"))));
  }

  // ================================================================ SEARCH
  async function pageSearch() {
    subEl.textContent = "Every source, every country — at once";
    const last = LS.get("jr_last_query", {});
    if (!LS.get("jr_strict_v2", false)) { last.include_worldwide = false; LS.set("jr_strict_v2", true); }
    const q = Object.assign({ keywords: "", country: "", region: "", city: "", remote: "any", days: 0, job_type: "", max_per_source: 500,
      match_description: false, include_worldwide: false, multilingual: true, sources: null, max_per_source: 1000 }, last);
    if (q.multilingual === undefined) q.multilingual = true;
    const kw = h("input.input", { value: q.keywords, placeholder: "Job title, skill or company — commas = OR (e.g. nurse, caregiver)", autofocus: true,
      onkeydown: (e) => { if (e.key === "Enter") go(); }, oninput: debounce(() => showExpansion(), 350) });
    const expandLine = h("div.expand-line");
    async function showExpansion() {
      if (!q.multilingual || !kw.value.trim()) return clear(expandLine);
      try {
        const r = await api.get("/api/expand?" + new URLSearchParams({ q: kw.value, country: q.country }));
        mount(expandLine, r.extra.length ? [icon("globe", "icon"), h("span", "Also searching in other languages: "),
          r.extra.slice(0, 10).map((w) => h("span.xterm", w)), r.extra.length > 10 ? h("span.xmore", "+ more") : null] : []);
      } catch (_) { /* ignore */ }
    }
    const regionIn = h("input.input", { value: q.region, placeholder: "State / region", list: "jr-regions", oninput: (e) => { q.region = e.target.value; } });
    const regionsDl = h("datalist#jr-regions");
    const fillRegions = () => mount(regionsDl, (META.regions[q.country] || []).map((r) => h("option", { value: r })));
    const combo = countryCombo(q.country, (cc) => { q.country = cc; fillRegions(); showExpansion(); });
    fillRegions();
    const cityIn = h("input.input", { value: q.city, placeholder: "City", oninput: (e) => { q.city = e.target.value; }, onkeydown: (e) => { if (e.key === "Enter") go(); } });
    const goBtn = h("button.btn.btn-go", { onclick: () => go() }, icon("radar"), "Search");
    const remoteSeg = h("div.seg", [["any", "Any"], ["remote", "Remote"], ["onsite", "On-site"]].map(([v, l]) =>
      h("button" + (q.remote === v ? ".on" : ""), { onclick: (e) => { q.remote = v; $$("button", remoteSeg).forEach((b) => b.classList.toggle("on", b === e.currentTarget)); } }, l)));
    const daysSel = sel([[0, "Any time"], [1, "Past 24 hours"], [3, "Past 3 days"], [7, "Past week"], [14, "Past 2 weeks"], [30, "Past month"]], q.days, (v) => { q.days = +v; }, "sm");
    let advOpen = LS.get("jr_adv", false);
    const adv = h("div.adv", { hidden: !advOpen });
    const srcOn = new Set(q.sources || META.sources.filter((s) => s.ready && !(META.settings.disabled_sources || []).includes(s.id)).map((s) => s.id));
    function drawAdv() {
      mount(adv,
        h("div.grid-3",
          field("Job type", h("input.input", { value: q.job_type, placeholder: "full-time, contract, internship…", oninput: (e) => { q.job_type = e.target.value; } })),
          field("Max results per source", sel([[100, "100"], [300, "300"], [500, "500"], [1000, "1,000"], [2000, "2,000"], [5000, "5,000 (deep)"]], q.max_per_source, (v) => { q.max_per_source = +v; })),
          h("div.stack", { style: { gap: "10px", paddingTop: "22px" } },
            h("label.switch", h("input", { type: "checkbox", checked: q.match_description, onchange: (e) => { q.match_description = e.target.checked; } }), h("span.track"), "Also match keywords in descriptions"),
            h("label.switch", h("input", { type: "checkbox", checked: q.include_worldwide, onchange: (e) => { q.include_worldwide = e.target.checked; } }), h("span.track"), "Also include remote jobs open to this country"),
            h("label.switch", h("input", { type: "checkbox", checked: q.multilingual, onchange: (e) => { q.multilingual = e.target.checked; showExpansion(); } }), h("span.track"), "Search in all languages (EN · FR · DE · ES · IT · PT · NL · AR)"))),
        h("div", h("div.label", { style: { marginBottom: "8px" } }, "Sources"),
          h("div.chips", META.sources.map((s) => h("button.chip" + (!s.ready ? ".off" : srcOn.has(s.id) ? ".on" : ""), {
            title: s.ready ? s.coverage : "Needs setup in Sources (free API key)",
            onclick: (e) => { if (!s.ready) { location.hash = "#/sources"; return; } srcOn.has(s.id) ? srcOn.delete(s.id) : srcOn.add(s.id); e.currentTarget.classList.toggle("on"); },
          }, s.name + (s.ready ? "" : " 🔑"))))));
    }
    drawAdv();
    const hero = h("section.hero",
      h("h2", "Find jobs anywhere on Earth"),
      h("p", "Searches job boards, remote boards, government portals and thousands of company career pages at once."),
      h("div.sform", h("div.kw", icon("search"), kw), combo, h("div", regionIn, regionsDl), cityIn, goBtn),
      expandLine,
      h("div.hero-row2", remoteSeg, daysSel,
        h("button.link", { onclick: () => { advOpen = !advOpen; LS.set("jr_adv", advOpen); adv.hidden = !advOpen; } }, icon("sliders"), "Advanced & sources"),
        h("span.spacer"),
        h("button.link", { onclick: saveAlert }, icon("bell"), "Save as alert")),
      adv);

    const progBox = h("div");
    const recentBox = h("div.recent");
    const nightBanner = STATS && STATS.night && !STATS.night.seen ? h("a.alert-box.night-banner", { href: "#/night" }, icon("moon"),
      h("div", h("b", STATS.night.headline), h("div.small.muted", "Your night deep scan finished " + TT.timeAgo(STATS.night.finished_at) + " - open the morning report →"))) : null;
    let list = null;
    const listWrap = h("div");
    mount(content, nightBanner, hero, progBox, recentBox, listWrap);
    showExpansion();

    let runId = LS.get("jr_active_run", null);
    let timer = null;

    function params() {
      return { keywords: kw.value.trim(), country: q.country, region: regionIn.value.trim(), city: cityIn.value.trim(), remote: q.remote, days: q.days,
        job_type: q.job_type, max_per_source: q.max_per_source, match_description: q.match_description, include_worldwide: q.include_worldwide,
        multilingual: q.multilingual, sources: srcOn.size ? [...srcOn] : null };
    }

    async function go(p) {
      p = p || params();
      LS.set("jr_last_query", p);
      await withBusy(goBtn, async () => {
        try {
          const res = await api.post("/api/search", p);
          runId = res.run_id;
          LS.set("jr_active_run", runId);
          showResults();
          poll();
        } catch (e) { toast(e.message, "error"); }
      });
    }

    function saveAlert() {
      const p = params();
      const name = h("input.input", { value: [p.keywords || "All jobs", p.country ? countryName(p.country) : "", p.city || p.region].filter(Boolean).join(" · ") });
      const every = sel([[0, "Only when I click Run"], [1, "Every hour"], [3, "Every 3 hours"], [6, "Every 6 hours"], [12, "Every 12 hours"], [24, "Every day"]], 6, () => {});
      const saveBtn = h("button.btn.btn-primary", { onclick: async () => {
        try { await api.post("/api/searches", { name: name.value, params: p, every_hours: +every.value }); m.close(); toast("Alert saved — you'll be notified of new jobs", "ok"); }
        catch (e) { toast(e.message, "error"); }
      } }, "Save alert");
      const m = modal({ title: "Save this search as an alert", size: "narrow", body: h("div.stack", field("Name", name), field("Run automatically", every, "JobRadar must be running for scheduled searches.")),
        foot: [h("button.btn.btn-ghost", { onclick: () => m.close() }, "Cancel"), saveBtn] });
    }

    function showResults() {
      list = JobList({ filters: () => ({ run: runId }), searchPlaceholder: "Filter these results…",
        emptyState: () => empty("radar", "Scanning…", "Matches appear here as each source reports in.") });
      mount(listWrap, list.el);
      list.reload(true);
    }

    async function poll() {
      clearTimeout(timer);
      if (!runId) return;
      let r;
      try { r = (await api.get("/api/runs/" + runId)).run; }
      catch (e) { LS.del("jr_active_run"); runId = null; clear(progBox); return; }
      drawProgress(r);
      if (list) list.reload(false);
      if (r.status === "running") timer = setTimeout(poll, 1500);
      else { refreshStats(); drawRecent(); }
    }

    function drawProgress(r) {
      const prog = Object.entries(r.progress || {});
      const done = prog.filter(([, p]) => ["done", "error", "stopped"].includes(p.status)).length;
      const pct = prog.length ? Math.round((done / prog.length) * 100) : 0;
      const running = r.status === "running";
      const p = r.params || {};
      mount(progBox, h("div.card.card-pad.prog",
        h("div.prog-head",
          h("div", h("h3", running ? "Searching…" : r.status === "stopped" ? "Search stopped" : r.status === "interrupted" ? "Search interrupted" : "Search complete"),
            h("div.small.muted", [p.keywords || "All jobs", p.country ? flagOf(p.country) + " " + countryName(p.country) : "🌍 Anywhere", p.region, p.city, p.remote !== "any" ? p.remote : ""].filter(Boolean).join(" · "))),
          h("span.spacer"),
          h("div.big-num", nfmt(r.found), h("small", "matches")),
          h("div.big-num", { style: { color: "var(--accent)" } }, nfmt(r.new), h("small", "new")),
          running ? h("button.btn.btn-sm", { onclick: async () => { await api.post("/api/runs/" + r.id + "/stop", {}); toast("Stopping…", "info"); } }, icon("stop"), "Stop") : null,
          ["stopped", "interrupted", "error"].includes(r.status) ? h("button.btn.btn-sm.btn-primary", { onclick: async (e) => {
            await withBusy(e.currentTarget, async () => {
              try { await api.post("/api/runs/" + r.id + "/resume", {}); toast("Resuming — finished sources are skipped", "ok"); poll(); }
              catch (err) { toast(err.message, "error"); }
            });
          } }, icon("play"), "Resume") : null),
        r.note ? h("div.alert-box.warn", { style: { marginTop: "12px" } }, icon("wifiOff"), h("div", r.note)) : null,
        r.status === "interrupted" ? h("div.alert-box", { style: { marginTop: "12px" } }, icon("info"),
          h("div", "This search was cut off (the app closed or the PC shut down). Click Resume to continue where it stopped — nothing is lost.")) : null,
        h("div.pbar" + (running ? ".live" : ""), h("i", { style: { width: (running ? Math.max(6, pct) : 100) + "%" } })),
        h("div.tiny.faint", done + " of " + prog.length + " sources finished" + (running ? "" : " · " + TT.timeAgo(r.finished_at || r.started_at))),
        h("div.srcs", prog.map(([id, s]) => h("div.src." + s.status,
          h("span.st", s.status === "running" ? h("div.spinner") : icon(s.status === "done" ? "check" : s.status === "error" ? "alert" : s.status === "stopped" ? "stop" : "clock")),
          h("div", { style: { minWidth: 0 } }, h("b", s.name), s.error ? h("div.err", s.error) : h("div.msg", { title: s.message }, s.message || (s.status === "queued" ? "waiting" : ""))),
          h("span.n", nfmt(s.found)))))));
    }

    async function drawRecent() {
      try {
        const res = await api.get("/api/runs");
        const seen = new Set();
        const items = res.runs.filter((r) => { const k = JSON.stringify([r.params.keywords, r.params.country, r.params.region, r.params.city]); if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 8);
        mount(recentBox, items.length ? [h("span.small.muted", { style: { alignSelf: "center" } }, "Recent:"), items.map((r) => h("button", {
          onclick: () => { runId = r.id; LS.set("jr_active_run", r.id); showResults(); poll(); },
          title: "Show results (" + r.found + ")",
        }, icon("clock"), (r.params.keywords || "All jobs") + (r.params.country ? " · " + flagOf(r.params.country) : "") + " · " + nfmt(r.found)))] : []);
      } catch (_) { /* ignore */ }
    }

    drawRecent();
    if (runId) { showResults(); poll(); }
    else mount(listWrap, h("div.card", empty("radar", "Ready when you are", "Type a job title, pick a country (or leave it on Anywhere) and hit Search. Tip: separate alternatives with commas.")));
    return () => clearTimeout(timer);
  }

  // ================================================================ ALL JOBS
  async function pageJobs(params) {
    const f = { country: params.get("country") || "", region: "", days: 0, source: params.get("source") || "", status: params.get("status") || "",
      company_key: params.get("company") || "", run: params.get("run") || "" };
    await refreshStats();
    const s = STATS;
    subEl.textContent = nfmt(s.jobs) + " jobs in your database";
    const kpi = (ic, l, v) => h("div.card.kpi", h("div.l", icon(ic), l), h("div.v", nfmt(v)));
    const combo = countryCombo(f.country, (cc) => { f.country = cc; list.reload(true); }, { placeholder: "🌍 Any country" });
    combo.style.minWidth = "200px";
    const region = h("input.input", { placeholder: "Region / city", style: { width: "150px" }, oninput: debounce((e) => { f.region = e.target.value; list.reload(true); }, 300) });
    const days = sel([[0, "Any date"], [1, "24 hours"], [3, "3 days"], [7, "7 days"], [30, "30 days"]], 0, (v) => { f.days = +v; list.reload(true); });
    const srcSel = sel([["", "All sources"]].concat(META.sources.map((x) => [x.id, x.name])).concat([["alert", "Email alerts"]]), f.source, (v) => { f.source = v; list.reload(true); });
    const stSel = sel([["", "Any status"]].concat(Object.entries(STATUS).map(([k, [l]]) => [k, l])), f.status, (v) => { f.status = v; list.reload(true); });
    const contractSel = sel([["", "Any contract"], ["Permanent", "Permanent / CDI"], ["Fixed-term", "Fixed-term / CDD"], ["Freelance", "Freelance / contract"],
      ["Internship", "Internship / stage"], ["Apprenticeship", "Apprenticeship"], ["Part-time", "Part-time"], ["Full-time", "Full-time"]], "", (v) => { f.contract = v; list.reload(true); });
    const expSel = sel([[0, "Any experience"], [1, "≤ 1 year"], [2, "≤ 2 years"], [3, "≤ 3 years"], [5, "≤ 5 years"], [8, "≤ 8 years"]], 0, (v) => { f.max_exp = +v; list.reload(true); });
    const list = JobList({
      initial: { sort: params.get("sort") || "", min_match: params.get("min_match") || 0 },
      filters: () => ({ country: f.country, region: f.region, days: f.days, source: f.source, status: f.status, company_key: f.company_key, run: f.run,
        contract: f.contract || "", max_exp: f.max_exp || "" }),
      extraFilters: [combo, region, days, srcSel, stSel, contractSel, expSel],
      emptyState: () => empty("briefcase", s.jobs ? "No jobs match these filters" : "No jobs yet", s.jobs ? "Clear a filter or two." : "Run your first search.", s.jobs ? null : h("a.btn.btn-primary", { href: "#/search" }, icon("radar"), "Search jobs")),
    });
    mount(content,
      h("div.kpis", kpi("briefcase", "Jobs", s.jobs), kpi("zap", "Found today", s.today), kpi("mail", "With email", s.with_email),
        kpi("phone", "With phone", s.with_phone), kpi("building", "Companies", s.companies), kpi("globe", "Countries", s.countries)),
      f.company_key || f.run ? h("div.alert-box", { style: { marginBottom: "12px" } }, icon("filter"),
        h("div", f.company_key ? "Showing jobs of one company." : "Showing results of one search run.", " ", h("a", { href: "#/jobs" }, "Show all jobs"))) : null,
      list.el);
    list.reload(true);
  }

  // ================================================================ PIPELINE
  async function pagePipeline() {
    subEl.textContent = "Drag cards between columns to track your applications";
    const cols = ["saved", "applied", "interview", "offer", "rejected"];
    const board = h("div.board");
    mount(content, board);
    async function load() {
      const data = await Promise.all(cols.map((c) => api.get("/api/jobs?status=" + c + "&per=200&sort=found")));
      mount(board, cols.map((c, i) => {
        const col = h("div.col", { dataset: { st: c } },
          h("div.col-head", icon(STATUS[c][1], "icon"), STATUS[c][0], h("span.n", String(data[i].total))),
          data[i].jobs.map((j) => {
            const card = h("div.kcard", { draggable: "true", dataset: { id: j.id }, onclick: () => openJob(j.id, load),
              ondragstart: (e) => { e.dataTransfer.setData("text/plain", j.id); card.classList.add("dragging"); },
              ondragend: () => card.classList.remove("dragging") },
              h("b", j.title), h("small", (j.company || "") + " · " + flagOf(j.country) + " " + (j.city || j.country || (j.remote ? "Remote" : ""))));
            return card;
          }),
          !data[i].jobs.length ? h("div.tiny.faint", { style: { textAlign: "center", padding: "30px 6px" } }, c === "saved" ? "Save jobs from search results to start" : "Drop jobs here") : null);
        col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("over"); });
        col.addEventListener("dragleave", () => col.classList.remove("over"));
        col.addEventListener("drop", async (e) => {
          e.preventDefault();
          col.classList.remove("over");
          const id = e.dataTransfer.getData("text/plain");
          if (!id) return;
          await api("PATCH", "/api/jobs/" + id, { status: c });
          toast("Moved to " + STATUS[c][0], "ok", { duration: 1300 });
          load();
        });
        return col;
      }));
    }
    await load();
  }

  // ================================================================ COMPANIES
  async function pageCompanies(params) {
    subEl.textContent = "Every employer in your results — recruiters, emails and profile from their own websites";
    if (params && params.get("open")) setTimeout(() => openCompany(params.get("open")), 50);
    const st = { q: "", has: false, page: 1 };
    const statusBox = h("div");
    const tableBox = h("div.card");
    const bulkBtn = h("button.btn.btn-primary", { onclick: async () => {
      const r = await api.post("/api/enrich/bulk", { all_missing: true });
      toast("Finding contacts for " + r.queued + " companies in the background", "info");
      watch();
    } }, icon("wand"), "Find recruiters for all new companies");
    mount(actionsEl, bulkBtn);
    const hasTg = h("button.tgl", { onclick: () => { st.has = !st.has; hasTg.classList.toggle("on", st.has); st.page = 1; load(); } }, icon("mail"), "Has contacts");
    mount(content, statusBox,
      h("div.fbar", h("div.search-input", icon("search"), h("input.input", { placeholder: "Search companies or domains…", oninput: debounce((e) => { st.q = e.target.value; st.page = 1; load(); }, 250) })), hasTg),
      tableBox);
    let wt = null;
    async function watch() {
      clearTimeout(wt);
      const s = (await api.get("/api/enrich/status")).status;
      if (s.running || s.total) {
        mount(statusBox, h("div.card.card-pad", { style: { marginBottom: "14px" } },
          h("div.row", h("div.spinner"), h("b", "Finding contacts… " + s.done + " / " + s.total), h("span.muted.small", s.current), h("span.spacer"),
            h("button.btn.btn-sm", { onclick: async () => { await api.post("/api/enrich/cancel", {}); toast("Cancelled", "info"); } }, "Cancel")),
          h("div.pbar", h("i", { style: { width: (s.total ? (s.done / s.total) * 100 : 0) + "%" } }))));
        wt = setTimeout(() => { watch(); load(true); }, 2500);
      } else clear(statusBox);
    }
    async function load(silent) {
      if (!silent) mount(tableBox, spin());
      const res = await api.get("/api/companies?" + new URLSearchParams({ q: st.q, has_contact: st.has ? 1 : "", page: st.page }));
      if (!res.companies.length) return mount(tableBox, empty("building", "No companies yet", "Companies appear here after your searches."));
      mount(tableBox, h("div.table-wrap", h("table.dtable",
        h("thead", h("tr", ["Company", "Jobs", "People", "Countries", "Emails", "Phones", "Status", ""].map((c) => h("th", c)))),
        h("tbody", res.companies.map((c) => {
          const btn = h("button.btn.btn-sm", { onclick: () => withBusy(btn, async () => {
            try { await api.post("/api/companies/" + encodeURIComponent(c.key) + "/enrich", {}); toast("Updated " + c.name, "ok"); load(true); }
            catch (e) { toast(e.message, "error"); }
          }) }, icon("wand"), c.enriched_at ? "Again" : "Find recruiters");
          const types = c.email_types || {};
          return h("tr",
            h("td", h("div.row", logo(c.name, 34), h("div", h("a.strong", { href: "#", onclick: (e) => { e.preventDefault(); openCompany(c.key); } }, c.name),
              h("div.tiny", c.domain ? h("a", { href: "https://" + c.domain, target: "_blank", rel: "noopener" }, c.domain) : h("span.faint", "no website yet"), " ",
                h("button.btn.btn-ghost.btn-sm", { style: { minHeight: "22px", padding: "0 6px" }, title: "Set website", onclick: () => setDomain(c) }, icon("edit")))))),
            h("td", h("a", { href: "#/jobs?company=" + encodeURIComponent(c.key) }, nfmt(c.jobs_count))),
            h("td", c.people_count ? h("a", { href: "#", onclick: (e) => { e.preventDefault(); openCompany(c.key); } },
              h("span.badge" + (c.hr_count ? ".ok" : ""), c.people_count + (c.hr_count ? " · " + c.hr_count + " HR" : ""))) : h("span.faint", "—")),
            h("td", (c.countries || "").split(",").filter(Boolean).slice(0, 6).map((cc) => h("span", { title: countryName(cc) }, flagOf(cc) + " "))),
            h("td.small", c.emails.slice(0, 3).map((e) => h("div", h("a", { href: "mailto:" + e }, e),
              types[e] === "recruiting" ? h("span.badge.ok", { style: { marginLeft: "6px" } }, "jobs") : null)),
              c.emails.length > 3 ? h("span.faint", "+" + (c.emails.length - 3)) : null),
            h("td.small", c.phones.slice(0, 2).map((p) => h("div", h("a", { href: "tel:" + p.replace(/\s/g, "") }, p)))),
            h("td.tiny.muted", c.enriched_at ? [c.enrich_status, h("br"), TT.timeAgo(c.enriched_at)] : "—"),
            h("td", btn));
        })))),
        res.pages > 1 ? h("div.pager", h("span", "Page " + res.page + " of " + res.pages + " · " + nfmt(res.total) + " companies"),
          h("div.row", h("button.btn.btn-sm", { disabled: res.page <= 1, onclick: () => { st.page--; load(); } }, icon("chevronLeft")),
            h("button.btn.btn-sm", { disabled: res.page >= res.pages, onclick: () => { st.page++; load(); } }, icon("chevronRight")))) : null);
    }
    function setDomain(c) {
      const inp = h("input.input", { value: c.domain, placeholder: "company.com" });
      const b = h("button.btn.btn-primary", { onclick: async () => { await api("PATCH", "/api/companies/" + encodeURIComponent(c.key), { domain: inp.value }); m.close(); toast("Website saved", "ok"); load(true); } }, "Save");
      const m = modal({ title: "Website of " + c.name, size: "narrow", body: field("Domain", inp, "Used to find contact pages."), foot: [h("button.btn.btn-ghost", { onclick: () => m.close() }, "Cancel"), b] });
    }
    await load();
    watch();
    return () => clearTimeout(wt);
  }

  // ================================================================ RECRUITERS (people directory)
  async function pageRecruiters() {
    subEl.textContent = "Recruiters, HR and hiring managers published by the companies in your results";
    const st = { q: "", role: "", has_email: false, country: "", page: 1 };
    const listBox = h("div");
    const countsBox = h("div.kpis", { style: { gridTemplateColumns: "repeat(auto-fill,minmax(170px,1fr))" } });
    const qs = (extra) => new URLSearchParams(Object.assign({ q: st.q, role: st.role, has_email: st.has_email ? 1 : "", country: st.country, page: st.page }, extra || {})).toString();
    mount(actionsEl,
      h("button.btn", { onclick: (e) => popMenu(e.currentTarget, [
        { icon: "download", label: "Export to Excel (.xlsx)", run: () => download("/api/export/people?format=xlsx&" + qs()) },
        { icon: "download", label: "Export to CSV", run: () => download("/api/export/people?format=csv&" + qs()) },
      ]) }, icon("download"), "Export"),
      h("button.btn.btn-primary", { onclick: async () => {
        const r = await api.post("/api/enrich/bulk", { all_missing: true });
        toast("Scanning " + r.queued + " company websites for recruiters — see progress on Companies", "info", { duration: 5000 });
      } }, icon("wand"), "Find recruiters for all new companies"));
    const roleSeg = h("div.seg", [["", "All"], ["hr", "HR / Recruiting"], ["leader", "Leadership"], ["manager", "Hiring managers"]].map(([v, l]) =>
      h("button" + (v === st.role ? ".on" : ""), { onclick: (e) => { st.role = v; st.page = 1; $$("button", roleSeg).forEach((b) => b.classList.toggle("on", b === e.currentTarget)); load(); } }, l)));
    const mailTg = h("button.tgl", { onclick: () => { st.has_email = !st.has_email; mailTg.classList.toggle("on", st.has_email); st.page = 1; load(); } }, icon("mail"), "Has email");
    const combo = countryCombo("", (cc) => { st.country = cc; st.page = 1; load(); }, { placeholder: "🌍 Any country" });
    combo.style.minWidth = "200px";
    mount(content, countsBox,
      h("div.fbar", h("div.search-input", icon("search"), h("input.input", { placeholder: "Search name, title, company or email…", oninput: debounce((e) => { st.q = e.target.value; st.page = 1; load(); }, 250) })),
        roleSeg, mailTg, combo),
      listBox);
    async function load() {
      mount(listBox, spin());
      const res = await api.get("/api/people?" + qs());
      const c = res.counts || {};
      const total = Object.values(c).reduce((a, b) => a + b, 0);
      mount(countsBox,
        h("div.card.kpi", h("div.l", icon("users"), "People found"), h("div.v", nfmt(total))),
        h("div.card.kpi", h("div.l", icon("users"), "HR / Recruiting"), h("div.v", nfmt(c.hr || 0))),
        h("div.card.kpi", h("div.l", icon("star"), "Leadership"), h("div.v", nfmt(c.leader || 0))),
        h("div.card.kpi", h("div.l", icon("briefcase"), "Hiring managers"), h("div.v", nfmt(c.manager || 0))));
      if (!res.people.length) {
        return mount(listBox, h("div.card", empty("users", total ? "Nobody matches these filters" : "No recruiters found yet",
          total ? "Try another filter." : "Open a job and click “Find recruiters & contacts”, or scan all companies at once.",
          total ? null : h("a.btn.btn-primary", { href: "#/companies" }, icon("building"), "Go to Companies"))));
      }
      mount(listBox, h("div.card", h("div.people.people-list", res.people.map((p) => personRow(p, { company: true })))),
        res.pages > 1 ? h("div.pager", h("span", "Page " + res.page + " of " + res.pages + " · " + nfmt(res.total) + " people"),
          h("div.row", h("button.btn.btn-sm", { disabled: res.page <= 1, onclick: () => { st.page--; load(); } }, icon("chevronLeft")),
            h("button.btn.btn-sm", { disabled: res.page >= res.pages, onclick: () => { st.page++; load(); } }, icon("chevronRight")))) : null);
    }
    await load();
  }

  // ================================================================ ALERTS & INBOX
  async function pageAlerts() {
    subEl.textContent = "Saved searches that run by themselves + jobs from your alert emails";
    const box = h("div");
    const inbox = h("div");
    mount(content, h("div.sec-title", icon("bell", "icon"), "Saved searches"), box, h("div.sec-title", icon("inbox", "icon"), "Import from job-alert emails"), inbox);
    const EVERY = [[0, "Manual"], [1, "Every hour"], [3, "Every 3 h"], [6, "Every 6 h"], [12, "Every 12 h"], [24, "Daily"]];
    async function load() {
      const res = await api.get("/api/searches");
      if (!res.searches.length) return mount(box, h("div.card", empty("bell", "No saved searches", "On the Search page, set your filters and click “Save as alert”.", h("a.btn.btn-primary", { href: "#/search" }, "Go to Search"))));
      mount(box, h("div.card", h("div.table-wrap", h("table.dtable",
        h("thead", h("tr", ["Search", "Schedule", "Last run", "New", ""].map((c) => h("th", c)))),
        h("tbody", res.searches.map((s) => {
          const p = s.params;
          const every = sel(EVERY, s.every_hours, async (v) => { await api.put("/api/searches/" + s.id, { every_hours: +v }); toast("Schedule updated", "ok"); });
          every.style.width = "auto";
          return h("tr",
            h("td", h("b", s.name), h("div.tiny.muted", [p.keywords || "All jobs", p.country ? flagOf(p.country) + " " + countryName(p.country) : "🌍", p.region, p.city, p.remote !== "any" ? p.remote : ""].filter(Boolean).join(" · "))),
            h("td", every),
            h("td.small.muted", s.running ? h("span.row", h("div.spinner", { style: { width: "14px", height: "14px" } }), "running") : s.last_run ? TT.timeAgo(s.last_run) : "never"),
            h("td", s.unseen ? h("span.badge.accent", "+" + s.unseen) : h("span.faint", "—")),
            h("td", h("div.row", { style: { justifyContent: "flex-end" } },
              h("button.btn.btn-sm", { onclick: async () => { const r = await api.post("/api/searches/" + s.id + "/run", {}); LS.set("jr_active_run", r.run_id); LS.set("jr_last_query", p); location.hash = "#/search"; } }, icon("play"), "Run"),
              h("button.btn.btn-sm", { onclick: async () => { await api.post("/api/searches/" + s.id + "/seen", {}); LS.set("jr_last_query", p); location.hash = "#/search"; } }, "Open"),
              h("button.btn.btn-sm.btn-ghost.btn-icon", { "aria-label": "Delete", onclick: async () => { if (await confirmDialog({ title: "Delete “" + s.name + "”?", ok: "Delete", danger: true })) { await api.del("/api/searches/" + s.id); load(); } } }, icon("trash")))));
        }))))));
    }
    const st = META.settings;
    const f = {
      imap_host: h("input.input", { value: st.imap_host }), imap_user: h("input.input", { value: st.imap_user, placeholder: "you@gmail.com" }),
      imap_password: h("input.input", { type: "password", value: st.imap_password, placeholder: "16-character app password" }),
      imap_folder: h("input.input", { value: st.imap_folder }), imap_days: h("input.input", { type: "number", min: 1, max: 365, value: st.imap_days }),
    };
    const statusEl = h("div");
    const importBtn = h("button.btn.btn-primary", { onclick: async () => {
      await api.put("/api/settings", Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value])));
      const r = await api.post("/api/alerts/import", {});
      if (!r.started && r.state.error) toast(r.state.error, "error");
      watchImport();
    } }, icon("inbox"), "Save & import now");
    let it = null;
    async function watchImport() {
      clearTimeout(it);
      const s = (await api.get("/api/alerts/status")).state;
      mount(statusEl, s.error ? h("div.alert-box.warn", icon("alert"), s.error) : s.message ? h("div.alert-box", s.running ? h("div.spinner", { style: { width: "18px", height: "18px" } }) : icon("check"), s.message) : null);
      if (s.running) it = setTimeout(watchImport, 1500);
    }
    mount(inbox, h("div.card.card-pad", h("div.grid-2",
      h("div.stack",
        h("p.note", "Get LinkedIn, Indeed and Glassdoor jobs the safe way: create free job alerts on those sites (any keyword, any country). JobRadar reads the alert emails from your mailbox (read-only) and adds every job here — no scraping, no risk to your accounts."),
        h("ol.note", { style: { paddingLeft: "18px", margin: 0 } },
          h("li", "On LinkedIn / Indeed / Glassdoor: search a job → turn on “Job alert” / “Get new jobs by email”."),
          h("li", "Gmail: enable 2-Step Verification, then create an App Password (Google Account → Security → App passwords)."),
          h("li", "Enter it here and click Import. Repeat anytime — duplicates are merged."))),
      h("div.stack",
        h("div.grid-2", field("IMAP server", f.imap_host), field("Folder", f.imap_folder)),
        field("Email address", f.imap_user), field("App password", f.imap_password, "Stored only on this computer."),
        field("Look back (days)", f.imap_days), h("div.row", importBtn), statusEl))));
    await load();
    watchImport();
    const t = setInterval(load, 15000);
    return () => { clearInterval(t); clearTimeout(it); };
  }

  // ================================================================ SOURCES
  async function pageSources() {
    subEl.textContent = "Where JobRadar looks for jobs";
    const settings = META.settings;
    const disabled = new Set(settings.disabled_sources || []);
    const grid = h("div.src-grid");
    const boardsBox = h("div");
    mount(content, h("div.sec-title", icon("database", "icon"), "Job sources"), grid,
      h("div.sec-title", icon("building", "icon"), "Company career boards", h("span.small.muted", { style: { fontWeight: 500 } }, "— grows automatically as JobRadar discovers companies")), boardsBox);
    const KEYS = { adzuna: [["adzuna_app_id", "App ID"], ["adzuna_app_key", "App Key"]], jooble: [["jooble_key", "API key"]], usajobs: [["usajobs_key", "API key"], ["usajobs_email", "Your email"]],
      careerjet: [["careerjet_affid", "Affiliate ID"]], reliefweb: [["reliefweb_appname", "Approved app name"]] };
    function drawSources() {
      mount(grid, META.sources.map((s) => {
        const on = !disabled.has(s.id);
        const keys = KEYS[s.id] || [];
        const inputs = keys.map(([k, l]) => [k, h("input.input", { value: settings[k] || "", placeholder: l })]);
        const testBtn = h("button.btn.btn-sm", { disabled: !s.ready, onclick: () => withBusy(testBtn, async () => {
          try { const r = await api.post("/api/sources/" + s.id + "/test", {}); toast(s.name + ": OK · " + r.count + " jobs in " + r.seconds + "s" + (r.sample ? " · e.g. “" + r.sample + "”" : ""), "ok", { duration: 5000 }); }
          catch (e) { toast(e.message, "error"); }
        }) }, icon("zap"), "Test");
        return h("div.card.src-card",
          h("div.top", h("div", { style: { flex: 1 } }, h("h3", s.name), h("div.cov", s.coverage)),
            s.ready ? h("label.switch.sm", h("input", { type: "checkbox", checked: on, onchange: async (e) => {
              e.target.checked ? disabled.delete(s.id) : disabled.add(s.id);
              const r = await api.put("/api/settings", { disabled_sources: [...disabled] });
              META.settings = r.settings;
              toast(s.name + (e.target.checked ? " enabled" : " disabled"), "info", { duration: 1400 });
            } }), h("span.track")) : h("span.badge.warn", s.needs.length ? "needs key" : "add a website")),
          h("p.note", s.about),
          inputs.length ? h("div.stack", { style: { gap: "8px" } }, inputs.map(([, el]) => el),
            h("div.row", h("button.btn.btn-sm.btn-primary", { onclick: async () => {
              const r = await api.put("/api/settings", Object.fromEntries(inputs.map(([k, el]) => [k, el.value])));
              META.settings = r.settings; META.sources = r.sources; toast("Saved", "ok"); drawSources();
            } }, "Save key"), s.homepage ? h("a.btn.btn-sm.btn-ghost", { href: s.homepage, target: "_blank", rel: "noopener" }, icon("external"), "Get a free key") : null)) : null,
          s.id === "sites" ? siteEditor() : null,
          h("div.row", testBtn, s.homepage && !inputs.length ? h("a.btn.btn-sm.btn-ghost", { href: s.homepage, target: "_blank", rel: "noopener" }, icon("external"), "Website") : null));
      }));
    }
    function siteEditor() {
      const ta = h("textarea.textarea", { placeholder: "https://company.com/careers\nhttps://another.com/jobs" }, (settings.crawl_sites || []).join("\n"));
      return h("div.stack", { style: { gap: "8px" } }, ta, h("button.btn.btn-sm.btn-primary", { onclick: async () => {
        const r = await api.put("/api/settings", { crawl_sites: ta.value });
        META.settings = r.settings; META.sources = r.sources; toast("Career sites saved", "ok"); drawSources();
      } }, "Save sites"));
    }
    async function drawBoards(filter = {}) {
      const res = await api.get("/api/boards?" + new URLSearchParams(filter));
      const add = h("textarea.textarea", { placeholder: "Paste careers page URLs (one per line) or provider:slug\nhttps://stripe.com/jobs\nhttps://jobs.lever.co/palantir\ngreenhouse:airbnb" });
      const addBtn = h("button.btn.btn-primary", { onclick: () => withBusy(addBtn, async () => {
        try { const r = await api.post("/api/boards", { input: add.value }); toast(r.added + " new board(s) · detected: " + (r.found.join(", ") || "nothing"), r.found.length ? "ok" : "info", { duration: 6000 }); add.value = ""; drawBoards(filter); }
        catch (e) { toast(e.message, "error"); }
      }) }, icon("plus"), "Add companies");
      const q = h("input.input", { placeholder: "Filter boards…", value: filter.q || "", onkeydown: (e) => { if (e.key === "Enter") drawBoards(Object.assign({}, filter, { q: e.target.value })); } });
      mount(boardsBox,
        h("div.kpis", { style: { gridTemplateColumns: "repeat(auto-fill,minmax(160px,1fr))" } },
          h("div.card.kpi", h("div.l", icon("building"), "Company boards"), h("div.v", nfmt(res.total))),
          res.summary.map((s) => h("div.card.kpi", h("div.l", s.provider), h("div.v", nfmt(s.n)), h("div.tiny.faint", nfmt(s.jobs || 0) + " jobs cached")))),
        h("div.grid-2", { style: { alignItems: "start" } },
          h("div.card.card-pad.stack", h("b", "Add companies"), h("p.note", "JobRadar detects the career system behind any careers page (Greenhouse, Lever, Ashby, Recruitee, SmartRecruiters, Personio). Other sites are added to the website crawler."), add, h("div.row", addBtn)),
          h("div.card",
            h("div.fbar", { style: { padding: "12px 12px 0" } }, q,
              sel([["", "All statuses"], ["ok", "OK"], ["empty", "Empty"], ["new", "Not fetched yet"], ["dead", "Dead"]], filter.status || "", (v) => drawBoards(Object.assign({}, filter, { status: v }))),
              h("button.btn.btn-sm", { onclick: async () => { await api.post("/api/boards/revive", {}); toast("Dead boards will be retried", "ok"); drawBoards(filter); } }, icon("refresh"), "Retry dead")),
            h("div.table-wrap", { style: { maxHeight: "420px", overflow: "auto" } }, h("table.dtable",
              h("thead", h("tr", ["Company", "System", "Jobs", "Status", ""].map((c) => h("th", c)))),
              h("tbody", res.boards.map((b) => h("tr",
                h("td", h("b", b.company || b.slug), h("div.tiny.faint", b.slug + (b.discovered_from && b.discovered_from !== "seed" ? " · found via " + b.discovered_from.slice(0, 30) : ""))),
                h("td.small", b.provider), h("td.num", nfmt(b.jobs_count)),
                h("td", h("span.badge." + ({ ok: "ok", dead: "danger", empty: "", new: "info" }[b.status] || ""), b.status), b.last_error ? h("div.tiny.faint", b.last_error.slice(0, 40)) : null),
                h("td", h("button.btn.btn-ghost.btn-sm.btn-icon", { "aria-label": "Remove", onclick: async () => { await api.del("/api/boards/" + b.id); drawBoards(filter); } }, icon("trash")))))))))));
    }
    drawSources();
    await drawBoards();
  }

  // ================================================================ MY PROFILE & AUTOFILL
  async function pageProfile() {
    subEl.textContent = "Your details and CVs for one-click application forms - stored only on this computer";
    let data = await api.get("/api/profile");
    const p = data.profile;
    const dirty = {};
    const saveBtn = h("button.btn.btn-primary", { onclick: () => withBusy(saveBtn, save) }, icon("check"), "Save profile");
    mount(actionsEl, h("a.btn", { href: "/autofill-test", target: "_blank" }, icon("external"), "Practice form"), saveBtn);
    const inp = (k, attrs = {}) => h("input.input", Object.assign({ value: p[k] || "", oninput: (e) => { dirty[k] = e.target.value; } }, attrs));
    const area = (k, rows, ph) => h("textarea.textarea", { rows, placeholder: ph || "", oninput: (e) => { dirty[k] = e.target.value; } }, p[k] || "");
    const yn = (k) => sel([["", "Don't answer automatically"], ["yes", "Yes"], ["no", "No"]], p[k] || "", (v) => { dirty[k] = v; });
    async function save() {
      try { data = await api.put("/api/profile", dirty); Object.keys(dirty).forEach((k) => delete dirty[k]); toast("Profile saved", "ok"); }
      catch (e) { toast(e.message, "error"); }
    }
    const coverTa = area("cover_letter", 9, "Dear hiring team at {company},\n\nI'm applying for the {job_title} position…\n\nBest regards,\n{my_name}");
    const insertPh = (ph) => { const s = coverTa.selectionStart || coverTa.value.length; coverTa.value = coverTa.value.slice(0, s) + ph + coverTa.value.slice(s); dirty.cover_letter = coverTa.value; coverTa.focus(); };

    const cvBox = h("div");
    const tokenBox = h("div");
    function drawCvs() {
      const file = h("input", { type: "file", accept: ".pdf,.doc,.docx,.odt,.rtf,.txt", hidden: true, onchange: (e) => upload(e.target.files[0]) });
      const drop = h("div.cv-drop", { onclick: () => file.click(),
        ondragover: (e) => { e.preventDefault(); drop.classList.add("over"); }, ondragleave: () => drop.classList.remove("over"),
        ondrop: (e) => { e.preventDefault(); drop.classList.remove("over"); upload(e.dataTransfer.files[0]); } },
        icon("upload", "icon"), h("b", "Add a CV version"), h("span.tiny.faint", "PDF recommended · Word, ODT, RTF, TXT · max 10 MB"), file);
      mount(cvBox, drop, data.cvs.length ? h("div.cv-list", data.cvs.map((c) => {
        const label = h("input.input.cv-label", { value: c.label, title: "Name this version (e.g. Developer CV, French CV)",
          onchange: async (e) => { data = await api.put("/api/profile/cv/" + c.id, { label: e.target.value }); toast("Renamed", "ok", { duration: 1200 }); } });
        return h("div.cv-item",
          h("label.cv-def", { title: "Use this CV by default" }, h("input", { type: "radio", name: "cvdef", checked: c.default,
            onchange: async () => { data = await api.put("/api/profile/cv/" + c.id, { default: true }); toast("Default CV set", "ok", { duration: 1200 }); drawCvs(); } })),
          h("div", { style: { flex: 1, minWidth: 0 } }, label, h("div.tiny.faint", c.name + " · " + Math.max(1, Math.round(c.size / 1024)) + " KB · " + TT.fmtDate(c.uploaded_at) + (c.default ? " · default" : ""))),
          h("a.btn.btn-sm.btn-ghost.btn-icon", { href: "/api/profile/cv/" + c.id, title: "Download" }, icon("download")),
          h("button.btn.btn-sm.btn-ghost.btn-icon", { title: "Delete", onclick: async () => {
            if (await confirmDialog({ title: "Delete " + c.label + "?", ok: "Delete", danger: true })) { data = await api.del("/api/profile/cv/" + c.id); drawCvs(); }
          } }, icon("trash")));
      })) : h("p.note", { style: { marginTop: "10px" } }, "No CV yet. Add your main CV, and more versions if you target different jobs."));
    }
    async function upload(f) {
      if (!f) return;
      const fd = new FormData();
      fd.append("file", f);
      try { data = await api("POST", "/api/profile/cv", fd); toast("CV added", "ok"); drawCvs(); }
      catch (e) { toast(e.message, "error"); }
    }
    function drawToken() {
      let shown = false;
      const code = h("code.token", "••••••••••••••••••••");
      mount(tokenBox,
        h("div.row", code,
          h("button.btn.btn-sm", { onclick: (e) => { shown = !shown; code.textContent = shown ? data.token : "••••••••••••••••••••"; e.currentTarget.textContent = shown ? "Hide" : "Show"; } }, "Show"),
          h("button.btn.btn-sm", { onclick: async () => { await TT.copyText(data.token); toast("Pairing code copied", "ok"); } }, icon("copy"), "Copy"),
          h("button.btn.btn-sm.btn-ghost", { title: "Make a new code (the old one stops working)", onclick: async () => {
            if (!await confirmDialog({ title: "Create a new pairing code?", message: "The extension will need the new code.", ok: "Create" })) return;
            data.token = (await api.post("/api/profile/token", {})).token; drawToken(); toast("New code created - paste it in the extension options", "ok");
          } }, icon("refresh"))));
    }

    mount(content, h("div.profile-grid",
      h("div.stack",
        h("div.card.card-pad.stack", h("h3", "Personal details"),
          h("div.grid-2", field("First name", inp("first_name", { autocomplete: "given-name" })), field("Last name", inp("last_name", { autocomplete: "family-name" }))),
          h("div.grid-2", field("Email", inp("email", { type: "email" })), field("Phone", inp("phone", { placeholder: "+216 20 123 456" }))),
          field("Address", inp("address")),
          h("div.grid-3", field("City", inp("city")), field("Postal code", inp("postal_code")), field("Country", inp("country", { placeholder: "Tunisia" })))),
        h("div.card.card-pad.stack", h("h3", "Links"),
          field("LinkedIn", inp("linkedin", { placeholder: "https://www.linkedin.com/in/…" })),
          h("div.grid-2", field("GitHub", inp("github")), field("Website / portfolio", inp("website")))),
        h("div.card.card-pad.stack", h("h3", "Work & education"),
          h("div.grid-2", field("Current / last job title", inp("current_title")), field("Current / last company", inp("current_company"))),
          h("div.grid-3", field("Years of experience", inp("years_experience", { placeholder: "3" })), field("Salary expectation", inp("salary_expectation", { placeholder: "e.g. 2 500 DT / month" })),
            field("Notice period / availability", inp("notice_period", { placeholder: "e.g. 1 month" }))),
          h("div.grid-2", field("School / university", inp("education_school")), field("Degree", inp("education_degree"))),
          field("Languages", inp("languages", { placeholder: "Arabic (native), French (fluent), English (B2)" }))),
        h("div.card.card-pad.stack", h("h3", "Common questions"),
          h("p.note", "Only filled when a form asks exactly this. Leave on “Don't answer automatically” if you prefer to answer yourself."),
          h("div.grid-3", field("Authorized to work?", yn("authorized_to_work")), field("Need visa sponsorship?", yn("requires_sponsorship")), field("Willing to relocate?", yn("willing_to_relocate")))),
        h("div.card.card-pad.stack", h("h3", "Summary & cover letter"),
          field("Short professional summary", area("summary", 4, "2-3 sentences about you")),
          h("div.field", h("label", "Cover letter template"), coverTa,
            h("div.row.wrap", h("span.hint", "Insert:"), ["{company}", "{job_title}", "{my_name}"].map((ph) => h("button.chip", { type: "button", onclick: () => insertPh(ph) }, ph)),
              h("span.hint", "- replaced automatically for each job."))))),
      h("div.stack",
        h("div.card.card-pad.stack", h("h3", icon("briefcase", "icon"), " CV versions"), cvBox),
        h("div.card.card-pad.stack", h("h3", icon("wand", "icon"), " Browser helper (autofill)"),
          h("p.note", "Fills application forms for you in Chrome or Edge - name, contacts, links, CV upload, common questions. You always check and click Submit yourself."),
          h("div.label", "Pairing code"), tokenBox,
          h("ol.steps",
            h("li", "Open ", h("code", "edge://extensions"), " or ", h("code", "chrome://extensions"), " and turn on ", h("b", "Developer mode"), "."),
            h("li", "Click ", h("b", "Load unpacked"), " and choose this folder:", h("div.row", { style: { marginTop: "6px" } }, h("code.path", data.extension_dir),
              h("button.btn.btn-sm", { onclick: async () => { await TT.copyText(data.extension_dir); toast("Folder path copied", "ok"); } }, icon("copy")))),
            h("li", "The extension options open: paste your pairing code and click ", h("b", "Save & test"), "."),
            h("li", "Pin the JobRadar icon. On any application page click it or press ", h("code", "Alt+Shift+F"), ".")),
          h("a.btn", { href: "/autofill-test", target: "_blank" }, icon("external"), "Try it on the practice form")))));
    drawCvs();
    drawToken();
    const beforeUnload = (e) => { if (Object.keys(dirty).length) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }

  // ================================================================ shared: match rings, KPIs, pager
  function mcls(s) { return s >= 75 ? "top" : s >= 60 ? "good" : s >= 40 ? "fair" : "low"; }
  function verdict(s) { return s >= 75 ? "Excellent match" : s >= 60 ? "Good match" : s >= 40 ? "Partial match" : "Weak match"; }
  function ring(score, size, title) {
    const el = h("div.ring." + mcls(score), { title: title || score + "% match with your CV" }, h("span", String(score)));
    el.style.setProperty("--p", score);
    if (size) { el.style.width = size + "px"; el.style.height = size + "px"; el.style.fontSize = Math.max(11, Math.round(size / 3.3)) + "px"; }
    return el;
  }
  function kpiBox(ic, label, v, cls) { return h("div.card.kpi", h("div.l", icon(ic), label), h("div.v" + (cls ? "." + cls : ""), typeof v === "number" ? nfmt(v) : v)); }
  function kpiLink(label, v, href, cls) { return h("a.card.kpi.kpi-link", { href }, h("div.l", label), h("div.v" + (cls ? ".m-" + cls : ""), nfmt(v))); }
  function pager(res, go) {
    if (!res.pages || res.pages <= 1) return null;
    return h("div.pager", h("span", "Page " + res.page + " of " + res.pages + " · " + nfmt(res.total)),
      h("div.row", h("button.btn.btn-sm", { disabled: res.page <= 1, onclick: () => go(res.page - 1) }, icon("chevronLeft")),
        h("button.btn.btn-sm", { disabled: res.page >= res.pages, onclick: () => go(res.page + 1) }, icon("chevronRight"))));
  }
  function kv(label, value) { return h("div.irow2", h("span.faint", label), h("div", value)); }
  const PARTS = { skills: "Skills", role: "Job family", experience: "Experience", languages: "Languages", education: "Education", location: "Location" };
  const EDU = { 5: "PhD / Doctorate", 4: "Master's", 3: "Bachelor's", 2: "Associate / BTS", 1: "High school" };
  const LVL = { 5: "native", 4: "fluent", 3: "good", 2: "intermediate", 1: "basic" };
  function bar(label, pct) {
    return h("div.mbar", h("span", label), h("i", h("b", { class: "m-" + mcls(pct), style: { width: Math.max(2, pct) + "%" } })), h("em", pct + "%"));
  }

  function matchCard(j) {
    const m = j.match || {};
    if (!m.parts || j.match_score == null) {
      return h("div.contact-card", h("h4", icon("sparkles", "icon"), "CV match"),
        h("p.note", "Add your CV in ", h("a", { href: "#/profile" }, "My profile"), " to see how well you fit this job and which skills are missing."));
    }
    const chips = (label, list, cls) => (list || []).length ? h("div.mrow", h("span.tiny.faint", label), h("div.chips", list.map((s) => h("span.skill" + cls, s)))) : null;
    return h("div.contact-card.match-card",
      h("div.row", ring(j.match_score, 58), h("div", { style: { flex: 1, minWidth: 0 } }, h("b", verdict(j.match_score)),
        h("div.tiny.muted", m.cv_label ? "Best CV for this job: " + m.cv_label : "Compared with your CV")),
        h("a.btn.btn-sm.btn-ghost", { href: "#/cvmatch" }, icon("sparkles"), "Improve")),
      h("div.mbars", Object.keys(PARTS).filter((k) => m.parts[k] != null).map((k) => bar(PARTS[k], m.parts[k]))),
      chips("You have", m.have, ".good"), chips("Close (related skill)", m.partial, ".part"),
      chips("Missing - required", m.missing, ".miss"), chips("Nice to have", m.missing_nice, ""),
      (m.notes || []).length ? h("div.row.wrap", { style: { marginTop: "8px" } }, m.notes.map((n) => h("span.badge.warn", n))) : null);
  }

  // ================================================================ CV CHECK & MATCH
  async function pageCv(params) {
    subEl.textContent = "How ATS robots read your CV - and how well it fits every job in your database";
    let prof = await api.get("/api/profile");
    if (!prof.cvs.length) {
      mount(content, h("div.card", empty("note", "Add your CV first", "Upload your CV in My profile. JobRadar then checks it like an ATS robot and scores every job against it.",
        h("a.btn.btn-primary", { href: "#/profile" }, icon("upload"), "Go to My profile"))));
      return;
    }
    let cvId = params.get("cv") || (prof.cvs.find((c) => c.default) || prof.cvs[0]).id;
    const targets = h("input.input", { value: prof.profile.target_titles || "", placeholder: "e.g. comptable, accountant, auditor" });
    const extra = h("input.input", { value: prof.profile.skills_extra || "", placeholder: "e.g. Odoo, Power BI" });
    const cvSel = sel(prof.cvs.map((c) => [c.id, c.label + (c.default ? " (default)" : "")]), cvId, (v) => { cvId = v; run(false); });
    async function saveTargets() {
      if (targets.value !== (prof.profile.target_titles || "") || extra.value !== (prof.profile.skills_extra || "")) {
        prof = Object.assign(prof, await api.put("/api/profile", { target_titles: targets.value, skills_extra: extra.value }));
      }
    }
    const checkBtn = h("button.btn.btn-primary", { onclick: () => withBusy(checkBtn, async () => { await saveTargets(); await run(true); drawMatch(); }) }, icon("refresh"), "Check my CV");
    const resBox = h("div");
    const matchBox = h("div");
    let mt = null;
    mount(content,
      h("div.card.card-pad.stack", { style: { marginBottom: "16px" } },
        h("div.grid-3", field("CV version", cvSel), field("Target job titles", targets, "What you apply for - commas between titles, any language."),
          field("Extra skills", extra, "Skills you have that your CV doesn't mention.")),
        h("div.row", checkBtn, h("span.tiny.faint", "Your CV is analysed on this computer only - it's never uploaded anywhere."))),
      resBox, matchBox);

    function checkRow(c) {
      const ic = { ok: "check", fail: "x", warn: "alert", info: "info" }[c.status];
      return h("div.chk." + c.status, h("span.ci", icon(ic)),
        h("div", { style: { minWidth: 0 } }, h("b", c.title), c.detail ? h("div.small.muted", c.detail) : null, c.fix ? h("div.small.fix", "→ " + c.fix) : null),
        c.max ? h("span.pts", Math.round(c.points) + "/" + c.max) : null);
    }

    async function run(force) {
      mount(resBox, spin());
      let r;
      try { r = (await api.get("/api/cv/check?" + new URLSearchParams({ cv: cvId, force: force ? 1 : "" }))).result; }
      catch (e) { mount(resBox, h("div.card", empty("alert", "Couldn't read this CV", e.message))); return; }
      const order = { fail: 0, warn: 1, info: 2, ok: 3 };
      const checks = r.checks.slice().sort((a, b) => order[a.status] - order[b.status]);
      const bad = checks.filter((c) => c.status !== "ok");
      const good = checks.filter((c) => c.status === "ok");
      const p = r.profile;
      mount(resBox, h("div.cv-grid",
        h("div.stack",
          h("div.card.card-pad.cv-score",
            h("div.row", { style: { gap: "18px" } }, ring(r.score, 104, "ATS score"),
              h("div", h("div.grade.m-" + mcls(r.score), r.grade), h("div.small.muted", "ATS score · " + r.cv.label),
                h("div.tiny.faint", (r.facts.format || "").toUpperCase() + " · " + r.facts.pages + " page(s) · checked " + TT.timeAgo(r.checked_at)))),
            h("div.mbars", Object.values(r.categories).filter((c) => c.pct != null).map((c) => bar(c.name, c.pct)))),
          h("div.card.card-pad", h("h3", { style: { marginBottom: "10px" } }, bad.length ? "To improve (" + bad.length + ")" : "Nothing to fix"),
            bad.length ? h("div.checks", bad.map(checkRow)) : h("p.note", "Great CV - robots and recruiters can read everything."),
            good.length ? h("details.ok-list", h("summary.small.muted", "✓ " + good.length + " checks passed"), h("div.checks", good.map(checkRow))) : null),
          h("div.card.card-pad",
            h("details.ats-view", h("summary", icon("eye", "icon"), " What the robot reads (plain text, in file order)"), h("pre.ats-text", r.ats_text || "(no text)")),
            h("p.tiny.faint", { style: { marginTop: "8px" } }, "Most applicant-tracking systems extract exactly this. If sections are mixed up or missing here, the recruiter's software sees them that way too."))),
        h("div.stack",
          h("div.card.card-pad.stack", h("h3", icon("briefcase", "icon"), " What JobRadar understood"),
            h("div", kv("Experience", p.years ? p.years + " years (from your dates)" : "No dates found"), kv("Education", EDU[p.education] || "-"),
              kv("Languages", Object.entries(p.languages || {}).map(([k, v]) => k + " (" + LVL[v] + ")").join(", ") || "-"),
              kv("Job family", (p.families || []).join(", ") || "-"), kv("CV language", ({ fr: "French", en: "English", de: "German", es: "Spanish", ar: "Arabic" })[p.language] || "-")),
            h("div", h("div.label", { style: { marginBottom: "6px" } }, "Skills found (" + p.skills.length + ")"),
              p.skills.length ? h("div.chips", p.skills.map((s) => h("span.skill", s))) : h("p.note", "No skills recognised - add a Skills section."))),
          h("div.card.card-pad.stack", h("h3", icon("trendUp", "icon"), " What employers ask for"),
            r.market_jobs >= 10 ? [h("p.note", "Most requested skills in " + r.market_jobs + " jobs for “" + r.targets + "” - ✓ on your CV, ≈ close, ✗ missing:"),
              h("div.mkt", r.market.map((m) => h("div.mkt-row", h("span.skill" + (m.have ? ".good" : m.partial ? ".part" : ".miss"), (m.have ? "✓ " : m.partial ? "≈ " : "✗ ") + m.skill),
                h("i", h("b", { style: { width: m.share + "%" } })), h("em", m.share + "%"))))] :
              h("p.note", r.targets ? "Only " + r.market_jobs + " jobs for “" + r.targets + "” in your database. Run a search for it, then check again."
                : "Set your target job titles above to compare your CV with what employers ask.")))));
    }

    async function drawMatch() {
      clearTimeout(mt);
      let st, gap;
      try { [st, gap] = await Promise.all([api.get("/api/match/status"), api.get("/api/match/gap")]); }
      catch (_) { return; }
      const d = st.dist;
      const alertSel = sel([[0, "Off"], [60, "60%+"], [70, "70%+"], [75, "75%+"], [85, "85%+"]], st.alert_min,
        async (v) => { const x = await api.put("/api/settings", { match_alert_min: +v }); META.settings = x.settings; toast("Saved", "ok"); });
      alertSel.style.width = "auto";
      const g = gap.gap;
      mount(matchBox,
        h("div.sec-title", icon("sparkles", "icon"), "Your matches",
          st.state.running ? h("span.badge.info", h("div.spinner", { style: { width: "12px", height: "12px" } }), " Scoring " + st.state.done + "/" + st.state.total) : null),
        h("div.kpis", kpiLink("Top matches · 75%+", d.top, "#/jobs?sort=match&min_match=75", "top"), kpiLink("Good · 60-74%", d.good, "#/jobs?sort=match&min_match=60", "good"),
          kpiLink("Partial · 40-59%", d.fair, "#/jobs?sort=match&min_match=40", "fair"), kpiLink("Jobs scored", d.scored, "#/jobs?sort=match", "")),
        h("div.grid-2", { style: { alignItems: "start" } },
          h("div.card.card-pad.stack", h("h3", icon("zap", "icon"), " Skills to learn next"),
            h("p.note", "Required most often in jobs of your field that your CV doesn't show" + (g.jobs ? " (" + nfmt(g.jobs) + " jobs)." : ".") + " “Unlocks” = good jobs you'd reach with that one skill."),
            g.skills.length ? h("div.table-wrap", h("table.dtable", h("thead", h("tr", ["Skill", "Asked in", "Unlocks", ""].map((x) => h("th", x)))),
              h("tbody", g.skills.map((s) => h("tr", h("td", h("b", s.skill)), h("td.small", s.jobs + " jobs · " + s.share + "%"),
                h("td", s.unlocks ? h("span.badge.ok", "+" + s.unlocks) : h("span.faint", "-")),
                h("td", h("button.btn.btn-sm.btn-ghost", { title: "I have this skill - add it to my profile", onclick: () => addSkill(s.skill) }, icon("plus"), "I have it"))))))) :
              h("p.note", st.ready ? "No gaps yet - JobRadar needs more jobs in your field (run a search)." : "Add a CV to see your skill gaps.")),
          h("div.card.card-pad.stack", h("h3", icon("bell", "icon"), " Top-match alerts"),
            h("p.note", "Get a notification when new jobs match your CV at least this much - checked after every search and every night."),
            h("div.row", alertSel, h("span.spacer"),
              h("button.btn.btn-sm.btn-ghost", { onclick: async () => { await api.post("/api/match/rescore", {}); toast("Re-scoring all jobs…", "info"); setTimeout(drawMatch, 1200); } }, icon("refresh"), "Re-score all jobs")),
            st.me ? h("div.tiny.faint", "Matching with " + st.me.skills.length + " skills · " + st.me.years + " years · " + st.me.cvs.length + " CV version(s)" + (st.me.targets ? " · target: " + st.me.targets : "")) : null)));
      if (st.state.running) mt = setTimeout(drawMatch, 2500);
    }
    async function addSkill(s) {
      extra.value = (extra.value.trim() ? extra.value.trim().replace(/,$/, "") + ", " : "") + s;
      await saveTargets();
      toast("Added " + s + " - your matches are being updated", "ok");
      setTimeout(drawMatch, 1500);
    }
    run(false);
    drawMatch();
    return () => clearTimeout(mt);
  }

  // ================================================================ HIRING SIGNALS
  async function pageSignals(params) {
    subEl.textContent = "Companies about to hire - spotted from changes on their career pages, often before the big job boards";
    const st = { country: (params.get("country") || "").toUpperCase(), field: false, contact: false, watched: false, q: params.get("company") || "", page: 1 };
    const sumBox = h("div");
    const listBox = h("div");
    const combo = countryCombo(st.country, (cc) => { st.country = cc; st.page = 1; load(); }, { placeholder: "🌍 Any country" });
    combo.style.minWidth = "200px";
    const tg = (k, ic, label) => { const b = h("button.tgl", { onclick: () => { st[k] = !st[k]; b.classList.toggle("on", st[k]); st.page = 1; load(); } }, icon(ic), label); return b; };
    mount(content, sumBox,
      h("div.fbar", h("div.search-input", icon("search"), h("input.input", { placeholder: "Search companies…", value: st.q, oninput: debounce((e) => { st.q = e.target.value; st.page = 1; load(); }, 250) })),
        combo, tg("field", "sparkles", "In my field"), tg("contact", "mail", "Has contact"), tg("watched", "star", "Watched")),
      listBox);

    function sigCard(c) {
      const s = c.signal || { reasons: [], titles: [] };
      const watchBtn = h("button.btn.btn-sm.btn-ghost.btn-icon.star" + (c.watch ? ".on" : ""), {
        title: c.watch ? "Stop watching" : "Watch - notify me as soon as they post a job",
        onclick: async () => {
          c.watch = c.watch ? 0 : 1;
          await api.post("/api/companies/" + encodeURIComponent(c.key) + "/watch", { watch: !!c.watch });
          watchBtn.classList.toggle("on", !!c.watch);
          toast(c.watch ? "Watching " + c.name + " - you'll be notified of new jobs" : "Stopped watching " + c.name, "ok");
        } }, icon("star"));
      const findBtn = h("button.btn.btn-sm", { onclick: () => withBusy(findBtn, async () => {
        try { await api.post("/api/companies/" + encodeURIComponent(c.key) + "/enrich", {}); toast("Contacts updated for " + c.name, "ok"); load(); }
        catch (e) { toast(e.message, "error"); }
      }) }, icon("wand"), c.enriched_at ? "Contacts again" : "Find contacts");
      const draftBtn = h("button.btn.btn-sm.btn-primary", { onclick: () => withBusy(draftBtn, async () => {
        const r = await api.post("/api/outreach/drafts", { items: [{ key: c.key }] });
        if (r.created) toast("Draft ready - review it before it's sent", "ok", { action: { label: "Review", run: () => { location.hash = "#/outreach?tab=queue"; } } });
        else toast(c.contacted ? "You already contacted " + c.name : "No email found yet - click Find contacts first", "info", { duration: 5000 });
      }) }, icon("send"), "Apply spontaneously");
      return h("div.card.sig-card",
        h("div.sig-top", logo(c.name, 42),
          h("div", { style: { flex: 1, minWidth: 0 } }, h("a.strong", { href: "#", onclick: (e) => { e.preventDefault(); openCompany(c.key); } }, c.name),
            h("div.tiny.muted", [c.domain, (c.countries || []).slice(0, 6).map(flagOf).join(" "), c.jobs ? c.jobs + " jobs in JobRadar" : ""].filter(Boolean).join(" · "))),
          h("div.heat", { title: "Hiring heat (0-100)" }, h("div.heat-bar", h("i", { style: { width: c.heat + "%" } })), h("b", String(c.heat))), watchBtn),
        s.reasons.length ? h("div.sig-reasons", s.reasons.map(([k, t]) => h("span.sigr." + k, t))) : h("div.tiny.faint", "Watching - no new signal yet"),
        (s.titles || []).length ? h("div.tiny.faint.sig-titles", "Recent: " + s.titles.slice(0, 4).join(" · ")) : null,
        h("div.row.wrap",
          c.best_match != null ? h("span.badge." + (c.best_match >= 60 ? "ok" : c.best_match >= 40 ? "warn" : ""), "Best match " + c.best_match + "%") : null,
          c.hr ? h("span.badge.ok", c.hr + " HR contact" + (c.hr > 1 ? "s" : "")) : c.people ? h("span.badge", c.people + " people") : null,
          (c.emails || []).length ? h("span.badge.info", icon("mail"), "email") : null,
          c.contacted ? h("span.badge.accent", "Contacted " + TT.timeAgo(c.contacted)) : null,
          h("span.spacer"),
          c.jobs ? h("a.btn.btn-sm.btn-ghost", { href: "#/jobs?company=" + encodeURIComponent(c.key) }, icon("briefcase"), "Jobs") : null, findBtn, draftBtn));
    }

    async function load() {
      mount(listBox, spin());
      let r;
      try { r = await api.get("/api/signals?" + new URLSearchParams({ country: st.country, field: st.field ? 1 : "", contact: st.contact ? 1 : "", watched: st.watched ? 1 : "", q: st.q, page: st.page })); }
      catch (e) { mount(listBox, h("div.card", empty("alert", "Couldn't load signals", e.message))); return; }
      const s = r.summary;
      mount(sumBox,
        h("div.kpis", kpiBox("flame", "Heating up (40+)", s.hot), kpiBox("trendUp", "Warming up", s.warm), kpiBox("globe", "Entering a new country", s.new_country),
          kpiBox("star", "Watched", s.watched), kpiBox("building", "Career pages tracked", s.tracked_boards)),
        !s.snapshots ? h("div.alert-box", { style: { marginBottom: "12px" } }, icon("info"),
          h("div", "Signals get sharper every day: JobRadar compares each company's career page with previous days. Run searches, or let the ",
            h("a", { href: "#/night" }, "night scan"), " refresh every company each night. Until then, signals come from job-board posting dates."))
          : h("div.tiny.faint", { style: { margin: "-6px 0 12px" } }, "Tracking " + nfmt(s.tracked_boards) + " company career pages since " + TT.fmtDate(s.tracking_since) + " · " + nfmt(s.snapshots) + " snapshots"));
      if (!r.companies.length) {
        mount(listBox, h("div.card", empty("flame", st.watched ? "No watched companies" : "No hiring signals match",
          st.watched ? "Click the ☆ on any company to watch it - you'll be notified the moment it posts a job." : "Try another filter, or run more searches.")));
        return;
      }
      mount(listBox, h("div.sig-list", r.companies.map(sigCard)), pager(r, (p) => { st.page = p; load(); window.scrollTo(0, 0); }));
    }
    await load();
  }

  // ================================================================ SPONTANEOUS APPLICATIONS
  async function pageOutreach(params) {
    subEl.textContent = "Reach companies before they post a job - personal emails from your own mailbox, with your best CV";
    let tab = params.get("tab") || "find";
    const TABS = [["find", "Find companies", "search"], ["queue", "Review & send", "send"], ["sent", "Sent & replies", "inbox"], ["settings", "Settings", "settings"]];
    const tabBar = h("div.tabs");
    const statusBox = h("div");
    const box = h("div");
    let counts = {};
    let status = null;
    function go(t) { tab = t; history.replaceState(null, "", "#/outreach?tab=" + t); drawTabs(); show(); }
    function drawTabs() {
      mount(tabBar, TABS.map(([id, label, ic]) => h("button" + (tab === id ? ".on" : ""), { onclick: () => go(id) }, icon(ic), label,
        id === "queue" && (counts.draft || counts.failed) ? h("span.count", String((counts.draft || 0) + (counts.failed || 0))) :
          id === "sent" && counts.replied ? h("span.count", String(counts.replied)) : null)));
    }
    async function refreshStatus() {
      let s, l;
      try { [s, l] = await Promise.all([api.get("/api/outreach/status"), api.get("/api/outreach?status=active")]); }
      catch (_) { return; }
      status = s;
      counts = l.counts || {};
      drawTabs();
      const st = s.stats;
      const snd = s.sender;
      mount(statusBox,
        h("div.kpis", kpiBox("send", "Sent · 30 days", st.sent), kpiBox("inbox", "Replies", st.replied), kpiBox("star", "Interviews", st.interviews),
          kpiBox("chart", "Reply rate", st.reply_rate + "%"), kpiBox("edit", "Waiting for your OK", counts.draft || 0)),
        h("div.alert-box" + (["error", "setup", "paused"].includes(snd.state) || s.config.paused ? ".warn" : ""), { style: { marginBottom: "14px", alignItems: "center" } },
          icon(snd.state === "sending" ? "send" : s.config.paused ? "stop" : "clock"),
          h("div", h("b", "Sender · "), s.config.paused ? "Paused" : (snd.message || "Idle"), h("span.muted", " · sent today " + s.sent_today + "/" + s.config.daily)),
          h("span.spacer"),
          s.config.paused ? h("button.btn.btn-sm.btn-primary", { onclick: async () => { await api.put("/api/settings", { outreach_paused: 0 }); await api.post("/api/outreach/wake", {}); toast("Sending resumed", "ok"); refreshStatus(); } }, icon("play"), "Resume sending")
            : h("button.btn.btn-sm", { onclick: async () => { await api.put("/api/settings", { outreach_paused: 1 }); toast("Sending paused", "info"); refreshStatus(); } }, icon("stop"), "Pause")));
    }

    // ---- find companies
    function tabFind() {
      const f = { src: LS.get("jr_out_src", "jobradar"), country: LS.get("jr_out_country", ""), city: "", q: "", field: false, general: true };
      const selected = new Set();
      const listBox = h("div");
      const actBar = h("div");
      const srcSeg = h("div.seg", [["jobradar", "JobRadar companies"], ["leadfinder", "Lead Finder"]].map(([v, l]) => h("button" + (f.src === v ? ".on" : ""), {
        onclick: (e) => { f.src = v; LS.set("jr_out_src", v); $$("button", srcSeg).forEach((b) => b.classList.toggle("on", b === e.currentTarget)); selected.clear(); load(); } }, l)));
      const combo = countryCombo(f.country, (cc) => { f.country = cc; LS.set("jr_out_country", cc); selected.clear(); load(); }, { placeholder: "🌍 Any country" });
      combo.style.minWidth = "190px";
      const city = h("input.input", { placeholder: "City", style: { width: "130px" }, oninput: debounce((e) => { f.city = e.target.value; load(); }, 350) });
      const kw = h("input.input", { placeholder: "Sector or name (e.g. audit, comptable)", style: { width: "240px" }, oninput: debounce((e) => { f.q = e.target.value; load(); }, 350) });
      const fieldTg = h("button.tgl", { title: "Companies hiring in your field or whose jobs match your CV", onclick: () => { f.field = !f.field; fieldTg.classList.toggle("on", f.field); load(); } }, icon("sparkles"), "In my field");
      const genTg = h("button.tgl.on", { title: "Also companies that only publish a general address (contact@, info@)", onclick: () => { f.general = !f.general; genTg.classList.toggle("on", f.general); load(); } }, icon("mail"), "contact@ / info@ too");
      const langSel = sel([["", "Language: automatic"], ["fr", "Français"], ["en", "English"]], "", () => {}, "sm");
      langSel.style.width = "auto";
      function drawAct() {
        mount(actBar, selected.size ? h("div.bulkbar", h("b", selected.size + " selected"), h("span.spacer"), langSel,
          h("button.btn.btn-sm", { onclick: (e) => withBusy(e.currentTarget, create) }, icon("edit"), "Create " + selected.size + " draft" + (selected.size > 1 ? "s" : "")),
          h("button.btn.btn-sm", { onclick: () => { selected.clear(); $$("input[type=checkbox]", listBox).forEach((x) => { x.checked = false; }); drawAct(); } }, "Clear")) : null);
      }
      async function create() {
        const ids = [...selected];
        const r = f.src === "leadfinder" ? await api.post("/api/outreach/leadfinder/import", { ids, draft: true, lang: langSel.value })
          : await api.post("/api/outreach/drafts", { items: ids.map((k) => ({ key: k })), lang: langSel.value });
        const n = r.created != null ? r.created : r.drafts;
        if (n) toast(n + " draft" + (n !== 1 ? "s" : "") + " created - check them, then approve", "ok", { action: { label: "Review", run: () => go("queue") } });
        else toast("No drafts created - those companies were already contacted or have no usable email", "info", { duration: 5000 });
        selected.clear();
        load();
        refreshStatus();
      }
      const cbx = (id) => h("input", { type: "checkbox", checked: selected.has(id), onclick: (e) => e.stopPropagation(), onchange: (e) => { e.target.checked ? selected.add(id) : selected.delete(id); drawAct(); } });
      const selAll = (ids) => h("input", { type: "checkbox", title: "Select all", onchange: (e) => {
        ids.forEach((id) => (e.target.checked ? selected.add(id) : selected.delete(id)));
        $$("tbody input[type=checkbox]", listBox).forEach((x) => { x.checked = e.target.checked; });
        drawAct();
      } });
      async function load() {
        mount(listBox, spin());
        drawAct();
        try {
          if (f.src === "leadfinder") {
            const r = await api.get("/api/outreach/leadfinder?" + new URLSearchParams({ country: f.country, city: f.city, q: f.q }));
            if (!r.found) return mount(listBox, h("div.card", empty("database", "Lead Finder not found", "Run Lead Finder to collect local companies by sector - they appear here to apply spontaneously.")));
            if (r.error) return mount(listBox, h("div.card", empty("alert", "Couldn't read Lead Finder", r.error)));
            if (!r.leads.length) return mount(listBox, h("div.card", empty("search", "No Lead Finder companies match", "In Lead Finder, search your sector (e.g. accounting firms in Tunis) - companies with an email appear here.")));
            const fresh = r.leads.filter((l) => !l.contacted);
            mount(listBox, h("div.card", h("div.table-wrap", h("table.dtable",
              h("thead", h("tr", h("th", selAll(fresh.map((l) => l.id))), ["Company", "Sector", "City", "Email", ""].map((x) => h("th", x)))),
              h("tbody", r.leads.map((l) => h("tr" + (l.contacted ? ".dim" : ""), h("td", l.contacted ? null : cbx(l.id)),
                h("td", h("b", l.name), h("div.tiny.faint", l.domain || "")), h("td.small", l.category || l.niche || ""), h("td.small", l.city || ""),
                h("td.small", l.email), h("td", l.contacted ? h("span.badge.accent", "contacted") : l.in_jobradar ? h("span.badge", "in JobRadar") : null))))))),
              h("p.tiny.faint", { style: { marginTop: "8px" } }, nfmt(r.total) + " companies with an email in Lead Finder" + (r.total > r.leads.length ? " · showing the best " + r.leads.length : "")));
          } else {
            const r = await api.get("/api/outreach/candidates?" + new URLSearchParams({ country: f.country, city: f.city, q: f.q, field: f.field ? 1 : "", general: f.general ? 1 : 0 }));
            if (!r.companies.length) {
              return mount(listBox, h("div.card", empty("building", "No companies with a contact yet",
                "Find recruiters and emails first (Companies → “Find recruiters for all new companies”), or import companies from Lead Finder.",
                h("a.btn.btn-primary", { href: "#/companies" }, icon("wand"), "Find contacts"))));
            }
            mount(listBox, h("div.card", h("div.table-wrap", h("table.dtable",
              h("thead", h("tr", h("th", selAll(r.companies.map((c) => c.key))), ["Company", "Who you'd write to", "Why this company", ""].map((x) => h("th", x)))),
              h("tbody", r.companies.map((c) => h("tr", h("td", cbx(c.key)),
                h("td", h("div.row", logo(c.name, 32), h("div", { style: { minWidth: 0 } }, h("a.strong", { href: "#", onclick: (e) => { e.preventDefault(); openCompany(c.key); } }, c.name),
                  h("div.tiny.faint", [c.domain, c.jobs ? c.jobs + " jobs" : "", c.source === "leadfinder" ? "from Lead Finder" : ""].filter(Boolean).join(" · "))))),
                h("td.small", h("span.badge" + (["HR person", "Recruiting inbox"].includes(c.contact.quality) ? ".ok" : ""), c.contact.quality),
                  h("div", { style: { marginTop: "3px" } }, c.contact.name ? c.contact.name + " · " : "", c.contact.email)),
                h("td", c.reasons.length ? h("div.sig-reasons", c.reasons.map((t) => h("span.sigr", t))) : h("span.faint.tiny", "-")),
                h("td", c.heat ? h("span.badge.warn", { title: "Hiring heat" }, icon("flame"), String(c.heat)) : null))))))),
              h("p.tiny.faint", { style: { marginTop: "8px" } }, nfmt(r.total) + " companies ready for a spontaneous application · companies you already wrote to are hidden"));
          }
        } catch (e) { mount(listBox, h("div.card", empty("alert", "Couldn't load companies", e.message))); }
        drawAct();
      }
      mount(box,
        h("p.note", { style: { marginBottom: "12px" } }, "Companies with a real contact that you haven't written to yet - ranked by hiring signals, how well their jobs match your CV and the contact (a named HR person first). Nothing is sent until you approve each email."),
        h("div.fbar", srcSeg, combo, city, kw, fieldTg, genTg), actBar, listBox);
      load();
    }

    // ---- review & send
    async function tabQueue() {
      mount(box, spin());
      let r, prof;
      try { [r, prof] = await Promise.all([api.get("/api/outreach?status=active"), api.get("/api/profile")]); }
      catch (e) { mount(box, h("div.card", empty("alert", "Couldn't load drafts", e.message))); return; }
      const cvOpts = prof.cvs.map((c) => [c.id, c.label]);
      if (!r.items.length) {
        mount(box, h("div.card", empty("send", "Nothing to review", "Pick companies in “Find companies” to create personal drafts.", h("button.btn.btn-primary", { onclick: () => go("find") }, icon("search"), "Find companies"))));
        return;
      }
      const drafts = r.items.filter((i) => i.status === "draft");
      const approveAll = h("button.btn.btn-primary", { onclick: async () => {
        if (!await confirmDialog({ title: "Approve " + drafts.length + " email" + (drafts.length > 1 ? "s" : "") + "?", message: "They'll be sent from your mailbox one by one, within your daily limit and sending hours. You can pause anytime.", ok: "Approve all" })) return;
        const x = await api.post("/api/outreach/bulk", { ids: drafts.map((d) => d.id), action: "approve" });
        toast(x.count + " approved", "ok");
        tabQueue();
        refreshStatus();
      } }, icon("check"), "Approve all " + drafts.length);
      const mbBtn = status && status.mailblaster && drafts.length ? h("button.btn", { title: "Send them as a MailBlaster campaign instead", onclick: async () => {
        const x = await api.post("/api/outreach/mailblaster", { ids: drafts.map((d) => d.id) });
        toast("MailBlaster group “" + x.group + "”: " + x.added + " added, " + x.updated + " updated", "ok", { duration: 6000 });
      } }, icon("download"), "Export to MailBlaster") : null;
      mount(box,
        h("div.row.wrap", { style: { marginBottom: "12px" } },
          h("span.muted.small", drafts.length + " draft(s) · " + r.items.filter((i) => i.status === "queued").length + " approved, waiting · " + r.items.filter((i) => i.status === "failed").length + " failed"),
          h("span.spacer"), mbBtn, drafts.length ? approveAll : null),
        h("div.drafts", r.items.map((it) => draftCard(it, cvOpts))));
    }
    function draftCard(it, cvOpts) {
      const editable = it.status === "draft" || it.status === "failed";
      const save = debounce(async (patch) => { try { await api.put("/api/outreach/" + it.id, patch); } catch (e) { toast(e.message, "error"); } }, 600);
      const to = h("input.input", { value: it.to_email, disabled: !editable, onchange: (e) => save({ to_email: e.target.value }) });
      const subj = h("input.input", { value: it.subject, disabled: !editable, oninput: (e) => save({ subject: e.target.value }) });
      const body = h("textarea.textarea", { rows: 11, disabled: !editable, oninput: (e) => save({ body: e.target.value }) }, it.body);
      const cv = sel([["", "No attachment"]].concat(cvOpts), it.cv_id, (v) => save({ cv_id: v }), "sm");
      cv.disabled = !editable || it.kind === "followup";
      cv.style.width = "auto";
      const badge = { draft: ["Draft - needs your OK", "warn"], queued: ["Approved - waiting for sending hours", "info"], failed: ["Failed", "danger"] }[it.status] || [it.status, ""];
      return h("div.card.card-pad.draft",
        h("div.row", logo(it.company || it.to_email, 36), h("div", { style: { flex: 1, minWidth: 0 } }, h("b", it.company || it.to_email),
          h("div.tiny.muted", [it.kind === "followup" ? "Follow-up" : "", it.to_name ? it.to_name + (it.to_title ? " (" + it.to_title + ")" : "") : "", it.reason, (it.lang || "").toUpperCase()].filter(Boolean).join(" · "))),
          h("span.badge." + badge[1], badge[0])),
        it.error ? h("div.alert-box.warn", { style: { margin: "10px 0" } }, icon("alert"), h("div", it.error)) : null,
        h("div.grid-2", { style: { margin: "10px 0" } }, field("To", to), field("Subject", subj)), body,
        h("div.row.wrap", { style: { marginTop: "10px" } }, h("span.small.muted", it.kind === "followup" ? "Follow-ups are sent in the same thread, without attachment." : "CV attached:"), it.kind === "followup" ? null : cv, h("span.spacer"),
          h("button.btn.btn-sm.btn-ghost", { onclick: () => preview(it.id) }, icon("eye"), "Preview"),
          editable ? h("button.btn.btn-sm.btn-ghost", { onclick: async () => { await api.del("/api/outreach/" + it.id); toast("Deleted", "info"); tabQueue(); refreshStatus(); } }, icon("trash"), "Delete") : null,
          it.status === "queued" ? h("button.btn.btn-sm", { onclick: async () => { await api.post("/api/outreach/bulk", { ids: [it.id], action: "draft" }); tabQueue(); refreshStatus(); } }, icon("undo"), "Back to draft") : null,
          editable ? h("button.btn.btn-sm.btn-primary", { onclick: (e) => withBusy(e.currentTarget, async () => {
            try {
              await api.put("/api/outreach/" + it.id, { to_email: to.value, subject: subj.value, body: body.value, status: "queued" });
              toast("Approved - it goes out within your sending hours", "ok");
              tabQueue();
              refreshStatus();
            } catch (err) { toast(err.message, "error"); }
          }) }, icon("check"), "Approve") : null));
    }
    async function preview(id) {
      try {
        const r = await api.get("/api/outreach/preview/" + id);
        modal({ title: "Email preview", size: "wide", body: h("div.stack",
          h("div.small", h("b", "From: "), r.headers.From), h("div.small", h("b", "To: "), r.headers.To), h("div.small", h("b", "Subject: "), r.headers.Subject),
          h("pre.mail-body", r.body),
          r.attachments.length ? h("div.small", icon("note", "icon"), " " + r.attachments.map((a) => a.name + " (" + Math.max(1, Math.round(a.size / 1024)) + " KB)").join(", ")) : h("div.small.faint", "No attachment")) });
      } catch (e) { toast(e.message, "error"); }
    }

    // ---- sent & replies
    async function tabSent(page) {
      mount(box, spin());
      const r = await api.get("/api/outreach?status=done&page=" + (page || 1));
      const checkBtn = h("button.btn.btn-sm", { onclick: () => withBusy(checkBtn, async () => {
        try { const x = await api.post("/api/outreach/check-replies", {}); toast(x.found ? x.found + " new repl" + (x.found > 1 ? "ies" : "y") : "No new replies", "ok"); tabSent(1); refreshStatus(); }
        catch (e) { toast(e.message, "error"); }
      }) }, icon("inbox"), "Check replies now");
      const KIND = { interview: ["Interview / positive", "ok"], rejection: ["Not this time", ""], auto: ["Auto-reply", "info"], other: ["Replied", "accent"], bounce: ["Bounced", "danger"] };
      mount(box,
        h("div.row", { style: { marginBottom: "12px" } }, h("span.muted.small", nfmt(r.total) + " sent · replies are detected in your inbox every 15 minutes (read-only)"), h("span.spacer"), checkBtn),
        !r.items.length ? h("div.card", empty("inbox", "Nothing sent yet", "Approved emails appear here once they're sent.")) :
          h("div.card", h("div.table-wrap", h("table.dtable",
            h("thead", h("tr", ["Company", "To", "Sent", "Status", "Their answer"].map((x) => h("th", x)))),
            h("tbody", r.items.map((i) => {
              const k = i.status === "bounced" ? KIND.bounce : i.status === "replied" ? (KIND[i.reply_kind] || KIND.other) : null;
              return h("tr", h("td", h("b", i.company || "-"), i.kind === "followup" ? h("div.tiny.faint", "follow-up") : null), h("td.small", i.to_email),
                h("td.small.muted", i.sent_at ? TT.fmtDateTime(i.sent_at) : "-"),
                h("td", k ? h("span.badge" + (k[1] ? "." + k[1] : ""), k[0]) : h("span.badge", "Sent · waiting")),
                h("td.small", i.reply_snippet ? h("div.reply", i.reply_snippet) : h("span.faint", i.status === "sent" ? "no answer yet" : "")));
            }))))), pager(r, (p) => tabSent(p)));
    }

    // ---- settings
    async function tabSettings() {
      mount(box, spin());
      const [s, t] = await Promise.all([api.get("/api/outreach/status"), api.get("/api/outreach/templates")]);
      const c = s.config;
      const ms = META.settings;
      const f = {
        smtp_host: h("input.input", { value: ms.smtp_host || c.host, placeholder: "smtp.gmail.com" }),
        smtp_port: h("input.input", { type: "number", value: c.port }),
        smtp_user: h("input.input", { value: ms.smtp_user || c.user, placeholder: "you@gmail.com" }),
        smtp_password: h("input.input", { type: "password", value: ms.smtp_password || "", placeholder: s.has_password ? "Using the app password from Alerts & inbox" : "16-character app password" }),
        outreach_daily_limit: h("input.input", { type: "number", min: 1, max: 50, value: c.daily }),
        outreach_gap_min: h("input.input", { type: "number", min: 1, max: 180, value: c.gap }),
        outreach_window: h("input.input", { value: c.window, placeholder: "09:00-18:00" }),
        outreach_followup_days: h("input.input", { type: "number", min: 0, max: 60, value: c.followup_days }),
      };
      const wk = h("input", { type: "checkbox", checked: !!c.weekdays });
      const att = h("input", { type: "checkbox", checked: !!c.attach_cv });
      async function saveSettings() {
        const payload = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value]));
        payload.outreach_weekdays = wk.checked ? 1 : 0;
        payload.outreach_attach_cv = att.checked ? 1 : 0;
        const r = await api.put("/api/settings", payload);
        META.settings = r.settings;
      }
      const saveBtn = () => h("button.btn.btn-primary", { onclick: (e) => withBusy(e.currentTarget, async () => {
        try { await saveSettings(); toast("Saved", "ok"); refreshStatus(); } catch (err) { toast(err.message, "error"); }
      }) }, "Save settings");
      const testBtn = h("button.btn", { onclick: () => withBusy(testBtn, async () => {
        try { await saveSettings(); await api.post("/api/outreach/test", {}); toast("Connected ✓ JobRadar can send from this mailbox", "ok", { duration: 5000 }); }
        catch (err) { toast(err.message, "error", { duration: 7000 }); }
      }) }, icon("zap"), "Save & test login");
      const tpl = {};
      const tplBoxes = ["fr", "en"].map((L) => {
        tpl[L] = { subject: h("input.input", { value: t.templates[L].subject }), body: h("textarea.textarea", { rows: 13 }, t.templates[L].body) };
        return h("div.stack", h("div.label", L === "fr" ? "Français - Tunisia, Morocco, Algeria, France, Belgium…" : "English - all other countries"),
          tpl[L].subject, tpl[L].body,
          h("button.btn.btn-sm.btn-ghost", { onclick: () => { tpl[L].subject.value = t.defaults[L].subject; tpl[L].body.value = t.defaults[L].body; } }, icon("undo"), "Reset to default"));
      });
      const saveTpl = h("button.btn.btn-primary", { onclick: () => withBusy(saveTpl, async () => {
        await api.put("/api/outreach/templates", { fr: { subject: tpl.fr.subject.value, body: tpl.fr.body.value }, en: { subject: tpl.en.subject.value, body: tpl.en.body.value } });
        toast("Templates saved - used for new drafts", "ok");
      }) }, "Save templates");
      mount(box,
        h("div.grid-2", { style: { alignItems: "start" } },
          h("div.card.card-pad.stack", h("h3", icon("mail", "icon"), " Your mailbox"),
            h("p.note", "Emails go out from your own address, so replies come straight back to you. Gmail: turn on 2-Step Verification, then create an App Password (Google Account → Security → App passwords)."),
            h("div.grid-2", field("SMTP server", f.smtp_host), field("Port", f.smtp_port, "465 (SSL) or 587 (STARTTLS)")),
            field("Email address", f.smtp_user), field("App password", f.smtp_password, "Stored only on this computer."),
            h("div.row", saveBtn(), testBtn)),
          h("div.card.card-pad.stack", h("h3", icon("shield", "icon"), " Safe sending"),
            h("p.note", "A few personal emails a day, spaced out, in office hours - like a real person writing. JobRadar never writes to the same company twice and stops by itself if something goes wrong."),
            h("div.grid-2", field("Max emails per day", f.outreach_daily_limit, "10-20 recommended"), field("Minutes between emails", f.outreach_gap_min, "A random extra delay is added")),
            h("div.grid-2", field("Sending hours", f.outreach_window, "Your local time, e.g. 09:00-18:00"), field("Follow-up draft after (days)", f.outreach_followup_days, "0 = no follow-ups")),
            h("label.switch", wk, h("span.track"), "Weekdays only"), h("label.switch", att, h("span.track"), "Attach my CV (the version that fits each company best)"),
            h("div.row", saveBtn()))),
        h("div.card.card-pad.stack", { style: { marginTop: "16px" } }, h("h3", icon("edit", "icon"), " Email templates"),
          h("div.row.wrap", h("span.hint", "Filled in for each company:"), t.placeholders.map((p) => h("code.ph", p))),
          h("div.grid-2", { style: { alignItems: "start" } }, tplBoxes), h("div.row", saveTpl)));
    }

    function show() { ({ find: tabFind, queue: tabQueue, sent: tabSent, settings: tabSettings })[tab](); }
    mount(content, statusBox, tabBar, box);
    await refreshStatus();
    show();
    const it = setInterval(refreshStatus, 10000);
    return () => clearInterval(it);
  }

  // ================================================================ NIGHT SCAN
  async function pageNight() {
    subEl.textContent = "JobRadar works while you sleep - and leaves you a morning report";
    const left = h("div.stack");
    const right = h("div.stack");
    const histBox = h("div");
    let timer = null;
    mount(content, h("div.grid-2.night-grid", { style: { alignItems: "start" } }, left, right), histBox);
    let r = await api.get("/api/night");
    api.post("/api/night/seen", {});
    const c = r.config;
    const en = h("input", { type: "checkbox", checked: !!c.enabled });
    const cu = h("input", { type: "checkbox", checked: !!c.catchup });
    const ka = h("input", { type: "checkbox", checked: !!c.keep_awake });
    const tm = h("input.input", { type: "time", value: c.time, style: { width: "140px" } });
    const em = h("input.input", { type: "number", min: 0, max: 300, value: c.enrich_max, style: { width: "120px" } });
    const tasks = new Set(c.tasks);
    const saveBtn = h("button.btn.btn-primary", { onclick: () => withBusy(saveBtn, async () => {
      const x = await api.put("/api/settings", { night_enabled: en.checked ? 1 : 0, night_time: tm.value || "02:00", night_catchup: cu.checked ? 1 : 0,
        night_keep_awake: ka.checked ? 1 : 0, night_enrich_max: +em.value || 0, night_tasks: [...tasks] });
      META.settings = x.settings;
      if (r.wake.installed) { try { await api.post("/api/night/wake", { on: true }); } catch (_) { /* keep settings */ } }
      toast("Night scan settings saved", "ok");
    }) }, "Save");
    const runBox = h("span");
    const wakeBox = h("div");
    function drawRunBtn(running) {
      mount(runBox, running ? h("button.btn", { onclick: async () => { await api.post("/api/night/stop", {}); toast("Stopping after the current step…", "info"); } }, icon("stop"), "Stop")
        : h("button.btn.btn-primary", { onclick: async (e) => { await withBusy(e.currentTarget, async () => { await api.post("/api/night/run", {}); }); toast("Deep scan started - keep using JobRadar meanwhile", "ok"); poll(); } }, icon("play"), "Run the deep scan now"));
    }
    function drawWake() {
      if (!r.wake.supported) return clear(wakeBox);
      const b = h("button.btn" + (r.wake.installed ? "" : ".btn-primary"), { onclick: () => withBusy(b, async () => {
        try { const x = await api.post("/api/night/wake", { on: !r.wake.installed }); r.wake = x.wake; toast(r.wake.installed ? "Your PC will wake up for the night scan" : "Wake task removed", "ok"); drawWake(); }
        catch (err) { toast(err.message, "error", { duration: 7000 }); }
      }) }, r.wake.installed ? "Remove" : "Set it up");
      mount(wakeBox, h("div.card.card-pad.stack", h("h3", icon("moon", "icon"), " Wake the PC at night"),
        h("p.note", "JobRadar can only scan while the PC is on. This creates a Windows scheduled task that wakes the PC from sleep 10 minutes before the scan and starts JobRadar in the background (no window). Windows must allow wake timers: Power options → Change plan settings → Advanced → Sleep → Allow wake timers."),
        h("div.row", r.wake.installed ? h("span.badge.ok", "Wake task active") : h("span.badge", "Not set up"), h("span.spacer"), b)));
    }
    mount(left,
      h("div.card.card-pad.stack", h("h3", icon("moon", "icon"), " Night deep scan"),
        h("label.switch", en, h("span.track"), "Run every night"),
        h("div.row.wrap", { style: { gap: "16px" } }, field("Start at", tm), field("Companies to scan for recruiters", em)),
        h("label.switch", cu, h("span.track"), "PC was off at night? Run when JobRadar starts (catch-up)"),
        h("label.switch", ka, h("span.track"), "Keep the PC awake while scanning"),
        h("div", h("div.label", { style: { marginBottom: "8px" } }, "What to do each night"),
          h("div.chips", r.stages.map(([id, name]) => h("button.chip" + (tasks.has(id) ? ".on" : ""), { onclick: (e) => { tasks.has(id) ? tasks.delete(id) : tasks.add(id); e.currentTarget.classList.toggle("on"); } }, name)))),
        h("div.row", saveBtn, h("span.spacer"), runBox)),
      wakeBox);
    drawWake();

    const STI = { done: "check", error: "alert", stopped: "stop", skipped: "minus", queued: "clock" };
    function progressCard(run) {
      const done = run.stages.filter((s) => ["done", "error", "stopped", "skipped"].includes(s.status)).length;
      return h("div.card.card-pad.stack", h("div.row", h("h3", run.status === "running" ? "Scanning…" : "Last scan"), h("span.spacer"),
        h("span.tiny.faint", "started " + TT.fmtDateTime(run.started_at) + (run.finished_at ? " · took " + Math.max(1, Math.round((run.finished_at - run.started_at) / 60)) + " min" : ""))),
        run.status === "running" ? h("div.pbar.live", h("i", { style: { width: Math.max(5, Math.round(done / run.stages.length * 100)) + "%" } })) : null,
        h("div.stages", run.stages.map((s) => h("div.stage." + s.status,
          h("span.st", s.status === "running" ? h("div.spinner") : icon(STI[s.status] || "clock")),
          h("div", { style: { minWidth: 0 } }, h("b", s.name), h("div.tiny.muted", s.message || (s.status === "skipped" ? "off" : s.status === "queued" ? "waiting" : "")))))));
    }
    function reportCard(run) {
      const rep = run.report || {};
      if (!rep.headline) return null;
      return h("div.card.card-pad.stack.report",
        h("h3", rep.headline),
        h("div.kpis.mini", kpiBox("briefcase", "New jobs", rep.new_jobs || 0), kpiBox("sparkles", "Top matches", rep.top_count || 0),
          kpiBox("flame", "Heating up", (rep.hot || []).length), kpiBox("users", "New recruiters", rep.people || 0)),
        (rep.top_matches || []).length ? h("div", h("div.label", { style: { marginBottom: "6px" } }, "Best new matches (" + rep.alert_min + "%+)"),
          h("div.rep-list", rep.top_matches.map((j) => h("button.rep-item", { onclick: () => openJob(j.id) }, ring(j.match_score, 34),
            h("div", { style: { minWidth: 0, textAlign: "left" } }, h("b", j.title), h("div.tiny.muted", [j.company, j.flag + " " + (j.city || j.country || "")].filter(Boolean).join(" · "))))))) : null,
        (rep.hot || []).length ? h("div", h("div.label", { style: { marginBottom: "6px" } }, "Companies heating up"),
          h("div.rep-list", rep.hot.map((c) => h("button.rep-item", { onclick: () => openCompany(c.key) }, h("span.badge.warn", icon("flame"), String(c.heat)),
            h("div", { style: { minWidth: 0, textAlign: "left" } }, h("b", c.name), h("div.tiny.muted", c.reasons.join(" · "))))))) : null,
        (rep.replies || []).length ? h("div", h("div.label", "Replies to your applications"), h("div.row.wrap", rep.replies.map((x) => h("span.badge" + (x.reply_kind === "interview" ? ".ok" : ""), x.company)))) : null,
        h("div.row.wrap", rep.closed ? h("span.badge", rep.closed + " saved job(s) closed") : null, rep.followups ? h("a.badge.info", { href: "#/outreach?tab=queue" }, rep.followups + " follow-up(s) to review") : null,
          h("span.spacer"), h("a.btn.btn-sm", { href: "#/jobs?sort=match" }, icon("sparkles"), "All jobs by match")));
    }
    function drawRight() {
      const last = r.history[0];
      drawRunBtn(r.running);
      if (!last) { mount(right, h("div.card", empty("moon", "No deep scan yet", "Click “Run the deep scan now” to try it - or wait for tonight."))); }
      else mount(right, reportCard(last) || null, progressCard(last));
      const past = r.history.slice(1).filter((x) => x.report && x.report.headline);
      mount(histBox, past.length ? [h("div.sec-title", icon("clock", "icon"), "Previous nights"),
        h("div.card", h("div.table-wrap", h("table.dtable", h("thead", h("tr", ["When", "Trigger", "Result", "Duration"].map((x) => h("th", x)))),
          h("tbody", past.map((x) => h("tr", h("td.small", TT.fmtDateTime(x.started_at)), h("td.small.muted", x.trigger), h("td.small", x.report.headline.replace(/^☀️ Good morning - /, "")),
            h("td.small.muted", x.finished_at ? Math.max(1, Math.round((x.finished_at - x.started_at) / 60)) + " min" : "-")))))))] : []);
    }
    async function poll() {
      clearTimeout(timer);
      try { r = await api.get("/api/night"); } catch (_) { /* retry */ }
      drawRight();
      if (r.running) timer = setTimeout(poll, 2500);
    }
    drawRight();
    if (r.running) poll();
    return () => clearTimeout(timer);
  }

  // ================================================================ SETTINGS
  async function pageSettings() {
    const st = META.settings;
    const f = {
      board_cache_hours: h("input.input", { type: "number", min: 1, max: 72, value: st.board_cache_hours }),
      board_workers: h("input.input", { type: "number", min: 2, max: 16, value: st.board_workers }),
      crawl_pages: h("input.input", { type: "number", min: 5, max: 300, value: st.crawl_pages }),
    };
    const themeSel = sel([["system", "System"], ["light", "Light"], ["dark", "Dark"]], LS.get("jr_theme", "system"), (v) => { LS.set("jr_theme", v); location.reload(); });
    mount(content, h("div.stack", { style: { maxWidth: "820px" } },
      h("div.card.card-pad.stack",
        h("h3", "Performance"),
        h("div.grid-3",
          field("Company board cache (hours)", f.board_cache_hours, "How long company career boards are reused before re-downloading."),
          field("Parallel company downloads", f.board_workers, "2–16. Higher is faster; 8 is polite."),
          field("Pages per crawled website", f.crawl_pages)),
        h("div.row", h("button.btn.btn-primary", { onclick: async () => {
          const r = await api.put("/api/settings", Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value])));
          META.settings = r.settings; toast("Saved", "ok");
        } }, "Save"))),
      h("div.card.card-pad.stack", h("h3", "Appearance"), field("Theme", themeSel)),
      h("div.card.card-pad.stack", h("h3", "Your data"),
        h("p.note", "Everything is stored on this computer only. Automatic backups run at every start (last 10 kept)."),
        h("div.row", h("a.btn", { href: "/api/backup" }, icon("download"), "Download a backup now"),
          h("button.btn", { onclick: () => download("/api/export?format=xlsx") }, icon("download"), "Export all jobs to Excel"))),
      h("div.card.card-pad.stack", h("h3", "How JobRadar collects jobs"),
        h("p.note", "JobRadar only uses official/public job APIs and feeds, public company career boards, schema.org job data on websites you add (robots.txt respected), and your own alert emails. It identifies itself honestly, waits between requests to each site, and never bypasses logins, captchas or blocks. Contact details come from the job post itself or the company's own public website."),
        h("p.note", "Please use contact details responsibly: for your own applications, respecting each site's terms and privacy laws in your country."))));
  }

  // ================================================================ boot
  (async function boot() {
    try { META = await api.get("/api/meta"); }
    catch (e) { mount($("#app"), empty("alert", "JobRadar isn't responding", e.message)); return; }
    META.sources.forEach((s) => { SRC[s.id] = s.name; });
    renderShell();
    window.addEventListener("hashchange", route);
    route();
    refreshStats();
    setInterval(refreshStats, 8000);
  })();
})();
