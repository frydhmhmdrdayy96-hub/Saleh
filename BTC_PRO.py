#!/usr/bin/env python3
# BTC PRO Telegram analyst | Android / Termux | Python standard library only
# Rule-based technical confluence, NOT a statistically calibrated win probability.

import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Fill these two values before running.
BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID", "PASTE_TELEGRAM_CHAT_ID")

SYMBOL = "BTCUSDT"
BINANCE_BASE = "https://api.binance.com"
CHECK_AFTER_HOUR_MINUTE = 3  # analyze after the UTC hourly candle has closed
REQUEST_TIMEOUT = 25
MAX_RETRIES = 3

TIMEFRAMES = {"15m": 0.15, "1h": 0.35, "4h": 0.30, "1d": 0.20}
MIN_SIGNAL_SCORE = 72
MIN_DIRECTION_GAP = 14


def http_json(url, data=None):
    body = None if data is None else urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"User-Agent": "BTC-PRO-Telegram/3.0", "Accept": "application/json"}
    )
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if isinstance(payload, dict) and payload.get("code") is not None:
                    raise RuntimeError(f"خطای API: {payload}")
                return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"ارتباط با سرویس برقرار نشد: {last_error}")


def get_candles(interval, limit=250):
    url = (f"{BINANCE_BASE}/api/v3/klines?symbol={SYMBOL}"
           f"&interval={interval}&limit={limit}")
    rows = http_json(url)
    if not isinstance(rows, list) or len(rows) < 80:
        raise RuntimeError(f"داده کافی از Binance برای تایم‌فریم {interval} دریافت نشد.")
    # Discard the currently-forming candle. All analysis uses closed candles only.
    now_ms = int(time.time() * 1000)
    # Keep only candles whose close time has passed; avoids relying on array position.
    candles = [{
        "open_time": int(r[0]), "open": float(r[1]), "high": float(r[2]),
        "low": float(r[3]), "close": float(r[4]), "volume": float(r[5]),
        "close_time": int(r[6]),
    } for r in rows if int(r[6]) < now_ms]
    if len(candles) < 205:
        raise RuntimeError(f"برای محاسبه EMA200 در تایم‌فریم {interval} حداقل ۲۰۵ کندل بسته‌شده لازم است؛ دریافت شد: {len(candles)}")
    for c in candles:
        if not all(math.isfinite(c[k]) for k in ("open", "high", "low", "close", "volume")):
            raise RuntimeError(f"داده نامعتبر در تایم‌فریم {interval}")
        if c["high"] < max(c["open"], c["close"]) or c["low"] > min(c["open"], c["close"]):
            raise RuntimeError(f"OHLC نامعتبر در تایم‌فریم {interval}")
    return candles


def ema(values, period):
    if len(values) < period:
        raise ValueError(f"Not enough data for EMA{period}")
    alpha = 2.0 / (period + 1.0)
    out = [None] * (period - 1)
    current = sum(values[:period]) / period
    out.append(current)
    for value in values[period:]:
        current = alpha * value + (1.0 - alpha) * current
        out.append(current)
    return out


def rsi(values, period=14):
    if len(values) <= period:
        raise ValueError("Not enough data for RSI")
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out = [None] * period
    out.append(100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss))
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out.append(100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss))
    return out


def macd(values):
    e12, e26 = ema(values, 12), ema(values, 26)
    line = [None if a is None or b is None else a - b for a, b in zip(e12, e26)]
    valid = [x for x in line if x is not None]
    sig_valid = ema(valid, 9)
    signal = [None] * (len(line) - len(sig_valid)) + sig_valid
    hist = [None if a is None or b is None else a - b for a, b in zip(line, signal)]
    return line, signal, hist


def atr(candles, period=14):
    trs = []
    for i, c in enumerate(candles):
        prev = candles[i - 1]["close"] if i else c["close"]
        trs.append(max(c["high"] - c["low"], abs(c["high"] - prev), abs(c["low"] - prev)))
    return sum(trs[-period:]) / min(period, len(trs))


def adx_estimate(candles, period=14):
    # Smoothed directional movement estimate, used as a trend-strength filter.
    plus, minus, tr = [], [], []
    for i in range(1, len(candles)):
        cur, prev = candles[i], candles[i - 1]
        up = cur["high"] - prev["high"]
        down = prev["low"] - cur["low"]
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
        tr.append(max(cur["high"] - cur["low"], abs(cur["high"] - prev["close"]),
                      abs(cur["low"] - prev["close"])))
    tr_sum = sum(tr[-period:])
    if tr_sum <= 0:
        return 0.0
    pdi = 100.0 * sum(plus[-period:]) / tr_sum
    mdi = 100.0 * sum(minus[-period:]) / tr_sum
    return 0.0 if pdi + mdi == 0 else 100.0 * abs(pdi - mdi) / (pdi + mdi)


def pivot_levels(candles, lookback=100):
    sample = candles[-lookback:]
    highs, lows = [], []
    for i in range(2, len(sample) - 2):
        h, l = sample[i]["high"], sample[i]["low"]
        if all(h > sample[j]["high"] for j in (i - 2, i - 1, i + 1, i + 2)):
            highs.append(h)
        if all(l < sample[j]["low"] for j in (i - 2, i - 1, i + 1, i + 2)):
            lows.append(l)
    return highs, lows


def nearest_level(levels, price, above):
    candidates = [x for x in levels if x > price] if above else [x for x in levels if x < price]
    if not candidates:
        return None
    return min(candidates) if above else max(candidates)


def divergence(candles, rsi_values):
    # Simple two-pivot divergence check; informational, not a standalone signal.
    lows, highs = [], []
    for i in range(2, len(candles) - 2):
        if candles[i]["low"] < min(candles[j]["low"] for j in (i-2, i-1, i+1, i+2)):
            lows.append(i)
        if candles[i]["high"] > max(candles[j]["high"] for j in (i-2, i-1, i+1, i+2)):
            highs.append(i)
    bull = bear = False
    if len(lows) >= 2:
        a, b = lows[-2:]
        bull = candles[b]["low"] < candles[a]["low"] and rsi_values[b] > rsi_values[a] + 2
    if len(highs) >= 2:
        a, b = highs[-2:]
        bear = candles[b]["high"] > candles[a]["high"] and rsi_values[b] < rsi_values[a] - 2
    return bull, bear


def analyze_timeframe(candles):
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    e20, e50, e200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    rs = rsi(closes)
    _, _, hist = macd(closes)
    i, last = len(candles) - 1, candles[-1]
    price = last["close"]
    up = down = 0
    up_reasons, down_reasons = [], []

    def score(up_ok, down_ok, points, up_text, down_text):
        nonlocal up, down
        if up_ok:
            up += points
            up_reasons.append(up_text)
        if down_ok:
            down += points
            down_reasons.append(down_text)

    score(price > e20[i], price < e20[i], 8, "قیمت بالای EMA20", "قیمت زیر EMA20")
    score(e20[i] > e50[i], e20[i] < e50[i], 12, "EMA20 بالای EMA50", "EMA20 زیر EMA50")
    score(e50[i] > e200[i], e50[i] < e200[i], 10, "EMA50 بالای EMA200", "EMA50 زیر EMA200")
    score(52 <= rs[i] <= 70, 30 <= rs[i] <= 48, 8,
          f"RSI مساعد صعود ({rs[i]:.1f})", f"RSI مساعد نزول ({rs[i]:.1f})")
    score(hist[i] > 0, hist[i] < 0, 9, "هیستوگرام MACD مثبت", "هیستوگرام MACD منفی")
    avg_volume = sum(volumes[-21:-1]) / 20
    vol_ratio = volumes[-1] / avg_volume if avg_volume else 0.0
    score(vol_ratio >= 1.2 and last["close"] > last["open"],
          vol_ratio >= 1.2 and last["close"] < last["open"], 8,
          f"حجم خرید/کندل مثبت ({vol_ratio:.2f}x)", f"حجم فروش/کندل منفی ({vol_ratio:.2f}x)")
    strength = adx_estimate(candles)
    score(strength >= 20 and e20[i] > e50[i], strength >= 20 and e20[i] < e50[i], 7,
          f"قدرت روند مناسب ({strength:.1f})", f"قدرت روند مناسب ({strength:.1f})")

    prev_high = max(c["high"] for c in candles[-21:-1])
    prev_low = min(c["low"] for c in candles[-21:-1])
    candle_range = max(last["high"] - last["low"], 1e-9)
    upper_wick = last["high"] - max(last["open"], last["close"])
    lower_wick = min(last["open"], last["close"]) - last["low"]
    breakout = "none"
    if price > prev_high:
        breakout = "bullish" if upper_wick / candle_range < 0.45 else "possible_false_up"
        if breakout == "bullish":
            up += 10
            up_reasons.append("شکست سقف ۲۰ کندل با بسته‌شدن بالای سطح")
        else:
            down += 5
            down_reasons.append("سایه بالایی بلند؛ احتمال شکست نامعتبر رو به بالا")
    elif price < prev_low:
        breakout = "bearish" if lower_wick / candle_range < 0.45 else "possible_false_down"
        if breakout == "bearish":
            down += 10
            down_reasons.append("شکست کف ۲۰ کندل با بسته‌شدن زیر سطح")
        else:
            up += 5
            up_reasons.append("سایه پایینی بلند؛ احتمال شکست نامعتبر رو به پایین")

    bull_div, bear_div = divergence(candles, rs)
    if bull_div:
        up += 8
        up_reasons.append("واگرایی مثبت RSI")
    if bear_div:
        down += 8
        down_reasons.append("واگرایی منفی RSI")

    highs, lows = pivot_levels(candles)
    # Maximum possible raw score is 80 points.
    return {
        "up": min(100, round(up / 80 * 100)),
        "down": min(100, round(down / 80 * 100)),
        "price": price, "rsi": rs[i], "atr": atr(candles),
        "adx": strength, "volume_ratio": vol_ratio, "breakout": breakout,
        "resistance": nearest_level(highs, price, True),
        "support": nearest_level(lows, price, False),
        "up_reasons": up_reasons, "down_reasons": down_reasons,
    }


def build_report():
    data = {tf: analyze_timeframe(get_candles(tf)) for tf in TIMEFRAMES}
    bull = round(sum(data[tf]["up"] * weight for tf, weight in TIMEFRAMES.items()))
    bear = round(sum(data[tf]["down"] * weight for tf, weight in TIMEFRAMES.items()))
    h1, h4, daily = data["1h"], data["4h"], data["1d"]
    price, volatility = h1["price"], h1["atr"]

    # Require meaningful confluence and higher-timeframe agreement.
    if bull >= MIN_SIGNAL_SCORE and bull - bear >= MIN_DIRECTION_GAP and h4["up"] >= 55 and daily["up"] >= 45:
        direction, side = "🟢 گرایش صعودی", "long"
        reasons = h1["up_reasons"][:4] + h4["up_reasons"][:2]
    elif bear >= MIN_SIGNAL_SCORE and bear - bull >= MIN_DIRECTION_GAP and h4["down"] >= 55 and daily["down"] >= 45:
        direction, side = "🔴 گرایش نزولی", "short"
        reasons = h1["down_reasons"][:4] + h4["down_reasons"][:2]
    else:
        direction, side, reasons = "🟡 فعلاً ورود نکن؛ هم‌جهتی کافی نیست", None, []

    entry = stop = targets = None
    if side == "long":
        entry = price
        stop = min(price - 1.5 * volatility, h1["support"] * 0.998 if h1["support"] else price - 1.5 * volatility)
        risk = max(entry - stop, volatility)
        targets = [entry + risk, entry + 2 * risk, entry + 3 * risk]
        # Avoid suggesting a target beyond a nearby resistance without noting it.
    elif side == "short":
        entry = price
        stop = max(price + 1.5 * volatility, h1["resistance"] * 1.002 if h1["resistance"] else price + 1.5 * volatility)
        risk = max(stop - entry, volatility)
        targets = [entry - risk, entry - 2 * risk, entry - 3 * risk]

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"📊 BTC PRO | {SYMBOL}", f"زمان تحلیل: {stamp}",
        f"قیمت آخرین کندل بسته‌شده ۱ساعته: ${price:,.2f}", "",
        f"امتیاز صعود: {bull}/100", f"امتیاز نزول: {bear}/100", direction, "",
        "🧭 وضعیت تایم‌فریم‌ها:",
    ]
    for tf in TIMEFRAMES:
        x = data[tf]
        lines.append(f"{tf}: صعود {x['up']} | نزول {x['down']} | RSI {x['rsi']:.1f} | ADX~ {x['adx']:.1f}")
    lines += ["", f"حمایت نزدیک ۱ساعته: ${h1['support']:,.2f}" if h1["support"] else "حمایت نزدیک ۱ساعته: شناسایی نشد",
              f"مقاومت نزدیک ۱ساعته: ${h1['resistance']:,.2f}" if h1["resistance"] else "مقاومت نزدیک ۱ساعته: شناسایی نشد",
              f"نسبت حجم آخر به میانگین: {h1['volume_ratio']:.2f}x",
              f"وضعیت شکست: {h1['breakout']}"]
    if side:
        lines += ["", f"📍 سطح مرجع ورود: ${entry:,.2f}", f"🛑 حد ضرر محاسباتی: ${stop:,.2f}",
                  f"🎯 هدف ۱: ${targets[0]:,.2f}", f"🎯 هدف ۲: ${targets[1]:,.2f}",
                  f"🎯 هدف ۳: ${targets[2]:,.2f}"]
    lines += ["", "دلایل اصلی: " + ("؛ ".join(reasons) if reasons else "سیگنال معتبر با شروط فعلی شکل نگرفته است."),
              "", "⚠️ امتیازها امتیاز هم‌جهتی قواعد تکنیکال‌اند، نه احتمال واقعی موفقیت. شکست‌ها ممکن است فیک باشند؛ قبل از معامله واقعی، بک‌تست و حساب آزمایشی لازم است. داده‌ها از بازار اسپات Binance هستند."]
    return "\n".join(lines)


def telegram_send(message):
    if not BOT_TOKEN or not CHAT_ID or "PASTE_" in BOT_TOKEN or "PASTE_" in CHAT_ID:
        raise RuntimeError("مقادیر BOT_TOKEN و CHAT_ID را در ابتدای فایل وارد کن.")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    # Telegram limits text messages to 4096 characters.
    chunks = [message[i:i + 3900] for i in range(0, len(message), 3900)] or [""]
    for chunk in chunks:
        result = http_json(url, {"chat_id": CHAT_ID, "text": chunk,
                                 "disable_web_page_preview": "true"})
        if not result.get("ok"):
            raise RuntimeError(f"Telegram error: {result}")


def seconds_until_next_hour():
    now = time.time()
    next_run = (int(now // 3600) + 1) * 3600 + CHECK_AFTER_HOUR_MINUTE * 60
    return max(5, next_run - now)


def main():
    once = "--once" in sys.argv
    test = "--test" in sys.argv
    print("BTC PRO v3 started. Analysis uses closed candles only.")

    if test:
        telegram_send("✅ اتصال ربات BTC PRO به تلگرام موفق است.")
        print("Telegram test message sent.")
        if once:
            return

    while True:
        if not once:
            wait = seconds_until_next_hour()
            print(f"تحلیل بعدی پس از {int(wait)} ثانیه؛ زمان‌بندی بر اساس UTC")
            time.sleep(wait)
        try:
            report = build_report()
            telegram_send(report)
            print("BTC PRO report sent.")
        except Exception as exc:
            print(f"Analysis/send error: {exc}")
            try:
                telegram_send(f"⚠️ خطا در تحلیل BTC PRO:\n{exc}")
            except Exception as send_exc:
                print(f"Could not send error to Telegram: {send_exc}")
        if once:
            break


if __name__ == "__main__":
    main()
