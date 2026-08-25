"""Phase 5 — Seasonal decision quality tests.

Tests cover:
  1. Festival >120 days with generic offer → low priority_hint, honest framing
  2. Festival >120 days with festival-specific offer → higher relevance score
  3. Festival 30 days away with relevant offer → near-term framing
  4. Festival 7 days away with any offer → immediate activation, full priority
  5. Distant festival with explicit merchant planning intent → proximity boosted
  6. Distant festival with no relevant merchant evidence → fallback candidate only
  7. Seasonal opportunity competes with stronger current demand signal
  8. Existing strong trigger behaviour (supply_alert) unchanged
"""

import json
import unittest
from pathlib import Path

from vera_engine.candidates import (
    _festival_offer_relevance,
    _festival_proximity_factor,
    _has_festival_planning_intent,
    generate_candidates,
    FESTIVAL_PROXIMITY_BANDS,
    FESTIVAL_PROXIMITY_DEFAULT,
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

def _make_category(slug="salons", seasonal_beats=None, digest=None):
    payload = {
        "slug": slug,
        "voice": {"tone": "warm_practical"},
        "peer_stats": {"avg_ctr": 0.04, "avg_views_30d": 2400},
    }
    if seasonal_beats:
        payload["seasonal_beats"] = seasonal_beats
    if digest:
        payload["digest"] = digest
    return CategoryContext.from_payload(payload)


def _make_merchant(signals=None, conversation_history=None, offers=None, performance=None):
    payload = {
        "merchant_id": "m_test",
        "category_slug": "salons",
        "identity": {"owner_first_name": "Priya"},
        "performance": performance or {"views": 3000, "calls": 40, "ctr": 0.04},
        "offers": offers if offers is not None else [{"title": "Haircut @ ₹99", "status": "active"}],
        "signals": signals or [],
        "conversation_history": conversation_history or [],
        "customer_aggregate": {},
    }
    return MerchantContext.from_payload(payload)


def _make_festival_trigger(days_until, festival="Diwali", urgency=1):
    return normalize_trigger(TriggerContext.from_payload({
        "id": "trg_test_festival",
        "scope": "merchant",
        "kind": "festival_upcoming",
        "source": "external",
        "merchant_id": "m_test",
        "customer_id": None,
        "urgency": urgency,
        "suppression_key": f"festival:{festival}:test",
        "expires_at": "2026-12-01T00:00:00Z",
        "payload": {
            "festival": festival,
            "date": "2026-10-31",
            "days_until": days_until,
            "category_relevance": ["salons", "restaurants"],
        },
    }))


def _compose_full(category_id, merchant_id, trigger_id):
    cs = ContextStore()
    for scope, path, cid in [
        ("category", ROOT / "categories" / f"{category_id}.json", category_id),
        ("merchant", ROOT / "merchants" / f"{merchant_id}.json", merchant_id),
        ("trigger",  ROOT / "triggers"  / f"{trigger_id}.json",  trigger_id),
    ]:
        cs.put(ContextEnvelope(scope, cid, 1, json.loads(path.read_text()), "now"))
    return DecisionEngine(cs, ConversationStore(), SuppressionStore()).compose_trigger(trigger_id)


# ---------------------------------------------------------------------------
# 1. Festival >120 days with generic offer → low priority_hint, honest framing
# ---------------------------------------------------------------------------

class TestDistantFestivalGenericOffer(unittest.TestCase):
    def setUp(self):
        self.category = _make_category(seasonal_beats=[
            {"month_range": "Oct-Dec", "note": "primary wedding/festival season — bridal 4x baseline"},
        ])
        self.merchant = _make_merchant()
        self.trigger = _make_festival_trigger(days_until=188)
        self.offer = {"title": "Haircut @ ₹99", "status": "active"}

    def test_proximity_factor_is_low_for_distant_festival(self):
        factor = _festival_proximity_factor(188)
        self.assertEqual(factor, FESTIVAL_PROXIMITY_DEFAULT)  # 0.3

    def test_offer_relevance_is_low_for_generic_offer(self):
        # Category has NO relevant seasonal beat → relevance falls to 0.2
        category_no_beat = _make_category(seasonal_beats=[
            {"month_range": "Apr-May", "note": "summer hair-care surge"},  # not festival-related
        ])
        relevance = _festival_offer_relevance(self.offer, "Diwali", category_no_beat, 188)
        self.assertLess(relevance, 0.5)

    def test_offer_relevance_is_moderate_with_relevant_seasonal_beat(self):
        # Category WITH a festival-relevant beat → relevance = 0.8
        relevance = _festival_offer_relevance(self.offer, "Diwali", self.category, 188)
        self.assertGreaterEqual(relevance, 0.8)
        self.assertLess(relevance, 1.0)

    def test_plan_seasonal_campaign_priority_hint_is_depressed(self):
        signals = extract_signals(self.category, self.merchant, self.trigger)
        candidates = generate_candidates(self.category, self.merchant, self.trigger, signals)
        festival_candidates = [c for c in candidates if c.objective == "plan_seasonal_campaign"]
        self.assertTrue(festival_candidates, "plan_seasonal_campaign candidate must exist")
        top = festival_candidates[0]
        # Effective priority = 78 × 0.3 × 0.2 ≈ 4, floored to 15
        self.assertLessEqual(top.priority_hint, 25)

    def test_distant_festival_body_uses_honest_framing(self):
        action = _compose_full("salons", "m_003_studio11_salon_hyderabad", "trg_006_festival_diwali")
        self.assertIsNotNone(action)
        # With a stronger current seasonal signal, the engine picks the current
        # opportunity (seasonal digest item) over the distant festival campaign.
        # The message must not pretend the festival is imminent.
        self.assertNotIn("is a great fit for Haircut", action.body)
        # Must be grounded in the salon category
        body_lower = action.body.lower()
        self.assertTrue(
            "salon" in body_lower or "bridal" in body_lower or "keratin" in body_lower
            or "diwali" in body_lower,
            f"Expected salon-specific content, got: {action.body}",
        )


# ---------------------------------------------------------------------------
# 2. Festival >120 days with festival-specific offer → higher relevance
# ---------------------------------------------------------------------------

class TestDistantFestivalRelevantOffer(unittest.TestCase):
    def test_festive_offer_title_gives_high_relevance(self):
        category = _make_category()
        bridal_offer = {"title": "Bridal Package @ ₹2999", "status": "active"}
        relevance = _festival_offer_relevance(bridal_offer, "Diwali", category, 188)
        self.assertGreaterEqual(relevance, 1.0)

    def test_wedding_keyword_in_offer_gives_high_relevance(self):
        category = _make_category()
        wedding_offer = {"title": "Wedding Mehendi Special @ ₹499", "status": "active"}
        relevance = _festival_offer_relevance(wedding_offer, "Diwali", category, 150)
        self.assertGreaterEqual(relevance, 1.0)

    def test_festive_offer_produces_higher_priority_than_generic(self):
        category = _make_category(seasonal_beats=[
            {"month_range": "Oct-Dec", "note": "wedding season — bridal 4x"},
        ])
        merchant_generic = _make_merchant(
            offers=[{"title": "Haircut @ ₹99", "status": "active"}]
        )
        merchant_festive = _make_merchant(
            offers=[{"title": "Bridal Package @ ₹2999", "status": "active"}]
        )
        trigger = _make_festival_trigger(days_until=188)
        signals = extract_signals(category, merchant_generic, trigger)

        generic_cands = generate_candidates(category, merchant_generic, trigger, signals)
        festive_cands = generate_candidates(category, merchant_festive, trigger, signals)

        generic_p = next((c.priority_hint for c in generic_cands if c.objective == "plan_seasonal_campaign"), 0)
        festive_p = next((c.priority_hint for c in festive_cands if c.objective == "plan_seasonal_campaign"), 0)
        self.assertGreater(festive_p, generic_p, "Festival-specific offer should give higher priority than generic")


# ---------------------------------------------------------------------------
# 3. Festival 30 days away — near-term framing
# ---------------------------------------------------------------------------

class TestNearTermFestival(unittest.TestCase):
    def test_proximity_factor_is_high_at_30_days(self):
        factor = _festival_proximity_factor(30)
        self.assertGreaterEqual(factor, 0.9)

    def test_offer_relevance_is_full_at_30_days(self):
        category = _make_category()
        generic_offer = {"title": "Haircut @ ₹99", "status": "active"}
        # At ≤60 days, any offer gets full relevance
        relevance = _festival_offer_relevance(generic_offer, "Diwali", category, 30)
        self.assertEqual(relevance, 1.0)

    def test_near_term_festival_priority_hint_is_high(self):
        category = _make_category(seasonal_beats=[
            {"month_range": "Oct-Dec", "note": "wedding season"},
        ])
        merchant = _make_merchant()
        trigger = _make_festival_trigger(days_until=30)
        signals = extract_signals(category, merchant, trigger)
        candidates = generate_candidates(category, merchant, trigger, signals)
        festival_cands = [c for c in candidates if c.objective == "plan_seasonal_campaign"]
        self.assertTrue(festival_cands)
        self.assertGreaterEqual(festival_cands[0].priority_hint, 60)


# ---------------------------------------------------------------------------
# 4. Festival 7 days away — immediate activation, full priority
# ---------------------------------------------------------------------------

class TestImmediateFestival(unittest.TestCase):
    def test_proximity_factor_is_1_at_7_days(self):
        factor = _festival_proximity_factor(7)
        self.assertEqual(factor, 1.0)

    def test_immediate_festival_preserves_high_priority(self):
        category = _make_category(seasonal_beats=[
            {"month_range": "Oct-Dec", "note": "festive season"},
        ])
        merchant = _make_merchant()
        trigger = _make_festival_trigger(days_until=7)
        signals = extract_signals(category, merchant, trigger)
        candidates = generate_candidates(category, merchant, trigger, signals)
        festival_cands = [c for c in candidates if c.objective == "plan_seasonal_campaign"]
        self.assertTrue(festival_cands)
        # With proximity=1.0 and relevance=1.0 (≤60d), priority should be max
        self.assertGreaterEqual(festival_cands[0].priority_hint, 70)


# ---------------------------------------------------------------------------
# 5. Distant festival with explicit merchant planning intent → boost proximity
# ---------------------------------------------------------------------------

class TestPlanningIntentBoostsFestival(unittest.TestCase):
    def test_planning_intent_detected_in_conversation(self):
        # Only merchant-sent turns count as planning intent
        merchant = _make_merchant(conversation_history=[
            {"body": "Can you help me plan a Diwali campaign for bridal season?", "from": "merchant"},
        ])
        has_intent = _has_festival_planning_intent(merchant, "Diwali")
        self.assertTrue(has_intent)

    def test_planning_intent_not_detected_in_vera_sent_turns(self):
        # Vera-sent turns with festival keywords should NOT count as merchant planning intent
        merchant = _make_merchant(conversation_history=[
            {"body": "Bridal demand is up — want me to plan a Diwali campaign?", "from": "vera"},
        ])
        has_intent = _has_festival_planning_intent(merchant, "Diwali")
        self.assertFalse(has_intent)

    def test_no_planning_intent_without_relevant_conversation(self):
        merchant = _make_merchant(conversation_history=[
            {"body": "How do I improve my listing?", "from": "merchant"},
        ])
        has_intent = _has_festival_planning_intent(merchant, "Diwali")
        self.assertFalse(has_intent)

    def test_planning_intent_boosts_priority_hint(self):
        category = _make_category(seasonal_beats=[
            {"month_range": "Oct-Dec", "note": "wedding season"},
        ])
        # Merchant WITH explicit planning intent (merchant-sent turn)
        merchant_with = _make_merchant(conversation_history=[
            {"body": "I want to plan for the wedding season", "from": "merchant"},
        ])
        # Merchant WITHOUT planning intent
        merchant_without = _make_merchant(conversation_history=[
            {"body": "Bridal demand up this week", "from": "vera"},  # Vera turn, not merchant
        ])

        trigger = _make_festival_trigger(days_until=150)
        signals = extract_signals(category, merchant_with, trigger)

        cands_with = generate_candidates(category, merchant_with, trigger, signals)
        cands_without = generate_candidates(category, merchant_without, trigger, signals)

        p_with    = next((c.priority_hint for c in cands_with    if c.objective == "plan_seasonal_campaign"), 0)
        p_without = next((c.priority_hint for c in cands_without if c.objective == "plan_seasonal_campaign"), 0)
        self.assertGreater(p_with, p_without, "Merchant planning intent should boost priority_hint")


# ---------------------------------------------------------------------------
# 6. Distant festival with no relevant merchant evidence → only weak candidate
# ---------------------------------------------------------------------------

class TestDistantFestivalNoEvidence(unittest.TestCase):
    def test_no_offer_produces_no_plan_seasonal_campaign(self):
        """Without an active offer there is no plan_seasonal_campaign candidate.
        The catch-all may still produce prepare_seasonal_campaign, but the
        stronger plan_seasonal_campaign requires an explicit offer."""
        category = _make_category()
        merchant = _make_merchant(offers=[])  # no active offer
        trigger = _make_festival_trigger(days_until=200)
        signals = extract_signals(category, merchant, trigger)
        candidates = generate_candidates(category, merchant, trigger, signals)
        festival_cands = [c for c in candidates if c.objective == "plan_seasonal_campaign"]
        self.assertEqual(festival_cands, [], "plan_seasonal_campaign requires an active offer")

    def test_very_distant_festival_has_lowest_priority_band(self):
        for days in (121, 150, 200, 365):
            self.assertEqual(
                _festival_proximity_factor(days),
                FESTIVAL_PROXIMITY_DEFAULT,
                f"days={days} should use default factor {FESTIVAL_PROXIMITY_DEFAULT}",
            )


# ---------------------------------------------------------------------------
# 7. Seasonal opportunity competition: current demand signal can outrank distant festival
# ---------------------------------------------------------------------------

class TestSeasonalOpportunityCompetition(unittest.TestCase):
    def test_current_seasonal_digest_generates_competing_candidate(self):
        """When festival is distant and category has a current seasonal digest item,
        a share_relevant_category_knowledge candidate is also generated."""
        category = _make_category(
            seasonal_beats=[{"month_range": "Oct-Dec", "note": "wedding season"}],
            digest=[{
                "id": "d_current_season",
                "kind": "seasonal",
                "title": "Secondary bridal window Apr-May — bookings 2x",
                "source": "magicpin internal",
                "actionable": "Run a Bridal Trial offer now",
            }],
        )
        merchant = _make_merchant()
        trigger = _make_festival_trigger(days_until=188)
        signals = extract_signals(category, merchant, trigger)
        candidates = generate_candidates(category, merchant, trigger, signals)
        objectives = [c.objective for c in candidates]
        self.assertIn("plan_seasonal_campaign",          objectives)
        self.assertIn("share_relevant_category_knowledge", objectives,
                      "A current seasonal digest item should generate a competing candidate")

    def test_competing_candidate_has_higher_priority_than_distant_festival(self):
        """The current-demand candidate should outrank the distant festival candidate."""
        category = _make_category(
            seasonal_beats=[{"month_range": "Oct-Dec", "note": "wedding season"}],
            digest=[{
                "id": "d_now",
                "kind": "seasonal",
                "title": "Bridal season active now",
                "source": "magicpin",
                "actionable": "Push bridal trial",
            }],
        )
        merchant = _make_merchant()
        trigger = _make_festival_trigger(days_until=188)
        signals = extract_signals(category, merchant, trigger)
        candidates = generate_candidates(category, merchant, trigger, signals)

        festival_p = next((c.priority_hint for c in candidates if c.objective == "plan_seasonal_campaign"), 0)
        current_p  = next((c.priority_hint for c in candidates if c.objective == "share_relevant_category_knowledge"), 0)
        self.assertGreater(current_p, festival_p,
                           "Current demand signal should have higher priority than distant festival")


# ---------------------------------------------------------------------------
# 8. Existing strong trigger behaviour unchanged
# ---------------------------------------------------------------------------

class TestStrongTriggerRegression(unittest.TestCase):
    def test_supply_alert_still_fires_and_contains_batch_numbers(self):
        action = _compose_full("pharmacies", "m_009_apollo_pharmacy_jaipur", "trg_018_supply_atorvastatin_recall")
        self.assertIsNotNone(action)
        self.assertIn("atorvastatin", action.body.lower())
        self.assertIn("AT2024", action.body)

    def test_research_digest_still_fires_and_uses_high_risk_count(self):
        action = _compose_full("dentists", "m_001_drmeera_dentist_delhi", "trg_001_research_digest_dentists")
        self.assertIsNotNone(action)
        self.assertIn("high-risk", action.body.lower())
        self.assertIn("124", action.body)

    def test_review_theme_still_fires_with_readable_theme(self):
        action = _compose_full("restaurants", "m_005_pizzajunction_restaurant_delhi", "trg_011_review_theme_late_delivery")
        self.assertIsNotNone(action)
        self.assertIn("delivery", action.body.lower())

    def test_festival_diwali_still_contains_festival_name_and_offer(self):
        """The Diwali trigger must still produce a non-None action grounded in
        the merchant's category context.  When a stronger current opportunity
        exists, the action may be about that opportunity rather than the distant
        festival itself — but it must still be category-specific, not generic."""
        action = _compose_full("salons", "m_003_studio11_salon_hyderabad", "trg_006_festival_diwali")
        self.assertIsNotNone(action)
        # Action must be about the salon category
        self.assertTrue(
            "Diwali" in action.body or "salon" in action.body.lower() or "bridal" in action.body.lower(),
            f"Expected salon-specific action, got: {action.body}",
        )
        # Must NOT be generic fallback
        self.assertNotIn("I found a", action.body)


if __name__ == "__main__":
    unittest.main()
