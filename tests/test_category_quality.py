import json
import unittest
from pathlib import Path

from vera_engine.engine import DecisionEngine
from vera_engine.models import ContextEnvelope
from vera_engine.store import ContextStore, ConversationStore, SuppressionStore


class CategoryQualityTests(unittest.TestCase):
    def test_pharmacy_supply_alert_uses_batch_and_molecule(self):
        root = Path("expanded")
        contexts = ContextStore()
        for scope, path, context_id in [
            ("category", root / "categories/pharmacies.json", "pharmacies"),
            ("merchant", root / "merchants/m_009_apollo_pharmacy_jaipur.json", "m_009_apollo_pharmacy_jaipur"),
            ("trigger", root / "triggers/trg_018_supply_atorvastatin_recall.json", "trg_018_supply_atorvastatin_recall"),
        ]:
            contexts.put(ContextEnvelope(scope, context_id, 1, json.loads(path.read_text()), "now"))
        action = DecisionEngine(contexts, ConversationStore(), SuppressionStore()).compose_trigger("trg_018_supply_atorvastatin_recall")

        self.assertIsNotNone(action)
        self.assertIn("atorvastatin", action.body)
        self.assertIn("AT2024-1102", action.body)

    def test_restaurant_event_uses_event_and_offer(self):
        root = Path("expanded")
        contexts = ContextStore()
        for scope, path, context_id in [
            ("category", root / "categories/restaurants.json", "restaurants"),
            ("merchant", root / "merchants/m_005_pizzajunction_restaurant_delhi.json", "m_005_pizzajunction_restaurant_delhi"),
            ("trigger", root / "triggers/trg_010_ipl_match_delhi.json", "trg_010_ipl_match_delhi"),
        ]:
            contexts.put(ContextEnvelope(scope, context_id, 1, json.loads(path.read_text()), "now"))
        action = DecisionEngine(contexts, ConversationStore(), SuppressionStore()).compose_trigger("trg_010_ipl_match_delhi")

        self.assertIsNotNone(action)
        self.assertIn("DC vs MI", action.body)
        self.assertIn("Buy 1 Pizza Get 1 Free", action.body)


if __name__ == "__main__":
    unittest.main()