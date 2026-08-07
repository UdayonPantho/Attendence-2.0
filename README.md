# Attendance Bot — Setup Guide

## ধাপ ১: Telegram Bot বানানো
1. Telegram-এ **@BotFather** কে খোঁজো, chat শুরু করো
2. `/newbot` লিখো, নাম আর username দাও (username শেষে অবশ্যই `bot` থাকতে হবে, যেমন `csc1100_attendance_bot`)
3. BotFather তোমাকে একটা **token** দিবে, এমন দেখতে: `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
   এটা secret — কারো সাথে শেয়ার করবে না।

## ধাপ ২: কোড চালানো (নিজের কম্পিউটারে টেস্ট করার জন্য)
```bash
pip install -r requirements.txt
export BOT_TOKEN="তোমার-token-এখানে-বসাও"
python bot.py
```
(Windows-এ `export` এর বদলে `set BOT_TOKEN=...` লিখবে)

এটা চলতে থাকলে বট online থাকবে। কম্পিউটার বন্ধ করলে বট বন্ধ হয়ে যাবে —
তাই ২৪ ঘণ্টা চালু রাখতে হলে নিচের hosting অংশ দেখো।

## ধাপ ৩: বট-কে group-এ add করা
1. তোমার study group-এ বট-কে add করো (member হিসেবে invite)
2. Group-এর প্রতিটা member personally বট-কে `/start` লিখে পাঠাক
   (এটা must — নাহলে বট তাদের DM করতে পারবে না, এটা Telegram-এর নিয়ম)

## ধাপ ৪: ব্যবহার
- একটা মাত্র course register করতে (personal chat-এ):
  `/register CSE2201DMS`
- 2-2 লেভেলের সবগুলো (৯টা) কোর্সে একসাথে register করতে:
  `/register22`
- Class শেষ হলে group-এ যেকেউ লিখবে:
  `/classdone CSE2201DMS`
  → বট তখন সবাইকে personally DM করে Yes/No জিজ্ঞেস করবে
- নির্দিষ্ট একটা কোর্সের attendance দেখতে (personal chat-এ):
  `/attendance CSE2201DMS`
- সবগুলো কোর্স মিলিয়ে গড় attendance দেখতে:
  `/totalattendance`

## Course List (হার্ডকোড করা আছে bot.py-তে)
```
CSE2201DMS
CSE2202DMSLAB
CSE2203CAO
CSE2204DAA
CSE2205DAALAB
CSE2206MAL
CSE2207MALLAB
CSE2208SDWITHJAVALAB
STAT2209PSA
```
নতুন course যোগ/বাদ দিতে চাইলে `bot.py`-এর ভেতরে `CURRICULUM` লিস্টটা এডিট করলেই হবে।

## ২৪/৭ Hosting (ফ্রি/সস্তা অপশন)
নিজের কম্পিউটার সবসময় চালু রাখা অবাস্তব, তাই কোথাও deploy করতে হবে। সহজ অপশনগুলো:

- **Railway.app** — GitHub repo connect করলেই deploy হয়ে যায়, ছোট বটের জন্য free tier যথেষ্ট
- **Render.com** — "Background Worker" হিসেবে deploy করা যায়
- **Azure for Students** — university email দিয়ে card ছাড়াই sign up করা যায়, $100 credit + "Always Free" VM (B1s) চিরকাল ফ্রি

এই তিনটার যেকোনো একটায়:
1. এই ফাইলগুলো (`bot.py`, `sheets_sync.py`, `requirements.txt`) একটা GitHub repo-তে push করো
2. Hosting platform-এ repo connect করো
3. Environment variable হিসেবে `BOT_TOKEN` সেট করো
4. Start command: `python bot.py`

## Database সম্পর্কে
এখন এটা SQLite ব্যবহার করছে (`attendance.db` নামের একটা ফাইল, নিজে থেকেই তৈরি হয়ে যাবে)।
ছোট study group-এর জন্য এটা যথেষ্ট। বড় হলে পরে PostgreSQL-এ migrate করা যাবে।

---

## Google Sheets Sync (optional, একজন admin সেট করবে)

এটা সেট করলে প্রতিটা course-এর জন্য একটা shared Google Sheet-এ আলাদা tab
(worksheet)-এ date-wise attendance টেবিল automatic আপডেট হতে থাকবে (কেউ Yes/No
দেওয়ার ~১ মিনিট পরে, বা `/sync CSE2201DMS` দিয়ে manually)।

### ধাপ ১: Google Cloud project বানানো
1. https://console.cloud.google.com -এ যাও, নতুন project বানাও
2. **APIs & Services > Library** থেকে এই API-টা enable করো:
   - Google Sheets API

### ধাপ ২: Service Account বানানো (এটাই bot-এর "Google account")
1. **APIs & Services > Credentials > Create Credentials > Service Account**
2. নাম দিয়ে তৈরি করো, তারপর সেই service account-এ ঢুকে **Keys > Add Key > Create new key > JSON**
3. একটা `.json` ফাইল ডাউনলোড হবে — এর নাম `credentials.json` রেখে বটের ফোল্ডারে রাখো
4. JSON ফাইলটার ভেতরে `"client_email"` নামে একটা email থাকবে — এটা এখন লাগবে

### ধাপ ৩: Google Sheet বানানো
1. https://sheets.google.com -এ নতুন একটা spreadsheet বানাও
   (এটাই হবে সবার shared attendance sheet, প্রতিটা course একটা করে tab পাবে)
2. এটা **Share** করো, উপরের ধাপে পাওয়া service account-এর email-কে
   **Editor** access দিয়ে add করো
3. URL থেকে spreadsheet ID কপি করো:
   `https://docs.google.com/spreadsheets/d/`**`THIS_LONG_ID`**`/edit`

### ধাপ ৪: Environment variables সেট করা
```bash
export GOOGLE_CREDENTIALS_FILE="credentials.json"
export GOOGLE_SHEETS_SPREADSHEET_ID="উপরের ধাপ থেকে পাওয়া ID"
export ADMIN_IDS="তোমার-telegram-user-id"   # optional, খালি রাখলে সবাই /sync চালাতে পারবে
```
নিজের Telegram user ID জানতে **@userinfobot** কে message করো।

### ধাপ ৫: টেস্ট করা
```bash
python sheets_sync.py CSE2201DMS
```
এটা ঠিকঠাক চললে Sheet-এ গিয়ে দেখবে CSE2201DMS নামের একটা নতুন tab এসেছে,
তাতে date-wise attendance table বসানো আছে।

এরপর `python bot.py` চালালে বট নিজে থেকেই প্রতিটা response-এর পর sheet sync করবে,
আর group-এ `/sync CSE2201DMS` লিখলেও force sync হবে।

## বটের নাম বদলানো (BotFather দিয়ে, কোডে না)
1. Telegram-এ **@BotFather**-কে message করো
2. `/mybots` লিখো, তোমার বট সিলেক্ট করো
3. **Edit Bot > Edit Name** সিলেক্ট করো
4. নতুন নাম লিখে পাঠাও — সাথে সাথেই বদলে যাবে (username, অর্থাৎ `@csc2201_DMS_attendance_bot` অংশটা এভাবে বদলানো যায় না, শুধু display name বদলায়)
