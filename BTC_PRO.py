#!/usr/bin/env python3
# BTC PRO ULTIMATE V18 - Multi-Timeframe Buttons & 15m Auto
import os
import sys
import json
import time
import threading
import urllib.request
import urllib.parse

BASE = "https://data-api.binance.vision"
TOKEN = os.getenv("BOT_TOKEN", "")
CHAT = os.getenv("ALLOWED_CHAT_ID", "") or os.getenv("CHAT_ID", "")
TIMEOUT = 20

SYMBOL = "BTCUSDT"
SYMBOL_NAME = "بیت کوین (BTC)"
DEFAULT_TIMEFRAME = "15m"  # تایم‌فریم پیش‌فرض برای ارسال خودکار

# متغیر کنترلی برای جلوگیری از ارسال همزمان
is_sending_auto = False

def api(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "BTC-PRO-V18"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())

def candles(interval, limit=300):
    rows = api("/api/v3/klines", {"symbol": SYMBOL, "interval": interval, "limit": limit})
    now = int(time.time() * 1000)
    rows = [x for x in rows if int(x[6]) < now]
    if len(rows) < 220:
        raise RuntimeError("داده کافی نیست: " + interval)
    return {
        "time": [int(x[0]) for x in rows],
        "open": [float(x[1]) for x in rows],
        "high": [float(x[2]) for x in rows],
        "low": [float(x[3]) for x in rows],
        "close": [float(x[4]) for x in rows],
        "volume": [float(x[5]) for x in rows]
    }

def ema(v, p):
    out = [None] * len(v)
    if len(v) < p: return out
    value = sum(v[:p]) / p
    out[p - 1] = value
    alpha = 2 / (p + 1)
    for i in range(p, len(v)):
        value = v[i] * alpha + value * (1 - alpha)
        out[i] = value
    return out

def rsi(v, p=14):
    out = [None] * len(v)
    if len(v) <= p: return out
    changes = [v[i] - v[i - 1] for i in range(1, len(v))]
    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]
    ag = sum(gains[:p]) / p
    al = sum(losses[:p]) / p
    def calc(g, l):
        if l == 0: return 100 if g else 50
        return 100 - 100 / (1 + g / l)
    out[p] = calc(ag, al)
    for i in range(p + 1, len(v)):
        ag = (ag * (p - 1) + gains[i - 1]) / p
        al = (al * (p - 1) + losses[i - 1]) / p
        out[i] = calc(ag, al)
    return out

def macd(v):
    f, s = ema(v, 12), ema(v, 26)
    line = [None] * len(v)
    for i in range(len(v)):
        if f[i] is not None and s[i] is not None:
            line[i] = f[i] - s[i]
    start = next((i for i, x in enumerate(line) if x is not None), len(line))
    valid = line[start:]
    sig = ema(valid, 9) if valid else []
    signal = [None] * len(v)
    hist = [None] * len(v)
    for j, x in enumerate(sig):
        i = start + j
        if x is not None and line[i] is not None:
            signal[i] = x
            hist[i] = line[i] - x
    return line, signal, hist

def dmi(data, p=14):
    h, l, c = data["high"], data["low"], data["close"]
    n = len(c)
    tr = [0.0] * n
    plus = [0.0] * n
    minus = [0.0] * n
    for i in range(1, n):
        up = h[i] - h[i - 1]
        down = l[i - 1] - l[i]
        plus[i] = up if up > down and up > 0 else 0
        minus[i] = down if down > up and down > 0 else 0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    st = sum(tr[1:p + 1])
    sp = sum(plus[1:p + 1])
    sm = sum(minus[1:p + 1])
    dx = []
    last_pdi = last_mdi = 0
    for i in range(p + 1, n):
        st = st - st / p + tr[i]
        sp = sp - sp / p + plus[i]
        sm = sm - sm / p + minus[i]
        if st == 0: continue
        last_pdi = 100 * sp / st
        last_mdi = 100 * sm / st
        total = last_pdi + last_mdi
        dx.append(100 * abs(last_pdi - last_mdi) / total if total else 0)
    if len(dx) < p: return 0, 0, 0
    adx = sum(dx[:p]) / p
    for x in dx[p:]:
        adx = (adx * (p - 1) + x) / p
    return last_pdi, last_mdi, adxdef analyze(data):
    c = data["close"]
    h = data["high"]
    l = data["low"]
    v = data["volume"]
    e20 = ema(c, 20)
    e50 = ema(c, 50)
    e200 = ema(c, 200)
    rr = rsi(c)
    _, _, mh = macd(c)
    pdi, mdi, adx_value = dmi(data)
    i = -1
    price = c[-1]
    
    bull = 0
    bear = 0
    if price > e20[i]: bull += 2
    else: bear += 2
    if e20[i] > e50[i]: bull += 2
    else: bear += 2
    if e50[i] > e200[i]: bull += 2
    else: bear += 2
    if rr[i] > 55: bull += 2
    elif rr[i] < 45: bear += 2
    if mh[i] > 0 and mh[i] > mh[-2]: bull += 2
    elif mh[i] < 0 and mh[i] < mh[-2]: bear += 2
    if adx_value >= 18:
        if pdi > mdi: bull += 2
        elif mdi > pdi: bear += 2
    
    resistance = max(h[-21:-1])
    support = min(l[-21:-1])
    if price > resistance: bull += 3
    if price < support: bear += 3
    
    typical = [(h[j] + l[j] + c[j]) / 3 for j in range(len(c) - 30, len(c))]
    volumes = v[-30:]
    total_volume = sum(volumes)
    vwap = sum(x * y for x, y in zip(typical, volumes)) / total_volume if total_volume else price
    if price > vwap: bull += 1
    elif price < vwap: bear += 1
    
    total_score = bull + bear
    normalized = (bull / total_score * 100) if total_score > 0 else 50

    if adx_value < 20: trend_text = "رِنج (بدون روند)"
    elif adx_value < 25: trend_text = "در حال شکل‌گیری"
    elif adx_value < 40: trend_text = "روند قوی"
    else: trend_text = "روند بسیار قوی"

    if rr[i] < 30: rsi_text = "اشباع فروش"
    elif rr[i] > 70: rsi_text = "اشباع خرید"
    else: rsi_text = "خنثی"

    if mh[i] > 0 and mh[i] > mh[-2]: macd_text = "صعودی (خریداران)"
    elif mh[i] < 0 and mh[i] < mh[-2]: macd_text = "نزولی (فروشندگان)"
    else: macd_text = "کم‌جان"

    if normalized >= 65: status = "🟢 صعودی"
    elif normalized <= 35: status = "🔴 نزولی"
    else: status = "🟡 خنثی"

    if normalized >= 65 and adx_value >= 20 and rr[i] < 70:
        action = "🟢 خرید بزن"
        action_desc = "شرایط صعودی تایید شد."
    elif normalized <= 35 and adx_value >= 20 and rr[i] > 30:
        action = "🔴 فروش بزن"
        action_desc = "شرایط نزولی تایید شد."
    else:
        action = "🟡 معامله نکن"
        action_desc = "شرایط برای ورود امن نیست، صبر کنید."

    return {
        "price": price, "trend_text": trend_text, "rsi_text": rsi_text,
        "macd_text": macd_text, "status": status, "support": support,
        "resistance": resistance, "action": action, "action_desc": action_desc
    }

def send_telegram(message, reply_markup=None):
    if not TOKEN or not CHAT: return
    url = "https://api.telegram.org/bot" + TOKEN + "/sendMessage"
    payload = {"chat_id": CHAT, "text": message, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
        
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=data)
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT)
    except Exception as e:
        print("Telegram error:", e)

def get_updates(offset=None):
    url = "https://api.telegram.org/bot" + TOKEN + "/getUpdates"
    params = {"timeout": 30, "drop_pending_updates": True}
    if offset: params["offset"] = offset
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=TIMEOUT+10) as r:
        return json.loads(r.read().decode())

def send_analysis(timeframe):
    global is_sending_auto
    
    is_sending_auto = True
    try:
        d_tf = candles(timeframe)
        res = analyze(d_tf)
        
        msg = f"📊 تحلیل {SYMBOL_NAME} ({timeframe})\n"
        msg += f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        msg += f"💰 قیمت: ${res['price']:,.2f}\n"
        msg += f"📌 وضعیت: {res['status']}\n\n"
        msg += f"🔹 روند بازار: {res['trend_text']}\n"
        msg += f"🔹 روانشناسی: {res['rsi_text']}\n"
        msg += f"🔹 مومنتوم: {res['macd_text']}\n\n"
        msg += f"🟢 حمایت: ${res['support']:,.2f}\n"
        msg += f"🔴 مقاومت: ${res['resistance']:,.2f}\n"
        msg += f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        msg += f"🎯 توصیه نهایی: {res['action']}\n"
        msg += f"_{res['action_desc']}_"
        
        send_telegram(msg)
    except Exception as e:
        print("Analysis Error:", e)
    finally:
        is_sending_auto = False

def auto_timer():
    print("Auto-timer started (every 15 mins).")
    while True:
        time.sleep(900) # 900 ثانیه = 15 دقیقه
        if not is_sending_auto:
            print("Sending auto analysis...")
            send_analysis(DEFAULT_TIMEFRAME)

def handle_messages():
    global is_sending_auto
    print("Bot is running...")
    last_update_id = None
    
    t = threading.Thread(target=auto_timer, daemon=True)
    t.start()
    
    # ساخت کیبورد با دکمه‌های مختلف تایم‌فریم
    keyboard = {
        "keyboard": [
            [{"text": "5m"}, {"text": "15m"}, {"text": "1h"}],
            [{"text": "4h"}, {"text": "1d"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    
    while True:
        try:
            updates = get_updates(last_update_id)
            if updates.get("ok"):
                for update in updates["result"]:
                    last_update_id = update["update_id"] + 1
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"].strip()
                        chat_id = str(update["message"]["chat"]["id"])
                        
                        if CHAT and chat_id != CHAT:
                            continue
                            
                        if text in ["/start", "استارت", "شروع"]:
                            send_telegram(f"🤖 ربات تحلیل {SYMBOL_NAME}\n\n✅ روشن شد.\nاز این به بعد هر ۱۵ دقیقه تحلیل تایم‌فریم ۱۵ دقیقه را می‌فرستم.\nبرای تحلیل دستی، روی دکمه‌های زیر کلیک کنید:", reply_markup=keyboard)
                        
                        elif text in ["5m", "15m", "1h", "4h", "1d"]:
                            if not is_sending_auto:
                                send_telegram(f"⏳ در حال تحلیل تایم‌فریم {text}...")
                                send_analysis(text)
                                
                        elif text in ["/analyze", "تحلیل", "تحلیل کن"]:
                            if not is_sending_auto:
                                send_telegram(f"⏳ در حال تحلیل تایم‌فریم {DEFAULT_TIMEFRAME}...")
                                send_analysis(DEFAULT_TIMEFRAME)
            time.sleep(1)
        except Exception as e:
            print("Polling error:", e)
            time.sleep(5)

if name == "main":
    if not TOKEN:
        print("BOT_TOKEN is missing!")
        sys.exit(1)
    handle_messages()
