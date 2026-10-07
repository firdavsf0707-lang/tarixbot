# Tarix test boti

## Ishga tushirish
1. Python 3.10+ o'rnatilgan bo'lsin.
2. `pip install -r requirements.txt`
3. `.env.example` faylini `.env` ga o'zgartiring va BOT_TOKEN hamda GROQ_API_KEY ni yozing.
4. `python bot.py`

## Tuzilishi
- `bot.py` — Telegram menyulari va test jarayoni
- `quizlib.py` — AI (Groq) bilan test tuzish, qiyinlik darajalari, natijalarni saqlash
- `data/` — 8 ta darslik (5–9-sinf), mavzular bo'yicha ajratilgan matn

## Sozlash
- Qiyinlik: `quizlib.py` ichidagi `LEVELS` (sinf bo'yicha).
- Savollar soni: `TOTAL_QUESTIONS`.
- Model: `.env` ichida `GROQ_MODEL`.
- Yangi darslik: `data/` ga `gradeN_nom.json` qo'shing (bot o'zi topadi).
