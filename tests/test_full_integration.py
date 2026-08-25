import json
import unittest
from pathlib import Path

from vera_engine.engine import DecisionEngine
from vera_engine.models import ContextEnvelope
from vera_engine.store import ContextStore, ConversationStore, SuppressionStore


ROOT = Path(__file__).parents[1]
DATA = ROOT / "expanded"


class FullIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.categories = {
            path.stem: json.loads(path.read_text())
            for path in (DATA / "categories").glob("*.json")
        }
        cls.merchants = {
            path.stem: json.loads(path.read_text())
            for path in (DATA / "merchants").glob("*.json")
        }
        cls.customers = {
            path.stem: json.loads(path.read_text())
            for path in (DATA / "customers").glob("*.json")
        }
        cls.triggers = {
            path.stem: json.loads(path.read_text())
            for path in (DATA / "triggers").glob("*.json")
        }

    def build_engine(self):
        contexts = ContextStore()
        for slug, payload in self.categories.items():
            contexts.put(ContextEnvelope("category", slug, 1, payload, "now"))
        for merchant_id, payload in self.merchants.items():
            contexts.put(ContextEnvelope("merchant", merchant_id, 1, payload, "now"))
        for customer_id, payload in self.customers.items():
            contexts.put(ContextEnvelope("customer", customer_id, 1, payload, "now"))
        for trigger_id, payload in self.triggers.items():
            contexts.put(ContextEnvelope("trigger", trigger_id, 1, payload, "now"))
        return DecisionEngine(contexts, ConversationStore(), SuppressionStore()), contexts

    def test_all_triggers_process_without_exceptions(self):
        engine, _ = self.build_engine()

        actions = [engine.compose_trigger(trigger_id) for trigger_id in self.triggers]

        self.assertEqual(len(actions), 100)
        for action in actions:
            if action:
                self.assertTrue(action.body)
                self.assertTrue(action.suppression_key)
                self.assertLessEqual(action.body.count("?"), 1)

    def test_canonical_pairs_produce_expected_scope_and_identity(self):
        engine, _ = self.build_engine()
        pairs = json.loads((DATA / "test_pairs.json").read_text())["pairs"]

        for pair in pairs:
            action = engine.compose_trigger(pair["trigger_id"])
            if action:
                self.assertEqual(action.merchant_id, pair["merchant_id"])
                self.assertEqual(action.customer_id, pair.get("customer_id"))
                expected_sender = "merchant_on_behalf" if pair.get("customer_id") else "vera"
                self.assertEqual(action.send_as, expected_sender)

    def test_same_input_is_deterministic_before_suppression(self):
        first, _ = self.build_engine()
        second, _ = self.build_engine()

        first_action = first.compose_trigger("trg_001_research_digest_dentists")
        second_action = second.compose_trigger("trg_001_research_digest_dentists")

        self.assertEqual(first_action, second_action)

    def test_context_upgrade_changes_composition_source(self):
        engine, contexts = self.build_engine()
        original = engine.compose_trigger("trg_001_research_digest_dentists")
        updated_category = dict(self.categories["dentists"])
        updated_category["digest"] = [{
            "id": "d_new", "kind": "research", "title": "New recall guidance", "source": "New Journal",
        }]
        updated_trigger = dict(self.triggers["trg_001_research_digest_dentists"])
        updated_trigger["payload"] = {"top_item_id": "d_new"}
        contexts.put(ContextEnvelope("category", "dentists", 2, updated_category, "later"))
        contexts.put(ContextEnvelope("trigger", "trg_001_research_digest_dentists", 2, updated_trigger, "later"))
        updated_engine = DecisionEngine(contexts, ConversationStore(), SuppressionStore())
        updated = updated_engine.compose_trigger("trg_001_research_digest_dentists")

        self.assertNotEqual(original.body, updated.body)
        self.assertIn("New recall guidance", updated.body)


if __name__ == "__main__":
    unittest.main()