"""โหลดตำราฐานข้อมูล (Markdown ที่แปลงจาก PDF) แล้วค้นหาหัวข้อที่เกี่ยวข้องกับคำถามผู้ใช้"""

import os
import re
import hashlib
import json

KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "knowledge")
MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "output/pdf/manifest.json")
DATASET_ERROR = ""
DOCUMENT_META = {}

_EMPTY = {"", "-", "–", "—"}

# คำภาษาอังกฤษที่พบบ่อยจนไม่ช่วยแยกแยะหัวข้อ
_STOPWORDS = {"sql", "table", "column", "name", "value", "data", "the", "how", "what", "is", "in", "of", "to"}

# วลีภาษาไทยที่เป็นคำถาม/คำเชื่อม ตัดทิ้งก่อนสร้าง n-gram ไม่งั้นทุกหัวข้อจะได้คะแนนเท่ากันหมด
_TH_NOISE = [
    "คืออะไร", "คือ", "อะไรบ้าง", "อะไร", "ยังไงบ้าง", "ยังไง", "อย่างไร",
    "ช่วยอธิบาย", "อธิบาย", "ช่วยบอก", "ช่วย", "หน่อย", "ขอตัวอย่าง",
    "ตัวอย่าง", "อยากรู้", "อยากทราบ", "เรื่อง", "ครับ", "ค่ะ", "คะ", "นะ",
    "แล้ว", "และ", "หรือ", "ที่", "ให้", "ได้", "การ", "ของ", "แบบ", "ทำ", "ใช้",
    "ความแตกต่าง", "แตกต่าง", "ต่างกัน", "เปรียบเทียบ", "ไหม", "กับ", "มีกี่", "กี่",
]


# คนไทยถามด้วยคำธรรมดา แต่หัวข้อในไฟล์เป็นศัพท์อังกฤษ ตารางนี้เชื่อมสองฝั่งเข้าหากัน
# ระบบให้คะแนนคำอังกฤษที่ตรงกับหัวข้อสูงสุด การเติมคำอังกฤษให้จึงช่วยการค้นหาได้มาก
# คำอังกฤษฝั่งซ้ายต้องมีอยู่ในชื่อหัวข้อของตำรา ไม่งั้นเติมไปก็ไม่ช่วย
_ALIASES = {
    "aggregate": ("ผลรวม", "ยอดรวม", "ค่าเฉลี่ย", "เฉลี่ย", "มากสุด", "สูงสุด", "น้อยสุด", "ต่ำสุด",
                  "นับจำนวน", "ฟังก์ชันสรุป"),
    "group by": ("จัดกลุ่ม", "แยกตาม", "กรองหลังจัดกลุ่ม"),
    "order by": ("เรียงลำดับ", "จัดเรียง", "มากไปน้อย", "น้อยไปมาก"),
    "where": ("กรองข้อมูล", "เงื่อนไข"),
    "join": ("เชื่อมตาราง", "รวมตาราง", "สองตาราง", "หลายตาราง"),
    "distinct": ("ไม่ซ้ำ",),
    "aliases": ("ตั้งชื่อชั่วคราว", "ชื่อเล่น"),
    "create": ("สร้างตาราง", "สร้างฐานข้อมูล"),
    "alter": ("แก้ไขโครงสร้าง", "เพิ่มคอลัมน์"),
    "drop": ("ลบตาราง",),
    "insert": ("เพิ่มข้อมูล", "ใส่ข้อมูล"),
    "update": ("แก้ไขข้อมูล", "อัปเดต"),
    "delete": ("ลบข้อมูล", "ลบแถว"),
    "primary key": ("คีย์หลัก",),
    "foreign key": ("คีย์นอก",),
}

# ศัพท์ที่ผู้ใช้พิมพ์ได้หลายแบบ แต่ตำราใช้คำเดียว: เติมคำที่ตำราใช้ต่อท้ายคำถาม
# (ค่าที่สามเป็น True = แทนที่คำเดิมเลย เพราะคำอังกฤษเดิมจะไปตรงกับหัวข้ออื่น)
_REWRITES = [
    (r"weak entit(y|ies)", "เอ็นทิตี้แบบอ่อนแอ", True),
    (r"\b1\s*nf\b|first normal form", "นอมอลฟอร์มระดับที่ 1"),
    (r"\b2\s*nf\b|second normal form", "นอมอลฟอร์มระดับที่ 2"),
    (r"\b3\s*nf\b|third normal form", "นอมอลฟอร์มระดับที่ 3"),
    (r"นอร์มัลไลเซชัน|นอร์มัลไลเซชั่น|นอร์มอลไลเซชัน|นอมอลไลเซชั่น", "นอมอลไลเซชัน", True),
    (r"normali[sz]", "นอมอลไลเซชัน"),
    (r"นอร์มัลฟอร์ม|นอร์มอลฟอร์ม", "นอมอลฟอร์ม", True),
    (r"normal form", "นอมอลฟอร์ม"),
    (r"\bdbms\b", "ระบบจัดการฐานข้อมูล"),
    (r"data dictionary", "พจนานุกรมข้อมูล"),
    (r"\bentit(y|ies)\b|เอนทิตี|เอ็นทิตี(?!้)", "เอ็นทิตี้"),
    (r"\battributes?\b|แอตทริบิวท์|แอทริบิวต์|แอททริบิวต์", "แอตทริบิวต์"),
    (r"\brelations?\b|รีเลชั่น", "รีเลชัน"),
    (r"\b(having|group)\b", "group by"),
    (r"\b(count|avg|sum|max|min)\b", "aggregate"),
    (r"functional dependenc|dependency|ฟังก์ชันขึ้นต่อกัน", "ฟังก์ชันการขึ้นต่อกัน"),
    (r"\bschema\b|สคีมา", "โครงร่างฐานข้อมูล"),
    (r"data independence", "ความเป็นอิสระของข้อมูล"),
    (r"three.?(level|schema)|3.?(level|schema)", "สถาปัตยกรรม 3 ระดับ"),
    (r"\berd?\b|e-r diagram|อีอาร์", "er diagram"),
    (r"\binformation\b", "สารสนเทศ"),
    (r"\bsecurity\b", "ความปลอดภัย"),
    (r"\bwildcards?\b|ไวลด์การ์ด|\boperators?\b|ตัวดำเนินการ", "สัญลักษณ์"),
    (r"\bpassword\b|รหัสผ่าน|เข้ารหัส", "ระบบรักษาความปลอดภัยสำหรับผู้ใช้"),
]

# หัวข้อบทนำ บทสรุป และแบบฝึกหัด พูดกว้าง ๆ ทั้งบท ให้แพ้หัวข้อเนื้อหาจริง เว้นแต่ผู้ใช้ถามถึงเอง
_META_WORDS = ("บทนำ", "สรุป", "แบบฝึกหัด", "summary", "exercise")


def _alias_words(text):
    """หาคำอังกฤษที่ควรใช้ค้นหาเพิ่ม จากคำไทยที่ผู้ใช้พิมพ์"""
    found = set()
    for english, thai_terms in _ALIASES.items():
        if any(t in text for t in thai_terms):
            found.update(english.split())
    return found


def _clean(value):
    value = (value or "").strip()
    return "" if value in _EMPTY else value


def _md_prose(text):
    """ตัดเส้นคั่นแนวนอน (--- หรือ ***) ทิ้ง ไม่งั้นเส้นคั่นของหัวข้อถัดไป
    จะถูกดูดมาอยู่ท้ายคำอธิบายของหัวข้อก่อนหน้า"""
    text = re.sub(r"^[ \t]*(-{3,}|\*{3,}|_{3,})[ \t]*$", "", text, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _load_md(path):
    """อ่านไฟล์ Markdown ตามข้อตกลง:
    `## หัวข้อ` = 1 หัวข้อ, ข้อความถัดมา = เนื้อหา, `### แหล่งอ้างอิง` = บทและเลขหน้า"""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    parts = re.split(r"^##[ \t]+(?!#)(.+?)[ \t]*$", raw, flags=re.M)
    entries = []
    for i in range(1, len(parts) - 1, 2):
        topic = _clean(parts[i])
        if not topic:
            continue
        segs = re.split(r"^###[ \t]+(.+?)[ \t]*$", parts[i + 1], flags=re.M)
        named = {segs[j].strip().lower(): segs[j + 1] for j in range(1, len(segs) - 1, 2)}
        entries.append({
            "topic": topic,
            "description": _clean(_md_prose(segs[0])),
            "source": os.path.basename(path),
            "references": _md_prose(named.get("แหล่งอ้างอิง", "")),
        })
    return entries


def load_entries():
    """Fail closed: only load the verified textbook, never legacy files or a model."""
    global DATASET_ERROR, DOCUMENT_META
    DATASET_ERROR, DOCUMENT_META = "", {}
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            manifest = json.load(f)
        # basename กันไม่ให้ manifest ชี้ออกไปนอกโฟลเดอร์ที่กำหนด
        path = os.path.join(KNOWLEDGE_DIR, os.path.basename(manifest["markdown_filename"]))
        pdf_path = os.path.join(os.path.dirname(MANIFEST_PATH), os.path.basename(manifest["pdf_filename"]))
        for target, expected in (
            (path, manifest["markdown_sha256"]),
            (pdf_path, manifest["pdf_sha256"]),
        ):
            with open(target, "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() != expected:
                    raise ValueError("Handbook checksum mismatch")
        entries = _load_md(path)
        if len(entries) != manifest["topic_count"]:
            raise ValueError("Handbook topic count mismatch")
        DOCUMENT_META = manifest
    except (OSError, ValueError, KeyError, TypeError):
        DATASET_ERROR = "ชุดข้อมูลยังไม่พร้อมหรือไม่ตรงกับ PDF จึงหยุดตอบเพื่อป้องกันการใช้ข้อมูลผิดฉบับครับ"
        return []
    return entries


ENTRIES = load_entries()

_WORD_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
_THAI_RE = re.compile(r"[฀-๿]+")


def _strip_thai_noise(text):
    for phrase in _TH_NOISE:
        text = text.replace(phrase, " ")
    return text


def _thai_ngrams(text, sizes=(4, 3)):
    """ภาษาไทยไม่มีช่องว่างระหว่างคำ จึงใช้ n-gram ระดับตัวอักษรแทนการตัดคำ"""
    grams = set()
    for chunk in _THAI_RE.findall(_strip_thai_noise(text)):
        for size in sizes:
            if len(chunk) < size:
                continue
            for i in range(len(chunk) - size + 1):
                grams.add(chunk[i:i + size])
    return grams


def _expand(text):
    for pattern, extra, *replace in _REWRITES:
        if replace:
            text = re.sub(pattern, extra, text)
        elif re.search(pattern, text):
            text += " " + extra
    return text


def _numbers(text):
    """ตัวเลขที่มีความหมายในชื่อหัวข้อ เช่น 'ระดับที่ 3' โดยไม่นับเลขหัวข้อ 7.5 และลำดับ · 3."""
    text = re.sub(r"^\d+\.\d+ |· \d+\. |บทที่ \d+", " ", text)
    return set(re.findall(r"(?<![\d.])\d(?![\d.])", text))


def _chapter_of(topic):
    """'7.5 ...' / 'บทสรุป บทที่ 7 ...' / 'ภาคผนวก ก ...' -> '7' หรือ 'ก'"""
    m = re.match(r"^(\d+)\.\d+ ", topic) or re.search(r"บทที่ (\d+)", topic) or re.search(r"ภาคผนวก ([กข])", topic)
    return m.group(1) if m else ""


def _is_meta(topic):
    return topic.startswith(("บทสรุป", "แบบฝึกหัด")) or topic.endswith("(บทนำ)")


# คำที่ตามหลัง "ภาษา" แล้วยังหมายถึงภาษา SQL ในตำรา (เช่น ภาษา DDL = ภาษานิยามข้อมูลของ SQL)
_SQL_LANG_WORDS = {"sql", "ddl", "dml", "dcl", "data", "structured", "query"}


def _heading_matches(query):
    """พิมพ์หัวข้อในเล่มโดยไม่มีเลขหัวข้อ เช่น "โครงสร้างแฟ้มข้อมูลแบบเรียงลำดับ" "การทำนอมอลไลเซชัน" -> หัวข้อนั้น"""
    asked = {_term_key(t) for t in _asked_terms(query)} - {""}
    return [e for e in ENTRIES if not _is_meta(e["topic"]) and len(_term_key(_own_title(e))) >= 4
            and asked & {_term_key(_heading(e)), _term_key(_own_title(e))}]


def _data_type_topics(query):
    """เลือกหัวข้อชนิดข้อมูลตามบริบท แยกหัวข้อทั่วไป 1.2 กับชนิดข้อมูลใน Access/SQL 8.2

    ถ้าถามกว้าง ๆ โดยไม่ระบุบริบท ให้คืนทั้งสองหัวข้อที่ชื่อซ้ำกัน เพื่อไม่เดาแทนผู้ใช้
    และไม่ปล่อยให้คำว่า 'มีอะไรบ้าง' พาไปจับหัวข้ออื่นที่มีคำว่า 'ข้อมูล'.
    """
    text = query.lower().strip()
    if not re.search(r"(?:ชนิด|ประเภท)\s*(?:ของ\s*)?ข้อมูล|ข้อมูล\s*(?:ชนิด|ประเภท)|data\s+types?", text):
        return []
    general = re.search(r"\b1\.2\b|บทที่\s*1(?!\d)|ทั่วไป|พื้นฐาน|เบื้องต้น", text)
    # คำถามถึงชนิดข้อมูลเฉพาะของ Access มักไม่พิมพ์คำว่า Access ซ้ำ
    # (เช่น "ชนิดข้อมูล Yes/No") จึงต้องพิจารณาชื่อชนิดข้อมูลด้วย
    access = re.search(r"\b8\.2\b|บทที่\s*8(?!\d)|microsoft\s*access|\baccess\b|\bsql\b|ภาษา\s*sql|"
                       r"\byes\s*/?\s*no\b|\bshort\s+text\b|\blong\s+text\b|\bautonumber\b|"
                       r"\bole\s+object\b|\blookup\s+wizard\b|\bcurrency\b|\binteger\b|\bsingle\b|\bdouble\b", text)
    if general and not access:
        prefixes = ("1.2 ",)
    elif access and not general:
        prefixes = ("8.2 ",)
    else:
        prefixes = ("1.2 ", "8.2 ")
    return [e for e in ENTRIES if e["topic"].startswith(prefixes)]


def _special_topics(text):
    """คำถามพื้นฐานที่ชื่อหัวข้อตอบไม่ตรง จึงกำหนดหัวข้อไว้เอง"""
    text = text.lower().strip()
    def topics(*prefixes):
        return [e for e in ENTRIES if e["topic"].startswith(prefixes)]

    # วลีเชิงความหมายที่มักไม่ตรงกับชื่อหัวข้อในสารบัญ
    if re.search(r"ลำดับชั้น.{0,12}ข้อมูล|โครงสร้าง.{0,12}file\s*record\s*field", text):
        return topics("1.3 ")
    if re.search(r"\bdba\b|database\s+administrator|ผู้บริหารฐานข้อมูล|ผู้ดูแลระบบฐานข้อมูล", text):
        return topics("12.4 ")
    if re.search(r"ความปลอดภัย.{0,20}ฐานข้อมูล|รักษาความปลอดภัย.{0,20}ฐานข้อมูล|database\s+security", text):
        return topics("12.4 ")
    if re.search(r"conceptual\s+level|ระดับแนวคิด", text):
        return topics("3.5 ")
    if re.search(r"external\s+level|ระดับภายนอก", text):
        return topics("3.4 ")
    if re.search(r"internal\s+level|ระดับภายใน", text):
        return topics("3.6 ")
    if re.search(r"\bdbms\b|database\s+management\s+system|ระบบจัดการฐานข้อมูล", text):
        return topics("2.3 ")
    if re.search(r"\bdatabase\b|ฐานข้อมูล\s*\(database\)|ฐานข้อมูลคือ|ฐานข้อมูลหมายถึง", text) \
            and not re.search(r"create\s+database|สร้างฐานข้อมูล", text):
        return topics("2.2 ")
    if re.search(r"\bddl\b", text) and re.search(r"\bdml\b", text):
        return topics("8.1 ")
    if re.search(r"ความหมายและองค์ประกอบการแปลง", text):
        return topics("6.1 ")
    if re.search(r"\ber\s*[- ]?diagram\b|แผนภาพอีอาร์|อีอาร์ไดอะแกรม", text) \
            and re.search(r"แปลง|ขั้นตอน|transform|convert", text):
        return topics("6.2 ")
    if re.search(r"\brelation\b|รีเลชัน", text) \
            and not re.search(r"\bjoin\b|แปลง|convert|transform|รีเลชันชิพ", text):
        return topics("4.4 ")
    if re.search(r"แอตทริบิวต์.{0,30}ทูเพิล|ทูเพิล.{0,30}แอตทริบิวต์|\battribute\b.{0,30}\btuple\b", text):
        return topics("4.4 ")
    if re.search(r"\bweak\s+(?:entity|entities)\b|เอ็นทิตี้แบบอ่อนแอ|เอนทิตี้แบบอ่อน", text):
        if re.search(r"แปลง|convert|mapping", text):
            return topics("6.4 ")
        return topics("5.3 เอ็นทิตี้ · 2.")
    if re.search(r"\bstrong\s+(?:entity|entities)\b|เอ็นทิตี้แบบปกติ|เอนทิตี้ปกติ", text):
        if re.search(r"แปลง|convert|mapping", text):
            return topics("6.4 ")
        return topics("5.3 เอ็นทิตี้ · 1.")
    if re.search(r"\brecursive\s+entities?\b|เอ็นทิตี้เรียกซ้ำ|เอนทิตี้เรียกซ้ำ", text):
        return topics("5.3 เอ็นทิตี้ · 2.")
    if re.search(r"entity\s+relationship|เอ็นทิตี้รีเลชันชิพ", text):
        return topics("5.3 เอ็นทิตี้ · 3.")
    if re.search(r"เอ็นทิตี้.{0,30}แอตทริบิวต์|เอนทิตี.{0,30}แอตทริบิวต์", text) \
            and re.search(r"ต่างกัน|เปรียบเทียบ|กับ", text):
        return topics("5.3 ", "5.4 ")
    if re.search(r"\bentity\b|เอ็นทิตี้|เอนทิตี", text) and not re.search(r"entity\s+integrity|ความคงสภาพของเอ็นทิตี้", text):
        if re.search(r"แปลง|convert|mapping", text):
            return topics("6.4 ")
        if re.search(r"คืออะไร|หมายถึง|what\s+is|ความหมาย", text) \
                and not re.search(r"แอตทริบิวต์|attribute|ต่างกัน|เปรียบเทียบ", text):
            return topics("5.3 ")
    if re.search(r"แอตทริบิวต์หลายค่า|multivalued\s+attribute|multi.?valued\s+attribute", text) \
            and re.search(r"แปลง|รีเลชัน|ตาราง|convert", text):
        return topics("6.3 ")
    if re.search(r"\b1\s*:\s*m\b|\b1\s*:\s*n\b|หนึ่งต่อกลุ่ม|one\s+to\s+many", text) \
            and re.search(r"แปลง|ตาราง|รีเลชัน|convert", text):
        return topics("6.6 ")
    if re.search(r"\bm\s*:\s*n\b|\bm\s*:\s*m\b|กลุ่มต่อกลุ่ม|many\s+to\s+many", text) \
            and re.search(r"แปลง|ตาราง|รีเลชัน|convert", text):
        return topics("6.7 ")
    if re.search(r"\b1\s*:\s*1\b|หนึ่งต่อหนึ่ง|one\s+to\s+one", text) \
            and re.search(r"แปลง|ตาราง|รีเลชัน|convert", text):
        return topics("6.5 ")
    if re.search(r"วัตถุประสงค์|เป้าหมาย|ทำไมต้อง|ประโยชน์", text) \
            and re.search(r"นอมอล|normaliz", text):
        return topics("7.1 ")
    if re.search(r"create\s+table|สร้างตาราง", text) and re.search(r"primary\s+key|foreign\s+key|คีย์หลัก|คีย์นอก", text):
        return topics("8.3 ")
    if re.search(r"not\s*null|unique", text):
        return topics("8.3 ")
    if re.search(r"\blike\b", text) and re.search(r"ค้น|ข้อความ|เงื่อนไข|ใช้", text):
        return topics("9.6 ")
    if re.search(r"แนวโน้ม.{0,30}(?:เทคโนโลยี|ฐานข้อมูล)|เทคโนโลยี.{0,30}ฐานข้อมูล", text):
        return topics("บทที่ 11 ")
    if re.search(r"ภัยคุกคาม|threat", text):
        return topics("12.3 ")
    if re.search(r"\bgrant\b|\brevoke\b|กำหนดสิทธิ์|กำหนดสิทธิ", text):
        return topics("12.4 ")
    if re.search(r"backup|recovery|สำรอง.{0,10}กู้คืน|กู้คืน.{0,10}สำรอง", text):
        return topics("12.6 ")
    if re.search(r"access\s+control|ควบคุมการเข้าถึง", text):
        return topics("12.4 ")
    if re.search(r"\bentity\s+integrity\b|ความคงสภาพของข้อมูล|data\s+integrity", text):
        return topics("4.6 ")

    # คำถามเชิงความหมายที่กล่าวถึงเนื้อหาในย่อหน้าหรือรายการย่อย
    # แต่คำสำคัญไม่ได้ปรากฏในชื่อหัวข้อ (ต้องตรวจชุดข้อมูลก่อนตอบว่าไม่พบ)
    if re.search(r"สารสนเทศ", text) and re.search(r"คุณสมบัติ|ลักษณะ|ที่ดี|ดีควร", text):
        return [e for e in ENTRIES if e["topic"].startswith("1.1 ")][:1]
    if re.search(r"ข้อมูล\s*(?:วันที่และเวลา|วันและเวลา)|date\s*time", text):
        return [e for e in ENTRIES if e["topic"].startswith("1.2 ")][:1]
    if re.search(r"ข้อมูล\s*(?:เสียง)|\bsound\b", text):
        return [e for e in ENTRIES if e["topic"].startswith("1.2 ")][:1]
    if (re.search(r"แยก\s*(?:แฟ้ม|ไฟล์)|แฟ้มข้อมูล.*แยก|เก็บ.*แยกจากกัน", text)
            and re.search(r"รวบรวม|ล่าช้า|ช้า|เข้าถึง|แผนก", text)):
        return [e for e in ENTRIES if e["topic"].startswith("1.6 ข้อจำกัดของวิธีแฟ้มข้อมูล · 1.")][:1]
    if (re.search(r"แถว|ทูเพิล|เรคอร์ด|ระเบียน", text)
            and re.search(r"ระบุ|ชี้|แยกแยะ|ไม่ซ้ำ|เอกลักษณ์", text)
            and re.search(r"คีย์|ตาราง|ข้อมูล", text)):
        return [e for e in ENTRIES if e["topic"].startswith("4.5 ประเภทของคีย์ · 3.")][:1]
    if re.search(r"\bddl\b|data\s+definition\s+language|ภาษาสำหรับนิยามข้อมูล", text):
        return [e for e in ENTRIES if e["topic"].startswith("8.1 ")][:1]
    if re.search(r"(?:what is sql\b|(?<![\w-])sql\s*(?:คืออะไร|ทำอะไรได้|ใช้ทำอะไร|มี\s*กี่\s*(?:ประเภท|แบบ)|"
                 r"แบ่ง(?:ได้|เป็น|ออกเป็น|ออกได้)?\s*(?:กี่\s*)?(?:ประเภท|แบบ)|ประเภท(?:อะไร)?บ้าง)"
                 r"|(?:ประเภท|ชนิด)\s*(?:คำสั่ง\s*)?sql\s*(?:มีอะไรบ้าง|อะไรบ้าง|มีกี่(?:ประเภท|แบบ))"
                 r"|ภาษา sql คือ|ความหมายของภาษา sql)", text):
        return [e for e in ENTRIES if e["topic"].startswith("8.1 ")][:1]
    # "JOIN คืออะไร" ถามคำสั่ง JOIN ทั่วไป: บทนำบทที่ 10 อธิบายการเชื่อมตาราง + ตารางรูปแบบ JOIN ทุกชนิดใน 10.2
    # (ไม่งั้นได้ "10.1 การเกิด CARTESIAN JOIN" ซึ่งเป็น JOIN ชนิดเดียว)
    if re.fullmatch(r"(คำสั่ง\s*)?join(\s+table)?", " ".join(_asked_terms(text)).strip()):
        return [e for e in ENTRIES if e["topic"].startswith(("บทที่ 10 ", "10.2 "))]
    return []


_MISSING_BOOK_TOPICS = re.compile(
    r"\bdata\s+warehouse\b|\bwarehouse\b|คลังข้อมูล|"
    r"\bdistributed\s+database\b|ฐานข้อมูลแบบกระจาย|ฐานข้อมูลกระจาย|"
    r"\bcloud\s+database\b|ฐานข้อมูลบนคลาวด์|ฐานข้อมูลบน cloud",
    re.I,
)


def _explicitly_missing_topic(text):
    """แนวคิดที่ตรวจแล้วว่าไม่มีคำอธิบายในชุดตำราปัจจุบัน ต้องไม่จับไปหัวข้อที่มีคำคล้ายกัน"""
    return bool(_MISSING_BOOK_TOPICS.search(text))


def search(query, limit=6, min_score=1.0):
    """Require topic evidence: a word in the body alone is not evidence the book explains it."""
    query = _split_glued(query)
    text = query.lower().strip()
    if _explicitly_missing_topic(text) or (re.search(r"รหัสผ่าน|password", text)
                                           and re.search(r"มหาวิทยาลัย|ระบบของฉัน|ของฉัน", text)):
        return []
    exact = [entry for entry in ENTRIES if entry["topic"].lower() == text]
    if exact:
        return exact[:limit]
    data_types = _data_type_topics(text)
    if data_types:
        return data_types[:limit]
    special = _special_topics(text)
    if special:
        return special[:limit]
    same = _heading_matches(query)
    if same:
        return same[:limit]
    # ระบุเลขหัวข้อมาตรง ๆ เช่น "7.5" (เลขภาพ/ตารางไม่ใช่เลขหัวข้อ)
    num = re.search(r"(?<![\d.])(\d{1,2}\.\d{1,2})(?![\d.])", _CAP_REF.sub(" ", text))
    if num:
        by_num = [e for e in ENTRIES if e["topic"].startswith(num.group(1) + " ")]
        if by_num:
            return by_num[:1]
    if re.search(r"ภาคผนวก\s*[ค-ฮ]", text):
        return []   # ตำรามีแค่ภาคผนวก ก และ ข
    chapter = re.search(r"บทที่\s*(\d{1,2})|ภาคผนวก\s*([กข])", text)
    pool = ENTRIES
    if chapter:
        wanted = chapter.group(1) or chapter.group(2)
        pool = [e for e in ENTRIES if _chapter_of(e["topic"]) == wanted] or ENTRIES
        text = text.replace(chapter.group(0), " ")
    meta_query = any(k in text for k in _META_WORDS)

    # ตำรามีแต่ "ภาษา SQL" ถ้าถามภาษาอื่น (ภาษา C, Python, Java) คำว่า "ภาษา" อย่างเดียว
    # จะพาไปเจอหัวข้อ "8.1 ความหมายของภาษา SQL" ทั้งที่ตำราไม่ได้พูดถึงภาษานั้นเลย
    lang = re.search(r"ภาษา\s*([a-z][a-z0-9+#]*|ซี|จาวา|ไพทอน|ไพธอน)", text)
    if lang and lang.group(1) not in _SQL_LANG_WORDS:
        return []

    text = _expand(text)
    words = set(_WORD_RE.findall(text)) - _STOPWORDS - {"function", "use", "explain", "does"}
    words |= _alias_words(text)
    english = " ".join(_WORD_RE.findall(query.lower()))
    grams = _thai_ngrams(text)
    numbers = _numbers(text)
    ranked = []
    for e in pool:
        topic = e["topic"].lower()
        tokens = set(_WORD_RE.findall(topic))
        hits = words & tokens
        thai = _thai_ngrams(topic)
        overlap = len(grams & thai) / max(1, len(grams))
        if not hits and not (len(grams & thai) >= 3 and overlap >= .45):
            continue
        score = 10 * len(hits) + overlap * 8
        if words and hits:
            score += 5 * len(hits) / len(words)
        # วลีอังกฤษหลายคำตรงกับชื่อหัวข้อทั้งวลี เช่น "many to many"
        if " " in english and english in topic:
            score += 15
        score += 6 * len(numbers & _numbers(topic))
        # คะแนนเท่ากัน ให้หัวข้อที่ชื่อตรงกับคำถามเกือบทั้งชื่อชนะ (เช่น "5.3 เอ็นทิตี้" ชนะ
        # "4.6 กฎความคงสภาพ… · 1. กฎความคงสภาพของเอ็นทิตี้" เมื่อถาม "เอ็นทิตี้มีกี่ประเภท")
        # (หัวข้อย่อยวัดเฉพาะชื่อส่วนของตัวเอง ไม่นับชื่อหัวข้อหลักที่นำหน้า)
        own = _thai_ngrams(topic.split(" · ")[-1])
        if own:
            score += .5 * len(grams & own) / len(own)   # น้ำหนักน้อย ใช้ตัดสินเฉพาะตอนคะแนนใกล้กัน
        if _is_meta(e["topic"]) and not meta_query:
            score *= .3
        ranked.append((score, e))
    ranked.sort(key=lambda x: x[0], reverse=True)
    if not ranked:
        if chapter and pool is not ENTRIES:
            # ถามถึงบทเฉย ๆ เช่น "บทที่ 7" ให้บทนำของบทนั้น
            return [e for e in pool if e["topic"].endswith("(บทนำ)")][:1] or pool[:1]
        return []

    def coverage(topic):
        """ส่วนของคำถามที่ชื่อหัวข้อนี้ตอบ: คำอังกฤษ ตัวเลข และ n-gram ไทยที่ตรงกัน"""
        topic = topic.lower()
        return ({"w:" + w for w in words & set(_WORD_RE.findall(topic))}
                | {"n:" + n for n in numbers & _numbers(topic)}
                | {"g:" + g for g in grams & _thai_ngrams(topic)})

    def adds(cov, base):
        """cov ตอบส่วนของคำถามที่ base ยังไม่ได้ตอบจริงไหม (ไม่ใช่แค่ตัวอักษรซ้ำบังเอิญ 1-2 ชิ้น)"""
        new = cov - base
        new_grams = sum(1 for x in new if x.startswith("g:"))
        return any(not x.startswith("g:") for x in new) or new_grams >= max(3, .25 * len(grams))

    by_topic = {e["topic"]: e for e in ENTRIES}
    cut = max(min_score, ranked[0][0] * .7)
    chosen, covered = [], set()
    for score, e in ranked:
        if score < cut or len(chosen) >= limit:
            break
        cov = coverage(e["topic"])
        parent = by_topic.get(e["topic"].split(" · ")[0])
        if parent is not e and parent is not None:
            if any(c is parent for c in chosen):
                continue   # ตอบทั้งหัวข้อหลักไปแล้ว ส่วนย่อยรวมอยู่ในนั้น
            # ส่วนย่อยตรงกับคำถามแค่เพราะชื่อหัวข้อหลัก (เช่น "ประเภทของคีย์") ให้ตอบทั้งหัวข้อ ไม่ใช่ส่วนเดียว
            parent_cov = coverage(parent["topic"])
            if not adds(cov, parent_cov):
                e, cov = parent, parent_cov
        if any(c is e for c in chosen):
            continue
        # หัวข้อถัดไปต้องตอบส่วนของคำถามที่หัวข้อก่อนหน้ายังไม่ได้ตอบ (เช่น LEFT JOIN ใน "INNER JOIN กับ LEFT JOIN")
        # ไม่งั้นเป็นแค่หัวข้อที่มีคำซ้ำ ไม่ใช่เรื่องที่ถาม
        if chosen and not adds(cov, covered):
            continue
        # บทนำ/บทสรุป/แบบฝึกหัด พูดกว้าง ๆ ทั้งบท ไม่ดึงมาเป็นหัวข้อเสริม เว้นแต่ผู้ใช้ถามถึงเอง
        if chosen and _is_meta(e["topic"]) and not meta_query:
            continue
        chosen.append(e)
        covered |= cov
    return chosen


BOOK_NAME = "การจัดการระบบฐานข้อมูลเพื่องานธุรกิจ"
HELP_HINT = 'พิมพ์ "ตอบอะไรได้บ้าง" เพื่อดูหัวข้อทั้งหมด'
NO_DATA = ("ไม่มีข้อมูลเรื่องนี้ในตำราครับ\n\n"
           f"ผมตอบได้เฉพาะเรื่องฐานข้อมูลและ SQL จากตำรา **{BOOK_NAME}** — {HELP_HINT}")

EXAMPLES = ["คีย์หลัก (Primary Key) คืออะไร", "ER Diagram คืออะไร", "นอมอลฟอร์มระดับที่ 3 (3NF)",
            "INNER JOIN กับ LEFT JOIN ต่างกันยังไง", "GROUP BY กับ HAVING ใช้ยังไง"]

# คำถามถึงตัวบอท ไม่ใช่คำถามเนื้อหา: ตัดคำสุภาพ/สรรพนามทิ้งแล้วต้องเหลือตรงกับวลีเหล่านี้ทั้งหมด
# (เทียบทั้งประโยค เพื่อไม่ให้ "SQL ทำอะไรได้บ้าง" กลายเป็นคำถามถึงบอท)
_POLITE = re.compile(r"[\s?!.ๆ]+|ครับ|คับ|ค่ะ|คะ|นะ|จ้า|จ้ะ|หน่อย|มากๆ|มาก")
# สรรพนามเรียกบอท ตัดทิ้งเฉพาะตอนเช็กคำถามถึงบอท (ห้ามตัดก่อนเช็ก "ขอบคุณ" ไม่งั้นเหลือ "ขอบ")
_PRONOUNS = re.compile(r"คุณ|บอท|ครูเอสคิว|นาย|เธอ|แก|น้อง")
_GREETINGS = ("สวัสดี", "หวัดดี", "ดีจ้า", "hello", "hi", "hey")
_THANKS = ("ขอบคุณ", "ขอบใจ", "thanks", "thankyou", "thx")
_ABOUT_BOT = {
    "ตอบอะไรได้บ้าง", "ตอบอะไรได้", "ตอบเรื่องอะไรได้บ้าง", "ตอบเรื่องอะไรบ้าง", "ทำอะไรได้บ้าง", "ทำอะไรได้",
    "ช่วยอะไรได้บ้าง", "ช่วยอะไรได้", "ถามอะไรได้บ้าง", "ถามอะไรได้", "ถามเรื่องอะไรได้บ้าง", "รู้อะไรบ้าง",
    "รู้เรื่องอะไรบ้าง", "มีหัวข้ออะไรบ้าง", "มีเรื่องอะไรบ้าง", "คือใคร", "เป็นใคร", "ใช้งานยังไง", "ใช้งานอย่างไร",
    "วิธีใช้", "help", "/help", "เมนู", "menu",
}


def _about_bot():
    chapters = [e["topic"].removesuffix(" (บทนำ)") for e in ENTRIES if e["topic"].endswith("(บทนำ)")]
    return "\n".join(
        [f"ผมครูเอสคิว ตอบคำถามเรื่องฐานข้อมูลและ SQL จากตำรา **{BOOK_NAME}** เท่านั้น "
         "ไม่แต่งคำตอบเอง ถ้าเรื่องไหนตำราไม่มี ผมจะบอกว่าไม่มีข้อมูลครับ", "", "ตำราแบ่งเป็นหัวข้อเหล่านี้"]
        + ["- " + c for c in chapters]
        + ["", "ลองถามเช่น"] + ["- " + q for q in EXAMPLES]
        + ["", "ถามด้วยเลขหัวข้อก็ได้ เช่น 7.5 หรือ แบบฝึกหัดบทที่ 7"])


def small_talk(query):
    """คำทักทาย คำขอบคุณ และคำถามว่าบอทตอบอะไรได้ ตอบด้วยข้อความคงที่ ไม่ค้นในตำรา"""
    text = _POLITE.sub("", query.lower())
    for g in _GREETINGS:
        if text.startswith(g):
            rest = text[len(g):]
            if not rest:
                return ("สวัสดีครับ ผมครูเอสคิว ถามเรื่องฐานข้อมูลและ SQL ได้เลย เช่น "
                        + ", ".join(EXAMPLES[:3]) + "\n\n" + HELP_HINT)
            text = rest   # "สวัสดี ตอบอะไรได้บ้าง" ให้ดูส่วนที่เหลือต่อ
            break
    if text in _THANKS:
        return "ยินดีครับ มีคำถามเรื่องฐานข้อมูลหรือ SQL ถามต่อได้เลยครับ"
    if _PRONOUNS.sub("", text) in _ABOUT_BOT:
        return _about_bot()
    return None


FIGURE_DIR = os.path.join(os.path.dirname(__file__), "static", "figures")
FIGURE_URL = "/static/figures/"
_CAPTION_RE = re.compile(r"^ภาพที่\s*(\d+\.\d+)(?!\d)")


def with_figures(description):
    """ใส่รูปจากตำรา (ตัดจากหน้า PDF ไว้ล่วงหน้า) ไว้เหนือบรรทัดคำบรรยาย "ภาพที่ X.Y" แบบเดียวกับในเล่ม
    ใช้เฉพาะรูปที่อยู่ใน manifest และมีไฟล์อยู่จริง"""
    figures = {f["figure"]: f for f in DOCUMENT_META.get("figures", [])}
    if not figures:
        return description
    out = []
    for line in description.split("\n"):
        m = _CAPTION_RE.match(line)
        f = figures.get(m.group(1)) if m else None
        if f and os.path.isfile(os.path.join(FIGURE_DIR, os.path.basename(f["file"]))):
            out.append(f"![ภาพที่ {f['figure']}]({FIGURE_URL}{os.path.basename(f['file'])})")
        out.append(line)
    return "\n".join(out)


def section_parts(entry):
    """หัวข้อยาวถูกแบ่งเป็นส่วนย่อย ("4.5 ประเภทของคีย์ · 3. คีย์หลัก") ถ้าตอบหัวข้อหลัก ต้องได้ครบทุกส่วน
    ไม่ใช่แค่ย่อหน้านำ (ซึ่งมักจบด้วย "ดังรายละเอียดต่อไปนี้")"""
    if " · " in entry["topic"]:
        return [entry]
    return [entry] + [e for e in ENTRIES if e["topic"].startswith(entry["topic"] + " · ")]


# ---------------------------------------------------------------- บทสนทนาต่อเนื่อง
# ถามต่อสั้น ๆ เช่น "ขอตัวอย่างเพิ่ม" "อธิบายเพิ่ม" "มันต่างกันยังไง" ต้องรู้ว่ากำลังคุยเรื่องอะไรอยู่
# เรื่องที่คุยอยู่ = หัวข้อ (บรรทัด "## ") ในคำตอบล่าสุดของบอท ซึ่งเบราว์เซอร์ส่งประวัติมาทุกครั้ง
_EXAMPLE_RE = re.compile(r"ตัวอย่าง|example", re.I)
_MORE_RE = re.compile(r"อธิบายเพิ่ม|อธิบายต่อ|ขยายความ|ละเอียด|เพิ่มเติม|ข้อมูลเพิ่ม|มีอะไรอีก|อะไรอีก|มีอีก|อีกไหม|"
                      r"เกี่ยวข้อง|เกี่ยวกับหัวข้อนี้|เกี่ยวกับเรื่องนี้|ต่อเลย|ต่อไป|เล่าต่อ|\bmore\b", re.I)
_COMPARE_RE = re.compile(r"ต่างกัน|ต่างจาก|แตกต่าง|เทียบ|เหมือนกันไหม|\bvs\b", re.I)
# ต่อจากคำตอบตัวอย่าง: "อีก" "มีอีกไหม" "ต่อ" สั้น ๆ = ขอตัวอย่างต่อ
# (แต่ "เพิ่มเติมที่เกี่ยวกับหัวข้อนี้" "อธิบายเพิ่ม" = ขอหัวข้อที่เกี่ยวข้อง)
_AGAIN_RE = re.compile(r"^(มี|ขอ|เอา)?(อีก|ต่อ)|อีก(ไหม|มั้ย|หน่อย|สิ|ครับ|ค่ะ)?$|\bmore\b", re.I)
_RELATED_RE = re.compile(r"เกี่ยว|อธิบาย|ขยายความ|ละเอียด|หัวข้อ")
# คำที่อ้างถึงเรื่องที่คุยอยู่ ("มันต่างจาก…", "เรื่องนี้…") ถ้าไม่มี ถือว่าเป็นคำถามใหม่ที่ครบในตัวเอง
_BACKREF_RE = re.compile(r"มัน|อันนี้|อันนั้น|ตัวนี้|เรื่องนี้|หัวข้อนี้|ข้างบน|เมื่อกี้|ที่แล้ว|ก่อนหน้า|สองอัน|ทั้งสอง|\bit\b|\bthis\b", re.I)
# คำที่ใช้ถามต่อ ตัดทิ้งก่อนดูว่าผู้ใช้เอ่ยถึงหัวข้อใหม่ไหม
_FOLLOW_WORDS = re.compile(
    r"ขอ|ยก|เอา|ดู|ตัวอย่าง|example|อธิบาย|เพิ่มเติม|เพิ่ม|ขยายความ|ละเอียด|ข้อมูล|อีก|ไหม|หน่อย|ต่อ|เลย|ไป|"
    r"เล่า|เกี่ยวข้อง|เกี่ยวกับ|หัวข้อ|เรื่อง|นี้|นั้น|มัน|อันนี้|แล้ว|ล่ะ|ต่างกัน|ต่างจาก|แตกต่าง|เทียบ|"
    r"เหมือนกัน|ยังไง|อย่างไร|อะไร|มี|บ้าง|ครับ|ค่ะ|คะ|นะ|จ้า|\bmore\b|\bvs\b|[\s?!.,ๆ]+", re.I)
_GENERIC_TERMS = {"sql", "table", "microsoft access", "access", "data", "er", "a", "b", "fk"}
EXAMPLES_PER_ANSWER = 3


def _answer_topics(text):
    return [line[3:].strip() for line in text.split("\n") if line.startswith("## ")]


def conversation_context(history):
    """หัวข้อในคำตอบล่าสุดที่เป็นเนื้อหาจากตำรา (ข้ามคำตอบคงที่/รายการตัวอย่าง ซึ่งไม่มีบรรทัด "## ")
    คืน (หัวข้อล่าสุด, หัวข้อก่อนหน้าที่ต่างออกไป, ข้อความที่บอทเคยแสดงแล้วทั้งหมด)"""
    by_topic = {e["topic"]: e for e in ENTRIES}
    answers = [str(m.get("content") or "") for m in history
               if isinstance(m, dict) and m.get("role") == "assistant"]
    topic_answers = [[by_topic[t] for t in _answer_topics(a) if t in by_topic] for a in answers]
    topic_answers = [t for t in topic_answers if t]
    current = topic_answers[-1] if topic_answers else []
    previous = next((t for t in reversed(topic_answers[:-1])
                     if {e["topic"] for e in t} != {e["topic"] for e in current}), [])
    return current, previous, "\n".join(answers)


def key_terms(entry):
    """คำหลักของหัวข้อ ใช้หาตัวอย่าง/หัวข้อที่เกี่ยวข้อง: วลีอังกฤษในชื่อ (GROUP BY, Primary Key)
    และชื่อไทยของหัวข้อย่อย (คีย์หลัก) ถ้าไม่มีวลีอังกฤษ ใช้ชื่อไทยของหัวข้อ"""
    title = entry["topic"].split(" · ")[-1]
    title = re.sub(r"^(ภาคผนวก [กข] )?(\d+\.)+\d*\s*", "", title)
    english = [p.strip() for p in re.findall(r"[A-Za-z][A-Za-z0-9_ \-]*[A-Za-z0-9_]", title)]
    english = [p for p in english if p.lower() not in _GENERIC_TERMS and len(p) >= 3]
    # วลีไทยของชื่อ (ไม่เอาวงเล็บและคำอังกฤษ แต่เก็บตัวเลข เช่น "นอมอลฟอร์มระดับที่ 3")
    thai = re.sub(r"\(.*\)|[A-Za-z_:/\-]+", " ", title)
    thai = re.sub(r"\s+", " ", thai).strip()
    thai = [thai] if len(thai) >= 4 else []
    if " · " in entry["topic"] or not english:
        return english + thai
    return english


def _blocks(description):
    """แบ่งเนื้อหาเป็นก้อน: บล็อกโค้ด ```...``` ทั้งก้อน หรือบรรทัดข้อความ"""
    lines, out, i = description.split("\n"), [], 0
    while i < len(lines):
        if lines[i].startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append(("code", "\n".join(lines[i:j + 1])))
            i = j + 1
        else:
            out.append(("text", lines[i]))
            i += 1
    return out


def _example_end(us, k, used):
    """ตัวอย่างที่ขึ้นหัวไว้ที่ย่อหน้า k ("ตัวอย่างที่ 1 การวิเคราะห์…") ยาวถึงไหน: ก่อนตัวอย่าง/หัวเรื่องถัดไป
    และยาวราว BLOCK_CHARS (ตารางที่กำลังแสดงอยู่แสดงจนครบ)"""
    size, j = 0, k + 1
    while j < len(us) and j not in used:
        t = us[j].strip()
        row = " | " in t
        if (t.startswith("ตัวอย่าง") and len(t) <= 80 and not row) or _SUBNUM.match(t) or _SUMMARY_RE.match(t):
            break
        if size >= BLOCK_CHARS and not row:
            break
        size, j = size + len(t), j + 1
    return j


def _example_snippets(entry, terms):
    """ตัวอย่างในหัวข้อนี้ที่เกี่ยวกับคำหลัก (ข้อความจากตำราตรงตัว) เรียงตามลำดับในหัวข้อ:
    คำสั่ง SQL ที่มีคำหลัก + บรรทัดนำ ("ตัวอย่างที่ …") + ตารางผลลัพธ์ที่ตามมา, บรรทัด "เช่น …" ที่มีคำหลัก
    หรือหัวตัวอย่าง ("ตัวอย่างข้อมูล") พร้อมเนื้อตัวอย่างที่ตามมา"""
    blocks = _blocks(entry["description"])
    us = [text for _, text in blocks]
    # terms = None: ตัวอย่างทุกอันของหัวข้อนี้ (หัวข้อที่ชื่อคือเรื่องที่ถาม และแสดงไปแค่บางส่วน)
    has = lambda t: terms is None or any(term.lower() in t.lower() for term in terms)
    found, used = [], set()
    for k, (kind, text) in enumerate(blocks):
        if kind == "code" and has(text):
            lead = [j for j in range(max(0, k - 2), k) if blocks[j][0] == "text" and blocks[j][1].strip()]
            start = next((j for j in lead if blocks[j][1].startswith("ตัวอย่างที่")), lead[-1] if lead else k)
            end = k + 1
            while end < len(blocks) and end - k <= 15 and blocks[end][0] == "text" and (
                    " | " in blocks[end][1] or blocks[end][1].startswith("ตารางที่")):
                end += 1
            used.update(range(start, end))
            found.append((start, "\n".join(us[start:end])))
    for k, (kind, text) in enumerate(blocks):
        head = text.strip()
        if k in used or kind != "text" or not has(text) or not re.search(r"ตัวอย่าง|เช่น", text) or text.startswith("ภาพที่"):
            continue
        if len(head) <= 80 and _INTRO_END.search(head):
            continue                           # บรรทัดเกริ่น ("…พิจารณาได้จากตัวอย่างดังต่อไปนี้") ยังไม่ใช่ตัวอย่าง
        end = k + 1
        if head.startswith("ตัวอย่าง") and len(head) <= 80 and " | " not in head:
            # หัวตัวอย่าง: เอาเนื้อตัวอย่างที่ตามมาด้วย (หัวอย่างเดียวไม่ใช่ตัวอย่าง)
            end = max(subheading_block(entry, k)) + 1 if _is_subheading(us, k) else _example_end(us, k, used)
        used.update(range(k, end))
        found.append((k, "\n".join(us[k:end])))
    return [snippet for _, snippet in sorted(found)]


def _topic_name(current):
    return " / ".join(dict.fromkeys(e["topic"].split(" · ")[0] if len(current) > 1 else e["topic"] for e in current))


def _source_line(e):
    return "แหล่งข้อมูล: " + (e.get("references") or e["topic"]) + " · ไฟล์ " + e["source"]


def _unseen_part(snippet, seen):
    """ตัวอย่างที่ยังไม่ได้แสดง: None = แสดงไปแล้วทั้งก้อน, ถ้าคำตอบก่อนหน้าแสดงต้นย่อหน้านี้ไปแล้ว (ตัดก่อน "เช่น …")
    คืนเฉพาะท่อนตัวอย่างที่เหลือ ขึ้นต้นด้วย "… " ไม่แสดงต้นย่อหน้าซ้ำ"""
    flat = re.sub(r"\s+", "", snippet)
    if flat in seen:
        return None
    if "\n" not in snippet and len(flat) > 40 and flat[:40] in seen:
        m = next((m for m in _EXAMPLE_START.finditer(snippet) if m.start() >= 40), None)
        if m:
            return "… " + snippet[m.start():].strip()
    return snippet


def _find_examples(terms, skip_topics, seen, own=(), titled=()):
    """own = หัวข้อที่กำลังคุยอยู่ (ตัวอย่างของหัวข้อนั้นมาก่อน), titled = หัวข้อที่ชื่อคือเรื่องที่ถามและแสดงไปแค่บางส่วน
    ตัวอย่างที่เหลือทุกอันของหัวข้อนั้นเป็นตัวอย่างของเรื่องที่ถาม ไม่ต้องมีศัพท์อยู่ในบรรทัด"""
    found = []
    for order, e in enumerate(ENTRIES):
        if e["topic"] in skip_topics:
            continue
        mine = e["topic"] in own
        for snippet in _example_snippets(e, None if e["topic"] in titled else terms):
            snippet = _unseen_part(snippet, seen)
            if snippet:
                # ของหัวข้อที่คุยอยู่ก่อน, คำสั่ง SQL จริงก่อน, บทนำ/บทสรุป/แบบฝึกหัดไว้ท้าย, นอกนั้นตามลำดับในเล่ม
                rank = (0 if mine else 1, 0 if "```" in snippet else 1, 1 if _is_meta(e["topic"]) else 0, order)
                found.append((rank, e, snippet))
    found.sort(key=lambda f: f[0])
    return [(e, snippet) for _, e, snippet in found]


def _examples(current, shown_text, focus_terms=(), partial=False):
    """(ตัวอย่างที่ยังไม่ได้แสดง, ชื่อเรื่อง) ของเรื่องที่คุยอยู่
    focus_terms = ศัพท์ที่ถามเมื่อคำตอบล่าสุดแสดงแค่บางส่วนของหัวข้อ ("ทูเพิล" ในหัวข้อ 4.4, "COUNT" ในหัวข้อ 9.10)
    หาตัวอย่างของศัพท์นั้นก่อน รวมส่วนที่ยังไม่ได้แสดงของหัวข้อเดิมด้วย"""
    seen = re.sub(r"\s+", "", shown_text)
    found, name = [], _topic_name(current)
    own = {e["topic"] for e in current}
    focus_terms = [t for t in focus_terms if 2 <= len(t) <= 30]
    keys = [_term_key(t) for t in focus_terms]
    titled = {e["topic"] for e in current if partial and any(len(k) >= 4 and k in _term_key(e["topic"]) for k in keys)}
    if focus_terms:
        found = _find_examples(focus_terms, set(), seen, own, titled)
        name = " / ".join(focus_terms) if found else name
    terms = [t for e in current for t in key_terms(e)]
    if not found and terms:
        found = _find_examples(terms, own - titled, seen, own, titled)
    return found, name, terms


def more_examples(current, shown_text, focus_terms=(), partial=False):
    """ตัวอย่างเรื่องที่คุยอยู่ ครั้งละ 3 ตัวอย่าง ข้ามที่เคยแสดงแล้ว (partial = คำตอบล่าสุดแสดงหัวข้อแค่บางส่วน
    ตัวอย่างที่เหลือในหัวข้อนั้นมาก่อน แล้วจึงเป็นตัวอย่างจากหัวข้ออื่นในตำรา)"""
    found, name, terms = _examples(current, shown_text, focus_terms, partial)
    if not found and not terms:
        return f"เรื่อง **{name}** ในตำรามีตัวอย่างเท่าที่แสดงไปแล้วด้านบนครับ\n\n" + related_topics(current, shown_text, lead=False)
    if not found:
        return (f"ตัวอย่างเรื่อง **{name}** ในตำรามีเท่าที่แสดงไปแล้วครับ\n\n"
                + related_topics(current, shown_text, lead=False))
    where = "ในตำรา" if any(e in current for e, _ in found) else "จากหัวข้ออื่นในตำรา"
    blocks = [f"ตัวอย่างเพิ่มเติมเรื่อง **{name}** {where}"]
    for e, snippet in found[:EXAMPLES_PER_ANSWER]:
        blocks.append("### จาก " + e["topic"] + "\n\n" + with_figures(snippet) + "\n\n" + _source_line(e))
    rest = len(found) - EXAMPLES_PER_ANSWER
    if rest > 0:
        blocks.append(f'ยังมีอีก {rest} ตัวอย่าง พิมพ์ "ขอตัวอย่างเพิ่ม" เพื่อดูต่อ')
    return "\n\n---\n\n".join(blocks)


def related_topics(current, shown_text, lead=True):
    """หัวข้อในตำราที่เกี่ยวกับเรื่องที่คุยอยู่ แสดงเป็นปุ่มให้แตะถามต่อ (ไม่เดาเนื้อหาเอง)"""
    shown = set(_answer_topics(shown_text)) | {e["topic"] for e in current}
    terms = [t.lower() for e in current for t in key_terms(e)]
    chapters = {_chapter_of(e["topic"]) for e in current}
    picks = []

    def add(e):
        if e["topic"] not in shown and all(p is not e for p in picks):
            picks.append(e)

    for e in current:   # 1) ส่วนอื่นของหัวข้อเดียวกันที่ยังไม่ได้แสดง
        base = e["topic"].split(" · ")[0]
        for x in ENTRIES:
            if x["topic"].split(" · ")[0] == base:
                add(x)
    for x in ENTRIES:   # 2) หัวข้ออื่นที่ชื่อมีคำหลัก
        if terms and any(t in x["topic"].lower() for t in terms) and not _is_meta(x["topic"]):
            add(x)
    ranked = []         # 3) หัวข้อในบทเดียวกันที่เนื้อหาพูดถึงคำหลักบ่อย
    for x in ENTRIES:
        if _chapter_of(x["topic"]) in chapters and not _is_meta(x["topic"]):
            hits = sum(x["description"].lower().count(t) for t in terms)
            if hits:
                ranked.append((hits, x))
    for _, x in sorted(ranked, key=lambda p: -p[0]):
        add(x)
    for x in ENTRIES:   # 4) บทสรุปของบท
        if _chapter_of(x["topic"]) in chapters and x["topic"].startswith("บทสรุป"):
            add(x)
    name = _topic_name(current)
    if not picks:
        return f"ในตำราไม่มีหัวข้ออื่นที่เกี่ยวกับ **{name}** เพิ่มเติมครับ"
    head = f"หัวข้อในตำราที่เกี่ยวกับ **{name}** (แตะเพื่อดูเนื้อหา)" if lead else "หัวข้อที่เกี่ยวข้องในตำรา (แตะเพื่อดูเนื้อหา)"
    return head + "\n\n" + "\n".join(f"[[ถาม:{x['topic']}]]" for x in picks[:6])


def render_topics(entries):
    return render_plan([(e, None) for e in entries])


# ---------------------------------------------------------------- ตอบเฉพาะส่วนที่ถาม
# หัวข้อยาวมักอธิบายหลายเรื่อง เช่น 1.1 มีทั้งความหมายของข้อมูลและของสารสนเทศ ถาม "สารสนเทศคืออะไร"
# จึงควรได้เฉพาะย่อหน้าที่อธิบายสารสนเทศ (พร้อมตัวอย่าง/รูป/ตารางที่ประกอบ) ไม่ใช่ทั้งหัวข้อ
# ย่อหน้าที่แสดงยังเป็นข้อความจากตำราตรงตัวทุกตัวอักษร เพียงแต่ไม่แสดงย่อหน้าที่ไม่เกี่ยว
FOCUS_MIN_CHARS = 1500   # หัวข้อสั้นกว่านี้แสดงทั้งหัวข้อ ตัดแล้วไม่ได้อ่านง่ายขึ้น
BLOCK_CHARS = 1200       # นิยามยาวถึงนี้แล้ว หยุดที่ย่อหน้าถัดไป (ตาราง/รูปที่กำลังแสดงอยู่ยังแสดงจนครบ)
PARTIAL_MARK = "แสดงเฉพาะส่วนที่ตอบคำถาม"      # ใช้ตรวจว่าคำตอบเป็นแบบบางส่วน (แชทเก่าที่เก็บไว้ในเบราว์เซอร์ใช้ข้อความท้ายต่างจากปัจจุบัน)
PARTIAL_NOTE = PARTIAL_MARK + " แตะปุ่มด้านล่างเพื่ออ่านต่อ"


def units(entry):
    """ย่อหน้าของหัวข้อ: บล็อกโค้ดทั้งก้อน หรือทีละบรรทัด (ไฟล์ความรู้เก็บหนึ่งย่อหน้าต่อบรรทัด)"""
    return [text for _, text in _blocks(entry["description"])]


# ศัพท์เดียวกันสะกดได้หลายแบบ (ในตำราเองก็สะกดไม่เหมือนกันทุกที่) แปลงเป็นแบบเดียวก่อนเทียบ
_SPELLINGS = [
    (r"เอ็?น[ทต]ิตี้?", "เอ็นทิตี้"),
    (r"แอ[ตทด]{0,2}ร?ิบิว[ตท]?์?", "แอตทริบิวต์"),
    (r"เร็?[คก]{1,2}อร์ด", "เรคอร์ด"),
    (r"ทู(?:เพิ้?ล|พิล|เปิล)", "ทูเพิล"),
    (r"คาร์ดิน[ัา]ล?ลิ[ตท][ีิ]้?", "คาร์ดินัลลิตี้"),
    (r"ซ[ุู][ปบ]?เปอร์คีย์", "ซุปเปอร์คีย์"),
    (r"ส[กค]ีมา", "สกีมา"),
    (r"ฟ[ิี][ลว]ด์", "ฟิลด์"),
    (r"ไบ[ตท]์", "ไบต์"),
    (r"นอร์?ม[ัอ]ลไลเซชั่?น", "นอมอลไลเซชัน"),
    (r"นอร์?ม[ัอ]ลฟอร์ม?", "นอมอลฟอร์ม"),
    (r"^ภาษา(?=\s*[a-z])", ""),                     # "ภาษา SQL" = "SQL"
]


def _term_key(text):
    """รูปมาตรฐานของศัพท์ ใช้เทียบศัพท์ในคำถามกับศัพท์ที่ตำรานิยาม"""
    text = text.lower().strip()
    for pattern, repl in _SPELLINGS:
        text = re.sub(pattern, repl, text)
    return re.sub(r"[\s\-_:;,.'\"“”()]+", "", text)


_NUM_MARK = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})*)(?:\s*([.)])|\s)\s*")
_CAPTION = re.compile(r"^(ภาพที่|ตารางที่)\s*\d")
_EXPLAIN = re.compile(r"^จาก\s*(ภาพ|ตาราง)")
_NOT_TERM = re.compile(r"^(จาก|หมายเหตุ|ข้อใด|ตัวอย่าง|รูปแบบ|โครงสร้างคำสั่ง|โครงสร้างการ|ตาราง|ที่มา|ภาพที่|ขั้น|วิธี|"
                       r"สรุป|ประเภทคำสั่ง|[a-z_0-9(),.\s]+$)")
_INTRO_END = re.compile(r"(ต่อไปนี้|ดังนี้|ได้แก่|ดังรายละเอียด\S*|ประกอบด้วย|มีดังนี้|:)\s*$")


def _defined_terms(line):
    """ศัพท์ที่บรรทัดนี้นิยามไว้ คืน (ชื่อศัพท์ทุกแบบ, นิยามเต็ม?)
    - "ทูเพิล หมายถึง …" / "2) ฟิลด์ (Field) หมายถึง …" / "ภาษา SQL (Structured Query Language) เป็น…" -> นิยามเต็ม
    - "ดีกรี (Degree)" / "1. ภาษาสำหรับนิยามข้อมูล (Data Definition Language: DDL)" -> หัวเรื่องของศัพท์ เนื้อหาอยู่บรรทัดถัดไป"""
    text = _NUM_MARK.sub("", line).strip()
    m = re.match(r"(?P<th>[^()|:“”\"]{1,45}?)\s*(?:หรือ\s*)?\((?P<en>[A-Za-z][^()]{0,60})\)\s*(?P<rest>.*)$", text)
    if m and re.search(r"\d{4}|et al|&", m.group("en")):
        m = None                            # วงเล็บเป็นการอ้างอิง "(Petersen, 2018)" ไม่ใช่ชื่อศัพท์
    if m:
        th, en, rest = m.group("th").strip(), m.group("en"), m.group("rest")
        # "5) บิต (Bit) บิต เป็น…" / "…(DML) ภาษาสำหรับจัดการฐานข้อมูล เป็น…" ทวนชื่อศัพท์ก่อนนิยาม
        full = bool(re.match(r"(?:" + re.escape(th) + r"\s*)?(หมายถึง|คือ|เป็น|จะ|มี|ถือ)", rest))
        if rest and not full:
            return [], False
    else:
        m = re.match(r"(?P<th>[^()|:“”\"]{1,30}?)\s*(หมายถึง|คือ)\s", text)
        if not m:
            return [], False
        th, en, full = m.group("th").strip(), "", True
    if not th or _NOT_TERM.match(th) or len(th) > 40 or re.search(r"(?<!ความ)เป็น|คือ|หมายถึง", th):
        return [], False                    # "กระบวนการ 2NF เป็นการกำจัด (Partial Dependency)" เป็นประโยค ไม่ใช่ชื่อศัพท์
    names = [th] + [p.strip() for p in th.split("หรือ") if p.strip()]
    names += [p.strip() for p in re.split(r"[:,]| or ", en) if len(p.strip()) >= 2]
    if en:
        names.append(f"{th} ({en})")      # พิมพ์ทั้งชื่อไทยและอังกฤษตามหัวเรื่องในเล่ม
    return list(dict.fromkeys(n for n in names if n)), full


_DEFINITIONS = {"key": None, "index": {}}


def definitions():
    """ดัชนีศัพท์ที่ตำรานิยามไว้ในเนื้อหา: รูปมาตรฐานของศัพท์ -> [(หัวข้อ, เลขย่อหน้า, นิยามเต็ม?)]
    (หัวข้อตามสารบัญมีแค่ 172 ชื่อ แต่ศัพท์อย่างทูเพิล ดีกรี ฟิลด์ DDL นิยามไว้ในเนื้อหาของหัวข้ออื่น)"""
    if _DEFINITIONS["key"] is not ENTRIES:
        index = {}
        for e in ENTRIES:
            own = _own_title(e)
            for k, u in enumerate(units(e)):
                names, full = _defined_terms(u)
                if not names and k < 3 and own and re.match(re.escape(own) + r"\s*(หมายถึง|คือ|เป็น)", u):
                    names, full = [own], True       # "เหมืองข้อมูล เป็น…" ต้นหัวข้อ "11.4 เหมืองข้อมูล"
                for name in names:
                    key = _term_key(name)
                    if len(key) >= 2:
                        index.setdefault(key, []).append((e, k, full))
        # ชื่ออังกฤษในชื่อหัวข้อ "11.6 ปัญญาประดิษฐ์ (Artificial Intelligence: AI)" ใช้ถามแทนชื่อไทยได้
        for e in ENTRIES:
            thai = index.get(_term_key(_own_title(e)), [])
            for name in _title_names(e)[1:] if thai else []:
                key = _term_key(name)
                index[key] = index.get(key, []) + [h for h in thai if h not in index.get(key, [])]
        _DEFINITIONS.update(key=ENTRIES, index=index)
    return _DEFINITIONS["index"]


def _definition_span(entry, start):
    """ช่วงย่อหน้าที่อธิบายศัพท์ซึ่งนิยามไว้ที่ย่อหน้า start: ตัวนิยาม + ตัวอย่าง รูป ตาราง โค้ด และรายการย่อยที่ตามมา
    หยุดเมื่อถึงศัพท์ถัดไป หัวเรื่องถัดไป หรือรูปใหม่ที่ไม่เกี่ยวกับศัพท์นี้ (คำตอบใช้เฉพาะส่วนต้น ดู definition_block)"""
    us = units(entry)
    names, full = _defined_terms(us[start])
    if full and start > 0:
        prev_names, prev_full = _defined_terms(us[start - 1])
        if prev_names and not prev_full and {_term_key(n) for n in prev_names} & {_term_key(n) for n in names}:
            start -= 1          # หัวเรื่องของศัพท์ "ดีกรี (Degree)" อยู่บรรทัดก่อนนิยาม
            names, full = prev_names, False
    keys = {_term_key(n) for n in names}
    mark = _NUM_MARK.match(us[start])
    style = mark.group(2) if mark else None
    picked, size = [start], len(us[start])
    body_seen = full            # หัวเรื่องเฉย ๆ ต้องได้ย่อหน้าเนื้อหาอย่างน้อยหนึ่งย่อหน้า
    intro = bool(_INTRO_END.search(us[start]))
    example = in_list = explained = False
    for k in range(start + 1, len(us)):
        u = us[k].strip()
        if not u:
            continue
        num = _NUM_MARK.match(u)
        other_names, _ = _defined_terms(u)
        other = other_names and not ({_term_key(n) for n in other_names} & keys)
        enough = size >= BLOCK_CHARS
        if u.startswith("```") or " | " in u or re.match(r"^ที่มา\s*:?", u):
            pass                            # ตาราง โค้ด และที่มาของรูป ไปกับย่อหน้าก่อนหน้าเสมอ
        elif _CAPTION.match(u):
            if explained or (enough and not example):
                break                       # รูปใหม่หลังคำอธิบายรูปก่อนหน้า = เรื่องถัดไป
            in_list = False
        elif _EXPLAIN.match(u):
            explained, example, in_list = True, False, False
        elif num and style and num.group(2) == style and "." not in num.group(1):
            break                           # ข้อถัดไประดับเดียวกัน เช่น "2) ฟิลด์" ต่อจาก "1) แฟ้มข้อมูล"
        elif other and not (num and (intro or in_list) and not re.search(r"\([A-Za-z]", u)):
            break                           # ศัพท์อื่น (ยกเว้นข้อย่อยของรายการที่ศัพท์นี้เกริ่นไว้)
        elif num:
            if not (intro or in_list or not body_seen) or (enough and not in_list):
                break
            in_list = True
        elif re.match(r"ตัวอย่าง(ที่\s*\d|การ)", u) or (enough and not in_list):
            break                           # โจทย์ตัวอย่าง/การประยุกต์ใช้ เป็นเนื้อหาต่อยอด ไม่ใช่ความหมาย
        elif u.startswith("ตัวอย่าง"):
            example = True
        elif not body_seen:
            body_seen = True
        elif re.match(r"(กระบวนการ|ขั้นตอน|ประโยชน์|ข้อดี|ข้อเสีย|วิธี|การประยุกต์)", u) and _INTRO_END.search(u):
            break                           # เกริ่นรายการเรื่องใหม่ (ขั้นตอน/ประโยชน์) ไม่ใช่ความหมาย
        elif example or (in_list and len(u) <= 200):
            pass                            # ข้อมูลตัวอย่าง / คำอธิบายของข้อย่อย
        elif len(u) <= 40 or not any(key in _term_key(u) for key in keys):
            break                           # หัวเรื่องของเรื่องถัดไป หรือย่อหน้าที่ไม่ได้พูดถึงศัพท์นี้แล้ว
        else:
            in_list = False
        picked.append(k)
        size += len(u)
        intro = bool(_INTRO_END.search(u))
    return picked


def definition_block(entry, start, extras=True):
    """เฉพาะตัวนิยามของศัพท์ที่นิยามไว้ที่ย่อหน้า start: หัวเรื่องศัพท์ (ถ้ามี) + ย่อหน้านิยาม
    + รายการข้อย่อยที่นิยามเกริ่นไว้ ("ได้แก่/ดังนี้" เช่น ลักษณะของ Big Data 3 ข้อ) + โค้ดไวยากรณ์ที่ตามติดมา
    ตัวอย่าง รูป และตารางที่ตามมาไม่รวม ผู้ใช้กดปุ่มต่อได้ (ถามแค่ความหมายต้องไม่ได้ของเกินจากที่ถาม)"""
    us = units(entry)
    span = _definition_span(entry, start)
    core = [k for k in span if k <= start] or [start]
    names, full = _defined_terms(us[start])
    if names and not full:                     # หัวเรื่องศัพท์เฉย ๆ ("1. ภาษาสำหรับนิยามข้อมูล (DDL)") ต้องมีย่อหน้าเนื้อหาตามมา
        body = next((k for k in span if k > start and us[k].strip()), None)
        if body is not None:
            core.append(body)
    if not extras:                             # คำตอบเปรียบเทียบ: ย่อหน้านิยามอย่างเดียวพอ
        return sorted(set(core))
    if _INTRO_END.search(us[max(core)].strip()):
        for k in (k for k in span if k > max(core)):
            u = us[k].strip()
            if not u:
                continue
            if _CAPTION.match(u) or _EXPLAIN.match(u) or u.startswith(("ตัวอย่าง", "ที่มา", "```")) or " | " in u:
                break
            if not _NUM_MARK.match(u) and len(u) > 300:
                break                          # ย่อหน้าเนื้อหาใหม่ ไม่ใช่ข้อย่อยของรายการ
            core.append(k)
    elif max(core) + 1 < len(us) and us[max(core) + 1].startswith("```") and max(core) + 1 in span:
        core.append(max(core) + 1)
    return sorted(set(core))


_GLUED = {"key": None, "pairs": []}
_EN_PHRASE = re.compile(r"\b[A-Za-z]{2,}(?: [A-Za-z]{2,})+\b")
_COMMON_PHRASES = ("inner join", "left join", "right join", "full join", "full outer join", "cross join", "group by",
                   "order by", "primary key", "foreign key", "candidate key", "composite key", "alternate key", "super key")


def _split_glued(text):
    """แยกวลีอังกฤษที่พิมพ์ติดกัน: "innerjoin กับ leftjoin" -> "inner join กับ left join" (วลีมาจากชื่อหัวข้อในเล่ม)"""
    if _GLUED["key"] is not ENTRIES:
        phrases = set(_COMMON_PHRASES)
        for e in ENTRIES:
            phrases.update(p.lower() for p in _EN_PHRASE.findall(e["topic"]))
        pairs = sorted(((p.replace(" ", ""), p) for p in phrases if len(p.replace(" ", "")) >= 6), key=lambda x: -len(x[0]))
        _GLUED.update(key=ENTRIES, pairs=pairs)
    for glued, phrase in _GLUED["pairs"]:
        text = re.sub(r"(?<![A-Za-z])" + re.escape(glued) + r"(?![A-Za-z])", phrase, text, flags=re.I)
    return text


def _asked_terms(query):
    """ศัพท์ที่ถาม: ตัดคำถาม/คำสุภาพทิ้ง ("สารสนเทศคืออะไรครับ" -> ["สารสนเทศ"], "COUNT ใช้ยังไง" -> ["COUNT"])
    ถามเทียบ ("ข้อมูลกับสารสนเทศต่างกันยังไง") ได้ศัพท์ทั้งสองฝั่ง"""
    text = re.sub(r"\s*(มีอะไรบ้าง|มีอะไร|ประกอบด้วยอะไรบ้าง|ประกอบด้วยอะไร|"
                  r"ใช้ยังไง|ใช้อย่างไร|ใช้ทำอะไร|ใช้งานยังไง|ใช้งานอย่างไร"
                  r"|มีลักษณะ(?:เป็นอย่างไร|อย่างไร|ยังไง|อะไรบ้าง)?)", " ", _split_glued(query))   # "big data มีลักษณะยังไง" = ถามนิยามของ big data
    text = re.sub(r"^\s*(วิธีใช้งาน|วิธีใช้|การใช้งาน)\s*", " ", text)
    text = re.sub(r"^\s*(?:ความหมายของ|ความหมาย)\s*", " ", text)   # "ความหมายของข้อมูล" เฉพาะที่ต้นประโยค
    text = re.sub(r"คืออะไร|หมายถึงอะไร|แปลว่าอะไร|อะไรคือ|หมายถึง|แปลว่า|คือ|"
                  r"ช่วยอธิบาย|อธิบาย|ช่วยบอก|บอกหน่อย|อยากรู้ว่า|อยากรู้|อยากทราบ|สงสัยว่า|"
                  r"what\s+is|what\s+are|what's|define|definition\s+of|meaning\s+of|"
                  r"ความแตกต่างระหว่าง|ความแตกต่าง|แตกต่างกัน|ต่างกัน|ต่างจาก|เปรียบเทียบ|เทียบ|ยังไง|อย่างไร|"
                  r"[?？!]", " ", text, flags=re.I)
    # คำสุภาพตัดเฉพาะที่ท้ายคำ ไม่ตัดกลางคำ ("เจ้าของ" มี "จ้า", "คะแนน" มี "คะ")
    text = re.sub(r"(?:ครับ|คับ|ค่ะ|คะ|นะ|จ้า|หน่อย)+(?=\s|$)", " ", text)
    parts = re.split(r"\s+กับ\s*|กับ|\s+และ\s+|\s+vs\.?\s+|\s*/\s*|,", text) if _COMPARE_RE.search(query) else [text]
    return [p.strip() for p in parts if _term_key(p)]


_DEFINE_RE = re.compile(r"คือ|หมายถึง|แปลว่า|(?<![฀-๿])ความหมาย|what\s+is|what's|define|meaning|ต่างกัน|แตกต่าง|ต่างจาก|เทียบ", re.I)


def find_definition(term, prefer=()):
    """ย่อหน้าที่ตำรานิยามศัพท์นี้ไว้ดีที่สุด คืน (หัวข้อ, เลขย่อหน้า, นิยามเต็ม?) หรือ None
    ลำดับ: นิยามเต็มก่อนหัวเรื่องเฉย ๆ, หัวข้อที่ชื่อมีศัพท์นี้หรือค้นเจอจากชื่อหัวข้อก่อน, บทสรุป/แบบฝึกหัดทีหลัง,
    นอกนั้นเอาที่นิยามไว้ก่อนในเล่ม ถ้าไม่มีนิยามเต็มของศัพท์นี้ ใช้นิยามเต็มในหัวข้อที่ค้นเจอซึ่งชื่อศัพท์มีคำที่ถาม
    (ถาม "ฐานข้อมูล" ได้นิยาม "ระบบฐานข้อมูล" ในหัวข้อ 2.2 แทนป้ายในรูป "ฐานข้อมูล (DBMS)")"""
    key = _term_key(term)
    # เทียบด้วยชื่อหัวข้อ ไม่ใช่ตัวอ็อบเจกต์ (ENTRIES โหลดใหม่ทุกคำถาม คำถามที่มาพร้อมกันอาจถือคนละชุด)
    order = {e["topic"]: n for n, e in enumerate(ENTRIES)}
    preferred = {e["topic"] for e in prefer}
    hits = definitions().get(key, [])
    if not any(full and not _is_meta(e["topic"]) for e, _, full in hits):
        near = [(e, k, full) for other, found in definitions().items() if key in other
                for e, k, full in found if full and e["topic"] in preferred and not _is_meta(e["topic"])]
        hits = near or hits
    if not hits:
        return None
    return min(hits, key=lambda h: (_is_meta(h[0]["topic"]), not h[2],
                                    key not in _term_key(h[0]["topic"]) and h[0]["topic"] not in preferred,
                                    order.get(h[0]["topic"], 0), h[1]))


def _heading(entry):
    """ชื่อหัวข้อตามที่พิมพ์ในเล่มโดยไม่มีเลขหัวข้อ: "4.5 ประเภทของคีย์ · 3. คีย์หลัก (Primary Key)" -> "คีย์หลัก (Primary Key)" """
    return re.sub(r"^(ภาคผนวก [กข] )?(\d+\.)+\d*\s*", "", entry["topic"].split(" · ")[-1]).strip()


def _own_title(entry):
    """ชื่อหัวข้อไม่เอาเลขหัวข้อ ชื่อหัวข้อหลัก และคำอธิบายในวงเล็บ: "4.5 ประเภทของคีย์ · 3. คีย์หลัก (Primary Key)" -> "คีย์หลัก" """
    return re.sub(r"\s*\(.*$", "", _heading(entry)).strip()


def _title_names(entry):
    """ชื่อไทยของหัวข้อ + ชื่ออังกฤษในวงเล็บท้ายชื่อ: "11.6 ปัญญาประดิษฐ์ (Artificial Intelligence: AI)"
    -> ["ปัญญาประดิษฐ์", "Artificial Intelligence", "AI"]"""
    en = re.search(r"\(([A-Za-z][^()]*)\)\s*$", entry["topic"].split(" · ")[-1])
    names = [_own_title(entry)] + (re.split(r"[:,]", en.group(1)) if en else [])
    return [n.strip() for n in names if len(_term_key(n)) >= 2]


def asks_meaning(query):
    """ถามความหมาย/ความต่าง ("X คืออะไร", "X กับ Y ต่างกันยังไง") หรือพิมพ์แค่ชื่อศัพท์ที่ตำรานิยามไว้ ("ทูเพิล")"""
    terms = _asked_terms(query)
    return bool(_DEFINE_RE.search(query)) or (len(terms) == 1 and _term_key(terms[0]) in definitions())


def definition_blocks(query, entry):
    """ย่อหน้าที่หัวข้อนี้นิยามศัพท์ที่ถาม (เฉพาะคำถามความหมาย) หรือ [] ถ้าหัวข้อนี้ไม่ได้นิยามศัพท์นั้น"""
    if not asks_meaning(query):
        return []
    picked = set()
    for term in _asked_terms(query):
        hits = [h for h in definitions().get(_term_key(term), []) if h[0]["topic"] == entry["topic"]]
        if hits:
            e, k, _ = min(hits, key=lambda h: (not h[2], h[1]))
            picked |= set(definition_block(e, k))
    return sorted(picked)


def names_topic(query):
    """ถามด้วยชื่อหัวข้อเต็ม เลขหัวข้อ (7.5) หรือบท (แบบฝึกหัดบทที่ 7) = ต้องการทั้งหัวข้อนั้น ไม่ต้องตีความ"""
    text = query.lower().strip()
    return (any(e["topic"].lower() == text for e in ENTRIES)
            or bool(re.search(r"(?<![\d.])\d{1,2}\.\d{1,2}(?![\d.])|บทที่|ภาคผนวก", _CAP_REF.sub(" ", text))))


def plan_answer(query):
    """เลือกหัวข้อและย่อหน้าที่ตอบคำถาม โดยไม่ใช้ AI: [(หัวข้อ, เลขย่อหน้า หรือ None = ทั้งหัวข้อ)]
    ถามความหมายของศัพท์ -> เฉพาะย่อหน้าที่นิยามศัพท์นั้น (ถ้าหัวข้อยาว), ถามชื่อหัวข้อ/เลขหัวข้อ/อย่างอื่น -> ทั้งหัวข้อ"""
    return _plan(query)[0]


def _plan(query):
    """(แผนคำตอบ, มั่นใจไหม) — มั่นใจเมื่อถามด้วยชื่อ/เลขหัวข้อ, ศัพท์ที่ตำรานิยามไว้ หรือหัวเรื่องย่อยตรงตัว
    ไม่มั่นใจ = ได้หัวข้อจากคำที่ตรงกับชื่อหัวข้อเท่านั้น ซึ่งพลาดได้กับคำถามที่คนพิมพ์เอง"""
    direct = _direct_plan(query)
    if direct is not None:
        return direct, True
    data_types = _data_type_topics(query)
    if data_types:
        return [(e, None) for e in data_types], True
    entries = search(query, limit=3)
    terms = _asked_terms(query)
    whole = [(e, None) for e in entries]
    special = _special_topics(query)
    # คำถามนิยาม “ฐานข้อมูล” ใช้ประโยคเปิดที่ให้ความหมายตรงจากหัวข้อ 2.2
    # แทนย่อหน้าสรุปที่กล่าวถึงฐานข้อมูลภายหลัง
    if special and len(special) == 1 and special[0]["topic"].startswith("2.2 ") \
            and asks_meaning(query):
        return [(special[0], [0])], True
    # เปรียบเทียบ Entity กับ Attribute: ใช้นิยามตรงของแต่ละศัพท์ ไม่ใช้ย่อหน้าตัวอย่าง
    # ที่เอ่ยถึงทั้งสองคำแต่ไม่ได้อธิบายความแตกต่าง
    if re.search(r"เอ็นทิต|เอนทิต", query, re.I) and re.search(r"แอตทริบิวต์|attribute", query, re.I) \
            and len(terms) > 1 and _COMPARE_RE.search(query):
        expected = ("5.3 เอ็นทิตี้", "5.4 แอตทริบิวต์")
        cores = []
        for term, prefix in zip(terms, expected):
            entry = next((e for e in ENTRIES if e["topic"].startswith(prefix)), None)
            hit = find_definition(term, prefer=[entry]) if entry else None
            if hit and entry and hit[0] is entry:
                cores.append((entry, definition_block(entry, hit[1], extras=False)))
        if len(cores) == 2:
            return _merge_plan([_brief_core(core) for core in cores]), True
    if special and asks_meaning(query) and len(terms) == 1:
        # คำศัพท์บางคำมีคำอธิบายซ้ำอยู่ในบทการแปลง (เช่น Weak Entity);
        # เมื่อคำถามเรียกศัพท์โดยตรง ให้ใช้หัวข้อที่นิยามศัพท์นั้น ไม่ใช่หัวข้อที่อธิบายขั้นตอนแปลง
        e = special[0]
        return [(e, definition_blocks(query, e) or [])], True
    if names_topic(query) or not terms:
        return whole, bool(entries) and names_topic(query)
    if _special_topics(query) and not asks_meaning(query):
        return whole, True             # "SQL แบ่งเป็นกี่ประเภท" "JOIN" กำหนดหัวข้อไว้แล้ว
    if len(terms) > 1 and _COMPARE_RE.search(query):
        cores = [_side_core(t, entries) for t in terms]
        compared = _compare_plan([{_term_key(t)} for t in terms], cores, entries)
        if compared:
            return compared, True
        # เทียบไม่ได้ (หาตัวนิยามของแต่ละฝั่งไม่ครบ): ใจความเปิดของฝั่งที่เจอ/หัวข้อที่ค้นเจอ ไม่ยกทั้งหัวข้อมาต่อกัน
        found = [c for c in cores if c]
        mains = {c[0]["topic"].split(" · ")[0] for c in found}
        rest = [e for e in entries if all(e["topic"] != c[0]["topic"] for c in found)]
        whole = _merge_plan([_brief_core(c) for c in found]
                            + [_brief_core(_entry_core(e)) for e in rest if e["topic"] not in mains])
        whole += [(e, LINK) for e in rest if e["topic"] in mains]      # หัวข้อหลักของส่วนที่แสดง: ปุ่มไปอ่านทั้งหัวข้อ
        if found or len(entries) >= len(terms):
            return whole, True         # เจอบางฝั่ง หรือค้นเจอครบทุกฝั่งจากชื่อหัวข้อ (AI เคยเลือกกว้างกว่านี้: ทั้งหัวข้อ 5.3)
    plan, all_found = _meaning_plan(terms, entries) if asks_meaning(query) else ([], False)
    if plan and all_found:
        return plan, True
    if _heading_matches(query):        # พิมพ์ชื่อหัวข้อในเล่ม (ไม่มีเลข) -> ทั้งหัวข้อ
        return whole, True
    sub = _subheading_plan(terms[0], entries) if len(terms) == 1 else []
    if sub:
        return sub, True
    # คำถามมีชื่อหัวข้อสั้นที่ค้นเจอเป็นอันดับแรกอยู่ทั้งชื่อ ("ทำไมต้องมีคีย์หลัก" -> "คีย์หลัก (Primary Key)")
    # แสดงทั้งหัวข้อได้โดยไม่เกินคำถาม ไม่ต้องให้ AI ตีความ (AI เคยเลือก "ซุปเปอร์คีย์" แทน)
    if len(entries) == 1 and len(entries[0]["description"]) < FOCUS_MIN_CHARS \
            and len(_own_title(entries[0])) >= 4 and _term_key(_own_title(entries[0])) in _term_key(query):
        return whole, True
    if len(terms) > 1 and _COMPARE_RE.search(query):   # เทียบไม่ได้ครบทุกฝั่ง: ยังแสดงแค่ใจความเปิดของส่วนที่เจอ
        plan = [_brief_core(item) if item[1] else item for item in plan]
    # ถามประเภท วิธีใช้ ("GROUP BY ใช้ยังไง") หรือคำที่ตรงกับชื่อหัวข้อบางส่วน -> ทั้งหัวข้อ
    return plan or whole, False


_SUMMARY_RE = re.compile(r"^(?:จาก(?:รายละเอียด|ข้อมูล|ที่)\S{0,30}(?:กล่าวมา|ข้างต้น|ดังกล่าว)|กล่าวโดยสรุป|โดยสรุป)")
_SUBNUM = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{1,2}\s")   # หัวเรื่องระดับที่สามในเล่ม "9.10.3 ฟังก์ชัน COUNT()…"
_CATEGORY = r"(ข้อดี|ข้อเสีย|ข้อจำกัด|ประเภท|ชนิด|คุณสมบัติ|ความหมาย|ตัวอย่าง|ลักษณะ|ประโยชน์|วิธี|ขั้นตอน|สรุป)"


def _is_subheading(us, k):
    """หัวเรื่องย่อยในเนื้อหา: "9.10.3 ฟังก์ชัน COUNT() การนับจำนวน" หรือบรรทัดสั้นที่ตามด้วยย่อหน้าเนื้อหา
    เช่น "ข้อดีของแบบจำลองฐานข้อมูลเชิงสัมพันธ์" (ป้ายในรูปมักเป็นบรรทัดสั้นติดกันหลายบรรทัด จึงไม่นับ)"""
    u = us[k].strip()
    if _SUBNUM.match(u):
        return True
    # "ตัวอย่างข้อมูล" "ตัวอย่างสารสนเทศ" เป็นหัวเรื่องแม้บรรทัดถัดไปจะสั้น (ข้อมูลตัวอย่างในเล่มเป็นบรรทัดสั้น ๆ)
    if re.match(r"ตัวอย่าง(?!ที่\s*\d)", u) and 6 <= len(u) <= 60 and " | " not in u \
            and not u.startswith("```") and not _INTRO_END.search(u):
        return True
    if (not 4 <= len(u) <= 70 or " | " in u or u.startswith("```") or _CAPTION.match(u) or _EXPLAIN.match(u)
            or u.startswith("ที่มา") or _INTRO_END.search(u) or _NUM_MARK.match(u)
            or u.count(",") >= 2 or not re.match(r"[^\dA-Za-z฀-๿]*[A-Za-z฀-๿]", u)):
        return False                           # แถวข้อมูล "cat, dog, rabbit" / "161.2, 175.3" ไม่ใช่หัวเรื่อง
    nxt = next((x.strip() for x in us[k + 1:] if x.strip()), "")
    return len(nxt) >= len(u) + 15 or bool(_NUM_MARK.match(nxt) or _INTRO_END.search(nxt))


def subheading_block(entry, k):
    """หัวเรื่องย่อยที่ย่อหน้า k จนถึงหัวเรื่องถัดไประดับเดียวกัน
    หัวเรื่องที่พูดถึงเรื่องเดียวกันและไม่ได้ขึ้นต้นด้วยข้อดี/ประเภท/ตัวอย่าง… เป็นหัวข้อย่อยของมัน
    ("ประเภทของแอตทริบิวต์" มี "คีย์แอตทริบิวต์ (Key Attribute)" เป็นหัวข้อย่อย แต่ "ข้อดีของ X" จบที่ "ข้อจำกัดของ X")"""
    us = units(entry)
    head = us[k].strip()
    subject = _term_key(re.sub(r"^" + _CATEGORY + r"(ของ|ที่)?", "", head))
    picked, explained = [k], False
    for j in range(k + 1, len(us)):
        u = us[j].strip()
        if _SUMMARY_RE.match(u):
            break                              # ย่อหน้าสรุปของทั้งหัวข้อ ("จากรายละเอียด…สรุปได้ว่า ข้อมูล หมายถึง…")
        if _SUBNUM.match(head):
            if _SUBNUM.match(u):
                break
        else:
            # ตัวอย่างหนึ่งชุดจบที่คำอธิบายรูปของมัน (รูปใหม่ถัดมาเป็นเรื่องอื่น) แต่รายการประเภท/ชนิด ("ประเภทของแอตทริบิวต์")
            # มีรูปคั่นทุกข้อ จึงต้องไปต่อจนถึงหัวเรื่องถัดไป
            if _CAPTION.match(u) and explained and head.startswith("ตัวอย่าง"):
                break
            if _EXPLAIN.match(u):
                explained = True
            if _is_subheading(us, j) and (re.match(_CATEGORY, u) or not subject or subject not in _term_key(u)):
                break
        picked.append(j)
    return picked


_SUBHEADINGS = {"key": None, "index": {}}


def subheadings():
    """ดัชนีหัวเรื่องย่อยในเนื้อหา: รูปมาตรฐานของหัวเรื่อง (ไม่เอาเลข 9.10.3) -> [(หัวข้อ, เลขย่อหน้า)]"""
    if _SUBHEADINGS["key"] is not ENTRIES:
        index = {}
        for e in ENTRIES:
            us = units(e)
            for k in range(len(us)):
                if _is_subheading(us, k):
                    key = _term_key(_SUBNUM.sub("", us[k].strip()))
                    if len(key) >= 6:
                        index.setdefault(key, []).append((e, k))
        _SUBHEADINGS.update(key=ENTRIES, index=index)
    return _SUBHEADINGS["index"]


def _subheading_plan(term, entries):
    """ถามหัวเรื่องย่อยในเนื้อหา ("ข้อดีของแบบจำลองฐานข้อมูลเชิงสัมพันธ์", "คุณสมบัติของรีเลชันที่สำคัญ")
    หรือศัพท์ที่เป็นหัวเรื่องระดับที่สามของหัวข้อที่ค้นเจอ ("COUNT ใช้ยังไง" -> "9.10.3 ฟังก์ชัน COUNT()")
    -> เฉพาะส่วนนั้นของหัวข้อยาว"""
    key = _term_key(term)
    hits = [(e, k) for e, k in subheadings().get(key, [])
            if len(e["description"]) >= FOCUS_MIN_CHARS and not _is_meta(e["topic"])]
    hits.sort(key=lambda h: all(h[0]["topic"] != e["topic"] for e in entries))   # หัวข้อที่ค้นเจอจากชื่อก่อน
    if not hits and entries and len(entries[0]["description"]) >= FOCUS_MIN_CHARS and len(key) >= 3:
        us = units(entries[0])
        found = [k for k, u in enumerate(us) if _SUBNUM.match(u.strip()) and key in _term_key(u)]
        if len(found) == 1:
            hits = [(entries[0], found[0])]
    if not hits:
        return []
    e, k = hits[0]
    block = subheading_block(e, k)
    if block[-1] == len(units(e)) - 1 and len(section_parts(e)) > 1:
        return [(e, None)]      # "ประเภทของเอ็นทิตี้" เป็นหัวเรื่องท้ายหัวข้อ เนื้อหาอยู่ในหัวข้อย่อยที่แบ่งไว้ทุกส่วน
    return [(e, block)]


EXTRA_MIN_CHARS = 250    # ส่วนที่เหลือนอกจากตัวนิยามสั้นกว่านี้ แสดงทั้งหัวข้อไปเลย (ตัดแล้วไม่ได้อ่านง่ายขึ้น)


def _only_definition(entry, core):
    """core ถ้าตัวอย่าง/รูป/ตารางที่ตามหลังยาวพอจะเป็นของเกิน ไม่งั้น [] = ทั้งหัวข้อ"""
    rest = sum(len(u) for k, u in enumerate(units(entry)) if k not in core)
    return core if rest >= EXTRA_MIN_CHARS else []


def _lead_block(entry):
    """ย่อหน้าเปิดของหัวข้อ (ประโยคที่บอกว่าหัวข้อนี้คืออะไร) + โค้ดไวยากรณ์ที่ตามติดมา ไม่รวมตัวอย่างหลังจากนั้น"""
    us = units(entry)
    k = next((i for i, u in enumerate(us) if len(u.strip()) >= 60 and " | " not in u and not u.startswith("```")), 0)
    return [k, k + 1] if k + 1 < len(us) and us[k + 1].startswith("```") else [k]


def _meaning_plan(terms, entries):
    """ถามความหมาย: ย่อหน้าที่ตำรานิยามแต่ละศัพท์ (หัวข้อยาว) หรือทั้งหัวข้อ (หัวข้อสั้น/หัวข้อที่ชื่อคือศัพท์นั้น)"""
    plan = []
    for term in terms:
        # หัวข้อที่ชื่อคือศัพท์นี้ ("5.3 เอ็นทิตี้") หรือเป็นหัวข้อความหมายของศัพท์นี้
        # ("5.1 ความหมายและความเป็นมา (บทที่ 5 … (ER Diagram))") เชื่อได้กว่าประโยคที่แค่หน้าตาเหมือนนิยาม
        # (เช่น "6.2.2 การแปลง (ER-Diagram) เป็นรีเลชัน…" ซึ่งพูดถึงการแปลง ไม่ใช่ความหมายของ ER Diagram)
        titled = next((e for e in entries if _term_key(term) in {_term_key(n) for n in _title_names(e)}
                       or ("ความหมาย" in e["topic"] and _term_key(term) in _term_key(e["topic"]))), None)
        found = find_definition(term, prefer=entries)
        if found and _is_meta(found[0]["topic"]) and any(not _is_meta(e["topic"]) for e in entries):
            found = None                    # นิยามในแบบฝึกหัด/บทสรุป ใช้เมื่อไม่มีหัวข้อเนื้อหาที่ตอบได้เท่านั้น
        if titled and (not found or found[0] is not titled):
            # หัวข้อชื่อตรงกับศัพท์ เช่น "5.3 เอ็นทิตี้": ตอบส่วนนำของหัวข้อ ไม่ต้องรวมหัวข้อย่อยทุกประเภท
            plan.append((titled, [] if len(titled["description"]) < FOCUS_MIN_CHARS else None))
        elif found:
            e, k, _ = found
            plan.append((e, _only_definition(e, definition_block(e, k))))
        else:
            # ตำราไม่มีประโยค "X หมายถึง" แต่ศัพท์เป็นชื่อหัวข้อ ("10.5 … วิธี INNER JOIN"): ย่อหน้าเปิดของหัวข้อนั้น
            e = next((x for x in entries if len(_term_key(term)) >= 4 and _term_key(term) in _term_key(x["topic"])
                      and not _is_meta(x["topic"])), None)
            if e is not None:
                plan.append((e, _only_definition(e, _lead_block(e))))
    # ศัพท์สองคำในหัวข้อเดียวกัน (ข้อมูล / สารสนเทศ ใน 1.1) รวมเป็นคำตอบเดียว
    merged = {}
    for e, picked in plan:
        t = e["topic"]
        if t in merged and merged[t][1] is not None and picked:
            merged[t] = (e, sorted(set(merged[t][1]) | set(picked)))
        else:
            merged.setdefault(t, (e, picked))
    return list(merged.values()), len(plan) == len(terms)


_CAP_RE = re.compile(r"^(ภาพที่|ตารางที่)\s*(\d{1,2}\.\d{1,2})(?!\d)\s*(.*)$")
# "ภาพที่ 1.1" "รูป 1.1" "ตารางที่ 4.3" ในคำถาม (เลขภาพ/ตารางเป็นเลขบท.ลำดับ ไม่ใช่เลขหัวข้อ ห้ามเอาไปค้นเป็นหัวข้อ)
_CAP_REF = re.compile(r"(ภาพที่|รูปที่|ตารางที่|ภาพ|รูป|ตาราง)\s*(\d{1,2}\.\d{1,2})(?![\d.])")
_CAPTIONS = {"key": None, "num": {}, "title": {}}


def captions():
    """ดัชนีคำบรรยายภาพ/ตาราง: ({(ชนิด, เลข): [(หัวข้อ, ย่อหน้า)]}, {รูปมาตรฐานของชื่อ: [(ชนิด, เลข, หัวข้อ, ย่อหน้า)]})"""
    if _CAPTIONS["key"] is not ENTRIES:
        by_num, by_title = {}, {}
        for e in ENTRIES:
            for k, u in enumerate(units(e)):
                m = _CAP_RE.match(u.strip())
                if m:
                    by_num.setdefault((m.group(1), m.group(2)), []).append((e, k))
                    key = _term_key(m.group(3))
                    if len(key) >= 6:
                        by_title.setdefault(key, []).append((m.group(1), m.group(2), e, k))
        _CAPTIONS.update(key=ENTRIES, num=by_num, title=by_title)
    return _CAPTIONS["num"], _CAPTIONS["title"]


def caption_block(entry, k):
    """ภาพ/ตารางที่คำบรรยายอยู่ย่อหน้า k: คำบรรยาย (รูปแทรกให้ตอน render) + ที่มา + ข้อมูลตาราง/โค้ด
    + ย่อหน้าอธิบายภาพ/ตารางนั้น ("จากภาพที่ 1.1 …") หยุดเมื่อถึงเรื่องอื่น"""
    us = units(entry)
    m = _CAP_RE.match(us[k].strip())
    kind, num = m.group(1), m.group(2)
    picked, small = [k], 0
    for j in range(k + 1, len(us)):
        u = us[j].strip()
        if not u:
            continue
        ref = re.match(r"^จาก\s*(?:ภาพ|ตาราง)(?:ที่)?\s*(\d{1,2}\.\d{1,2})", u)
        if re.match(r"^ที่มา\s*:?", u) or u.startswith("```") or " | " in u:
            pass
        elif ref and ref.group(1) == num:
            pass
        elif kind == "ตารางที่" and len(u) <= 30 and small < 14 and not _CAPTION.match(u) and not _EXPLAIN.match(u) \
                and not u.startswith("ตัวอย่าง") and not _NUM_MARK.match(u) and not _is_subheading(us, j):
            small += 1                         # ตารางที่มีช่องเดียวต่อแถว ("รหัส" "P6")
        else:
            break
        picked.append(j)
    return picked


def caption_plan(query):
    """ถามถึงภาพ/ตารางตามเลข ("ภาพที่ 1.1") หรือตามชื่อ ("ชุดข้อมูลที่ยังไม่มีความหมาย")
    None = ไม่ใช่คำถามเรื่องภาพ/ตาราง, [] = เลขนี้ไม่มีในตำรา, [(หัวข้อ, ย่อหน้า)] = คำบรรยาย + ส่วนที่เกี่ยวข้อง"""
    by_num, by_title = captions()
    m = _CAP_REF.search(query)
    if m:
        kind = "ตารางที่" if m.group(1).startswith("ตาราง") else "ภาพที่"
        hits = by_num.get((kind, m.group(2)), [])
        if not hits:
            return []
        e, k = next((h for h in hits if not _is_meta(h[0]["topic"])), hits[0])
        return [(e, caption_block(e, k))]
    text = question_key(query)
    for cand in (text, re.sub(r"^(?:ขอดู|ขอ|ดู|แสดง|อยากดู|เปิด)?\s*(?:ภาพ|รูป)\s*", "", text)):
        hits = by_title.get(_term_key(cand), [])
        if hits and len({(h[0], h[1]) for h in hits}) == 1:
            kind, num, e, k = next((h for h in hits if not _is_meta(h[2]["topic"])), hits[0])
            return [(e, caption_block(e, k))]
    return None


def _direct_plan(query):
    """ถามตรงถึงสิ่งที่มีชื่ออยู่ในเล่ม (ภาพ/ตาราง/หัวเรื่องย่อย) ไม่ต้องตีความ และไม่ถูกตีเป็นคำถามต่อจากเรื่องที่คุยอยู่
    (ปุ่ม "ตัวอย่างข้อมูล" ต้องได้ส่วนตัวอย่างข้อมูล ไม่ใช่ "ตัวอย่างเพิ่มเติมจากหัวข้ออื่น") None = ไม่ใช่"""
    cap = caption_plan(query)
    if cap is not None:
        return cap
    key = _term_key(_SUBNUM.sub("", question_key(query)))
    if len(key) >= 6 and len(subheadings().get(key, [])) == 1:
        return _subheading_plan(key, []) or None
    return None


# ---------------------------------------------------------------- ถามเปรียบเทียบ ("X กับ Y ต่างกันยังไง")
# บอทสรุปความต่างเองไม่ได้ (ห้ามแต่งคำ) จึงแสดง 1) ย่อหน้าที่ตำราเทียบเรื่องทั้งสองไว้เอง (ถ้ามี) 2) ตัวนิยามของแต่ละเรื่อง
# 3) ปุ่มอ่านหัวข้อเต็ม ไม่ใช่ยกทั้งสองหัวข้อมาต่อกัน
# แสดงแค่ใจความเปิดของแต่ละเรื่อง: ตัดก่อนตัวอย่าง ("เช่น …") และรายละเอียดต่อท้าย ผู้ใช้ขอตัวอย่างหรืออ่านทั้งหัวข้อต่อเองได้
_CONTRAST_RE = re.compile(r"(?<!บาง)(?<!แต่ละ)(?<!ทุก)(?<!หลาย)(?<!สัด)(?<!อัตรา)(?<!เป็น)"
                          r"ส่วน(?!ประกอบ|ใหญ่|ตัว|ที่|หนึ่ง|ใด|สูง|น้อย|ของ|หลัก|ย่อย)|ต่างจาก|แตกต่าง|ต่างกัน|ในขณะที่"
                          r"|คล้ายกัน|เหมือนกัน|เปรียบเทียบ|ตรงข้าม")


def _merge_plan(plan):
    """รวมรายการของหัวข้อเดียวกัน (ย่อหน้าเรียงตามลำดับในเล่ม, [] = ทั้งหัวข้อชนะ)"""
    merged = {}
    for e, picked in plan:
        t = e["topic"]
        if t not in merged:
            merged[t] = (e, picked)
        elif merged[t][1] is not None and picked is not None:
            both = sorted(set(merged[t][1]) | set(picked), key=_unit_of)
            merged[t] = (e, both if merged[t][1] and picked else [])
        else:
            merged[t] = (e, None)
    return list(merged.values())


LINK = "link"             # รายการในแผนที่ไม่แสดงเนื้อหา มีแต่ปุ่มไปอ่านหัวข้อนั้น
COMPARE_PARA_MAX = 700    # ย่อหน้าเทียบยาวกว่านี้ ใช้นิยามสองฝั่งแทนถ้าสั้นกว่า
COMPARE_SIDE_MAX = 250    # ใจความเปิดของแต่ละเรื่องในคำตอบเปรียบเทียบ ยาวประมาณนี้ (ตัดที่รอยต่อประโยค)
COMPARE_SLACK = 60        # เกินได้เท่านี้ถ้าจบย่อหน้า/ถึงตัวอย่างพอดี ดีกว่าตัดกลางประโยค
EXAMPLE_CHIP = "ขอตัวอย่าง"   # ปุ่มท้ายคำตอบเปรียบเทียบ (ตัวอย่างไม่แสดงมาเอง ผู้ใช้ขอเองได้)
_EXAMPLE_START = re.compile(r"\s*(?:ตัวอย่างเช่น|ยกตัวอย่าง|เช่น(?!เดียว|กัน|นี้|นั้น)|อาทิ|ดัง(?:แสดงใน)?(?:ภาพ|รูป|ตาราง))")
_CLAUSE_WORD = re.compile(r"โดย|ซึ่ง|แต่(?!ละ)|เเต่(?!ละ)|เมื่อ|ถ้า|หาก|เนื่องจาก|เพราะ|ดังนั้น|กล่าวคือ|ทั้งนี้|นอกจากนี้|อย่างไรก็ตาม|สำหรับ|ส่วน|ใน")
_CLAUSE_GAP = re.compile(r"(?<=[฀-๿)”])\s+(?=[฀-๿])")
_CLAUSE_START = re.compile(r"(?:\s+(?=ส่วน(?!ประกอบ|ใหญ่|ตัว|ที่|หนึ่ง|ใด|สูง|น้อย|ของ|หลัก|ย่อย)|และสุดท้าย|ทั้งนี้)"
                           r"|(?:\s+|(?<=[฀-๿]))(?=ข้อสังเกต|นอกจากนี้|ดังนั้น|อย่างไรก็ตาม))")


def _unit_of(k):
    """เลขย่อหน้าของรายการในแผน (เลขเดี่ยว = ทั้งย่อหน้า, (เลข, เริ่ม, จบ) = ช่วงของย่อหน้า)"""
    return k[0] if isinstance(k, tuple) else k


def _brief_end(u, begin, after, limit=COMPARE_SIDE_MAX):
    """ตำแหน่งจบของใจความเปิดของย่อหน้า นับจาก begin: จบก่อนตัวอย่าง ("เช่น …" "ดังภาพที่ …") และยาวราว limit ตัวอักษร
    ตัดได้เฉพาะรอยต่อประโยค (เว้นวรรคระหว่างข้อความไทยนอกวงเล็บ เลือกที่ขึ้นด้วยคำเชื่อม "โดย/ซึ่ง/แต่…" ก่อน)
    after = ตำแหน่งที่ต้องแสดงให้ถึงเป็นอย่างน้อย (ศัพท์ที่เทียบถูกเอ่ยถึงตรงนั้น) คืน len(u) ถ้าไม่ต้องตัด"""
    floor = max(begin + 40, after + 30)
    end = next((m.start() for m in _EXAMPLE_START.finditer(u) if m.start() >= floor), len(u))
    if end - begin <= limit + COMPARE_SLACK:
        return end
    gaps = [m for m in _CLAUSE_GAP.finditer(u, 0, end) if m.start() >= floor
            and u.count("(", 0, m.start()) == u.count(")", 0, m.start())
            and u.count("“", 0, m.start()) == u.count("”", 0, m.start())]
    # ประโยคใหม่: ขึ้นด้วยคำเชื่อม หรือเป็นประโยคแจกแจง ("โครงสร้างของฐานข้อมูล ได้แก่ …")
    strong = [m.start() for m in gaps if _CLAUSE_WORD.match(u, m.end()) or re.match(r"\S{1,40}\s*ได้แก่", u[m.end():])]
    cuts = [0] + [m.end() for m in _CLAUSE_GAP.finditer(u)] + [len(u)]
    # เว้นวรรคระหว่างรายการสั้น ๆ ("คน สถานที่ สิ่งของ") ไม่ใช่รอยต่อประโยค
    weak = [m.start() for m in gaps if all(b - a >= 15 for a, b in zip(cuts, cuts[1:]) if a == m.end() or m.start() < b <= m.end())]
    target = begin + limit
    for group in (strong, weak):               # รอยต่อสุดท้ายที่ยังไม่เกินความยาว
        fit = [p for p in group if p <= target]
        if fit:
            return fit[-1]
    for group in (strong, weak):               # ศัพท์ที่เทียบถูกเอ่ยถึงไกลกว่านั้น: รอยต่อแรกหลังจากเอ่ยถึง
        if group:
            return group[0]
    return end


def _brief_core(core):
    """(หัวข้อ, ย่อหน้า) -> ย่อหน้าเดิมแต่ตัดเหลือใจความเปิด (โค้ดและหัวเรื่องสั้น ๆ คงไว้ทั้งก้อน)"""
    e, picked = core
    us, out, cut = units(e), [], False
    for k in picked:
        k, begin, stop = k if isinstance(k, tuple) else (k, 0, len(us[k]))
        u = us[k]
        if u.startswith("```") or " | " in u:
            if not cut:                        # โค้ดที่ตามหลังย่อหน้าที่ตัดก่อน "ตัวอย่างเช่น …" คือตัวอย่างนั้นเอง
                out.append(k)
            continue
        end = min(stop, _brief_end(u, begin, begin))
        cut = end < len(u.rstrip())
        out.append((k, begin, end) if cut or begin else k)
    return e, out


def _brief_plan(plan):
    """แผนคำตอบของคำถามเปรียบเทียบที่ได้จากการตีความ (AI/คำตอบที่จำไว้): แสดงแค่ใจความเปิดเหมือนคำตอบเปรียบเทียบอื่น
    หัวข้อที่เลือกมาทั้งหัวข้อ -> ย่อหน้านิยาม/ย่อหน้าเปิดของหัวข้อนั้น"""
    return [item if item[1] == LINK else _brief_core(item if item[1] else _entry_core(item[0])) for item in plan]


def _statement(entry, key):
    """ประโยคกลางย่อหน้าที่บอกว่าเรื่องนี้เป็นอะไร ("… ระบบแฟ้มข้อมูล เป็นการเก็บข้อมูลลงแฟ้มแยกตามแผนก …")
    คืน (เลขย่อหน้า, ตำแหน่งที่ขึ้นด้วยชื่อเรื่อง, ท้ายย่อหน้า) หรือ None"""
    said = re.compile(r"\s*".join(re.escape(c) for c in key) + r"\s*(?:\([^)]*\)\s*)?(?:เป็น(?!ต้น)|คือ|หมายถึง)")
    for k, u in enumerate(units(entry)):
        m = said.search(u.lower()) if len(u) >= 60 and " | " not in u and not u.startswith("```") else None
        if m:
            return k, m.start() + len(m.group()) - len(m.group().lstrip()), len(u)
    return None


def _side_core(term, entries):
    """ย่อหน้าที่บอกว่าเรื่องฝั่งนี้คืออะไร (ย่อหน้าเดียว ไม่รวมตัวอย่าง/รายการ): ประโยค "X หมายถึง" ในตำรา,
    ย่อหน้าเปิดของหัวข้อที่ชื่อมีศัพท์นั้น หรือหัวเรื่องระดับที่สามของหัวข้อที่ค้นเจอ ("9.10.3 ฟังก์ชัน COUNT()" + ไวยากรณ์)"""
    found = find_definition(term, prefer=entries)
    if found and not (_is_meta(found[0]["topic"]) and any(not _is_meta(x["topic"]) for x in entries)):
        e, k, _ = found
        return e, definition_block(e, k, extras=False)
    key = _term_key(term)
    # หัวข้อที่ค้นเจอ รวมหัวข้อย่อยของมัน ("เอ็นทิตี้แบบอ่อน" -> "5.3 เอ็นทิตี้ · 2. เอ็นทิตี้แบบอ่อนแอ")
    titled = list({x["topic"]: x for found in list(entries) + search(term, limit=2) for x in section_parts(found)}.values())
    e = next((x for x in titled if len(key) >= 4 and key in _term_key(x["topic"]) and not _is_meta(x["topic"])), None)
    if e is not None:
        lead = _lead_block(e)[:1]
        opening = units(e)[lead[0]]
        if key not in _term_key(opening[:_brief_end(opening, 0, 0)]):
            said = _statement(e, key)          # ย่อหน้าเปิดเล่าเรื่องอื่นก่อน ("ในอดีต…"): ใช้ประโยคที่บอกว่าเรื่องนี้เป็นอะไร
            if said:
                return e, [said]
        return e, lead
    for e in entries:
        us = units(e)
        heads = [k for k, u in enumerate(us) if _SUBNUM.match(u.strip()) and key in _term_key(u)]
        if len(key) >= 3 and len(heads) == 1:
            block = subheading_block(e, heads[0])
            cut = next((n for n, k in enumerate(block) if n and us[k].strip().startswith("ตัวอย่าง")), len(block))
            code = next((n for n, k in enumerate(block[:cut]) if us[k].startswith("```")), None)
            return e, block[:cut if code is None else code + 1]    # ถึงโค้ดไวยากรณ์ ไม่รวมตารางสรุปที่ตามมา
    return None


def _near(key_text, sides, limit=160):
    """ทุกฝั่งถูกเอ่ยถึงใกล้กันในย่อหน้านี้ไหม (ย่อหน้าที่เอ่ยถึงสองเรื่องห่างกันคนละท่อนไม่ใช่การเทียบ)"""
    spots = [[m.start() for a in alts for m in re.finditer(re.escape(a), key_text)] for alts in sides]
    if not all(spots):
        return False
    return any(all(min(abs(a - b) for b in other) <= limit for other in spots[1:]) for a in spots[0])


def _excerpt(u, sides):
    """ช่วง (เริ่ม, จบ) ของย่อหน้าที่พูดถึงเรื่องที่เทียบ ตัดที่รอยต่อประโยคเท่านั้น ("ส่วน…" "และสุดท้าย…" "ข้อสังเกต…")
    เช่นบทสรุปบทที่ 10 พูดถึง JOIN ทุกชนิด ถาม INNER กับ LEFT ได้ถึงท่อน LEFT JOIN ไม่รวม RIGHT/FULL OUTER
    แล้วจบที่ใจความเปิด (ก่อนตัวอย่าง/รายละเอียดต่อท้าย) เมื่อเอ่ยถึงครบทุกฝั่งแล้ว
    None = ใช้ทั้งย่อหน้า (หาตำแหน่งไม่ได้ หรือตัดแล้วไม่สั้นลง)"""
    low, firsts, wide = u.lower(), [], False
    for alts in sides:
        hits = sorted((m.start(), m.end()) for a in alts if a
                      for m in re.finditer(r"\s*".join(re.escape(c) for c in a), low))
        if not hits:
            return None
        wide = wide or len(hits) > 3           # ศัพท์กว้างที่ถูกเอ่ยถึงทั้งย่อหน้า: ไม่ตัดท่อนหน้า
        firsts.append(hits[0])
    lo, hi = min(a for a, _ in firsts), max(b for _, b in firsts)
    starts = sorted({0} | {m.end() for m in _CLAUSE_START.finditer(u)})
    begin, end = max(b for b in starts if b <= lo), min([b for b in starts if b > hi] + [len(u)])
    if wide or len(u[begin:end].strip()) < 80 or end - begin > 0.7 * len(u):
        begin, end = 0, len(u)
    end = min(end, _brief_end(u, begin, hi))
    return (begin, end) if (begin, end) != (0, len(u)) else None


def _compare_plan(sides, cores, entries):
    """sides: ฝั่งละรายการคำ (รูปมาตรฐาน) ที่ย่อหน้าต้องมีอย่างน้อยหนึ่งคำ, cores: [(หัวข้อ, ย่อหน้า) หรือ None] ต่อฝั่ง
    แสดงอย่างใดอย่างหนึ่ง ไม่ซ้อนกัน: ย่อหน้าที่ตำราเทียบสองเรื่องไว้เอง (ตัดเหลือช่วงที่เกี่ยว) หรือย่อหน้านิยามของแต่ละฝั่ง
    คืน [] ถ้าไม่มีทั้งสองแบบ"""
    cores = [_brief_core(c) if c else None for c in cores]
    cands = {c[0]["topic"]: c[0] for c in cores if c}
    cands.update({e["topic"]: e for e in entries})
    for e in list(cands.values()):             # บทสรุปของบทที่เกี่ยวข้องมักเป็นที่ที่ตำราเทียบเรื่องต่าง ๆ ไว้
        chapter = _chapter_of(e["topic"])
        for x in ENTRIES:
            if chapter and _chapter_of(x["topic"]) == chapter and x["topic"].startswith("บทสรุป"):
                cands[x["topic"]] = x
    paras = []
    for order, e in enumerate(ENTRIES):
        if e["topic"] not in cands or e["topic"].startswith("แบบฝึกหัด"):
            continue
        for k, u in enumerate(units(e)):
            if len(u) < 60 or " | " in u or u.startswith("```") or not _near(_term_key(u), sides):
                continue
            # เทียบจริง = ช่วงที่แสดงมีคำเปรียบเทียบ (ส่วน/คล้ายกัน/แตกต่าง…), เนื้อหาก่อนบทสรุป, ตามลำดับในเล่ม
            cut = _excerpt(u, sides)
            shown = u[cut[0]:cut[1]] if cut else u
            paras.append((not _CONTRAST_RE.search(shown), _is_meta(e["topic"]), order, k, e, cut))
    paras.sort(key=lambda p: p[:4])
    both = _merge_plan([c for c in cores if c]) if all(cores) else []
    both_size = sum(k[2] - k[1] if isinstance(k, tuple) else len(units(e)[k])
                    for e, picked in both for k in (picked or range(len(units(e)))))

    def paragraph(p):
        k, e, cut = p[3], p[4], p[5]
        links = [(c[0], LINK) for c in cores if c and c[0]["topic"] != e["topic"]]
        return [(e, [(k,) + cut if cut else k])] + links, (cut[1] - cut[0] if cut else len(units(e)[k]))

    own = {(e["topic"], _unit_of(k)) for e, picked in both for k in picked or []}
    explicit = [p for p in paras if not p[0] and (p[4]["topic"], p[3]) not in own]
    if explicit:                               # 1) ตำราเทียบสองเรื่องไว้เอง: ใช้ ถ้าไม่ยาวกว่านิยามสองฝั่ง
        plan, size = paragraph(explicit[0])
        if size <= COMPARE_PARA_MAX or not both or size <= both_size:
            return plan
    if both:                                   # 2) นิยามของแต่ละฝั่งวางคู่กัน
        return both
    # 3) หานิยามไม่ครบ: ย่อหน้าที่เอ่ยถึงทั้งสองเรื่องใกล้กัน ("HAVING … เนื่องจากไม่สามารถใช้ WHERE กับ…") ดีกว่ายกทั้งหัวข้อ
    return paragraph(paras[0])[0] if paras else []


def _entry_core(entry):
    hits = sorted(k for hs in definitions().values() for x, k, full in hs if x["topic"] == entry["topic"] and full)
    if hits and hits[0] < 3:
        return entry, definition_block(entry, hits[0], extras=False)
    return entry, _lead_block(entry)[:1]


def _compare_entries_plan(pair):
    """เทียบเรื่องที่คุยอยู่กับอีกเรื่อง (ตามหัวข้อที่เปิดไว้): ชื่อฝั่งละ = ชื่อไทยของหัวข้อ + วลีอังกฤษในชื่อ"""
    pair = list({e["topic"]: e for e in pair}.values())[:2]
    if len(pair) < 2:
        return []
    sides = [{k for k in [_term_key(_own_title(e))] + [_term_key(p) for p in _EN_PHRASE.findall(_heading(e))]
              if len(k) >= 4} for e in pair]
    return _compare_plan(sides, [_entry_core(e) for e in pair], pair)


def _shows_terms(plan, terms):
    """ข้อความที่จะแสดงตามแผนนี้มีศัพท์ที่ถามอยู่จริงไหม (เทียบแบบไม่สนช่องว่าง/ตัวพิมพ์/การสะกดที่ต่างกัน)"""
    keys = {_term_key(t) for t in terms} - {""}
    shown = []
    for e, picked in plan:
        if picked is None:
            shown += [u for p in section_parts(e) for u in units(p)]
        else:
            shown += units(e) if not picked else [units(e)[_unit_of(k)] for k in picked]
    # ต้องอยู่ในย่อหน้าเนื้อหา ไม่ใช่แค่ข้อในรายการ/ช่องในตาราง ("- Sql Injection" ในตาราง 12.2 ไม่ได้อธิบายว่าคืออะไร)
    text = _term_key(" ".join(u for u in shown if not u.lstrip().startswith("-") and " | " not in u))
    return any(k in text for k in keys)


def _followup_chips(entry, picked):
    """ปุ่มต่อจากคำตอบบางส่วน: ถ้าย่อหน้าถัดไปในเล่มเป็นตัวอย่าง ("ตัวอย่างข้อมูล") หรือภาพ/ตาราง ("ภาพที่ 1.1 …")
    ให้ปุ่มถามถึงสิ่งนั้นโดยตรง (ข้อความปุ่มต้องตอบได้ตรงเรื่องเดียว จึงใช้เฉพาะชื่อที่ไม่ซ้ำกันในเล่ม)"""
    us = units(entry)
    nxt = next((k for k in range(max(picked) + 1, len(us)) if us[k].strip()), None)
    if nxt is None:
        return []
    u = us[nxt].strip()
    m = _CAP_RE.match(u)
    if m:
        return [f"{m.group(1)} {m.group(2)} {m.group(3)}".strip()]
    if re.match(r"ตัวอย่าง(?!ที่\s*\d)", u) and len(u) <= 60 and " | " not in u and not u.startswith("```"):
        if len(subheadings().get(_term_key(_SUBNUM.sub("", u)), [])) == 1:
            return [u]
    return []


def render_plan(plan, first_chips=()):
    """plan: [(หัวข้อ, ย่อหน้าที่เลือก)] ย่อหน้าที่เลือก None = ทั้งหัวข้อรวมหัวข้อย่อยทุกส่วน,
    [] = ทั้งหัวข้อเฉพาะส่วนนี้ (ไม่รวมหัวข้อย่อย), [เลข...] = เฉพาะย่อหน้าเหล่านั้น ตามลำดับในเล่ม
    คำตอบที่แสดงบางส่วนมีหมายเหตุกับปุ่มต่อ (ตัวอย่าง/ภาพที่ตามมา และทั้งหัวข้อ) ท้ายคำตอบครั้งเดียว
    first_chips = ปุ่มที่ขึ้นก่อนปุ่มหัวข้อ ("ขอตัวอย่าง" ของคำตอบเปรียบเทียบ)"""
    blocks, chips, follow, partials = [], [], [], 0
    links = [entry["topic"] for entry, picked in plan if picked == LINK]
    plan = [(entry, picked) for entry, picked in plan if picked != LINK]
    whole = {entry["topic"] for entry, picked in plan if picked is None}
    shown = set()

    def piece(us, k):
        """ย่อหน้าเต็ม หรือช่วงของย่อหน้า (มี … บอกว่าตัดมาจากกลางย่อหน้า ข้อความในช่วงยังตรงตัวตามตำรา)"""
        if not isinstance(k, tuple):
            return us[k]
        u = us[k[0]]
        return ("… " if k[1] > 0 else "") + u[k[1]:k[2]].strip() + (" …" if k[2] < len(u) else "")

    for entry, picked in plan:
        main = entry["topic"].split(" · ")[0]
        if entry["topic"] in shown or (main != entry["topic"] and main in whole):
            continue                           # แสดงไปแล้ว หรือรวมอยู่ในหัวข้อหลักที่แสดงครบทุกส่วน
        shown.add(entry["topic"])
        parts = section_parts(entry) if picked is None else [entry]
        for e in parts:
            us = units(e)
            cut = bool(picked) and any(isinstance(k, tuple) for k in picked)
            partial = cut or (bool(picked) and len(set(picked)) < len(us))
            order = sorted(set(picked), key=lambda k: k[0] if isinstance(k, tuple) else k) if partial else []
            text = "\n".join(piece(us, k) for k in order) if partial else e["description"]
            # บท + เลขหน้า มาจากส่วน "แหล่งอ้างอิง" ของหัวข้อในไฟล์ (ตรวจกับสารบัญและหน้า PDF แล้ว)
            block = ["## " + e["topic"], with_figures(text), _source_line(e)]
            if partial:
                partials += 1
                follow += [] if cut else _followup_chips(e, picked)
                chips.append(e["topic"])
            elif picked is not None and len(section_parts(e)) > 1:
                chips.append(e["topic"])       # หัวข้อย่อยที่ไม่ได้แสดง อ่านต่อได้จากหัวข้อหลัก
            blocks.append("\n\n".join(block))
    out = "\n\n---\n\n".join(blocks)
    # ปุ่มตัวอย่าง/ภาพที่ตามมาใช้เฉพาะคำตอบที่มีส่วนเดียว (คำตอบเปรียบเทียบหลายส่วนไม่ควรมีปุ่มของส่วนใดส่วนหนึ่ง)
    chips = list(dict.fromkeys(list(first_chips) + (follow if partials == 1 else []) + chips + links))
    if chips:
        out += "\n\n" + PARTIAL_NOTE + "\n" + "\n".join(f"[[ถาม:{t}]]" for t in chips)
    return out


def render_compared(plan, terms=()):
    """คำตอบเปรียบเทียบ: แสดงแค่ใจความเปิดของแต่ละเรื่อง ตัวอย่างไม่แสดงมาเอง
    ถ้าตำรามีตัวอย่างของเรื่องที่เทียบ มีปุ่ม "ขอตัวอย่าง" ให้ผู้ใช้ขอเอง (กดแล้วได้เท่ากับพิมพ์ "ขอตัวอย่าง" ต่อจากคำตอบนี้)"""
    text = render_plan(plan)
    shown = [e for e, picked in plan if picked != LINK]
    if PARTIAL_MARK not in text or not _examples(shown, text, terms, partial=True)[0]:
        return text
    return render_plan(plan, first_chips=[EXAMPLE_CHIP])


def question_key(query):
    """รูปมาตรฐานของคำถาม: พิมพ์ต่างกันเล็กน้อยถือเป็นคำถามเดียวกัน ได้คำตอบเดียวกัน
    ("SQL คืออะไร", "sql คืออะไรครับ?", "sql  คือ อะไร" -> "sql คืออะไร")"""
    text = re.sub(r"[\s?？!.,ๆ\"'“”]+", " ", _split_glued(query).lower()).strip()
    text = re.sub(r"(?<=[฀-๿]) (?=[฀-๿])", "", text)          # ช่องว่างระหว่างคำไทยไม่มีความหมาย
    return re.sub(r"\s*(ครับ|คับ|ค่ะ|คะ|นะคะ|นะครับ|นะ|จ้า|จ้ะ|หน่อย)+$", "", text).strip()


def plan_to_json(plan):
    return [{"topic": e["topic"], "picked": picked} for e, picked in plan]


def _valid_pick(entry, k):
    us = units(entry)
    if isinstance(k, tuple):
        return (len(k) == 3 and all(isinstance(n, int) and not isinstance(n, bool) for n in k)
                and 0 <= k[0] < len(us) and 0 <= k[1] < k[2] <= len(us[k[0]]))
    return isinstance(k, int) and not isinstance(k, bool) and 0 <= k < len(us)


def plan_from_json(items):
    """แผนที่จำไว้ -> แผนของตำราที่โหลดอยู่ หรือ None ถ้าอ้างหัวข้อ/ย่อหน้าที่ไม่มีแล้ว"""
    by_topic = {e["topic"]: e for e in ENTRIES}
    plan = []
    for item in items if isinstance(items, list) else []:
        e = by_topic.get(item.get("topic")) if isinstance(item, dict) else None
        picked = item.get("picked") if e else None
        if isinstance(picked, list):           # ช่วงของย่อหน้าเก็บเป็น [เลข, เริ่ม, จบ]
            picked = [tuple(k) if isinstance(k, list) else k for k in picked]
        if e is None or not (picked is None or (isinstance(picked, list) and all(_valid_pick(e, k) for k in picked))):
            return None
        plan.append((e, picked))
    return plan if isinstance(items, list) else None


def _decide(query, plan, selector, memory):
    """คำถามที่ต้องตีความ (วิธีค้นเองไม่มั่นใจ):
    1) เคยตอบคำถามนี้แล้ว -> คำตอบเดิม (AI ตอบไม่เหมือนเดิมทุกครั้ง จึงต้องจำ ไม่ถาม AI ซ้ำ)
    2) ยังไม่เคย -> ให้ AI ช่วยเลือก แล้วจำคำตอบที่แสดงไว้ (รวมกรณีที่ AI ใช้ไม่ได้และตอบด้วยวิธีค้นเอง)
    3) จำเพิ่มไม่ได้ (บน Vercel) -> ไม่เรียก AI สด ใช้วิธีค้นเองซึ่งได้ผลเดิมทุกครั้ง"""
    book = DOCUMENT_META.get("markdown_sha256")
    key = question_key(query)
    if memory is not None:
        stored = memory.get(key, book)
        restored = plan_from_json(stored.get("plan")) if isinstance(stored, dict) else None
        if restored is not None:
            return restored
        if not memory.writable:
            return plan
    if not selector:
        return plan
    chosen = selector(query)
    # ค้นเองไม่เจอเลยและถามความหมายของศัพท์ ("MySQL คืออะไร"): ย่อหน้าที่ AI เลือกต้องมีศัพท์นั้นอยู่จริง
    # ไม่งั้นเป็นแค่หัวข้อที่เรื่องใกล้เคียง (ตำราไม่ได้อธิบายศัพท์นั้น) ตอบว่าไม่มีข้อมูลตามเดิม
    # AI เลือกได้แค่แบบฝึกหัด/บทสรุปทั้งที่ไม่ได้ถามถึง (เคยสุ่มพลาดครั้งหนึ่ง) ใช้ผลค้นเองแทน
    only_meta = chosen and plan and all(e["topic"].startswith(("แบบฝึกหัด", "บทสรุป")) for e, _ in chosen) \
        and not any(k in query.lower() for k in _META_WORDS)
    if chosen and not only_meta and (plan or not asks_meaning(query) or _shows_terms(chosen, _asked_terms(query))):
        plan, source = chosen, "AI"
    elif chosen is None:
        source = "ค้นเอง (เรียก AI ไม่สำเร็จ)"
    else:
        source = "ค้นเอง (AI ไม่พบหรือผลไม่ผ่านการตรวจ)"
    if memory is not None:
        memory.put(key, book, plan_to_json(plan), source)
    return plan


def answer_from_dataset(history, selector=None, memory=None):
    """No generated prose: render only stored fields, with traceable provenance.
    selector (ไม่บังคับ) = ตัวช่วยเลือกหัวข้อ/ย่อหน้าด้วย AI (ai_select.plan_answer) คืนแผนแบบ plan_answer
    หรือ None/[] เมื่อใช้ไม่ได้หรือไม่เจอ ซึ่งจะกลับมาใช้วิธีค้นแบบเดิม
    memory (ไม่บังคับ) = answer_memory.AnswerMemory จำคำตอบของคำถามที่ต้องตีความ ถามซ้ำได้คำตอบเดิมเสมอ"""
    global ENTRIES
    # Revalidate on each answer, including when files change after startup.
    ENTRIES = load_entries()
    if DATASET_ERROR:
        return DATASET_ERROR
    questions = [str(m.get("content") or "") for m in history if isinstance(m, dict) and m.get("role") == "user"]
    query = _split_glued(questions[-1]) if questions else ""
    canned = small_talk(query)
    if canned:
        return canned

    if _explicitly_missing_topic(query) or (re.search(r"รหัสผ่าน|password", query, re.I)
                                            and re.search(r"มหาวิทยาลัย|ระบบของฉัน|ของฉัน", query)):
        return NO_DATA

    direct = _direct_plan(query)
    special_override = _special_topics(query)
    if direct is not None and not special_override:  # ภาพ/ตาราง/หัวเรื่องย่อยที่ถามตรงชื่อ (รวมปุ่มต่อท้ายคำตอบก่อนหน้า)
        return render_plan(direct) if direct else NO_DATA

    data_types = _data_type_topics(query)
    if data_types:                              # ชื่อหัวข้อซ้ำกัน: ใช้บริบทหรือแสดงทั้งสองหัวข้อถ้าถามกว้าง ๆ
        return render_plan([(e, None) for e in data_types])

    current, previous, shown_text = conversation_context(history)
    if current:
        # ถามต่อจากเรื่องที่คุยอยู่: ตัดคำถามต่อทิ้ง ดูว่ายังเหลือชื่อหัวข้อใหม่ไหม
        residual = _FOLLOW_WORDS.sub(" ", query).strip()
        mentioned = search(residual, limit=3) if residual else []
        current_topics = {e["topic"] for e in current}
        if _COMPARE_RE.search(query):
            pair = []
            if mentioned:
                # "แล้วมันต่างจาก INNER JOIN ยังไง" -> เรื่องที่คุยอยู่ + เรื่องที่ยกมาเทียบ
                # ("INNER JOIN กับ LEFT JOIN ต่างกันยังไง" ระบุครบทั้งสองฝั่ง = คำถามใหม่ ไม่เอาเรื่องเดิมมาปน)
                implicit = _BACKREF_RE.search(query) or (re.search(r"ต่างจาก|เทียบกับ", query) and len(mentioned) == 1)
                if implicit:
                    pair = current + [e for e in mentioned if e["topic"] not in current_topics]
            elif previous:    # "มันต่างกันยังไง" -> สองเรื่องล่าสุดที่คุยกัน
                pair = previous + current
            else:             # คุยมาเรื่องเดียว ยังไม่รู้ว่าจะเทียบกับอะไร
                return (f"ต้องการเทียบ **{_topic_name(current)}** กับเรื่องอะไรครับ "
                        'พิมพ์ชื่อเรื่องที่ต้องการเทียบ เช่น "ต่างจาก INNER JOIN ยังไง"')
            if len({e["topic"] for e in pair}) > 1:
                compared = _compare_entries_plan(pair)
                return "ตำราอธิบายแต่ละเรื่องไว้ดังนี้\n\n---\n\n" + (
                    render_compared(compared, _asked_terms(query)) if compared else render_topics(pair))
        last_answer = next((str(m.get("content") or "") for m in reversed(history)
                            if isinstance(m, dict) and m.get("role") == "assistant"), "")
        asking_examples = _EXAMPLE_RE.search(query) or (   # "มีอีกไหม" ต่อจากคำตอบตัวอย่าง
            last_answer.startswith("ตัวอย่างเพิ่มเติมเรื่อง") and _AGAIN_RE.search(query.strip())
            and not _RELATED_RE.search(query))
        if asking_examples and (not mentioned or {e["topic"] for e in mentioned} <= current_topics):
            # คำตอบก่อนหน้าแสดงเฉพาะส่วน: ตัวอย่างของศัพท์ที่ถาม ไม่ใช่ของทั้งหัวข้อ
            partial = PARTIAL_MARK in last_answer
            asked = _asked_terms(questions[-2]) if partial and len(questions) > 1 else []
            return more_examples(current, shown_text, focus_terms=asked, partial=partial)
        if _MORE_RE.search(query) and not mentioned:
            # คำตอบล่าสุดแสดงแค่ส่วนที่ถาม: "อธิบายเพิ่ม" "มีอีกไหม" = อ่านทั้งหัวข้อ, "…ที่เกี่ยวข้อง" = หัวข้ออื่น
            if PARTIAL_MARK in last_answer and not re.search(r"เกี่ยว", query):
                return render_topics(current)
            return related_topics(current, shown_text)

    # วิธีค้นเองมั่นใจ (ชื่อหัวข้อ, ศัพท์ที่ตำรานิยามไว้, หัวเรื่องย่อยตรงตัว) ได้ผลเดิมทุกครั้ง ไม่ต้องใช้ AI
    # นอกนั้นใช้คำตอบที่จำไว้ หรือให้ AI ช่วยตีความแล้วจำไว้
    plan, sure = _plan(query)
    comparing = len(_asked_terms(query)) > 1 and bool(_COMPARE_RE.search(query))
    if not sure:
        plan = _decide(query, plan, selector, memory)
        if comparing:
            plan = _brief_plan(plan)
    if not plan and len(questions) > 1 and query.startswith(("แล้ว", "อธิบายต่อ")):
        plan = plan_answer(questions[-2] + " " + query)
    if not plan:
        return NO_DATA
    return render_compared(plan, _asked_terms(query)) if comparing else render_plan(plan)
