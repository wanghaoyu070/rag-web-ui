"use client";

import { useEffect, useState } from "react";
import { Activity } from "lucide-react";
import { api } from "@/lib/api";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

type Trace = {
  status: string;
  stage: string;
  original_query: string;
  retrieval_query: string | null;
  rewrite_used: boolean;
  requested_knowledge_base_ids: number[];
  used_knowledge_base_id: number | null;
  top_k: number;
  score_type: string | null;
  evidence: { number: number; content: string; metadata: Record<string, unknown>; score: number }[];
  model: { provider: string; name: string } | null;
  model_inputs: Record<string, { role: string; content: unknown }[]>;
  timings_ms: Record<string, number>;
  answer: string;
  error: { type: string; message: string } | null;
  citation_check: { cited_numbers: number[]; invalid_numbers: number[]; missing_citations: boolean; unsupported_format: boolean } | null;
};

const statusLabels: Record<string, string> = { running: "执行中", completed: "已完成", failed: "失败", interrupted: "已中断" };
const stageLabels: Record<string, string> = { initialization: "初始化", rewrite: "问题改写", retrieval: "文档检索", generation: "回答生成", completed: "已完成" };

export function RagTracePanel({ chatId, messageId, disabled }: { chatId: string; messageId: string; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError("");
    api.get(`/api/chat/${chatId}/messages/${messageId}/trace`)
      .then((data) => { if (active) setTrace(data.trace); })
      .catch(() => { if (active) setError("无法读取过程记录，请关闭面板后重试。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, chatId, messageId]);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button disabled={disabled} className="mt-3 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground focus-visible:outline focus-visible:outline-2 disabled:opacity-40" title={disabled ? "回答结束后可查看" : "查看本次实际执行记录"}>
          <Activity className="h-3.5 w-3.5" />查看 RAG 过程
        </button>
      </DialogTrigger>
      <DialogContent className="left-auto right-0 top-0 flex h-[100dvh] w-full max-w-2xl translate-x-0 translate-y-0 flex-col gap-4 rounded-none sm:rounded-none">
        <DialogHeader className="pr-7">
          <DialogTitle>RAG 过程</DialogTitle>
          <DialogDescription>本次实际执行的数据与模型请求。检索分数不是答案可信度，也不代表模型内部思考。</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto pr-2 pb-8 text-sm">
          {loading ? <p role="status">正在读取执行记录…</p> : error ? <p role="alert" className="text-destructive">{error}</p> : !trace ? <div className="rounded-lg border p-4"><h3 className="font-medium">未采集执行记录</h3><p className="mt-2 text-muted-foreground">这条旧消息没有保存 RAG 过程。请发送新问题查看，不会为历史消息补造过程。</p></div> : <>
            <div className="rounded-lg border bg-muted/30 p-3">
              <p>{statusLabels[trace.status] || trace.status} · {trace.model ? `${trace.model.provider} / ${trace.model.name}` : "模型未初始化"}</p>
              <p className="mt-1 text-xs text-muted-foreground">总耗时 {trace.timings_ms.total ?? "未采集"} ms</p>
              {trace.error && <p className="mt-2 text-destructive">{stageLabels[trace.stage] || trace.stage}：{trace.error.message}（{trace.error.type}）</p>}
            </div>
            <section><h3 className="mb-2 font-semibold">1. 问题理解</h3>
              <p className="text-xs text-muted-foreground">用户原问题</p><p className="my-2 whitespace-pre-wrap break-words">{trace.original_query}</p>
              <p className="text-xs text-muted-foreground">实际检索问题 · {trace.rewrite_used ? (trace.retrieval_query === trace.original_query ? "已调用改写，结果未变" : "已根据历史改写") : "未调用改写"}</p>
              <p className="my-2 whitespace-pre-wrap break-words">{trace.retrieval_query ?? "检索尚未执行"}</p>
            </section>
            <section><h3 className="mb-2 font-semibold">2. 文档检索</h3>
              <p className="text-xs text-muted-foreground">请求知识库：{trace.requested_knowledge_base_ids.join(", ") || "无"} · 实际使用：{trace.used_knowledge_base_id ?? "无"} · Top-K {trace.top_k} · 返回 {trace.evidence.length} 段</p>
              <p className="my-2 text-xs text-muted-foreground">{trace.score_type ?? "分数未采集"}。当前未使用重排序。</p>
              {trace.evidence.map((item) => <details key={item.number} className="mb-2 rounded-lg border p-3"><summary className="cursor-pointer break-words">[{item.number}] {String(item.metadata.file_name || item.metadata.source || "未知来源")} <span className="text-xs text-muted-foreground">· {item.score.toFixed(4)}</span></summary><p className="mt-3 whitespace-pre-wrap break-words leading-relaxed">{item.content}</p></details>)}
              {!trace.evidence.length && <p className="mt-2 text-muted-foreground">没有采集到检索片段。</p>}
            </section>
            <section><h3 className="mb-2 font-semibold">3. 实际模型输入</h3>
              <p className="mb-2 text-xs text-muted-foreground">由模型调用回调采集，片段编号与检索顺序对应。这里只展示请求内容，不含 API Key。</p>
              {["rewrite", "answer"].filter((phase) => trace.model_inputs[phase]).map((phase) => { const messages = trace.model_inputs[phase]; return ( <details key={phase} className="mb-2 rounded-lg border p-3"><summary className="cursor-pointer">{phase === "rewrite" ? "问题改写请求" : "问答生成请求"} · {messages.length} 条消息</summary>{messages.map((message, i) => <div key={i} className="mt-3"><p className="mb-1 text-xs font-medium text-muted-foreground">{message.role}</p><pre className="whitespace-pre-wrap break-words rounded bg-muted/50 p-3 text-xs leading-relaxed">{typeof message.content === "string" ? message.content : JSON.stringify(message.content, null, 2)}</pre></div>)}</details>); })}
              {!Object.keys(trace.model_inputs).length && <p className="text-muted-foreground">模型尚未调用。</p>}
            </section>
            <section><h3 className="mb-2 font-semibold">4. 回答与引用检查</h3>
              <p className="whitespace-pre-wrap break-words rounded-lg border p-3">{trace.answer || "没有生成回答"}</p>
              {trace.citation_check && <div className="mt-2 space-y-1 text-xs"><p>已引用编号：{trace.citation_check.cited_numbers.join(", ") || "无"}</p>
                <p>越界编号：{trace.citation_check.invalid_numbers.join(", ") || "无"}</p>
                {trace.citation_check.missing_citations && <p className="text-amber-700">存在检索资料，但回答没有标准引用；是否确实需要引用仍需人工判断。</p>}
                {trace.citation_check.unsupported_format && <p className="text-amber-700">发现不支持的 context 引用格式。</p>}
                <p className="text-muted-foreground">引用是否支持结论：未自动验证，请展开原文核查。</p></div>}
            </section>
            <section><h3 className="mb-2 font-semibold">5. 阶段耗时</h3><div className="space-y-1 text-xs">{Object.entries(trace.timings_ms).map(([stage, ms]) => <p key={stage}>{({ rewrite: "问题改写", retrieval: "向量检索（含问题向量化）", answer: "回答生成", total: "总计" } as Record<string, string>)[stage] || stage}：{ms} ms</p>)}</div></section>
          </>}
        </div>
      </DialogContent>
    </Dialog>
  );
}
