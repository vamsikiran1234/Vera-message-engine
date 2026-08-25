import unittest

from vera_engine.candidates import CandidateAction
from vera_engine.models import CategoryContext, MerchantContext, TriggerContext
from vera_engine.scoring import rank_candidates
from vera_engine.signals import normalize_trigger


class ScoringTests(unittest.TestCase):
    def test_rank_is_deterministic_and_prefers_actionable_candidate(self):
        category = CategoryContext.from_payload({"slug": "restaurants", "voice": {"tone": "fellow_operator"}})
        merchant = MerchantContext.from_payload({"merchant_id": "m_1", "category_slug": "restaurants", "identity": {"name": "Cafe"}})
        trigger = normalize_trigger(TriggerContext.from_payload({
            "id": "trg_1", "kind": "festival_upcoming", "merchant_id": "m_1", "urgency": 3,
            "payload": {"festival": "Diwali"},
        }))
        candidates = [
            CandidateAction("inform", "inform", "view", "signal_a", facts={"festival": "Diwali"}, priority_hint=30),
            CandidateAction("prepare", "recommend", "approve", "signal_b", facts={"festival": "Diwali"}, priority_hint=80),
        ]

        first = rank_candidates(category, merchant, trigger, candidates, [])
        second = rank_candidates(category, merchant, trigger, candidates, [])

        self.assertEqual(first, second)
        self.assertEqual(first[0].candidate.objective, "prepare")

    def test_customer_relevance_is_zero_without_customer(self):
        category = CategoryContext.from_payload({"slug": "dentists"})
        merchant = MerchantContext.from_payload({"merchant_id": "m_1", "category_slug": "dentists"})
        trigger = normalize_trigger(TriggerContext.from_payload({"id": "trg_1", "scope": "merchant", "merchant_id": "m_1"}))
        candidate = CandidateAction("inform", "inform", "view", "trigger:unknown")

        ranked = rank_candidates(category, merchant, trigger, [candidate], [])

        self.assertEqual(ranked[0].components["customer_relevance"], 0.0)


if __name__ == "__main__":
    unittest.main()