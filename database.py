import aiosqlite

DB_NAME = "lawyer_bot.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                language TEXT DEFAULT 'ru',
                credits INTEGER DEFAULT 2
            )
        """)
        await db.commit()

async def get_or_create_user(user_id: int, default_lang: str = 'ru'):
    lang = 'ru' if default_lang.startswith('ru') else 'en'
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT language, credits FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"lang": row[0], "credits": row[1]}
            
            await db.execute("INSERT INTO users (user_id, language, credits) VALUES (?, ?, ?)", (user_id, lang, 2))
            await db.commit()
            return {"lang": lang, "credits": 2}

async def set_user_language(user_id: int, lang: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
        await db.commit()

async def deduct_credit(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET credits = credits - 1 WHERE user_id = ? AND credits > 0", (user_id,))
        await db.commit()

async def add_credits(user_id: int, amount: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()
