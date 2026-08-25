import unittest

from vera_engine.candidates import CandidateAction
from vera_engine.models import CategoryContext, MerchantContext, TriggerContext
from vera_engine.planner import build_message_plan
from vera_engine.signals import normalize_trigger
from vera_engine.templates import render_message


class TemplateTests(unittest.TestCase):
    def test_research_template_uses_digest_facts(self):
        category = CategoryContext.from_payload({
            "slug": "dentists",
            "digest": [{"id": "d1", "title": "Recall update", "source": "JIDA"}],
        })
        merchant = MerchantContext.from_payload({
            "merchant_id": "m_1", "category_slug": "dentists", "identity": {"owner_first_name": "Meera"},
        })
        trigger = normalize_trigger(TriggerContext.from_payload({
            "id": "t1", "kind": "research_digest", "merchant_id": "m_1",
            "payload": {"top_item_id": "d1"},
        }))
        candidate = CandidateAction("share", "inform", "view", "category_digest_item", facts={"digest_item": category.digest[0]})

        body, params = render_message(category, merchant, trigger, build_message_plan(category, merchant, trigger, candidate))

        self.assertIn("Dr. Meera", body)
        self.assertIn("Recall update", body)
        self.assertIn("JIDA", body)
        self.assertIn("patient message", body)
        self.assertEqual(params[0], "Meera")

    def test_compliance_confirm_cta_is_reflected(self):
        category = CategoryContext.from_payload({
            "slug": "dentists",
            "digest": [{"id": "d1", "title": "Dose limits", "source": "DCI"}],
        })
        merchant = MerchantContext.from_payload({"merchant_id": "m_1", "category_slug": "dentists", "identity": {"owner_first_name": "Meera"}})
        trigger = normalize_trigger(__import__("vera_engine.models", fromlist=["TriggerContext"]).TriggerContext.from_payload({
            "id": "t1", "kind": "regulation_change", "merchant_id": "m_1",
            "payload": {"top_item_id": "d1", "deadline_iso": "2026-12-15"},
        }))
        candidate = CandidateAction("compliance", "recommend", "confirm", "category_digest_item", facts={"digest_item": category.digest[0]})
        plan = build_message_plan(category, merchant, trigger, candidate)

        body, _ = render_message(category, merchant, trigger, plan)

        self.assertIn("Should I prepare", body)

if __name__ == "__main__":
    unittest.main()