/* JobRadar Autofill - form filler. Injected only when you click the extension (or press Alt+Shift+F).
   - Recognises fields by autocomplete tokens, known applicant-tracking-system field names and multilingual labels
   - Fills only EMPTY fields (never overwrites what you typed), React/Vue-safe, uploads your chosen CV
   - Never touches sensitive/diversity questions, passwords or captchas, and NEVER clicks Submit */
(function () {
  "use strict";
  if (window.__jobradarAutofill) { window.__jobradarAutofill.run(); return; }

  const IS_TOP = window.top === window;
  const fold = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[_\-\[\]().:*/]+/g, " ").replace(/\s+/g, " ").trim();
  const send = (msg) => new Promise((res) => chrome.runtime.sendMessage(msg, (r) => res(r || { ok: false, error: chrome.runtime.lastError && chrome.runtime.lastError.message })));

  // ---------------------------------------------------------------- field rules (order matters: specific first)
  // ac = autocomplete tokens, nm = regex on name/id, lb = regex on label/placeholder/aria text, kinds = allowed controls
  const R = (key, o) => Object.assign({ key, kinds: ["text"] }, o);
  const RULES = [
    R("email", { ac: ["email"], nm: /(^|\b)e ?mail/, lb: /\be ?mail\b|courriel|correo|posta elettronica|البريد/ , kinds: ["text", "email"] }),
    R("first_name", { ac: ["given-name"], nm: /first ?name|firstname|given ?name|prenom|vorname|_systemfield_first/,
      lb: /first name|given name|prenom|vorname|\bnombre\b(?! completo)|\bnome\b(?! completo)|voornaam|الاسم الأول/ }),
    R("last_name", { ac: ["family-name"], nm: /last ?name|lastname|family ?name|surname|nachname|apellido|cognome|_systemfield_last/,
      lb: /last name|family name|surname|nom de famille|^nom$|^nom \*|nachname|apellidos?|cognome|sobrenome|achternaam|اسم العائلة|اللقب/ }),
    R("full_name", { ac: ["name"], nm: /^(full ?name|name|candidate ?name|_systemfield_name)$/,
      lb: /full name|your name|^name$|nom complet|nom et prenom|vollstandiger name|nombre completo|nome completo|الاسم الكامل/ }),
    R("phone", { ac: ["tel", "tel-national"], nm: /phone|mobile|tel(ephone)?|handy|celular|cellulare/,
      lb: /phone|mobile|telephone|telefon|handy|telefono|celular|cellulare|الهاتف|جوال|رقم الهاتف/, kinds: ["text", "tel"] }),
    R("linkedin", { nm: /linked ?in/, lb: /linked ?in/, kinds: ["text", "url"] }),
    R("github", { nm: /github/, lb: /github/, kinds: ["text", "url"] }),
    R("website", { ac: ["url"], nm: /website|portfolio|personal ?site|homepage|urls? ?other/,
      lb: /website|portfolio|site web|personal site|webseite|sitio web|sito web|موقع/, kinds: ["text", "url"] }),
    R("postal_code", { ac: ["postal-code"], nm: /zip|postal|postcode|plz/, lb: /zip|postal|code postal|plz|postleitzahl|codigo postal|\bcap\b/ }),
    R("city", { ac: ["address-level2"], nm: /\bcity\b|ville|stadt|ciudad|citta|cidade|location|localisation/,
      lb: /\bcity\b|ville|\bstadt\b|\bort\b|ciudad|citta|cidade|المدينة|current location|localisation|where are you (based|located)/ }),
    R("country", { ac: ["country", "country-name"], nm: /country|pays|land|pais|paese/,
      lb: /country|pays|\bland\b|pais|paese|البلد|الدولة/, kinds: ["text", "select"] }),
    R("address", { ac: ["street-address", "address-line1"], nm: /address|adresse|street/, lb: /address|adresse|anschrift|direccion|indirizzo|endereco|العنوان/ }),
    R("current_company", { ac: ["organization"], nm: /current ?company|employer|^org$|company ?name/,
      lb: /current (company|employer)|employer|entreprise actuelle|employeur actuel|arbeitgeber|empresa actual|azienda attuale/ }),
    R("current_title", { ac: ["organization-title"], nm: /current ?title|job ?title|position ?title/,
      lb: /current (job )?title|job title|poste actuel|intitule du poste|berufsbezeichnung|cargo actual|posizione attuale/ }),
    R("years_experience", { nm: /years? ?(of )?experience|experience ?years|yoe/,
      lb: /years? of (professional )?experience|annees d.experience|jahre (berufs)?erfahrung|anos de experiencia|anni di esperienza|سنوات الخبرة/, kinds: ["text", "number", "select"] }),
    R("salary_expectation", { nm: /salary|compensation|pretention/,
      lb: /salary|compensation expectation|pretentions?|salaire|remuneration souhaitee|gehaltsvorstellung|gehalt|pretension salarial|salario|retribuzione|الراتب/, kinds: ["text", "number"] }),
    R("notice_period", { nm: /notice|availability|start ?date/,
      lb: /notice period|preavis|disponibilite|availability|start date|date de debut|kundigungsfrist|verfugbar ab|disponibilidad|preaviso|متى يمكنك/ }),
    R("education_school", { nm: /school|university|college|universite/, lb: /school|university|college|ecole|universite|hochschule|universitat|universidad|universita|الجامعة/ }),
    R("education_degree", { nm: /degree|diploma|diplome/, lb: /degree|diploma|diplome|abschluss|titulo|laurea|الشهادة/ }),
    R("languages", { nm: /languages?/, lb: /languages? (spoken|you speak)|langues|sprachen|idiomas|lingue|اللغات/ }),
    R("cover_letter", { nm: /cover ?letter|motivation|anschreiben/,
      lb: /cover letter|lettre de motivation|motivation letter|anschreiben|carta de presentacion|lettera di presentazione|carta de apresentacao|رسالة التحفيز/, kinds: ["textarea"] }),
    R("summary", { nm: /summary|about ?you|profile/, lb: /summary|about (you|yourself)|resume du profil|a propos de vous|uber mich|sobre ti|chi sei/, kinds: ["textarea"] }),
    // yes / no questions
    R("authorized_to_work", { lb: /authori[sz]ed to work|legally (authori[sz]ed|allowed|eligible) to work|right to work|work permit|autorise a travailler|arbeitserlaubnis|autorizado para trabajar/, kinds: ["select", "radio"] }),
    R("requires_sponsorship", { lb: /sponsor(ship)?|visa support|parrainage|visum|patrocinio/, kinds: ["select", "radio"] }),
    R("willing_to_relocate", { lb: /relocat|demenag|umzug|reubicar|trasferir/, kinds: ["select", "radio"] }),
  ];
  const RESUME_RX = /resume|\bcv\b|curriculum|lebenslauf|currículo|السيرة الذاتية|attach.*(resume|cv)/;
  const COVER_FILE_RX = /cover ?letter|lettre de motivation|anschreiben/;
  // Never touched: diversity / sensitive / security questions
  const SENSITIVE = /gender|\bsex\b|sexe|geschlecht|genero|race|ethnic|origine|hispanic|latino|veteran|disab|handicap|behinderung|sexual orientation|pronoun|religion|date of birth|birth ?date|date de naissance|geburtsdatum|\bage\b|marital|social security|\bssn\b|passport number|national id|cin\b|password|mot de passe|passwort|captcha|credit card|iban/;
  const YES = /^(yes|oui|ja|si|sim|نعم|y)\b/;
  const NO = /^(no|non|nein|nao|não|لا|n)\b/;

  // ---------------------------------------------------------------- helpers
  function visible(el) {
    if (el.disabled || el.readOnly) return false;
    if (el.type === "file") return true;                  // file inputs are often hidden behind a drop-zone
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== "hidden" && st.display !== "none";
  }

  function labelText(el) {
    const parts = [];
    const add = (t) => { if (t && t.trim()) parts.push(t.trim()); };
    if (el.id) document.querySelectorAll('label[for="' + CSS.escape(el.id) + '"]').forEach((l) => add(l.textContent));
    const wrap = el.closest("label");
    if (wrap) add(wrap.textContent);
    add(el.getAttribute("aria-label"));
    (el.getAttribute("aria-labelledby") || "").split(/\s+/).forEach((id) => { const n = id && document.getElementById(id); if (n) add(n.textContent); });
    add(el.getAttribute("placeholder"));
    add(el.getAttribute("title"));
    add(el.getAttribute("data-qa"));
    if (el.type === "radio" || el.type === "checkbox") {
      const fs = el.closest("fieldset");
      const lg = fs && fs.querySelector("legend");
      if (lg) add(lg.textContent);
    }
    if (parts.length < 2) {                                // nearby question text in custom layouts
      let n = el.parentElement;
      for (let i = 0; i < 3 && n; i++, n = n.parentElement) {
        const q = n.querySelector("label, legend, .label, [class*='label'], [class*='question'], h3, h4");
        if (q && !q.contains(el) && q.textContent.length < 200) { add(q.textContent); break; }
      }
    }
    return parts.join(" | ").slice(0, 400);
  }

  function describe(el) {
    return { ac: (el.getAttribute("autocomplete") || "").toLowerCase().split(/\s+/).pop(), nm: fold((el.name || "") + " " + (el.id || "")),
             lb: fold(labelText(el)), raw: labelText(el) };
  }

  function kindOf(el) {
    if (el.tagName === "TEXTAREA") return "textarea";
    if (el.tagName === "SELECT") return "select";
    const t = (el.type || "text").toLowerCase();
    if (["text", "email", "tel", "url", "number", "search"].includes(t)) return t === "search" ? null : t;
    if (t === "radio" || t === "file") return t;
    return null;
  }

  function isRequired(el, d) {
    return el.required || el.getAttribute("aria-required") === "true" || /\*/.test(d.raw);
  }

  function setValue(el, value) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    el.focus({ preventScroll: true });
    setter.call(el, value);                                  // native setter: React/Vue see the change
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function pickOption(select, want) {
    const w = fold(want);
    if (!w) return false;
    const opts = [...select.options].filter((o) => o.value !== "" || o.textContent.trim());
    const exact = opts.find((o) => fold(o.textContent) === w || fold(o.value) === w);
    const yesno = YES.test(w) ? opts.find((o) => YES.test(fold(o.textContent))) : NO.test(w) ? opts.find((o) => NO.test(fold(o.textContent))) : null;
    const partial = opts.find((o) => w.length > 2 && (fold(o.textContent).startsWith(w) || w.startsWith(fold(o.textContent)) && fold(o.textContent).length > 2));
    const hit = exact || yesno || partial;
    if (!hit) return false;
    setValue(select, hit.value);
    return true;
  }

  function pickRadio(radios, want) {
    const w = fold(want);
    const match = radios.find((r) => {
      const t = fold(labelOf(r) || r.value);
      return (YES.test(w) && YES.test(t)) || (NO.test(w) && NO.test(t)) || t === w;
    });
    if (!match) return false;
    match.click();
    return true;
  }

  function labelOf(radio) {
    if (radio.id) { const l = document.querySelector('label[for="' + CSS.escape(radio.id) + '"]'); if (l) return l.textContent; }
    const wrap = radio.closest("label");
    return wrap ? wrap.textContent : radio.value;
  }

  function mark(el, color, why) {
    if (!el.dataset.jrOutline) el.dataset.jrOutline = el.style.outline || "none";
    el.style.outline = "2px solid " + color;
    el.style.outlineOffset = "1px";
    if (why) el.title = why;
  }

  function jobInfo() {
    let title = "", company = "";
    document.querySelectorAll('script[type="application/ld+json"]').forEach((s) => {
      try {
        const stack = [JSON.parse(s.textContent)];
        while (stack.length) {
          const n = stack.pop();
          if (Array.isArray(n)) { stack.push(...n); continue; }
          if (!n || typeof n !== "object") continue;
          if (n["@graph"]) stack.push(...[].concat(n["@graph"]));
          const t = [].concat(n["@type"] || []);
          if (t.includes("JobPosting")) {
            title = title || n.title || "";
            const org = [].concat(n.hiringOrganization || [])[0];
            company = company || (typeof org === "string" ? org : (org && org.name) || "");
          }
        }
      } catch (_) { /* invalid JSON-LD */ }
    });
    const og = (p) => (document.querySelector('meta[property="' + p + '"]') || {}).content || "";
    title = title || og("og:title") || (document.querySelector("h1") || {}).textContent || document.title;
    company = company || og("og:site_name");
    return { title: String(title).trim().slice(0, 200), company: String(company).trim().slice(0, 120) };
  }

  // ---------------------------------------------------------------- filling
  const state = { profile: null, cvs: [], cvId: null, filled: new Set(), needs: new Map(), skipped: 0, cvDone: false, errors: [] };

  function valueFor(key) {
    const p = state.profile;
    if (!p) return "";
    if (key === "full_name") return p.full_name;
    return p[key] || "";
  }

  function matchRule(el, d, kind) {
    for (const r of RULES) {
      const kinds = r.kinds.includes("text") ? r.kinds.concat(["email", "tel", "url", "number"]) : r.kinds;
      if (!kinds.includes(kind)) continue;
      if (r.ac && d.ac && r.ac.includes(d.ac)) return r;
    }
    for (const r of RULES) {
      const kinds = r.kinds.includes("text") ? r.kinds.concat(["email", "tel", "url", "number"]) : r.kinds;
      if (!kinds.includes(kind)) continue;
      if ((r.nm && r.nm.test(d.nm)) || (r.lb && r.lb.test(d.lb))) return r;
    }
    return null;
  }

  async function fillFile(el) {
    if (el.files && el.files.length) return false;                     // you already attached something
    const cv = state.cvs.find((c) => c.id === state.cvId);
    if (!cv) return false;
    const r = await send({ type: "cv", id: cv.id, name: cv.name });
    if (!r.ok) { state.errors.push("CV download failed: " + r.error); return false; }
    const bin = atob(r.data.b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const file = new File([bytes], cv.name, { type: r.data.mime || "application/pdf" });
    const dt = new DataTransfer();
    dt.items.add(file);
    el.files = dt.files;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  async function fillAll() {
    const controls = [...document.querySelectorAll("input, textarea, select")].filter((el) => !el.closest("#jobradar-autofill-host"));
    const radioGroups = new Map();
    for (const el of controls) {
      const kind = kindOf(el);
      if (!kind || !visible(el) || el.dataset.jrDone) continue;
      const d = describe(el);
      if (SENSITIVE.test(d.lb) || SENSITIVE.test(d.nm)) { el.dataset.jrDone = "1"; state.skipped++; continue; }
      if (kind === "radio") {
        const g = radioGroups.get(el.name) || [];
        g.push(el);
        radioGroups.set(el.name, g);
        continue;
      }
      if (kind === "file") {
        if (COVER_FILE_RX.test(d.lb + " " + d.nm)) { if (isRequired(el, d)) state.needs.set(el, "Attach a cover letter file"); continue; }
        if (RESUME_RX.test(d.lb + " " + d.nm) || controls.filter((c) => c.type === "file").length === 1) {
          if (await fillFile(el)) { state.cvDone = true; state.filled.add(el); el.dataset.jrDone = "1"; mark(el.closest("div") || el, "#22c55e", "CV attached by JobRadar"); }
        }
        continue;
      }
      const current = el.tagName === "SELECT" ? (el.value && el.selectedIndex > 0 ? el.value : "") : el.value;
      if (String(current || "").trim()) continue;                       // never overwrite
      const rule = matchRule(el, d, kind);
      const val = rule ? valueFor(rule.key) : "";
      let ok = false;
      if (rule && val) {
        if (kind === "select") ok = pickOption(el, val);
        else { setValue(el, val); ok = true; }
      }
      if (ok) { state.filled.add(el); el.dataset.jrDone = "1"; mark(el, "#22c55e", "Filled by JobRadar - please check"); state.needs.delete(el); }
      else if (isRequired(el, d)) { state.needs.set(el, d.raw.split("|")[0].trim().slice(0, 70) || "Required field"); mark(el, "#f59e0b", "Please answer this yourself"); }
    }
    for (const [, radios] of radioGroups) {
      if (radios.some((r) => r.checked)) continue;
      const d = describe(radios[0]);
      if (SENSITIVE.test(d.lb)) { state.skipped++; continue; }
      const rule = matchRule(radios[0], d, "radio");
      const val = rule ? valueFor(rule.key) : "";
      if (rule && val && pickRadio(radios, val)) { radios.forEach((r) => { r.dataset.jrDone = "1"; }); state.filled.add(radios[0]); mark(radios[0].closest("fieldset") || radios[0], "#22c55e"); }
      else if (radios.some((r) => r.required) || /\*/.test(d.raw)) { state.needs.set(radios[0], d.raw.split("|")[0].trim().slice(0, 70)); mark(radios[0].closest("fieldset") || radios[0], "#f59e0b"); }
    }
  }

  // ---------------------------------------------------------------- panel (shadow DOM, top frame)
  let host = null, shadow = null, observer = null;

  function panel(html) {
    if (!IS_TOP) return;
    if (!host) {
      host = document.createElement("div");
      host.id = "jobradar-autofill-host";
      host.style.cssText = "position:fixed;right:18px;bottom:18px;z-index:2147483647;";
      shadow = host.attachShadow({ mode: "open" });
      document.documentElement.appendChild(host);
    }
    shadow.innerHTML = STYLE + '<div class="p">' + html + "</div>";
  }

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const STYLE = `<style>
    .p{width:330px;font:13.5px/1.45 system-ui,Segoe UI,Roboto,sans-serif;color:#1c1b19;background:#fff;border-radius:16px;box-shadow:0 18px 50px -12px rgba(0,0,0,.35),0 0 0 1px rgba(0,0,0,.06);overflow:hidden}
    .h{display:flex;align-items:center;gap:10px;padding:12px 14px;background:linear-gradient(135deg,#4338ca,#5b5bd6 60%,#0ea5e9);color:#fff;font-weight:800}
    .h .x{margin-left:auto;background:rgba(255,255,255,.2);border:0;color:#fff;width:26px;height:26px;border-radius:8px;cursor:pointer;font-size:15px}
    .b{padding:12px 14px}
    .stat{display:flex;gap:8px;margin-bottom:10px}.stat div{flex:1;background:#f4f3f1;border-radius:10px;padding:8px;text-align:center}
    .stat b{display:block;font-size:18px}.stat .g b{color:#16a34a}.stat .a b{color:#d97706}
    ul{margin:6px 0 10px;padding-left:18px;max-height:120px;overflow:auto;color:#5f5b55}
    select,button.btn{width:100%;margin-top:6px;border-radius:9px;border:1px solid #d4cfc8;padding:8px 10px;font:inherit;background:#fff;cursor:pointer}
    button.pri{background:#5b5bd6;color:#fff;border-color:#5b5bd6;font-weight:700}
    .row{display:flex;gap:6px}.row button{flex:1}
    .m{color:#5f5b55;font-size:12.5px;margin-top:8px}.err{color:#d33a2c;font-weight:600}.ok{color:#16a34a;font-weight:700}
  </style>`;

  function render(extra) {
    const needs = [...state.needs.values()].filter(Boolean);
    const cvOpts = state.cvs.map((c) => `<option value="${esc(c.id)}"${c.id === state.cvId ? " selected" : ""}>${esc(c.label || c.name)}</option>`).join("");
    panel(`<div class="h">JobRadar Autofill<button class="x" id="close" title="Close">✕</button></div>
      <div class="b">
        <div class="stat"><div class="g"><b>${state.filled.size}</b>filled</div><div class="a"><b>${needs.length}</b>need you</div><div><b>${state.cvDone ? "✓" : "–"}</b>CV</div></div>
        ${needs.length ? "<div><b>Please answer:</b></div><ul>" + needs.slice(0, 8).map((n) => "<li>" + esc(n) + "</li>").join("") + "</ul>" : ""}
        ${state.skipped ? `<div class="m">${state.skipped} sensitive question(s) left for you (diversity, date of birth…).</div>` : ""}
        ${state.cvs.length ? `<label class="m">CV to attach${state.suggested && state.suggested === state.cvId && state.cvs.length > 1 ? " · best match for this job" : ""}</label><select id="cv">${cvOpts}</select>` : '<div class="m">No CV in JobRadar yet - add one in My profile.</div>'}
        <div class="row"><button class="btn" id="again">Fill again</button><button class="btn pri" id="applied">Mark as applied</button></div>
        <div class="m">Check everything, then click the site's Submit button yourself. JobRadar never submits for you.</div>
        ${extra || ""}
        ${state.errors.length ? '<div class="m err">' + esc(state.errors.slice(-1)[0]) + "</div>" : ""}
      </div>`);
    shadow.getElementById("close").onclick = close;
    shadow.getElementById("again").onclick = () => run(true);
    shadow.getElementById("applied").onclick = markApplied;
    const cv = shadow.getElementById("cv");
    if (cv) cv.onchange = async (e) => {
      state.cvId = e.target.value;
      document.querySelectorAll('input[type="file"]').forEach((f) => { delete f.dataset.jrDone; });
      state.cvDone = false;
      await run(true, true);
    };
  }

  function close() {
    if (observer) observer.disconnect();
    document.querySelectorAll("[data-jr-outline]").forEach((el) => { el.style.outline = el.dataset.jrOutline === "none" ? "" : el.dataset.jrOutline; delete el.dataset.jrOutline; });
    if (host) host.remove();
    host = null;
    window.__jobradarAutofill = null;
  }

  async function markApplied() {
    const info = jobInfo();
    const r = await send({ type: "applied", payload: { url: location.href, title: info.title, company: info.company, cv_id: state.cvId } });
    render(r.ok ? `<div class="m ok">Saved in JobRadar as Applied${r.data.created ? " (new job added)" : ""}.</div>` : `<div class="m err">${esc(r.error)}</div>`);
  }

  async function run(again, fileOnly) {
    if (!state.profile) {
      const info = jobInfo();
      const r = await send({ type: "profile", title: info.title, company: info.company, url: location.href });
      if (!r.ok) {
        const msg = r.error === "NOT_PAIRED" ? "Connect the extension first: open its Options and paste your pairing code from JobRadar > My profile."
          : r.error === "BAD_TOKEN" ? "The pairing code is wrong or was changed. Copy it again from JobRadar > My profile."
          : r.error === "JOBRADAR_OFFLINE" ? "JobRadar isn't running. Start it (Start.bat) and try again." : r.error;
        panel(`<div class="h">JobRadar Autofill<button class="x" id="close">✕</button></div><div class="b"><div class="err">${esc(msg)}</div>
          <button class="btn pri" id="opt">Open extension options</button></div>`);
        if (shadow) { shadow.getElementById("close").onclick = close; shadow.getElementById("opt").onclick = () => send({ type: "options" }); }
        return;
      }
      state.profile = r.data.profile;
      state.cvs = r.data.cvs || [];
      // the CV that matches this job best (JobRadar's match score), else the default one
      state.suggested = r.data.suggested_cv || "";
      state.cvId = (state.cvs.find((c) => c.id === state.suggested) || state.cvs.find((c) => c.default) || state.cvs[0] || {}).id || null;
    }
    if (again && !fileOnly) document.querySelectorAll("[data-jr-done]").forEach((el) => { if (el.type !== "file") delete el.dataset.jrDone; });
    await fillAll();
    render();
    // multi-step forms: fill new fields as they appear (next page of a wizard, "add another" sections)
    if (!observer) {
      let t = null;
      observer = new MutationObserver(() => { clearTimeout(t); t = setTimeout(async () => { await fillAll(); render(); }, 900); });
      observer.observe(document.body, { childList: true, subtree: true });
    }
  }

  window.__jobradarAutofill = { run: () => run(true) };
  run(false);
})();
