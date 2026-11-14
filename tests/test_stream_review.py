import copy
import unittest
from importlib.util import find_spec
from stream_review import packet_digest, review_packets, validate_selection, validate_source


class StreamReviewTests(unittest.TestCase):
    @unittest.skipUnless(find_spec("numpy"), "NumPy classifier trace test runs on the cloud worker")
    def test_classifier_trace_preserves_rejection_and_speech_resets(self):
        import numpy as np
        from unittest.mock import Mock
        from music_screen import MusicScreen, HOP
        screen = MusicScreen.__new__(MusicScreen)
        screen.spoken, screen.vocals, screen.music = [0], [1], 2
        screen.input, screen.output, screen.size, screen.shape = 0, 1, HOP, (HOP,)
        screen.model = Mock()
        samples = np.ones(17 * HOP, dtype=np.float32)
        for scores, rejected, decision in [([.01,.01,.95], True, "music"), ([.8,.01,.1], False, "speech")]:
            screen.model.get_tensor.return_value = np.array(scores)
            plain = screen.flagged_span(samples, [], [])
            trace = []
            traced = screen.flagged_span(samples, [], [], diagnostics=trace)
            self.assertEqual(plain, traced)
            self.assertEqual(bool(traced), rejected)
            self.assertEqual(len(trace), 17)
            self.assertTrue(all(row['decision'] == decision for row in trace))
        trace = []
        self.assertIsNone(screen.flagged_span(samples * 0, [], [], diagnostics=trace))
        self.assertTrue(all(row['decision'] == 'quiet' for row in trace))

    def setUp(self):
        self.packet = dict(source_id="test", packet_sha256="abc", start=100, end=900)
        self.packet["packet_sha256"] = packet_digest(self.packet)
        self.selection = dict(source_id="test", packet_sha256="abc", clips=[dict(
            start=105, end=130, title="The plane survives", hook="Can chat land it?",
            setup="Chat controls landing", payoff="Plane lands", why_interesting="Unexpected success")])
        self.selection["packet_sha256"] = self.packet["packet_sha256"]

    def test_window_boundaries_preserve_story_context(self):
        words = [(700, 710, "setup"), (725, 730, "payoff")]
        packets = review_packets(words, 0, 1500)
        self.assertEqual([(p['start'], p['end']) for p in packets], [(0,720),(676,1396),(1352,1500)])
        self.assertEqual(packets[1]['words'], words)

    def test_selection_rejects_wrong_source_stale_transcript_and_overlap(self):
        self.assertEqual(len(validate_selection(self.selection, self.packet)), 1)
        with self.assertRaises(ValueError):
            validate_selection(self.selection, dict(self.packet, end=1000))
        for key, value in [("source_id", "other"), ("packet_sha256", "stale")]:
            bad = dict(self.selection, **{key:value})
            with self.assertRaises(ValueError): validate_selection(bad, self.packet)
        bad = copy.deepcopy(self.selection)
        bad['clips'].append(dict(bad['clips'][0], start=120, end=150))
        with self.assertRaises(ValueError): validate_selection(bad, self.packet)

    def test_editor_can_reject_without_downloading_or_loading_models(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from stream_review import render_selection
        packet = dict(self.packet, source={"credit": "test"})
        packet["packet_sha256"] = packet_digest(packet)
        selection = dict(self.selection, packet_sha256=packet["packet_sha256"], clips=[])
        with self.assertRaises(ValueError): validate_selection(selection, packet)
        selection.update(decision="reject", reason="Only six seconds of story; the rest is filler")
        with TemporaryDirectory() as tmp, patch("stream_review.download") as download, patch("music_screen.MusicScreen") as model:
            render_selection(packet["source"], packet, selection, Path(tmp))
            download.assert_not_called()
            model.assert_not_called()
            self.assertEqual(json.loads((Path(tmp)/"rejected.json").read_text())["status"], "editorial_rejected")

    def test_timing_and_story_requirements(self):
        for change in [dict(start=99), dict(end=901), dict(end=150), dict(end=float('nan')),
                       dict(start=True), dict(payoff=""), dict(hook="WOW"), dict(captions="false")]:
            bad = copy.deepcopy(self.selection)
            bad['clips'][0].update(change)
            with self.assertRaises(ValueError): validate_selection(bad, self.packet)
        selected = copy.deepcopy(self.selection)
        selected['clips'][0]['captions'] = False
        self.assertEqual(len(validate_selection(selected, self.packet)), 1)

    def test_age_permission_is_not_blanket_channel_permission(self):
        source = dict(channel_id="123", credit="creator", permission_url="https://example.org/policy",
                      uploaded_before="2025-11-13T00:00:00+00:00")
        info = dict(channel_id="123", timestamp=1500000000, duration=3600)
        self.assertEqual(validate_source(source, info), 3600)
        for change in [dict(channel_id="999"), dict(timestamp=1900000000), dict(timestamp=None), dict(is_live=True)]:
            with self.assertRaises(ValueError): validate_source(source, dict(info, **change))
