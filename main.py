import asyncio
import logging
import base64
import os  # ✅ Обязательно добавь!
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from huggingface_hub import InferenceClient

# --- НАСТРОЙКИ (из переменных окружения) ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")      # ✅ Из настроек Render
HF_API_KEY = os.getenv("HF_API_KEY")              # ✅ Из настроек Render

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

hf_client = InferenceClient(token=HF_API_KEY)

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
    waiting_for_input = State()  # Ждём фото ИЛИ текст
    waiting_for_text = State()   # Только текст (для перефразирования/сокращения)

# --- ФУНКЦИИ AI ---

async def ask_hf_text(prompt: str):
    """Текст через Hugging Face"""
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
    """Фото через Hugging Face Vision"""
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

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бесплатный бот-помощник для учёбы. 🚀\n\n"
        "👨‍💻 **Создатель бота:** @negative1431\n\n"
        "Я умею:\n"
        "📸 **Решение задания** — ответ и решение (фото или текст)\n"
        "📖 **Объяснение задания** — подробный разбор (фото или текст)\n"
        "✏️ **Перефразировать** — изменить текст, сохранив смысл\n"
        "✂️ **Сократить** — оставить только главное\n\n"
        "Жми на кнопку и отправляй фото или текст!",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

# 1. 📸 РЕШЕНИЕ ЗАДАНИЯ
@dp.message(F.text.in_({"📸 Решение задания"}))
async def start_solution_mode(message: types.Message, state: FSMContext):
    await state.update_data(mode="solution")
    await state.set_state(TaskAction.waiting_for_input)
    await message.answer("📷 Отправь фото задания **или напиши текст задачи**:", parse_mode="Markdown")

# 2. 📖 ОБЪЯСНЕНИЕ ЗАДАНИЯ
@dp.message(F.text.in_({"📖 Объяснение задания"}))
async def start_explanation_mode(message: types.Message, state: FSMContext):
    await state.update_data(mode="explanation")
    await state.set_state(TaskAction.waiting_for_input)
    await message.answer("📷 Отправь фото задания **или напиши текст задачи**:", parse_mode="Markdown")

# 3. ✏️ ПЕРЕФРАЗИРОВАТЬ
@dp.message(F.text.in_({"✏️ Перефразировать"}))
async def start_paraphrase_mode(message: types.Message, state: FSMContext):
    await state.update_data(mode="paraphrase")
    await state.set_state(TaskAction.waiting_for_text)
    await message.answer("✍️ Отправь текст, который нужно перефразировать:")

# 4. ✂️ СОКРАТИТЬ
@dp.message(F.text.in_({"✂️ Сократить"}))
async def start_shorten_mode(message: types.Message, state: FSMContext):
    await state.update_data(mode="shorten")
    await state.set_state(TaskAction.waiting_for_text)
    await message.answer("✍️ Отправь текст, который нужно сократить:")

# 5. ОБРАБОТКА ФОТО (для решений)
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
        prompt = """Реши эту задачу. 
ВАЖНО: 
- Пиши формулы ОБЫЧНЫМ текстом (например: 3/4, а не \\frac{3}{4})
- Не используй LaTeX, скобки $$, \\(, \\)
- Пиши просто: 1+1=2, x^2, sqrt(5)
Напиши ТОЛЬКО ответ и краткое решение."""
    elif mode == "explanation":
        prompt = """Реши эту задачу. Дай ПОДРОБНОЕ объяснение каждого шага.
ВАЖНО:
- Пиши формулы ОБЫЧНЫМ текстом (например: 3/4, а не \\frac{3}{4})
- Не используй LaTeX, скобки $$, \\(, \\)
- Пиши просто: 1+1=2, x^2, sqrt(5)
Чтобы школьник понял логику решения."""
    else:
        prompt = "Реши эту задачу."
    
    result = await ask_hf_image(prompt, image_data)
    await message.answer(result)  # ✅ Без parse_mode
    await state.clear()

# 6. ОБРАБОТКА ТЕКСТА (для решений заданий)
@dp.message(TaskAction.waiting_for_input, F.text)
async def handle_task_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("mode")
    user_text = message.text
    
    await message.answer("🤔 Думаю...")
    
    if mode == "solution":
        prompt = f"""Реши эту задачу.
ВАЖНО:
- Пиши формулы ОБЫЧНЫМ текстом (например: 3/4, а не \\frac{{3}}{{4}})
- Не используй LaTeX, скобки $$, \\(, \\)
- Пиши просто: 1+1=2, x^2, sqrt(5)
Напиши ТОЛЬКО ответ и краткое решение.
Задача: {user_text}"""
    elif mode == "explanation":
        prompt = f"""Реши эту задачу. Дай ПОДРОБНОЕ объяснение каждого шага.
ВАЖНО:
- Пиши формулы ОБЫЧНЫМ текстом (например: 3/4, а не \\frac{{3}}{{4}})
- Не используй LaTeX, скобки $$, \\(, \\)
- Пиши просто: 1+1=2, x^2, sqrt(5)
Чтобы школьник понял логику решения.
Задача: {user_text}"""
    else:
        prompt = f"Реши эту задачу: {user_text}"
    
    result = await ask_hf_text(prompt)
    await message.answer(result)  # ✅ Без parse_mode
    await state.clear()

# 7. ОБРАБОТКА ТЕКСТА (для перефразирования/сокращения)
@dp.message(TaskAction.waiting_for_text, F.text)
async def handle_text_action(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("mode")
    user_text = message.text
    
    await message.answer("⏳ Обрабатываю...")
    
    if mode == "paraphrase":
        prompt = f"Перефразируй этот текст, сохранив смысл: {user_text}"
    elif mode == "shorten":
        prompt = f"Сократи этот текст, оставив суть: {user_text}"
    else:
        prompt = user_text
        
    result = await ask_hf_text(prompt)
    await message.answer(result)  # ✅ Без parse_mode
    await state.clear()

# 8. ОБЫЧНЫЕ СООБЩЕНИЯ (не в режиме)
@dp.message(F.photo)
async def handle_regular_photo(message: types.Message):
    await message.answer(
        "📸 Выберите режим работы с заданием:\n"
        "— **Решение** — только ответ\n"
        "— **Объяснение** — подробный разбор\n\n"
        "Нажмите на кнопку в меню ниже!",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(F.text)
async def handle_regular_text(message: types.Message):
    await message.answer(
        "Выберите действие в меню 👇",
        reply_markup=get_main_keyboard()
    )

# --- ЗАПУСК ---
async def main():
    try:
        await asyncio.to_thread(
            hf_client.chat_completion,
            model=TEXT_MODEL,
            messages=[{"role": "user", "content": "Test"}]
        )
        print("✅ Hugging Face подключен!")
    except Exception as e:
        print(f"❌ Hugging Face ошибка: {e}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
