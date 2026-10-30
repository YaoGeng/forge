// Forge 客户端主进程（docs/18 §6 T4）：v1 = 壳 + updater + 商店指引。
// 禁事项（MUST NOT）：不引 better-sqlite3 / Monaco / React Flow / 渲染层框架。
import { app, BrowserWindow, ipcMain, shell } from "electron";
import { autoUpdater } from "electron-updater";
import * as path from "node:path";

const STORE_URL = "https://forge.aim8848.com/store";
// E2 契约：生产 feed = backend `GET /api/v1/store/client/`（generic provider，
// latest.yml sha512 base64 口径）。FORGE_UPDATE_FEED 仅供本地假 feed 闭环。
const PROD_FEED = "https://forge.aim8848.com/api/v1/store/client/";

function feedUrl(): string {
  return process.env.FORGE_UPDATE_FEED || PROD_FEED;
}

let win: BrowserWindow | null = null;

/** 事件写 console（打包后经 --enable-logging 落 t4.1-updater.log）+ 推 UI 状态行。 */
function log(line: string): void {
  console.log(`[${new Date().toISOString()}] ${line}`);
  if (win && !win.isDestroyed()) win.webContents.send("updater-log", line);
}

function createWindow(): void {
  win = new BrowserWindow({
    width: 1280,
    height: 800,
    title: "Forge 客户端",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, "..", "renderer", "index.html"));
}

function setupUpdater(): void {
  const feed = feedUrl();
  autoUpdater.setFeedURL({ provider: "generic", url: feed });
  // 本地闭环验证退出时不得静默安装新版本；正式更新由用户点击「重启更新」触发。
  autoUpdater.autoInstallOnAppQuit = false;
  autoUpdater.autoDownload = true;
  autoUpdater.on("checking-for-update", () => log(`updater: checking-for-update (feed=${feed})`));
  autoUpdater.on("update-available", (i) => log(`updater: update-available ${i?.version ?? "?"}`));
  autoUpdater.on("update-not-available", (i) => log(`updater: update-not-available ${i?.version ?? "?"}`));
  autoUpdater.on("download-progress", (p) =>
    log(`updater: download-progress ${p.percent.toFixed(1)}% (${p.transferred}/${p.total})`),
  );
  autoUpdater.on("update-downloaded", (i) =>
    log(`updater: update-downloaded ${i?.version ?? "?"}（可重启安装）`),
  );
  autoUpdater.on("error", (e) => log(`updater: error ${String(e)}`));
}

app.whenReady().then(() => {
  createWindow();
  setupUpdater();
  ipcMain.handle("forge:app-info", () => ({ version: app.getVersion(), feed: feedUrl() }));
  ipcMain.handle("forge:open-store", () => shell.openExternal(STORE_URL));
  ipcMain.handle("forge:quit-and-install", () => {
    log("updater: quit-and-install（用户触发）");
    autoUpdater.quitAndInstall();
  });
  log(`app: 启动完成 version=${app.getVersion()} packaged=${app.isPackaged}`);
  // error 事件已记日志；catch 仅吞 promise 拒绝避免 UnhandledPromiseRejection。
  autoUpdater.checkForUpdates().catch(() => undefined);
});
app.on("window-all-closed", () => app.quit());
