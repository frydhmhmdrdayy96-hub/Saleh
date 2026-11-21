#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BTC SPOT HUNTER - Cartel Hunter Bot
منطق: شکار ریز موج‌های کارتل در تایم‌فریم 4 ساعته
فقط اسپات (Spot) - بدون اهرم، بدون فیوچرز
"""

import os
import sys
import json
import time
import threading
import urllib.request
import urllib.parse

# ═══════════════════════════════════════════════
# تنظیمات
# ═══════════════════════════════════════════════
BASE = "https://data-api.binance.vision"
TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT = os.getenv("ALLOWED_CHAT_ID", "").strip()
TIMEOUT = 25

SYMBOL = "BTCUSDT"
SYMBOL_NAME = "بیت کوین"
TIMEFRAME = "4h"
RSI_PERIOD = 14

# فاصله تایمر خودکار: هر ۴ ساعت = ۱۴۴۰۰ ثانیه
AUTO_INTERVAL = 4 * 60 * 60

# قفل برای جلوگیری از ارسال همزمان
send_lock = threading.Lock()


# ═══════════════════════════════════════════════
# دریافت داده از بایننس
# ═══════════════════════════════════════════════
def api_get(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "SpotHunter/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def fetch_candles(symbol, interval, limit=300):
    """دریافت کندل‌های بسته‌شده (بدون کندل جاری)."""
    rows = api_get("/api/v3/klines", {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    })
    now_ms = int(time.time() * 1000)
    rows = [x for x in rows if int(x[6]) < now_ms]  # فقط کندل بسته‌شده
    if len(rows) < RSI_PERIOD + 5:
        raise RuntimeError("داده کافی نیست برای محاسبه RSI")
    return {
        "close": [float(x[4]) for x in rows],
        "high": [float(x[2]) for x in rows],
        "low": [float(x[3]) for x in rows],
        "volume": [float(x[5]) for x in rows],
        "time": [int(x[0]) for x in rows],
    }


# ═══════════════════════════════════════════════
# محاسبه RSI (Wilder's Smoothing)
# ═══════════════════════════════════════════════
def rsi(values, period=14):
    out = [None] * len(values)
    if len(values) <= period:
        return out

    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _calc(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        rs = g / l
        return 100.0 - (100.0 / (1.0 + rs))

    out[period] = _calc(avg_gain, avg_loss)

    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = _calc(avg_gain, avg_loss)

    return out


# ═══════════════════════════════════════════════
# منطق شکارچی کارتل
# ═══════════════════════════════════════════════
def analyze_market():
    data = fetch_candles(SYMBOL, TIMEFRAME, limit=300)
    closes = data["close"]
    rsi_values = rsi(closes, RSI_PERIOD)
    current_rsi = rsi_values[-1]
    price = closes[-1]

    if current_rsi is None:
        raise RuntimeError("RSI محاسبه نشد")

    # ─── تشخیص سیگنال ───
    if current_rsi < 30:
        signal = "🟢 خرید اسپات (Spot Buy)"
        reason = (
            "RSI زیر ۳۰ است. همه از ترس دارند می‌فروشند. "
            "کارتل دارد می‌ترساند و کف بازار شکل گرفته. "
            "فرصت خرید در بازار اسپات."
        )
        action = "خرید"
    elif current_rsi > 70:
        signal = "🔴 فروش اسپات (Spot Sell)"
        reason = (
            "RSI بالای ۷۰ است. همه با طمع دارند می‌خرند. "
            "کارتل دارد پوزیشن‌هایش را خالی می‌کند. "
            "زمان فروش و نقد کردن سود."
        )
        action = "فروش"
    else:
        signal = "🟡 صبر کن (معامله نکن)"
        reason = (
            "RSI بین ۳۰ تا ۷۰ است. بازار در حالت خنثی و بدون تصمیم. "
            "کارتل هنوز حرکت اصلی‌اش را شروع نکرده. "
            "صبر کن تا بازار به یکی از دو ناحیه برسد."
        )
        action = "صبر"

    return {
        "price": price,
        "rsi": current_rsi,
        "signal": signal,
        "reason": reason,
        "action": action,
    }


# ═══════════════════════════════════════════════
# ارسال پیام تلگرام (Plain Text)
# ═══════════════════════════════════════════════
def send_message(text, chat_id=None, keyboard=None):
    if not TOKEN:
        print("BOT_TOKEN تنظیم نشده")
        return
    target = chat_id or CHAT
    if not target:
        print("CHAT_ID تنظیم نشده")
        return

    url = "https://api.telegram.org/bot" + TOKEN + "/sendMessage"
    payload = {"chat_id": target, "text": text}
    if keyboard:
        payload["reply_markup"] = json.dumps(keyboard)

    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=data)

    with send_lock:
        try:
            urllib.request.urlopen(req, timeout=TIMEOUT)
        except Exception as e:
            print("Telegram send error:", e)


def get_updates(offset=None):
    url = "https://api.telegram.org/bot" + TOKEN + "/getUpdates"
    params = {
        "timeout": 30,
        "drop_pending_updates": True,  # جلوگیری از پیام‌های تکراری بعد از ری‌استارت
    }
    if offset:
        params["offset"] = offset

    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=TIMEOUT + 10) as r:
        return json.loads(r.read().decode())


# ═══════════════════════════════════════════════
# ساخت پیام تحلیل
# ═══════════════════════════════════════════════
def build_message(result, auto=False):
    head = "🔔 هشدار خودکار کارتل" if auto else "🕵️‍♂️ گزارش شکارچی کارتل"
    lines = [
        head,
        "━━━━━━━━━━━━━━━━━━",
        f"جفت‌ارز: {SYMBOL_NAME} ({SYMBOL})",
        f"تایم‌فریم: {TIMEFRAME}",
        "",
        f"قیمت فعلی: ${result['price']:,.2f}",
        f"RSI ({RSI_PERIOD}): {result['rsi']:.2f}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"سیگنال: {result['signal']}",
        "",
        f"تحلیل:",
        result["reason"],
        "━━━━━━━━━━━━━━━━━━",
        "⚠️ فقط بازار اسپات — بدون اهرم و فیوچرز",
    ]
    if auto:
        lines.append("⏰ این تحلیل هر ۴ ساعت خودکار ارسال می‌شود")
    return "\n".join(lines)


# ═══════════════════════════════════════════════
# کیبورد
# ═══════════════════════════════════════════════
def main_keyboard():
    return {
        "keyboard": [[{"text": "🕵️‍♂️ بررسی بازار"}]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


# ═══════════════════════════════════════════════
# اجرای تحلیل و ارسال
# ═══════════════════════════════════════════════
def run_analysis(chat_id, auto=False):
    try:
        if not auto:
            send_message("⏳ در حال بررسی بازار...", chat_id=chat_id)
        result = analyze_market()
        msg = build_message(result, auto=auto)
        send_message(msg, chat_id=chat_id, keyboard=main_keyboard())
        print(f"[{'AUTO' if auto else 'MANUAL'}] Signal: {result['action']} | RSI={result['rsi']:.2f}")
    except Exception as e:
        err = f"❌ خطا در تحلیل بازار:\n{str(e)}"
        send_message(err, chat_id=chat_id, keyboard=main_keyboard())
        print("Analysis error:", e)


# ═══════════════════════════════════════════════
# تایمر خودکار (هر ۴ ساعت)
# ═══════════════════════════════════════════════
def auto_hunter():
    print(f"⏰ Auto Hunter started (every {AUTO_INTERVAL // 3600} hours)")
    while True:
        time.sleep(AUTO_INTERVAL)
        if not CHAT:
            continue
        print("⏰ Running auto analysis...")
        run_analysis(CHAT, auto=True)


# ═══════════════════════════════════════════════
# حلقه اصلی ربات
# ═══════════════════════════════════════════════
def main():
    if not TOKEN:
        print("❌ BOT_TOKEN در متغیرهای محیطی تنظیم نشده!")
        sys.exit(1)

    print("🚀 Spot Hunter Bot is running...")

    # شروع تایمر خودکار
    threading.Thread(target=auto_hunter, daemon=True).start()

    last_update_id = None

    while True:
        try:
            updates = get_updates(last_update_id)
            if not updates.get("ok"):
                time.sleep(3)
                continue

            for update in updates["result"]:
                last_update_id = update["update_id"] + 1

                if "message" not in update or "text" not in update["message"]:
                    continue

                text = update["message"]["text"].strip()
                chat_id = str(update["message"]["chat"]["id"])

                # فقط چت مجاز
                if CHAT and chat_id != CHAT:
                    continue

                # ─── /start ───
                if text in ["/start", "شروع", "استارت"]:
                    welcome = (
                        "🕵️‍♂️ به ربات شکارچی کارتل خوش آمدید\n\n"
                        "این ربات فقط در تایم‌فریم ۴ ساعته کار می‌کند،\n"
                        "چون تایم‌فریم‌های پایین زمین بازی دستکاری‌شده‌ی کارتل هستند.\n\n"
                        "منطق کار:\n"
                        "• RSI زیر ۳۰ ← 🟢 خرید اسپات\n"
                        "• RSI بالای ۷۰ ← 🔴 فروش اسپات\n"
                        "• بین ۳۰ تا ۷۰ ← 🟡 صبر کن\n\n"
                        "برای شروع، دکمه زیر را بزن:\n"
                        "⏰ هر ۴ ساعت هم خودکار تحلیل می‌فرستم."
                    )
                    send_message(welcome, chat_id=chat_id, keyboard=main_keyboard())

                # ─── دکمه بررسی بازار ───
                elif text in ["🕵️‍♂️ بررسی بازار", "بررسی بازار", "بررسی", "/analyze"]:
                    threading.Thread(
                        target=run_analysis,
                        args=(chat_id,),
                        daemon=True,
                    ).start()

                # ─── /stop ───
                elif text in ["/stop", "توقف", "قطع"]:
                    send_message(
                        "🛑 برای قطع کامل ربات، در GitHub Actions آن را غیرفعال کن.\n"
                        "تایمر خودکار همچنان کار می‌کند.",
                        chat_id=chat_id,
                    )

                # ─── هر پیام دیگری ───
                else:
                    send_message(
                        "برای بررسی بازار، دکمه زیر را بزن 👇",
                        chat_id=chat_id,
                        keyboard=main_keyboard(),
                    )

        except Exception as e:
            print("Polling error:", e)
            time.sleep(5)


# ═══════════════════════════════════════════════
if __name__ == "__main__":
    main()
