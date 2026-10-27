"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

type StoredChunks = {
  config: { chunk_size: number; chunk_overlap: number; strategy: string; unit: string } | null;
  total_chunks: number; snapshot_matches: boolean | null; order_known: boolean;
  chunks: { content: string; metadata: Record<string, unknown> }[];
};
export function DocumentChunksButton({ knowledgeBaseId, documentId, fileName }: { knowledgeBaseId: number; documentId: number; fileName: string }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<StoredChunks | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true); setError("");
    api.get(`/api/knowledge-base/${knowledgeBaseId}/documents/${documentId}/chunks`)
      .then((result) => { if (active) setData(result); })
      .catch(() => { if (active) setError("片段读取失败，请关闭后重试。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, knowledgeBaseId, documentId]);
  return <Dialog open={open} onOpenChange={setOpen}>
    <DialogTrigger asChild><button className="text-sm text-primary underline underline-offset-4" aria-label={`查看 ${fileName} 的入库片段`}>查看片段</button></DialogTrigger>
    <DialogContent className="flex max-h-[85dvh] max-w-3xl flex-col">
      <DialogHeader><DialogTitle className="break-all pr-6">{fileName}</DialogTitle><DialogDescription>查看实际入库文本与来源，不会重新解析原文件。</DialogDescription></DialogHeader>
      <div className="min-h-0 space-y-3 overflow-y-auto text-sm">
        {loading ? <p role="status">正在读取…</p> : error ? <p role="alert" className="text-destructive">{error}</p> : data && <>
          <p>实际入库 {data.total_chunks} 个片段</p>
          <p className="text-muted-foreground">{data.config ? `递归切分 · 长度 ${data.config.chunk_size} 字符 · 重叠 ${data.config.chunk_overlap} 字符` : "旧文档未记录分块配置，配置未知。"}</p>
          {data.snapshot_matches === true && <p className="text-green-700">内容、顺序及来源与已确认预览快照一致。</p>}
          {data.snapshot_matches === false && <p role="alert" className="text-destructive">入库内容与预览快照不一致，请检查数据。</p>}
          {!data.order_known && <p className="text-amber-700">旧文档未记录原始片段顺序，以下仅按存储记录展示。</p>}
          {data.chunks.map((chunk, index) => <article key={index} className="rounded-lg border p-3"><p className="mb-2 text-xs text-muted-foreground">{data.order_known ? "片段" : "记录"} {index + 1} · {Array.from(chunk.content).length} 字符 · {String(chunk.metadata.source || fileName)}{chunk.metadata.page !== undefined ? ` · 第 ${Number(chunk.metadata.page) + 1} 页` : ""}</p><pre className="whitespace-pre-wrap break-words leading-relaxed">{chunk.content}</pre></article>)}
          {!data.chunks.length && <p>没有可展示的片段记录。</p>}
        </>}
      </div>
    </DialogContent>
  </Dialog>;
}
