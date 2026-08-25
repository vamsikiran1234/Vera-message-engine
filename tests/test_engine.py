import json
import unittest
from pathlib import Path

from vera_engine.engine import DecisionEngine
from vera_engine.models import ContextEnvelope
from vera_engine.store import ContextStore, ConversationStore, SuppressionStore


class EngineTests(unittest.TestCase):
    def test_research_trigger_composes_grounded_action(self):
        root = Path("expanded")
        contexts = ContextStore()
        for scope, path, context_id in [
            ("category", root / "categories/dentists.json", "dentists"),
            ("merchant", root / "merchants/m_001_drmeera_dentist_delhi.json", "m_001_drmeera_dentist_delhi"),
            ("trigger", root / "triggers/trg_001_research_digest_dentists.json", "trg_001_research_digest_dentists"),
        ]:
            contexts.put(ContextEnvelope(scope, context_id, 1, json.loads(path.read_text()), "now"))
        engine = DecisionEngine(contexts, ConversationStore(), SuppressionStore())

        action = engine.compose_trigger("trg_001_research_digest_dentists")

        self.assertIsNotNone(action)
        self.assertIn("JIDA", action.body)
        self.assertEqual(action.send_as, "vera")
        self.assertEqual(action.suppression_key, "research:dentists:2026-W17")

    def test_missing_trigger_returns_no_action(self):
        engine = DecisionEngine(ContextStore(), ConversationStore(), SuppressionStore())

        self.assertIsNone(engine.compose_trigger("missing"))

    def test_compliance_trigger_is_not_dropped_for_cta_mismatch(self):
        root = Path("expanded")
        contexts = ContextStore()
        for scope, path, context_id in [
            ("category", root / "categories/dentists.json", "dentists"),
            ("merchant", root / "merchants/m_001_drmeera_dentist_delhi.json", "m_001_drmeera_dentist_delhi"),
            ("trigger", root / "triggers/trg_002_compliance_dci_radiograph.json", "trg_002_compliance_dci_radiograph"),
        ]:
            contexts.put(ContextEnvelope(scope, context_id, 1, json.loads(path.read_text()), "now"))
        engine = DecisionEngine(contexts, ConversationStore(), SuppressionStore())

        action = engine.compose_trigger("trg_002_compliance_dci_radiograph")

        self.assertIsNotNone(action)
        self.assertIn("compliance checklist", action.body)


if __name__ == "__main__":
    unittest.main()