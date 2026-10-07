"""Test tuzish, Groq bilan ishlash va saqlash (Telegramga bog'liq emas)."""
import asyncio, json, os, random, sqlite3, time
from pathlib import Path
import httpx

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TOTAL_QUESTIONS = 10   # Testlar soni
CHUNK_SIZE = 9000      # Bir marta AI ga beriladigan matn (belgi)
MAX_CHUNKS = 3

# ---------------------------------------------------------------- darsliklar
def load_books(data_dir="data"):
    books = []
    for p in Path(data_dir).glob("grade*.json"):
        with open(p, encoding="utf-8") as f:
            b = json.load(f)
        books.append(b)
    books.sort(key=lambda b: (b["grade"], b["subject"]))
    for i, b in enumerate(books):
        b["id"] = i
        b["key"] = f'{b["grade"]}|{b["subject"]}'
    return books

# ---------------------------------------------------------------- matnni bo'lish
def split_text(text, size=CHUNK_SIZE, max_chunks=MAX_CHUNKS):
    text = text[: size * max_chunks]
    parts, cur = [], ""
    for para in text.split("\n\n"):
        while len(para) > size:
            if cur.strip():
                parts.append(cur); cur = ""
            parts.append(para[:size]); para = para[size:]
        if len(cur) + len(para) + 2 > size and cur.strip():
            parts.append(cur); cur = ""
        cur += para + "\n\n"
    if cur.strip():
        parts.append(cur)
    return parts[:max_chunks] if len(parts) > max_chunks else parts

# ---------------------------------------------------------------- qiyinlik
LEVELS = {
    5: "5-sinf o'quvchisi uchun o'rtacha-qiyin. Til sodda va tushunarli bo'lsin, lekin savollarning kamida uchdan biri 'nima uchun?' yoki 'qanday oqibatga olib keldi?' turida bo'lsin.",
    6: "6-sinf o'quvchisi uchun qiyin. Sana, shaxs va joylarni aralashtirib yuboradigan, diqqatni talab qiladigan savollar tuz; sabab-oqibat savollari ko'p bo'lsin.",
    7: "7-sinf uchun qiyin. Faktlarni eslab qolishdan tashqari taqqoslash, xronologiya (qaysi voqea oldin/keyin) va sabab-oqibat savollari bo'lsin.",
    8: "8-sinf uchun qiyin. Tahlil, taqqoslash, xronologiya va 'quyidagilardan qaysi biri noto'g'ri?' turidagi savollar ko'p bo'lsin.",
    9: "9-sinf uchun juda qiyin (DTM va olimpiada darajasiga yaqin). Chuqur tahlil, taqqoslash, xronologiya, sabab-oqibat va 'qaysi biri noto'g'ri/ortiqcha?' savollari bo'lsin; noto'g'ri variantlar juda ishonarli bo'lsin.",
}

FOCUS = [
    "sanalar va voqealar ketma-ketligiga",
    "shaxslar va ularning faoliyatiga",
    "sabab va oqibatlarga",
    "atamalar va tushunchalarga",
    "joylar, shaharlar va davlatlarga",
    "taqqoslash va o'xshash-farqli jihatlarga",
    "tarixiy voqealarning ahamiyati va natijalariga",
]

# ---------------------------------------------------------------- Groq
SYSTEM_PROMPT = """Sen maktab tarix fani o'qituvchisisan. Senga darslikdan parcha beriladi. Shu parcha asosida o'quvchilar uchun ko'p tanlovli test savollari tuzasan.
Qoidalar:
1) BARCHA SAVOLLAR VA JAVOB VARIANTLARI FAQAT O'ZBEK TILIDA (LOTIN YOZUVIDA) BO'LISHI SHART. BOSHQA TILLARNI ISHLATMA.
2) Faqat berilgan matndagi ma'lumotlarga tayan, o'zingdan fakt qo'shma.
3) Savollar sana, shaxs, joy, voqea, sabab-oqibat va atamalar haqida bo'lsin; oson va o'rtacha qiyinlikdagi savollar aralash bo'lsin.
4) Har savolda aniq 4 ta variant bo'lsin, faqat bittasi to'g'ri. Noto'g'ri variantlar ishonarli bo'lsin, uzunligi to'g'ri javobga yaqin bo'lsin.
5) "Matnga ko'ra", "darslikda" kabi iboralarni ishlatma, savol mustaqil tushunarli bo'lsin.
6) Matn oxiridagi "Savol va topshiriqlar", "O'ylab ko'ring" kabi mashq qismlarini savolga aylantirma, asosiy bayon qilingan ma'lumotdan foydalan.
7) Savollar bir-birini takrorlamasin.
Javobni FAQAT JSON ko'rinishida ber, boshqa hech narsa yozma:
{"questions":[{"q":"savol matni","options":["A varianti","B varianti","C varianti","D varianti"],"answer":0,"explanation":"bir jumlalik izoh"}]}
Bunda "answer" to'g'ri variantning indeksi (0, 1, 2 yoki 3)."""

async def groq_chat(messages, json_mode=True, temperature=0.3, retries=6):
    key = os.environ.get("GROQ_API_KEY", "")
    model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
    if not key:
        raise RuntimeError("GROQ_API_KEY topilmadi (.env faylini tekshiring)")
    payload = {"model": model, "messages": messages, "temperature": temperature}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {key}"}
    last = None
    async with httpx.AsyncClient(timeout=120) as client:
        for attempt in range(retries):
            try:
                r = await client.post(GROQ_URL, json=payload, headers=headers)
            except httpx.HTTPError as e:
                last = e; await asyncio.sleep(5 * (attempt + 1)); continue
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            last = RuntimeError(f"Groq {r.status_code}: {r.text[:200]}")
            if r.status_code in (429, 500, 502, 503) or "json_validate_failed" in r.text:
                wait = float(r.headers.get("retry-after", 0) or 0) or 10 * (attempt + 1)
                await asyncio.sleep(min(wait, 60)); continue
            raise last
    raise last or RuntimeError("Groq javob bermadi")

def validate(items):
    ok = []
    for it in items if isinstance(items, list) else []:
        try:
            q = str(it["q"]).strip(); opts = [str(o).strip() for o in it["options"]]
            ans = int(it["answer"]); exp = str(it.get("explanation", "")).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not q or len(opts) != 4 or len(set(o.lower() for o in opts)) != 4 or not all(opts):
            continue
        if not 0 <= ans <= 3:
            continue
        ok.append({"q": q, "options": opts, "answer": ans, "explanation": exp})
    return ok

def parse_questions(content):
    data = json.loads(content)
    if isinstance(data, dict):
        data = data.get("questions", [])
    return validate(data)

async def _ask(book, topic, chunk, cnt, grade, focus):
    level = LEVELS.get(grade, LEVELS[7])
    b_name = book["book"]
    t_no = topic["no"]
    t_title = topic["title"]
    f1, f2 = focus[0], focus[1]
    
    user = (
        f"Darslik: {b_name}\nMavzu: {t_no}-mavzu. {t_title}\n\n"
        f"QIYINLIK DARAJASI: {level}\n"
        f"Savollar turi taxminan: 40% fakt, 30% sabab-oqibat va tahlil, 15% taqqoslash, 15% 'qaysi biri noto'g'ri?' turida.\n"
        f"Bu safar {f1} va {f2} ko'proq e'tibor ber. Odatiy, eng aniq savollardan qoch, yangicha tuz.\n\n"
        f"Quyidagi parcha asosida aniq {cnt} ta test savoli tuz. Barcha savollar faqat O'zbek tilida bo'lsin.\n\nMATN:\n{chunk}"
    )
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
    for _ in range(3):
        try:
            got = parse_questions(await groq_chat(msgs, temperature=0.8))
        except (json.JSONDecodeError, KeyError):
            got = []
        if len(got) >= max(1, cnt // 2):
            return got[:cnt]
    return got[:cnt]

def _dedupe(qs):
    seen, out = set(), []
    for q in qs:
        k = q["q"].lower()
        if k not in seen:
            seen.add(k); out.append(q)
    return out

async def generate_questions(book, topic, grade=None, total=TOTAL_QUESTIONS):
    """Har chaqirilganda YANGI testlar tuzadi."""
    grade = grade or book.get("grade", 7)
    focus = random.sample(FOCUS, 2)
    chunks = split_text(topic["text"])
    random.shuffle(chunks)
    n = len(chunks)
    per = [total // n + (1 if k < total % n else 0) for k in range(n)]
    out = []
    for chunk, cnt in zip(chunks, per):
        if cnt > 0:
            out += await _ask(book, topic, chunk, cnt + 1, grade, focus)
            await asyncio.sleep(1.0)
    out = _dedupe(out)
    if len(out) < total:
        need = total - len(out)
        out += await _ask(book, topic, random.choice(chunks), need + 1, grade, random.sample(FOCUS, 2))
        out = _dedupe(out)
    if len(out) == 0:
        raise RuntimeError("Yetarli savol tuzilmadi")
    random.shuffle(out)
    return out[:total]

def shuffled(q):
    """Variantlarni aralashtiradi."""
    idx = list(range(4)); random.shuffle(idx)
    return {"q": q["q"], "options": [q["options"][i] for i in idx],
            "answer": idx.index(q["answer"]), "explanation": q["explanation"]}

async def ai_feedback(book, topic, wrong, percent):
    """Xatolar bo'yicha qisqa shaxsiy fikr."""
    if not wrong:
        return None
    lines = "\n".join(f"- {w['q']} (to'g'ri javob: {w['correct']}; o'quvchi javobi: {w['chosen']})" for w in wrong[:12])
    topic_title = topic["title"]
    user_prompt = f"O'quvchi \"{topic_title}\" mavzusi bo'yicha test topshirdi, natija {percent}%. Xato qilgan savollari:\n{lines}\n\nO'quvchiga: qaysi qismlarni qayta o'qishi kerakligini va qanday o'qishni maslahat ber. Rag'batlantiruvchi bo'lsin."
    
    msgs = [
        {"role": "system", "content": "Sen mehribon tarix o'qituvchisisan. O'zbek tilida (lotin) 3-4 jumlada yoz. Ro'yxat va sarlavha ishlatma."},
        {"role": "user", "content": user_prompt}
    ]
    try:
        return (await groq_chat(msgs, json_mode=False, temperature=0.5)).strip()
    except Exception:
        return None

# ---------------------------------------------------------------- saqlash
class Store:
    def __init__(self, path="bot.db"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS results (id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, book TEXT, topic TEXT, correct INTEGER, total INTEGER, ts INTEGER)""")
        self.db.commit()
    def add_result(self, uid, book, topic, correct, total):
        self.db.execute("INSERT INTO results (user_id,book,topic,correct,total,ts) VALUES (?,?,?,?,?,?)",
                        (uid, book, topic, correct, total, int(time.time())))
        self.db.commit()
    def last_results(self, uid, n=10):
        return self.db.execute("SELECT book,topic,correct,total FROM results WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, n)).fetchall()