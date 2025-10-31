/* global window, document */
const { invoke } = window.__TAURI__.core;

const $ = (q) => document.querySelector(q);
const on = (el, ev, fn) => el.addEventListener(ev, fn);

let logTimer = null;
let seenTimer = null;
let selectedUUID = null;

function logAppend(lines) {
  const box = $("#logBox");
  const freeze = $("#chkFreeze").checked;
  if (!lines || !lines.length) return;
  let atBottom = false;
  if (!freeze) {
    atBottom = Math.abs(box.scrollHeight - box.scrollTop - box.clientHeight) < 8;
  }
  for (const ln of lines) {
    box.textContent += (box.textContent.endsWith("\n") || box.textContent === "" ? "" : "\n") + ln;
  }
  if (!freeze && atBottom) {
    box.scrollTop = box.scrollHeight;
  }
}

async function rpc(method, params = {}) {
  const r = await invoke("mesh_action", { method, params });
  if (!r || !r.ok) throw new Error(r && r.error ? r.error : "rpc failed");
  return r.data;
}

// ----- Controls
on($("#btnCreateNet"), "click", async () => {
  try { await rpc("create_network"); logAppend(["[create_network] OK"]); } catch (e) { logAppend(["[create_network][ERR] " + e.message]); }
});
on($("#btnAttach"), "click", async () => {
  try { await rpc("attach"); logAppend(["[attach] OK"]); } catch (e) { logAppend(["[attach][ERR] " + e.message]); }
});
on($("#btnLeave"), "click", async () => {
  try { await rpc("leave", { deep:false }); logAppend(["[leave] OK"]); } catch (e) { logAppend(["[leave][ERR] " + e.message]); }
});
on($("#btnPurge"), "click", async () => {
  try { await rpc("purge"); logAppend(["[purge] OK"]); } catch (e) { logAppend(["[purge][ERR] " + e.message]); }
});

// ----- Scan + Seen UUIDs
async function refreshSeenOnce() {
  try {
    const rows = await rpc("scan_seen", { limit: 200 });
    const tb = $("#seenTable tbody");
    tb.innerHTML = "";
    for (const o of rows) {
      const tr = document.createElement("tr");
      tr.dataset.uuid = o.uuid_hex;
      tr.innerHTML = `<td>${o.uuid_hex}</td><td>${o.rssi}</td><td>${Math.round((Date.now()/1000 - o.last_seen))}s ago</td>`;
      on(tr, "click", () => {
        [...tb.querySelectorAll("tr")].forEach(r => r.classList.remove("sel"));
        tr.classList.add("sel");
        selectedUUID = o.uuid_hex;
        $("#btnProvision").disabled = false;
      });
      on(tr, "dblclick", async () => {
        selectedUUID = o.uuid_hex;
        $("#btnProvision").disabled = false;
        await doProvision();
      });
      tb.appendChild(tr);
    }
  } catch (e) {
    logAppend(["[scan_seen][ERR] " + e.message]);
  }
}

async function doProvision() {
  if (!selectedUUID) return;
  try {
    await rpc("provision_uuid", { uuid_hex: selectedUUID });
    logAppend([`[provision_uuid] ${selectedUUID} → OK`]);
  } catch (e) {
    logAppend([`[provision_uuid][ERR] ${e.message}`]);
  }
}

on($("#btnProvision"), "click", doProvision);

on($("#btnScanStart"), "click", async () => {
  try {
    await rpc("scan_start", { seconds: 15 });
    $("#scanStatus").textContent = "scanning…";
    if (seenTimer) clearInterval(seenTimer);
    await refreshSeenOnce();
    seenTimer = setInterval(refreshSeenOnce, 1000);
    logAppend(["[scan_start] OK"]);
  } catch (e) {
    logAppend(["[scan_start][ERR] " + e.message]);
  }
});

on($("#btnScanStop"), "click", async () => {
  try { await rpc("scan_stop"); } catch (e) { /* ignore */ }
  $("#scanStatus").textContent = "idle";
  if (seenTimer) { clearInterval(seenTimer); seenTimer = null; }
  logAppend(["[scan_stop] OK"]);
});

on($("#btnRefreshSeen"), "click", refreshSeenOnce);

// ----- Logs
on($("#btnListRecent"), "click", async () => {
  try {
    const lines = await rpc("poll_logs");
    logAppend(lines);
  } catch (e) {
    logAppend(["[poll_logs][ERR] " + e.message]);
  }
});

function startLogPoll() {
  const rate = parseInt($("#pollRate").value, 10);
  if (logTimer) clearInterval(logTimer);
  logTimer = setInterval(async () => {
    try {
      const lines = await rpc("poll_logs");
      logAppend(lines);
    } catch (e) {
      logAppend(["[poll_logs][ERR] " + e.message]);
    }
  }, rate);
}
function stopLogPoll() {
  if (logTimer) { clearInterval(logTimer); logTimer = null; }
}
on($("#chkAutoPoll"), "change", (e) => {
  if (e.target.checked) startLogPoll(); else stopLogPoll();
});
on($("#pollRate"), "change", () => { if ($("#chkAutoPoll").checked) startLogPoll(); });

// Freeze scroll on hover (quality-of-life)
on($("#logBox"), "mouseenter", () => { $("#chkFreeze").checked = true; });
on($("#logBox"), "mouseleave", () => { $("#chkFreeze").checked = false; });

// greet demo still present? Not used anymore; we keep the file minimal.

