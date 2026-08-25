"""Scoring gap analysis for Phase 2 weight redesign."""
import json
from pathlib import Path
from vera_engine.models import ContextEnvelope, TriggerContext, MerchantContext, CategoryContext
from vera_engine.signals import normalize_trigger, extract_signals
from vera_engine.candidates import generate_candidates
from vera_engine.scoring import rank_candidates, ScoringWeights
from vera_engine.store import ContextStore

ROOT = Path("expanded")


def load_contexts(category_id, merchant_id, trigger_id):
    cs = ContextStore()
    for scope, path, cid in [
        ("category", ROOT / "categories" / f"{category_id}.json", category_id),
        ("merchant", ROOT / "merchants" / f"{merchant_id}.json", merchant_id),
        ("trigger", ROOT / "triggers" / f"{trigger_id}.json", trigger_id),
    ]:
        cs.put(ContextEnvelope(scope, cid, 1, json.loads(path.read_text()), "now"))
    return cs


def analyse(label, category_id, merchant_id, trigger_id, weights=None):
    cs = load_contexts(category_id, merchant_id, trigger_id)
    trigger = TriggerContext.from_payload(cs.payload("trigger", trigger_id))
    merchant = MerchantContext.from_payload(cs.payload("merchant", merchant_id))
    category = CategoryContext.from_payload(cs.payload("category", category_id))
    normalized = normalize_trigger(trigger)
    signals = extract_signals(category, merchant, normalized)
    candidates = generate_candidates(category, merchant, normalized, signals)
    if not candidates:
        print(f"{label}: NO CANDIDATES")
        return None
    ranked = rank_candidates(category, merchant, normalized, candidates, signals, weights=weights)
    top = ranked[0]
    c = top.components
    w = weights or ScoringWeights()
    urgency_contrib = c["trigger_strength"] * w.trigger_strength + c["urgency"] * w.urgency
    evidence_contrib = (
        c["specificity"] * w.specificity
        + c["merchant_relevance"] * w.merchant_relevance
        + c["evidence_strength"] * w.evidence_strength
        + c["offer_compatibility"] * w.offer_compatibility
        + c["conversation_continuity"] * w.conversation_continuity
    )
    print(f"{label}")
    print(f"  urgency={normalized.urgency}  total_score={top.score:.4f}")
    print(f"  URGENCY contribution    = {urgency_contrib:.4f}  (trigger_str={c['trigger_strength']:.3f} urgency_c={c['urgency']:.3f})")
    print(f"  EVIDENCE contribution   = {evidence_contrib:.4f}  (spec={c['specificity']:.3f} merch_rel={c['merchant_relevance']:.3f} evid_str={c['evidence_strength']:.3f} offer={c['offer_compatibility']:.3f} conv={c['conversation_continuity']:.3f})")
    print(f"  merchant_impact={c['merchant_impact']:.3f}  category_fit={c['category_fit']:.3f}  actionability={c['actionability']:.3f}")
    print()
    return top.score


# ── Current weights ──────────────────────────────────────────────────────────
print("=" * 70)
print("CURRENT WEIGHTS  (trigger_strength=0.25, urgency=0.10, evidence×5=0.05each)")
print("=" * 70)
cases = [
    ("supply_alert     (urgency=5)", "pharmacies",  "m_009_apollo_pharmacy_jaipur",              "trg_018_supply_atorvastatin_recall"),
    ("perf_dip         (urgency=4)", "dentists",    "m_002_bharat_dentist_mumbai",               "trg_004_perf_dip_bharat"),
    ("review_theme     (urgency=3)", "restaurants", "m_005_pizzajunction_restaurant_delhi",      "trg_011_review_theme_late_delivery"),
    ("research_digest  (urgency=2)", "dentists",    "m_001_drmeera_dentist_delhi",               "trg_001_research_digest_dentists"),
    ("competitor_open  (urgency=2)", "dentists",    "m_001_drmeera_dentist_delhi",               "trg_023_competitor_opened_dentist"),
    ("winback          (urgency=2)", "salons",      "m_004_glamour_salon_pune",                  "trg_009_winback_glamour"),
    ("dormant          (urgency=2)", "salons",      "m_004_glamour_salon_pune",                  "trg_025_dormancy_glamour"),
    ("milestone        (urgency=1)", "restaurants", "m_006_southindiancafe_restaurant_bangalore","trg_012_milestone_mylari"),
    ("festival_upcmg   (urgency=1)", "salons",      "m_003_studio11_salon_hyderabad",            "trg_006_festival_diwali"),
    ("curious_ask      (urgency=1)", "salons",      "m_003_studio11_salon_hyderabad",            "trg_008_curious_ask_studio11"),
]

current_scores = {}
for args in cases:
    s = analyse(*args)
    current_scores[args[0]] = s

# ── Proposed weights ─────────────────────────────────────────────────────────
proposed = ScoringWeights(
    trigger_strength=0.15,     # was 0.25 — still present, just halved
    merchant_impact=0.20,      # unchanged
    category_fit=0.15,         # unchanged
    actionability=0.20,        # was 0.15 — reward higher-priority_hint candidates more
    customer_relevance=0.10,   # unchanged
    urgency=0.05,              # was 0.10 — no longer double-counts at full weight
    specificity=0.05,          # unchanged (signal.specificity/4 — still 0 for op triggers)
    merchant_relevance=0.05,   # unchanged
    offer_compatibility=0.03,  # was 0.05 — slight trim to free up budget
    conversation_continuity=0.05, # unchanged
    evidence_strength=0.07,    # was 0.05 — reward richer evidence packs
)
# Verify weights sum to 1.0
total = sum([
    proposed.trigger_strength, proposed.merchant_impact, proposed.category_fit,
    proposed.actionability, proposed.customer_relevance, proposed.urgency,
    proposed.specificity, proposed.merchant_relevance, proposed.offer_compatibility,
    proposed.conversation_continuity, proposed.evidence_strength,
])
print(f"\nProposed weight sum = {total:.4f}")

print("\n" + "=" * 70)
print("PROPOSED WEIGHTS  (trigger_strength=0.15, urgency=0.05, actionability=0.20, evidence_strength=0.07)")
print("=" * 70)
for args in cases:
    analyse(*args, weights=proposed)
