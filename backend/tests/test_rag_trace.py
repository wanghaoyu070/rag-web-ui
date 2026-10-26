import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from app.services.rag_trace import RagTraceRecorder
from app.services.chat_service import generate_response
from tests.test_chat_grounding import RecordingChatModel


class FailingModel(RecordingChatModel):
    def _generate(self, messages, **kwargs):
        raise RuntimeError("provider failed with sk-should-not-be-exposed")


class TraceTests(unittest.IsolatedAsyncioTestCase):
    def test_citation_bounds_do_not_claim_semantic_verification(self):
        recorder = RagTraceRecorder("问题", [7])
        recorder.data["evidence"] = [{"number": 1}, {"number": 2}]
        recorder.finish("答案[citation:0][citation:2][citation:9][context:1]")
        check = recorder.data["citation_check"]
        self.assertEqual(check["invalid_numbers"], [0, 9])
        self.assertTrue(check["unsupported_format"])
        self.assertFalse(check["support_verified"])

    async def test_failure_preserves_evidence_input_and_stage_without_provider_secret(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.side_effect = [
            [SimpleNamespace(id=7)], [SimpleNamespace(id=12)]
        ]
        store = MagicMock()
        store.similarity_search_with_score.return_value = [(Document(page_content="证据"), 0.2)]
        with patch("app.services.chat_service.EmbeddingsFactory.create"), \
             patch("app.services.chat_service.VectorStoreFactory.create", return_value=store), \
             patch("app.services.chat_service.LLMFactory.create", return_value=FailingModel()):
            chunks = [x async for x in generate_response("问题", {"messages": [{"role": "user", "content": "问题"}]}, [7], 100, db)]
        saved = [c.args[0] for c in db.add.call_args_list if getattr(c.args[0], "role", None) == "assistant"][-1]
        trace = saved.rag_trace
        self.assertEqual(trace["status"], "failed")
        self.assertEqual(trace["stage"], "generation")
        self.assertEqual(trace["evidence"][0]["content"], "证据")
        self.assertIn("answer", trace["model_inputs"])
        self.assertNotIn("sk-should-not-be-exposed", str(trace) + "".join(chunks))
        self.assertTrue(any(x.startswith("3:") for x in chunks))

    async def test_empty_knowledge_base_has_failed_trace_without_model_request(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        with patch("app.services.chat_service.EmbeddingsFactory.create"):
            chunks = [x async for x in generate_response("问题", {"messages": [{"role": "user", "content": "问题"}]}, [], 100, db)]
        saved = [c.args[0] for c in db.add.call_args_list if getattr(c.args[0], "role", None) == "assistant"][-1]
        self.assertEqual(saved.rag_trace["status"], "failed")
        self.assertEqual(saved.rag_trace["stage"], "retrieval")
        self.assertEqual(saved.rag_trace["model_inputs"], {})

    def test_startup_compares_database_revision_to_migration_scripts(self):
        from app.startup.migarate import DatabaseMigrator
        migrator = DatabaseMigrator("mysql+mysqlconnector://unused")
        with patch.object(migrator, "database_connection") as connection, \
             patch("app.startup.migarate.MigrationContext.configure") as context, \
             patch("app.startup.migarate.ScriptDirectory.from_config") as scripts:
            context.return_value.get_current_revision.return_value = "3580c0dcd005"
            scripts.return_value.get_heads.return_value = ["7c9e012ab345"]
            self.assertEqual(migrator.check_migration_needed(), (True, "3580c0dcd005", "7c9e012ab345"))
