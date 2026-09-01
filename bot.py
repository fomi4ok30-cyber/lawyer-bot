import os
import io
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import (
    LabeledPrice, 
    PreCheckoutQuery, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from google import genai
from pypdf import PdfReader
from docx import Document

from database import init_db, get_or_create_user, set_user_language, deduct_credit, add_credits

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

TARIFFS = {
    "pack_5": ("Экспресс (5 консультаций)", "Express (5 Consultations)", 5, 150),
    "pack_15": ("Стандарт (15 аудитов/вопросов)", "Standard (15 Audits/Inquiries)", 15, 390),
    "pack_50": ("Бизнес Пакет (50 запросов)", "Business Pro (50 Requests)", 50, 990),
}

MESSAGES = {
    'ru': {
        'welcome': (
            "⚖️ **Добро пожаловать в ИИ-Адвокат!**\n\n"
            "Я ваш персональный юридический ассистент на базе Google Gemini.\n"
            "• Правовые консультации (РФ и международное право)\n"
            "• Аудит договоров и документов (PDF, DOCX, TXT)\n"
            "• Анализ рисков и помощь в составлении претензий\n\n"
            "🎁 У вас есть **{credits} бесплатные консультации**.\n"
            "Отправьте ваш вопрос текстом или прикрепите файл документа."
        ),
        'no_credits': "⚠️ У вас закончились консультации. Выберите пакет пополнения через Telegram Stars:",
        'lang_btn': "🌐 Change to English",
        'analyzing_doc': "⏳ Читаю и анализирую ваш документ...",
        'error': "⚠️ Произошла ошибка при обработке. Попробуйте еще раз."
    },
    'en': {
        'welcome': (
            "⚖️ **Welcome to AI Lawyer!**\n\n"
            "I am your personal legal assistant powered by Google Gemini.\n"
            "• Legal consultations (international & civil law)\n"
            "• Contract analysis & risk audit (PDF, DOCX, TXT)\n"
            "• Risk detection and dispute assistance\n\n"
            "🎁 You have **{credits} free consultations**.\n"
            "Send your legal inquiry or attach a document to start."
        ),
        'no_credits': "⚠️ You have run out of consultations. Choose a package with Telegram Stars:",
        'lang_btn': "🌐 Переключить на Русский",
        'analyzing_doc': "⏳ Reading and analyzing your document...",
        'error': "⚠️ An error occurred. Please try again later."
    }
}

SYSTEM_PROMPT = """
You are a top-tier international legal advisor and attorney AI.
Core rules:
1. Provide legally grounded, structured, and clear legal guidance.
2. When analyzing contracts/documents: identify high-risk clauses, hidden liabilities, and missing protections.
3. Always respond in the language of the user's query or document (Russian or English).
4. Maintain a clear format: Summary -> Legal Analysis -> Risks & Loopholes -> Actionable Recommendations.
5. Add a brief legal disclaimer that advice is for analytical and educational purposes.
"""

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def get_main_keyboard(lang: str):
    buttons = []
    for plan_id, plan_data in TARIFFS.items():
        title = plan_data[0] if lang == 'ru' else plan_data[1]
        stars = plan_data[3]
        buttons.append([InlineKeyboardButton(text=f"⭐ {title} — {stars} Stars", callback_data=f"buy:{plan_id}")])
    buttons.append([InlineKeyboardButton(text=MESSAGES[lang]['lang_btn'], callback_data="toggle_lang")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    user_lang = message.from_user.language_code or 'ru'
    user = await get_or_create_user(message.from_user.id, user_lang)
    lang = user['lang']
    text = MESSAGES[lang]['welcome'].format(credits=user['credits'])
    await message.answer(text, reply_markup=get_main_keyboard(lang), parse_mode="Markdown")

@dp.callback_query(F.data == "toggle_lang")
async def toggle_lang_handler(call: types.CallbackQuery):
    user = await get_or_create_user(call.from_user.id)
    new_lang = 'en' if user['lang'] == 'ru' else 'ru'
    await set_user_language(call.from_user.id, new_lang)
    await call.answer("Language updated!")
    text = MESSAGES[new_lang]['welcome'].format(credits=user['credits'])
    await call.message.edit_text(text, reply_markup=get_main_keyboard(new_lang), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("buy:"))
async def send_invoice_handler(call: types.CallbackQuery):
    plan_id = call.data.split(":")[1]
    if plan_id not in TARIFFS:
        return
    plan = TARIFFS[plan_id]
    user = await get_or_create_user(call.from_user.id)
    lang = user['lang']
    title = plan[0] if lang == 'ru' else plan[1]
    stars = plan[3]
    credits_count = plan[2]
    desc = f"Пакет на {credits_count} консультаций" if lang == 'ru' else f"Package of {credits_count} consultations"

    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title=title,
        description=desc,
        payload=f"{plan_id}:{credits_count}",
        currency="XTR",
        prices=[LabeledPrice(label=title, amount=stars)],
        provider_token=""
    )
    await call.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    payload = message.successful_payment.invoice_payload
    credits_to_add = int(payload.split(":")[1])
    await add_credits(message.from_user.id, credits_to_add)
    user = await get_or_create_user(message.from_user.id)
    success_msg = f"✅ Оплата прошла! Начислено {credits_to_add} консультаций." if user['lang'] == 'ru' else f"✅ Payment successful! {credits_to_add} consultations added."
    await message.answer(success_msg)

@dp.message(F.text)
async def handle_text(message: types.Message):
    user = await get_or_create_user(message.from_user.id)
    lang = user['lang']
    if user['credits'] <= 0:
        await message.answer(MESSAGES[lang]['no_credits'], reply_markup=get_main_keyboard(lang))
        return
        
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        prompt_with_sys = f"{SYSTEM_PROMPT}\n\nUser Question: {message.text}"
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt_with_sys
        )
        await deduct_credit(message.from_user.id)
        left = user['credits'] - 1
        credits_notice = f"\n\n_(Осталось консультаций: {left})_" if lang == 'ru' else f"\n\n_(Consultations left: {left})_"
        try:
            await message.answer(response.text + credits_notice, parse_mode="Markdown")
        except Exception:
            await message.answer(response.text + credits_notice)
    except Exception as e:
        print(f"DEBUG GEMINI ERROR: {e}")
        await message.answer(MESSAGES[lang]['error'])

@dp.message(F.document)
async def handle_document(message: types.Message):
    user = await get_or_create_user(message.from_user.id)
    lang = user['lang']
    if user['credits'] <= 0:
        await message.answer(MESSAGES[lang]['no_credits'], reply_markup=get_main_keyboard(lang))
        return

    doc = message.document
    await message.answer(MESSAGES[lang]['analyzing_doc'])
    file_io = io.BytesIO()
    file = await bot.get_file(doc.file_id)
    await bot.download_file(file.file_path, destination=file_io)
    file_io.seek(0)
    
    extracted_text = ""
    try:
        if doc.file_name.endswith('.pdf'):
            reader = PdfReader(file_io)
            for page in reader.pages:
                extracted_text += (page.extract_text() or "") + "\n"
        elif doc.file_name.endswith('.docx'):
            document = Document(file_io)
            extracted_text = "\n".join([p.text for p in document.paragraphs])
        elif doc.file_name.endswith('.txt'):
            extracted_text = file_io.read().decode('utf-8', errors='ignore')
            
        if not extracted_text.strip():
            await message.answer("⚠️ Не удалось прочитать текст документа. Отправьте файл без сканов/картинок.")
            return

        prompt = f"{SYSTEM_PROMPT}\n\nPerform a comprehensive legal audit on this document:\n\n{extracted_text[:15000]}"
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt
        )
        await deduct_credit(message.from_user.id)
        left = user['credits'] - 1
        credits_notice = f"\n\n_(Осталось консультаций: {left})_" if lang == 'ru' else f"\n\n_(Consultations left: {left})_"
        try:
            await message.answer(response.text + credits_notice, parse_mode="Markdown")
        except Exception:
            await message.answer(response.text + credits_notice)
    except Exception as e:
        print(f"DEBUG GEMINI DOC ERROR: {e}")
        await message.answer(MESSAGES[lang]['error'])

async def health_check(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
