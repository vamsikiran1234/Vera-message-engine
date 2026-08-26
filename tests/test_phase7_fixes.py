"""Phase 7 regression tests — 4 targeted fixes.

Tests:
  1.  Confirmed planning intent produces a grounded artifact structure
  2.  Artifact contains no fabricated prices or invented capabilities
  3.  Unconfirmed planning intent still uses the old ask-to-start pattern
  4.  Perf spike preserves 'likely' uncertainty in likely_driver wording
  5.  Perf spike includes relevant conversation evidence (kids-yoga case)
  6.  Seasonal beat influences action selection (retention flag set)
  7.  Low-acquisition season does not blindly produce acquisition CTA
  8.  Seasonal digest uses grounded category/merchant evidence as why-now anchor
  9.  Internal terminology remains blocked and strong triggers unchanged
"""

import json
import unittest
from pathlib import Path

from vera_engine.candidates import (
    _is_confirmed_intent,
    _grounded_artifact_skeleton,
    _translate_likely_driver,
    _seasonal_strategy,
    generate_candidates,
)
from vera_engine.engine import DecisionEngine
from vera_engine.models import (
    CategoryContext, ContextEnvelope, MerchantContext, TriggerContext,
)
from vera_engine.signals import extract_signals, normalize_trigger
from vera_engine.store import ContextStore, ConversationStore, SuppressionStore

ROOT = Path(__file__).parents[1] / "expanded"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cat(slug, seasonal_beats=None, digest=None, peer_stats=None):
    payload = {
        "slug": slug,
        "voice": {"tone": "energetic_disciplined"},
        "peer_stats": peer_stats or {"avg_ctr": 0.045, "avg_calls_30d": 18, "avg_views_30d": 1100},
        "seasonal_beats": seasonal_beats or [],
        "digest": digest or [],
    }
    return CategoryContext.from_payload(payload)


def _merchant(slug, offers=None, signals=None, conversation_history=None, performance=None):
    return MerchantContext.from_payload({
        "merchant_id": "m_test",
        "category_slug": slug,
        "identity": {"owner_first_name": "Padma"},
        "performance": performance or {"views": 880, "calls": 18, "ctr": 0.062,
                                        "delta_7d": {"calls_pct": 0.15}},
        "offers": offers if offers is not None else [
            {"title": "First Month @ Rs499", "status": "active"}
        ],
        "signals": signals or ["high_retention"],
        "conversation_history": conversation_history or [],
        "customer_aggregate": {},
    })


def _planning_trigger(intent_topic, merchant_last_message, urgency=4):
    return normalize_trigger(TriggerContext.from_payload({
        "id": "trg_test_plan",
        "scope": "merchant",
        "kind": "active_planning_intent",
        "source": "internal",
        "merchant_id": "m_test",
        "customer_id": None,
        "urgency": urgency,
        "suppression_key": "plan:test",
        "expires_at": "2026-12-01T00:00:00Z",
        "payload": {
            "intent_topic": intent_topic,
            "merchant_last_message": merchant_last_message,
        },
    }))


def _spike_trigger(metric="calls", delta=0.15, likely_driver=None):
    payload = {"metric": metric, "delta_pct": delta, "window": "7d", "vs_baseline": 18}
    if likely_driver:
        payload["likely_driver"] = likely_driver
    return normalize_trigger(TriggerContext.from_payload({
        "id": "trg_test_spike",
        "scope": "merchant",
        "kind": "perf_spike",
        "source": "internal",
        "merchant_id": "m_test",
        "customer_id": None,
        "urgency": 1,
        "suppression_key": "spike:test",
        "expires_at": "2026-12-01T00:00:00Z",
        "payload": payload,
    }))


def _compose_full(category_id, merchant_id, trigger_id):
    cs = ContextStore()
    for scope, path, cid in [
        ("category", ROOT / "categories" / f"{category_id}.json", category_id),
        ("merchant", ROOT / "merchants"  / f"{merchant_id}.json",  merchant_id),
        ("trigger",  ROOT / "triggers"   / f"{trigger_id}.json",   trigger_id),
    ]:
        cs.put(ContextEnvelope(scope, cid, 1, json.loads(path.read_text()), "now"))
    return DecisionEngine(cs, ConversationStore(), SuppressionStore()).compose_trigger(trigger_id)


# ---------------------------------------------------------------------------
# 1. Confirmed planning intent produces a grounded artifact structure
# ---------------------------------------------------------------------------

class TestConfirmedPlanningIntent(unittest.TestCase):

    def _action(self, merchant_last_message, intent_topic="corporate_bulk_thali_package"):
        category = _cat("restaurants")
        merchant = _merchant("restaurants", conversation_history=[
            {"from": "vera", "body": "Want me to add a corporate-bulk version?"},
            {"from": "merchant", "body": merchant_last_message},
        ])
        trigger = _planning_trigger(intent_topic, merchant_last_message)
        signals = extract_signals(category, merchant, trigger)
        candidates = generate_candidates(category, merchant, trigger, signals)
        return next((c for c in candidates if c.objective == "prepare_content"), None)

    def test_confirmed_message_produces_artifact_skeleton(self):
        cand = self._action("Yes good idea, what would it look like")
        self.assertIsNotNone(cand)
        self.assertTrue(cand.facts.get("merchant_confirms"), "merchant_confirms should be True")
        self.assertIn("artifact_skeleton", cand.facts, "artifact_skeleton should be present")
        skeleton = cand.facts["artifact_skeleton"]
        self.assertTrue(len(skeleton) > 10, "Skeleton should have meaningful content")

    def test_full_pipeline_confirmed_shows_structure_not_question(self):
        action = _compose_full(
            "restaurants",
            "m_006_southindiancafe_restaurant_bangalore",
            "trg_013_corporate_thali_planning",
        )
        self.assertIsNotNone(action)
        body = action.body
        # Must show a draft structure, not just offer to start
        self.assertTrue(
            "draft structure" in body.lower() or "starting structure" in body.lower(),
            f"Expected 'draft structure' in body, got: {body}",
        )
        # Must still name the topic
        self.assertIn("corporate bulk thali", body.lower(),
                      f"Expected topic name in body, got: {body}")

    def test_unconfirmed_message_does_not_produce_artifact(self):
        cand = self._action("What would that look like")  # question, not confirmation
        self.assertIsNotNone(cand)
        self.assertFalse(cand.facts.get("merchant_confirms", False),
                         "An ambiguous question should not set merchant_confirms")

    def test_is_confirmed_intent_helper_detects_affirmatives(self):
        self.assertTrue(_is_confirmed_intent("Yes good idea, what would it look like"))
        self.assertTrue(_is_confirmed_intent("yes"))
        self.assertTrue(_is_confirmed_intent("go ahead"))
        self.assertTrue(_is_confirmed_intent("sounds good, proceed"))

    def test_is_confirmed_intent_helper_rejects_questions(self):
        self.assertFalse(_is_confirmed_intent("What would that cost?"))
        self.assertFalse(_is_confirmed_intent("How many people does this serve?"))
        self.assertFalse(_is_confirmed_intent(""))


# ---------------------------------------------------------------------------
# 2. Artifact contains only grounded facts — no fabricated prices/capabilities
# ---------------------------------------------------------------------------

class TestArtifactGrounding(unittest.TestCase):

    def test_skeleton_uses_existing_offer_title_as_base_unit(self):
        merchant = _merchant("restaurants", offers=[
            {"title": "Weekday Lunch Thali @ Rs149", "status": "active"},
        ])
        skeleton = _grounded_artifact_skeleton("corporate_bulk_thali_package", merchant, None)
        self.assertIn("Weekday Lunch Thali @ Rs149", skeleton,
                      "Skeleton must use the actual offer title, not invented price")

    def test_skeleton_does_not_invent_prices_when_no_offer(self):
        merchant = _merchant("restaurants", offers=[])
        skeleton = _grounded_artifact_skeleton("corporate_bulk_thali_package", merchant, None)
        # Should return empty — cannot ground without an offer
        self.assertEqual(skeleton, "",
                         "Skeleton should be empty when no offer exists to anchor on")

    def test_skeleton_placeholder_fields_use_to_be_confirmed(self):
        merchant = _merchant("restaurants", offers=[
            {"title": "Thali @ Rs149", "status": "active"},
        ])
        skeleton = _grounded_artifact_skeleton("corporate_bulk_thali_package", merchant, None)
        # Editable fields should use "to be confirmed" not bracket notation
        self.assertIn("to be confirmed", skeleton,
                      "Editable fields should use 'to be confirmed' phrasing")
        # No bracket placeholders
        self.assertNotIn("[", skeleton,
                         "Bracket placeholders should not appear in the skeleton")

    def test_skeleton_contains_no_mojibake(self):
        merchant = _merchant("restaurants", offers=[
            {"title": "Thali @ Rs149", "status": "active"},
        ])
        skeleton = _grounded_artifact_skeleton("corporate_bulk_thali_package", merchant, None)
        self.assertNotIn("â€", skeleton, "Mojibake sequence â€ must not appear in skeleton")
        self.assertNotIn("\u00e2\u20ac", skeleton, "Mojibake must not appear in skeleton")


# ---------------------------------------------------------------------------
# 3 & 4. Perf spike: likely_driver preserved with uncertainty + conversation
# ---------------------------------------------------------------------------

class TestPerfSpikeEvidenceThreading(unittest.TestCase):

    def _spike_candidates(self, likely_driver=None, conversation_history=None):
        category = _cat("gyms", seasonal_beats=[
            {"month_range": "Apr-Jun", "note": "lowest acquisition window — focus on retention"},
        ])
        merchant = _merchant("gyms", conversation_history=conversation_history or [])
        trigger = _spike_trigger(metric="calls", delta=0.15, likely_driver=likely_driver)
        signals = extract_signals(category, merchant, trigger)
        return generate_candidates(category, merchant, trigger, signals)

    def test_likely_driver_translates_to_natural_language(self):
        label = _translate_likely_driver("kids_yoga_post")
        self.assertIn("kids", label.lower())
        self.assertNotIn("kids_yoga_post", label,  # raw slug must not appear
                         "Raw internal slug must be translated")

    def test_likely_driver_unknown_value_humanised_not_exposed(self):
        label = _translate_likely_driver("some_unknown_event_post")
        self.assertNotIn("_", label, "Underscores should be humanised out")

    def test_spike_candidate_carries_driver_label(self):
        cands = self._spike_candidates(likely_driver="kids_yoga_post")
        spike = next((c for c in cands if c.objective == "capitalize_on_demand"), None)
        self.assertIsNotNone(spike)
        label = spike.facts.get("spike_driver_label", "")
        self.assertTrue(len(label) > 0, "spike_driver_label should be populated")
        self.assertNotIn("kids_yoga_post", label, "Raw slug must not reach plan.facts")

    def test_spike_body_uses_likely_not_caused_by(self):
        action = _compose_full("gyms", "m_008_zenyoga_gym_chennai", "trg_024_perf_spike_zen")
        self.assertIsNotNone(action)
        body_lower = action.body.lower()
        self.assertIn("likely", body_lower,
                      f"Body should preserve 'likely' uncertainty, got: {action.body}")
        self.assertNotIn("caused by", body_lower)
        self.assertNotIn("because of", body_lower)

    def test_spike_no_driver_still_produces_valid_message(self):
        cands = self._spike_candidates(likely_driver=None)
        spike = next((c for c in cands if c.objective == "capitalize_on_demand"), None)
        self.assertIsNotNone(spike)
        self.assertNotIn("spike_driver_label", spike.facts)


# ---------------------------------------------------------------------------
# 5 & 6. Seasonal beat awareness — retention season
# ---------------------------------------------------------------------------

class TestSeasonalBeatAwareness(unittest.TestCase):

    def test_seasonal_strategy_returns_retention_for_retention_beat(self):
        category = _cat("gyms", seasonal_beats=[
            {"month_range": "Apr-Jun", "note": "lowest acquisition window — focus on retention, not acquisition"},
        ])
        self.assertEqual(_seasonal_strategy(category), "retention")

    def test_seasonal_strategy_returns_acquisition_for_peak_beat(self):
        category = _cat("gyms", seasonal_beats=[
            {"month_range": "Jan", "note": "resolution surge — trial walk-ins 4x baseline; convert window"},
        ])
        self.assertEqual(_seasonal_strategy(category), "acquisition")

    def test_seasonal_strategy_returns_neutral_when_no_beats(self):
        category = _cat("gyms", seasonal_beats=[])
        self.assertEqual(_seasonal_strategy(category), "neutral")

    def test_seasonal_strategy_does_not_hardcode_months(self):
        # Strategy should be detected from note text, not month string
        category = _cat("gyms", seasonal_beats=[
            {"month_range": "XYZ",  # nonsense month
             "note": "focus on retention, not acquisition this period"},
        ])
        self.assertEqual(_seasonal_strategy(category), "retention",
                         "Strategy detection must use note text, not month")

    def test_retention_season_produces_retention_cta_not_promotion(self):
        action = _compose_full("gyms", "m_008_zenyoga_gym_chennai", "trg_024_perf_spike_zen")
        self.assertIsNotNone(action)
        body_lower = action.body.lower()
        # Should NOT blindly say "prepare a promotion"
        self.assertNotIn("prepare a promotion to capitalise", body_lower,
                         f"Retention season should not produce acquisition CTA, got: {action.body}")
        # Should use retention / follow-up language
        self.assertTrue(
            "follow-up" in body_lower or "draft" in body_lower or "convert" in body_lower,
            f"Expected retention-oriented CTA, got: {action.body}",
        )


# ---------------------------------------------------------------------------
# 7. Seasonal digest uses grounded evidence
# ---------------------------------------------------------------------------

class TestSeasonalDigestGrounding(unittest.TestCase):

    def test_diwali_seasonal_digest_mentions_grounded_seasonal_fact(self):
        action = _compose_full("salons", "m_003_studio11_salon_hyderabad", "trg_006_festival_diwali")
        self.assertIsNotNone(action)
        body = action.body
        # Must mention a grounded fact from the context (seasonal beat count or search signal)
        self.assertTrue(
            "4x" in body or "4×" in body or "28%" in body
            or "bridal" in body.lower() or "wedding" in body.lower(),
            f"Expected grounded seasonal evidence in body, got: {body}",
        )
        # Must NOT expose the generic source label verbatim as the sole anchor
        self.assertNotIn("Wedding industry intel", body,
                         "Generic source label should not be the primary anchor")

    def test_seasonal_digest_body_does_not_contain_internal_vocabulary(self):
        action = _compose_full("salons", "m_003_studio11_salon_hyderabad", "trg_006_festival_diwali")
        self.assertIsNotNone(action)
        body_lower = action.body.lower()
        for forbidden in ("signal", "candidate", "trigger", "operator check",
                          "decision score", "ranking", "suppression key"):
            self.assertNotIn(forbidden, body_lower,
                             f"Internal term '{forbidden}' found in body: {action.body}")

    def test_seasonal_message_contains_no_mojibake(self):
        """Encoded em-dashes must not appear verbatim in any merchant-facing message."""
        action = _compose_full("salons", "m_003_studio11_salon_hyderabad", "trg_006_festival_diwali")
        self.assertIsNotNone(action)
        body = action.body
        # The three-character mojibake sequence for em-dash: â€" (U+00E2 U+20AC U+201D)
        mojibake_sequences = ["â€", "\u00e2\u20ac", "Ã"]
        for seq in mojibake_sequences:
            self.assertNotIn(seq, body,
                             f"Mojibake sequence '{seq}' found in body: {body}")


# ---------------------------------------------------------------------------
# 8. Internal terminology blocked + strong triggers unchanged
# ---------------------------------------------------------------------------

class TestRegressionStrongTriggers(unittest.TestCase):

    def test_supply_alert_body_contains_batch_numbers(self):
        action = _compose_full("pharmacies", "m_009_apollo_pharmacy_jaipur",
                               "trg_018_supply_atorvastatin_recall")
        self.assertIsNotNone(action)
        self.assertIn("AT2024", action.body)
        self.assertIn("atorvastatin", action.body.lower())

    def test_research_digest_body_contains_high_risk_count(self):
        action = _compose_full("dentists", "m_001_drmeera_dentist_delhi",
                               "trg_001_research_digest_dentists")
        self.assertIsNotNone(action)
        self.assertIn("124", action.body)
        self.assertIn("high-risk", action.body.lower())

    def test_gbp_unverified_body_contains_uplift_and_peer_ctr(self):
        action = _compose_full("pharmacies", "m_010_sunrisepharm_pharmacy_lucknow",
                               "trg_021_unverified_gbp_sunrise")
        self.assertIsNotNone(action)
        body_lower = action.body.lower()
        self.assertTrue(
            "%" in action.body or "verified" in body_lower,
            f"Expected verification or uplift in body, got: {action.body}",
        )

    def test_winback_body_contains_days_and_performance_drop(self):
        action = _compose_full("salons", "m_004_glamour_salon_pune",
                               "trg_009_winback_glamour")
        self.assertIsNotNone(action)
        self.assertIn("38 days", action.body)

    def test_no_internal_terms_in_any_strong_trigger_body(self):
        cases = [
            ("pharmacies", "m_009_apollo_pharmacy_jaipur",              "trg_018_supply_atorvastatin_recall"),
            ("dentists",   "m_001_drmeera_dentist_delhi",               "trg_001_research_digest_dentists"),
            ("restaurants","m_005_pizzajunction_restaurant_delhi",       "trg_011_review_theme_late_delivery"),
            ("restaurants","m_006_southindiancafe_restaurant_bangalore", "trg_013_corporate_thali_planning"),
            ("salons",     "m_004_glamour_salon_pune",                   "trg_009_winback_glamour"),
        ]
        forbidden = ("signal", "candidate", "trigger", "operator check",
                     "decision score", "ranking", "suppression key", "internal state")
        for cat, mid, tid in cases:
            action = _compose_full(cat, mid, tid)
            if action:
                body_lower = action.body.lower()
                for term in forbidden:
                    self.assertNotIn(term, body_lower,
                                     f"'{term}' found in body for {tid}: {action.body}")


if __name__ == "__main__":
    unittest.main()
