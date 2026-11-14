import hashlib
from pathlib import Path
import tempfile
import unittest
from scripts.review_preview import verified_media


class PreviewQATests(unittest.TestCase):
    def test_review_binds_frames_to_exact_selected_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'preview-1.mp4'
            path.write_bytes(b'fixture')
            selection = {'clips': [{'start': 1, 'end': 22, 'title': 'A complete story'}]}
            row = dict(selection['clips'][0], file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(verified_media(root, row, selection), path)
            for change in ({'file':'../preview-1.mp4'}, {'sha256':'bad'}, {'start': 3}):
                with self.assertRaises(ValueError):
                    verified_media(root, dict(row, **change), selection)
            path.write_bytes(b'altered')
            with self.assertRaises(ValueError): verified_media(root, row, selection)
