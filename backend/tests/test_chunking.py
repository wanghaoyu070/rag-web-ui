import tempfile
import unittest
from pathlib import Path
from pydantic import ValidationError
from app.schemas.knowledge import ChunkConfig, PreviewRequest
from app.services.chunking import load_and_split


class ChunkingTests(unittest.TestCase):
    def test_invalid_parameters_are_rejected(self):
        for values in [{"chunk_size": 0}, {"chunk_overlap": -1}, {"chunk_size": 100, "chunk_overlap": 100}, {"chunk_size": None}, {"chunk_size": 2.5}]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ChunkConfig(**values)
        with self.assertRaises(ValidationError):
            PreviewRequest(upload_ids=[])

    def test_parsing_is_independent_of_temporary_path_and_uses_characters(self):
        text = "甲乙丙丁戊己庚辛壬癸" * 10
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory)/"a.txt", Path(directory)/"b.txt"
            a.write_text(text); b.write_text(text)
            config = ChunkConfig(chunk_size=30, chunk_overlap=5)
            first = load_and_split(str(a), "测试.txt", config)
            second = load_and_split(str(b), "测试.txt", config)
        self.assertGreater(len(first), 1)
        self.assertEqual(first, second)
        self.assertTrue(all(len(d.page_content) <= 30 for d in first))
        self.assertEqual(first[0].page_content[-5:], first[1].page_content[:5])
        self.assertEqual(first[0].metadata["source"], "测试.txt")

    def test_empty_document_has_actionable_error(self):
        with tempfile.NamedTemporaryFile(suffix=".txt") as file:
            with self.assertRaisesRegex(ValueError, "未提取到"):
                load_and_split(file.name, "empty.txt", ChunkConfig())
