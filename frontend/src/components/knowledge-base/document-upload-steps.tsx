"use client";

import { useEffect, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, Upload, X } from "lucide-react";

type FileEntry = { file: File; uploadId?: number; existing?: boolean; documentId?: number };
type Chunk = { content: string; metadata: Record<string, unknown> };
type Preview = { preview_id: string; upload_id: number; file_name: string; total_chunks: number; chunks: Chunk[]; config: { chunk_size: number; chunk_overlap: number }; expires_at: string };
type Task = { upload_id: number; task_id?: number; document_id?: number; status: string; error_message?: string; chunk_count?: number };

export function DocumentUploadSteps({ knowledgeBaseId, onComplete }: { knowledgeBaseId: number; onComplete?: () => void }) {
  const [step, setStep] = useState(1);
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [size, setSize] = useState("1000");
  const [overlap, setOverlap] = useState("200");
  const [previews, setPreviews] = useState<Record<number, Preview>>({});
  const [selected, setSelected] = useState("");
  const [tasks, setTasks] = useState<Record<number, Task>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [invalidated, setInvalidated] = useState(false);
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);

  const chunkSize = Number(size), chunkOverlap = Number(overlap);
  const valid = size !== "" && overlap !== "" && Number.isInteger(chunkSize) && Number.isInteger(chunkOverlap) && chunkSize >= 1 && chunkSize <= 20000 && chunkOverlap >= 0 && chunkOverlap < chunkSize;
  const uploads = files.filter((f) => !f.existing && f.uploadId);
  const unfinished = uploads.filter((f) => tasks[f.uploadId!]?.status !== "completed");
  const ready = uploads.length > 0 && unfinished.every((f) => {
    const p = previews[f.uploadId!];
    return p && p.config.chunk_size === chunkSize && p.config.chunk_overlap === chunkOverlap && Date.parse(p.expires_at) > Date.now();
  });
  const total = uploads.reduce((sum, f) => sum + (previews[f.uploadId!]?.total_chunks || 0), 0);
  const complete = uploads.length > 0 && uploads.every((f) => tasks[f.uploadId!]?.status === "completed");
  const preview = previews[Number(selected)];

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    disabled: busy || step !== 1,
    maxFiles: 50,
    accept: { "application/pdf": [".pdf"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"], "text/plain": [".txt"], "text/markdown": [".md"] },
    onDrop: (accepted, rejected) => {
      setError(rejected.length ? "部分文件格式不支持，请选择 PDF、DOCX、Markdown 或 TXT。" : "");
      setFiles((previous) => {
        const names = new Set(previous.map((f) => f.file.name));
        return [...previous, ...accepted.filter((f) => { if (names.has(f.name)) return false; names.add(f.name); return true; }).map((file) => ({ file }))];
      });
    },
  });

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : "操作失败，请重试。");
  const changeConfig = (field: "size" | "overlap", value: string) => {
    field === "size" ? setSize(value) : setOverlap(value);
    setPreviews((old) => Object.fromEntries(Object.entries(old).filter(([id]) => tasks[Number(id)]?.status === "completed")));
    setInvalidated(true);
    setError("");
  };

  const uploadFiles = async () => {
    if (files.every((f) => f.uploadId || f.existing)) { setStep(2); return; }
    setBusy(true); setError("");
    try {
      const form = new FormData();
      files.filter((f) => !f.uploadId && !f.existing).forEach((f) => form.append("files", f.file));
      const result = await api.post(`/api/knowledge-base/${knowledgeBaseId}/documents/upload`, form);
      if (!active.current) return;
      setFiles((old) => old.map((f) => {
        const r = result.find((value: { file_name: string }) => value.file_name === f.file.name);
        return r ? { ...f, uploadId: r.upload_id, documentId: r.document_id, existing: r.skip_processing } : f;
      }));
      setStep(2);
    } catch (e) { if (active.current) fail(e); }
    finally { if (active.current) setBusy(false); }
  };

  const generatePreviews = async () => {
    if (!valid) return;
    setBusy(true); setError("");
    try {
      const result = await api.post(`/api/knowledge-base/${knowledgeBaseId}/documents/preview`, {
        upload_ids: unfinished.map((f) => f.uploadId), chunk_size: chunkSize, chunk_overlap: chunkOverlap,
      });
      if (!active.current) return;
      setPreviews((old) => ({ ...old, ...result }));
      setSelected(String(unfinished[0]?.uploadId || uploads[0]?.uploadId || ""));
      setInvalidated(false);
    } catch (e) { if (active.current) fail(e); }
    finally { if (active.current) setBusy(false); }
  };

  const process = async () => {
    if (!ready) { setError("预览已失效或过期，请重新生成预览。"); setStep(2); return; }
    setBusy(true); setError("");
    try {
      const result = await api.post(`/api/knowledge-base/${knowledgeBaseId}/documents/process`, { preview_ids: uploads.map((f) => previews[f.uploadId!].preview_id) });
      if (!active.current) return;
      setStep(3);
      setTasks(Object.fromEntries(result.tasks.map((task: { upload_id: number; task_id: number }) => [task.upload_id, { ...task, status: "pending" }])));
      const ids = result.tasks.map((task: { task_id: number }) => task.task_id);
      while (active.current) {
        const status: Record<string, Task> = await api.get(`/api/knowledge-base/${knowledgeBaseId}/documents/tasks?task_ids=${ids.join(",")}`);
        if (!active.current) return;
        const values = Object.values(status);
        setTasks(Object.fromEntries(values.map((task) => [task.upload_id, task])));
        if (values.length === ids.length && values.every((task) => ["completed", "failed"].includes(task.status))) break;
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    } catch (e) { if (active.current) fail(e); }
    finally { if (active.current) setBusy(false); }
  };

  return <div className="space-y-5">
    <ol className="flex gap-4 text-sm" aria-label="文档入库步骤">
      {["上传文件", "预览并确认", "入库结果"].map((label, index) => <li key={label} className={step === index + 1 ? "font-semibold text-foreground" : "text-muted-foreground"}>{index + 1}. {label}</li>)}
    </ol>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive break-words">{error}</p>}
    {step === 1 && <>
      <div {...getRootProps()} className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center ${isDragActive ? "bg-muted" : ""}`}>
        <input {...getInputProps()} aria-label="选择文档文件" />
        <Upload className="mx-auto mb-3 h-7 w-7 text-muted-foreground" /><p>点击选择文件，或拖拽到这里</p><p className="mt-2 text-xs text-muted-foreground">PDF、DOCX、Markdown、TXT · 单次最多 50 个文件 · 同名文件只选择一次</p>
      </div>
      <ul className="max-h-48 space-y-2 overflow-y-auto">{files.map((f) => <li key={f.file.name} className="flex items-center justify-between gap-3 rounded border p-2 text-sm"><span className="break-all">{f.file.name}</span><button aria-label={`移除 ${f.file.name}`} disabled={busy} onClick={() => setFiles((old) => old.filter((entry) => entry !== f))}><X className="h-4 w-4" /></button></li>)}</ul>
      {files.length > 50 && <p role="alert" className="text-destructive text-sm">一次最多处理 50 个文件，请移除多余文件。</p>}
      <Button className="w-full" disabled={busy || !files.length || files.length > 50} onClick={uploadFiles}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}上传文件并继续</Button>
    </>}
    {step === 2 && <>
      {files.filter((f) => f.existing).map((f) => <p key={f.file.name} className="rounded-lg bg-muted p-3 text-sm">{f.file.name} 已存在，未重新处理。当前参数不会应用到旧文档。</p>)}
      {!!uploads.length && <>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2"><Label htmlFor="chunk-size">片段长度（字符）</Label><Input id="chunk-size" type="number" min={1} max={20000} value={size} disabled={busy} onChange={(e) => changeConfig("size", e.target.value)} /></div>
          <div className="space-y-2"><Label htmlFor="chunk-overlap">重叠长度（字符）</Label><Input id="chunk-overlap" type="number" min={0} value={overlap} disabled={busy} onChange={(e) => changeConfig("overlap", e.target.value)} /></div>
        </div>
        <p className="text-xs text-muted-foreground">递归字符切分：优先保留段落。重叠用于衔接上下文，必须小于片段长度；字符数不等于 token 数。已完成入库的文件不会重新切分。</p>
        {!valid && <p role="alert" className="text-sm text-destructive">长度须为 1–20000 的整数；重叠须为非负整数且小于长度。</p>}
        {invalidated && <p role="status" className="text-sm text-amber-700">配置已变化，请重新生成所有待处理文件的预览。</p>}
        <Button disabled={busy || !valid || !unfinished.length} onClick={generatePreviews}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}为所有待处理文件生成预览</Button>
        <ul className="space-y-1 text-sm">{uploads.map((f) => <li key={f.uploadId} className="flex justify-between gap-3"><span className="break-all">{f.file.name}</span><span className="shrink-0 text-muted-foreground">{tasks[f.uploadId!]?.status === "completed" ? "已入库" : previews[f.uploadId!] ? `已预览 · ${previews[f.uploadId!].total_chunks} 块` : "未预览"}</span></li>)}</ul>
        {!!Object.keys(previews).length && <>
          <Label htmlFor="preview-document">查看文件预览</Label><select id="preview-document" className="w-full rounded border bg-background p-2 text-sm" value={selected} onChange={(e) => setSelected(e.target.value)}><option value="">选择文件</option>{uploads.filter((f) => previews[f.uploadId!]).map((f) => <option key={f.uploadId} value={f.uploadId}>{f.file.name}</option>)}</select>
          {preview && <div className="space-y-2"><p className="text-xs text-muted-foreground">{preview.total_chunks} 块 · {preview.config.chunk_size}/{preview.config.chunk_overlap} 字符 · 待处理预览有效至 {new Date(preview.expires_at).toLocaleString()}</p><div className="max-h-64 space-y-3 overflow-y-auto rounded-lg border p-3">{preview.chunks.map((chunk, index) => <article key={index} className="rounded bg-muted/50 p-3"><p className="mb-2 text-xs text-muted-foreground">片段 {index + 1} · {Array.from(chunk.content).length} 字符 · {String(chunk.metadata.source || preview.file_name)}{chunk.metadata.page !== undefined ? ` · 第 ${Number(chunk.metadata.page) + 1} 页` : ""}</p><pre className="whitespace-pre-wrap break-words text-sm leading-relaxed">{chunk.content}</pre></article>)}</div></div>}
        </>}
        <Button className="w-full" disabled={busy || !ready || complete} onClick={process}>确认并入库 · {uploads.length} 个文件 / 共 {total} 个片段</Button>
      </>}
      {!uploads.length && <Button className="w-full" onClick={onComplete}>完成 · 无需重复入库</Button>}
      <Button variant="ghost" disabled={busy || Object.keys(tasks).length > 0} onClick={() => setStep(1)}>返回上传</Button>
    </>}
    {step === 3 && <>
      <p className="text-sm text-muted-foreground">正式处理只使用已确认的预览快照，不重新切分文件。</p>
      <div className="max-h-80 space-y-3 overflow-y-auto">{uploads.map((f) => { const task = tasks[f.uploadId!]; return <div key={f.uploadId} className="rounded-lg border p-3 text-sm"><p className="break-all font-medium">{f.file.name}</p><p className="mt-1">{({ pending: "等待处理", processing: "正在向量化和校验", completed: "入库完成", failed: "处理失败，可重试" } as Record<string, string>)[task?.status] || "等待处理"}</p><p className="mt-1 text-xs text-muted-foreground">已确认 {previews[f.uploadId!]?.total_chunks} 块{task?.chunk_count != null ? ` · 实际入库 ${task.chunk_count} 块` : ""}</p>{task?.error_message && <p className="mt-2 text-destructive">{task.error_message}</p>}</div>; })}</div>
      {busy && <p role="status" className="flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin" />正在处理，关闭窗口不会取消已提交任务。</p>}
      {!busy && !complete && <div className="flex flex-wrap gap-3"><Button onClick={process}>重试未完成任务</Button><Button variant="outline" onClick={() => setStep(2)}>返回并重新预览</Button></div>}
      {complete && <><p className="text-sm text-green-700">所有文件已完成片段和向量校验。可在文档列表点击“查看片段”核对内容与配置。</p><Button className="w-full" onClick={onComplete}>完成并查看文档</Button></>}
    </>}
  </div>;
}
