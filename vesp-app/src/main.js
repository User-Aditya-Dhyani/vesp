// Vanilla template exposes invoke via window.__TAURI__.core
const { invoke } = window.__TAURI__.core;

const $ = (sel) => document.querySelector(sel);
const logEl = $("#log");

function logLine(s) {
  logEl.textContent += (typeof s === "string" ? s : JSON.stringify(s)) + "\n";
  logEl.scrollTop = logEl.scrollHeight;
}

async function call(method, params = {}) {
  // mesh_action is a Rust command that forwards to the Python bridge
  return await invoke("mesh_action", { method, params });
}

function onlyHex(s) {
  return (s || "").toLowerCase().replace(/[^0-9a-f]/g, "");
}

window.addEventListener("DOMContentLoaded", () => {
  $("#btnDoctor").addEventListener("click", async () => {
    try {
      const r = await invoke("doctor");
      logLine(`[doctor] ${r}`);
    } catch (e) {
      logLine(`[doctor][ERR] ${e}`);
    }
  });

  $("#btnCreate").addEventListener("click", async () => {
    try {
      const r = await call("create_network", {});
      logLine(["[create_network]", r]);
    } catch (e) {
      logLine(["[create_network][ERR]", String(e)]);
    }
  });

  $("#btnAttach").addEventListener("click", async () => {
    try {
      const r = await call("attach", {}); // token is auto-loaded in Python if omitted
      logLine(["[attach]", r]);
    } catch (e) {
      logLine(["[attach][ERR]", String(e)]);
    }
  });

  $("#btnScan").addEventListener("click", async () => {
    const secs = Number($("#secs").value || "15");
    try {
      const r = await call("scan_start", { seconds: secs });
      logLine(["[scan_start]", r]);
    } catch (e) {
      logLine(["[scan_start][ERR]", String(e)]);
    }
  });

  $("#btnProvision").addEventListener("click", async () => {
    const hex = onlyHex($("#uuidHex").value);
    if (hex.length !== 32) {
      logLine("[provision][ERR] UUID must be 32 hex chars (no 0x, no dashes)");
      return;
    }
    try {
      const r = await call("provision_uuid", { uuid_hex: hex });
      logLine(["[provision_uuid]", r]);
    } catch (e) {
      logLine(["[provision_uuid][ERR]", String(e)]);
    }
  });

  $("#btnReset").addEventListener("click", async () => {
    const unicast = onlyHex($("#unicast").value);
    if (!unicast) {
      logLine("[reset][ERR] provide unicast address (hex)");
      return;
    }
    try {
      const r = await call("reset_node", { unicast });
      logLine(["[reset_node]", r]);
    } catch (e) {
      logLine(["[reset_node][ERR]", String(e)]);
    }
  });

  $("#btnLeave").addEventListener("click", async () => {
    try {
      const r = await call("leave", { deep: false });
      logLine(["[leave]", r]);
    } catch (e) {
      logLine(["[leave][ERR]", String(e)]);
    }
  });

  $("#btnPurge").addEventListener("click", async () => {
    try {
      const r = await call("purge", {});
      logLine(["[purge]", r]);
    } catch (e) {
      logLine(["[purge][ERR]", String(e)]);
    }
  });

  $("#btnPollLogs").addEventListener("click", async () => {
    try {
      const r = await call("poll_logs", {});
      // r is { ok, data: [lines] } from Python bridge
      const lines = (r && r.data) || [];
      lines.forEach((ln) => logLine(ln));
    } catch (e) {
      logLine(["[poll_logs][ERR]", String(e)]);
    }
  });

  // Auto-poll logs every 1s
  setInterval(async () => {
    try {
      const r = await call("poll_logs", {});
      const lines = (r && r.data) || [];
      lines.forEach((ln) => logLine(ln));
    } catch (_) {
      /* ignore */
    }
  }, 1000);
});

