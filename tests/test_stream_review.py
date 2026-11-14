import copy
import unittest
from stream_review import packet_digest, review_packets, validate_selection, validate_source


class StreamReviewTests(unittest.TestCase):
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

    def test_timing_and_story_requirements(self):
        for change in [dict(start=99), dict(end=901), dict(end=150), dict(end=float('nan')),
                       dict(start=True), dict(payoff=""), dict(hook="WOW")]:
            bad = copy.deepcopy(self.selection)
            bad['clips'][0].update(change)
            with self.assertRaises(ValueError): validate_selection(bad, self.packet)

    def test_age_permission_is_not_blanket_channel_permission(self):
        source = dict(channel_id="123", credit="creator", permission_url="https://example.org/policy",
                      uploaded_before="2025-11-13T00:00:00+00:00")
        info = dict(channel_id="123", timestamp=1500000000, duration=3600)
        self.assertEqual(validate_source(source, info), 3600)
        for change in [dict(channel_id="999"), dict(timestamp=1900000000), dict(timestamp=None), dict(is_live=True)]:
            with self.assertRaises(ValueError): validate_source(source, dict(info, **change))
