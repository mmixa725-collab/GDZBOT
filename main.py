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

# Проверка наличия токенов
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не установлен!")
if not HF_API_KEY:
    raise ValueError("❌ HF_API_KEY не установлен!")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Создаем клиент без base_url (используется стандартный)
hf_client = InferenceClient(token=HF_API_KEY)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        logger.info(f"Отправка текстового запроса к {TEXT_MODEL}")
        
        response = await asyncio.to_thread(
            hf_client.chat_completion,
            model=TEXT_MODEL,
            messages=[
                {"role": "system", "content": "Ты полезный помощник для школьников. Объясняй понятно, используй простые примеры."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1500,
            temperature=0.7
        )
        
        if response and response.choices:
            return response.choices[0].message.content
        else:
            return "❌ Не удалось получить ответ от модели"
            
    except Exception as e:
        logger.error(f"Ошибка в ask_hf_text: {type(e).__name__}: {str(e)}")
        return f"⚠️ Ошибка при обработке текста: {str(e)}"

async def ask_hf_image(prompt: str, image_bytes: bytes):
    try:
        logger.info(f"Отправка запроса с изображением к {VISION_MODEL}")
        
        # Правильное кодирование изображения в base64
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        # Формируем правильный data URL
        image_data_url = f"data:image/jpeg;base64,{image_base64}"
        
        response = await asyncio.to_thread(
            hf_client.chat_completion,
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url", 
                            "image_url": {
                                "url": image_data_url  # Исправлено: теперь правильный data URL
                            }
                        }
                    ]
                }
            ],
            max_tokens=1500,
            temperature=0.7
        )
        
        if response and response.choices:
            return response.choices[0].message.content
        else:
            return "❌ Не удалось получить ответ от модели"
            
    except Exception as e:
        logger.error(f"Ошибка в ask_hf_image: {type(e).__name__}: {str(e)}")
        return f"⚠️ Ошибка при обработке изображения: {str(e)}"

# --- HTTP СЕРВЕР ДЛЯ RENDER ---
async def health_handler(request):
    return web.json_response({"status": "ok", "timestamp": asyncio.get_event_loop().time()})

async def start_http_server():
    app = web.Application()
    app.router.add_get('/health', health_handler)
    app.router.add_get('/healthz', health_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Пробуем разные порты
    ports = [10000, 8080, 8000]
    for port in ports:
        try:
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            logger.info(f"✅ HTTP-сервер запущен на порту {port}")
            return
        except OSError:
            logger.warning(f"Порт {port} занят, пробуем следующий...")
            continue
    
    logger.warning("⚠️ Не удалось запустить HTTP-сервер, но бот продолжает работу")

# --- ХЕНДЛЕРЫ ---

# 1. Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🌟 *Привет! Я бесплатный бот-помощник для учёбы!* 🌟\n\n"
        "📚 Я помогу тебе:\n"
        "• Решать задачи по фото или тексту\n"
        "• Объяснять сложные темы\n"
        "• Перефразировать и сокращать текст\n\n"
        "👨‍💻 *Создатель:* @negative1431\n\n"
        "👇 *Выбери действие:*",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

# 2. Обработка фото в режиме задания
@dp.message(TaskAction.waiting_for_input, F.photo)
async def handle_task_photo(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        mode = data.get("mode")
        
        # Получаем фото
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file.file_path)
        image_data = photo_bytes.read()

        await message.answer("🤔 Анализирую изображение...")
        
        # Выбираем промпт в зависимости от режима
        if mode == "solution":
            prompt = "Реши эту задачу. Используй простые объяснения. Если есть формулы, пиши их в виде текста (например: x^2, 3/4). Дай краткое решение."
        elif mode == "explanation":
            prompt = "Реши эту задачу и подробно объясни каждый шаг решения. Используй простые аналогии. Формулы пиши текстом."
        else:
            prompt = "Что изображено на этой картинке? Если это задача - реши её."
        
        result = await ask_hf_image(prompt, image_data)
        await message.answer(result, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Ошибка в handle_task_photo: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")
    finally:
        await state.clear()

# 3. Обработка текста в режиме задания
@dp.message(TaskAction.waiting_for_input, F.text)
async def handle_task_text(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        mode = data.get("mode")
        user_text = message.text
        
        await message.answer("🤔 Думаю над решением...")
        
        # Выбираем промпт в зависимости от режима
        if mode == "solution":
            prompt = f"Реши эту задачу. Используй простые объяснения. Задача: {user_text}"
        elif mode == "explanation":
            prompt = f"Реши эту задачу и подробно объясни каждый шаг. Задача: {user_text}"
        else:
            prompt = f"Реши эту задачу: {user_text}"
        
        result = await ask_hf_text(prompt)
        await message.answer(result, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Ошибка в handle_task_text: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")
    finally:
        await state.clear()

# 4. Обработка текста в режиме перефразирования/сокращения
@dp.message(TaskAction.waiting_for_text, F.text)
async def handle_text_action(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        mode = data.get("mode")
        user_text = message.text
        
        await message.answer("⏳ Обрабатываю текст...")
        
        if mode == "paraphrase":
            prompt = f"Перефразируй этот текст, сохраняя смысл, но используя другие слова: {user_text}"
        elif mode == "shorten":
            prompt = f"Сократи этот текст, сохраняя основную мысль: {user_text}"
        else:
            prompt = user_text
            
        result = await ask_hf_text(prompt)
        await message.answer(result, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Ошибка в handle_text_action: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")
    finally:
        await state.clear()

# 5. Обработка кнопок меню
@dp.message(F.text)
async def handle_menu_buttons(message: types.Message, state: FSMContext):
    text = message.text
    
    if text == "📸 Решение задания":
        await state.update_data(mode="solution")
        await state.set_state(TaskAction.waiting_for_input)
        await message.answer(
            "📤 *Отправь мне:*\n"
            "• 📷 Фото задачи\n"
            "• 📝 Текст задачи\n\n"
            "Я решу её максимально подробно!",
            parse_mode="Markdown"
        )
        
    elif text == "📖 Объяснение задания":
        await state.update_data(mode="explanation")
        await state.set_state(TaskAction.waiting_for_input)
        await message.answer(
            "📤 *Отправь мне:*\n"
            "• 📷 Фото с заданием\n"
            "• 📝 Текст задания\n\n"
            "Я объясню каждый шаг решения!",
            parse_mode="Markdown"
        )
        
    elif text == "✏️ Перефразировать":
        await state.update_data(mode="paraphrase")
        await state.set_state(TaskAction.waiting_for_text)
        await message.answer(
            "✍️ *Отправь текст,* который нужно перефразировать:",
            parse_mode="Markdown"
        )
        
    elif text == "✂️ Сократить":
        await state.update_data(mode="shorten")
        await state.set_state(TaskAction.waiting_for_text)
        await message.answer(
            "✍️ *Отправь текст,* который нужно сократить:",
            parse_mode="Markdown"
        )
    else:
        # Если текст не соответствует кнопкам
        await message.answer(
            "Пожалуйста, используй кнопки меню для выбора действия 👇",
            reply_markup=get_main_keyboard()
        )

# 6. Обработка фото без режима
@dp.message(F.photo)
async def handle_regular_photo(message: types.Message):
    await message.answer(
        "📸 Сначала выбери действие в меню:\n"
        "• 📸 Решение задания\n"
        "• 📖 Объяснение задания",
        reply_markup=get_main_keyboard()
    )

# 7. Обработка всех остальных сообщений
@dp.message()
async def handle_other(message: types.Message):
    await message.answer(
        "Я понимаю только команды из меню 👇\n"
        "Пожалуйста, воспользуйся кнопками!",
        reply_markup=get_main_keyboard()
    )

# --- ЗАПУСК ---
async def main():
    logger.info("🚀 Запуск бота...")
    
    # Небольшая задержка для инициализации
    await asyncio.sleep(2)
    
    # Проверка подключения к Hugging Face
    try:
        logger.info("Проверка подключения к Hugging Face...")
        test_response = await asyncio.to_thread(
            hf_client.chat_completion,
            model=TEXT_MODEL,
            messages=[{"role": "user", "content": "Тестовое сообщение. Ответь 'ok' если работаешь."}],
            max_tokens=10
        )
        logger.info("✅ Hugging Face успешно подключен!")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к Hugging Face: {e}")
        logger.warning("⚠️ Бот продолжит работу, но могут быть проблемы с запросами")
    
    # Запускаем HTTP сервер для Render
    await start_http_server()
    
    # Запускаем бота
    logger.info("🤖 Бот начинает polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
