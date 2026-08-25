import unittest

from vera_engine.candidates import generate_candidates
from vera_engine.models import CategoryContext, CustomerContext, MerchantContext, TriggerContext
from vera_engine.signals import extract_signals, normalize_trigger


class CandidateTests(unittest.TestCase):
    def test_perf_dip_with_active_offer_is_actionable(self):
        category = CategoryContext.from_payload({"slug": "salons"})
        merchant = MerchantContext.from_payload({
            "merchant_id": "m_1",
            "category_slug": "salons",
            "offers": [{"title": "Haircut @ ₹99", "status": "active"}],
        })
        trigger = normalize_trigger(TriggerContext.from_payload({
            "id": "trg_1", "kind": "perf_dip", "merchant_id": "m_1", "urgency": 4,
            "payload": {"metric": "calls", "delta_pct": -0.3},
        }))

        candidates = generate_candidates(category, merchant, trigger, extract_signals(category, merchant, trigger))

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].action_type, "recommend")
        self.assertEqual(candidates[0].cta, "approve")

    def test_customer_candidate_requires_consent(self):
        category = CategoryContext.from_payload({"slug": "dentists"})
        merchant = MerchantContext.from_payload({"merchant_id": "m_1", "category_slug": "dentists"})
        trigger = normalize_trigger(TriggerContext.from_payload({
            "id": "trg_1", "kind": "recall_due", "scope": "customer", "merchant_id": "m_1",
            "customer_id": "c_1", "urgency": 3, "payload": {"due_date": "2026-11-12"},
        }))
        customer = CustomerContext.from_payload({
            "customer_id": "c_1", "merchant_id": "m_1", "state": "lapsed_soft",
            "preferences": {"reminder_opt_in": False},
            "consent": {"scope": ["recall_reminders"]},
        })

        self.assertEqual(generate_candidates(category, merchant, trigger, [], customer), [])

    def test_unknown_trigger_uses_available_payload_without_invention(self):
        category = CategoryContext.from_payload({"slug": "cafes"})
        merchant = MerchantContext.from_payload({"merchant_id": "m_1", "category_slug": "cafes"})
        trigger = normalize_trigger(TriggerContext.from_payload({
            "id": "trg_1", "kind": "new_signal", "merchant_id": "m_1",
            "payload": {"topic": "new opening"},
        }))

        candidates = generate_candidates(category, merchant, trigger, [])

        self.assertEqual(candidates[0].facts, {"topic": "new opening"})

    def test_research_candidate_preserves_merchant_offer_and_history_evidence(self):
        category = CategoryContext.from_payload({
            "slug": "dentists",
            "digest": [{"id": "d1", "title": "Recall research", "patient_segment": "high_risk_adults"}],
        })
        merchant = MerchantContext.from_payload({
            "merchant_id": "m_1", "category_slug": "dentists",
            "offers": [{"title": "Dental Cleaning @ ₹299", "status": "active"}],
            "signals": ["high_risk_adult_cohort"],
            "customer_aggregate": {"high_risk_adult_count": 12},
            "conversation_history": [{"body": "Focus on whitening and aligners"}],
        })
        trigger = normalize_trigger(TriggerContext.from_payload({
            "id": "t1", "kind": "research_digest", "merchant_id": "m_1",
            "payload": {"top_item_id": "d1"},
        }))

        candidates = generate_candidates(category, merchant, trigger, extract_signals(category, merchant, trigger))

        candidate = candidates[0]
        self.assertEqual(candidate.facts["high_risk_adult_count"], 12)
        self.assertTrue(candidate.offer_evidence)
        self.assertTrue(candidate.conversation_evidence)


if __name__ == "__main__":
    unittest.main()