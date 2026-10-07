import asyncio, html, logging, os, random
from dotenv import load_dotenv
load_dotenv()
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
import quizlib as ql

logging.basicConfig(level=logging.INFO)
BOOKS = ql.load_books("data")
STORE = ql.Store("bot.db")
router = Router()
GEN_LIMIT = asyncio.Semaphore(int(os.environ.get("MAX_PARALLEL_GENERATIONS", "2")))
sessions = {}   # user_id -> joriy test
pending = {}    # user_id -> (bid, i, asyncio.Task)  — "Tayyormisan?" ekranida oldindan tuzilayotgan test
LETTERS = "ABCD"
esc = html.escape

WHY_READ = ("📚 <b>Nega ko'proq o'qish kerak?</b>\nTarix — faqat sana va ismlar emas. Voqealarning sabab va oqibatini bilgan odam bugungi "
            "hayotni ham yaxshiroq tushunadi, xatolarni takrorlamaydi va Vatanining o'tmishi bilan haqiqiy faxrlana oladi. "
            "Bir marta o'qigan narsa tez unutiladi, takror o'qish esa uni uzoq xotiraga o'tkazadi. Mavzuni qayta o'qib, "
            "testni yana yechsangiz (savollar har safar yangi bo'ladi), natijangiz albatta oshadi.")

def tier(p):
    if p >= 90: return "🏆 Ajoyib natija! Mavzuni juda yaxshi o'zlashtirgansiz."
    if p >= 70: return "👍 Yaxshi natija! Bir oz takrorlasangiz, a'lo bo'ladi."
    if p >= 50: return "🙂 O'rtacha natija. Mavzuni yana bir bor diqqat bilan o'qib chiqing."
    return "📖 Hozircha bilim yetarli emas, lekin bu normal. Mavzuni qaytadan o'qib, testni yana urinib ko'ring."

async def send_long(msg: Message, text: str, markup=None):
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 3800:
            parts.append(cur); cur = ""
        cur += line + "\n"
    parts.append(cur)
    for i, p in enumerate(parts):
        await msg.answer(p.strip() or "…", reply_markup=markup if i == len(parts) - 1 else None)

# ------------------------------------------------------------------ test tuzish
async def _generate(bid, i):
    bk = BOOKS[bid]
    async with GEN_LIMIT:
        return await ql.generate_questions(bk, bk["topics"][i], bk["grade"])

def start_generation(uid, bid, i):
    """Testni fonda tuzishni boshlaydi (eskisi bo'lsa bekor qiladi)."""
    old = pending.pop(uid, None)
    if old and not old[2].done():
        old[2].cancel()
    task = asyncio.create_task(_generate(bid, i))
    task.add_done_callback(lambda t: t.cancelled() or t.exception())   # "never retrieved" ogohlantirishini o'chiradi
    pending[uid] = (bid, i, task)
    return task

# ------------------------------------------------------------------ menyular
def home_kb():
    b = InlineKeyboardBuilder()
    for g in sorted({bk["grade"] for bk in BOOKS}):
        b.button(text=f"{g}-sinf", callback_data=f"g:{g}")
    b.button(text="📊 Natijalarim", callback_data="stats")
    b.adjust(3, 2, 1)
    return b.as_markup()

HELLO = ("Assalomu alaykum, <b>{name}</b>! 👋\n\nMen tarix fanidan bilimingizni sinab ko'radigan botman. "
         "Sinf va mavzuni tanlang, men darslik asosida <b>30 ta qiyin test</b> tuzaman. Savollar har safar yangi bo'ladi.\n\n"
         "<b>Sinfingizni tanlang:</b>")

@router.message(CommandStart())
async def start(m: Message):
    sessions.pop(m.from_user.id, None)
    await m.answer(HELLO.format(name=esc(m.from_user.first_name or "do'st")), reply_markup=home_kb())

@router.callback_query(F.data == "home")
async def home(c: CallbackQuery):
    await c.message.edit_text(HELLO.format(name=esc(c.from_user.first_name or "do'st")), reply_markup=home_kb())
    await c.answer()

@router.callback_query(F.data == "stats")
async def stats(c: CallbackQuery):
    rows = STORE.last_results(c.from_user.id)
    if not rows:
        text = "Hali test topshirmagansiz. Sinfni tanlab, birinchi testni boshlang!"
    else:
        lines = ["📊 <b>Oxirgi natijalaringiz:</b>\n"]
        for key, topic, ok, total in rows:
            grade, subj = key.split("|", 1)
            lines.append(f"• {grade}-sinf · {esc(subj)} · {esc(topic)}-mavzu — <b>{ok}/{total}</b> ({round(ok * 100 / total)}%)")
        text = "\n".join(lines)
    b = InlineKeyboardBuilder(); b.button(text="🏠 Bosh sahifa", callback_data="home")
    await c.message.edit_text(text, reply_markup=b.as_markup())
    await c.answer()

@router.callback_query(F.data.startswith("g:"))
async def pick_grade(c: CallbackQuery):
    grade = int(c.data.split(":")[1])
    books = [b for b in BOOKS if b["grade"] == grade]
    if len(books) == 1:
        return await show_topics(c, books[0]["id"])
    b = InlineKeyboardBuilder()
    for bk in books:
        b.button(text=f'📘 {bk["subject"]}', callback_data=f'b:{bk["id"]}')
    b.button(text="🏠 Bosh sahifa", callback_data="home")
    b.adjust(1)
    await c.message.edit_text(f"<b>{grade}-sinf.</b> Qaysi fan?", reply_markup=b.as_markup())
    await c.answer()

@router.callback_query(F.data.startswith("b:"))
async def pick_book(c: CallbackQuery):
    await show_topics(c, int(c.data.split(":")[1]))

async def show_topics(c: CallbackQuery, bid: int):
    bk = BOOKS[bid]
    lines = [f'<b>{bk["grade"]}-sinf · {esc(bk["subject"])}</b>\nMavzuni tanlang (raqamni bosing):\n']
    b = InlineKeyboardBuilder()
    for i, t in enumerate(bk["topics"]):
        lines.append(f'<b>{esc(t["no"])}.</b> {esc(t["title"])}')
        b.button(text=t["no"], callback_data=f"t:{bid}:{i}")
    b.adjust(5)
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="home"))
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "…"
    await c.message.edit_text(text, reply_markup=b.as_markup())
    await c.answer()

@router.callback_query(F.data.startswith("t:"))
async def pick_topic(c: CallbackQuery):
    _, bid, i = c.data.split(":"); bid, i = int(bid), int(i)
    bk, t = BOOKS[bid], BOOKS[bid]["topics"][i]
    start_generation(c.from_user.id, bid, i)          # foydalanuvchi o'qiyotganda test tayyorlanaveradi
    text = (f'<b>{esc(t["no"])}-mavzu. {esc(t["title"])}</b>\n\n'
            f'📖 <b>Zarur adabiyot:</b> {esc(bk["book"])}, {t["pages"][0]}–{t["pages"][1]}-betlar.\n\n'
            f'Shu mavzudan <b>{ql.TOTAL_QUESTIONS} ta qiyin test</b> tuzaman. Har savolda 4 ta variant bor.\n\n<b>Tayyormisiz?</b>')
    b = InlineKeyboardBuilder()
    b.button(text="✅ Ha, tayyorman", callback_data=f"go:{bid}:{i}")
    b.button(text="⬅️ Mavzularga qaytish", callback_data=f"b:{bid}")
    b.adjust(1)
    await c.message.edit_text(text, reply_markup=b.as_markup())
    await c.answer()

# ------------------------------------------------------------------ test jarayoni
@router.callback_query(F.data.startswith("go:"))
async def go(c: CallbackQuery):
    _, bid, i = c.data.split(":"); bid, i = int(bid), int(i)
    uid = c.from_user.id
    await c.answer()
    await c.message.edit_text("⏳ Savollar tayyorlanmoqda, bir oz kuting (20–60 soniya)…")
    p = pending.get(uid)
    task = p[2] if p and p[0] == bid and p[1] == i and not p[2].cancelled() else start_generation(uid, bid, i)
    try:
        qs = await asyncio.wait_for(asyncio.shield(task), timeout=240)
    except Exception:
        logging.exception("Test tuzishda xato")
        pending.pop(uid, None)
        b = InlineKeyboardBuilder()
        b.button(text="🔁 Qayta urinish", callback_data=f"go:{bid}:{i}")
        b.button(text="⬅️ Mavzularga qaytish", callback_data=f"b:{bid}")
        b.adjust(1)
        return await c.message.edit_text("😔 Testni tayyorlab bo'lmadi. Birozdan keyin qayta urinib ko'ring.", reply_markup=b.as_markup())
    pending.pop(uid, None)
    qs = [ql.shuffled(q) for q in qs]; random.shuffle(qs)
    sessions[uid] = {"bid": bid, "i": i, "qs": qs, "pos": 0, "answers": []}
    await show_question(c.message, uid)

def question_text(s, extra=""):
    q = s["qs"][s["pos"]]
    opts = "\n".join(f"<b>{LETTERS[k]})</b> {esc(o)}" for k, o in enumerate(q["options"]))
    return f'<b>Savol {s["pos"] + 1}/{len(s["qs"])}</b>\n\n{esc(q["q"])}\n\n{opts}{extra}'

async def show_question(msg, uid):
    s = sessions[uid]
    b = InlineKeyboardBuilder()
    for k in range(4):
        b.button(text=LETTERS[k], callback_data=f'a:{s["pos"]}:{k}')
    b.adjust(4)
    await msg.edit_text(question_text(s), reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("a:"))
async def answer(c: CallbackQuery):
    s = sessions.get(c.from_user.id)
    _, pos, k = c.data.split(":"); pos, k = int(pos), int(k)
    if not s or s["pos"] != pos or len(s["answers"]) != pos:
        return await c.answer("Bu savolga javob berilgan yoki test tugagan.", show_alert=True)
    q = s["qs"][pos]
    s["answers"].append(k)
    if k == q["answer"]:
        extra = "\n\n✅ <b>To'g'ri!</b>"
    else:
        extra = f'\n\n❌ <b>Xato.</b> To\'g\'ri javob: <b>{LETTERS[q["answer"]]}) {esc(q["options"][q["answer"]])}</b>'
        if q["explanation"]:
            extra += f'\n💡 {esc(q["explanation"])}'
    b = InlineKeyboardBuilder()
    last = pos + 1 == len(s["qs"])
    b.button(text="📊 Natijani ko'rish" if last else "Keyingisi ➡️", callback_data=f"n:{pos}")
    await c.message.edit_text(question_text(s, extra), reply_markup=b.as_markup())
    await c.answer()

@router.callback_query(F.data.startswith("n:"))
async def nxt(c: CallbackQuery):
    s = sessions.get(c.from_user.id)
    pos = int(c.data.split(":")[1])
    if not s or s["pos"] != pos or len(s["answers"]) != pos + 1:
        return await c.answer()
    s["pos"] += 1
    await c.answer()
    if s["pos"] >= len(s["qs"]):
        return await finish(c)
    await show_question(c.message, c.from_user.id)

async def finish(c: CallbackQuery):
    uid = c.from_user.id
    s = sessions.pop(uid)
    bk, t = BOOKS[s["bid"]], BOOKS[s["bid"]]["topics"][s["i"]]
    total = len(s["qs"])
    wrong = [{"q": q["q"], "correct": q["options"][q["answer"]], "chosen": q["options"][k], "exp": q["explanation"]}
             for q, k in zip(s["qs"], s["answers"]) if k != q["answer"]]
    correct = total - len(wrong)
    percent = round(correct * 100 / total)
    STORE.add_result(uid, bk["key"], t["no"], correct, total)
    await c.message.edit_text(f'✅ Test tugadi: <b>{esc(t["no"])}-mavzu. {esc(t["title"])}</b>')
    text = (f"📊 <b>Natijangiz</b>\n\n✅ To'g'ri: <b>{correct}</b>\n❌ Xato: <b>{len(wrong)}</b>\n"
            f"📈 Foiz: <b>{percent}%</b>\n\n{tier(percent)}")
    fb = await ql.ai_feedback(bk, t, wrong, percent)
    if fb:
        text += f"\n\n🧑‍🏫 <b>Ustoz fikri:</b>\n{esc(fb)}"
    if wrong:
        text += "\n\n<b>Xato qilgan savollaringiz:</b>"
        for n, w in enumerate(wrong[:10], 1):
            text += f'\n\n{n}. {esc(w["q"])}\n   ✔️ To\'g\'ri javob: <b>{esc(w["correct"])}</b>'
            if w["exp"]:
                text += f'\n   💡 {esc(w["exp"])}'
        if len(wrong) > 10:
            text += f"\n\n…yana {len(wrong) - 10} ta xato bor."
    text += f"\n\n{WHY_READ}\n\n📖 Qayta o'qing: {esc(bk['book'])}, {t['pages'][0]}–{t['pages'][1]}-betlar."
    b = InlineKeyboardBuilder()
    b.button(text="🔁 Yangi savollar bilan qayta urinish", callback_data=f't:{s["bid"]}:{s["i"]}')
    b.button(text="📚 Boshqa mavzu", callback_data=f'b:{s["bid"]}')
    b.button(text="🏠 Bosh sahifa", callback_data="home")
    b.adjust(1)
    await send_long(c.message, text, b.as_markup())

async def main():
    bot = Bot(os.environ["BOT_TOKEN"], default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(); dp.include_router(router)
    logging.info("Bot ishga tushdi. Darsliklar: %s", [(b["grade"], b["subject"], len(b["topics"])) for b in BOOKS])
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
