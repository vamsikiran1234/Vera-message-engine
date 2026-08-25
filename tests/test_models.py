import unittest

from vera_engine.models import CategoryContext, CustomerContext, MerchantContext, TriggerContext


class ContextModelTests(unittest.TestCase):
    def test_category_preserves_unknown_fields(self):
        context = CategoryContext.from_payload({"slug": "cafes", "future_field": {"enabled": True}})

        self.assertEqual(context.slug, "cafes")
        self.assertEqual(context.extra["future_field"], {"enabled": True})

    def test_merchant_normalizes_invalid_optional_collections(self):
        context = MerchantContext.from_payload({
            "merchant_id": "m_test",
            "category_slug": "cafes",
            "offers": None,
            "signals": "not-a-list",
        })

        self.assertEqual(context.offers, [])
        self.assertEqual(context.signals, [])

    def test_customer_and_trigger_preserve_references(self):
        customer = CustomerContext.from_payload({
            "customer_id": "c_test",
            "merchant_id": "m_test",
            "state": "active",
        })
        trigger = TriggerContext.from_payload({
            "id": "trg_test",
            "scope": "customer",
            "merchant_id": "m_test",
            "customer_id": "c_test",
            "urgency": "4",
        })

        self.assertEqual(customer.customer_id, "c_test")
        self.assertEqual(trigger.customer_id, "c_test")
        self.assertEqual(trigger.urgency, 4)


if __name__ == "__main__":
    unittest.main()