# Telegram Attendance Bot

A Telegram bot that tracks class attendance for a study group and syncs it to Google Sheets in real time.

## How it works

1. Each student DMs the bot once with `/start`
2. Students enroll in their courses (`/register CSE2201DMS` or `/register22` to join all Level 2-2 courses at once)
3. When a class happens, anyone in the group runs `/classdone CSE2201DMS`
4. The bot DMs every enrolled student with a Yes/No inline button
5. Responses are stored in SQLite and pushed to a shared Google Sheet (one tab per course)

## Commands

| Command | Description |
|---|---|
| `/start` | Register with the bot (required before it can DM you) |
| `/register <code>` | Enroll in a single course |
| `/register22` | Enroll in all Level 2-2 courses at once |
| `/classdone <code>` | (group only) Trigger an attendance check for a course |
| `/attendance <code>` | View your attendance for one course |
| `/totalattendance` | View your average attendance across all enrolled courses |
| `/sync <code>` | Manually push a course's attendance table to Google Sheets |

## Tech stack

- **Python** + [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- **SQLite** for attendance storage
- **Google Sheets API** for live, shared attendance tracking
- Deployed on an **Azure VM** (Ubuntu 22.04) running as a systemd service

## Setup

```bash
pip install -r requirements.txt
export BOT_TOKEN="your-bot-token-from-BotFather"
python bot.py
```

Optional — Google Sheets sync:

```bash
export GOOGLE_CREDENTIALS_FILE="credentials.json"
export GOOGLE_SHEETS_SPREADSHEET_ID="your-spreadsheet-id"
```

Requires a Google Cloud service account with the Sheets API enabled; share your spreadsheet with the service account's email as an Editor.

## Course list

Edit the `CURRICULUM` list in `bot.py` to change which courses `/register22` enrolls students into.
