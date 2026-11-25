#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BTC SPOT HUNTER - Multi Timeframe Cartel Hunter
تایم‌فریم‌ها: 5m ، 15m ، 30m ، 1h ، 4h
فقط اسپات (Spot) - بدون اهرم
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
RSI_PERIOD = 14

# تایم‌فریم‌ها و برچسب فارسی‌شان
TIMEFRAMES = {
    "5m":  "۵ دقیقه",
    "15m": "۱۵ دقیقه",
    "30m": "۳۰ دقیقه",
    "1h":  "۱ ساعته",
    "4h":  "۴ ساعته",
}

# فاصله تایمر خودکار: هر ۱۵ دقیقه (برای هر پنج تایم‌فریم)
AUTO_INTERVAL = 15 * 60   # ۹۰۰ ثانیه

send_lock = threading.Lock()


# ═══════════════════════════════════════════════
# دریافت داده
# ═══════════════════════════════════════════════
def api_get(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "SpotHunter/3.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def fetch_candles(symbol, interval, limit=300):
    rows = api_get("/api/v3/klines", {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    })
    now_ms = int(time.time() * 1000)
    rows = [x for x in rows if int(x[6]) < now_ms]  # فقط کندل بسته‌شده
    if len(rows) < RSI_PERIOD + 5:
        raise RuntimeError(f"داده کافی نیست برای {interval}")
    return {
        "close": [float(x[4]) for x in rows],
        "high": [float(x[2]) for x in rows],
        "low": [float(x[3]) for x in rows],
        "volume": [float(x[5]) for x in rows],
        "time": [int(x[0]) for x in rows],
    }


# ═══════════════════════════════════════════════
# RSI
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
# منطق شکارچی کارتل (برای یک تایم‌فریم)
# ═══════════════════════════════════════════════
def analyze_tf(timeframe):
    data = fetch_candles(SYMBOL, timeframe, limit=300)
    closes = data["close"]
    rsi_values = rsi(closes, RSI_PERIOD)
    current_rsi = rsi_values[-1]
    price = closes[-1]

    if current_rsi is None:
        raise RuntimeError(f"RSI محاسبه نشد برای {timeframe}")

    if current_rsi < 30:
        signal = "🟢 خرید اسپات (Spot Buy)"
        reason = (
            "RSI زیر ۳۰ است. همه از ترس دارند می‌فروشند. "
            "کارتل دارد می‌ترساند و کف بازار شکل گرفته."
        )
        action = "خرید"
    elif current_rsi > 70:
        signal = "🔴 فروش اسپات (Spot Sell)"
        reason = (
            "RSI بالای ۷۰ است. همه با طمع دارند می‌خرند. "
            "کارتل دارد پوزیشن‌هایش را خالی می‌کند."
        )
        action = "فروش"
    else:
        signal = "🟡 صبر کن (معامله نکن)"
        reason = (
            "RSI بین ۳۰ تا ۷۰ است. بازار خنثی. "
            "کارتل هنوز حرکت اصلی‌اش را شروع نکرده."
        )
        action = "صبر"

    return {
        "timeframe": timeframe,
        "tf_fa": TIMEFRAMES.get(timeframe, timeframe),
        "price": price,
        "rsi": current_rsi,
        "signal": signal,
        "reason": reason,
        "action": action,
    }


def analyze_all():
    results = {}
    errors = {}
    for tf in TIMEFRAMES.keys():
        try:
            results[tf] = analyze_tf(tf)
        except Exception as e:
            errors[tf] = str(e)
    return results, errors


# ═══════════════════════════════════════════════
# تلگرام
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
    params = {"timeout": 30, "drop_pending_updates": True}
    if offset:
        params["offset"] = offset
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=TIMEOUT + 10) as r:
        return json.loads(r.read().decode())


# ═══════════════════════════════════════════════
# ساخت پیام
# ═══════════════════════════════════════════════
def build_single_message(r, auto=False):
    head = "🔔 هشدار خودکار کارتل" if auto else "🕵️‍♂️ گزارش شکارچی کارتل"
    lines = [
        head,
        "━━━━━━━━━━━━━━━━━━",
        f"جفت‌ارز: {SYMBOL_NAME} ({SYMBOL})",
        f"تایم‌فریم: {r['tf_fa']} ({r['timeframe']})",
        "",
        f"قیمت فعلی: ${r['price']:,.2f}",
        f"RSI ({RSI_PERIOD}): {r['rsi']:.2f}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"سیگنال: {r['signal']}",
        "",
        "تحلیل:",
        r["reason"],
        "━━━━━━━━━━━━━━━━━━",
        "⚠️ فقط بازار اسپات — بدون اهرم",
    ]
    if auto:
        lines.append("⏰ این تحلیل هر ۱۵ دقیقه خودکار ارسال می‌شود")
    return "\n".join(lines)


def build_all_message(results, errors, auto=False):
    head = "🔔 تحلیل خودکار همه تایم‌فریم‌ها" if auto else "🕵️‍♂️ تحلیل همه تایم‌فریم‌ها"
    lines = [
        head,
        "━━━━━━━━━━━━━━━━━━",
        f"جفت‌ارز: {SYMBOL_NAME} ({SYMBOL})",
        "",
    ]

    buy_count = sell_count = wait_count = 0

    for tf, tf_fa in TIMEFRAMES.items():
        if tf in errors:
            lines.append(f"⚠️ {tf_fa}: خطا ({errors[tf]})")
            lines.append("")
            continue

        r = results[tf]
        if r["action"] == "خرید":
            buy_count += 1
        elif r["action"] == "فروش":
            sell_count += 1
        else:
            wait_count += 1

        lines.append(f"📊 {tf_fa} ({tf})")
        lines.append(f"   قیمت: ${r['price']:,.2f}")
        lines.append(f"   RSI: {r['rsi']:.2f}")
        lines.append(f"   سیگنال: {r['signal']}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("جمع‌بندی:")
    lines.append(f"🟢 خرید: {buy_count} | 🔴 فروش: {sell_count} | 🟡 صبر: {wait_count}")

    if buy_count >= 3:
        lines.append("✅ حداقل سه تایم‌فریم سیگنال خرید می‌دهند — فرصت قوی")
    elif sell_count >= 3:
        lines.append("✅ حداقل سه تایم‌فریم سیگنال فروش می‌دهند — فرصت قوی")
    elif buy_count >= 2:
        lines.append("⚠️ دو تایم‌فریم خرید می‌دهند — با احتیاط وارد شو")
    elif sell_count >= 2:
        lines.append("⚠️ دو تایم‌فریم فروش می‌دهند — با احتیاط خارج شو")
    elif buy_count == 1:
        lines.append("⚠️ فقط یک تایم‌فریم خرید می‌دهد — با احتیاط وارد شو")
    elif sell_count == 1:
        lines.append("⚠️ فقط یک تایم‌فریم فروش می‌دهد — با احتیاط خارج شو")
    else:
        lines.append("⚪ هیچ سیگنال همسویی بین تایم‌فریم‌ها نیست — صبر کن")

    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ فقط بازار اسپات — بدون اهرم")
    if auto:
        lines.append("⏰ این تحلیل هر ۱۵ دقیقه خودکار ارسال می‌شود")
    return "\n".join(lines)


# ═══════════════════════════════════════════════
# کیبورد
# ═══════════════════════════════════════════════
def main_keyboard():
    return {
        "keyboard": [
            [{"text": "🕵️‍♂️ تحلیل همه تایم‌فریم‌ها"}],
            [{"text": "📊 ۵ دقیقه"}, {"text": "📊 ۱۵ دقیقه"}, {"text": "📊 ۳۰ دقیقه"}],
            [{"text": "📊 ۱ ساعته"}, {"text": "📊 ۴ ساعته"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


# ═══════════════════════════════════════════════
# اجرای تحلیل
# ═══════════════════════════════════════════════
def run_single(chat_id, tf, auto=False):
    try:
        if not auto:
            send_message(f"⏳ در حال تحلیل {TIMEFRAMES[tf]}...", chat_id=chat_id)
        r = analyze_tf(tf)
        msg = build_single_message(r, auto=auto)
        send_message(msg, chat_id=chat_id, keyboard=main_keyboard())
        print(f"[{'AUTO' if auto else 'MANUAL'}] {tf} → {r['action']} | RSI={r['rsi']:.2f}")
    except Exception as e:
        send_message(f"❌ خطا در تحلیل {TIMEFRAMES[tf]}:\n{str(e)}",
                     chat_id=chat_id, keyboard=main_keyboard())
        print(f"Analysis error ({tf}):", e)


def run_all(chat_id, auto=False):
    try:
        if not auto:
            send_message("⏳ در حال تحلیل همه تایم‌فریم‌ها...", chat_id=chat_id)
        results, errors = analyze_all()
        if not results and errors:
            send_message("❌ هیچ تایم‌فریمی تحلیل نشد:\n" + json.dumps(errors, ensure_ascii=False),
                         chat_id=chat_id, keyboard=main_keyboard())
            return
        msg = build_all_message(results, errors, auto=auto)
        send_message(msg, chat_id=chat_id, keyboard=main_keyboard())
        summary = ", ".join(f"{tf}={results[tf]['action']}" for tf in results)
        print(f"[{'AUTO' if auto else 'MANUAL'}] ALL → {summary}")
    except Exception as e:
        send_message(f"❌ خطا در تحلیل همه:\n{str(e)}",
                     chat_id=chat_id, keyboard=main_keyboard())
        print("Analysis ALL error:", e)


# ═══════════════════════════════════════════════
# تایمر خودکار — هر ۱۵ دقیقه
# ═══════════════════════════════════════════════
def auto_hunter():
    print(f"⏰ Auto Hunter started (every {AUTO_INTERVAL // 60} minutes)")
    while True:
        time.sleep(AUTO_INTERVAL)
        if not CHAT:
            continue
        print("⏰ Running auto analysis (all 5 timeframes)...")
        run_all(CHAT, auto=True)


# ═══════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════
def main():
    if not TOKEN:
        print("❌ BOT_TOKEN در متغیرهای محیطی تنظیم نشده!")
        sys.exit(1)

    print("🚀 Spot Hunter Bot is running (5m/15m/30m/1h/4h)...")
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

                if CHAT and chat_id != CHAT:
                    continue

                if text in ["/start", "شروع", "استارت"]:
                    welcome = (
                        "🕵️‍♂️ به ربات شکارچی کارتل خوش آمدید\n\n"
                        "این ربات در پنج تایم‌فریم تحلیل می‌کند:\n"
                        "• ۵ دقیقه\n"
                        "• ۱۵ دقیقه\n"
                        "• ۳۰ دقیقه\n"
                        "• ۱ ساعته\n"
                        "• ۴ ساعته\n\n"
                        "منطق کار:\n"
                        "• RSI زیر ۳۰ ← 🟢 خرید اسپات\n"
                        "• RSI بالای ۷۰ ← 🔴 فروش اسپات\n"
                        "• بین ۳۰ تا ۷۰ ← 🟡 صبر کن\n\n"
                        "می‌توانی هر تایم‌فریم را جدا ببینی یا همه را با هم.\n"
                        "⏰ هر ۱۵ دقیقه هم خودکار همه تایم‌فریم‌ها را تحلیل می‌کنم."
                    )
                    send_message(welcome, chat_id=chat_id, keyboard=main_keyboard())

                elif text in ["🕵️‍♂️ تحلیل همه تایم‌فریم‌ها", "همه تایم‌فریم‌ها", "همه"]:
                    threading.Thread(target=run_all, args=(chat_id,), daemon=True).start()

                elif text == "📊 ۵ دقیقه":
                    threading.Thread(target=run_single, args=(chat_id, "5m"), daemon=True).start()

                elif text == "📊 ۱۵ دقیقه":
                    threading.Thread(target=run_single, args=(chat_id, "15m"), daemon=True).start()

                elif text == "📊 ۳۰ دقیقه":
                    threading.Thread(target=run_single, args=(chat_id, "30m"), daemon=True).start()

                elif text == "📊 ۱ ساعته":
                    threading.Thread(target=run_single, args=(chat_id, "1h"), daemon=True).start()

                elif text == "📊 ۴ ساعته":
                    threading.Thread(target=run_single, args=(chat_id, "4h"), daemon=True).start()

                elif text in ["/stop", "توقف", "قطع"]:
                    send_message(
                        "🛑 برای قطع کامل ربات، در GitHub Actions آن را غیرفعال کن.",
                        chat_id=chat_id,
                    )

                else:
                    send_message(
                        "از دکمه‌های زیر استفاده کن 👇",
                        chat_id=chat_id,
                        keyboard=main_keyboard(),
                    )

        except Exception as e:
            print("Polling error:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
