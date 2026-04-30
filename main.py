import os
import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from telegram.error import BadRequest, RetryAfter

from crex_api import CrexAPI

BOT_TOKEN = os.getenv("BOT_TOKEN")
REFRESH_INTERVAL = float(os.getenv("REFRESH_INTERVAL", "2.0"))  # seconds
MAX_REFRESH_SECONDS = 600  # auto-stop after 10 min to save resources

MATCH_KEYS = {"118N": "🏏 Live Match"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

api = CrexAPI()

# Track live auto-refresh tasks: {chat_id_message_id: asyncio.Task}
LIVE_TASKS: dict = {}


# ---------- FORMATTING ----------
def format_score(m: dict, key: str) -> str:
    if not m:
        return f"⚠️ *No data* for `{key}`\nMatch might be over or key expired."

    icon = {"LIVE": "🔴", "Upcoming": "⏳", "Innings Break": "☕",
            "Completed": "✅", "Result Out": "🏁"}.get(m["status"], "⚪")

    text = (
        f"{icon} *{m['status']}*  ·  Match #{m['match_no']}  ·  {m['format']}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🏏 *{m['batting_team']}*  —  `{m['score']}`  ({m['overs']} ov)\n"
        f"🎯 vs *{m['bowling_team']}*\n\n"
        f"📊 CRR: `{m['run_rate']}`"
    )

    if m.get("partnership"):
        text += f"  ·  🤝 P'ship: `{m['partnership']}`"

    if m.get("innings_1"):
        text += f"\n\n1️⃣ *1st Inns:* `{m['innings_1']})`"
    if m.get("innings_2") and m["innings_2"] != m.get("innings_1"):
        text += f"\n2️⃣ *2nd Inns:* `{m['innings_2']})`"

    if m.get("this_over"):
        text += f"\n\n⚡ *This Over:* `{m['this_over']}`"

    if m.get("recent_overs"):
        text += "\n\n📜 *Recent Overs:*"
        for ov in m["recent_overs"][:3]:
            text += f"\n  `Ov {ov['over']}:` " + " • ".join(ov["balls"])

    if m.get("projections"):
        text += "\n\n📈 *Projected:*"
        for p in m["projections"]:
            s = p["scores"]
            text += f"\n  *{p['overs']}:*  {s[0]} / {s[1]} / {s[2]} / {s[3]}"

    text += f"\n\n🕐 _Updated: {datetime.now().strftime('%H:%M:%S')}_"
    return text


def match_keyboard(key: str, live: bool) -> InlineKeyboardMarkup:
    btn = "⏸ Stop Live" if live else "▶️ Start Live"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Now", callback_data=f"k:{key}")],
        [InlineKeyboardButton(btn, callback_data=f"live:{key}")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ])


def main_menu() -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(n, callback_data=f"k:{k}")] for k, n in MATCH_KEYS.items()]
    kb.append([
        InlineKeyboardButton("➕ Add", callback_data="help"),
        InlineKeyboardButton("ℹ️ About", callback_data="about")
    ])
    return InlineKeyboardMarkup(kb)


# ---------- AUTO-REFRESH ENGINE ----------
async def live_refresh_loop(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_id: int, key: str):
    """Background task that refreshes the message every N seconds."""
    last_text = ""
    start = datetime.now()

    try:
        while True:
            # Auto-stop after MAX_REFRESH_SECONDS
            if (datetime.now() - start).seconds > MAX_REFRESH_SECONDS:
                log.info(f"Auto-stop refresh for {key}")
                break

            m = api.parse(key)
            text = format_score(m, key)

            # Only edit if content changed (saves Telegram API quota)
            if text != last_text:
                try:
                    await ctx.bot.edit_message_text(
                        chat_id=chat_id, message_id=msg_id,
                        text=text, parse_mode="Markdown",
                        reply_markup=match_keyboard(key, live=True)
                    )
                    last_text = text
                except BadRequest as e:
                    if "not modified" not in str(e).lower():
                        log.warning(f"Edit error: {e}")
                except RetryAfter as e:
                    log.warning(f"Flood wait {e.retry_after}s")
                    await asyncio.sleep(e.retry_after)

            # Stop if match ended
            if m and m.get("status_code") in (4, 5):
                log.info(f"Match {key} ended, stopping refresh")
                try:
                    await ctx.bot.edit_message_reply_markup(
                        chat_id=chat_id, message_id=msg_id,
                        reply_markup=match_keyboard(key, live=False)
                    )
                except Exception:
                    pass
                break

            await asyncio.sleep(REFRESH_INTERVAL)
    except asyncio.CancelledError:
        log.info(f"Refresh cancelled for {key}")
    except Exception as e:
        log.error(f"Loop error: {e}")
    finally:
        LIVE_TASKS.pop(f"{chat_id}:{msg_id}", None)


# ---------- HANDLERS ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏏 *Live Cricket Score Bot*\n\n"
        "• ⚡ Ball-by-ball updates\n"
        "• 🔄 Auto-refresh (live mode)\n"
        "• 📊 Projections & CRR\n\n"
        "Select a match:",
        parse_mode="Markdown", reply_markup=main_menu()
    )


async def show_match(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Updating…")
    key = q.data.split(":", 1)[1]
    m = api.parse(key)
    text = format_score(m, key)

    # Check if this message already has a live loop
    task_id = f"{q.message.chat_id}:{q.message.message_id}"
    is_live = task_id in LIVE_TASKS

    try:
        await q.edit_message_text(text, parse_mode="Markdown",
                                  reply_markup=match_keyboard(key, is_live))
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.error(e)


async def toggle_live(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    key = q.data.split(":", 1)[1]
    task_id = f"{q.message.chat_id}:{q.message.message_id}"

    if task_id in LIVE_TASKS:
        # Stop
        LIVE_TASKS[task_id].cancel()
        LIVE_TASKS.pop(task_id, None)
        await q.answer("⏸ Live updates stopped")
        m = api.parse(key)
        await q.edit_message_text(format_score(m, key), parse_mode="Markdown",
                                  reply_markup=match_keyboard(key, live=False))
    else:
        # Start
        await q.answer("▶️ Live mode started!")
        task = asyncio.create_task(
            live_refresh_loop(ctx, q.message.chat_id, q.message.message_id, key)
        )
        LIVE_TASKS[task_id] = task


async def back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # Cancel any active refresh
    task_id = f"{q.message.chat_id}:{q.message.message_id}"
    if task_id in LIVE_TASKS:
        LIVE_TASKS[task_id].cancel()
        LIVE_TASKS.pop(task_id, None)
    await q.edit_message_text(
        "🏏 *Live Cricket Score Bot*\n\nSelect a match:",
        parse_mode="Markdown", reply_markup=main_menu()
    )


async def help_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "➕ *Add a Match*\n\n"
        "1. Go to [crex.com](https://crex.com) → live match\n"
        "2. DevTools (F12) → Network → filter `getSV3`\n"
        "3. Copy `key` from URL\n\n"
        "Then send: `/add <key> <name>`\n"
        "Example: `/add 118N IND vs AUS`",
        parse_mode="Markdown", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )


async def about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🤖 *Live Cricket Bot*\n\n"
        f"• 🔄 Refresh: `{REFRESH_INTERVAL}s`\n"
        "• 🚂 Hosted on Railway\n"
        "• 📡 CREX API\n",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )


# ---------- COMMANDS ----------
async def add_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        await update.message.reply_text("Usage: `/add <key> <name>`", parse_mode="Markdown")
        return
    MATCH_KEYS[ctx.args[0]] = " ".join(ctx.args[1:])
    await update.message.reply_text(f"✅ Added `{ctx.args[0]}`", parse_mode="Markdown")


async def remove_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/remove <key>`", parse_mode="Markdown")
        return
    MATCH_KEYS.pop(ctx.args[0], None)
    await update.message.reply_text(f"🗑 Removed `{ctx.args[0]}`", parse_mode="Markdown")


async def score_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/score <key>`", parse_mode="Markdown")
        return
    key = ctx.args[0]
    m = api.parse(key)
    await update.message.reply_text(
        format_score(m, key), parse_mode="Markdown",
        reply_markup=match_keyboard(key, live=False)
    )


async def stop_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Stop all live refreshes for this user."""
    count = 0
    chat_id = update.effective_chat.id
    for tid in list(LIVE_TASKS.keys()):
        if tid.startswith(f"{chat_id}:"):
            LIVE_TASKS[tid].cancel()
            LIVE_TASKS.pop(tid, None)
            count += 1
    await update.message.reply_text(f"⏹ Stopped {count} live update(s)")


# ---------- MAIN ----------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN env variable missing!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("score", score_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))

    app.add_handler(CallbackQueryHandler(show_match, pattern="^k:"))
    app.add_handler(CallbackQueryHandler(toggle_live, pattern="^live:"))
    app.add_handler(CallbackQueryHandler(back, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(help_btn, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(about, pattern="^about$"))

    log.info(f"🚀 Bot started (refresh every {REFRESH_INTERVAL}s)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
