import os
import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest, RetryAfter
from crex_api import CrexAPI

BOT_TOKEN = os.getenv("BOT_TOKEN")
REFRESH_INTERVAL = float(os.getenv("REFRESH_INTERVAL", "2.0"))
MAX_REFRESH_SECONDS = 900  # 15 min

MATCH_KEYS = {"118N": "🏏 Live Match"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

api = CrexAPI()
LIVE_TASKS = {}


def format_score(m, key):
    if not m:
        return f"⚠️ *No data* for `{key}`"
    icon = {"LIVE": "🔴", "Upcoming": "⏳", "Innings Break": "☕",
            "Completed": "✅", "Result Out": "🏁"}.get(m["status"], "⚪")
    text = (
        f"{icon} *{m['status']}* · Match #{m['match_no']} · {m['format']}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🏏 *{m['batting_team']}* — `{m['score']}` ({m['overs']} ov)\n"
        f"🎯 vs *{m['bowling_team']}*\n\n"
        f"📊 CRR: `{m['run_rate']}`"
    )
    if m.get("partnership"):
        text += f" · 🤝 `{m['partnership']}`"
    if m.get("innings_1"):
        text += f"\n\n1️⃣ `{m['innings_1']})`"
    if m.get("innings_2") and m["innings_2"] != m.get("innings_1"):
        text += f"\n2️⃣ `{m['innings_2']})`"
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
            text += f"\n  *{p['overs']}:* {s[0]}/{s[1]}/{s[2]}/{s[3]}"
    text += f"\n\n🕐 _{datetime.now().strftime('%H:%M:%S')}_"
    return text


def match_keyboard(key, live):
    btn = "⏸ Stop Live" if live else "▶️ Start Live"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"k:{key}")],
        [InlineKeyboardButton(btn, callback_data=f"live:{key}")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back")]
    ])


def main_menu():
    kb = [[InlineKeyboardButton(n, callback_data=f"k:{k}")] for k, n in MATCH_KEYS.items()]
    kb.append([InlineKeyboardButton("➕ Add", callback_data="help"),
               InlineKeyboardButton("ℹ️ About", callback_data="about")])
    return InlineKeyboardMarkup(kb)


async def live_loop(ctx, chat_id, msg_id, key):
    last = ""
    start = datetime.now()
    try:
        while True:
            if (datetime.now() - start).seconds > MAX_REFRESH_SECONDS:
                break
            m = api.parse(key)
            text = format_score(m, key)
            if text != last:
                try:
                    await ctx.bot.edit_message_text(
                        chat_id=chat_id, message_id=msg_id, text=text,
                        parse_mode="Markdown", reply_markup=match_keyboard(key, True))
                    last = text
                except BadRequest as e:
                    if "not modified" not in str(e).lower():
                        log.warning(e)
                except RetryAfter as e:
                    await asyncio.sleep(e.retry_after)
            if m and m.get("status_code") in (4, 5):
                break
            await asyncio.sleep(REFRESH_INTERVAL)
    except asyncio.CancelledError:
        pass
    finally:
        LIVE_TASKS.pop(f"{chat_id}:{msg_id}", None)


async def start_cmd(update, ctx):
    await update.message.reply_text(
        "🏏 *Live Cricket Score Bot*\n\nSelect a match:",
        parse_mode="Markdown", reply_markup=main_menu())


async def show_match(update, ctx):
    q = update.callback_query
    await q.answer("Loading…")
    key = q.data.split(":", 1)[1]
    m = api.parse(key)
    await q.edit_message_text(format_score(m, key), parse_mode="Markdown",
                              reply_markup=match_keyboard(key, False))


async def toggle_live(update, ctx):
    q = update.callback_query
    key = q.data.split(":", 1)[1]
    task_id = f"{q.message.chat_id}:{q.message.message_id}"

    if task_id in LIVE_TASKS:
        LIVE_TASKS[task_id].cancel()
        LIVE_TASKS.pop(task_id, None)
        await q.answer("⏸ Live stopped")
        m = api.parse(key)
        await q.edit_message_text(format_score(m, key), parse_mode="Markdown",
                                  reply_markup=match_keyboard(key, False))
    else:
        await q.answer("▶️ Live started")
        task = asyncio.create_task(live_loop(ctx, q.message.chat_id, q.message.message_id, key))
        LIVE_TASKS[task_id] = task


async def back(update, ctx):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🏏 *Select a match:*", parse_mode="Markdown", reply_markup=main_menu())


async def help_btn(update, ctx):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "➕ *Add a Match*\n\n1. Go to crex.com → live match\n"
        "2. F12 → Network → filter `getSV3`\n3. Copy `key` from URL\n\n"
        "Then: `/add <key> <name>`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]]))


async def about(update, ctx):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🤖 *Live Cricket Bot*\n⚡ Auto-refresh · 🚂 Railway hosted",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]]))


async def add_cmd(update, ctx):
    if len(ctx.args) < 2:
        await update.message.reply_text("Usage: `/add <key> <name>`", parse_mode="Markdown")
        return
    MATCH_KEYS[ctx.args[0]] = " ".join(ctx.args[1:])
    await update.message.reply_text(f"✅ Added `{ctx.args[0]}`", parse_mode="Markdown")


async def score_cmd(update, ctx):
    if not ctx.args:
        await update.message.reply_text("Usage: `/score <key>`", parse_mode="Markdown")
        return
    m = api.parse(ctx.args[0])
    await update.message.reply_text(format_score(m, ctx.args[0]), parse_mode="Markdown",
                                    reply_markup=match_keyboard(ctx.args[0], False))


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN env var not set!")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("score", score_cmd))
    app.add_handler(CallbackQueryHandler(show_match, pattern="^k:"))
    app.add_handler(CallbackQueryHandler(toggle_live, pattern="^live:"))
    app.add_handler(CallbackQueryHandler(back, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(help_btn, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(about, pattern="^about$"))
    log.info("✅ Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
