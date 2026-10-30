# fake-feed 本地存证说明（docs/18 T4）

`forge-client-0.2.0-win.exe`（121,541,374 字节 ≈ 115.9MB）**不入库**：超 GitHub 单文件 100MB 硬限，会导致整仓 push 被拒。文件保留在本机此目录作证据，指纹如下（与 `latest.yml` 内 sha512 一致，updater 实际校验通过）：

- 文件：`forge-client-0.2.0-win.exe`
- 字节数：121,541,374
- sha512（base64，electron-updater 口径）：`kHSbiWmjCUOeagciDYwdK6UkwiZZCUvCF4w6dnTgJmqksPJZOuUUxbd7k77+v9pQ0TAWyeYeuqn0vJ3Sq6LaZg==`
- 生成方式：`electron-builder --win nsis` v0.2.0，见 `t4.1-updater.log` session B

复现：`pnpm -F client dist`（版本号改 0.2.0 后重打）。`latest.yml` 体积小，正常入库。
