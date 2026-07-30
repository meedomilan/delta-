import os
import time
import requests
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

TOKEN = "8640721796:AAHrKDS6WPYQ7_B4N-Aj459pOSmZS-_LPu8"
CHAT_ID = "-1004437537280"
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

session = requests.Session()
# إضافة هيدرز لتجنب حظر الطلبات من بايننس
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
})

def get_binance_futures_symbols():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        response = session.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if 'symbols' in data:
                symbols = [s['symbol'] for s in data['symbols'] if s['status'] == 'TRADING' and s['contractType'] == 'PERPETUAL']
                print(f"Successfully fetched {len(symbols)} symbols from Binance.")
                return symbols
        print(f"Binance API warning status: {response.status_code}, response: {response.text[:100]}")
    except Exception as e:
        print(f"Error fetching symbols: {e}")
    
    # القائمة الاحتياطية الأساسية في حال الضغط
    return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "DOGEUSDT"]

def send_telegram_message(text):
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        session.post(TELEGRAM_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram error: {e}")

def check_single_symbol(symbol):
    timeframes = {"15m": "15m", "1h": "1h", "4h": "4h"}
    for tf_key, tf_val in timeframes.items():
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={tf_val}&limit=10"
        try:
            res = session.get(url, timeout=5)
            if res.status_code != 200:
                continue
            candles = res.json()
            if not isinstance(candles, list) or len(candles) < 5:
                continue
            
            last_candle = candles[-1]
            close_price = float(last_candle[4])
            
            # ضع شروط مؤشرك هنا

        except Exception as e:
            continue

def check_market_data():
    symbols = get_binance_futures_symbols()
    if not symbols:
        return
    print(f"Checking {len(symbols)} symbols...")
    
    # استخدام عدد خيوط آمن ومستقر لمنع ضغط الطلبات
    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(check_single_symbol, symbols)

def main():
    print("Stable Bot starting...")
    try:
        send_telegram_message("✅ *تم تحديث وتثبيت البوت للاتصال المستقر بدون أخطاء*")
    except Exception as e:
        print(f"Startup telegram error: {e}")
    
    while True:
        try:
            check_market_data()
            time.sleep(10) # فترة راحة بين الدورات لضمان عدم حظر الـ IP
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(15)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Critical crash error: {e}")
