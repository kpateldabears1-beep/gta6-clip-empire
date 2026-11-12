import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import main


@unittest.skipUnless(os.getenv("CLIPS_TEST_REDIS_URL"), "needs a test Redis instance")
class RedisTests(unittest.TestCase):
    def test_atomic_reservation_duplicate_and_daily_limit(self):
        import redis

        db = redis.Redis.from_url(os.environ["CLIPS_TEST_REDIS_URL"], decode_responses=True)
        prefix = "test:gta-clips:" + uuid4().hex
        ledger, day = prefix + ":clips", prefix + ":day"
        try:
            with patch.object(main, "LEDGER", ledger), patch.object(main, "day_key", return_value=day), \
                    patch.dict(os.environ, {"DAILY_POST_CAP": "1"}):
                self.assertTrue(main.reserve(db, ["one", "two"], "batch"))
                with self.assertRaisesRegex(RuntimeError, "reserved"):
                    main.reserve(db, ["two", "three"], "duplicate")
                self.assertFalse(main.reserve(db, ["three"], "over-limit"))
                self.assertEqual(db.hmget(ledger, ["one", "two", "three"]),
                                 ["pending:batch", "pending:batch", None])
                self.assertEqual(db.get(day), "1")
                self.assertGreater(db.ttl(day), 0)
        finally:
            db.delete(ledger, day)
