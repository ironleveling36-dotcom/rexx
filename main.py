import os
import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = "https://api.goscorer.com/api/v3/getSV3?key={}"
HEADERS = {
    "authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCIsImV4cGlyZXNJbiI6IjM2NWQifQ.eyJ0aW1lIjoxNjYwMDQ2NjIwMDAwfQ.bTEmMWlR7hLRUHxPPq6-1TP7cuuW7m6sZ9jcdbYzLRA",
    "origin": "https://crex.com",
    "referer": "https://crex.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

# Add match keys you find on crex.com URLs
MATCH_KEYS = {
    "118N": "🏏 Live Match"
}

STATUS_MAP = {
    0: "⏳ Upcoming",
    1: "🟡 Starting Soon",
    2: "🔴 LIVE",
    3: "☕ Innings Break",
    4: "✅ Completed",
    5: "🏁 Result"
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# ---------- API ----------
def fetch_match(key):
    try:
        r = requests.get(BASE_URL.format(key), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json()
        log.warning(f"API {r.status_code} for key={key}")
        return None
    except Exception as e:
        log.error(f"Error: {e}")
        return None

# ---------- FORMATTER ----------
def parse_balls(over_str):
    """Parse '4:0.5.1.1.0.6' -> 'Ov 4: 0 • 5 • 1 • 1 • 0 • 6'"""
    if not over_str or ":" not in over_str:
        return ""
    ov, balls = over_str.split(":", 1)
    return f"Ov {ov}: " + " • ".join(balls.split("."))

def format_score(d, key):
    if not d:
        return f"⚠️ *No data for key `{key}`*\n\nMatch might be over or key expired."

    batting = d.get("a", "").split(".")[0] or "—"
    bowling = d.get("F", "").replace("^", "") or "—"
    score = d.get("ats", "—")
    overs = d.get("q", "0").replace("*", "")
    crr = d.get("s", "—")
    match_no = d.get("mn", "?")
    status = STATUS_MAP.get(d.get("ms", 0), "Unknown")
    fmt = "T20" if d.get("f") == 1 else "ODI/Test"

    inn1 = d.get("j", "")
    inn2 = d.get("k", "")

    # Current over balls
    last_ball = d.get("d", "").split("|")[-1] if d.get("d") else ""
    this_over = " • ".join(last_ball.split(".")) if last_ball else "—"

    # Times
    mt = d.get("mt", 0)
    match_time = datetime.fromtimestamp(mt/1000).strftime("%d %b, %H:%M") if mt else ""

    # Build message
    text = (
        f"{status}  *Match #{match_no}* · {fmt}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🏏 *{batting}*  —  `{score}`  ({overs} ov)\n"
        f"🎯 *vs {bowling}*\n\n"
        f"📊 *CRR:* `{crr}`\n"
    )

    if inn1:
        text += f"\n1️⃣ *1st Inns:* `{inn1})`"
    if inn2 and inn2 != inn1:
        text += f"\n2️⃣ *2nd Inns:* `{inn2})`"

    if this_over and this_over != "—":
        text += f"\n\n⚡ *This Over:* `{this_over}`"

    # Last 4 overs
    last_overs = []
    for k in ["l", "m", "n"]:
        ov = parse_balls(d.get(k, ""))
        if ov:
            last_overs.append(ov)
    if last_overs:
        text += "\n\n📜 *Recent Overs:*\n" + "\n".join(f"  `{o}`" for o in last_overs)

    # Projected scores
    pr = d.get("pr", {})
    if pr.get("ps"):
        text += "\n\n📈 *Projected Scores:*\n"
        for p in pr["ps"]:
            sc = p.get("sc", {})
            text += f"  • *{p.get('ov')}:* {sc.get('ps1','-')} / {sc.get('ps2','-')} / {sc.get('ps3','-')} / {sc.get('ps4','-')}\n"
        rates = pr.get("rates", {})
        if rates:
            text += f"  _Rates: {rates.get('r1')} / {rates.get('r2')} / {rates.get('r3')} / {rates.get('r4')}_"

    if match_time:
        text += f"\n\n🕐 _Started: {match_time}_"

    text += f"\n\n🔑 Key: `{key}`"
    return text

# ---------- HANDLERS ----------
def main_menu():
    kb = [[InlineKeyboardButton(name, callback_data=f"k:{k}")] for k, name in MATCH_KEYS.items()]
    kb.append([
        InlineKeyboardButton("➕ Add Match", callback_data="help"),
        InlineKeyboardButton("ℹ️ About", callback_data="about")
    ])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏏 *Live Cricket Score Bot*\n\n"
        "Get real-time ball-by-ball scores!\n\n"
        "👇 Select a match or use `/score <key>`",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def show_match(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Updating…")
    key = q.data.split(":", 1)[1]
    data = fetch_match(key)
    text = format_score(data, key)
    kb = [
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ]
    try:
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        if "not modified" not in str(e).lower():
            log.error(e)

async def back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🏏 *Live Cricket Score Bot*\n\nSelect a match:",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def help_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "➕ *Add a Match*\n\n"
        "1. Open [crex.com](https://crex.com) → any live match\n"
        "2. Open DevTools (F12) → Network tab\n"
        "3. Filter for `getSV3`\n"
        "4. Copy the `key` value from the URL\n\n"
        "Then send:\n"
        "`/add <key> <name>`\n\n"
        "Example:\n"
        "`/add 118N IND vs AUS`",
        parse_mode="Markdown", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

async def about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🤖 *Live Cricket Bot*\n\n"
        "• ⚡ Real-time ball-by-ball\n"
        "• 📊 CRR + projected scores\n"
        "• 📜 Last overs history\n"
        "• 🚂 Hosted on Railway\n\n"
        "_Data via CREX API_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

# ---------- COMMANDS ----------
async def add_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        await update.message.reply_text(
            "Usage: `/add <key> <name>`\nExample: `/add 118N IND vs AUS`",
            parse_mode="Markdown"
        )
        return
    key = ctx.args[0]
    name = " ".join(ctx.args[1:])
    MATCH_KEYS[key] = name
    await update.message.reply_text(f"✅ Added: *{name}* (`{key}`)", parse_mode="Markdown")

async def remove_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/remove <key>`", parse_mode="Markdown")
        return
    key = ctx.args[0]
    if key in MATCH_KEYS:
        del MATCH_KEYS[key]
        await update.message.reply_text(f"🗑 Removed `{key}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("Key not found.")

async def score_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/score <key>`\nExample: `/score 118N`",
                                        parse_mode="Markdown")
        return
    key = ctx.args[0]
    data = fetch_match(key)
    kb = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")]]
    await update.message.reply_text(format_score(data, key), parse_mode="Markdown",
                                     reply_markup=InlineKeyboardMarkup(kb))

async def list_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not MATCH_KEYS:
        await update.message.reply_text("No matches added. Use `/add`.")
        return
    text = "📋 *Saved Matches:*\n\n" + "\n".join(f"• `{k}` — {v}" for k, v in MATCH_KEYS.items())
    await update.message.reply_text(text, parse_mode="Markdown")

def main():
    if not BOT_TOKEN:
        raise RuntimeError("Set BOT_TOKEN environment variable!")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("score", score_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CallbackQueryHandler(show_match, pattern="^k:"))
    app.add_handler(CallbackQueryHandler(back, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(help_btn, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(about, pattern="^about$"))

    log.info("✅ Bot running")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
