"""ตอบเฉพาะส่วนที่ถาม (ไม่ดึงทั้งหัวข้อมาเมื่อถามเรื่องเดียว) และ AI ช่วยเลือกหัวข้อ/ย่อหน้าได้โดยไม่แต่งคำตอบเอง
ทดสอบแบบไม่ต่อเน็ต: ส่วนที่เรียก AI ใช้ตัวปลอมแทน Gemini (ทดสอบกับ Gemini จริงใช้ eval_questions.py --ai)"""
import json
import os
import re
import tempfile
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import knowledge_base as kb
import ai_select
import eval_questions as ev
from answer_memory import AnswerMemory

BOOK_LINES = set(Path(kb.KNOWLEDGE_DIR, 'db_business_textbook_th.md').read_text(encoding='utf-8').split('\n'))
FIXED = re.compile(r'^(## |แหล่งข้อมูล:|!\[ภาพที่ [\d.]+\]\(/static/figures/|\[\[ถาม:|---$|ตำราอธิบายแต่ละเรื่อง)')


def ask(q, selector=None, history=()):
    return kb.answer_from_dataset(list(history) + [{'role': 'user', 'content': q}], selector=selector)


def chat(*messages):
    """ถามต่อกันในบทสนทนาเดียว คืนคำตอบของแต่ละข้อ"""
    history, answers = [], []
    for m in messages:
        answers.append(ask(m, history=history))
        history += [{'role': 'user', 'content': m}, {'role': 'assistant', 'content': answers[-1]}]
    return answers


def temp_memory(test, writable=True):
    """ที่จำคำตอบชั่วคราวสำหรับทดสอบ (ไม่แตะ ai_answers.json ของจริง)"""
    fd, path = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    os.unlink(path)
    test.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
    return AnswerMemory(path, writable=writable, model='test-model')


def topic_index(prefix):
    return next(i for i, e in enumerate(kb.ENTRIES) if e['topic'].startswith(prefix))


class FakeGemini:
    """แทน ai_select._generate: ตอบตามที่กำหนด และจำว่าถูกเรียกด้วยอะไร"""
    def __init__(self, sections=(), paragraphs=(), error=None):
        self.sections, self.paragraphs, self.error, self.calls = list(sections), list(paragraphs), error, []

    def __call__(self, system, prompt, schema):
        self.calls.append((system, prompt))
        if self.error:
            raise self.error
        if system == ai_select.ROUTE_SYSTEM:
            return {'sections': self.sections}
        return {'paragraphs': self.paragraphs}


class FocusedAnswers(unittest.TestCase):
    def assertVerbatim(self, answer):
        """ทุกบรรทัดเนื้อหาในคำตอบต้องเป็นบรรทัดในไฟล์ตำราตรงตัว (ยกเว้นชื่อหัวข้อ ที่มา รูป ปุ่ม)"""
        for line in answer.split('\n'):
            if not line.strip() or FIXED.match(line) or line == kb.PARTIAL_NOTE:
                continue
            if line.startswith('… ') or line.endswith(' …'):       # ช่วงที่ตัดมาจากกลางย่อหน้า: เนื้อในต้องอยู่ในย่อหน้าของตำราตรงตัว
                inner = line.removeprefix('… ').removesuffix(' …')
                self.assertGreaterEqual(len(inner), 40)
                self.assertTrue(any(inner in book_line for book_line in BOOK_LINES), inner[:60])
            else:
                self.assertIn(line, BOOK_LINES)

    def test_question_sets(self):
        # หัวข้อตามสารบัญทุกหัวข้อ, หัวเรื่องย่อยในเนื้อหา, คำถามแบบพิมพ์เอง, คำถามนอกตำรา (ไม่นับข้อที่ต้องใช้ AI)
        for case in (ev.toc_cases(kb) + ev.HEADING_CASES + ev.REPORTED_CASES + ev.COMPARE_CASES + ev.NATURAL_CASES
                     + ev.PARAPHRASE_CASES + ev.OUTSIDE_CASES):
            if case.get('ai'):
                continue
            with self.subTest(q=case['q']):
                answer = ask(case['q'])
                self.assertEqual(ev.check(kb, case, answer), [])
                if answer != kb.NO_DATA:
                    self.assertVerbatim(answer)

    def test_meaning_is_only_the_definition(self):
        # ถามความหมาย ได้เฉพาะย่อหน้านิยาม ไม่แนบตัวอย่าง/รูป/ย่อหน้าของเรื่องอื่น (ตัวอย่างอยู่ที่ปุ่มต่อ)
        for q, own, other in [('สารสนเทศคืออะไร', 'สารสนเทศ (Information) หมายถึง', 'ข้อมูล (Data) หมายถึง'),
                              ('ความหมายของข้อมูล', 'ข้อมูล (Data) หมายถึง', 'สารสนเทศ (Information) หมายถึง')]:
            with self.subTest(q=q):
                answer = ask(q)
                self.assertIn(own, answer)
                self.assertNotIn(other, answer)
                self.assertNotIn('![ภาพที่', answer)
                self.assertLess(len(answer), 1500)
        chips = re.findall(r'^\[\[ถาม:(.+)\]\]$', ask('สารสนเทศคืออะไร'), re.M)
        self.assertEqual(chips[0], 'ตัวอย่างสารสนเทศ')                        # ปุ่มต่อ: ตัวอย่างของเรื่องนี้
        self.assertTrue(chips[-1].startswith('1.1 '))                        # ปุ่มสุดท้าย: อ่านทั้งหัวข้อ

    def test_example_button_gives_that_example_not_other_topics(self):
        # กดปุ่ม "ตัวอย่างสารสนเทศ" หลังคำตอบความหมาย ต้องได้ส่วนตัวอย่างสารสนเทศ (+รูป 1.2) ไม่ใช่ "ตัวอย่างเพิ่มเติมจากหัวข้ออื่น"
        history = [{'role': 'user', 'content': 'สารสนเทศคืออะไร'}, {'role': 'assistant', 'content': ask('สารสนเทศคืออะไร')}]
        answer = ask('ตัวอย่างสารสนเทศ', history=history)
        self.assertNotIn('ตัวอย่างเพิ่มเติม', answer)
        self.assertIn('![ภาพที่ 1.2](/static/figures/fig_1_2.webp)', answer)
        body = ev.content(kb, answer)
        self.assertNotIn('![ภาพที่ 1.3]', body)                              # จบที่คำอธิบายรูป 1.2 (รูป 1.3 อยู่ที่ปุ่ม)
        self.assertNotIn('ข้อมูล หมายถึงข้อมูลที่เกิดจากการรวบรวม', body)      # ไม่ลากไปถึงย่อหน้าสรุปทั้งหัวข้อ
        # ปุ่มรูป: "ภาพที่ 1.3 …" ที่ตามมา ถามได้ตรงตัว
        nxt = re.findall(r'^\[\[ถาม:(ภาพที่ 1\.3.*)\]\]$', answer, re.M)
        self.assertEqual(len(nxt), 1)
        self.assertIn('![ภาพที่ 1.3]', ask(nxt[0], history=history))

    def test_figures_and_tables_by_number_or_name(self):
        by_name = ask('ชุดข้อมูลที่ยังไม่มีความหมาย')       # "ความหมาย" อยู่ในชื่อภาพ ไม่ใช่คำถามว่าความหมาย
        self.assertIn('![ภาพที่ 1.1](/static/figures/fig_1_1.webp)', by_name)
        self.assertNotIn('สารสนเทศ (Information) หมายถึง', by_name)
        self.assertEqual(by_name, ask('ภาพที่ 1.1'))
        self.assertEqual(ask('รูปที่ 1.1'), ask('ภาพที่ 1.1'))
        fig = ask('ภาพที่ 1.4')                              # เลขภาพ 1.4 อยู่ในหัวข้อ 1.3 ไม่ใช่หัวข้อ 1.4
        self.assertTrue(fig.startswith('## 1.3 '))
        table = ask('ตารางที่ 4.3')
        self.assertIn('P0010 | สายยางรดน้ำ', table)
        self.assertNotIn('คุณสมบัติของรีเลชันที่สำคัญ', table)
        self.assertEqual(ask('ภาพที่ 99.9'), kb.NO_DATA)

    def test_politeness_words_are_not_cut_from_the_middle_of_words(self):
        # "จ้า/คะ/นะ" ตัดเฉพาะท้ายคำ: "เจ้าของ" "คะแนน" ต้องอยู่ครบ (เคยได้ "ความเป็นเ ของ" แล้วตอบหัวข้อผิด)
        self.assertEqual(kb._asked_terms('ความเป็นเจ้าของคืออะไรครับ'), ['ความเป็นเจ้าของ'])
        self.assertEqual(kb._asked_terms('คะแนนสอบคืออะไรนะคะ'), ['คะแนนสอบ'])
        self.assertTrue(ask('ความเป็นเจ้าของคืออะไร').startswith('## 12.1 '))

    def test_how_does_it_look_asks_for_the_definition(self):
        answer = ask('big data มีลักษณะยังไง')
        for v in ('Volume', 'Velocity', 'Variety'):
            self.assertIn(v, answer)
        self.assertNotIn('Tesco Lotus', answer)                       # ไม่ลากไปถึงกรณีศึกษาของหัวข้อ

    def test_comparison_shows_what_the_book_compares(self):
        # ตำราเทียบ INNER/LEFT ไว้เองในบทสรุปบทที่ 10 (ย่อหน้าเดียวพูดถึง JOIN ทุกชนิด): ได้เฉพาะช่วงที่พูดถึงสองเรื่องนี้
        answer = ask('inner join กับ left join ต่างกันยังไง')
        heads = [l[3:] for l in answer.split('\n') if l.startswith('## ')]
        self.assertEqual(len(heads), 1)
        self.assertTrue(heads[0].startswith('บทสรุป บทที่ 10'))
        body = ev.content(kb, answer)
        self.assertIn('INNER JOINจะใส่เงื่อนไขหลังคำสั่ง ON ส่วนวิธีการเลือกข้อมูลแบบ LEFT JOIN จะเน้น', body)
        self.assertNotIn('RIGHT JOIN', body)                                  # ท่อนของ JOIN ชนิดอื่นไม่ติดมา
        self.assertTrue(body.strip().endswith(' …'))                          # บอกว่าตัดมาจากกลางย่อหน้า
        self.assertLess(len(body), 400)
        chips = re.findall(r'^\[\[ถาม:(.+)\]\]$', answer, re.M)             # ปุ่มขอตัวอย่าง + อ่านหัวข้อเต็มของแต่ละฝั่ง
        self.assertEqual([c[:5] for c in chips], ['ขอตัว', 'บทสรุ', '10.5 ', '10.6 '])
        self.assertEqual(ask('innerjoin กับ left join ต่างกันยังไง'), answer)   # พิมพ์ติดกันได้คำตอบเดียวกัน

    def test_comparison_without_a_comparing_paragraph_shows_both_definitions(self):
        # ตำราไม่ได้เทียบคีย์หลักกับคีย์นอกไว้: นิยามของสองฝั่งคู่กัน (ย่อหน้าเดียวต่อฝั่ง) ไม่เดาความต่างเอง
        answer = ask('คีย์หลักกับคีย์นอกต่างกันยังไง')
        heads = [l[3:] for l in answer.split('\n') if l.startswith('## ')]
        self.assertEqual(len(heads), 2)
        self.assertTrue(heads[0].startswith('4.5 ประเภทของคีย์ · 3. คีย์หลัก'))
        self.assertTrue(heads[1].startswith('4.5 ประเภทของคีย์ · 4. คีย์นอก'))
        body = ev.content(kb, answer)
        self.assertNotIn('4) คีย์นอก ไม่จำเป็น', body)        # ข้อย่อยที่แค่เอ่ยถึงทั้งสองคำ ไม่ใช่การเทียบ
        self.assertNotIn('ตารางที่ 4.18', body)                # ไม่มีตารางตัวอย่างของฝั่งใดฝั่งหนึ่ง

    def test_comparison_shows_only_the_opening_of_each_side(self):
        # ผู้ใช้รายงานว่าคำตอบเปรียบเทียบยังยาว: เหลือแค่ใจความเปิดของแต่ละเรื่อง ตัดก่อน "เช่น …" และรายละเอียดต่อท้าย
        answer = ask('คีย์หลักกับคีย์นอกต่างกันยังไง')
        sides = [l for l in ev.content(kb, answer).split('\n') if l.strip()]
        self.assertEqual(len(sides), 2)
        self.assertTrue(sides[0].startswith('คีย์หลัก หมายถึง คีย์ที่มีความเป็นเอกลักษณ์'))
        self.assertTrue(sides[1].startswith('คีย์นอก หมายถึง คีย์ที่อ้างอิงมากจากอีกตารางหนึ่ง'))
        for side in sides:
            self.assertTrue(side.endswith(' …'))                 # บอกว่าย่อหน้ายังมีต่อ
            self.assertLessEqual(len(side), kb.COMPARE_SIDE_MAX + kb.COMPARE_SLACK + 2)
            self.assertNotIn('เช่น', side)
        self.assertNotIn('ตารางแผนกและตารางพนักงาน', answer)    # ตัวอย่างของคีย์นอกไม่ติดมา
        self.assertVerbatim(answer)
        # ตัดได้เฉพาะรอยต่อประโยค: ท่อนที่แสดงจบก่อนคำเชื่อม/ตัวอย่างในย่อหน้าของตำราพอดี
        line = next(l for l in BOOK_LINES if l.startswith('คีย์นอก หมายถึง'))
        self.assertTrue(line[len(sides[1]) - 2:].lstrip().startswith('เช่น'))
        chips = re.findall(r'^\[\[ถาม:(.+)\]\]$', answer, re.M)
        self.assertEqual(chips[0], kb.EXAMPLE_CHIP)                # ตัวอย่างไม่แสดงมาเอง ผู้ใช้ขอเองได้
        self.assertEqual([c[:21] for c in chips[1:]], ['4.5 ประเภทของคีย์ · 3', '4.5 ประเภทของคีย์ · 4'])
        # ย่อหน้าสั้นที่ไม่มีตัวอย่างแสดงทั้งย่อหน้า ไม่มี …
        self.assertNotIn(' …', ev.content(kb, ask('สกีมากับอินสแตนซ์ต่างกันยังไง')))

    def test_examples_are_given_when_asked_after_a_comparison(self):
        # กดปุ่ม/พิมพ์ "ขอตัวอย่าง" ต่อจากคำตอบเปรียบเทียบ: ได้ตัวอย่างที่ตัดออกไปของเรื่องนั้นก่อน ไม่แสดงต้นย่อหน้าซ้ำ
        first, examples = chat('คีย์หลักกับคีย์นอกต่างกันยังไง', kb.EXAMPLE_CHIP)
        blocks = examples.split('\n\n---\n\n')
        self.assertTrue(blocks[0].startswith('ตัวอย่างเพิ่มเติมเรื่อง **คีย์หลัก / คีย์นอก**'))
        self.assertTrue(blocks[1].startswith('### จาก 4.5 ประเภทของคีย์ · 4. คีย์นอก (Foreign Key)\n\n… เช่น ตารางแผนกและตารางพนักงาน'))
        self.assertNotIn('คีย์นอก หมายถึง', blocks[1])
        first, examples = chat('one to one กับ one to many ต่างกันยังไง', kb.EXAMPLE_CHIP)
        self.assertIn('… เช่น เอ็นทิตี้ “พนักงาน”', examples)
        self.assertIn('… เช่น เอ็นทิตี้ “ประเภทสินค้า”', examples)
        self.assertNotIn('จาก 4.', examples)                       # ไม่ลากตัวอย่างของหัวข้ออื่นมาก่อน
        # หัวตัวอย่างมาพร้อมเนื้อตัวอย่าง ไม่ใช่บรรทัดหัวอย่างเดียว
        first, examples = chat('1NF กับ 2NF ต่างกันยังไง', kb.EXAMPLE_CHIP)
        self.assertIn('ตัวอย่างที่ 1 การวิเคราะห์นอมอลฟอร์มระดับที่ 2 (2NF)\nจากตารางต่อไปนี้', examples)
        self.assertNotIn('พิจารณาได้จากตัวอย่างดังต่อไปนี้\n\nแหล่งข้อมูล', examples)   # บรรทัดเกริ่นไม่ใช่ตัวอย่าง
        # ไม่มีตัวอย่างให้ขอ ก็ไม่มีปุ่ม
        self.assertNotIn(kb.EXAMPLE_CHIP, ask('คีย์หลักคืออะไร'))

    def test_comparison_that_cannot_be_built_stays_short(self):
        # หาตัวนิยามได้ไม่ครบทุกฝั่ง: เดิมยกทั้งหัวข้อ 5.3 พร้อมหัวข้อย่อยทุกส่วน (9,500 ตัวอักษร)
        answer = ask('เอนทิตีแบบอ่อนกับแบบแข็งต่างกันยังไง')
        self.assertLess(len(ev.content(kb, answer)), 300)
        self.assertIn('เอ็นทิตี้แบบอ่อนแอ (Weak Entities) หมายถึง', answer)
        self.assertIn('[[ถาม:5.3 เอ็นทิตี้]]', answer)             # อ่านทั้งหัวข้อได้จากปุ่ม
        answer = ask('union กับ join ต่างกันยังไง')                 # ตำราไม่มี UNION: ส่วนที่เจอก็ยังสั้น ไม่มีโค้ดตัวอย่าง
        self.assertLess(len(ev.content(kb, answer)), 300)
        self.assertNotIn('```', answer)
        # แผนจากการตีความ (AI/คำตอบที่จำไว้) ที่เลือกมาทั้งหัวข้อ: คำตอบเปรียบเทียบก็ยังแสดงแค่ใจความเปิดของแต่ละหัวข้อ
        parts = [e for e in kb.ENTRIES if e['topic'].startswith(('5.3 เอ็นทิตี้ · 1.', '5.3 เอ็นทิตี้ · 2.'))]
        answer = kb.render_plan(kb._brief_plan([(parts[0], None), (parts[1], [])]))
        self.assertEqual([l[3:21] for l in answer.split('\n') if l.startswith('## ')], ['5.3 เอ็นทิตี้ · 1.', '5.3 เอ็นทิตี้ · 2.'])
        self.assertIn('เอ็นทิตี้แบบปกติ (Strong Entities)', answer)
        self.assertLess(len(ev.content(kb, answer)), 600)
        self.assertNotIn('ภาพที่ 5.4', answer)
        self.assertVerbatim(answer)

    def test_excerpts_survive_the_answer_memory(self):
        # แผนที่มีช่วงของย่อหน้า (เลข, เริ่ม, จบ) เก็บลง ai_answers.json แล้วอ่านกลับได้คำตอบเดิม
        plan = kb.plan_answer('คีย์หลักกับคีย์นอกต่างกันยังไง')
        self.assertTrue(any(isinstance(k, tuple) for _, picked in plan for k in picked))
        stored = json.loads(json.dumps(kb.plan_to_json(plan)))
        self.assertEqual(kb.render_plan(kb.plan_from_json(stored)), kb.render_plan(plan))
        stored[0]['picked'][0][2] = 10 ** 6                        # ช่วงเกินย่อหน้า (ตำราเปลี่ยน) ใช้ไม่ได้
        self.assertIsNone(kb.plan_from_json(stored))

    def test_comparison_never_dumps_whole_sections(self):
        # เดิมยกทั้งหัวข้อ: where/having ได้ทั้ง 9.11 (1,901), count/sum ได้ทั้ง 9.10 (3,643), ข้อมูล/สารสนเทศ 2,500
        for q, limit in [('where กับ having ต่างกันยังไง', 400), ('count กับ sum ต่างกันยังไง', 500),
                         ('ข้อมูลกับสารสนเทศต่างกันยังไง', 900), ('one to one กับ one to many ต่างกันยังไง', 700)]:
            with self.subTest(q=q):
                self.assertLess(len(ev.content(kb, ask(q)).strip()), limit)

    def test_partial_answer_offers_the_whole_topic(self):
        answer = ask('ทูเพิลคืออะไร')
        topic = next(e for e in kb.ENTRIES if e['topic'].startswith('4.4 '))
        self.assertIn(kb.PARTIAL_NOTE, answer)
        self.assertIn(f"[[ถาม:{topic['topic']}]]", answer)
        # แตะปุ่ม = ถามด้วยชื่อหัวข้อเต็ม ได้ทั้งหัวข้อ
        self.assertIn(kb.with_figures(topic['description']), ask(topic['topic']))
        # พิมพ์ "อธิบายเพิ่ม" ต่อจากคำตอบบางส่วน ก็ได้ทั้งหัวข้อเช่นกัน
        history = [{'role': 'user', 'content': 'ทูเพิลคืออะไร'}, {'role': 'assistant', 'content': answer}]
        self.assertIn(kb.with_figures(topic['description']), ask('อธิบายเพิ่ม', history=history))
        # ถามหัวข้อที่เกี่ยวข้อง ยังได้ปุ่มหัวข้ออื่นเหมือนเดิม
        related = ask('มีหัวข้ออะไรที่เกี่ยวข้องอีกไหม', history=history)
        self.assertIn('[[ถาม:', related)
        self.assertNotIn(topic['description'], related)

    def test_short_topic_is_shown_whole(self):
        answer = ask('คีย์หลักคืออะไร')
        topic = next(e for e in kb.ENTRIES if e['topic'].startswith('4.5 ประเภทของคีย์ · 3.'))
        self.assertIn(kb.with_figures(topic['description']), answer)
        self.assertNotIn(kb.PARTIAL_NOTE, answer)

    def test_definition_index(self):
        # ศัพท์ที่นิยามไว้ในเนื้อหา (ไม่ใช่ชื่อหัวข้อ) ต้องหาเจอ และประโยคที่แค่หน้าตาเหมือนนิยามต้องไม่ถูกนับ
        index = kb.definitions()
        for term, where in [('ทูเพิล', '4.4 '), ('DDL', '8.1 '), ('ฟิลด์', '1.3 '), ('บิต', '1.3 '), ('AI', '11.6 '),
                            ('Deletion Anomaly', '1.6 '), ('สคีมา', '3.9 ')]:
            with self.subTest(term=term):
                self.assertTrue(any(e['topic'].startswith(where) for e, _, _ in index[kb._term_key(term)]))
        self.assertNotIn(kb._term_key('Petersen, 2018'), index)                  # วงเล็บอ้างอิง
        self.assertFalse(any(e['topic'].startswith('7.4 ') for e, _, _ in index[kb._term_key('Partial Dependency')]))


class AiSelector(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'})
        env.start()
        self.addCleanup(env.stop)

    def use(self, fake):
        p = patch.object(ai_select, '_generate', fake)
        p.start()
        self.addCleanup(p.stop)
        return fake

    def test_ai_returns_only_numbers_and_text_comes_from_the_book(self):
        i = topic_index('9.10 ')
        n = len(kb.units(kb.ENTRIES[i]))
        fake = self.use(FakeGemini(sections=[i, 999, -1, 'x'],
                                   paragraphs=[f'{i}.0', f'[{i}.1]', f'{i}.{n + 50}', '3.1', 'แต่งคำตอบเอง']))
        answer = ask('นับจำนวนแถวในตาราง', selector=ai_select.plan_answer)
        self.assertEqual(len(fake.calls), 2)                        # เลือกหัวข้อ แล้วเลือกย่อหน้า
        self.assertIn('คำถาม: นับจำนวนแถวในตาราง', fake.calls[0][1])
        self.assertEqual([l[3:] for l in answer.split('\n') if l.startswith('## ')], [kb.ENTRIES[i]['topic']])
        self.assertNotIn('แต่งคำตอบเอง', answer)
        self.assertIn(kb.PARTIAL_NOTE, answer)
        FocusedAnswers.assertVerbatim(self, answer)

    def test_catalog_lists_terms_defined_inside_topics(self):
        catalog = ai_select._catalog()
        line = next(l for l in catalog.split('\n') if '4.4 โครงสร้างฐานข้อมูลเชิงสัมพันธ์' in l)
        self.assertIn('ทูเพิล', line)
        self.assertEqual(len(catalog.split('\n')), len(kb.ENTRIES))

    def test_ai_failure_falls_back_to_search(self):
        error = urllib.error.HTTPError('https://x', 429, 'Too Many Requests', {}, BytesIO(b'{"error": "quota"}'))
        self.use(FakeGemini(error=error))
        for q in ['ชนิดข้อมูลใน SQL มีอะไรบ้าง', 'GROUP BY ใช้ยังไง', 'ราคาทองวันนี้']:
            with self.subTest(q=q):
                self.assertEqual(ask(q, selector=ai_select.plan_answer), ask(q))

    def test_ai_says_not_in_book(self):
        self.use(FakeGemini(sections=[]))
        self.assertEqual(ask('ราคาทองวันนี้', selector=ai_select.plan_answer), kb.NO_DATA)
        # AI ว่าไม่มี แต่ค้นจากชื่อหัวข้อเจอ ใช้ผลค้นแบบเดิม (AI ตัดคำตอบที่มีในตำราทิ้งไม่ได้)
        self.assertEqual(ask('GROUP BY ใช้ยังไง', selector=ai_select.plan_answer), ask('GROUP BY ใช้ยังไง'))

    def test_confident_questions_do_not_use_ai(self):
        fake = self.use(FakeGemini(sections=[0]))
        for q in ['ทูเพิลคืออะไร', '7.5', 'ชนิดของแฟ้มข้อมูล', 'ข้อดีของแบบจำลองฐานข้อมูลเชิงสัมพันธ์',
                  kb.ENTRIES[5]['topic'], 'INNER JOIN กับ LEFT JOIN ต่างกันยังไง']:
            ask(q, selector=ai_select.plan_answer)
        self.assertEqual(fake.calls, [])

    def test_topic_without_picked_paragraphs_is_shown_whole(self):
        # AI เลือกหัวข้อแต่ไม่เลือกย่อหน้า (เคยเกิดกับคำถามเทียบ) ต้องไม่ตัดหัวข้อนั้นทิ้ง
        i, j = topic_index('10.5 '), topic_index('10.6 ')
        self.use(FakeGemini(sections=[i, j], paragraphs=[]))
        answer = ask('join สองแบบนี้ใช้ต่างกันตรงไหน', selector=ai_select.plan_answer)
        self.assertIn(kb.with_figures(kb.ENTRIES[i]['description']), answer)
        self.assertIn(kb.with_figures(kb.ENTRIES[j]['description']), answer)

    def test_topic_the_ai_read_and_rejected_is_dropped(self):
        # AI เลือกหลายหัวข้อ แต่พออ่านเนื้อหาแล้วเลือกย่อหน้าจากหัวข้อเดียว: หัวข้อที่แค่ชื่อคล้ายไม่ถูกแสดง
        appendix, security = topic_index('ภาคผนวก ข 1.'), topic_index('12.5 ')
        us = kb.units(kb.ENTRIES[security])
        k = next(k for k, u in enumerate(us) if 'Encrypt with Password' in u)
        fake = self.use(FakeGemini(sections=[appendix, security], paragraphs=[f'{security}.{k}']))
        answer = ask('ล็อกไฟล์ฐานข้อมูลไม่ให้คนอื่นเปิด', selector=ai_select.plan_answer)
        self.assertIn(appendix, [int(x) for x in re.findall(r'\[(\d+)\.\d+\]', fake.calls[1][1])])  # AI ได้อ่านเนื้อหาจริง
        self.assertEqual([l[3:] for l in answer.split('\n') if l.startswith('## ')], [kb.ENTRIES[security]['topic']])
        self.assertIn('Encrypt with Password', answer)

    def test_term_the_book_does_not_explain_stays_no_data(self):
        # ค้นเองไม่เจอ + AI เลือกหัวข้อที่ไม่มีคำว่า MySQL เลย (2.3 ระบบจัดการฐานข้อมูล) -> ยังตอบว่าไม่มีข้อมูล
        i = topic_index('2.3 ')
        self.use(FakeGemini(sections=[i], paragraphs=[f'{i}.0']))
        self.assertEqual(ask('MySQL คืออะไร', selector=ai_select.plan_answer), kb.NO_DATA)
        # ศัพท์ที่อยู่ในย่อหน้าที่ AI เลือกจริง ใช้คำตอบของ AI ได้
        j = topic_index('1.3 ')
        k = next(k for k, u in enumerate(kb.units(kb.ENTRIES[j])) if u.startswith('3) เรคอร์ดหรือระเบียน'))
        self.use(FakeGemini(sections=[j], paragraphs=[f'{j}.{k}']))
        self.assertIn('## 1.3 ', ask('ระเบียนข้อมูลในตารางคืออะไร', selector=ai_select.plan_answer))

    def test_exercise_page_does_not_replace_a_real_topic(self):
        # AI สุ่มพลาดเลือกแบบฝึกหัดท้ายบท ทั้งที่ค้นเองเจอหัวข้อเนื้อหา -> ใช้หัวข้อเนื้อหา
        self.use(FakeGemini(sections=[topic_index('แบบฝึกหัดท้ายบท บทที่ 9')]))
        self.assertEqual(ask('GROUP BY ใช้ยังไง', selector=ai_select.plan_answer), ask('GROUP BY ใช้ยังไง'))
        self.assertIn('แบบฝึกหัดท้ายบท', ask('แบบฝึกหัด GROUP BY', selector=ai_select.plan_answer))

    def test_parts_are_not_repeated(self):
        # AI เลือกทั้งหัวข้อหลัก 4.5 และหัวข้อย่อยของมัน ต้องแสดงแต่ละส่วนครั้งเดียว
        i = topic_index('4.5 ประเภทของคีย์')
        self.use(FakeGemini(sections=[i, i + 1, i + 2]))
        answer = ask('คีย์ในฐานข้อมูลแบ่งเป็นแบบไหนได้บ้าง', selector=ai_select.plan_answer)
        for e in kb.section_parts(kb.ENTRIES[i]):
            self.assertEqual(answer.count('## ' + e['topic'] + '\n'), 1)

    def test_definition_found_needs_one_call(self):
        fake = self.use(FakeGemini(sections=[topic_index('4.4 ')]))
        first = ai_select.plan_answer('ทูเพิลคืออะไร')
        self.assertEqual(len(fake.calls), 1)              # ย่อหน้านิยามหาเองได้ ไม่ต้องให้ AI เลือกย่อหน้า
        self.assertIn('ทูเพิล หมายถึง', kb.render_plan(first))

    def test_attach_keeps_figure_with_its_explanation(self):
        e = kb.ENTRIES[topic_index('1.1 ')]
        us = kb.units(e)
        explain = next(k for k, u in enumerate(us) if u.startswith('จาก ภาพที่ 1.2'))
        caption = next(k for k, u in enumerate(us) if u.startswith('ภาพที่ 1.2'))
        self.assertIn(caption, ai_select.attach(us, [explain]))

    def test_web_app_uses_ai_only_with_key(self):
        import app as application
        i = topic_index('9.10 ')
        self.use(FakeGemini(sections=[i], paragraphs=[f'{i}.0']))
        post = lambda client: client.post('/chat/stream', json={'message': 'นับจำนวนแถวในตาราง'}).get_data(as_text=True)
        with application.app.test_client() as client, patch.object(application, 'save_web_chat'):
            with patch.object(application, 'answer_memory', temp_memory(self)):
                self.assertIn('## 9.10 ', post(client))
                with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
                    self.assertIn('## 9.10 ', post(client))      # ถอด key แล้วก็ยังได้คำตอบเดิมที่จำไว้
            with patch.object(application, 'answer_memory', temp_memory(self)), \
                    patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
                self.assertIn('## 9.10 ', post(client))      # ไม่มี key และไม่เคยจำ: วิธีค้นเอง


class ChangingAI:
    """AI ที่ตอบไม่เหมือนเดิมทุกครั้ง (แบบที่ AI ทำจริง): แต่ละครั้งเลือกหัวข้อถัดไปในรายการ"""
    def __init__(self, *prefixes, error_first=False):
        self.sections = [topic_index(p) for p in prefixes]
        self.error_first, self.calls, self.routes = error_first, [], 0

    def __call__(self, system, prompt, schema):
        self.calls.append(system)
        if self.error_first and len(self.calls) == 1:
            raise urllib.error.URLError('network down')
        if system == ai_select.ROUTE_SYSTEM:
            self.routes += 1
            return {'sections': [self.sections[(self.routes - 1) % len(self.sections)]]}
        return {'paragraphs': []}


class SameAnswerEveryTime(unittest.TestCase):
    """ถามคำถามเดิมกี่รอบก็ต้องได้คำตอบเดิม แม้ AI จะตอบไม่เหมือนเดิมทุกครั้ง"""
    Q = 'หาค่าเฉลี่ยใน sql ใช้คำสั่งอะไร'

    def setUp(self):
        env = patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'})
        env.start()
        self.addCleanup(env.stop)

    def use(self, fake):
        p = patch.object(ai_select, '_generate', fake)
        p.start()
        self.addCleanup(p.stop)
        return fake

    def ask(self, q, memory):
        return kb.answer_from_dataset([{'role': 'user', 'content': q}], selector=ai_select.plan_answer, memory=memory)

    def test_ai_itself_is_not_repeatable(self):
        # ไม่มีที่จำคำตอบ: AI ตอบต่างกันแต่ละรอบ คำตอบของบอทก็ต่างตาม (ปัญหาที่ต้องแก้)
        self.use(ChangingAI('9.10 ', '1.2 '))
        self.assertNotEqual(ask(self.Q, selector=ai_select.plan_answer), ask(self.Q, selector=ai_select.plan_answer))

    def test_same_question_same_answer(self):
        fake = self.use(ChangingAI('9.10 ', '1.2 ', '8.6 '))
        memory = temp_memory(self)
        first = self.ask(self.Q, memory)
        routes = fake.routes
        for q in [self.Q, self.Q + 'ครับ', self.Q + ' ?', 'หาค่าเฉลี่ย ใน SQL ใช้คำสั่งอะไร', self.Q]:
            self.assertEqual(self.ask(q, memory), first)
        self.assertEqual(fake.routes, routes)             # ถามซ้ำไม่เรียก AI อีก
        self.assertIn('## 9.10 ', first)

    def test_answer_survives_restart(self):
        fake = self.use(ChangingAI('9.10 ', '1.2 '))
        memory = temp_memory(self)
        first = self.ask(self.Q, memory)
        again = AnswerMemory(memory.path, writable=True)   # เปิดเซิร์ฟเวอร์ใหม่ อ่านไฟล์เดิม
        calls = len(fake.calls)
        self.assertEqual(self.ask(self.Q, again), first)
        self.assertEqual(len(fake.calls), calls)
        saved = json.loads(Path(memory.path).read_text(encoding='utf-8'))
        self.assertEqual(saved['book'], kb.DOCUMENT_META['markdown_sha256'])
        entry = saved['answers'][kb.question_key(self.Q)]
        self.assertEqual(entry['plan'][0]['topic'], kb.ENTRIES[topic_index('9.10 ')]['topic'])
        self.assertEqual(entry['source'], 'AI test-model')

    def test_answer_given_while_ai_was_down_is_kept(self):
        # ครั้งแรก AI ใช้ไม่ได้ ตอบด้วยวิธีค้นเอง -> ครั้งต่อไป AI กลับมาแล้วก็ยังตอบแบบเดิม ไม่เปลี่ยนเอง
        self.use(ChangingAI('9.10 ', error_first=True))
        memory = temp_memory(self)
        first = self.ask(self.Q, memory)
        self.assertEqual(first, ask(self.Q))              # ตรงกับวิธีค้นเอง
        self.assertEqual(self.ask(self.Q, memory), first)
        self.assertIn('ค้นเอง', memory.get(kb.question_key(self.Q), kb.DOCUMENT_META['markdown_sha256'])['source'])

    def test_read_only_memory_never_calls_ai_live(self):
        # บน Vercel (อ่านอย่างเดียว): คำถามที่จำไว้ได้คำตอบที่จำ คำถามใหม่ได้วิธีค้นเอง ไม่เรียก AI สด
        book = kb.DOCUMENT_META['markdown_sha256']
        pinned = temp_memory(self)
        pinned.put(kb.question_key(self.Q), book, [{'topic': kb.ENTRIES[topic_index('9.10 ')]['topic'], 'picked': None}], 'AI')
        site = AnswerMemory(pinned.path, writable=False)
        fake = self.use(ChangingAI('1.2 '))
        self.assertIn('## 9.10 ', self.ask(self.Q, site))
        other = 'GROUP BY ใช้ยังไง'
        self.assertEqual(self.ask(other, site), ask(other))
        self.assertEqual(fake.calls, [])

    def test_stale_memory_is_ignored(self):
        memory = temp_memory(self)
        topic = kb.ENTRIES[topic_index('9.10 ')]['topic']
        memory.put(kb.question_key(self.Q), 'old-book', [{'topic': topic, 'picked': None}], 'AI')
        fake = self.use(ChangingAI('1.2 '))
        self.assertIn('## 1.2 ', self.ask(self.Q, memory))      # ตำราเปลี่ยน คำตอบเก่าใช้ไม่ได้
        self.assertEqual(fake.routes, 1)
        book = kb.DOCUMENT_META['markdown_sha256']
        memory.put(kb.question_key(self.Q), book, [{'topic': 'หัวข้อที่ไม่มีแล้ว', 'picked': None}], 'AI')
        self.assertIn('## 1.2 ', self.ask(self.Q, memory))      # อ้างหัวข้อที่ไม่มี -> ตอบใหม่
        self.assertIsNone(kb.plan_from_json([{'topic': topic, 'picked': [99999]}]))

    def test_confident_questions_are_not_stored(self):
        memory = temp_memory(self)
        for q in ['ทูเพิลคืออะไร', '7.5', 'ชนิดของแฟ้มข้อมูล']:
            self.ask(q, memory)
        self.assertEqual(memory.data['answers'], {})             # วิธีค้นเองได้ผลเดิมทุกครั้งอยู่แล้ว

    def test_question_key(self):
        for a, b in [('SQL คืออะไร', 'sql คืออะไรครับ?'), ('sql คืออะไร', 'sql  คือ อะไร'),
                     ('หาค่าเฉลี่ยใน sql ใช้คำสั่งอะไร', 'หาค่าเฉลี่ย ใน SQL ใช้คำสั่งอะไรนะคะ')]:
            self.assertEqual(kb.question_key(a), kb.question_key(b))
        self.assertEqual(kb.question_key('คะแนนสอบ'), 'คะแนนสอบ')   # "คะ" ในคำไม่ถูกตัด


if __name__ == '__main__':
    unittest.main()
