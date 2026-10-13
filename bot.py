import os
import asyncio
import yt_dlp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.environ.get(“TELEGRAM_BOT_TOKEN”)
OWNER_ID = 234063581

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
if update.effective_user.id != OWNER_ID:
return
await update.message.reply_text(“🎬 Zenvora Media\nأرسل رابط فيديو عام لتنزيله.”)

async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
if update.effective_user.id != OWNER_ID:
return

url = (update.message.text or "").strip()
if not url.startswith(("https://", "http://")):
    await update.message.reply_text("أرسل رابط فيديو صحيح.")
    return
msg = await update.message.reply_text("⏳ جارٍ تحميل الفيديو...")
filename = f"/tmp/zenvora_{update.message.message_id}"
try:
    options = {
        "format": "best[ext=mp4]/best",
        "outtmpl": filename + ".%(ext)s",
        "noplaylist": True,
        "max_filesize": 45 * 1024 * 1024,
    }
    def download():
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    path = await asyncio.to_thread(download)
    with open(path, "rb") as video:
        await update.message.reply_document(document=video)
    os.remove(path)
    await msg.edit_text("✅ تم إرسال الفيديو.")
except Exception:
    await msg.edit_text("❌ تعذر تنزيل الفيديو. جرّب رابطًا عامًا آخر.")

def main():
app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler(“start”, start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_video))
print(“Zenvora Media started”)
app.run_polling()

if name == “main”:
main()