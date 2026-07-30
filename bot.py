import os
import time
import requests
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

# بيانات الربط
TOKEN = "8640721796:AAHrKDS6WPYQ7_B4N-Aj459pOSmZS-_LPu8"
CHAT_ID = "-1004437537280"
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

# جلب قائمة عملات الفيوتشر النشطة من بايننس
def get_binance_futures_symbols():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        symbols = [s['symbol'] for s in data['symbols'] if s['status'] == 'TRADING' and s['contractType'] == 'PERPETUAL']
        return symbols
    except Exception as e:
        print(f"Error fetching symbols: {e}")
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# إرسال إشعار فوري لتيليجرام
def send_telegram_message(text):
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(TELEGRAM_URL, json=payload, timeout=3)
    except Exception as e:
        print(f"Telegram error: {e}")

# فحص العملة بشكل فوري ومتزامن
def check_single_symbol(symbol):
    timeframes = {"15m": "15m", "1h": "1h", "4h": "4h"}
    for tf_key, tf_val in timeframes.items():
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={tf_val}&limit=10"
        try:
            res = requests.get(url, timeout=3)
            if res.status_code != 200:
                continue
            candles = res.json()
            if not candles or len(candles) < 5:
                continue
            
            last_candle = candles[-1]
            close_price = float(last_candle[4])
            
            # ضع شروط مؤشرك هنا، وإذا تحققت الشرط يتم إرسال الإشعار فوراً بدون أي تأخير:
            # if [شرط الإشارة يتحقق]:
            #     saudi_time = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
            #     send_telegram_message(f"🚨 *إشارة جديدة فورية*\nالعملة: #{symbol}\nالفريم: {tf_val}\nالسعر: {close_price}\nالوقت: {saudi_time}")

        except Exception as e:
            continue

# فحص السوق بالكامل في نفس اللحظة (بدون انتظار)
def check_market_data():
    symbols = get_binance_futures_symbols()
    print(f"Instant parallel check started for {len(symbols)} symbols...")
    
    # فحص جميع العملات في نفس الثانية باستخدام الـ Threads
    with ThreadPoolExecutor(max_workers=50) as executor:
        executor.map(check_single_symbol, symbols)

def main():
    print("Instant Real-time Telegram Bot Started...")
    send_telegram_message("⚡ *تم تحديث البوت ليعمل بنظام الفحص الفوري المتزامن (بدون أي تأخير)*")
    
    while True:
        try:
            check_market_data()
            time.sleep(2) # راحة قصيرة جداً بين الدورات الفورية
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
