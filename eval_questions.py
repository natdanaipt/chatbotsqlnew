"""ชุดคำถามทดสอบว่าบอทตอบตรงคำถาม และไม่ดึงเนื้อหาเกินจากที่ถาม

รัน:   ./venv/bin/python eval_questions.py            ทดสอบแบบไม่ใช้ AI (เหมือนตอนไม่ได้ตั้ง API key)
       ./venv/bin/python eval_questions.py --ai       ให้ AI ช่วยเลือก (ต้องมี GEMINI_API_KEY ใน .env)
                                                      ใช้ที่จำคำตอบชั่วคราว วัดความสามารถของ AI โดยไม่แตะ ai_answers.json
       ./venv/bin/python eval_questions.py --ai --pin บันทึกคำตอบลง ai_answers.json (commit ขึ้นเว็บ) ข้อที่จำไว้แล้วใช้ของเดิม
       เพิ่ม --fresh เพื่อลบคำตอบที่จำไว้ใน ai_answers.json ก่อน (ให้ AI ตอบใหม่ทั้งหมด)
       เพิ่ม --repeat 3 เพื่อถาม AI ซ้ำ 3 รอบโดยไม่ใช้ที่จำคำตอบ นับข้อที่ AI ตอบไม่เหมือนเดิม
       เพิ่ม -v เพื่อดูข้อความคำตอบของข้อที่ไม่ผ่าน

แต่ละข้อกำหนด: หัวข้อแรกของคำตอบต้องขึ้นต้นด้วย topic, ต้องมีข้อความใน has (ตอบตรงเรื่อง)
และต้องไม่มีข้อความใน lacks (เนื้อหาของเรื่องอื่นที่อยู่ในหัวข้อเดียวกัน = ตอบเกินคำถาม)
ทุกข้อถามสองรอบ รอบสองต้องได้คำตอบเหมือนรอบแรกทุกตัวอักษร ข้อความทั้งหมดคัดจากไฟล์ตำราตรงตัว
"""

import os
import re
import sys
import tempfile
import time

# ชุด "หัวข้อ": ถามตามหัวข้อในไฟล์ PDF — ทุกหัวข้อตามสารบัญ (สร้างอัตโนมัติด้านล่าง) และหัวเรื่องย่อยตัวหนาในเนื้อหา
HEADING_CASES = [
    dict(q="ความหมายของข้อมูล", topic="1.1 ", has=["ข้อมูล (Data) หมายถึง"], lacks=["สารสนเทศ (Information) หมายถึง"]),
    dict(q="ความหมายของสารสนเทศ", topic="1.1 ", has=["สารสนเทศ (Information) หมายถึง"], lacks=["ข้อมูล (Data) หมายถึง"]),
    dict(q="ข้อผิดพลาดจากการลบข้อมูล (Deletion Anomaly)", topic="1.6 ข้อจำกัดของวิธีแฟ้มข้อมูล · 2.",
         has=["2.2 ข้อผิดพลาดจากการลบข้อมูล"], lacks=["2.3 ข้อผิดพลาดจากการเปลี่ยนแปลงข้อมูล"]),
    dict(q="ระดับชั้นผู้ใช้ (User Presentation)", topic="3.1 ", has=["ระดับชั้นผู้ใช้"], lacks=["ระดับชั้นฐานข้อมูล (Database File)"]),
    dict(q="อินสแตนซ์คืออะไร", topic="3.9 ", has=["อินสแตนซ์ (Instance) หมายถึง"]),
    dict(q="ข้อดีของแบบจำลองฐานข้อมูลเชิงสัมพันธ์", topic="4.3 ", has=["ข้อดีของแบบจำลองฐานข้อมูลเชิงสัมพันธ์"],
         lacks=["ข้อจำกัดของแบบจำลองฐานข้อมูลเชิงสัมพันธ์"]),
    dict(q="ข้อจำกัดของแบบจำลองฐานข้อมูลเชิงสัมพันธ์", topic="4.3 ", has=["ข้อจำกัดของแบบจำลองฐานข้อมูลเชิงสัมพันธ์"],
         lacks=["ข้อดีของแบบจำลองฐานข้อมูลเชิงสัมพันธ์"]),
    dict(q="คุณสมบัติของรีเลชันที่สำคัญ", topic="4.4 ", has=["คุณสมบัติของรีเลชันที่สำคัญ"], lacks=["ดีกรี หมายถึง"]),
    dict(q="ประเภทของแอตทริบิวต์", topic="5.4 ", has=["คีย์แอตทริบิวต์ หมายถึง", "ดีไรฟด์แอตทริบิวต์ คือ"]),
    dict(q="ประเภทของเอ็นทิตี้", topic="5.3 ", has=["เอ็นทิตี้แบบอ่อนแอ (Weak Entities) หมายถึง"]),
    dict(q="เอ็นทิตี้เรียกซ้ำ (Recursive Entities)", topic="5.3 เอ็นทิตี้ · 2.", has=["เอ็นทิตี้เรียกซ้ำ (Recursive Entities) เป็น"],
         lacks=["เอ็นทิตี้แบบอ่อนแอ (Weak Entities) หมายถึง"]),
    dict(q="อัตราส่วนคาร์ดินัลลิตี้", topic="5.6 ", has=["อัตราส่วนของคาร์ดินัลลิตี้ (Cardinality Ratio) คือ"]),
    dict(q="ฟังก์ชัน COUNT() การนับจำนวน", topic="9.10 ", has=["9.10.3 ฟังก์ชัน COUNT() การนับจำนวน"],
         lacks=["9.10.1 ฟังก์ชัน MAX()", "9.10.4 ฟังก์ชัน SUM()"]),
    dict(q="การขึ้นต่อกันแบบสมบูรณ์", topic="7.3 ", has=["การขึ้นต่อกันแบบสมบูรณ์"], lacks=["(Transitive Dependency)"]),
    dict(q="สรุปภาพรวมโครงสร้างของคีย์", topic="4.5 ประเภทของคีย์ · 6.", has=["สรุปภาพรวมโครงสร้างของคีย์"]),
    dict(q="แบบจำลองข้อมูลเชิงแนวคิด", topic="4.1 แบบจำลองข้อมูล · 1.", has=["Conceptual Data Model"]),
]

# ชุด "ที่ผู้ใช้รายงาน": ตอบเกิน / ไม่มีภาพ / เนื้อหาซ้ำ / เปรียบเทียบแล้วยกทั้งหัวข้อ (max_chars = เนื้อหาไม่เกินเท่านี้)
REPORTED_CASES = [
    dict(q="ความหมายของข้อมูล", topic="1.1 ", has=["ข้อมูล (Data) หมายถึง"], max_chars=1400,
         lacks=["ตัวอย่างข้อมูล", "cat, dog", "![ภาพที่", "สารสนเทศ (Information) หมายถึง"]),
    dict(q="ชุดข้อมูลที่ยังไม่มีความหมาย", topic="1.1 ", max_chars=900,
         has=["![ภาพที่ 1.1](/static/figures/fig_1_1.webp)", "ภาพที่ 1.1 ชุดข้อมูลที่ยังไม่มีความหมาย"],
         lacks=["สารสนเทศ (Information) หมายถึง", "ภาพที่ 1.2"]),
    dict(q="ตัวอย่างสารสนเทศ", topic="1.1 ", has=["ตัวอย่างสารสนเทศ", "![ภาพที่ 1.2]"], max_chars=1200,
         lacks=["ภาพที่ 1.3", "ข้อมูล หมายถึงข้อมูลที่เกิดจากการรวบรวม", "ข้อมูล (Data) หมายถึง"]),
    dict(q="ตัวอย่างข้อมูล", topic="1.1 ", has=["cat, dog", "![ภาพที่ 1.1]"],
         lacks=["สารสนเทศ (Information) หมายถึง", "ภาพที่ 1.2"]),
    dict(q="inner join กับ left join ต่างกันยังไง", topic="บทสรุป บทที่ 10", max_chars=500,
         has=["INNER JOIN จะมีลักษณะคล้ายกัน", "LEFT JOIN จะเน้นการนำเอาข้อมูลจากตารางทางซ้าย"],
         lacks=["RIGHT JOIN", "FULL OUTER JOIN", "ข้อสังเกต", "ตัวอย่างที่ 10.6", "ตัวอย่างที่ 10.11", "P6 | น้ำดื่มคริสตัล"]),
    dict(q="innerjoin กับ left join ต่างกันยังไง", topic="บทสรุป บทที่ 10", max_chars=500,
         has=["INNER JOIN จะมีลักษณะคล้ายกัน", "LEFT JOIN จะเน้นการนำเอาข้อมูลจากตารางทางซ้าย"], lacks=["RIGHT JOIN"]),
    dict(q="ภาพที่ 1.1", topic="1.1 ", has=["![ภาพที่ 1.1]", "จากภาพที่ 1.1"], max_chars=800, lacks=["ภาพที่ 1.2"]),
    dict(q="ภาพที่ 1.4", topic="1.3 ", has=["![ภาพที่ 1.4]"], lacks=["ภาพที่ 1.5"]),   # เลขภาพ ไม่ใช่เลขหัวข้อ 1.4
    dict(q="ตารางที่ 4.3", topic="4.4 ", has=["ตารางที่ 4.3 ตารางสินค้า", "P0010 | สายยางรดน้ำ"],
         lacks=["คุณสมบัติของรีเลชันที่สำคัญ", "ตารางที่ 4.4"]),
    dict(q="ภาพที่ 99.9", topic=None),
]

# ชุด "เปรียบเทียบ": ได้ย่อหน้าที่ตำราเทียบไว้เอง (ตัดเหลือช่วงที่เกี่ยว) หรือนิยามของสองฝั่ง ไม่ยกทั้งหัวข้อ ไม่ซ้อนกัน
COMPARE_CASES = [
    dict(q="left join กับ right join ต่างกันยังไง", topic="บทสรุป บทที่ 10", max_chars=300,
         has=["LEFT JOIN จะเน้น", "RIGHT JOIN คือ จะเน้น"], lacks=["FULL OUTER JOIN", "EQUI JOIN"]),
    dict(q="equi join กับ inner join ต่างกันยังไง", topic="10.5 ", max_chars=300,
         has=["คล้ายกับวิธี EQUI JOIN แตกต่างกันตรง"], lacks=["ตัวอย่างที่ 10.6"]),
    dict(q="where กับ having ต่างกันยังไง", topic="9.11 ", max_chars=400,
         has=["ไม่สามารถใช้คีย์เวิร์ด WHERE"], lacks=["ตัวอย่างที่ 9.28", "ตารางที่ 9.37"]),
    # นิยามสองฝั่ง: แค่ใจความเปิดของแต่ละเรื่อง ตัดก่อนตัวอย่าง ("เช่น …") และรายละเอียดต่อท้าย มีปุ่ม "ขอตัวอย่าง" ให้ขอเอง
    dict(q="คีย์หลักกับคีย์นอกต่างกันยังไง", topic="4.5 ประเภทของคีย์ · 3.", max_chars=550,
         has=["คีย์หลัก หมายถึง", "คีย์นอก หมายถึง", "[[ถาม:ขอตัวอย่าง]]"],
         lacks=["ตารางที่ 4.18", "4) คีย์นอก ไม่จำเป็น", "เช่น", "ตารางแผนกและตารางพนักงาน"]),
    dict(q="1NF กับ 2NF ต่างกันยังไง", topic="7.5 ", max_chars=550,
         has=["First Normal Form : 1NF", "Second Normal Form : 2NF"], lacks=["ตารางที่ 7.", "3) การแปลงรีเลชัน 1NF มาเป็น 2NF"]),
    dict(q="2NF กับ 3NF ต่างกันยังไง", topic="7.6 ", max_chars=650,
         has=["Second Normal Form : 2NF", "Third Normal Form : 3NF"], lacks=["1) รีเลชั"]),
    dict(q="count กับ sum ต่างกันยังไง", topic="9.10 ", max_chars=500,
         has=["9.10.3 ฟังก์ชัน COUNT()", "9.10.4 ฟังก์ชัน SUM()"], lacks=["9.10.1 ฟังก์ชัน MAX()", "ตัวอย่างที่ 9.23"]),
    dict(q="max กับ min ต่างกันยังไง", topic="9.10 ", max_chars=350,
         has=["9.10.1 ฟังก์ชัน MAX()", "9.10.2 ฟังก์ชัน MIN ()"], lacks=["ฟังก์ชัน | ความหมาย", "COUNT()", "ตัวอย่างที่ 9.20"]),
    dict(q="one to one กับ one to many ต่างกันยังไง", topic="5.6 ประเภทความสัมพันธ์ · 1.", max_chars=200,
         has=["หนึ่งสิ่งกับหนึ่งสิ่ง", "หนึ่งสิ่งต่อหลายสิ่ง", "[[ถาม:ขอตัวอย่าง]]"], lacks=["เช่น", "สูติบัตร", "ภาพที่ 5.19"]),
    dict(q="ฟิลด์กับเรคคอร์ดต่างกันยังไง", topic="1.3 ", max_chars=350,
         has=["ฟิลด์ (Field) หมายถึง", "(Record) หมายถึง"], lacks=["ไบต์ (Byte)", "เช่น", "ข้อมูลอาจารย์ 1 คน"]),
    dict(q="สกีมากับอินสแตนซ์ต่างกันยังไง", topic="3.9 ", max_chars=400,
         has=["สกีมา (Schema) หมายถึง", "อินสแตนซ์ (Instance) หมายถึง"]),
    dict(q="เอนทิตีกับแอตทริบิวต์ต่างกันยังไง", topic="5.3 ", max_chars=650,
         has=["เอ็นทิตี้ (Entity) หมายถึง", "แอตทริบิวต์ (Attribute) หมายถึง"], lacks=["เช่น", "ภาพที่ 5.10"]),
    dict(q="คีย์คู่แข่งกับคีย์สำรองต่างกันยังไง", topic="4.5 ประเภทของคีย์ · 2.", max_chars=550,
         has=["คีย์คู่แข่ง หมายถึง", "คีย์สำรอง หมายถึง"]),
    dict(q="DDL กับ DML ต่างกันยังไง", topic="8.1 ", max_chars=500,
         has=["Data Definition Language: DDL", "Data Manipulation Language: DML"], lacks=["การกำหนดชื่อฐานข้อมูล"]),
    # หัวข้อเปิดด้วยการเล่าที่มา ("ในอดีต…"): ใช้ประโยคที่บอกว่าเรื่องนี้เป็นอะไร
    dict(q="ระบบแฟ้มข้อมูลกับระบบฐานข้อมูลต่างกันยังไง", topic="1.5 ", max_chars=600,
         has=["ระบบแฟ้มข้อมูล (Files System) เป็น", "ระบบฐานข้อมูล (Database System) เป็น"], lacks=["ในอดีต", "เช่น"]),
    # หาตัวนิยามได้ไม่ครบทุกฝั่ง: ใจความเปิดของส่วนที่เจอ ไม่ยกทั้งหัวข้อ (เดิม 9,500 ตัวอักษร)
    dict(q="เอนทิตีแบบอ่อนกับแบบแข็งต่างกันยังไง", topic="5.3 เอ็นทิตี้ · 2.", max_chars=300, has=["Weak Entities", "[[ถาม:5.3 เอ็นทิตี้]]"]),
    dict(q="order by กับ group by ต่างกันยังไง", topic="9.7 ", max_chars=500, has=["ORDER BY", "GROUP BY"], lacks=["ตัวอย่างที่"]),
]

# ชุด "พิมพ์เอง": คำถามแบบที่คนพิมพ์ ไม่ได้ลอกชื่อหัวข้อ
NATURAL_CASES = [
    dict(q="ชนิดของข้อมูลมีอะไรบ้าง", topic=("1.2 ", "8.2 "), only=True,
         has=["ข้อความ (Text)", "SHORT TEXT"], lacks=["1.6 ข้อจำกัดของวิธีแฟ้มข้อมูล"]),
    dict(q="Data Type มีอะไรบ้าง", topic=("1.2 ", "8.2 "), only=True),
    dict(q="กรณีศึกษาที่ 1 ระบบร้านขายสินค้ามีอะไรบ้าง", topic=("5.7 ", "6.11 "), only=True),
    dict(q="กรณีศึกษาที่ 2 ระบบลงทะเบียนเรียนมีอะไรบ้าง", topic=("5.8 ", "6.12 "), only=True),
    dict(q="ชนิดของแฟ้มข้อมูลมีอะไรบ้าง", topic="1.4 ", only=True),
    dict(q="ประเภทของคีย์มีอะไรบ้าง", topic="4.5 ", only=True),
    dict(q="ประเภทความสัมพันธ์มีอะไรบ้าง", topic="5.6 ", only=True),
    dict(q="ข้อดีของวิธีฐานข้อมูลมีอะไรบ้าง", topic="2.5 ", only=True),
    dict(q="ชนิดข้อมูลทั่วไปมีอะไรบ้าง", topic="1.2 ", only=True,
         has=["ข้อความ (Text)", "ข้อมูลตัวเลข (Number)"], lacks=["SHORT TEXT"]),
    dict(q="ชนิดข้อมูลในบทที่ 1 มีอะไรบ้าง", topic="1.2 ", only=True),
    dict(q="ชนิดข้อมูลใน Microsoft Access มีอะไรบ้าง", topic="8.2 ", only=True,
         has=["SHORT TEXT"], lacks=["ข้อมูลตัวเลข (Number) เป็นข้อมูลที่เก็บค่า"]),
    dict(q="ประเภทข้อมูลใน Access มีอะไรบ้าง", topic="8.2 ", only=True),
    dict(q="ชนิดข้อมูลในบทที่ 8 มีอะไรบ้าง", topic="8.2 ", only=True),
    dict(q="สารสนเทศคืออะไร", topic="1.1 ", has=["สารสนเทศ (Information) หมายถึง"], lacks=["ข้อมูล (Data) หมายถึง", "ภาพที่ 1.3"]),
    dict(q="ข้อมูลคืออะไร", topic="1.1 ", has=["ข้อมูล (Data) หมายถึง"], lacks=["สารสนเทศ (Information) หมายถึง"]),
    dict(q="ข้อมูลกับสารสนเทศต่างกันยังไง", topic="1.1 ", max_chars=350, lacks=["ข้อมูล (Data) หมายถึง", "ภาพที่ 1.2", "เช่น"],
         has=["ข้อมูล หมายถึงข้อมูลที่เกิดจากการรวบรวม", "สารสนเทศ คือข้อมูลที่ผ่านการประมวลผลแล้ว"]),   # ย่อหน้าที่ตำราสรุปเทียบไว้
    dict(q="SQL คืออะไร", topic="8.1 ", has=["ภาษา SQL (Structured Query Language) เป็น"]),
    dict(q="sql คืออะไรครับ", topic="8.1 ", has=["ภาษา SQL (Structured Query Language) เป็น"]),
    dict(q="ฐานข้อมูลคืออะไร", topic="2.2 ", has=["ระบบฐานข้อมูล (Database System) เป็น"]),
    dict(q="DBMS คืออะไร", topic="2.3 ", has=["(Database Management System : DBMS) เป็น"]),
    dict(q="ฟิลด์คืออะไร", topic="1.3 ", has=["ฟิลด์ (Field) หมายถึง"], lacks=["ไบต์ (Byte)", "แฟ้มข้อมูล (File) หมายถึง"]),
    dict(q="เรคคอร์ดคืออะไร", topic="1.3 ", has=["(Record) หมายถึง"], lacks=["ฟิลด์ (Field) หมายถึง"]),
    dict(q="บิตคืออะไร", topic="1.3 ", has=["บิต (Bit)"], lacks=["ฟิลด์ (Field) หมายถึง"]),
    dict(q="ทูเพิลคืออะไร", topic="4.4 ", has=["ทูเพิล หมายถึง"], lacks=["ดีกรี หมายถึง", "โดเมน หมายถึง", "รีเลชัน หมายถึง"]),
    dict(q="ดีกรีคืออะไร", topic="4.4 ", has=["ดีกรี หมายถึง"], lacks=["ทูเพิล หมายถึง", "แอตทริบิวต์ หมายถึง"]),
    dict(q="โดเมนคืออะไร", topic="4.4 ", has=["โดเมน หมายถึง"], lacks=["ทูเพิล หมายถึง"]),
    dict(q="รีเลชันคืออะไร", topic="4.4 ", has=["รีเลชัน หมายถึง"], lacks=["ดีกรี หมายถึง", "ทูเพิล หมายถึง"]),
    dict(q="คีย์หลักคืออะไร", topic="4.5 ประเภทของคีย์ · 3.", has=["คีย์หลัก หมายถึง"], lacks=["คีย์สำรอง หมายถึง"]),
    dict(q="primary key คืออะไร", topic="4.5 ประเภทของคีย์ · 3.", has=["คีย์หลัก หมายถึง"]),
    dict(q="foreign key คืออะไร", topic="4.5 ประเภทของคีย์ · 4.", has=["คีย์นอก หมายถึง"]),
    dict(q="คีย์มีกี่ประเภท", topic="4.5 ", has=["ซุปเปอร์คีย์ หมายถึง", "คีย์สำรอง หมายถึง"]),
    dict(q="เอ็นทิตี้คืออะไร", topic="5.3 ", has=["เอ็นทิตี้ (Entity) หมายถึง"], lacks=["เอ็นทิตี้แบบอ่อนแอ (Weak Entities) หมายถึง"]),
    dict(q="แอตทริบิวต์คืออะไร", topic=("5.4 ", "4.4 ", "4.2 "), has=["แอตทริบิวต์"], lacks=["ดีไรฟด์แอตทริบิวต์ คือ"]),
    dict(q="ดีไรฟด์แอตทริบิวต์คืออะไร", topic="5.4 ", has=["ดีไรฟด์แอตทริบิวต์ คือ"], lacks=["คีย์แอตทริบิวต์ หมายถึง"]),
    dict(q="สกีมาคืออะไร", topic=("3.9 ", "4.4 ", "6.1 "), has=["สกีมา (Schema) หมายถึง"]),
    dict(q="DDL คืออะไร", topic="8.1 ", has=["Data Definition Language: DDL"], lacks=["Data Control Language: DCL"]),
    dict(q="DML คืออะไร", topic="8.1 ", has=["Data Manipulation Language: DML"], lacks=["Data Definition Language: DDL"]),
    dict(q="DCL คืออะไร", topic="8.1 ", has=["Data Control Language: DCL"], lacks=["Data Manipulation Language: DML"]),
    dict(q="3NF คืออะไร", topic="7.7 ", has=["Third Normal Form : 3NF"], lacks=["ตารางที่ 7.32"]),
    dict(q="normalization คืออะไร", topic="7.1 ", has=["การนอมอลไลเซชัน (Normalization) เป็น"]),
    dict(q="Partial Dependency คืออะไร", topic="7.3 ", has=["(Partial Dependency)"], lacks=["(Transitive Dependency)"]),
    dict(q="big data คืออะไร", topic="11.1 ", has=["ข้อมูลขนาดใหญ่ (Big Data) เป็น"], lacks=["บริษัท Tesco Lotus"]),
    dict(q="AI คืออะไร", topic="11.6 ", has=["ปัญญาประดิษฐ์ คือ"]),
    dict(q="machine learning คืออะไร", topic="11.5 ", has=["การเรียนรู้ของเครื่องจักร (Machine Learning) คือ"]),
    dict(q="data mining คืออะไร", topic="11.4 ", has=["เหมืองข้อมูล เป็น"], lacks=["การสร้างแบบจําลอง (Modeling) คือ"]),
    dict(q="ER Diagram คืออะไร", topic="5.1 "),
    dict(q="การเข้ารหัสลับคืออะไร", topic="12.5 ", has=["การเข้ารหัสลับ (Encryption) เป็น"], lacks=["User_Login"]),
    dict(q="ความเป็นส่วนตัวคืออะไร", topic="12.1 ", has=["ความเป็นส่วนตัว (Privacy) เป็น"], lacks=["ความเข้าถึงได้ (Accessibility)"]),
    dict(q="COUNT ใช้ยังไง", topic="9.10 ", has=["COUNT"], lacks=["9.10.1 ฟังก์ชัน MAX()", "9.10.4 ฟังก์ชัน SUM()"]),
    dict(q="GROUP BY ใช้ยังไง", topic="9.11 "),
    dict(q="ลบตารางยังไง", topic="8.5 "),
    dict(q="เพิ่มข้อมูลลงตาราง", topic="8.6 "),
    dict(q="ข้อดีของฐานข้อมูล", topic="2.5 "),
    dict(q="INNER JOIN กับ LEFT JOIN ต่างกันยังไง", topic="บทสรุป บทที่ 10", has=["INNER JOIN", "LEFT JOIN"], max_chars=500),
    # ค้นจากคำในชื่อหัวข้ออย่างเดียวพลาด ต้องอาศัย AI ตีความ (ai=True: ไม่นับตอนทดสอบแบบไม่ใช้ AI)
    dict(q="ชนิดข้อมูลใน SQL มีอะไรบ้าง", topic="8.2 ", only=True, has=["SHORT TEXT"]),
    dict(q="join คืออะไร", topic=("10.2 ", "บทที่ 10 ")),
    dict(q="ทำไมต้องทำ normalization", topic=("7.1 ", "7.2 ", "บทที่ 7 ")),
]

# ชุด "พิมพ์เองแบบถ้อยคำอื่น": ไม่มีชื่อศัพท์หรือชื่อหัวข้อในคำถามเลย ต้องตีความ (ai=True: วิธีค้นเองพลาดได้)
PARAPHRASE_CASES = [
    dict(q="ข้อมูลที่ผ่านการประมวลผลแล้วเรียกว่าอะไร", topic="1.1 ", has=["สารสนเทศ"], max_chars=1700, ai=True),
    dict(q="ทำไมต้องมีคีย์หลัก", topic="4.5 ประเภทของคีย์ · 3."),
    dict(q="อยากเรียงข้อมูลจากมากไปน้อยต้องใช้คำสั่งอะไร", topic="9.7 ", has=["ORDER BY"]),
    dict(q="หาค่าเฉลี่ยใน sql ใช้คำสั่งอะไร", topic="9.10 ", has=["AVG"], lacks=["9.10.1 ฟังก์ชัน MAX()"], ai=True),
    dict(q="นับจำนวนแถวในตาราง", topic="9.10 ", has=["COUNT"], lacks=["9.10.4 ฟังก์ชัน SUM()"], ai=True),
    dict(q="เลือกข้อมูลไม่ให้ซ้ำกัน", topic="9.3 "),
    dict(q="ตั้งรหัสผ่านให้ฐานข้อมูล Access ยังไง", topic="12.5 ", has=["Encrypt with Password"], ai=True),
    dict(q="ข้อมูลซ้ำซ้อนทำให้เกิดปัญหาอะไร", topic=("1.6 ", "7.2 ")),
    dict(q="สถาปัตยกรรมฐานข้อมูล 3 ระดับมีอะไรบ้าง", topic="3.2 "),
    dict(q="ความสัมพันธ์แบบ one to many แปลงเป็นตารางยังไง", topic="6.6 ", ai=True),
    dict(q="big data มีลักษณะยังไง", topic="11.1 ", has=["Volume", "Velocity", "Variety"], lacks=["บริษัท Tesco Lotus"]),
    dict(q="ถ้าอยากลบข้อมูลบางแถวออกจากตาราง", topic="8.8 "),
    dict(q="แก้ราคาสินค้าในตารางใช้คำสั่งอะไร", topic="8.7 ", ai=True),
    dict(q="SQL แบ่งเป็นกี่ประเภท", topic="8.1 ", has=["DDL", "DML", "DCL"]),
    dict(q="SQL แบ่งได้กี่ประเภท", topic="8.1 ", has=["DDL", "DML", "DCL"], lacks=["4.5 ประเภทของคีย์"]),
    dict(q="คำสั่งที่ใช้สร้างตาราง", topic="8.3 ", has=["CREATE TABLE"]),
]

# ชุด "นอกตำรา": ต้องตอบว่าไม่มีข้อมูล ไม่ใช่ดึงหัวข้อที่แค่มีคำคล้ายกันมาตอบ
OUTSIDE_CASES = [dict(q=q, topic=None) for q in [
    "ราคาทองวันนี้", "วิธีทำต้มยำกุ้ง", "ภาษา C คืออะไร", "python list comprehension", "Transaction คืออะไร",
    "stored procedure คืออะไร", "MySQL คืออะไร", "NoSQL คืออะไร", "SQL Injection คืออะไร",
]]


def toc_cases(kb):
    """ถามทุกหัวข้อตามสารบัญ โดยพิมพ์ชื่อหัวข้อไม่มีเลข ("ชนิดของแฟ้มข้อมูล") ต้องได้หัวข้อนั้นและไม่มีหัวข้ออื่นปน
    (ข้ามชื่อที่ซ้ำกันสองหัวข้อ เช่น "ชนิดของข้อมูล" มีทั้ง 1.2 และ 8.2 และบทนำ/บทสรุป/แบบฝึกหัด)"""
    names = [kb._heading(e) for e in kb.ENTRIES]
    return [dict(q=name, topic=e["topic"].split(" · ")[0], only=True)
            for e, name in zip(kb.ENTRIES, names) if names.count(name) == 1 and not kb._is_meta(e["topic"])]


def content(kb, answer):
    """เนื้อหาจากตำราในคำตอบ: ไม่นับชื่อหัวข้อ ที่มา หมายเหตุ และปุ่ม (รูปนับ)"""
    drop = re.compile(r"^(## .*|แหล่งข้อมูล:.*|\[\[ถาม:.*|" + re.escape(kb.PARTIAL_NOTE) + r"|---)$", re.M)
    return drop.sub("", answer)


def check(kb, case, answer):
    """คืนรายการปัญหาของคำตอบ ([] = ผ่าน)"""
    topics = [line[3:] for line in answer.split("\n") if line.startswith("## ")]
    if case["topic"] is None:
        return [] if answer == kb.NO_DATA else [f"ควรตอบว่าไม่มีข้อมูล แต่ได้ {topics[:2] or answer[:40]!r}"]
    want = case["topic"] if isinstance(case["topic"], tuple) else (case["topic"],)
    problems = []
    if not topics or not topics[0].startswith(want):
        problems.append(f"หัวข้อผิด: ได้ {topics[:2] or answer[:40]!r}")
    if case.get("only") and any(not t.startswith(want) for t in topics):
        problems.append(f"มีหัวข้ออื่นปน: {[t for t in topics if not t.startswith(want)]}")
    body = content(kb, answer)
    problems += [f"ไม่มี {p!r}" for p in case.get("has", []) if p not in answer]
    problems += [f"เกินคำถาม: มี {p!r}" for p in case.get("lacks", []) if p in body]
    if case.get("max_chars") and len(body) > case["max_chars"]:
        problems.append(f"ยาวเกินคำถาม: {len(body)} ตัวอักษร (ไม่ควรเกิน {case['max_chars']})")
    return problems


def body_chars(kb, answer):
    """จำนวนตัวอักษรเนื้อหาจากตำรา (ไม่นับชื่อหัวข้อ แหล่งข้อมูล รูป และปุ่ม)"""
    body = re.sub(r"^(## .*|แหล่งข้อมูล:.*|!\[.*|\[\[ถาม:.*|---|" + re.escape(kb.PARTIAL_NOTE) + ")$", "", answer, flags=re.M)
    return len(body.strip())


def main():
    args = sys.argv[1:]
    use_ai, verbose = "--ai" in args, "-v" in args
    repeat = int(args[args.index("--repeat") + 1]) if "--repeat" in args else 0
    import app  # noqa: F401  โหลด .env แบบเดียวกับตอนรันเว็บ
    import ai_select
    import knowledge_base as kb
    from answer_memory import AnswerMemory
    if not use_ai:
        os.environ.pop("GEMINI_API_KEY", None)
    elif not ai_select.enabled():
        sys.exit("ต้องมี GEMINI_API_KEY ใน .env หรือ environment ถึงจะทดสอบแบบใช้ AI ได้")
    selector, calls = None, []
    if use_ai:
        print(f"AI: {ai_select.model_label()}")
        generate = ai_select._generate

        def counted(*a, **kw):
            # โควตาฟรีของ Gemini 15 ครั้ง/นาที/รุ่น: เว้นระยะให้ไม่เกิน 14 ครั้งในหนึ่งนาที
            while len(calls) >= 14 and time.time() - calls[-14] < 61:
                time.sleep(1)
            calls.append(time.time())
            return generate(*a, **kw)
        ai_select._generate = counted
        selector = ai_select.plan_answer
    if "--pin" in args:
        memory = AnswerMemory(app.ANSWERS_PATH, writable=True, model=ai_select.model_label())
        if "--fresh" in args:
            memory.forget()
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        os.unlink(tmp.name)
        memory = AnswerMemory(tmp.name, writable=True, model=ai_select.model_label())

    def ask(q, mem=memory):
        return kb.answer_from_dataset([{"role": "user", "content": q}], selector=selector, memory=mem)

    groups = [("หัวข้อตามสารบัญ", toc_cases(kb)), ("หัวเรื่องย่อยในเนื้อหา", HEADING_CASES),
              ("ที่ผู้ใช้รายงาน", REPORTED_CASES), ("เปรียบเทียบ", COMPARE_CASES), ("พิมพ์เอง", NATURAL_CASES), ("พิมพ์เองแบบถ้อยคำอื่น", PARAPHRASE_CASES), ("นอกตำรา", OUTSIDE_CASES)]
    total_fail = 0
    for name, cases in groups:
        fails = need_ai = 0
        for case in cases:
            answer = ask(case["q"])
            problems = check(kb, case, answer)
            # ถามซ้ำ (รวมแบบพิมพ์ต่างเล็กน้อย) ต้องได้คำตอบเดิมทุกตัวอักษร
            for again in (case["q"], case["q"] + " ครับ"):
                if ask(again) != answer:
                    problems.append(f"ถาม {again!r} ซ้ำแล้วได้คำตอบไม่เหมือนเดิม")
            topics = [line[3:] for line in answer.split("\n") if line.startswith("## ")]
            # ข้อที่ต้องตีความ (ai=True) ถ้าไม่ใช้ AI แล้วพลาด ไม่นับว่าไม่ผ่าน แต่แสดงให้เห็น
            mark = "ผ่าน" if not problems else ("ต้องใช้ AI" if case.get("ai") and not use_ai else "ไม่ผ่าน")
            part = " (เฉพาะส่วน)" if kb.PARTIAL_NOTE in answer else ""
            if problems or name != "หัวข้อตามสารบัญ":
                print(f"[{mark}] {case['q']} -> {topics[0] if topics else answer[:30]!r}{part} {body_chars(kb, answer)} ตัวอักษร")
            for p in problems:
                print("        ", p)
            if problems and verbose:
                print("\n".join("         | " + line[:150] for line in answer.split("\n") if line.strip()))
            fails += mark == "ไม่ผ่าน"
            need_ai += mark == "ต้องใช้ AI"
        total_fail += fails
        extra = f" (อีก {need_ai} ข้อต้องใช้ AI)" if need_ai else ""
        print(f"== {name}: ผ่าน {len(cases) - fails - need_ai}/{len(cases)}{extra}\n")
    if use_ai:
        print(f"เรียก AI ทั้งหมด {len(calls)} ครั้ง")
    if use_ai and repeat > 1:
        # ถาม AI ซ้ำโดยไม่ใช้ที่จำคำตอบ: แสดงว่าทำไมต้องจำ (AI เองตอบไม่เหมือนเดิมทุกครั้ง)
        varied = []
        for case in [c for _, cs in groups[1:] for c in cs]:
            answers = {ask(case["q"], mem=None) for _ in range(repeat)}
            if len(answers) > 1:
                varied.append(case["q"])
        print(f"== ถาม AI ซ้ำ {repeat} รอบโดยไม่จำคำตอบ: ได้คำตอบต่างกัน {len(varied)} ข้อ {varied}")
    if "--pin" not in args and os.path.exists(memory.path):
        os.unlink(memory.path)                 # ที่จำคำตอบชั่วคราวของการทดสอบ
    sys.exit(1 if total_fail else 0)


if __name__ == "__main__":
    main()
