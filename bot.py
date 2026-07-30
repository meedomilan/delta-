import os
import time
import requests
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

TOKEN = "8640721796:AAHrKDS6WPYQ7_B4N-Aj459pOSmZS-_LPu8"
CHAT_ID = "-1004437537280"
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

# إنشاء جلسة اتصال موحدة لإعادة استخدام الاتصالات وتجنب استنزاف المنافذ
session = requests.Session()

def get_binance_futures_symbols():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        response = session.get(url, timeout=10)
        data = response.json()
        symbols = [s['symbol'] for s in data['symbols'] if s['status'] == 'TRADING' and s['contractType'] == 'PERPETUAL']
        return symbols
    except Exception as e:
        print(f"Error fetching symbols: {e}")
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

def send_telegram_message(text):
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        session.post(TELEGRAM_URL, json=payload, timeout=3)
    except Exception as e:
        print(f"Telegram error: {e}")

def check_single_symbol(symbol):
    timeframes = {"15m": "15m", "1h": "1h", "4h": "4h"}
    for tf_key, tf_val in timeframes.items():
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={tf_val}&limit=10"
        try:
            res = session.get(url, timeout=3)
            if res.status_code != 200:
                continue
            candles = res.json()
            if not candles or len(candles) < 5:
                continue
            
            last_candle = candles[-1]
            close_price = float(last_candle[4])
            
            # ضع شروط مؤشرك هنا

        except Exception as e:
            continue

def check_market_data():
    symbols = get_binance_futures_symbols()
    print(f"Checking {len(symbols)} symbols efficiently...")
    
    # تحديد عدد الخيوط بـ 20 لضمان السرعة وعدم استنزاف الموارد
    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(check_single_symbol, symbols)

def main():
    print("Optimized Real-time Bot Started...")
    send_telegram_message("⚡ *تم تحسين أداء البوت وحل مشكلة الاتصالات ليعمل بكفاءة عالية وسرعة فورية*")
    
    while True:
        try:
            check_market_data()
            time.sleep(5)
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
