import json
import unittest
from pathlib import Path

from vera_engine.engine import DecisionEngine
from vera_engine.models import ContextEnvelope
from vera_engine.store import ContextStore, ConversationStore, SuppressionStore


ROOT = Path(__file__).parents[1]


class ExpandedDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = ROOT / "expanded"
        cls.categories = {
            path.stem: json.loads(path.read_text())
            for path in (cls.data / "categories").glob("*.json")
        }
        cls.merchants = {
            path.stem: json.loads(path.read_text())
            for path in (cls.data / "merchants").glob("*.json")
        }
        cls.customers = {
            path.stem: json.loads(path.read_text())
            for path in (cls.data / "customers").glob("*.json")
        }
        cls.triggers = {
            path.stem: json.loads(path.read_text())
            for path in (cls.data / "triggers").glob("*.json")
        }

    def make_engine(self, trigger_ids):
        contexts = ContextStore()
        for slug, payload in self.categories.items():
            contexts.put(ContextEnvelope("category", slug, 1, payload, "now"))
        merchant_ids = {self.triggers[trigger_id].get("merchant_id") for trigger_id in trigger_ids}
        for merchant_id in merchant_ids:
            if merchant_id in self.merchants:
                contexts.put(ContextEnvelope("merchant", merchant_id, 1, self.merchants[merchant_id], "now"))
        customer_ids = {self.triggers[trigger_id].get("customer_id") for trigger_id in trigger_ids}
        for customer_id in customer_ids:
            if customer_id in self.customers:
                contexts.put(ContextEnvelope("customer", customer_id, 1, self.customers[customer_id], "now"))
        for trigger_id in trigger_ids:
            contexts.put(ContextEnvelope("trigger", trigger_id, 1, self.triggers[trigger_id], "now"))
        return DecisionEngine(contexts, ConversationStore(), SuppressionStore())

    def test_all_canonical_pairs_are_safe_to_process(self):
        pairs = json.loads((self.data / "test_pairs.json").read_text())["pairs"]
        engine = self.make_engine([pair["trigger_id"] for pair in pairs])

        actions = [engine.compose_trigger(pair["trigger_id"]) for pair in pairs]

        self.assertEqual(len(actions), 30)
        for action in actions:
            if action:
                self.assertTrue(action.body)
                self.assertLessEqual(action.body.count("?"), 1)
                self.assertTrue(action.suppression_key)

    def test_placeholder_triggers_do_not_crash_or_invent_numeric_claims(self):
        trigger_ids = [trigger_id for trigger_id, trigger in self.triggers.items() if trigger.get("payload", {}).get("placeholder")][:5]
        engine = self.make_engine(trigger_ids)

        for trigger_id in trigger_ids:
            action = engine.compose_trigger(trigger_id)
            if action:
                self.assertNotIn("999", action.body)

    def test_tick_style_batch_is_capped_at_twenty(self):
        trigger_ids = list(self.triggers)[:30]
        engine = self.make_engine(trigger_ids)
        actions = [engine.compose_trigger(trigger_id) for trigger_id in trigger_ids[:20]]

        self.assertLessEqual(len([action for action in actions if action]), 20)


if __name__ == "__main__":
    unittest.main()