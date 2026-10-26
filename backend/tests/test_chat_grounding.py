"""Exercise the real retrieval/streaming chain without calling an external model."""
import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from app.services.chat_service import generate_response
from app.services.llm.llm_factory import LLMFactory
from langchain_ollama import ChatOllama


class RecordingChatModel(BaseChatModel):
    calls: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "recording-test"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        return ChatResult(generations=[ChatGeneration(
            message=AIMessage(content="不能仅凭单一症状判断。[citation:2]")
        )])


class GroundingTests(unittest.IsolatedAsyncioTestCase):
    async def test_numbered_evidence_matches_stream_and_first_question_is_not_rewritten(self):
        # Nontrivial source IDs ensure citations use retrieval position, not database IDs.
        docs = [
            Document(page_content="早餐包括燕麦粥。", metadata={"document_id": 91}),
            Document(page_content="不能仅凭单一症状判断。", metadata={"document_id": 12}),
        ]
        store = MagicMock()
        store.as_retriever.return_value = RunnableLambda(lambda query: docs)
        db = MagicMock()
        db.query.return_value.filter.return_value.all.side_effect = [
            [SimpleNamespace(id=7)], [SimpleNamespace(id=12)]
        ]
        model = RecordingChatModel()
        question = "怕冷就能确定我的体质吗？"
        with patch("app.services.chat_service.EmbeddingsFactory.create"), \
             patch("app.services.chat_service.VectorStoreFactory.create", return_value=store), \
             patch("app.services.chat_service.LLMFactory.create", return_value=model):
            chunks = [chunk async for chunk in generate_response(
                question, {"messages": [{"role": "user", "content": question}]},
                [7], 100, db
            )]
        self.assertEqual(len(model.calls), 1, "First turn must not invoke a question rewrite")
        prompt = model.calls[0]
        self.assertEqual([m.content for m in prompt if m.type == "human"], [question])
        self.assertIn("[citation:1]\n早餐包括燕麦粥。", prompt[0].content)
        self.assertIn("[citation:2]\n不能仅凭单一症状判断。", prompt[0].content)
        payload = "".join(json.loads(c[2:]) for c in chunks if c.startswith("0:"))
        encoded, answer = payload.split("__LLM_RESPONSE__", 1)
        evidence = json.loads(base64.b64decode(encoded))["context"]
        self.assertEqual([d["metadata"]["document_id"] for d in evidence], [91, 12])
        self.assertEqual(answer, "不能仅凭单一症状判断。[citation:2]")
        self.assertNotIn("citation_index", docs[0].metadata)
        db.close.assert_called_once()

    def test_ollama_factory_uses_chat_roles(self):
        self.assertIsInstance(LLMFactory.create(provider="ollama"), ChatOllama)
