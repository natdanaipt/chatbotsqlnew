"""จำคำตอบของคำถามที่ต้องตีความ ถามซ้ำกี่รอบก็ได้คำตอบเดิม

AI ตอบไม่เหมือนเดิมทุกครั้ง (Gemini แม้ตั้ง temperature 0 ก็ยังต่าง)
จึงบันทึกคำตอบแรกของแต่ละคำถาม (หัวข้อ + เลขย่อหน้าที่แสดง) ไว้ในไฟล์ ai_answers.json แล้วใช้ซ้ำทุกครั้ง
คำตอบเปลี่ยนได้เฉพาะเมื่อแก้เนื้อหาตำรา (checksum เปลี่ยน คำตอบที่จำไว้ใช้ไม่ได้ทั้งหมด)
หรือผู้ดูแลลบรายการในไฟล์/สร้างใหม่ด้วย eval_questions.py --pin --fresh

- รันในเครื่อง: คำถามใหม่ถูกบันทึกลงไฟล์ commit ไฟล์นี้ขึ้นไปพร้อมโค้ด เว็บจะตอบแบบเดียวกัน
- บน Vercel: ไฟล์อ่านอย่างเดียวและเครื่องแต่ละตัวไม่ได้ใช้หน่วยความจำร่วมกัน จึงใช้เฉพาะคำตอบที่มีในไฟล์
  คำถามใหม่ที่ไม่มีในไฟล์ตอบด้วยวิธีค้นเอง (ได้ผลเหมือนเดิมทุกครั้งอยู่แล้ว) ไม่เรียก AI สด
"""

import json
import os
import threading
from datetime import datetime, timezone


class AnswerMemory:
    def __init__(self, path, writable=None, model=""):
        self.path = path
        self.model = model                     # รุ่น AI ที่ใช้ตอนบันทึก (เก็บไว้ดูย้อนหลัง)
        self._lock = threading.Lock()
        self.data = self._load()
        self.writable = self._can_write() if writable is None else writable

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
        if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
            data = {"book": None, "answers": {}}
        return data

    def _can_write(self):
        if os.path.exists(self.path):
            return os.access(self.path, os.W_OK)
        return os.access(os.path.dirname(os.path.abspath(self.path)), os.W_OK)

    def get(self, key, book):
        """คำตอบที่จำไว้ของคำถามนี้ (ต้องเป็นตำราฉบับเดียวกัน) หรือ None"""
        if not book or self.data.get("book") != book:
            return None
        return self.data["answers"].get(key)

    def put(self, key, book, plan, source):
        """จำคำตอบ: plan = [{"topic": ชื่อหัวข้อ, "picked": null | [] | [เลขย่อหน้า]}]"""
        with self._lock:
            if self.data.get("book") != book:
                self.data = {"book": book, "answers": {}}   # ตำราเปลี่ยน คำตอบเก่าอ้างเนื้อหาเก่า
            self.data["answers"][key] = {
                "plan": plan,
                "source": f"{source} {self.model}".strip() if source == "AI" else source,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            if self.writable:
                self._save()

    def forget(self, keys=None):
        """ลืมคำตอบ (ทั้งหมด หรือเฉพาะคำถามที่ระบุ) เพื่อให้ตอบใหม่"""
        with self._lock:
            if keys is None:
                self.data["answers"] = {}
            else:
                for key in keys:
                    self.data["answers"].pop(key, None)
            if self.writable:
                self._save()

    def _save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1, sort_keys=True)
                f.write("\n")
            os.replace(tmp, self.path)          # เขียนไฟล์ใหม่ทั้งไฟล์แล้วค่อยสลับ ไฟล์ไม่เสียถ้าเขียนไม่จบ
        except OSError as exc:
            print(f"[!] บันทึกคำตอบที่จำไว้ไม่ได้: {exc}")
