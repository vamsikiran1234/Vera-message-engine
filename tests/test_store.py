import unittest

from vera_engine.models import ContextEnvelope
from vera_engine.store import ContextStore, ConversationStore, SuppressionStore


class StoreTests(unittest.TestCase):
    def test_higher_context_version_replaces_previous_payload(self):
        store = ContextStore()
        first = ContextEnvelope("merchant", "m_1", 1, {"value": 1}, "t1")
        newer = ContextEnvelope("merchant", "m_1", 2, {"value": 2}, "t2")

        self.assertEqual(store.put(first), (True, 1))
        self.assertEqual(store.put(newer), (True, 2))
        self.assertEqual(store.payload("merchant", "m_1"), {"value": 2})

    def test_equal_or_lower_version_is_rejected(self):
        store = ContextStore()
        store.put(ContextEnvelope("category", "dentists", 3, {}, "t3"))

        self.assertEqual(store.put(ContextEnvelope("category", "dentists", 3, {}, "t3")), (False, 3))
        self.assertEqual(store.put(ContextEnvelope("category", "dentists", 2, {}, "t2")), (False, 3))

    def test_counts_and_conversation_state(self):
        contexts = ContextStore()
        contexts.put(ContextEnvelope("merchant", "m_1", 1, {}, "t"))
        contexts.put(ContextEnvelope("customer", "c_1", 1, {}, "t"))
        self.assertEqual(contexts.counts(), {"category": 0, "merchant": 1, "customer": 1, "trigger": 0})

        conversations = ConversationStore()
        state = conversations.get_or_create("conv_1", "m_1")
        conversations.add_turn("conv_1", {"from": "merchant", "body": "Yes"})
        self.assertEqual(state.merchant_id, "m_1")
        self.assertEqual(len(state.turns), 1)

    def test_suppression_tracks_keys_and_conversations(self):
        store = SuppressionStore()
        store.add("trigger:one")
        store.suppress_conversation("conv_1")

        self.assertTrue(store.contains("trigger:one"))
        self.assertTrue(store.conversation_suppressed("conv_1"))
        self.assertFalse(store.contains("trigger:two"))


if __name__ == "__main__":
    unittest.main()