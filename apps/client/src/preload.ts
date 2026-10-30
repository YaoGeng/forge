// contextIsolation 桥：renderer 仅见 forge 白名单 API（无 Node 能力泄漏）。
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("forge", {
  appInfo: () => ipcRenderer.invoke("forge:app-info"),
  openStore: () => ipcRenderer.invoke("forge:open-store"),
  quitAndInstall: () => ipcRenderer.invoke("forge:quit-and-install"),
  onUpdaterLog: (cb: (line: string) => void) => {
    ipcRenderer.on("updater-log", (_e, line: string) => cb(line));
  },
});
