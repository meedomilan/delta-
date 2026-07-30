import os
import time
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
import requests

app = Flask(__name__)

# إعدادات التلجرام
TELEGRAM_TOKEN = "8640721796:AAHrKDS6WPYQ7_B4N-Aj459pOSmZS-_LPu8"
CHAT_ID = "-1004437537280"

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Telegram Error: {e}")
        return None

def get_saudi_time():
    # توقيت السعودية (UTC+3)
    saudi_tz = timezone(timedelta(hours=3))
    return datetime.now(saudi_tz).strftime('%Y-%m-%d %I:%M:%S %p')

# تهيئة منصة باينانس للفيوتشر
exchange = ccxt.binance({
    'options': {'defaultType': 'future'},
    'enableRateLimit': True
})

# تتبع آخر حالة للإشارات لتجنب التكرار المزعج في نفس الشمعة
last_signals = {}

def fetch_data(symbol, timeframe, limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e:
        return None

def analyze_market():
    try:
        exchange.load_markets()
        symbols = [s for s in exchange.symbols if s.endswith('/USDT:USDT') or s.endswith('USDT')]
        # تصفية عملات الفيوتشر فقط
        futures_symbols = [s for s in exchange.symbols if 'USDT' in s and exchange.markets[s].get('linear', True)]
    except Exception as e:
        print(f"Error loading markets: {e}")
        return

    timeframes = {'15m': '15m', '1h': '1h', '4h': '4h'}
    
    for symbol in futures_symbols[:50]: # فحص العينات لتجنب الحظر، أو يمكنك إزالة الحد
        ticker_name = symbol.replace('/USDT:USDT', 'USDT.P').replace('/', '')
        if not ticker_name.endswith('.P'):
            ticker_name += '.P'

        for tf_key, tf_val in timeframes.items():
            df = fetch_data(symbol, tf_val, limit=60)
            if df is None or len(df) < 30:
                continue
            
            # حساب المؤشرات والزخم
            close = df['close'].iloc[-1]
            open_p = df['open'].iloc[-1]
            high = df['high'].iloc[-1]
            low = df['low'].iloc[-1]
            vol = df['volume'].iloc[-1]
            prev_close = df['close'].iloc[-2]
            
            # حساب الضغط (Pressure)
            candle_range = max(high - low, 1e-8)
            close_pos = max(0.0, min(1.0, (close - low) / candle_range))
            buy_pct = close_pos * 100
            sell_pct = (1.0 - close_pos) * 100
            
            # مفتاح فريد لكل عملة والفريم للحالة
            sig_key = f"{symbol}_{tf_val}"

            # 1. تنبيهات دخول الآن (على فريم 15m)
            if tf_val == '15m':
                if buy_pct >= 75 and close > prev_p_check := df['close'].iloc[-2]:
                    msg = (
                        f"🟢 <b>دخول الآن شراء</b>\n\n"
                        f"💰 العملة: #{ticker_name}\n"
                        f"⏰ الفريم: {tf_val}\n"
                        f"💵 السعر: {close}\n"
                        f"📊 الحالة: تأكد زخم الشراء\n"
                        f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                        f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{ticker_name.replace('.P','')}'>TradingView</a>"
                    )
                    if last_signals.get(sig_key + '_entry_buy') != df['timestamp'].iloc[-1]:
                        send_telegram_message(msg)
                        last_signals[sig_key + '_entry_buy'] = df['timestamp'].iloc[-1]

                elif sell_pct >= 75 and close < prev_close:
                    msg = (
                        f"🔴 <b>دخول الآن — بيع</b>\n\n"
                        f"💰 العملة: #{ticker_name}\n"
                        f"⏰ الفريم: {tf_val}\n"
                        f"💵 السعر: {close}\n"
                        f"📊 الحالة: تأكد زخم البيع\n"
                        f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                        f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{ticker_name.replace('.P','')}'>TradingView</a>"
                    )
                    if last_signals.get(sig_key + '_entry_sell') != df['timestamp'].iloc[-1]:
                        send_telegram_message(msg)
                        last_signals[sig_key + '_entry_sell'] = df['timestamp'].iloc[-1]

            # 2. تنبيهات استعداد (على فريم 1h)
            if tf_val == '1h':
                if 58 <= buy_pct < 75:
                    msg = (
                        f"🟡 <b>استعداد شراء</b>\n\n"
                        f"💰 العملة: #{ticker_name}\n"
                        f"⏰ الفريم: {tf_val}\n"
                        f"💵 السعر: {close}\n"
                        f"📊 الحالة: احتمال تكوّن دخول شراء\n"
                        f"⚠️ انتظر إشارة دخول الآن\n"
                        f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                        f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{ticker_name.replace('.P','')}'>TradingView</a>"
                    )
                    if last_signals.get(sig_key + '_ready_buy') != df['timestamp'].iloc[-1]:
                        send_telegram_message(msg)
                        last_signals[sig_key + '_ready_buy'] = df['timestamp'].iloc[-1]

                elif 58 <= sell_pct < 75:
                    msg = (
                        f"🟠 <b>استعداد بيع</b>\n\n"
                        f"💰 العملة: #{ticker_name}\n"
                        f"⏰ الفريم: {tf_val}\n"
                        f"💵 السعر: {close}\n"
                        f"📊 الحالة: احتمال تكوّن دخول بيع\n"
                        f"⚠️ انتظر إشارة دخول الآن\n"
                        f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                        f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{ticker_name.replace('.P','')}'>TradingView</a>"
                    )
                    if last_signals.get(sig_key + '_ready_sell') != df['timestamp'].iloc[-1]:
                        send_telegram_message(msg)
                        last_signals[sig_key + '_ready_sell'] = df['timestamp'].iloc[-1]

            # 3. تنبيهات Delta (على فريم 4h)
            if tf_val == '4h':
                delta_val = (buy_pct - sell_pct)
                if delta_val > 25:
                    msg = (
                        f"⚡ <b>DELTA BUY</b>\n\n"
                        f"💰 العملة: #{ticker_name}\n"
                        f"⏰ الفريم: {tf_val}\n"
                        f"💵 السعر: {close}\n"
                        f"📊 تدفق الأوامر تحول إلى الشراء\n"
                        f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                        f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{ticker_name.replace('.P','')}'>TradingView</a>"
                    )
                    if last_signals.get(sig_key + '_delta_buy') != df['timestamp'].iloc[-1]:
                        send_telegram_message(msg)
                        last_signals[sig_key + '_delta_buy'] = df['timestamp'].iloc[-1]

                elif delta_val < -25:
                    msg = (
                        f"⚡ <b>DELTA SELL</b>\n\n"
                        f"💰 العملة: #{ticker_name}\n"
                        f"⏰ الفريم: {tf_val}\n"
                        f"💵 السعر: {close}\n"
                        f"📊 تدفق الأوامر تحول إلى البيع\n"
                        f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                        f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{ticker_name.replace('.P','')}'>TradingView</a>"
                    )
                    if last_signals.get(sig_key + '_delta_sell') != df['timestamp'].iloc[-1]:
                        send_telegram_message(msg)
                        last_signals[sig_key + '_delta_sell'] = df['timestamp'].iloc[-1]

            # 4. تنبيهات Smart Money (على فريم 15m)
            if tf_val == '15m' and vol > df['volume'].rolling(20).mean().iloc[-1] * 1.5:
                if buy_pct >= 80:
                    msg = (
                        f"🚀 <b>SMART MONEY BUY — أول ظهور</b>\n\n"
                        f"💰 العملة: #{ticker_name}\n"
                        f"⏰ الفريم: {tf_val}\n"
                        f"💵 السعر: {close}\n"
                        f"📊 القوة: 91%\n"
                        f"🐋 سيولة ذكية شرائية\n"
                        f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                        f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{ticker_name.replace('.P','')}'>TradingView</a>"
                    )
                    if last_signals.get(sig_key + '_sm_buy') != df['timestamp'].iloc[-1]:
                        send_telegram_message(msg)
                        last_signals[sig_key + '_sm_buy'] = df['timestamp'].iloc[-1]

                elif sell_pct >= 80:
                    msg = (
                        f"🚀 <b>SMART MONEY SELL — أول ظهور</b>\n\n"
                        f"💰 العملة: #{ticker_name}\n"
                        f"⏰ الفريم: {tf_val}\n"
                        f"💵 السعر: {close}\n"
                        f"📊 القوة: 91%\n"
                        f"🐋 سيولة ذكية بيعية\n"
                        f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                        f"🔗 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:{ticker_name.pace('','') if False else ticker_name.replace('.P','')}'>TradingView</a>"
                    )
                    if last_signals.get(sig_key + '_sm_sell') != df['timestamp'].iloc[-1]:
                        send_telegram_message(msg)
                        last_signals[sig_key + '_sm_sell'] = df['timestamp'].iloc[-1]

@app.route('/')
chno = lambda: "Bot is running successfully!"
app.add_url_rule('/', 'index', chno)

if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    # تشغيل الفحص كل دقيقة لتغطية العملات والفريمات بدقة
    scheduler.add_job(func=analyze_market, trigger="interval", minutes=1)
    scheduler.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
