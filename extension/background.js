/* JobRadar Autofill - background service worker.
   Talks to your local JobRadar (http://127.0.0.1:5090) with your pairing code, and injects the form filler into the
   tab you clicked on. It never runs on a page unless you click the button / press Alt+Shift+F. */
const DEFAULTS = { base: "http://127.0.0.1:5090", token: "" };

async function config() {
  const c = await chrome.storage.local.get(DEFAULTS);
  return { base: (c.base || DEFAULTS.base).replace(/\/+$/, ""), token: c.token || "" };
}

async function call(path, opts = {}) {
  const { base, token } = await config();
  if (!token) throw new Error("NOT_PAIRED");
  let res;
  try {
    res = await fetch(base + path, {
      method: opts.method || "GET",
      headers: Object.assign({ "X-JobRadar-Token": token, "X-JobRadar": "1" }, opts.body ? { "Content-Type": "application/json" } : {}),
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) {
    throw new Error("JOBRADAR_OFFLINE");
  }
  if (res.status === 401) throw new Error("BAD_TOKEN");
  if (!res.ok) {
    let msg = "HTTP " + res.status;
    try { msg = (await res.json()).error || msg; } catch (_) { /* not json */ }
    throw new Error(msg);
  }
  return opts.raw ? res : res.json();
}

function toBase64(buf) {
  const bytes = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    try {
      if (msg.type === "profile") {
        const q = new URLSearchParams({ title: msg.title || "", company: msg.company || "", url: msg.url || "" });
        reply({ ok: true, data: await call("/ext/profile?" + q) });
      } else if (msg.type === "cv") {
        const res = await call("/ext/cv/" + encodeURIComponent(msg.id), { raw: true });
        const buf = await res.arrayBuffer();
        reply({ ok: true, data: { b64: toBase64(buf), mime: res.headers.get("Content-Type") || "application/pdf", name: msg.name } });
      } else if (msg.type === "applied") {
        reply({ ok: true, data: await call("/ext/applied", { method: "POST", body: msg.payload }) });
      } else if (msg.type === "ping") {
        reply({ ok: true, data: await call("/ext/ping") });
      } else if (msg.type === "options") {
        chrome.runtime.openOptionsPage();
        reply({ ok: true });
      } else {
        reply({ ok: false, error: "unknown message" });
      }
    } catch (e) {
      reply({ ok: false, error: e.message });
    }
  })();
  return true;                                   // async reply
});

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab || !tab.id || !/^https?:/.test(tab.url || "")) return;
  const target = { tabId: tab.id };
  // All frames when you allowed it in Options (forms embedded from Greenhouse/Lever/…); otherwise the page itself.
  const wide = await chrome.permissions.contains({ origins: ["https://*/*", "http://*/*"] });
  if (wide) target.allFrames = true;
  try {
    await chrome.scripting.executeScript({ target, files: ["content.js"] });
  } catch (e) {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
  }
});

chrome.runtime.onInstalled.addListener((d) => {
  if (d.reason === "install") chrome.runtime.openOptionsPage();
});
