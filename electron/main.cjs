const { app, BrowserWindow, Menu, dialog, shell, nativeTheme } = require("electron");
const { execFile } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const APP_NAME = "Dante Multimodal Dashboard";
const LAUNCH_LABEL = "com.vidigal.obsidian-dante-multimodal-rag";
const DASHBOARD_URL = process.env.DANTE_MULTIMODAL_DASHBOARD_URL || "http://127.0.0.1:5173/";
const BACKEND_URL = process.env.DANTE_MULTIMODAL_API_BASE_URL || "http://127.0.0.1:8035";
const STATIC_URL = process.env.DANTE_MULTIMODAL_STATIC_URL || `${BACKEND_URL}/`;
const LOG_DIR =
  process.env.DANTE_MULTIMODAL_LOG_DIR ||
  "/Users/vidigal/Obsidian_Dante_AI_RAG_DATA/smart-external-voyage-2048";
const ELECTRON_LOG_PATH =
  process.env.DANTE_MULTIMODAL_ELECTRON_LOG ||
  path.join(LOG_DIR, "dante-multimodal-dashboard.electron.log");
const ICON_PATH = path.join(__dirname, "assets", "DanteMultimodalDashboard.icns");

let mainWindow = null;
let loadingFallback = false;

app.setName(APP_NAME);
nativeTheme.themeSource = "dark";

function log(message, details = null) {
  const line = `[${new Date().toISOString()}] ${message}${
    details == null ? "" : ` ${typeof details === "string" ? details : JSON.stringify(details)}`
  }\n`;
  try {
    fs.mkdirSync(path.dirname(ELECTRON_LOG_PATH), { recursive: true });
    fs.appendFileSync(ELECTRON_LOG_PATH, line);
  } catch {
    // Logging must never prevent the app from opening.
  }
}

function execLaunchctl(args) {
  return new Promise((resolve) => {
    execFile("/bin/launchctl", args, { timeout: 15000 }, (error, stdout, stderr) => {
      resolve({
        ok: !error,
        stdout: stdout || "",
        stderr: stderr || "",
        code: error?.code ?? 0,
      });
    });
  });
}

function fetchText(url, { timeoutMs = 4500, method = "GET" } = {}) {
  return new Promise((resolve) => {
    const request = http.request(url, { method, timeout: timeoutMs }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        body += chunk;
      });
      response.on("end", () => {
        resolve({
          ok: response.statusCode >= 200 && response.statusCode < 300,
          status: response.statusCode || 0,
          body,
        });
      });
    });
    request.on("timeout", () => {
      request.destroy(new Error("timeout"));
    });
    request.on("error", (error) => {
      resolve({ ok: false, status: 0, body: error.message });
    });
    request.end();
  });
}

async function health() {
  log("health:start");
  const [backend, frontend, staticRoot] = await Promise.all([
    fetchText(`${BACKEND_URL}/api/stats`),
    fetchText(DASHBOARD_URL, { method: "GET" }),
    fetchText(STATIC_URL, { method: "GET" }),
  ]);

  let stats = null;
  if (backend.ok) {
    try {
      stats = JSON.parse(backend.body);
    } catch {
      stats = null;
    }
  }

  const result = {
    backend,
    frontend,
    staticRoot,
    stats,
    healthy: backend.ok && (frontend.ok || staticRoot.ok),
    loadUrl: frontend.ok ? DASHBOARD_URL : staticRoot.ok ? STATIC_URL : DASHBOARD_URL,
  };
  log("health:result", {
    backend: backend.status,
    frontend: frontend.status,
    staticRoot: staticRoot.status,
    healthy: result.healthy,
    loadUrl: result.loadUrl,
    total: stats?.total ?? null,
  });
  return result;
}

async function ensureServices() {
  let current = await health();
  if (current.healthy) {
    log("services:healthy");
    return current;
  }

  const bootstrap = await execLaunchctl([
    "bootstrap",
    `gui/${process.getuid()}`,
    `/Users/vidigal/Library/LaunchAgents/${LAUNCH_LABEL}.plist`,
  ]);
  log("services:bootstrap", { ok: bootstrap.ok, code: bootstrap.code, stderr: bootstrap.stderr.trim() });
  const kickstart = await execLaunchctl(["kickstart", "-k", `gui/${process.getuid()}/${LAUNCH_LABEL}`]);
  log("services:kickstart", { ok: kickstart.ok, code: kickstart.code, stderr: kickstart.stderr.trim() });

  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    current = await health();
    if (current.healthy) return current;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }

  return current;
}

async function logRendererSnapshot(reason) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  try {
    const snapshot = await mainWindow.webContents.executeJavaScript(
      `({
        reason: ${JSON.stringify(reason)},
        href: location.href,
        title: document.title,
        readyState: document.readyState,
        bodyText: document.body?.innerText?.slice(0, 300) || "",
        rootChildren: document.getElementById("root")?.childElementCount ?? null,
        background: getComputedStyle(document.body).backgroundColor,
      })`,
      true,
    );
    log("renderer:snapshot", snapshot);
  } catch (error) {
    log("renderer:snapshot:error", error.message);
  }
}

function fallbackHtml(state, title = "Dante dashboard is starting") {
  const backendStatus = state?.backend?.status || "offline";
  const frontendStatus = state?.frontend?.status || "offline";
  const escapedLogDir = LOG_DIR.replaceAll("&", "&amp;").replaceAll("<", "&lt;");
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${APP_NAME}</title>
  <style>
    body{margin:0;min-height:100vh;display:grid;place-items:center;background:#142109;color:#c7d2b0;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    main{max-width:640px;padding:36px;border:1px solid #47553b;border-radius:14px;background:linear-gradient(180deg,#233018,#1a1f0c);box-shadow:0 24px 80px -52px #000}
    h1{margin:0 0 8px;color:#effae7;font-size:24px}
    p{margin:8px 0;color:#a3a58c}
    code{color:#b6ffba}
    button{margin-top:18px;border:0;border-radius:9px;padding:10px 14px;background:#b6ffba;color:#16200a;font-weight:700}
  </style>
</head>
<body>
  <main>
    <h1>${title}</h1>
    <p>Backend status: <code>${backendStatus}</code></p>
    <p>Frontend status: <code>${frontendStatus}</code></p>
    <p>Logs: <code>${escapedLogDir}</code></p>
    <button onclick="location.reload()">Retry</button>
  </main>
</body>
</html>`;
}

async function createWindow() {
  log("window:create", { dashboardUrl: DASHBOARD_URL, backendUrl: BACKEND_URL });
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 980,
    minHeight: 680,
    title: APP_NAME,
    icon: ICON_PATH,
    backgroundColor: "#142109",
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
      webSecurity: true,
    },
  });
  log("window:created");

  // The bundle icon is set in Info.plist. Avoid changing the Dock icon at
  // runtime because some macOS/Electron builds can stall while decoding ICNS.
  log("window:bundle-icon", ICON_PATH);

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.webContents.on("did-start-loading", () => {
    log("webcontents:did-start-loading", mainWindow?.webContents.getURL() || "");
  });
  mainWindow.webContents.on("dom-ready", () => {
    log("webcontents:dom-ready", mainWindow?.webContents.getURL() || "");
    void logRendererSnapshot("dom-ready");
  });
  mainWindow.webContents.on("did-finish-load", () => {
    log("webcontents:did-finish-load", mainWindow?.webContents.getURL() || "");
    void logRendererSnapshot("did-finish-load");
  });
  mainWindow.webContents.on("did-navigate", (_event, url) => {
    log("webcontents:did-navigate", url);
  });
  mainWindow.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    log("renderer:console", { level, message, line, sourceId });
  });
  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    log("renderer:gone", details);
  });

  mainWindow.webContents.on("did-fail-load", async (_event, errorCode, errorDescription, validatedURL) => {
    log("webcontents:did-fail-load", { errorCode, errorDescription, validatedURL, loadingFallback });
    if (loadingFallback) return;
    const state = await ensureServices();
    if (state.healthy) {
      log("window:reload-after-fail", state.loadUrl);
      await mainWindow.loadURL(state.loadUrl);
    } else {
      loadingFallback = true;
      await mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(fallbackHtml(state, "Dante services are unavailable"))}`);
      loadingFallback = false;
    }
  });

  const state = await ensureServices();
  if (state.healthy) {
    log("window:load", state.loadUrl);
    await mainWindow.loadURL(state.loadUrl);
  } else {
    loadingFallback = true;
    log("window:load-fallback");
    await mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(fallbackHtml(state))}`);
    loadingFallback = false;
  }
}

async function showHealthDialog() {
  const state = await health();
  const statsText = state.stats
    ? `\nItems: ${state.stats.total}\nImages: ${state.stats.by_modality?.image ?? 0}\nText: ${state.stats.by_modality?.text ?? 0}`
    : "";
  await dialog.showMessageBox(mainWindow, {
    type: state.healthy ? "info" : "warning",
    title: "Dante Health",
    message: state.healthy ? "Dante dashboard is healthy." : "Dante dashboard is not fully healthy.",
    detail: `Backend: ${state.backend.status || "offline"}\nFrontend: ${state.frontend.status || "offline"}${statsText}`,
  });
}

async function restartServicesAndReload() {
  if (mainWindow) {
    await mainWindow.loadURL(
      `data:text/html;charset=utf-8,${encodeURIComponent(fallbackHtml(null, "Restarting Dante services"))}`,
    );
  }
  await execLaunchctl(["kickstart", "-k", `gui/${process.getuid()}/${LAUNCH_LABEL}`]);
  const state = await ensureServices();
  if (mainWindow) {
    await mainWindow.loadURL(
      state.healthy
        ? state.loadUrl
        : `data:text/html;charset=utf-8,${encodeURIComponent(fallbackHtml(state, "Dante services are unavailable"))}`,
    );
  }
}

function buildMenu() {
  const template = [
    {
      label: APP_NAME,
      submenu: [
        { role: "about" },
        { type: "separator" },
        {
          label: "Check Health",
          accelerator: "CommandOrControl+Shift+H",
          click: () => void showHealthDialog(),
        },
        {
          label: "Restart Dante Services",
          accelerator: "CommandOrControl+Shift+R",
          click: () => void restartServicesAndReload(),
        },
        {
          label: "Open Logs Folder",
          click: () => void shell.openPath(LOG_DIR),
        },
        {
          label: "Open in Chrome",
          click: () => void shell.openExternal(DASHBOARD_URL),
        },
        { type: "separator" },
        { role: "hide" },
        { role: "hideOthers" },
        { role: "unhide" },
        { type: "separator" },
        { role: "quit" },
      ],
    },
    {
      label: "Edit",
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        { role: "selectAll" },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "forceReload" },
        { type: "separator" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    {
      label: "Window",
      submenu: [{ role: "minimize" }, { role: "zoom" }, { role: "front" }],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

app.whenReady().then(async () => {
  log("app:ready");
  buildMenu();
  await createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) void createWindow();
  });
});

app.on("window-all-closed", () => {
  log("app:window-all-closed");
  if (process.platform !== "darwin") app.quit();
});
