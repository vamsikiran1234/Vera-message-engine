import unittest

from fastapi.testclient import TestClient

from bot import app


class ApiTests(unittest.TestCase):
    def setUp(self):
        import bot

        bot.context_store = bot.ContextStore()
        bot.conversation_store = bot.ConversationStore()
        bot.suppression_store = bot.SuppressionStore()
        self.client = TestClient(app)

    def test_health_aliases_and_metadata(self):
        self.assertEqual(self.client.get("/v1/healthz").status_code, 200)
        self.assertEqual(self.client.get("/healthz").json()["status"], "ok")
        self.assertIn("team_name", self.client.get("/v1/metadata").json())

    def test_context_version_contract(self):
        payload = {
            "scope": "merchant",
            "context_id": "m_api",
            "version": 1,
            "payload": {"merchant_id": "m_api"},
            "delivered_at": "2026-08-25T00:00:00Z",
        }

        accepted = self.client.post("/v1/context", json=payload)
        stale = self.client.post("/v1/context", json=payload)

        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.json()["accepted"])
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["reason"], "stale_version")

    def test_tick_and_reply_return_valid_shapes(self):
        tick = self.client.post("/v1/tick", json={"now": "now", "available_triggers": []})
        reply = self.client.post(
            "/v1/reply",
            json={
                "conversation_id": "conv_api",
                "merchant_id": "m_api",
                "from_role": "merchant",
                "message": "Hello",
                "received_at": "now",
                "turn_number": 1,
            },
        )

        self.assertEqual(tick.json(), {"actions": []})
        self.assertEqual(reply.json()["action"], "wait")


if __name__ == "__main__":
    unittest.main()