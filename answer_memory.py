"""จำแผนเลือกหัวข้อ/ย่อหน้าที่ผ่านการตรวจแล้วในไฟล์ ai_answers.json

ไฟล์นี้ลดการเลือกหัวข้อซ้ำในเครื่องได้; บน Vercel เป็นไฟล์อ่านอย่างเดียวและแต่ละ instance
ไม่มีหน่วยความจำร่วมกัน จึงไม่ใช่ที่เก็บถาวร คำตอบสุดท้ายยังตรวจจากข้อความใน dataset ก่อนแสดง
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
