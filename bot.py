"""
VoiceScribe Bot — Telegram-бот для транскрибации голосовых сообщений
Автор: Даниил Рашидов
Курс: Промпт-инженер (Zerocoder)
"""

import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI

# Загружаем переменные из .env (для локальной разработки)
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация OpenAI клиента
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Системный промпт для генерации тезисов
SYSTEM_PROMPT = """Ты — ассистент для обработки транскрибированных голосовых сообщений.

Твоя задача — выделить ключевые тезисы из текста.

Правила:
- Количество тезисов: от 3 до 7 (зависит от объёма информации)
- Каждый тезис — одна законченная мысль
- Порядок — по логике изложения в тексте
- Без интерпретаций и домыслов — только то, что сказано
- Формат: нумерованный список

Если текст слишком короткий (1-2 предложения), выдели 1-2 главные мысли."""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    welcome_message = """Здравствуйте! Я VoiceScribe — помогаю обрабатывать голосовые сообщения.

Отправьте аудиофайл или голосовое сообщение, и я сделаю:
• Полную текстовую расшифровку
• Краткие тезисы (3–7 пунктов)

Готов к работе."""
    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help"""
    help_text = """Я делаю две вещи:
1. Расшифровываю аудио в текст
2. Выделяю ключевые тезисы

Поддерживаемые форматы: голосовые сообщения, .ogg, .mp3, .wav

Просто отправьте аудио — покажу на практике."""
    await update.message.reply_text(help_text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик голосовых сообщений и аудиофайлов"""
    
    # Определяем тип сообщения (голосовое или аудиофайл)
    if update.message.voice:
        file = await context.bot.get_file(update.message.voice.file_id)
        file_extension = "ogg"
    elif update.message.audio:
        file = await context.bot.get_file(update.message.audio.file_id)
        file_extension = update.message.audio.file_name.split('.')[-1] if update.message.audio.file_name else "mp3"
    elif update.message.document:
        # Проверяем, что это аудиофайл
        mime_type = update.message.document.mime_type or ""
        if not mime_type.startswith("audio/"):
            await update.message.reply_text(
                "Я работаю только с аудиофайлами форматов .mp3, .ogg и .wav. "
                "Пожалуйста, отправьте голосовое сообщение или аудиозапись."
            )
            return
        file = await context.bot.get_file(update.message.document.file_id)
        file_extension = update.message.document.file_name.split('.')[-1] if update.message.document.file_name else "ogg"
    else:
        await update.message.reply_text(
            "Я работаю только с аудиофайлами форматов .mp3, .ogg и .wav. "
            "Пожалуйста, отправьте голосовое сообщение или аудиозапись."
        )
        return

    # Уведомляем пользователя о начале обработки
    processing_message = await update.message.reply_text("Файл получен. Обрабатываю...")

    try:
        # Скачиваем файл (используем текущую директорию для совместимости)
        file_path = f"voice_{update.message.chat_id}_{update.message.message_id}.{file_extension}"
        await file.download_to_drive(file_path)

        # Транскрибация через Whisper
        with open(file_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru"
            )
        
        transcript_text = transcription.text

        # Проверка на пустую транскрипцию
        if not transcript_text or transcript_text.strip() == "":
            await processing_message.edit_text(
                "Не удалось распознать речь. Возможно, запись слишком тихая или содержит только шум."
            )
            os.remove(file_path)
            return

        # Генерация тезисов через GPT
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Выдели тезисы из следующего текста:\n\n{transcript_text}"}
            ],
            temperature=0.3,
            max_tokens=1000
        )
        
        theses = response.choices[0].message.content

        # Формируем ответ
        result_message = f"""📝 Транскрипция:
{transcript_text}

📌 Тезисы:
{theses}

Нужно что-то ещё?"""

        # Отправляем результат
        await processing_message.edit_text(result_message)

        # Удаляем временный файл
        os.remove(file_path)

    except Exception as e:
        logger.error(f"Ошибка при обработке: {e}")
        error_message = "Произошла ошибка при обработке аудио. Попробуйте ещё раз."
        
        if "Could not process audio" in str(e):
            error_message = "Качество записи низкое, не удалось обработать. Попробуйте записать сообщение в более тихом месте."
        
        await processing_message.edit_text(error_message)
        
        # Удаляем временный файл, если он существует
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)


async def handle_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик остальных сообщений"""
    await update.message.reply_text(
        "Я специализируюсь на расшифровке аудио и выделении тезисов. "
        "Отправьте голосовое сообщение или аудиофайл."
    )


def main() -> None:
    """Запуск бота"""
    # Получаем токен из переменной окружения
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN не установлен!")
    
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY не установлен!")

    # Создаём приложение
    application = Application.builder().token(token).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    application.add_handler(MessageHandler(filters.Document.AUDIO, handle_voice))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_other))

    # Запускаем бота
    print("VoiceScribe Bot запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
