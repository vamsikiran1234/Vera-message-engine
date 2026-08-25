import json
import unittest
from pathlib import Path

from vera_engine.engine import DecisionEngine
from vera_engine.models import ContextEnvelope
from vera_engine.store import ContextStore, ConversationStore, SuppressionStore


class CustomerQualityTests(unittest.TestCase):
    def test_dentist_recall_uses_customer_slots_and_offer(self):
        root = Path("expanded")
        contexts = ContextStore()
        for scope, path, context_id in [
            ("category", root / "categories/dentists.json", "dentists"),
            ("merchant", root / "merchants/m_001_drmeera_dentist_delhi.json", "m_001_drmeera_dentist_delhi"),
            ("customer", root / "customers/c_001_priya_for_m001.json", "c_001_priya_for_m001"),
            ("trigger", root / "triggers/trg_003_recall_due_priya.json", "trg_003_recall_due_priya"),
        ]:
            contexts.put(ContextEnvelope(scope, context_id, 1, json.loads(path.read_text()), "now"))
        action = DecisionEngine(contexts, ConversationStore(), SuppressionStore()).compose_trigger("trg_003_recall_due_priya")

        self.assertIsNotNone(action)
        self.assertEqual(action.send_as, "merchant_on_behalf")
        self.assertIn("Priya", action.body)
        self.assertIn("Wed 5 Nov, 6pm", action.body)
        self.assertIn("Dental Cleaning @", action.body)


if __name__ == "__main__":
    unittest.main()