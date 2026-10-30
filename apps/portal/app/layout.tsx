import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Forge · AI 自动化应用平台",
  description:
    "买之前，就知道它能不能跑。认证积木组装、认证流水线放行才配上架；实测通过率带样本量，健康分来自用户真实运行上报。",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
