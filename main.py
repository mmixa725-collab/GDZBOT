import asyncio
import logging
import base64
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from huggingface_hub import InferenceClient
from aiohttp import web

# --- НАСТРОЙКИ ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
HF_API_KEY = os.getenv("HF_API_KEY")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

hf_client = InferenceClient(
    token=HF_API_KEY,
    base_url="https://router.huggingface.co"
)

logging.basicConfig(level=logging.INFO)

# --- МОДЕЛИ ---
TEXT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
VISION_MODEL = "meta-llama/Llama-3.2-11B-Vision-Instruct"

# --- КЛАВИАТУРА ---
def get_main_keyboard():
    kb = [
        [KeyboardButton(text="📸 Решение задания"), KeyboardButton(text="📖 Объяснение задания")],
        [KeyboardButton(text="✏️ Перефразировать"), KeyboardButton(text="✂️ Сократить")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- СОСТОЯНИЯ ---
class TaskAction(StatesGroup):
    waiting_for_input = State()
    waiting_for_text = State()

# --- ФУНКЦИИ AI ---

async def ask_hf_text(prompt: str):
    try:
        response = await asyncio.to_thread(
            hf_client.chat_completion,
            model=TEXT_MODEL,
            messages=[
                {"role": "system", "content": "Ты полезный помощник для школьников. Объясняй понятно."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ Ошибка: {e}"

async def ask_hf_image(prompt: str, image_bytes: bytes):
    try:
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        response = await asyncio.to_thread(
            hf_client.chat_completion,
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"image/jpeg;base64,{image_base64}"}}
                    ]
                }
            ],
            max_tokens=1500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ Ошибка обработки фото: {e}"

# --- HTTP СЕРВЕР ДЛЯ RENDER ---
async def health_handler(request):
    return web.json_response({"status": "ok"})

async def start_http_server():
    app = web.Application()
    app.router.add_get('/healthz', health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10000)
    await site.start()
    print("✅ HTTP-сервер запущен на порту 10000")

# --- ХЕНДЛЕРЫ (ВАЖНЫЙ ПОРЯДОК!) ---

# 1. Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Я бесплатный бот-помощник для учёбы. 🚀\n\n"
        "👨‍💻 **Создатель бота:** @negative1431\n\n"
        "Жми на кнопку!",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

# 2. Обработка фото в режиме задания
@dp.message(TaskAction.waiting_for_input, F.photo)
async def handle_task_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("mode")
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    photo_bytes = await bot.download_file(file.file_path)
    image_data = photo_bytes.read()

    await message.answer("🤔 Думаю...")
    
    if mode == "solution":
        prompt = "Реши эту задачу. Пиши формулы обычным текстом (3/4, x^2). Только ответ и краткое решение."
    elif mode == "explanation":
        prompt = "Реши эту задачу. Пиши формулы обычным текстом. Дай подробное объяснение каждого шага."
    else:
        prompt = "Реши эту задачу."
    
    result = await ask_hf_image(prompt, image_data)
    await message.answer(result)
    await state.clear()

# 3. Обработка текста в режиме задания
@dp.message(TaskAction.waiting_for_input, F.text)
async def handle_task_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("mode")
    user_text = message.text
    
    await message.answer("🤔 Думаю...")
    
    if mode == "solution":
        prompt = f"Реши эту задачу. Пиши формулы обычным текстом. Только ответ. Задача: {user_text}"
    elif mode == "explanation":
        prompt = f"Реши эту задачу. Пиши формулы обычным текстом. Подробное объяснение. Задача: {user_text}"
    else:
        prompt = f"Реши эту задачу: {user_text}"
    
    result = await ask_hf_text(prompt)
    await message.answer(result)
    await state.clear()

# 4. Обработка текста в режиме перефразирования/сокращения
@dp.message(TaskAction.waiting_for_text, F.text)
async def handle_text_action(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("mode")
    user_text = message.text
    
    await message.answer("⏳ Обрабатываю...")
    
    if mode == "paraphrase":
        prompt = f"Перефразируй этот текст: {user_text}"
    elif mode == "shorten":
        prompt = f"Сократи этот текст: {user_text}"
    else:
        prompt = user_text
        
    result = await ask_hf_text(prompt)
    await message.answer(result)
    await state.clear()

# 5. Обработка кнопок меню (ПОСЛЕ хендлеров состояний!)
@dp.message(F.text)
async def handle_menu_buttons(message: types.Message, state: FSMContext):
    text = message.text
    
    if text == "📸 Решение задания":
        await state.update_data(mode="solution")
        await state.set_state(TaskAction.waiting_for_input)
        await message.answer("📷 Отправь фото или текст задачи:")
        
    elif text == "📖 Объяснение задания":
        await state.update_data(mode="explanation")
        await state.set_state(TaskAction.waiting_for_input)
        await message.answer("📷 Отправь фото или текст задачи:")
        
    elif text == "✏️ Перефразировать":
        await state.update_data(mode="paraphrase")
        await state.set_state(TaskAction.waiting_for_text)
        await message.answer("✍️ Отправь текст:")
        
    elif text == "✂️ Сократить":
        await state.update_data(mode="shorten")
        await state.set_state(TaskAction.waiting_for_text)
        await message.answer("✍️ Отправь текст:")

# 6. Обычные фото (без режима)
@dp.message(F.photo)
async def handle_regular_photo(message: types.Message):
    await message.answer(
        "Выберите режим в меню!",
        reply_markup=get_main_keyboard()
    )

# --- ЗАПУСК ---
async def main():
    print("⏳ Ожидание 5 секунд...")
    await asyncio.sleep(5)
    
    try:
        await asyncio.to_thread(
            hf_client.chat_completion,
            model=TEXT_MODEL,
            messages=[{"role": "user", "content": "Test"}]
        )
        print("✅ Hugging Face подключен!")
    except Exception as e:
        print(f"❌ Hugging Face ошибка: {e}")
    
    await start_http_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
