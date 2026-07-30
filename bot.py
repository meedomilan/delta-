import os
import time
import requests
from datetime import datetime, timezone, timedelta

# بيانات الربط الجديدة للبوت
TOKEN = "8640721796:AAHrKDS6WPYQ7_B4N-Aj459pOSmZS-_LPu8"
CHAT_ID = "-1004437537280"
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

# جلب قائمة عملات الفيوتشر النشطة من بايننس تلقائياً
def get_binance_futures_symbols():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        symbols = [s['symbol'] for s in data['symbols'] if s['status'] == 'TRADING' and s['contractType'] == 'PERPETUAL']
        return symbols
    except Exception as e:
        print(f"Error fetching symbols from Binance: {e}")
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

# دالة إرسال الإشعار إلى تيليجرام
def send_telegram_message(text):
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(TELEGRAM_URL, json=payload, timeout=5)
        return response.json()
    except Exception as e:
        print(f"Error sending message to Telegram: {e}")

# جلب الوقت بتوقيت السعودية
def get_saudi_time():
    utc_now = datetime.now(timezone.utc)
    saudi_time = utc_now + timedelta(hours=3)
    return saudi_time.strftime("%Y-%m-%d %H:%M:%S")

# دالة جلب الشموع والتحقق من الإشارات الفنية (15m, 1h, 4h)
def check_market_data():
    symbols = get_binance_futures_symbols()
    timeframes = {"15m": "15m", "1h": "1h", "4h": "4h"}
    
    print(f"Checking {len(symbols)} futures symbols...")

    for symbol in symbols:
        formatted_symbol = f"#{symbol}.P"
        
        for tf_key, tf_val in timeframes.items():
            url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={tf_val}&limit=50"
            try:
                res = requests.get(url, timeout=5)
                if res.status_code != 200:
                    continue
                candles = res.json()
                if not candles or len(candles) < 20:
                    continue
                
                # تحليل بيانات آخر شمعة مغلقة
                last_candle = candles[-1]
                close_price = float(last_candle[4])
                
                # شروط المؤشر أو الفحص
                if tf_val == "15m":
                    pass
                if tf_val == "1h":
                    pass
                if tf_val == "4h":
                    pass

                time.sleep(0.05) 
            except Exception as e:
                continue

# التشغيل المستمر للبوت
def main():
    print("Telegram bot started successfully with new token and connected to Binance Futures...")
    # إرسال رسالة تجريبية للتأكد من نجاح الربط بالبوت الجديد
    send_telegram_message("🤖 *تم ربط البوت الجديد بنجاح وبدء مراقبة عملات الفيوتشر*")
    
    while True:
        try:
            check_market_data()
            time.sleep(10) # الفحص المستمر بدون تأخير
        except Exception as e:
            print(f"General error: {e}")
            time.sleep(15)

if __name__ == "__main__":
    main()
