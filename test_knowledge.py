import json
import unittest
from pathlib import Path
import knowledge_base as kb


class DatasetTests(unittest.TestCase):
    def test_appendix_b_question_set(self):
        cases = json.loads((Path(__file__).with_name('appendix_b_questions.json')).read_text(encoding='utf-8'))
        self.assertEqual(len(cases), 110)
        # ตรวจจากเนื้อหาตำราจริง: บางข้อในตารางระบุบทไม่ตรงกับตำแหน่งนิยามในเล่ม
        topic_overrides = {7: '2.2 ', 11: '12.4 ', 13: '3.3 ', 14: '4.6 ', 21: '8.1 ', 96: '11.5 '}
        # ตารางจัดเป็นคำถามในขอบเขต แต่ handbook ที่แชทบอตใช้อยู่ไม่มีเนื้อหาอธิบายหัวข้อเหล่านี้
        absent_from_handbook = {71, 73, 75}
        for case in cases:
            qid, query, scope = case['id'], case['question'], case['scope']
            with self.subTest(id=qid, query=query):
                answer = kb.answer_from_dataset([{'role': 'user', 'content': query}])
                topics = [line[3:] for line in answer.splitlines() if line.startswith('## ')]
                if qid in absent_from_handbook or (scope != 'ในขอบเขต' and qid != 96):
                    self.assertEqual(answer, kb.NO_DATA)
                    continue
                chapter = topic_overrides.get(qid, case['chapter'])
                if qid == 96:  # Machine Learning มีเนื้อหาจริงในหัวข้อ 11.5 แม้ตารางจัดเป็นนอกขอบเขต
                    chapter = '11.5 '
                self.assertTrue(topics, f'คำถามในตำราได้ NO_DATA: {query}')
                self.assertTrue(any(t.startswith(chapter + '.') or t.startswith(chapter)
                                    or t.startswith('บทที่ ' + chapter + ' ') for t in topics),
                                f'ต้องการบท {chapter}, ได้ {topics}')
                self.assertTrue(any(line.startswith('แหล่งข้อมูล:') for line in answer.splitlines()))

    def test_natural_language_questions_from_user_test_set(self):
        # คำถามที่ใช้ทดสอบ chatbot: ต้องค้นเจอหัวข้อที่ถูกต้องและแสดงหลักฐานจากตำรา
        cases = [
            ('สารสนเทศคืออะไร', '1.1 ', ['สารสนเทศ (Information) หมายถึง']),
            ('ข้อมูลกับสารสนเทศต่างกันอย่างไร', '1.1 ', ['ข้อมูล หมายถึง', 'สารสนเทศ คือข้อมูลที่ผ่านการประมวลผล']),
            ('สารสนเทศที่ดีควรมีคุณสมบัติอะไรบ้าง', '1.1 ',
             ['มีความถูกต้องรวดเร็วและเป็นปัจจุบัน', 'มีความสมบูรณ์ของข้อมูล', 'สอดคล้องกับความต้องการ']),
            ('ข้อมูลวันที่และเวลามีตัวอย่างอะไรบ้าง', '1.2 ', ['วันเกิด', 'วันที่ซื้อสินค้า']),
            ('ข้อมูลเสียงใช้เก็บข้อมูลแบบใด', '1.2 ', ['เพลง', 'การสัมภาษณ์', 'การตรวจคลื่นหัวใจ']),
            ('ทำไมการเก็บข้อมูลแยกแฟ้มจึงทำให้รวบรวมข้อมูลล่าช้า', '1.6 ข้อจำกัดของวิธีแฟ้มข้อมูล · 1.',
             ['รวบรวมข้อมูลเกิดความล่าช้า', 'ความล่าช้าในการประมวลผล']),
            ('ถ้าต้องการระบุข้อมูลแต่ละแถวในตาราง ควรใช้คีย์อะไร', '4.5 ประเภทของคีย์ · 3.',
             ['คีย์หลัก (Primary Key)', 'ระบุค่าในแต่ละแถวไม่ให้ซ้ำกัน']),
            ('คีย์นอกมีไว้ทำอะไร', '4.5 ประเภทของคีย์ · 4.', ['คีย์นอก (Foreign Key)', 'ความสัมพันธ์ของตาราง']),
            ('ซุปเปอร์คีย์กับคีย์คู่แข่งต่างกันอย่างไร', '4.5 ประเภทของคีย์ · 1.',
             ['ซุปเปอร์คีย์ (Super Key)', 'คีย์คู่แข่ง (Candidate Key)']),
            ('คีย์ประกอบคืออะไร', '4.5 ประเภทของคีย์ · 5.', ['คีย์ประกอบ (Composite Key)', 'ตั้งแต่ 2 ฟิลด์ขึ้นไป']),
            ('ใน Microsoft Access ควรใช้ชนิดข้อมูลใดเก็บวันและเวลา', '8.2 ', ['DATE/TIME', 'วันที่และเวลา']),
            ('ชนิดข้อมูล Yes/No ใช้เก็บข้อมูลแบบใด', '8.2 ', ['YES/NO', 'ข้อมูลเชิงตรรกะ']),
            ('SQL ประเภท DDL ใช้ทำอะไร', '8.1 ', ['Data Definition Language: DDL', 'นิยามโครงสร้าง']),
            ('SQL มีกี่ประเภท และมีอะไรบ้าง', '8.1 ',
             ['Data Definition Language: DDL', 'Data Manipulation Language: DML', 'Data Control Language: DCL']),
        ]
        for query, expected_topic, expected_text in cases:
            with self.subTest(query=query):
                found = kb.search(query, 6)
                self.assertTrue(found, f'ไม่พบหัวข้อสำหรับ {query}')
                self.assertTrue(found[0]['topic'].startswith(expected_topic),
                                [e['topic'] for e in found])
                answer = kb.answer_from_dataset([{'role': 'user', 'content': query}])
                for phrase in expected_text:
                    self.assertIn(phrase, answer)
                self.assertIn('แหล่งข้อมูล:', answer)
        # คำถามเรื่องชนิดข้อมูลเฉพาะใน Access ต้องไม่พ่วงหัวข้อชนิดข้อมูลทั่วไปของบท 1
        self.assertEqual([e['topic'] for e in kb.search('ชนิดข้อมูล Yes/No ใช้เก็บข้อมูลแบบใด')],
                         ['8.2 ชนิดของข้อมูล'])

    def test_retrieval(self):
        for query, expected in [('COUNT()', 'Aggregate'), ('GROUP BY', 'GROUP BY'), ('HAVING', 'GROUP BY'),
                                ('LEFT JOIN', 'LEFT JOIN'), ('คีย์หลักคืออะไร', 'Primary Key'),
                                ('foreign key', 'Foreign Key'), ('3NF', 'นอมอลฟอร์มระดับที่ 3'),
                                ('นอร์มัลไลเซชันคืออะไร', 'แนวคิดการนอมอลไลเซชัน'),
                                ('weak entity', 'อ่อนแอ'), ('ER Diagram คืออะไร', '5.1'),
                                ('DBMS คืออะไร', 'ระบบจัดการฐานข้อมูล'),
                                ('ข้อมูลกับสารสนเทศต่างกันยังไง', 'สารสนเทศ'),
                                ('what is sql', 'ความหมายของภาษา SQL'), ('ภาษา SQL คืออะไร', 'ความหมายของภาษา SQL'),
                                ('SQL แบ่งได้กี่ประเภท', '8.1 ความหมายของภาษา SQL'),
                                ('SQL แบ่งเป็นกี่ประเภท', '8.1 ความหมายของภาษา SQL'),
                                ('SQL มีกี่ประเภท', '8.1 ความหมายของภาษา SQL'),
                                ('ภาษา SQL แบ่งออกเป็นกี่ประเภท', '8.1 ความหมายของภาษา SQL'),
                                ('ภาษา DDL คืออะไร', 'ความหมายของภาษา SQL'), ('7.5', 'นอมอลฟอร์มระดับที่ 1'),
                                ('แบบฝึกหัดบทที่ 7', 'แบบฝึกหัดท้ายบท บทที่ 7')]:
            with self.subTest(query=query):
                self.assertIn(expected, kb.search(query, 1)[0]['topic'])

    def test_sql_type_question_does_not_match_key_types(self):
        for query in ['SQL แบ่งได้กี่ประเภท', 'SQL แบ่งเป็นกี่ประเภท', 'SQL มีกี่ประเภท',
                      'ภาษา SQL แบ่งออกเป็นกี่ประเภท', 'ประเภทคำสั่ง SQL มีอะไรบ้าง']:
            with self.subTest(query=query):
                found = kb.search(query, 3)
                self.assertEqual(len(found), 1, [e['topic'] for e in found])
                self.assertTrue(found[0]['topic'].startswith('8.1 ความหมายของภาษา SQL'))
                answer = kb.answer_from_dataset([{'role': 'user', 'content': query}])
                self.assertIn('Data Definition Language: DDL', answer)
                self.assertIn('Data Manipulation Language: DML', answer)
                self.assertIn('Data Control Language: DCL', answer)
                self.assertNotIn('4.5 ประเภทของคีย์', answer)

    def test_unrelated(self):
        # รวมเรื่อง SQL ที่ตำราไม่ได้อธิบาย แม้บางคำจะโผล่ในเนื้อหา (เช่น Transaction ในตาราง)
        for query in ['ราคาทองวันนี้', 'weather today', 'เขียนเพลงรัก', 'quantum computer คืออะไร',
                      'วิธีทำต้มยำกุ้ง', 'ฟุตบอลคืนนี้ใครชนะ', 'python list comprehension',
                      'CTE', 'ROW_NUMBER', 'Transaction', 'stored procedure', 'SQL Injection',
                      # ชื่อระบบที่มีคำว่า sql ไม่ใช่คำถาม "SQL คืออะไร" และภาคผนวกที่ตำราไม่มี
                      'MySQL คืออะไร', 'NoSQL คืออะไร', 'what is sqlite', 'PostgreSQL คืออะไร', 'ภาคผนวก ค',
                      # ภาษาโปรแกรมอื่น เคยได้หัวข้อ "8.1 ความหมายของภาษา SQL" เพราะคำว่า "ภาษา"
                      'ภาษา C คืออะไร', 'ภาษา c', 'ภาษา Python คืออะไร', 'ภาษา Java', 'ภาษา C++', 'ภาษา PHP']:
            with self.subTest(query=query):
                self.assertEqual(kb.search(query), [])
                self.assertEqual(kb.answer_from_dataset([{'role': 'user', 'content': query}]), kb.NO_DATA)

    def test_no_unrelated_second_topic(self):
        # หัวข้อที่แค่มีคำซ้ำกับคำถาม ไม่ถูกดึงมาปน
        for query, only in [('DBMS คืออะไร', '2.3 '), ('ข้อดีของฐานข้อมูล', '2.5 '), ('พจนานุกรมข้อมูล', '6.8 '),
                            ('SELECT ใช้ยังไง', '9.2 '), ('นอร์มัลไลเซชันคืออะไร', '7.1 '), ('normalization', '7.1 '),
                            ('ERD', '5.1 '), ('ความสัมพันธ์แบบกลุ่มต่อกลุ่ม', '5.6 ')]:
            with self.subTest(query=query):
                found = kb.search(query, 3)
                self.assertEqual(len(found), 1, [e['topic'] for e in found])
                self.assertTrue(found[0]['topic'].startswith(only))

    def test_question_about_two_things_gets_both(self):
        for query, starts in [('INNER JOIN กับ LEFT JOIN ต่างกันยังไง', ['10.5 ', '10.6 ']),
                              ('คีย์หลักกับคีย์นอกต่างกันยังไง', ['4.5 ประเภทของคีย์ · 3.', '4.5 ประเภทของคีย์ · 4.']),
                              ('UPDATE กับ DELETE ต่างกันยังไง', ['8.7 ', '8.8 ']),
                              ('1NF 2NF 3NF', ['7.5 ', '7.6 ', '7.7 '])]:
            with self.subTest(query=query):
                self.assertEqual([e['topic'][:len(s)] for e, s in zip(kb.search(query, 3), starts)], starts)

    def test_whole_section_is_not_cut(self):
        # หัวข้อที่ถูกแบ่งส่วน ถามหัวข้อหลักต้องได้ครบทุกส่วน ไม่ใช่แค่ย่อหน้านำ ("…ดังรายละเอียดต่อไปนี้")
        ask = lambda q: kb.answer_from_dataset([{'role': 'user', 'content': q}])
        for query in ['ประเภทของคีย์', 'คีย์มีกี่ประเภท', '4.5']:
            with self.subTest(query=query):
                answer = ask(query)
                for part in [e for e in kb.ENTRIES if e['topic'].startswith('4.5 ประเภทของคีย์')]:
                    self.assertIn(kb.with_figures(part['description']), answer)   # เนื้อหาครบ (พร้อมรูปในตำรา)
        # ถามเจาะจงส่วนเดียว ได้ส่วนนั้นส่วนเดียว
        answer = ask('คีย์หลักคืออะไร')
        self.assertIn('## 4.5 ประเภทของคีย์ · 3. คีย์หลัก (Primary Key)', answer)
        self.assertNotIn('คีย์สำรอง (Alternate Key)', answer)
        self.assertIn('5.3 เอ็นทิตี้ · 2. เอ็นทิตี้แบบอ่อนแอ', ask('เอ็นทิตี้มีกี่ประเภท'))

    def test_small_talk(self):
        ask = lambda q: kb.answer_from_dataset([{'role': 'user', 'content': q}])
        # ถามว่าบอทตอบอะไรได้ ต้องได้รายชื่อบทจากตำรา ไม่ใช่ "ไม่มีข้อมูล"
        for q in ['คุณตอบอะไรได้บ้าง', 'บอททำอะไรได้บ้าง', 'ถามอะไรได้บ้างครับ', 'help', 'สวัสดีครับ คุณตอบอะไรได้บ้าง']:
            with self.subTest(q=q):
                self.assertIn('บทที่ 7 การนอมอลไลเซชัน', ask(q))
        for q in ['สวัสดีครับ', 'หวัดดี', 'hi']:
            with self.subTest(q=q):
                self.assertTrue(ask(q).startswith('สวัสดีครับ'))
        for q in ['ขอบคุณครับ', 'ขอบคุณมากๆครับ', 'thanks']:
            with self.subTest(q=q):
                self.assertTrue(ask(q).startswith('ยินดีครับ'))
        # คำถามเนื้อหาที่หน้าตาคล้ายกัน ต้องไปค้นในตำราตามปกติ
        self.assertIn('8.1 ความหมายของภาษา SQL', ask('SQL ทำอะไรได้บ้าง'))
        self.assertIn('9.11', ask('สวัสดี GROUP BY'))
        self.assertEqual(ask('history'), kb.NO_DATA)

    def test_grounded_fields(self):
        for entry in kb.ENTRIES:
            answer = kb.answer_from_dataset([{'role': 'user', 'content': entry['topic']}])
            self.assertTrue(answer)
        for query in ['GROUP BY', 'คีย์หลัก', 'LEFT JOIN']:
            entries = kb.search(query, 2)
            answer = kb.answer_from_dataset([{'role': 'user', 'content': query}])
            for entry in entries:
                self.assertIn(entry['description'], answer)
                self.assertIn(entry['source'], answer)
        # หัวข้อยาวที่ถามเจาะจงส่วนเดียว ได้เฉพาะส่วนนั้น แต่ทุกบรรทัดยังเป็นข้อความในหัวข้อนั้นตรงตัว
        answer = kb.answer_from_dataset([{'role': 'user', 'content': 'COUNT()'}])
        entry = kb.search('COUNT()', 1)[0]
        self.assertIn('9.10.3 ฟังก์ชัน COUNT() การนับจำนวน', answer)
        self.assertNotIn('9.10.4 ฟังก์ชัน SUM()', answer)
        self.assertIn(entry['source'], answer)
        body = answer.split('\n\nแหล่งข้อมูล:')[0].split('\n', 2)[2]
        for line in body.split('\n'):
            self.assertIn(line, entry['description'].split('\n'))

    def test_sources(self):
        manifest = json.loads(Path(kb.MANIFEST_PATH).read_text(encoding='utf-8'))
        self.assertEqual(len(kb.ENTRIES), manifest['topic_count'])
        self.assertTrue(all(e['source'] == 'db_business_textbook_th.md' for e in kb.ENTRIES))
        self.assertEqual([e['topic'] for e in kb.ENTRIES], manifest['topics'])
        # ทุกหัวข้อบอกบทและเลขหน้า และคำตอบต้องแสดงให้ผู้ใช้เห็น
        for e in kb.ENTRIES:
            with self.subTest(topic=e['topic']):
                self.assertRegex(e['references'], r'(บทที่ \d+|ภาคผนวก [กข]) .+ · หน้า \d+(–\d+)? \(PDF หน้า \d+(–\d+)?\)$')
        answer = kb.answer_from_dataset([{'role': 'user', 'content': 'คีย์หลักคืออะไร'}])
        self.assertIn('บทที่ 4 แบบจำลองฐานข้อมูลเชิงสัมพันธ์ · หน้า 69–70 (PDF หน้า 96–97)', answer)


if __name__ == '__main__':
    unittest.main()
