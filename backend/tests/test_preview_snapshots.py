import hashlib
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from app.services.preview_ingestion import encode_snapshot, read_snapshot, vector_ids


class SnapshotTests(unittest.TestCase):
    def test_snapshot_hash_covers_order_text_and_metadata(self):
        chunks = [{"content": "同一段原文", "metadata": {"source": "a.txt", "page": 1}},
                  {"content": "同一段原文", "metadata": {"source": "a.txt", "page": 2}}]
        first = encode_snapshot({"chunks": chunks, "config": {"chunk_size": 300}})
        self.assertEqual(first, encode_snapshot({"config": {"chunk_size": 300}, "chunks": chunks}))
        self.assertNotEqual(first, encode_snapshot({"chunks": list(reversed(chunks)), "config": {"chunk_size": 300}}))
        ids = vector_ids("preview-one", 2)
        self.assertEqual(ids, vector_ids("preview-one", 2))
        self.assertNotEqual(ids[0], ids[1])
        self.assertNotEqual(ids, vector_ids("preview-two", 2))

    def test_corrupt_or_mismatched_snapshot_is_not_accepted(self):
        payload = {"file_hash": "abc", "version": "v1", "config": {"chunk_size": 300}, "chunks": [{"content": "原文", "metadata": {}}]}
        raw = encode_snapshot(payload)
        preview = SimpleNamespace(snapshot_path="test.json", snapshot_hash=hashlib.sha256(raw).hexdigest(), file_hash="abc", config={"chunk_size": 300}, processor_version="v1", chunk_count=1)
        client = MagicMock()
        client.get_object.return_value.read.return_value = raw
        self.assertEqual(read_snapshot(client, preview), payload)
        client.get_object.return_value.release_conn.assert_called_once()
        client.get_object.return_value.read.return_value = raw+b" "
        with self.assertRaisesRegex(ValueError, "完整性"):
            read_snapshot(client, preview)
        client.get_object.return_value.read.return_value = raw
        preview.chunk_count = 2
        with self.assertRaisesRegex(ValueError, "数量"):
            read_snapshot(client, preview)
