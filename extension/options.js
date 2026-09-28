const $ = (id) => document.getElementById(id);
const WIDE = { origins: ["https://*/*", "http://*/*"] };

chrome.storage.local.get({ base: "http://127.0.0.1:5090", token: "" }, (c) => {
  $("base").value = c.base;
  $("token").value = c.token;
});

function status(text, ok) {
  $("status").textContent = text;
  $("status").className = ok ? "ok" : "err";
}

$("save").onclick = async () => {
  const base = $("base").value.trim().replace(/\/+$/, "") || "http://127.0.0.1:5090";
  const token = $("token").value.trim();
  if (!/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(base)) return status("The address must be your local JobRadar (http://127.0.0.1:port).", false);
  await chrome.storage.local.set({ base, token });
  status("Testing…", true);
  chrome.runtime.sendMessage({ type: "ping" }, (r) => {
    if (r && r.ok) status("Connected ✓ " + (r.data.name ? "Hello " + r.data.name + " · " : "") + r.data.cvs + " CV(s) available", true);
    else if (r && r.error === "BAD_TOKEN") status("Wrong pairing code - copy it again from JobRadar → My profile.", false);
    else if (r && r.error === "JOBRADAR_OFFLINE") status("Can't reach JobRadar - is it running?", false);
    else status("Not connected: " + ((r && r.error) || "unknown error"), false);
  });
};

async function showWide() {
  const has = await chrome.permissions.contains(WIDE);
  $("wideStatus").textContent = has ? "Allowed ✓" : "";
  $("wideStatus").className = has ? "ok" : "";
}
$("wide").onclick = async () => { await chrome.permissions.request(WIDE); showWide(); };
showWide();
