"""
test_cross_session_isolation.py — Verification of strict session isolation for history and semantic cache.
"""

import unittest
from services.orchestrator.state_store import save_turn, load_history, clear_session
from services.orchestrator import cache_client

class TestCrossSessionIsolation(unittest.TestCase):
    def setUp(self):
        self.session_a = "session-test-abdul-kalam"
        self.session_b = "session-test-fresh-query"
        clear_session(self.session_a)
        clear_session(self.session_b)

    def tearDown(self):
        clear_session(self.session_a)
        clear_session(self.session_b)

    def test_session_history_isolation(self):
        # 1. Populate Session A with multi-turn discussion about Abdul Kalam
        save_turn(self.session_a, "1", "user", "who is Abdul Kalam")
        save_turn(self.session_a, "1", "assistant", "Abdul Kalam was the 11th President of India and a renowned space scientist.")
        save_turn(self.session_a, "2", "user", "tell me more about his space achievements")
        save_turn(self.session_a, "2", "assistant", "He directed India's SLV-III and missile development programs at ISRO and DRDO.")

        hist_a = load_history(self.session_a)
        self.assertEqual(len(hist_a), 4)

        # 2. Check Session B (new session ID) — must be completely empty!
        hist_b = load_history(self.session_b)
        self.assertEqual(len(hist_b), 0, "Session B history must be empty and isolated from Session A!")

        # 3. Add generic utterance to Session B
        save_turn(self.session_b, "1", "user", "wait")
        save_turn(self.session_b, "1", "assistant", "I am waiting. Take your time.")

        hist_b_after = load_history(self.session_b)
        self.assertEqual(len(hist_b_after), 2)
        # Ensure no Abdul Kalam content in Session B history
        for msg in hist_b_after:
            self.assertNotIn("kalam", msg["content"].lower(), "Session B must not contain foreign Abdul Kalam content!")

    def test_semantic_cache_isolation(self):
        query = "who is Abdul Kalam"
        sys_prompt = "You are a helpful assistant."
        model = "llama-3.3-70b"

        # 1. Store response in Session A cache
        cache_client.store(self.session_a, query, "Abdul Kalam was President of India", sys_prompt, model, [])

        # 2. Lookup in Session B (different session ID) for generic "wait" -> Must be a CACHE MISS!
        res_b = cache_client.lookup(self.session_b, "1", "wait", sys_prompt, model, [])
        self.assertIsNone(res_b, "Generic query 'wait' in Session B must not hit Session A's cache!")

        # 3. Lookup in Session B for exact query "who is Abdul Kalam" -> Must be a CACHE MISS (different session_id)!
        res_b_exact = cache_client.lookup(self.session_b, "1", query, sys_prompt, model, [])
        self.assertIsNone(res_b_exact, "Exact query in Session B must not hit Session A's cache due to strict session isolation!")

    def test_reused_session_id_cleanup(self):
        # Test session reuse after clear_session (e.g. user resets/reconnects)
        session_id = "session-reused-id"
        clear_session(session_id)

        save_turn(session_id, "1", "user", "who is Abdul Kalam")
        save_turn(session_id, "1", "assistant", "Abdul Kalam details...")
        cache_client.store(session_id, "who is Abdul Kalam", "Abdul Kalam details...", "sys", "model", [])

        # Clear session upon disconnect/reset
        clear_session(session_id)

        # New conversation starting with the same session_id
        hist = load_history(session_id)
        self.assertEqual(len(hist), 0, "Cleared session must have 0 history turns!")

        res_cached = cache_client.lookup(session_id, "1", "wait", "sys", "model", [])
        self.assertIsNone(res_cached, "Cleared session cache must not return stale response for generic queries!")

if __name__ == "__main__":
    unittest.main()
