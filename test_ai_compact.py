"""Tests for Gemini's dataset-only concise answer selection (no network calls)."""

import os
import unittest
from unittest.mock import patch

import ai_select
import knowledge_base as kb
from answer_memory import AnswerMemory


class CompactAnswerTests(unittest.TestCase):
    def setUp(self):
        self.rendered = (
            "## 4.5 ประเภทของคีย์ · 4. คีย์นอก (Foreign Key)\n"
            "คีย์นอก หมายถึง คีย์ที่อ้างอิงมาจากอีกตารางหนึ่งเพื่อใช้สำหรับการอ้างอิงความสัมพันธ์ของตาราง\n"
            "ตัวอย่างข้อความอีกส่วนที่ไม่จำเป็น\n\n"
            "แหล่งข้อมูล: ตำราการจัดการระบบฐานข้อมูลเพื่องานธุรกิจ · บทที่ 4 · หน้า 70\n"
            + kb.PARTIAL_MARK
        )

    @patch.object(ai_select, "enabled", return_value=True)
    @patch.object(ai_select, "_generate")
    def test_only_exact_dataset_quote_is_returned_and_citation_kept(self, generate, _enabled):
        quote = "คีย์นอก หมายถึง คีย์ที่อ้างอิงมาจากอีกตารางหนึ่งเพื่อใช้สำหรับการอ้างอิงความสัมพันธ์ของตาราง"
        generate.return_value = {"quotes": [quote]}

        answer = ai_select.compact_answer("คีย์นอกมีไว้ทำอะไร", self.rendered)

        self.assertIn(quote, answer)
        self.assertIn("## 4.5 ประเภทของคีย์", answer)
        self.assertIn("แหล่งข้อมูล: ตำรา", answer)
        self.assertNotIn("ตัวอย่างข้อความอีกส่วน", answer)
        self.assertNotIn(kb.PARTIAL_MARK, answer)

    @patch.object(ai_select, "enabled", return_value=True)
    @patch.object(ai_select, "_generate")
    def test_rejects_fabricated_quote_and_uses_caller_fallback(self, generate, _enabled):
        generate.return_value = {"quotes": ["คีย์นอก คือคีย์ลับที่ใช้เข้ารหัสข้อมูล"]}
        self.assertIsNone(ai_select.compact_answer("คีย์นอกคืออะไร", self.rendered))

    @patch.object(ai_select, "enabled", return_value=True)
    @patch.object(ai_select, "_generate")
    def test_does_not_call_gemini_for_out_of_dataset_answer(self, generate, _enabled):
        self.assertIsNone(ai_select.compact_answer("เรื่องนอกตำรา", kb.NO_DATA))
        generate.assert_not_called()

    def test_read_only_memory_does_not_block_live_selector(self):
        memory = AnswerMemory(os.devnull, writable=False)
        plan = kb.plan_answer("ทูเพิลคืออะไร")
        calls = []

        def selector(query):
            calls.append(query)
            return plan

        decided = kb._decide("ทูเพิลคืออะไร", plan, selector, memory)
        self.assertEqual(calls, ["ทูเพิลคืออะไร"])
        self.assertEqual(decided, plan)


if __name__ == "__main__":
    unittest.main()
