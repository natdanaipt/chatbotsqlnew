"""บทสนทนาต่อเนื่อง: ถามต่อสั้น ๆ ("ขอตัวอย่างเพิ่ม", "อธิบายเพิ่ม", "มันต่างกันยังไง") ต้องรู้ว่าคุยเรื่องอะไรอยู่
และยังตอบจากไฟล์ตำราเท่านั้น"""
import re
import unittest
from pathlib import Path
import knowledge_base as kb

BOOK = Path(kb.KNOWLEDGE_DIR, 'db_business_textbook_th.md').read_text(encoding='utf-8')


def chat(*messages):
    history, answers = [], []
    for m in messages:
        history.append({'role': 'user', 'content': m})
        answer = kb.answer_from_dataset(history)
        history.append({'role': 'assistant', 'content': answer})
        answers.append(answer)
    return answers


def topics(answer):
    return [line[3:] for line in answer.split('\n') if line.startswith('## ')]


class Conversation(unittest.TestCase):
    def test_more_examples_are_new_and_from_the_book(self):
        first, more, again = chat('GROUP BY', 'ขอตัวอย่างเพิ่ม', 'มีอีกไหม')
        self.assertTrue(more.startswith('ตัวอย่างเพิ่มเติมเรื่อง'))
        self.assertIn('GROUP BY', more)
        self.assertIn('### จาก 10.5 ', more)               # ตัวอย่าง GROUP BY ในบท JOIN
        self.assertNotIn('ตัวอย่างที่ 9.28', more)          # ไม่ซ้ำกับที่แสดงไปแล้วในหัวข้อ 9.11
        self.assertTrue(again.startswith('ตัวอย่างเพิ่มเติมเรื่อง'))   # "มีอีกไหม" ต่อจากตัวอย่าง = ขอตัวอย่างต่อ
        blocks = lambda a: {b.strip() for b in a.split('\n---\n') if b.strip().startswith('### จาก')}
        self.assertFalse(blocks(more) & blocks(again))      # ชุดถัดไปไม่ซ้ำชุดก่อน

    def test_every_topic_follow_up_is_verbatim_from_the_book(self):
        # ทุกหัวข้อ: ถามต่อ "ขอตัวอย่างเพิ่ม" และ "อธิบายเพิ่ม" แล้ว ทุกบรรทัดเนื้อหาต้องมีในไฟล์ตำราตรงตัว
        fixed = re.compile(r'^(ตัวอย่างเพิ่มเติมเรื่อง|ตัวอย่างเรื่อง|### จาก |แหล่งข้อมูล:|ยังมีอีก |---$|!\[ภาพที่|'
                           r'\[\[ถาม:|หัวข้อ(ใน|ที่เกี่ยวข้อง)|ในตำราไม่มีหัวข้ออื่น|เรื่อง \*\*)')
        for entry in kb.ENTRIES:
            for follow in ('ขอตัวอย่างเพิ่ม', 'อธิบายเพิ่ม'):
                answer = chat(entry['topic'], follow)[1]
                with self.subTest(topic=entry['topic'], follow=follow):
                    self.assertNotEqual(answer, kb.NO_DATA)
                    for line in answer.split('\n'):
                        if line.strip() and not fixed.match(line):
                            self.assertIn(line, BOOK)
                    for title in re.findall(r'^\[\[ถาม:(.+)\]\]$', answer, re.M):   # ปุ่มหัวข้อต้องเป็นหัวข้อจริง
                        self.assertIn('## ' + title + '\n', BOOK)

    def test_related_topics_for_more_info(self):
        answer = chat('GROUP BY', 'มีอะไรเพิ่มเติมที่เกี่ยวกับหัวข้อนี้ไหม')[1]
        self.assertIn('[[ถาม:9.10 กลุ่มฟังก์ชันสรุปข้อมูล (Aggregate Functions)]]', answer)
        self.assertNotIn('[[ถาม:9.11 ', answer)            # ไม่เสนอหัวข้อที่เพิ่งตอบไป

    def test_compare_uses_conversation(self):
        got = topics(chat('คีย์หลักคืออะไร', 'แล้วคีย์นอกล่ะ', 'มันต่างกันยังไง')[2])
        self.assertEqual(len(got), 2)
        self.assertTrue(got[0].startswith('4.5 ประเภทของคีย์ · 3. คีย์หลัก'))
        self.assertTrue(got[1].startswith('4.5 ประเภทของคีย์ · 4. คีย์นอก'))
        got = topics(chat('LEFT JOIN', 'แล้วมันต่างจาก INNER JOIN ยังไง')[1])
        self.assertEqual([t[:5] for t in got], ['บทสรุ'])                    # ช่วงที่ตำราเทียบสองเรื่องไว้เอง
        answer = chat('LEFT JOIN', 'แล้วมันต่างจาก INNER JOIN ยังไง')[1]
        self.assertEqual([c[:5] for c in re.findall(r'^\[\[ถาม:(.+)\]\]$', answer, re.M)], ['ขอตัว', 'บทสรุ', '10.6 ', '10.5 '])
        self.assertTrue(chat('LEFT JOIN', 'มันต่างกันยังไง')[1].startswith('ต้องการเทียบ'))

    def test_new_question_is_not_mixed_with_old_topic(self):
        # คำถามใหม่ที่ครบในตัวเอง ไม่เอาเรื่องที่คุยก่อนหน้ามาปน
        got = [t[:5] for t in topics(chat('GROUP BY', 'INNER JOIN กับ LEFT JOIN ต่างกันยังไง')[1])]
        self.assertEqual(got, ['บทสรุ'])                                   # ไม่มี 9.11 GROUP BY ปน
        self.assertEqual([t[:5] for t in topics(chat('GROUP BY', 'ขอตัวอย่าง LEFT JOIN')[1])], ['10.6 '])
        self.assertEqual(chat('ขอตัวอย่างเพิ่ม')[0], kb.NO_DATA)   # ยังไม่ได้คุยเรื่องอะไร


if __name__ == '__main__':
    unittest.main()
