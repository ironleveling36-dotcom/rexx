import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

# ---------------- CONFIG ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = "https://api.goscorer.com/api/v3/getSV3?key=118N"
HEADERS = {
    "authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCIsImV4cGlyZXNJbiI6IjM2NWQifQ.eyJ0aW1lIjoxNjYwMDQ2NjIwMDAwfQ.bTEmMWlR7hLRUHxPPq6-1TP7cuuW7m6sZ9jcdbYzLRA",
    "origin": "https://crex.com",
    "referer": "https://crex.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- API HELPERS ----------------
def fetch_matches():
    try:
        r = requests.get(API_URL, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        # Adjust depending on actual JSON shape
        matches = data.get("matches") or data.get("data") or []
        return matches
    except Exception as e:
        logger.error(f"API Error: {e}")
        return []

def format_match(match):
    """Format one match into a readable string."""
    try:
        team1 = match.get("team1", {}).get("name", "Team 1")
        team2 = match.get("team2", {}).get("name", "Team 2")
        score1 = match.get("team1", {}).get("score", "-")
        score2 = match.get("team2", {}).get("score", "-")
        status = match.get("status", "Live")
        venue = match.get("venue", "")
        return (
            f"🏏 *{team1}* vs *{team2}*\n"
            f"📊 {team1}: `{score1}`\n"
            f"📊 {team2}: `{score2}`\n"
            f"📍 {venue}\n"
            f"🟢 _{status}_"
        )
    except Exception:
        return "⚠️ Match data unavailable."

# ---------------- HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🏏 Live Matches", callback_data="live")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh"),
         InlineKeyboardButton("ℹ️ About", callback_data="about")]
    ]
    await update.message.reply_text(
        "👋 *Welcome to Live Cricket Score Bot!*\n\nClick below to start:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Fetching live scores...")

    matches = fetch_matches()
    if not matches:
        text = "⚠️ No live matches available right now."
        keyboard = [[InlineKeyboardButton("🔄 Retry", callback_data="live")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    keyboard = []
    for i, m in enumerate(matches[:10]):
        t1 = m.get("team1", {}).get("short_name", "T1")
        t2 = m.get("team2", {}).get("short_name", "T2")
        keyboard.append([InlineKeyboardButton(f"{t1} vs {t2}", callback_data=f"match_{i}")])
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="live")])

    context.user_data["matches"] = matches
    await query.edit_message_text(
        "🏏 *Select a Live Match:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def match_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    matches = context.user_data.get("matches", [])
    if idx >= len(matches):
        await query.edit_message_text("⚠️ Match expired. Please refresh.")
        return
    text = format_match(matches[idx])
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"match_{idx}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="live")]
    ]
    await query.edit_message_text(text, parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup(keyboard))

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back")]]
    await query.edit_message_text(
        "🤖 *Live Cricket Score Bot*\n\n"
        "• Real-time match updates\n"
        "• Inline button navigation\n"
        "• Hosted on Railway 🚂\n\n"
        "_Made with ❤️ in Python_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def back_to_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🏏 Live Matches", callback_data="live")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh"),
         InlineKeyboardButton("ℹ️ About", callback_data="about")]
    ]
    await query.edit_message_text(
        "👋 *Welcome to Live Cricket Score Bot!*\n\nClick below to start:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------- MAIN ----------------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable not set!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(show_matches, pattern="^(live|refresh)$"))
    app.add_handler(CallbackQueryHandler(match_detail, pattern="^match_"))
    app.add_handler(CallbackQueryHandler(about, pattern="^about$"))
    app.add_handler(CallbackQueryHandler(back_to_start, pattern="^back$"))

    logger.info("Bot started ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()