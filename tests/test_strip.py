#!/usr/bin/env python3
"""Unit tests for server.strip_reasoning — no API key or running server needed.

GLM-5.2 on Ollama Cloud can leak its chain-of-thought inline in message.content
(wrapped in <think>…</think>, or Kimi-style ◁think▷…◁/think▷) even when the
request sets think:false. Ollama's contract puts reasoning in message.thinking,
which the server never reads — strip_reasoning removes the fallback case where the
trace bleeds into content, so it never reaches the toolkit UI.

    python3 tests/test_strip.py
"""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import strip_reasoning

THINK_OPEN, THINK_CLOSE = "◁think▷", "◁/think▷"   # ◁think▷ / ◁/think▷ (Kimi)


class StripReasoning(unittest.TestCase):
    def test_think_block_removed(self):
        self.assertEqual(strip_reasoning("<think>plan the answer</think>Hello there."), "Hello there.")

    def test_multiline_block(self):
        self.assertEqual(strip_reasoning("<think>\na\nb\n</think>\n\nFinal answer."), "Final answer.")

    def test_kimi_unicode_delims(self):
        self.assertEqual(strip_reasoning(THINK_OPEN + "secret" + THINK_CLOSE + "Answer"), "Answer")

    def test_thinking_variant(self):
        self.assertEqual(strip_reasoning("<thinking>x</thinking>Answer"), "Answer")

    def test_no_reasoning_is_noop(self):
        self.assertEqual(strip_reasoning("Just a normal answer."), "Just a normal answer.")

    def test_answer_before_and_after(self):
        self.assertEqual(strip_reasoning("Answer one.<think>mid</think> Answer two."), "Answer one. Answer two.")

    def test_orphan_open_tag_keeps_visible_text(self):
        # unterminated block: strip the stray tag but never delete the visible answer
        self.assertEqual(strip_reasoning("<think>leaked with no close"), "leaked with no close")

    def test_case_insensitive(self):
        self.assertEqual(strip_reasoning("<THINK>x</THINK>Answer"), "Answer")

    def test_none_passthrough(self):
        self.assertIsNone(strip_reasoning(None))

    def test_empty_passthrough(self):
        self.assertEqual(strip_reasoning(""), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
