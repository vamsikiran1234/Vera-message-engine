import json
import os
import unittest
from dataclasses import replace
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from vera_engine.composer import compose_message, compose_message_diagnostic, objective_allowed, _prompt, _quality_failure_reason, _value_is_grounded_in_message
from vera_engine.models import CategoryContext, MerchantContext
from vera_engine.planner import MessagePlan
from vera_engine.signals import NormalizedTrigger


class FakeProvider:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.prompt = ""

    def complete(self, prompt, timeout):
        self.prompt = prompt
        if self.error:
            raise self.error
        return json.dumps(self.payload)


class RawProvider(FakeProvider):
    def __init__(self, response):
        super().__init__()
        self.response = response

    def complete(self, prompt, timeout):
        self.prompt = prompt
        return self.response


class ComposerTests(unittest.TestCase):
    def setUp(self):
        self.category = CategoryContext.from_payload({
            "slug": "gyms",
            "voice": {"tone": "coaching"},
        })
        self.merchant = MerchantContext.from_payload({
            "merchant_id": "m_1",
            "category_slug": "gyms",
            "identity": {"owner_first_name": "Padma", "languages": ["en"]},
            "performance": {"views": 700, "calls": 18, "ctr": 0.052},
            "offers": [{"title": "First Month @ ₹499", "status": "active"}],
        })
        self.trigger = NormalizedTrigger(
            trigger_id="t_1", kind="perf_spike", scope="merchant", source="internal",
            urgency=2, merchant_id="m_1", customer_id=None, suppression_key="s1",
            facts={"metric": "calls", "delta_pct": 0.15},
        )
        self.plan = MessagePlan(
            objective="capitalize_on_demand", primary_signal="performance_increase",
            facts={"performance_increase": {"metric": "calls", "delta_pct": 0.15}, "calls": 18, "offer": "First Month @ ₹499"},
            cta="send", send_as="vera", template_name="vera_perf_spike_v1",
            suppression_key="s1", rationale="grounded", supporting_facts={"calls": 18},
        )
        self.body = "Padma, your calls are up 15% this week. Want me to draft a follow-up?"
        self.valid = {
            "message": "Padma, your calls are up 15% this week. Want me to draft a follow-up for the people who called?",
            "cta": "send",
            "used_facts": ["performance_increase.metric", "performance_increase.delta_pct"],
            "confidence": 0.9,
        }

    def compose(self, payload=None, error=None, **env):
        provider = FakeProvider(payload or self.valid, error)
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true", **env}, clear=False):
            result = compose_message(self.category, self.merchant, self.trigger, self.plan, self.body, provider)
        return result, provider

    def test_valid_composition(self):
        result, _ = self.compose()
        self.assertEqual(result.message, self.valid["message"])
        self.assertEqual(result.cta, "send")

    def test_api_failure_falls_back(self):
        result, _ = self.compose(error=RuntimeError("API failure"))
        self.assertIsNone(result)

    def test_timeout_falls_back(self):
        result, _ = self.compose(error=TimeoutError("timed out"))
        self.assertIsNone(result)

    def test_malformed_json_falls_back(self):
        provider = FakeProvider()
        provider.complete = lambda prompt, timeout: "not json"
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            self.assertIsNone(compose_message(self.category, self.merchant, self.trigger, self.plan, self.body, provider))

    def test_raw_json_is_accepted(self):
        provider = RawProvider(json.dumps(self.valid))
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            self.assertIsNotNone(compose_message(self.category, self.merchant, self.trigger, self.plan, self.body, provider))

    def test_json_fence_is_accepted(self):
        provider = RawProvider("```json\n" + json.dumps(self.valid) + "\n```")
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            self.assertIsNotNone(compose_message(self.category, self.merchant, self.trigger, self.plan, self.body, provider))

    def test_plain_fence_is_accepted(self):
        provider = RawProvider("```\n" + json.dumps(self.valid) + "\n```")
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            self.assertIsNotNone(compose_message(self.category, self.merchant, self.trigger, self.plan, self.body, provider))

    def test_json_with_explanatory_text_is_rejected(self):
        provider = RawProvider(json.dumps(self.valid) + "\nHere is the result.")
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            self.assertIsNone(compose_message(self.category, self.merchant, self.trigger, self.plan, self.body, provider))

    def test_explanatory_text_before_json_is_rejected(self):
        provider = RawProvider("Here is the result.\n" + json.dumps(self.valid))
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            self.assertIsNone(compose_message(self.category, self.merchant, self.trigger, self.plan, self.body, provider))

    def test_malformed_fenced_json_is_rejected(self):
        provider = RawProvider("```json\n{" + "\"message\": \"broken\"" + "\n```")
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            self.assertIsNone(compose_message(self.category, self.merchant, self.trigger, self.plan, self.body, provider))

    def test_multiple_fences_are_rejected(self):
        fenced = "```json\n" + json.dumps(self.valid) + "\n```\n```json\n{}\n```"
        provider = RawProvider(fenced)
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            self.assertIsNone(compose_message(self.category, self.merchant, self.trigger, self.plan, self.body, provider))

    def test_unsupported_number_is_rejected(self):
        payload = {**self.valid, "message": "Padma, calls are up 99% this week. Want me to draft a follow-up?"}
        result, _ = self.compose(payload)
        self.assertIsNone(result)

    def test_unsupported_currency_is_rejected(self):
        payload = {**self.valid, "message": "Padma, promote this for ₹999. Want me to draft a follow-up?"}
        result, _ = self.compose(payload)
        self.assertIsNone(result)

    def test_grounded_currency_499_is_accepted(self):
        currency = chr(0x20B9)
        message = f"Padma, calls are up 15% this week. Your First Month @ {currency}499 offer is ready. Want me to draft a follow-up?"
        payload = {**self.valid, "message": message, "used_facts": ["merchant.offers[0].title", "performance_increase.delta_pct"]}
        result, _ = self.compose(payload)
        self.assertIsNotNone(result)

    def test_grounded_currency_4999_is_accepted(self):
        currency = chr(0x20B9)
        trigger = replace(self.trigger, kind="renewal_due", facts={"days_remaining": 12, "renewal_amount": 4999})
        plan = replace(self.plan, cta="confirm", facts={**self.plan.facts, "renewal_amount": 4999, "days_remaining": 12})
        provider = FakeProvider({
            "message": f"Padma, your Pro plan renewal is due in 12 days at {currency}4999. Shall I prepare the renewal details?",
            "cta": "confirm", "used_facts": ["renewal_amount", "days_remaining"], "confidence": 0.9,
        })
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            result = compose_message(self.category, self.merchant, trigger, plan, "Padma, your Pro plan renews in 12 days for ₹4999. Want me to prepare the renewal details?", provider)
        self.assertIsNotNone(result)

    def test_unsupported_date_is_rejected(self):
        payload = {**self.valid, "message": "Padma, act on 2027-01-10. Want me to draft a follow-up?"}
        result, _ = self.compose(payload)
        self.assertIsNone(result)

    def test_unsupported_offer_is_rejected(self):
        payload = {**self.valid, "used_facts": ["Fake Offer"]}
        result, _ = self.compose(payload)
        self.assertIsNone(result)

    def test_unsupported_business_name_is_rejected(self):
        payload = {**self.valid, "used_facts": ["New Gym"]}
        result, _ = self.compose(payload)
        self.assertIsNone(result)

    def test_unsupported_competitor_name_is_rejected(self):
        payload = {**self.valid, "used_facts": ["Competitor Gym"]}
        result, _ = self.compose(payload)
        self.assertIsNone(result)

    def test_changed_cta_is_rejected(self):
        payload = {**self.valid, "cta": "view"}
        result, _ = self.compose(payload)
        self.assertIsNone(result)

    def test_multiple_questions_are_rejected(self):
        payload = {**self.valid, "message": "Padma, calls are up 15% this week. Want me to draft it? Should I send it?"}
        result, _ = self.compose(payload)
        self.assertIsNone(result)

    def test_merchant_name_is_preserved(self):
        result, _ = self.compose()
        self.assertIn("Padma", result.message)

    def test_deterministic_message_preserved_on_failure(self):
        result, _ = self.compose(error=OSError("unavailable"))
        self.assertIsNone(result)
        self.assertEqual(self.body, "Padma, your calls are up 15% this week. Want me to draft a follow-up?")

    def test_disabled_composer_returns_fallback(self):
        provider = FakeProvider(self.valid)
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "false"}, clear=False):
            self.assertIsNone(compose_message(self.category, self.merchant, self.trigger, self.plan, self.body, provider))

    def test_allowlist_enforcement(self):
        self.assertTrue(objective_allowed("perf_spike"))
        self.assertFalse(objective_allowed("supply_alert"))
        with patch.dict(os.environ, {"LLM_COMPOSER_OBJECTIVES": "renewal_due"}, clear=False):
            self.assertFalse(objective_allowed("perf_spike"))
            self.assertTrue(objective_allowed("renewal_due"))

    def test_hindi_preference_is_given_to_composer(self):
        merchant = MerchantContext.from_payload({**self.merchant.__dict__, "identity": {"owner_first_name": "Padma", "languages": ["hi", "en"]}})
        provider = FakeProvider(self.valid)
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            compose_message(self.category, merchant, self.trigger, self.plan, self.body, provider)
        self.assertIn('"languages": ["hi", "en"]', provider.prompt)

    def test_non_hindi_preference_is_given_to_composer(self):
        result, provider = self.compose()
        self.assertNotIn('"hi"', provider.prompt)
        self.assertIsNotNone(result)

    def test_strong_deterministic_message_can_remain_unchanged(self):
        result, _ = self.compose(payload={**self.valid, "message": self.body})
        self.assertIsNone(result)

    def test_quality_gate_rejects_removed_peer_comparison(self):
        deterministic = "Padma, calls are up 15%. Your CTR is 5.2%, versus the 4.5% peer median. Want me to draft a follow-up?"
        composed = "Padma, calls are up 15%. Want me to draft a follow-up?"
        self.assertEqual(_quality_failure_reason(composed, deterministic, self.merchant, self.plan), "quality_failed:peer_comparison_removed")

    def test_nested_fact_paths_are_valid(self):
        result, _ = self.compose(payload={**self.valid, "used_facts": ["performance_increase.metric", "performance_increase.delta_pct"]})
        self.assertIsNotNone(result)

    def test_nonexistent_nested_fact_path_is_rejected(self):
        result, _ = self.compose(payload={**self.valid, "used_facts": ["performance_increase.foo"]})
        self.assertIsNone(result)

    def test_nested_fact_values_are_required_in_message(self):
        payload = {**self.valid, "used_facts": ["performance_increase.metric"], "message": "Padma, demand is up 15%. Want me to draft a follow-up?"}
        result, _ = self.compose(payload)
        self.assertIsNone(result)

    def test_decimal_percentage_grounding_uses_display_precision(self):
        message = "Padma, your calls are down 50%. Your CTR is 1.8%, versus the 3% peer median. Want me to draft the update?"
        self.assertTrue(_value_is_grounded_in_message(0.018, message))

    def test_scalar_fact_path_is_valid(self):
        payload = {**self.valid, "message": "Padma, your calls are up 15% from 18 this week. Want me to draft a follow-up?", "used_facts": ["calls"]}
        result, _ = self.compose(payload)
        self.assertIsNotNone(result)

    def test_draft_cta_language_is_accepted(self):
        payload = {**self.valid, "message": "Padma, calls are up 15% this week. Want me to draft the follow-up?", "cta": "send"}
        result, _ = self.compose(payload)
        self.assertIsNotNone(result)

    def test_draft_cta_without_draft_language_is_rejected(self):
        payload = {**self.valid, "message": "Padma, calls are up 15% this week. I will shape the next step.", "cta": "draft"}
        trigger = replace(self.trigger, kind="curious_ask_due")
        plan = replace(self.plan, cta="draft")
        provider = FakeProvider(payload)
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            result = compose_message(self.category, self.merchant, trigger, plan, self.body, provider)
        self.assertIsNone(result)

    def test_quality_gate_rejects_removed_uncertainty(self):
        deterministic = "Padma, calls are up 15%, likely following your post. Want me to draft a follow-up?"
        composed = "Padma, calls are up 15% following your post. Want me to draft a follow-up?"
        self.assertEqual(_quality_failure_reason(composed, deterministic, self.merchant, self.plan), "quality_failed:uncertainty_removed")

    def test_quality_gate_rejects_generic_message(self):
        self.assertEqual(_quality_failure_reason("Padma, your business is doing well. Want help?", self.body, self.merchant, self.plan), "quality_failed:generic")

    def test_quality_gate_rejects_unnecessarily_long_message(self):
        composed = "Padma, your calls are up 15%. " + "useful grounded context " * 30 + "Want me to draft a follow-up?"
        self.assertEqual(_quality_failure_reason(composed, self.body, self.merchant, self.plan), "quality_failed:unnecessarily_long")

    def test_grounded_useful_detail_may_exceed_deterministic_length(self):
        deterministic = "Padma, your plan renews in 12 days. Want me to prepare the renewal details?"
        composed = "Padma, your plan renews in 12 days for ₹4999. With 980 views and a 1.8% CTR compared to the 3% peer median, visibility matters now. Want me to prepare the renewal details?"
        self.assertIsNone(_quality_failure_reason(composed, deterministic, self.merchant, self.plan))

    def test_prompt_requests_grounded_quality(self):
        prompt = _prompt(self.category, self.merchant, self.trigger, self.plan, self.body)
        for phrase in ("specificity", "category fit", "merchant fit", "why this matters now", "Preserve every grounded", "one clear concrete CTA"):
            self.assertIn(phrase, prompt)
        self.assertIn("performance_increase.metric", prompt)
        self.assertIn("valid_used_fact_paths", prompt)

    def test_prompt_requires_explicit_cta_semantics(self):
        prompt = _prompt(self.category, self.merchant, self.trigger, self.plan, self.body)
        self.assertIn("draft, create, or prepare", prompt)
        self.assertIn("send or share", prompt)
        self.assertIn("approve or proceed", prompt)
        self.assertIn("ask to confirm", prompt)

    def test_diagnostic_reasons_cover_disabled_and_allowlist(self):
        provider = FakeProvider(self.valid)
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "false"}, clear=False):
            self.assertEqual(compose_message_diagnostic(self.category, self.merchant, self.trigger, self.plan, self.body, provider).reason, "disabled")
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true", "LLM_COMPOSER_OBJECTIVES": "renewal_due"}, clear=False):
            self.assertEqual(compose_message_diagnostic(self.category, self.merchant, self.trigger, self.plan, self.body, provider).reason, "not_allowlisted")

    def test_diagnostic_reasons_identify_provider_json_shape_cta_and_grounding(self):
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            self.assertEqual(compose_message_diagnostic(self.category, self.merchant, self.trigger, self.plan, self.body, FakeProvider(error=TimeoutError())).reason, "provider_error:timeout")
            invalid_json = FakeProvider()
            invalid_json.complete = lambda prompt, timeout: "not json"
            self.assertEqual(compose_message_diagnostic(self.category, self.merchant, self.trigger, self.plan, self.body, invalid_json).reason, "invalid_json")
            self.assertEqual(compose_message_diagnostic(self.category, self.merchant, self.trigger, self.plan, self.body, FakeProvider({"message": "x"})).reason, "invalid_shape")
            self.assertEqual(compose_message_diagnostic(self.category, self.merchant, self.trigger, self.plan, self.body, FakeProvider({**self.valid, "cta": "view"})).reason, "cta_mismatch")
            self.assertEqual(compose_message_diagnostic(self.category, self.merchant, self.trigger, self.plan, self.body, FakeProvider({**self.valid, "used_facts": ["Fake Offer"]})).reason, "grounding_failed:used_fact")

    def test_provider_http_errors_have_safe_status_reasons(self):
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            for status in (429, 500):
                error = HTTPError("https://example.test", status, "error", {}, None)
                result = compose_message_diagnostic(self.category, self.merchant, self.trigger, self.plan, self.body, FakeProvider(error=error))
                self.assertIsNone(result.composition)
                self.assertEqual(result.reason, f"provider_error:http_{status}")

    def test_provider_timeout_has_safe_reason(self):
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            result = compose_message_diagnostic(self.category, self.merchant, self.trigger, self.plan, self.body, FakeProvider(error=TimeoutError()))
        self.assertIsNone(result.composition)
        self.assertEqual(result.reason, "provider_error:timeout")

    def test_provider_network_error_has_safe_reason(self):
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            result = compose_message_diagnostic(self.category, self.merchant, self.trigger, self.plan, self.body, FakeProvider(error=URLError("unavailable")))
        self.assertIsNone(result.composition)
        self.assertEqual(result.reason, "provider_error:network")

    def test_provider_unknown_error_has_safe_reason(self):
        with patch.dict(os.environ, {"LLM_COMPOSER_ENABLED": "true"}, clear=False):
            result = compose_message_diagnostic(self.category, self.merchant, self.trigger, self.plan, self.body, FakeProvider(error=RuntimeError("unexpected")))
        self.assertIsNone(result.composition)
        self.assertEqual(result.reason, "provider_error:unknown")


if __name__ == "__main__":
    unittest.main()
