import unittest

from vera_engine.models import CategoryContext, CustomerContext, MerchantContext, TriggerContext
from vera_engine.signals import extract_signals, normalize_trigger


class SignalTests(unittest.TestCase):
    def test_normalization_removes_placeholder_metadata_only(self):
        trigger = TriggerContext.from_payload({
            "id": "trg_1",
            "kind": "perf_dip",
            "merchant_id": "m_1",
            "suppression_key": "perf:m_1:calls",
            "payload": {"placeholder": True, "metric_or_topic": "perf_dip", "metric": "calls"},
            "urgency": 3,
        })

        normalized = normalize_trigger(trigger)

        self.assertTrue(normalized.is_placeholder)
        self.assertEqual(normalized.suppression_key, "perf:m_1:calls")
        self.assertEqual(normalized.facts, {"metric": "calls"})

    def test_perf_dip_extracts_trigger_and_merchant_evidence(self):
        category = CategoryContext.from_payload({"slug": "dentists"})
        merchant = MerchantContext.from_payload({
            "merchant_id": "m_1",
            "category_slug": "dentists",
            "performance": {"calls": 4},
        })
        trigger = normalize_trigger(TriggerContext.from_payload({
            "id": "trg_1",
            "kind": "perf_dip",
            "merchant_id": "m_1",
            "payload": {"metric": "calls", "delta_pct": -0.5},
            "urgency": 4,
        }))

        signals = extract_signals(category, merchant, trigger)

        self.assertEqual([signal.name for signal in signals], ["performance_decline", "merchant_metric"])
        self.assertIn("trigger.payload.delta_pct=-0.5", signals[0].evidence)

    def test_customer_signal_requires_matching_customer(self):
        category = CategoryContext.from_payload({"slug": "dentists"})
        merchant = MerchantContext.from_payload({"merchant_id": "m_1", "category_slug": "dentists"})
        customer = CustomerContext.from_payload({"customer_id": "c_1", "merchant_id": "m_1", "state": "lapsed_soft"})
        trigger = normalize_trigger(TriggerContext.from_payload({
            "id": "trg_1",
            "kind": "recall_due",
            "merchant_id": "m_1",
            "customer_id": "c_1",
            "payload": {"due_date": "2026-11-12"},
            "urgency": 3,
        }))

        signals = extract_signals(category, merchant, trigger, customer)

        self.assertEqual([signal.name for signal in signals], ["customer_followup", "customer_due_date"])


if __name__ == "__main__":
    unittest.main()