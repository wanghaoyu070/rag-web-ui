"use client";

import Link from "next/link";
import styles from "./lab.module.css";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ChevronDown, FileText, Loader2, SlidersHorizontal } from "lucide-react";
import DashboardLayout from "@/components/layout/dashboard-layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";

type Strategy = "fixed" | "recursive" | "heading";
const strategies: { id: Strategy; name: string; description: string }[] = [
  { id: "fixed", name: "Fixed-size Character", description: "按固定长度滑动窗口切分，便于观察句子被截断的位置。" },
  { id: "recursive", name: "Recursive Character", description: "依次尝试段落、换行、空格和字符边界，在长度限制内保留上下文。" },
  { id: "heading", name: "Heading-based", description: "先按 # 至 ###### 标题分节，过长章节再递归切分；围栏代码中的 # 不作为标题，无标题时与递归策略相同。" },
];
const nameOf = (id: Strategy) => strategies.find((s) => s.id === id)!.name;
type Config = { strategy: Strategy; chunk_size: number; chunk_overlap: number };
type Chunk = { content: string; metadata: { start_index: number; end_index: number; heading_path?: string } };
type Result = { config: Config; statistics: { count: number; average_length: number; min_length: number; max_length: number; overlap_ratio: number }; chunks: Chunk[]; preview_id: string | null; expires_at: string | null };
type Comparison = { file_name: string; source_text: string; results: Result[]; can_ingest: boolean };
type Source = { id: number; file_name: string };
type Task = { task_id: number; status: string; chunk_count?: number; error_message?: string };
const initialParams = { fixed: { size: "500", overlap: "50" }, recursive: { size: "500", overlap: "50" }, heading: { size: "500", overlap: "50" } };

export default function ChunkLabPage() {
  const kb = Number(useParams().id);
  const [documents, setDocuments] = useState<Source[]>([]);
  const [source, setSource] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploadId, setUploadId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Strategy[]>(["fixed", "recursive", "heading"]);
  const [params, setParams] = useState(initialParams);
  const [individual, setIndividual] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [data, setData] = useState<Comparison | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [left, setLeft] = useState<Strategy>("fixed"), [right, setRight] = useState<Strategy>("recursive");
  const [mobileSide, setMobileSide] = useState(0);
  const [range, setRange] = useState<{ start: number; end: number; strategy: Strategy; index: number } | null>(null);
  const [showOverlap, setShowOverlap] = useState(false);
  const [originalOpen, setOriginalOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [choice, setChoice] = useState<Strategy>("recursive");
  const [task, setTask] = useState<Task | null>(null);
  const alive = useRef(true);
  const originalMark = useRef<HTMLElement>(null);
  const panels = useRef<(HTMLDivElement | null)[]>([]);
  useEffect(() => {
    alive.current = true;
    api.get(`/api/knowledge-base/${kb}`).then((r) => {
      if (!alive.current) return;
      const supported = r.documents.filter((d: Source) => /\.(txt|md)$/i.test(d.file_name));
      setDocuments(supported); setSource(supported.length ? String(supported[0].id) : "local");
    }).catch(() => { if (alive.current) setError("无法读取知识库，请返回后重试。"); });
    return () => { alive.current = false; };
  }, [kb]);
  useEffect(() => {
    if (!range) return;
    const selectedSide = [left, right].indexOf(range.strategy);
    if (selectedSide < 0) return;
    const panel = panels.current[1 - selectedSide];
    const target = panel?.querySelector<HTMLElement>('[data-corresponding="true"]');
    if (!panel || !target || panel.clientHeight === 0) return;
    const viewport = panel.getBoundingClientRect();
    const bounds = target.getBoundingClientRect();
    if (bounds.top < viewport.top || bounds.bottom > viewport.bottom) {
      panel.scrollTop += bounds.top - viewport.top - 12;
    }
  }, [range, left, right]);
  useEffect(() => { if (originalOpen) originalMark.current?.scrollIntoView({ block: "center" }); }, [originalOpen]);

  const configs: Config[] = selected.map((strategy) => ({ strategy, chunk_size: Number(params[individual ? strategy : "recursive"].size), chunk_overlap: Number(params[individual ? strategy : "recursive"].overlap) }));
  const valid = configs.every((c) => { const p = params[individual ? c.strategy : "recursive"]; return p.size !== "" && p.overlap !== "" && Number.isInteger(c.chunk_size) && c.chunk_size >= 1 && c.chunk_size <= 20000 && Number.isInteger(c.chunk_overlap) && c.chunk_overlap >= 0 && c.chunk_overlap < c.chunk_size; });
  const changed = () => { setDirty(true); setError(""); setTask(null); };
  const resetSource = () => { setData(null); setUploadId(null); setTask(null); setRange(null); setError(""); setDirty(false); };
  const resultFor = (strategy: Strategy) => data?.results.find((r) => r.config.strategy === strategy);
  const fresh = !!data && !dirty;
  const chosen = resultFor(choice);
  const generate = async () => {
    if (!valid || selected.length < 2) return;
    setBusy(true); setError(""); setTask(null);
    try {
      let id = uploadId;
      if (source === "local" && !id) {
        if (!file) throw new Error("请先选择 TXT 或 Markdown 文档。");
        const form = new FormData(); form.append("files", file);
        const uploaded = (await api.post(`/api/knowledge-base/${kb}/documents/upload`, form))[0];
        if (!alive.current) return;
        if (uploaded.skip_processing) {
          const docId = uploaded.document_id;
          setDocuments((old) => old.some((d) => d.id === docId) ? old : [...old, { id: docId, file_name: file.name }]);
          setSource(String(docId));
          const result = await api.post(`/api/knowledge-base/${kb}/chunk-lab/compare`, { document_id: docId, configs });
          if (alive.current) accept(result);
          return;
        }
        id = uploaded.upload_id; setUploadId(id);
      }
      const result = await api.post(`/api/knowledge-base/${kb}/chunk-lab/compare`, { ...(source === "local" ? { upload_id: id } : { document_id: Number(source) }), configs });
      if (alive.current) accept(result);
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "生成失败，请重试。"); }
    finally { if (alive.current) setBusy(false); }
  };
  const accept = (result: Comparison) => {
    setData(result); setDirty(false); setRange(null);
    const ids = result.results.map((r) => r.config.strategy);
    setLeft(ids[0]); setRight(ids[1]); setChoice(ids.includes("recursive") ? "recursive" : ids[0]);
  };
  const ingest = async () => {
    if (!fresh || !chosen?.preview_id) return;
    setBusy(true); setError("");
    try {
      const response = await api.post(`/api/knowledge-base/${kb}/chunk-lab/process`, { preview_id: chosen.preview_id });
      if (!alive.current) return;
      const id = response.tasks[0].task_id;
      setConfirmOpen(false); setTask({ task_id: id, status: "pending" });
      while (alive.current) {
        const state = (await api.get(`/api/knowledge-base/${kb}/documents/tasks?task_ids=${id}`))[String(id)];
        if (!alive.current) return;
        setTask({ ...state, task_id: id });
        if (["completed", "failed"].includes(state.status)) break;
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "提交失败，请重试。"); }
    finally { if (alive.current) setBusy(false); }
  };
  const pickStrategy = (side: number, strategy: Strategy) => {
    if (side === 0) { if (strategy === right) setRight(left); setLeft(strategy); }
    else { if (strategy === left) setLeft(right); setRight(strategy); }
  };
  const isLocked = busy || task?.status === "completed";
  const renderChunkText = (result: Result, chunk: Chunk, index: number) => {
    if (!showOverlap || index === 0) return chunk.content;
    const previous = result.chunks[index - 1];
    const overlap = Math.max(0, Math.min(previous.metadata.end_index, chunk.metadata.end_index) - chunk.metadata.start_index);
    const chars = Array.from(chunk.content);
    return <>{overlap > 0 && <span className="border-b border-dashed border-neutral-500" title={`与前一片段重叠 ${overlap} 字符`}>{chars.slice(0, overlap).join("")}</span>}{chars.slice(overlap).join("")}</>;
  };

  return <DashboardLayout><div className={`${styles.surface} mx-auto max-w-6xl pb-12 text-neutral-950`}>
    <Link href={`/dashboard/knowledge/${kb}`} className="inline-flex items-center gap-2 text-sm text-neutral-500 hover:text-neutral-950"><ArrowLeft size={15} />返回知识库</Link>
    <header className="mb-9 mt-7"><p className="mb-2 text-xs font-medium tracking-[0.2em] text-neutral-400">CHUNKING LAB</p><h1 className="text-3xl font-semibold tracking-tight">Chunking Lab</h1><p className="mt-3 text-sm leading-6 text-neutral-500">同一份文档，不同的切分方式。先看差异，再选择适合的方案。</p></header>
    {error && <p role="alert" className="mb-5 rounded-xl border border-neutral-300 bg-neutral-50 px-4 py-3 text-sm">操作未完成：{error}</p>}
    <section className="rounded-2xl border border-neutral-200 bg-white p-5 sm:p-6" aria-label="实验设置">
      <div className="flex flex-wrap items-end gap-4"><div className="min-w-0 flex-1 space-y-2"><Label htmlFor="lab-source">实验文档</Label><select id="lab-source" disabled={isLocked || !source} value={source} onChange={(e) => { resetSource(); setSource(e.target.value); }} className="h-11 w-full rounded-lg border border-neutral-200 bg-neutral-50 px-3 text-sm"><option value="" disabled>正在读取文档…</option>{documents.map((d) => <option key={d.id} value={d.id}>{d.file_name}</option>)}<option value="local">上传新文档…</option></select></div>{source === "local" && <div className="min-w-0 flex-1 space-y-2"><Label htmlFor="lab-file">TXT / Markdown · 最大800KB</Label><Input id="lab-file" type="file" accept=".txt,.md" disabled={isLocked} className="h-11" onChange={(e) => { resetSource(); const f = e.target.files?.[0]; if (f && (!/\.(txt|md)$/i.test(f.name) || f.size > 800000)) { setFile(null); setError("请选择800KB以内的 TXT 或 Markdown 文档。"); } else setFile(f || null); }} /></div>}</div>
      <div className="mt-6"><p className="mb-3 text-sm font-medium">参与对比 <span className="ml-2 font-normal text-neutral-400">至少选择两种</span></p><div className="flex flex-wrap gap-2">{strategies.map((strategy) => <button key={strategy.id} type="button" aria-pressed={selected.includes(strategy.id)} disabled={isLocked} onClick={() => { changed(); setSelected((old) => old.includes(strategy.id) ? old.filter((id) => id !== strategy.id) : strategies.filter((s) => old.includes(s.id) || s.id === strategy.id).map((s) => s.id)); }} className={`rounded-full border px-4 py-2 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-neutral-700 disabled:opacity-50 ${selected.includes(strategy.id) ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-200 bg-white text-neutral-500 hover:border-neutral-400"}`}>{strategy.name}{selected.includes(strategy.id) && <span className="ml-2">✓</span>}</button>)}</div></div>
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-neutral-100 pt-5"><p className="text-xs text-neutral-500">{individual ? "各策略独立参数" : `Chunk Size ${params.recursive.size || "—"} · Overlap ${params.recursive.overlap || "—"} characters`}</p><button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)} className="inline-flex items-center gap-2 rounded p-1 text-sm text-neutral-600 hover:text-black"><SlidersHorizontal size={14} />调整参数<ChevronDown size={14} className={expanded ? "rotate-180" : ""} /></button></div>
      {expanded && <div className="mt-5 space-y-5 border-t border-neutral-100 pt-5"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={individual} disabled={isLocked} className="accent-neutral-900" onChange={(e) => { changed(); setIndividual(e.target.checked); }} />分别设置参数</label>{(individual ? selected : ["recursive" as Strategy]).map((strategy) => <div key={strategy} className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_1fr]">{individual && <p className="pb-2 text-sm">{nameOf(strategy)}</p>}<div className="space-y-2"><Label htmlFor={`size-${strategy}`}>Chunk Size (characters)</Label><Input id={`size-${strategy}`} type="number" min={1} max={20000} disabled={isLocked} value={params[strategy].size} onChange={(e) => { changed(); setParams((old) => ({ ...old, [strategy]: { ...old[strategy], size: e.target.value } })); }} /></div><div className="space-y-2"><Label htmlFor={`overlap-${strategy}`}>Chunk Overlap (characters)</Label><Input id={`overlap-${strategy}`} type="number" min={0} disabled={isLocked} value={params[strategy].overlap} onChange={(e) => { changed(); setParams((old) => ({ ...old, [strategy]: { ...old[strategy], overlap: e.target.value } })); }} /></div></div>)}<p className="text-xs leading-5 text-neutral-500">长度为1–20000的整数，重叠须小于长度。递归切分不保证达到设定重叠；标题策略仅在同一章节内重叠，章节之间不重叠。</p></div>}
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3"><p role="status" className="text-xs text-neutral-500">{!valid ? "请检查长度和重叠参数。" : selected.length < 2 ? "请至少选择两种策略。" : dirty && data ? "参数或策略已修改，下方为上次结果，请重新生成。" : source === "local" ? "实验不生成向量，选定方案后才正式入库。" : "已入库文档仅用于比较，不改动已有索引。"}</p><Button disabled={isLocked || !source || (source === "local" && !file) || !valid || selected.length < 2} onClick={generate} className="rounded-full bg-neutral-950 px-6 text-white hover:bg-neutral-800">{busy && !task && <Loader2 size={14} className="mr-2 animate-spin" />}{data ? "重新生成对比" : "生成对比"}</Button></div>
    </section>
    <details className="my-5 text-sm text-neutral-500"><summary className="w-fit cursor-pointer rounded py-1 focus-visible:outline">这三种策略有什么不同？</summary><div className="mt-3 grid gap-5 rounded-xl bg-neutral-50 p-5 sm:grid-cols-3">{strategies.map((s) => <div key={s.id}><h2 className="mb-2 font-medium text-neutral-900">{s.name}</h2><p className="text-xs leading-6">{s.description}</p></div>)}</div></details>
    {!data && <div className="flex min-h-64 flex-col items-center justify-center rounded-2xl border border-dashed border-neutral-200 px-5 text-center"><FileText className="mb-4 text-neutral-300" size={28} /><h2 className="font-medium">从一份文档开始</h2><p className="mt-2 max-w-md text-sm leading-6 text-neutral-500">生成后先比较片段数量与长度，再选两种策略细读同一段原文。片段越少，并不意味着检索越好。</p></div>}
    {data && <div className={dirty ? "opacity-65" : ""}>
      <section className="my-8" aria-label="策略概览"><div className="mb-4 flex items-baseline justify-between gap-4"><h2 className="text-lg font-semibold">策略概览</h2><span className="truncate text-xs text-neutral-400">{data.file_name}</span></div><div className="overflow-x-auto rounded-xl border border-neutral-200"><table className="w-full min-w-[600px] text-left text-sm"><thead className="bg-neutral-50 text-xs text-neutral-500"><tr>{["Strategy", "Chunks", "Avg. Length", "Length Range", "Actual Overlap", ""].map((title, i) => <th key={i} className="whitespace-nowrap px-4 py-3 font-normal">{title}</th>)}</tr></thead><tbody>{data.results.map((result) => <tr key={result.config.strategy} className="border-t border-neutral-100"><th className="px-4 py-4 font-medium">{nameOf(result.config.strategy)}</th><td className="px-4 tabular-nums">{result.statistics.count}</td><td className="px-4 tabular-nums">{result.statistics.average_length} characters</td><td className="px-4 tabular-nums">{result.statistics.min_length}–{result.statistics.max_length}</td><td className="px-4 tabular-nums">{(result.statistics.overlap_ratio * 100).toFixed(1)}%</td><td className="px-4"><button className="relative whitespace-nowrap text-xs underline underline-offset-4" onClick={() => { pickStrategy(1, result.config.strategy); setMobileSide(1); }}>在右侧查看<span className="sr-only">{nameOf(result.config.strategy)}</span></button></td></tr>)}</tbody></table></div><p className="mt-3 text-xs leading-5 text-neutral-400">实际重叠比例 = 重复覆盖的字符数 ÷ 所有片段总字符数。这些指标描述切分差异，不代表检索质量排名。</p></section>
      <section aria-label="双栏片段对比"><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold">细读片段</h2><div className="flex flex-wrap items-center gap-4 text-xs"><label className="flex items-center gap-2 text-neutral-600"><input type="checkbox" className="accent-neutral-900" checked={showOverlap} onChange={(e) => setShowOverlap(e.target.checked)} />显示 Overlap</label><button className="rounded text-neutral-600 underline underline-offset-4 disabled:opacity-40" disabled={!range} onClick={() => setOriginalOpen(true)}>查看对应原文</button></div></div><p className="mb-4 text-xs text-neutral-500">点击片段，另一栏会标出覆盖同一段原文的片段。两栏按原文位置关联。</p>
        <div className="mb-3 flex rounded-full bg-neutral-100 p-1 md:hidden" aria-label="移动端对比栏">{[left, right].map((id, index) => <button key={index} aria-pressed={mobileSide === index} className={`flex-1 rounded-full px-3 py-2 text-xs ${mobileSide === index ? "bg-white font-medium shadow-sm" : "text-neutral-500"}`} onClick={() => setMobileSide(index)}>{index === 0 ? "A" : "B"} · {nameOf(id)}</button>)}</div>
        <div className="grid gap-5 md:grid-cols-2">{[left, right].map((id, side) => { const result = resultFor(id)!; return <div key={side} className={`${mobileSide !== side ? "hidden md:block" : ""} min-w-0 overflow-hidden rounded-2xl border border-neutral-200 bg-white`}><div className="flex items-center gap-3 border-b border-neutral-100 p-4"><span className="text-xs text-neutral-400">{side === 0 ? "A" : "B"}</span><select aria-label={side === 0 ? "左侧策略" : "右侧策略"} value={id} onChange={(e) => pickStrategy(side, e.target.value as Strategy)} className="min-w-0 flex-1 bg-white text-sm font-medium">{data.results.map((r) => <option key={r.config.strategy} value={r.config.strategy}>{nameOf(r.config.strategy)}</option>)}</select><span className="text-xs tabular-nums text-neutral-400">{result.config.chunk_size} / {result.config.chunk_overlap}</span></div><div ref={(el) => { panels.current[side] = el; }} data-strategy={id} className="h-[480px] space-y-4 overflow-y-auto overscroll-contain bg-neutral-50/50 p-3">{result.chunks.map((chunk, index) => { const corresponding = !!range && chunk.metadata.start_index < range.end && chunk.metadata.end_index > range.start; const active = range?.strategy === id && range.index === index; return <button
                  key={index}
                  aria-pressed={active}
                  data-chunk-index={index}
                  data-corresponding={corresponding}
                  onClick={() => setRange({ start: chunk.metadata.start_index, end: chunk.metadata.end_index, strategy: id, index })}
                  className={`${styles.chunkCard} ${active ? styles.chunkSelected : corresponding ? styles.chunkCorresponding : ""}`}
                >
                  <div className={styles.chunkHeader}>
                    <span className="text-xs font-semibold tabular-nums text-neutral-800">Chunk {String(index + 1).padStart(2, "0")}</span>
                    <div className="flex flex-wrap items-center justify-end gap-2 text-[11px] text-neutral-500">
                      <span className="tabular-nums">{Array.from(chunk.content).length} characters</span>
                      {corresponding && <span className="rounded border border-neutral-300 bg-white px-2 py-0.5 font-medium text-neutral-800">{active ? "已选择" : "对应原文"}</span>}
                    </div>
                  </div>
                  <pre className={`${styles.chunkBody} whitespace-pre-wrap break-words font-sans text-sm leading-7 text-neutral-800`}>{renderChunkText(result, chunk, index)}</pre>
                  <div className={styles.chunkFooter}>
                    <p>Source: characters {chunk.metadata.start_index + 1}–{chunk.metadata.end_index}</p>
                    {chunk.metadata.heading_path && <p className="mt-1 break-words">{chunk.metadata.heading_path}</p>}
                  </div>
                </button>; })}</div></div>; })}</div>
      </section>
      <footer className="mt-7 flex flex-wrap items-center justify-between gap-4 border-t border-neutral-200 pt-6"><p className="max-w-lg text-xs leading-6 text-neutral-500">{data.can_ingest ? "确认后按所选快照向量化，片段文本与顺序保持一致。预览24小时有效。" : "这是已有文档的只读实验。若要采用新策略，请以新文件名上传，确认后作为新文档入库。"}</p>{data.can_ingest && <Button disabled={!fresh || isLocked} className="rounded-full bg-neutral-950 px-6 text-white hover:bg-neutral-800" onClick={() => setConfirmOpen(true)}>选择入库方案</Button>}</footer>
      {task && <section role="status" className="mt-5 rounded-xl border border-neutral-200 bg-neutral-50 p-5 text-sm"><h2 className="font-medium">{task.status === "completed" ? "入库完成" : task.status === "failed" ? "处理失败" : "正在向量化与校验…"}</h2><p className="mt-2 text-neutral-500">{nameOf(choice)} · 已确认 {chosen?.statistics.count} 块{task.chunk_count != null ? ` · 实际入库 ${task.chunk_count} 块` : ""}</p>{task.error_message && <p className="mt-2">{task.error_message}</p>}{task.status === "completed" ? <Link className="mt-4 inline-block underline underline-offset-4" href={`/dashboard/knowledge/${kb}`}>返回知识库，查看入库片段 →</Link> : task.status === "failed" ? <Button className="mt-3" variant="outline" disabled={busy || dirty} onClick={ingest}>重试此方案</Button> : <p className="mt-2 text-xs text-neutral-500">离开页面不会取消已提交任务，结果可在知识库查看。{!busy && <button className="ml-2 underline" onClick={ingest}>继续查询任务</button>}</p>}</section>}
    </div>}
    <Dialog open={originalOpen} onOpenChange={setOriginalOpen}><DialogContent className={`${styles.surface} max-w-3xl`}><DialogHeader><DialogTitle>对应原文</DialogTitle><DialogDescription>{data?.file_name} · 灰色区域为所选片段，字符位置按解析文本计算。</DialogDescription></DialogHeader><pre className="max-h-[60dvh] overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-neutral-50 p-5 font-sans text-sm leading-7 text-neutral-500">{data && range && <>{Array.from(data.source_text).slice(0, range.start).join("")}<mark ref={originalMark} className="bg-neutral-200 text-neutral-950">{Array.from(data.source_text).slice(range.start, range.end).join("")}</mark>{Array.from(data.source_text).slice(range.end).join("")}</>}</pre></DialogContent></Dialog>
    <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}><DialogContent className={`${styles.surface} max-w-md`}><DialogHeader><DialogTitle>选择入库方案</DialogTitle><DialogDescription>只将一个方案写入知识库，其他实验结果不会生成向量。</DialogDescription></DialogHeader><Label htmlFor="ingest-choice">使用策略</Label><select id="ingest-choice" disabled={busy} value={choice} onChange={(e) => setChoice(e.target.value as Strategy)} className="h-11 rounded-lg border border-neutral-200 bg-white px-3 text-sm">{data?.results.map((r) => <option key={r.config.strategy} value={r.config.strategy}>{nameOf(r.config.strategy)}</option>)}</select><div className="space-y-2 rounded-xl bg-neutral-50 p-4 text-sm"><p className="break-all font-medium">{data?.file_name}</p><p className="text-neutral-500">Chunk Size {chosen?.config.chunk_size} · Overlap {chosen?.config.chunk_overlap} characters</p><p>共 {chosen?.statistics.count} 个片段</p></div><Button disabled={busy || !fresh || !chosen?.preview_id || !!chosen.expires_at && Date.parse(chosen.expires_at) <= Date.now()} className="bg-neutral-950 text-white hover:bg-neutral-800" onClick={ingest}>{busy && <Loader2 size={14} className="mr-2 animate-spin" />}确认并入库</Button>{chosen?.expires_at && Date.parse(chosen.expires_at) <= Date.now() && <p className="text-sm">预览已过期，请关闭窗口并重新生成。</p>}</DialogContent></Dialog>
  </div></DashboardLayout>;
}
