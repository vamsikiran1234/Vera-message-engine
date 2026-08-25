import unittest

from vera_engine.replies import classify_reply, handle_reply
from vera_engine.store import ConversationStore, SuppressionStore


class ReplyTests(unittest.TestCase):
    def setUp(self):
        self.conversations = ConversationStore()
        self.suppression = SuppressionStore()

    def test_classifies_priority_intents(self):
        self.assertEqual(classify_reply("Stop messaging me"), "OPT_OUT")
        self.assertEqual(classify_reply("How much is the offer?"), "REQUEST_DETAILS")
        self.assertEqual(classify_reply("Ok lets do it"), "CONFIRMATION")

    def test_auto_reply_backoff_then_end(self):
        first = handle_reply("conv_1", "Thank you for contacting us! Our team will respond shortly.", self.conversations, self.suppression)
        second = handle_reply("conv_1", "Thank you for contacting us! Our team will respond shortly.", self.conversations, self.suppression)
        third = handle_reply("conv_1", "Thank you for contacting us! Our team will respond shortly.", self.conversations, self.suppression)

        self.assertEqual(first.action, "wait")
        self.assertEqual(second.action, "wait")
        self.assertEqual(third.action, "end")
        self.assertTrue(self.suppression.conversation_suppressed("conv_1"))

    def test_opt_out_ends_conversation(self):
        result = handle_reply("conv_2", "No thanks, stop messaging me.", self.conversations, self.suppression)

        self.assertEqual(result.action, "end")
        self.assertTrue(self.conversations.get_or_create("conv_2").terminal)

    def test_confirmation_advances_without_qualification(self):
        result = handle_reply("conv_3", "Yes, go ahead", self.conversations, self.suppression)

        self.assertEqual(result.action, "send")
        self.assertIn("next action", result.body)

    def test_question_takes_priority_over_confirmation(self):
        result = handle_reply("conv_4", "Yes, how much is it?", self.conversations, self.suppression)

        self.assertEqual(result.action, "send")
        self.assertEqual(result.cta, "reply")

    def test_hostile_and_terminal_conversations_end_cleanly(self):
        hostile = handle_reply("conv_5", "This is useless spam", self.conversations, self.suppression)
        after_end = handle_reply("conv_5", "Actually go ahead", self.conversations, self.suppression)

        self.assertEqual(hostile.action, "end")
        self.assertEqual(after_end.action, "end")
        self.assertIn("already closed", after_end.rationale)


if __name__ == "__main__":
    unittest.main()