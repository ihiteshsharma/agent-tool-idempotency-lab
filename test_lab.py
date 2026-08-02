import sqlite3
import tempfile
import unittest
from pathlib import Path

from tool_lab import IntentConflict, LostAfterCommit, create_ticket, demo, initialize


class ToolBoundaryIntegrationTest(unittest.TestCase):
    def test_demo_states_the_retry_conclusion(self):
        report = demo()
        self.assertEqual(report["verdict"], "passed")
        self.assertTrue(all(report["checks"].values()))
        self.assertIn("one durable side effect", report["conclusion"])

    def test_retries_replay_one_durable_side_effect_and_changed_intent_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "lab.db"
            initialize(db)
            payload = {
                "tenant_id": "acme",
                "idempotency_key": "run-42:create-ticket",
                "title": "Restore search index",
                "priority": "high",
            }

            created = create_ticket(db, payload)
            replayed = create_ticket(db, payload)
            self.assertEqual(created["ticket_id"], replayed["ticket_id"])
            self.assertEqual(replayed["disposition"], "replayed")

            with self.assertRaises(IntentConflict):
                create_ticket(db, {**payload, "title": "Delete search index"})

            lost = {**payload, "idempotency_key": "run-43:create-ticket"}
            with self.assertRaises(LostAfterCommit):
                create_ticket(db, lost, lose_result=True)
            recovered = create_ticket(db, lost)
            self.assertEqual(recovered["disposition"], "replayed")

            with sqlite3.connect(db) as conn:
                counts = conn.execute(
                    "SELECT (SELECT count(*) FROM operations),"
                    "       (SELECT count(*) FROM tickets)"
                ).fetchone()
            self.assertEqual(counts, (2, 2))


if __name__ == "__main__":
    unittest.main()
