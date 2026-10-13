"""Offline route checks for the web app (the only channel): never contacts a model."""
import os
import unittest
from unittest.mock import patch

import app as application
from answer_memory import AnswerMemory


class HandbookRoutes(unittest.TestCase):
    def setUp(self):
        # app โหลด API key จาก .env ได้ ปิดไว้ให้ทดสอบแบบไม่ต่อเน็ต และไม่ใช้คำตอบที่จำไว้ใน ai_answers.json
        env = patch.dict(os.environ, {'GEMINI_API_KEY': ''})
        env.start()
        self.addCleanup(env.stop)
        memory = patch.object(application, 'answer_memory', AnswerMemory(os.devnull, writable=False))
        memory.start()
        self.addCleanup(memory.stop)

    def test_home_page_without_removed_resources(self):
        with application.app.test_client() as client:
            self.assertEqual(client.get('/').status_code, 200)
            for path in ['/handbook.pdf', '/handbook.md', '/knowledge/topics']:
                self.assertEqual(client.get(path).status_code, 404)

    def test_dataset_answer(self):
        with application.app.test_client() as client, patch.object(application, 'save_web_chat'):
            response = client.post('/chat/stream', json={'message': 'GROUP BY'})
            self.assertEqual(response.status_code, 200)
            text = response.get_data(as_text=True)
            self.assertIn('db_business_textbook_th.md', text)
            self.assertIn('HAVING', text)


    def test_page_version_matches_between_page_and_answers(self):
        # แท็บเก่าเทียบเวอร์ชันนี้กับ header ของคำตอบ ถ้าไม่ตรงจะขึ้นให้รีเฟรช
        with application.app.test_client() as client, patch.object(application, 'save_web_chat'):
            version = application.page_version()
            self.assertRegex(version, r'^[0-9a-f]{12}$')
            page = client.get('/')
            self.assertIn(f'const PAGE_VERSION = "{version}";', page.get_data(as_text=True))
            self.assertEqual(page.headers['Cache-Control'], 'no-cache')
            answer = client.post('/chat/stream', json={'message': 'GROUP BY'})
            self.assertEqual(answer.headers['X-Page-Version'], version)

    def test_line_and_telegram_are_removed(self):
        # รองรับเฉพาะหน้าเว็บ: webhook ของ LINE และ Telegram ถูกเอาออกแล้ว
        with application.app.test_client() as client:
            for path in ['/callback', '/telegram']:
                self.assertEqual(client.post(path, json={}).status_code, 404)

    def test_figure_is_served(self):
        with application.app.test_client() as client:
            r = client.get('/static/figures/fig_5_1.webp')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.mimetype, 'image/webp')

    def test_non_string_ids_do_not_crash(self):
        with application.app.test_client() as client, patch.object(application, 'save_web_chat'):
            for payload in [{'message': 'GROUP BY', 'chat_id': 12345678}, {'message': 'GROUP BY', 'name': 5}]:
                with self.subTest(payload=payload):
                    self.assertEqual(client.post('/chat/stream', json=payload).status_code, 200)


if __name__ == '__main__':
    unittest.main()
