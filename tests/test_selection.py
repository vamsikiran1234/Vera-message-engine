import unittest

from vera_engine.candidates import CandidateAction
from vera_engine.models import MerchantContext
from vera_engine.scoring import ScoredCandidate
from vera_engine.selection import select_candidate, select_tick_actions
from vera_engine.store import ConversationStore, SuppressionStore


def scored(objective, primary_signal="signal", action_type="recommend"):
    return ScoredCandidate(
        candidate=CandidateAction(objective, action_type, "approve", primary_signal),
        score=0.5,
        components={},
    )


class SelectionTests(unittest.TestCase):
    def test_selects_first_ranked_candidate_and_suppresses_key(self):
        suppression = SuppressionStore()
        conversations = ConversationStore()
        merchant = MerchantContext.from_payload({"merchant_id": "m_1", "category_slug": "salons"})

        result = select_candidate(
            [scored("first"), scored("second", "other")],
            merchant,
            suppression,
            conversations,
            "conv_1",
        )

        self.assertIsNotNone(result.selected)
        self.assertTrue(suppression.contains("candidate:first:signal"))

    def test_duplicate_selection_is_suppressed(self):
        suppression = SuppressionStore()
        conversations = ConversationStore()
        merchant = MerchantContext.from_payload({"merchant_id": "m_1", "category_slug": "salons"})
        ranked = [scored("same")]

        first = select_candidate(ranked, merchant, suppression, conversations, "conv_1")
        second = select_candidate(ranked, merchant, suppression, conversations, "conv_2")

        self.assertIsNotNone(first.selected)
        self.assertIsNone(second.selected)
        self.assertEqual(second.reason, "all_candidates_suppressed")

    def test_tick_selection_caps_actions(self):
        suppression = SuppressionStore()
        conversations = ConversationStore()
        merchant = MerchantContext.from_payload({"merchant_id": "m_1", "category_slug": "salons"})
        ranked = [(f"trg_{index}", [scored(f"objective_{index}", f"signal_{index}")]) for index in range(3)]

        selected = select_tick_actions(ranked, {f"trg_{index}": merchant for index in range(3)}, suppression, conversations, limit=2)

        self.assertEqual(len(selected), 2)


if __name__ == "__main__":
    unittest.main()