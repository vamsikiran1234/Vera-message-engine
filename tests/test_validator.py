import unittest

from vera_engine.models import CategoryContext, CustomerContext, MerchantContext
from vera_engine.planner import MessagePlan
from vera_engine.validator import validate_message


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.category = CategoryContext.from_payload({
            "slug": "dentists",
            "voice": {"vocab_taboo": ["guaranteed"]},
        })
        self.merchant = MerchantContext.from_payload({
            "merchant_id": "m_1",
            "category_slug": "dentists",
            "identity": {"owner_first_name": "Meera"},
            "performance": {"calls": 18},
        })
        self.plan = MessagePlan(
            objective="inform", primary_signal="signal", facts={"calls": 18}, cta="approve",
            send_as="vera", template_name="vera_signal_v1", suppression_key="s1", rationale="grounded",
        )

    def test_accepts_grounded_number_and_cta(self):
        result = validate_message("Meera, calls are 18. Should I approve?", "approve", self.category, self.merchant, self.plan)

        self.assertTrue(result.valid)
        self.assertIn("18", result.facts_checked)

    def test_rejects_unsupported_number_and_taboo(self):
        result = validate_message("Meera, guaranteed results at 99%. Should I approve?", "approve", self.category, self.merchant, self.plan)

        self.assertFalse(result.valid)
        self.assertIn("unsupported_fact:99", result.reasons)
        self.assertIn("taboo_term:guaranteed", result.reasons)

    def test_rejects_missing_customer_consent_and_repetition(self):
        customer = CustomerContext.from_payload({"customer_id": "c_1", "merchant_id": "m_1", "consent": {"scope": []}})
        plan = MessagePlan(
            objective="follow_up", primary_signal="signal", facts={}, cta="confirm",
            send_as="merchant_on_behalf", template_name="merchant_signal_v1", suppression_key="s1", rationale="grounded",
        )

        result = validate_message("Hi there. Want me to confirm?", "confirm", self.category, self.merchant, plan, customer, ["Hi there. Want me to confirm?"])

        self.assertFalse(result.valid)
        self.assertIn("customer_consent_missing", result.reasons)
        self.assertIn("repeated_body", result.reasons)


if __name__ == "__main__":
    unittest.main()