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

    def test_milestone_cta_is_concrete(self):
        category = CategoryContext.from_payload({"slug": "restaurants"})
        merchant = MerchantContext.from_payload({
            "merchant_id": "m_1", "category_slug": "restaurants",
            "identity": {"owner_first_name": "Suresh"},
        })
        trigger = normalize_trigger(TriggerContext.from_payload({
            "id": "t1", "kind": "milestone_reached", "merchant_id": "m_1",
            "payload": {"metric": "review_count", "value_now": 145, "milestone_value": 150, "is_imminent": True},
        }))
        candidate = CandidateAction("celebrate", "milestone", "draft", "milestone", facts={
            "metric": "review_count", "value_now": 145, "milestone_value": 150,
            "is_imminent": True, "milestone_gap": 5,
        })

        body, _ = render_message(category, merchant, trigger, build_message_plan(category, merchant, trigger, candidate))

        self.assertIn("Want me to draft a milestone post to share with your customers?", body)
        self.assertNotIn("APPROVE", body)

    def test_active_planning_strips_question_from_quoted_merchant_message(self):
        """Fix 6: merchant_msg with trailing '?' must be stripped to prevent double-? in body."""
        category = CategoryContext.from_payload({"slug": "gyms"})
        merchant = MerchantContext.from_payload({
            "merchant_id": "m_1", "category_slug": "gyms",
            "identity": {"owner_first_name": "Padma"},
        })
        trigger = normalize_trigger(TriggerContext.from_payload({
            "id": "t1", "kind": "active_planning_intent", "merchant_id": "m_1",
            "payload": {"intent_topic": "kids_yoga_summer_camp", "merchant_last_message": "Hi I want to add a kids yoga program — what should it look like?"},
        }))
        candidate = CandidateAction("prepare_content", "planning", "draft", "planning", facts={
            "intent_topic": "kids_yoga_summer_camp",
            "merchant_last_message": "Hi I want to add a kids yoga program — what should it look like?",
        })

        body, _ = render_message(category, merchant, trigger, build_message_plan(category, merchant, trigger, candidate))

        # The topic name should still appear
        self.assertIn("kids yoga summer camp", body)
        # Must have at most 1 question mark — stripping trailing ? prevents double-?
        self.assertLessEqual(body.count("?"), 1, f"Body has multiple '?': {body}")

    def test_cde_digest_normalizes_mojibake_without_stripping_rupee(self):
        category = CategoryContext.from_payload({
            "slug": "dentists",
            "digest": [{"id": "d1", "title": "Webinar â€“ ₹499 updates", "source": "IDA"}],
        })
        merchant = MerchantContext.from_payload({
            "merchant_id": "m_1", "category_slug": "dentists", "identity": {"owner_first_name": "Meera"},
        })
        trigger = normalize_trigger(TriggerContext.from_payload({
            "id": "t1", "kind": "cde_opportunity", "merchant_id": "m_1",
            "payload": {"digest_item_id": "d1", "credits": 2, "fee": "free_for_members"},
        }))
        candidate = CandidateAction("share", "inform", "view", "cde", facts={
            "digest_item": category.digest[0], "credits": 2, "fee": "free_for_members",
        })

        body, _ = render_message(category, merchant, trigger, build_message_plan(category, merchant, trigger, candidate))

        self.assertNotIn("â€", body)
        self.assertIn("₹", body)

if __name__ == "__main__":
    unittest.main()