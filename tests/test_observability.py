import unittest

from vera_engine.observability import DecisionEvent, DecisionLogger


class ObservabilityTests(unittest.TestCase):
    def test_logger_records_structured_decision_event(self):
        logger = DecisionLogger()
        logger.record(DecisionEvent(
            trigger_id="trg_1",
            merchant_id="m_1",
            customer_id=None,
            candidate_scores=({"objective": "inform", "score": 0.8},),
            selected_signal="signal_1",
            selected_action="inform",
            outcome="selected",
            validation_passed=True,
            latency_ms=1.2,
        ))

        self.assertEqual(len(logger.events), 1)
        self.assertEqual(logger.events[0].outcome, "selected")
        self.assertEqual(logger.events[0].candidate_scores[0]["score"], 0.8)


if __name__ == "__main__":
    unittest.main()