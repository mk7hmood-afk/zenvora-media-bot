import os
import asyncio
import logging
import tempfile
import time
from pathlib import Path

import yt_dlp
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OWNER_ID = 234063581

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

STATS_FILE = Path("stats.txt")
stats = {"downloads": 0, "audio": 0, "errors": 0}
active_jobs = set()


def load_stats():
    try:
        values = STATS_FILE.read_text().split(",")
        stats["downloads"] = int(values[0])
        stats["audio"] = int(values[1])
        stats["errors"] = int(values[2])
    except (OSError, ValueError, IndexError):
        pass


def save_stats():
    try:
        STATS_FILE.write_text(
            f'{stats["downloads"]},{stats["audio"]},{stats["errors"]}'
        )
    except OSError:
        pass


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 تنزيل فيديو", callback_data="video")],
        [InlineKeyboardButton("🎵 استخراج MP3", callback_data="audio")],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats")],
        [InlineKeyboardButton("ℹ️ المساعدة", callback_data="help")],
    ])


def quality_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("أفضل جودة", callback_data="q_best"),
            InlineKeyboardButton("720p", callback_data="q_720"),
        ],
        [
            InlineKeyboardButton("480p", callback_data="q_480"),
            InlineKeyboardButton("360p", callback_data="q_360"),
        ],
        [InlineKeyboardButton("⬅️ القائمة", callback_data="home")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    context.user_data.clear()
    await update.message.reply_text(
        "🎬 أهلاً بك في Zenvora Media\n\n"
        "بوتك الخاص لتنزيل الفيديوهات واستخراج الصوت.\n"
        "اختر الخدمة من القائمة:",
        reply_markup=menu(),
    )


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != OWNER_ID:
        return

    data = query.data

    if data == "home":
        context.user_data.clear()
        await query.edit_message_text(
            "🎬 Zenvora Media\nاختر الخدمة:",
            reply_markup=menu(),
        )

    elif data == "video":
        context.user_data["mode"] = "video"
        await query.edit_message_text(
            "📥 أرسل رابط الفيديو العام أولاً."
        )

    elif data == "audio":
        context.user_data["mode"] = "audio"
        await query.edit_message_text(
            "🎵 أرسل رابط الفيديو الذي تريد استخراج صوته MP3."
        )

    elif data == "stats":
        await query.edit_message_text(
            "📊 إحصائيات البوت\n\n"
            f'📥 التنزيلات الناجحة: {stats["downloads"]}\n'
            f'🎵 ملفات MP3: {stats["audio"]}\n'
            f'❌ الأخطاء: {stats["errors"]}\n'
            f'⚙️ العمليات الحالية: {len(active_jobs)}',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ القائمة", callback_data="home")
            ]]),
        )

    elif data == "help":
        await query.edit_message_text(
            "ℹ️ طريقة الاستخدام\n\n"
            "1. اختر تنزيل فيديو أو استخراج MP3.\n"
            "2. أرسل رابطاً عاماً مدعوماً.\n"
            "3. اختر الجودة عند تنزيل الفيديو.\n\n"
            "قد لا تعمل بعض الروابط أو بعض الجودات.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ القائمة", callback_data="home")
            ]]),
        )

    elif data.startswith("q_"):
        quality = data[2:]
        context.user_data["quality"] = quality
        context.user_data["mode"] = "video"
        context.user_data["awaiting_url"] = True
        await query.edit_message_text(
            "📥 أرسل رابط الفيديو العام لتنزيله."
        )


async def progress_update(message, percent):
    try:
        await message.edit_text(
            f"⏳ جارٍ تنزيل الوسائط...\nالتقدم التقريبي: {percent}%"
        )
    except Exception:
        pass


async def process_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.effective_user.id != OWNER_ID:
        return

    url = (update.message.text or "").strip()

    if not url.startswith(("https://", "http://")):
        await update.message.reply_text("❌ أرسل رابطاً صحيحاً يبدأ بـ https://")
        return

    mode = context.user_data.get("mode", "video")
    quality = context.user_data.get("quality", "best")

    if mode == "video" and not context.user_data.get("awaiting_url"):
        await update.message.reply_text(
            "اختر الخدمة أولاً:",
            reply_markup=menu(),
        )
        return

    if update.effective_user.id in active_jobs:
        await update.message.reply_text("⏳ انتظر حتى ينتهي التنزيل الحالي.")
        return

    active_jobs.add(update.effective_user.id)
    status = await update.message.reply_text("⏳ جارٍ تجهيز التنزيل...")

    try:
        with tempfile.TemporaryDirectory(prefix="zenvora_") as tmp:
            template = os.path.join(tmp, "media.%(ext)s")
            last_percent = [-1]
            last_time = [0.0]

            def hook(data):
                if data.get("status") != "downloading":
                    return

                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                done = data.get("downloaded_bytes", 0)

                if not total:
                    return

                percent = int(done * 100 / total)
                now = time.monotonic()

                if percent != last_percent[0] and now - last_time[0] >= 3:
                    last_percent[0] = percent
                    last_time[0] = now

                    try:
                        loop.call_soon_threadsafe(
                            asyncio.create_task,
                            progress_update(status, percent),
                        )
                    except Exception:
                        pass

            loop = asyncio.get_running_loop()

            if mode == "audio":
                options = {
                    "format": "bestaudio/best",
                    "outtmpl": template,
                    "noplaylist": True,
                    "max_filesize": 40 * 1024 * 1024,
                    "progress_hooks": [hook],
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }],
                }
            else:
                height = {
                    "best": None,
                    "720": 720,
                    "480": 480,
                    "360": 360,
                }.get(quality)

                fmt = (
                    f"best[height<={height}][ext=mp4]/best[height<={height}]/best"
                    if height
                    else "best[ext=mp4]/best"
                )

                options = {
                    "format": fmt,
                    "outtmpl": template,
                    "noplaylist": True,
                    "max_filesize": 40 * 1024 * 1024,
                    "progress_hooks": [hook],
                }

            def download():
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return Path(ydl.prepare_filename(info))

            path = await asyncio.to_thread(download)

            if mode == "audio":
                candidates = list(Path(tmp).glob("*.mp3"))
                if candidates:
                    path = candidates[0]

            if not path.exists():
                files = [p for p in Path(tmp).iterdir() if p.is_file()]
                if not files:
                    raise FileNotFoundError("No output file")
                path = files[0]

            if path.stat().st_size > 49 * 1024 * 1024:
                raise ValueError("File too large for this bot")

            await status.edit_text("📤 اكتمل التنزيل، جارٍ الإرسال...")

            with path.open("rb") as media:
                if mode == "audio":
                    await update.message.reply_audio(
                        audio=media,
                        filename="Zenvora.mp3",
                    )
                    stats["audio"] += 1
                else:
                    await update.message.reply_document(
                        document=media,
                        filename=path.name,
                    )

            stats["downloads"] += 1
            save_stats()
            await status.edit_text("✅ تم إرسال الملف بنجاح.")

    except Exception as exc:
        logging.warning("Download failed: %s", type(exc).__name__)
        stats["errors"] += 1
        save_stats()
        await status.edit_text(
            "❌ تعذر التنزيل أو التحويل.\n"
            "تأكد من أن الرابط عام ومدعوم، وأن الملف ليس كبيراً جداً "
            "وأن FFmpeg متوفر عند طلب MP3."
        )

    finally:
        active_jobs.discard(update.effective_user.id)
        context.user_data.pop("awaiting_url", None)
        context.user_data.pop("mode", None)
        context.user_data.pop("quality", None)


async def choose_quality(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.effective_user.id != OWNER_ID:
        return

    context.user_data["mode"] = "video"
    context.user_data["awaiting_url"] = True
    await update.message.reply_text(
        "🎞️ اختر جودة الفيديو:",
        reply_markup=quality_menu(),
    )


def main():
    if not TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

    load_stats()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("quality", choose_quality))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, process_link)
    )

    print("Zenvora Media started")
    app.run_polling()


if __name__ == "__main__":
    main()