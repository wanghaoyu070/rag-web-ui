import tempfile
import unittest
from pathlib import Path
from pydantic import ValidationError
from app.schemas.knowledge import ChunkConfig, LabCompareRequest
from app.services.chunking import split_text, heading_sections, chunk_statistics, load_and_split


class ChunkLabTests(unittest.TestCase):
    def test_fixed_ranges_are_exact_and_overlap_is_measured_not_configured(self):
        chunks = split_text("abcdefghij", "a.txt", ChunkConfig(strategy="fixed", chunk_size=6, chunk_overlap=2))
        self.assertEqual([c.page_content for c in chunks], ["abcdef", "efghij"])
        self.assertEqual([(c.metadata["start_index"], c.metadata["end_index"]) for c in chunks], [(0, 6), (4, 10)])
        self.assertAlmostEqual(chunk_statistics(chunks)["overlap_ratio"], 2 / 12, places=4)

    def test_heading_boundaries_preserve_code_fences_and_hierarchy(self):
        text = "开场\n# 章一\n内容\n```md\n## 代码标题\n```\n## 子节\n说明\n# 章二\n末尾"
        sections = heading_sections(text)
        self.assertEqual([p for _, _, p in sections], ["", "章一", "章一 / 子节", "章二"])
        chunks = split_text(text, "a.md", ChunkConfig(strategy="heading", chunk_size=100, chunk_overlap=10))
        self.assertEqual(len(chunks), 4)
        self.assertIn("## 代码标题", chunks[1].page_content)
        self.assertEqual(chunk_statistics(chunks)["overlap_ratio"], 0)
        for chunk in chunks:
            self.assertEqual(text[chunk.metadata["start_index"]:chunk.metadata["end_index"]], chunk.page_content)

    def test_all_strategies_match_unicode_source_and_repeated_text(self):
        text = "# 标题😀\n\n" + ("重复段落甲乙丙丁😀。\n\n" * 30) + "## 次标题\n结束。"
        for strategy in ("fixed", "recursive", "heading"):
            chunks = split_text(text, "unicode.md", ChunkConfig(strategy=strategy, chunk_size=53, chunk_overlap=9))
            with self.subTest(strategy=strategy):
                for chunk in chunks:
                    self.assertEqual(text[chunk.metadata["start_index"]:chunk.metadata["end_index"]], chunk.page_content)
                    self.assertLessEqual(len(chunk.page_content), 53)
                self.assertTrue(0 <= chunk_statistics(chunks)["overlap_ratio"] < 1)

    def test_txt_without_heading_matches_recursive_and_markdown_preserves_format(self):
        text = "  序言\n\n# 标题\n\n    缩进与空白保留\n\n内容 " * 5
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "a.md"
            path.write_text(text.replace("\n", "\r\n"), encoding="utf-8")
            for strategy in ("fixed", "recursive", "heading"):
                config = ChunkConfig(strategy=strategy, chunk_size=80, chunk_overlap=10)
                self.assertEqual(load_and_split(str(path), "a.md", config), split_text(text, "a.md", config))
        plain = "没有标题的段落。" * 50
        heading = split_text(plain, "a.txt", ChunkConfig(strategy="heading"))
        recursive = split_text(plain, "a.txt", ChunkConfig())
        self.assertEqual([c.page_content for c in heading], [c.page_content for c in recursive])

    def test_request_rejects_ambiguous_source_duplicate_and_unknown_strategy(self):
        configs = [{"strategy": "fixed"}, {"strategy": "recursive"}]
        for params in [{"configs": configs}, {"configs": configs, "upload_id": 1, "document_id": 2},
                       {"configs": [{"strategy": "fixed"}] * 2, "upload_id": 1},
                       {"configs": [{"strategy": "unknown"}, {"strategy": "recursive"}], "upload_id": 1}]:
            with self.assertRaises(ValidationError):
                LabCompareRequest(**params)
        self.assertEqual(len(LabCompareRequest(document_id=1, configs=configs).configs), 2)
