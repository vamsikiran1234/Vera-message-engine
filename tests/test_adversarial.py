import unittest

from vera_engine.candidates import generate_candidates
from vera_engine.models import CategoryContext, CustomerContext, MerchantContext, TriggerContext
from vera_engine.signals import extract_signals, normalize_trigger


class AdversarialTests(unittest.TestCase):
    def test_unknown_category_and_trigger_remain_conservative(self):
        category = CategoryContext.from_payload({"slug": "unknown_vertical"})
        merchant = MerchantContext.from_payload({"merchant_id": "m_1", "category_slug": "unknown_vertical"})
        trigger = normalize_trigger(TriggerContext.from_payload({
            "id": "t_1", "kind": "future_event", "merchant_id": "m_1", "payload": {},
        }))

        candidates = generate_candidates(category, merchant, trigger, extract_signals(category, merchant, trigger))

        self.assertEqual(candidates, [])

    def test_customer_from_another_merchant_cannot_be_contacted(self):
        category = CategoryContext.from_payload({"slug": "salons"})
        merchant = MerchantContext.from_payload({"merchant_id": "m_1", "category_slug": "salons"})
        customer = CustomerContext.from_payload({
            "customer_id": "c_1", "merchant_id": "m_other", "state": "lapsed_soft",
            "consent": {"opted_in_at": "2026-01-01", "scope": ["promotional_offers"]},
        })
        trigger = normalize_trigger(TriggerContext.from_payload({
            "id": "t_1", "kind": "customer_lapsed_soft", "scope": "customer",
            "merchant_id": "m_1", "customer_id": "c_1", "payload": {},
        }))

        candidates = generate_candidates(category, merchant, trigger, [], customer)

        self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()