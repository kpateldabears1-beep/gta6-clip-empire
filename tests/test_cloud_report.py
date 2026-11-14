import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import cloud_report


class CloudReportTests(unittest.TestCase):
    def test_unavailable_feed_does_not_erase_prior_view_counts(self):
        db = MagicMock()
        with patch.object(cloud_report, "urlopen", side_effect=HTTPError("url",404,"missing",{},None)):
            lines = cloud_report.view_report(db, "UC"+"a"*22, datetime.now(timezone.utc))
        self.assertIn("unavailable", lines[0])
        db.pipeline.assert_not_called()

    def test_view_changes_ignore_expired_entries_and_baseline_new_uploads(self):
        channel = "UC" + "a"*22
        feed = ('<feed><channelId>' + channel[2:] + '</channelId>' +
                ''.join(f'<entry><videoId>{vid}</videoId><group><community><statistics views="{count}"/>'
                        '</community></group></entry>' for vid, count in [('oldoldold12', 14), ('newnewnew12', 100)]) +
                '</feed>')
        db = MagicMock()
        db.get.return_value = json.dumps({'at': 'previous snapshot', 'views': {'oldoldold12': 10, 'gonegone123': 70}})
        with patch.object(cloud_report, 'urlopen', return_value=io.BytesIO(feed.encode())):
            lines = cloud_report.view_report(db, channel, datetime.now(timezone.utc))
        self.assertIn('+4 since prior check', lines[-2])
        self.assertIn('first observation', lines[-1])
        self.assertEqual(db.pipeline.return_value.__enter__.return_value.set.call_count, 2)
