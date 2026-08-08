const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("danteDesktop", {
  appName: "Dante Multimodal Dashboard",
});
