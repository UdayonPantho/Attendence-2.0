"""
Attendance Chatbot for Telegram Study Groups
---------------------------------------------
Flow:
  1. Everyone in the study group DMs the bot once with /start
     (Telegram requires this before the bot can message anyone privately)
  2. Each person joins their courses with:  /register CSE2201DMS
     ...or joins all 9 Level 2-2 courses at once with:  /register22
  3. When a class actually happens, anyone in the GROUP chat types:
        /classdone CSE2201DMS
     -> Bot creates a new "session" for that course and DMs every
        enrolled member asking Yes / No (via inline buttons)
  4. Each person taps Yes or No in their private chat with the bot
  5. Anyone can check their own record with:  /attendance CSE2201DMS
     or the average across every enrolled course with: /totalattendance

Requirements:
    pip install python-telegram-bot==21.*

Run:
    export BOT_TOKEN="123456:ABC-your-token-from-BotFather"
    python bot.py
"""

import logging
import os
import sqlite3
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# Google Sheets sync is optional -- if not configured, the bot still works
# for attendance tracking, it just won't push to Sheets.
try:
    from sheets_sync import sync_course_to_sheets, SHEETS_ENABLED
except Exception:  # missing credentials / libraries etc.
    SHEETS_ENABLED = False

    def sync_course_to_sheets(course_code: str):
        pass

# The fixed list of Level-2 Term-2 courses. /register22 enrolls a student in
# all of these at once instead of typing /register nine separate times.
CURRICULUM = [
    "CSE2201DMS",
    "CSE2202DMSLAB",
    "CSE2203CAO",
    "CSE2204DAA",
    "CSE2205DAALAB",
    "CSE2206MAL",
    "CSE2207MALLAB",
    "CSE2208SDWITHJAVALAB",
    "STAT2209PSA",
]

# Comma separated Telegram numeric user IDs allowed to run /sync manually.
# Leave empty to let anyone run it.
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()
}

# Seconds to wait after the last response before pushing an update to Sheets,
# so the bot doesn't hammer the Sheets API every single time someone taps a button.
SYNC_DEBOUNCE_SECONDS = 60

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "attendance.db")


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,   -- telegram user id
            username    TEXT,
            first_name  TEXT
        );

        CREATE TABLE IF NOT EXISTS courses (
            course_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT UNIQUE NOT NULL   -- e.g. CSC1100
        );

        CREATE TABLE IF NOT EXISTS enrollments (
            user_id     INTEGER NOT NULL,
            course_id   INTEGER NOT NULL,
            PRIMARY KEY (user_id, course_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        );

        CREATE TABLE IF NOT EXISTS sessions (
            session_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id   INTEGER NOT NULL,
            created_at  TEXT NOT NULL,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        );

        CREATE TABLE IF NOT EXISTS attendance (
            session_id  INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            response    TEXT,                  -- 'yes' / 'no' / NULL (not answered yet)
            responded_at TEXT,
            PRIMARY KEY (session_id, user_id),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        """
    )
    conn.commit()
    conn.close()


def upsert_user(user_id: int, username: str, first_name: str):
    conn = get_conn()
    conn.execute(
        """INSERT INTO users (user_id, username, first_name)
           VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
                                               first_name=excluded.first_name""",
        (user_id, username, first_name),
    )
    conn.commit()
    conn.close()


def get_or_create_course(code: str) -> int:
    code = code.upper().strip()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT course_id FROM courses WHERE code=?", (code,))
    row = c.fetchone()
    if row:
        course_id = row[0]
    else:
        c.execute("INSERT INTO courses (code) VALUES (?)", (code,))
        course_id = c.lastrowid
        conn.commit()
    conn.close()
    return course_id


def enroll_user(user_id: int, course_code: str):
    course_id = get_or_create_course(course_code)
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO enrollments (user_id, course_id) VALUES (?, ?)",
        (user_id, course_id),
    )
    conn.commit()
    conn.close()


def get_enrolled_users(course_code: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """SELECT u.user_id, u.first_name FROM users u
           JOIN enrollments e ON u.user_id = e.user_id
           JOIN courses c ON c.course_id = e.course_id
           WHERE c.code = ?""",
        (course_code.upper(),),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def create_session(course_code: str) -> int:
    course_id = get_or_create_course(course_code)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO sessions (course_id, created_at) VALUES (?, ?)",
        (course_id, datetime.utcnow().isoformat()),
    )
    session_id = c.lastrowid
    conn.commit()
    conn.close()
    return session_id


def record_pending(session_id: int, user_id: int):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO attendance (session_id, user_id, response) VALUES (?, ?, NULL)",
        (session_id, user_id),
    )
    conn.commit()
    conn.close()


def save_response(session_id: int, user_id: int, response: str):
    conn = get_conn()
    conn.execute(
        """UPDATE attendance SET response=?, responded_at=?
           WHERE session_id=? AND user_id=?""",
        (response, datetime.utcnow().isoformat(), session_id, user_id),
    )
    conn.commit()
    conn.close()


def get_course_code_for_session(session_id: int) -> str:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """SELECT c.code FROM sessions s
           JOIN courses c ON c.course_id = s.course_id
           WHERE s.session_id = ?""",
        (session_id,),
    )
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def get_courses_for_user(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """SELECT c.code FROM courses c
           JOIN enrollments e ON e.course_id = c.course_id
           WHERE e.user_id = ? ORDER BY c.code""",
        (user_id,),
    )
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows


def attendance_stats(user_id: int, course_code: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """SELECT a.response FROM attendance a
           JOIN sessions s ON s.session_id = a.session_id
           JOIN courses c ON c.course_id = s.course_id
           WHERE a.user_id = ? AND c.code = ?""",
        (user_id, course_code.upper()),
    )
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    total = len(rows)
    attended = sum(1 for r in rows if r == "yes")
    return attended, total


# --------------------------------------------------------------------------
# Command handlers
# --------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username or "", user.first_name or "")
    await update.message.reply_text(
        "স্বাগতম! এখন আমি তোমাকে সরাসরি মেসেজ পাঠাতে পারব।\n\n"
        "একটা কোর্সে join করতে লিখো:\n"
        "  /register CSE2201DMS\n\n"
        "2-2 লেভেলের সবগুলো কোর্সে একসাথে join করতে:\n"
        "  /register22\n\n"
        "নির্দিষ্ট কোর্সের attendance দেখতে:\n"
        "  /attendance CSE2201DMS\n\n"
        "সবগুলো কোর্স মিলিয়ে গড় attendance দেখতে:\n"
        "  /totalattendance"
    )


async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username or "", user.first_name or "")

    if not context.args:
        await update.message.reply_text("Usage: /register CSC1100")
        return

    course_code = context.args[0]
    enroll_user(user.id, course_code)
    await update.message.reply_text(f"তুমি এখন {course_code.upper()} কোর্সে enrolled আছো ✅")


async def register22(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username or "", user.first_name or "")

    for code in CURRICULUM:
        enroll_user(user.id, code)

    course_list = "\n".join(f"  • {c}" for c in CURRICULUM)
    await update.message.reply_text(
        f"তুমি এখন 2-2 লেভেলের সবগুলো কোর্সে enrolled আছো ✅\n\n{course_list}"
    )


async def classdone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only meant to be used inside the group chat
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("এই command টা group chat-এ ব্যবহার করো, personal chat-এ না।")
        return

    if not context.args:
        await update.message.reply_text("Usage: /classdone CSC1100")
        return

    course_code = context.args[0].upper()
    members = get_enrolled_users(course_code)

    if not members:
        await update.message.reply_text(
            f"{course_code} কোর্সে কেউ এখনো /register করেনি।"
        )
        return

    session_id = create_session(course_code)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes, ছিলাম", callback_data=f"att:{session_id}:yes"),
                InlineKeyboardButton("❌ No, ছিলাম না", callback_data=f"att:{session_id}:no"),
            ]
        ]
    )

    sent, failed = 0, []
    for user_id, first_name in members:
        record_pending(session_id, user_id)
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📚 {course_code} ক্লাস হয়ে গেছে।\nতুমি কি এই ক্লাসে উপস্থিত ছিলে?",
                reply_markup=keyboard,
            )
            sent += 1
        except Exception as e:
            logger.warning("Could not DM user %s: %s", user_id, e)
            failed.append(first_name or str(user_id))

    msg = f"{course_code} — {sent} জনকে DM পাঠানো হয়েছে।"
    if failed:
        msg += (
            "\n\n⚠️ এদের কাছে পাঠানো যায়নি (আগে বটকে /start করেনি): "
            + ", ".join(failed)
        )
    await update.message.reply_text(msg)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, session_id, response = query.data.split(":")
    session_id = int(session_id)
    user_id = query.from_user.id

    save_response(session_id, user_id, response)

    label = "✅ Present হিসেবে মার্ক করা হলো, ধন্যবাদ!" if response == "yes" else "❌ Absent হিসেবে মার্ক করা হলো।"
    await query.edit_message_text(label)

    # Debounced push to Google Sheets: cancel any pending sync job for this
    # course and schedule a fresh one, so rapid-fire responses only trigger
    # one Sheets update a little while after the last person answers.
    if SHEETS_ENABLED and context.job_queue is not None:
        course_code = get_course_code_for_session(session_id)
        if course_code:
            job_name = f"sync:{course_code}"
            for job in context.job_queue.get_jobs_by_name(job_name):
                job.schedule_removal()
            context.job_queue.run_once(
                run_sheets_sync_job,
                when=SYNC_DEBOUNCE_SECONDS,
                data=course_code,
                name=job_name,
            )


async def run_sheets_sync_job(context: ContextTypes.DEFAULT_TYPE):
    course_code = context.job.data
    try:
        sync_course_to_sheets(course_code)
        logger.info("Synced %s to Google Sheets", course_code)
    except Exception as e:
        logger.error("Sheets sync failed for %s: %s", course_code, e)


async def attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not context.args:
        await update.message.reply_text("Usage: /attendance CSC1100")
        return

    course_code = context.args[0]
    attended, total = attendance_stats(user.id, course_code)

    if total == 0:
        await update.message.reply_text(f"{course_code.upper()}-এ এখনো কোনো session record নেই।")
        return

    pct = round((attended / total) * 100, 1)
    await update.message.reply_text(
        f"📊 {course_code.upper()} Attendance\n"
        f"উপস্থিত ছিলে: {attended}/{total} ক্লাসে\n"
        f"শতকরা হার: {pct}%"
    )


async def total_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    courses = get_courses_for_user(user.id)

    if not courses:
        await update.message.reply_text(
            "তুমি এখনো কোনো কোর্সে register করোনি। প্রথমে /register22 বা /register CSE2201DMS লিখো।"
        )
        return

    lines = ["📊 তোমার সবগুলো কোর্সের attendance:\n"]
    total_attended, total_sessions = 0, 0

    for code in courses:
        attended, total = attendance_stats(user.id, code)
        total_attended += attended
        total_sessions += total
        if total == 0:
            lines.append(f"  {code}: এখনো কোনো class হয়নি")
        else:
            pct = round((attended / total) * 100, 1)
            lines.append(f"  {code}: {attended}/{total} ({pct}%)")

    if total_sessions == 0:
        lines.append("\nমোট গড়: এখনো কোনো data নেই")
    else:
        overall_pct = round((total_attended / total_sessions) * 100, 1)
        lines.append(f"\n📈 সবগুলো কোর্স মিলিয়ে গড়: {total_attended}/{total_sessions} ({overall_pct}%)")

    await update.message.reply_text("\n".join(lines))


async def sync_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_IDS and update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("এই command শুধু admin ব্যবহার করতে পারবে।")
        return

    if not SHEETS_ENABLED:
        await update.message.reply_text(
            "Google Sheets sync configure করা নেই। README.md দেখো credentials setup-এর জন্য।"
        )
        return

    if not context.args:
        await update.message.reply_text("Usage: /sync CSE2201DMS")
        return

    course_code = context.args[0].upper()
    await update.message.reply_text(f"{course_code} শীট আপডেট হচ্ছে...")
    try:
        sync_course_to_sheets(course_code)
        await update.message.reply_text(f"✅ {course_code} শীট আপডেট হয়ে গেছে।")
    except Exception as e:
        logger.error("Manual sync failed: %s", e)
        await update.message.reply_text(f"❌ Sync ব্যর্থ হয়েছে: {e}")


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable not set")

    init_db()

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("register22", register22))
    app.add_handler(CommandHandler("classdone", classdone))
    app.add_handler(CommandHandler("attendance", attendance))
    app.add_handler(CommandHandler("totalattendance", total_attendance))
    app.add_handler(CommandHandler("sync", sync_now))
    app.add_handler(CallbackQueryHandler(button_callback, pattern=r"^att:"))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
