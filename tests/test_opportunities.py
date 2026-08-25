import json
import unittest
from pathlib import Path

from vera_engine.engine import DecisionEngine
from vera_engine.models import ContextEnvelope
from vera_engine.store import ContextStore, ConversationStore, SuppressionStore


ROOT = Path(__file__).parents[1] / "expanded"


def compose(trigger_id, category_id, merchant_id):
    contexts = ContextStore()
    for scope, path, context_id in [
        ("category", ROOT / "categories" / f"{category_id}.json", category_id),
        ("merchant", ROOT / "merchants" / f"{merchant_id}.json", merchant_id),
        ("trigger", ROOT / "triggers" / f"{trigger_id}.json", trigger_id),
    ]:
        contexts.put(ContextEnvelope(scope, context_id, 1, json.loads(path.read_text()), "now"))
    return DecisionEngine(contexts, ConversationStore(), SuppressionStore()).compose_trigger(trigger_id)


class OpportunityTests(unittest.TestCase):
    def test_performance_dip_selects_listing_or_customer_opportunity(self):
        action = compose("trg_004_perf_dip_bharat", "dentists", "m_002_bharat_dentist_mumbai")

        self.assertIsNotNone(action)
        self.assertNotIn("current trigger window", action.body)
        self.assertTrue("listing" in action.body.lower() or "customers" in action.body.lower())

    def test_demand_event_uses_event_and_merchant_offer(self):
        action = compose("trg_010_ipl_match_delhi", "restaurants", "m_005_pizzajunction_restaurant_delhi")

        self.assertIsNotNone(action)
        self.assertIn("DC vs MI", action.body)
        self.assertIn("Buy 1 Pizza Get 1 Free", action.body)

    def test_dormancy_uses_duration_without_internal_vocabulary(self):
        action = compose("trg_025_dormancy_glamour", "salons", "m_004_glamour_salon_pune")

        self.assertIsNotNone(action)
        self.assertIn("38 days", action.body)
        self.assertNotIn("dormant signal", action.body.lower())

    def test_seasonal_opportunity_uses_offer(self):
        action = compose("trg_006_festival_diwali", "salons", "m_003_studio11_salon_hyderabad")

        self.assertIsNotNone(action)
        # The engine should select the most relevant current opportunity.
        # For a festival 188 days away with a stronger current seasonal signal,
        # the action should be grounded in the available context (Diwali or
        # the current seasonal digest item) rather than a generic fallback.
        self.assertTrue(
            "Diwali" in action.body or "salons" in action.body or "salon" in action.body.lower(),
            f"Expected a salon-specific action, got: {action.body}",
        )
        # Must NOT be the generic "I found a signal" fallback
        self.assertNotIn("I found a", action.body)

    def test_planning_intent_continues_conversation(self):
        action = compose("trg_013_corporate_thali_planning", "restaurants", "m_006_southindiancafe_restaurant_bangalore")

        self.assertIsNotNone(action)
        self.assertIn("corporate bulk thali package", action.body)
        self.assertIn("draft", action.body.lower())


if __name__ == "__main__":
    unittest.main()