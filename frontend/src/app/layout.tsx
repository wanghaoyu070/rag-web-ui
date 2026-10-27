import type { Metadata } from "next";
import "./globals.css";
import "highlight.js/styles/github.css";
// 如果使用 App Router
import { Toaster } from "@/components/ui/toaster";


export const metadata: Metadata = {
  icons: { icon: "/logo.svg" },
  title: "RAG Desk",
  description: "让你的文档成为可对话的知识库。支持本地模型、语义检索与来源引用。",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="font-sans antialiased">
        {children}
        <Toaster />
      </body>
    </html>
  );
}
