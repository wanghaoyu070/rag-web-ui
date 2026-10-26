"""Record execution evidence, never model credentials or inferred reasoning."""
import re
import time
from langchain_core.callbacks import BaseCallbackHandler


class RagTraceRecorder(BaseCallbackHandler):
    run_inline = True

    def __init__(self, query, knowledge_base_ids):
        self.started = time.perf_counter()
        self.model_starts = {}
        self.data = {
            "version": 1, "status": "running", "stage": "initialization",
            "original_query": query, "retrieval_query": None,
            "rewrite_used": False, "requested_knowledge_base_ids": knowledge_base_ids,
            "used_knowledge_base_id": None, "top_k": 4,
            "score_type": None, "evidence": [], "model": None,
            "model_inputs": {}, "timings_ms": {}, "answer": "",
            "citation_check": None, "error": None,
        }

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        phase = "answer" if "retrieval" in self.data["timings_ms"] else "rewrite"
        self.data["stage"] = "generation" if phase == "answer" else "rewrite"
        self.data["model_inputs"][phase] = [
            {"role": m.type, "content": m.content} for m in messages[0]
        ]
        self.model_starts[run_id] = (phase, time.perf_counter())

    def on_llm_end(self, response, *, run_id, **kwargs):
        self._end_model(run_id)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end_model(run_id)

    def _end_model(self, run_id):
        if run_id in self.model_starts:
            phase, started = self.model_starts.pop(run_id)
            self.data["timings_ms"][phase] = round((time.perf_counter() - started) * 1000, 1)

    def finish(self, answer, status="completed", error=None):
        self.data["answer"] = answer
        self.data["status"] = status
        self.data["error"] = error
        self.data["timings_ms"]["total"] = round((time.perf_counter() - self.started) * 1000, 1)
        numbers = [int(n) for n in re.findall(r"\[citation:(\d+)\]", answer)]
        count = len(self.data["evidence"])
        self.data["citation_check"] = {
            "cited_numbers": sorted(set(numbers)),
            "invalid_numbers": sorted({n for n in numbers if n < 1 or n > count}),
            "missing_citations": bool(answer.strip() and count and not numbers),
            "unsupported_format": bool(re.search(r"\[context:[^\]]+\]", answer)),
            "support_verified": False,
        }
        if status == "completed":
            self.data["stage"] = "completed"
