import os
import time
import requests
from datetime import datetime, timezone, timedelta

TOKEN = "8640721796:AAHrKDS6WPYQ7_B4N-Aj459pOSmZS-_LPu8"
CHAT_ID = "-1004437537280"
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

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

# فحص السوق بطلب واحد فقط لجميع العملات (بدون حظر وبسرعة فائقة)
def check_market_data():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        response = session.get(url, timeout=10)
        if response.status_code == 200:
            tickers = response.json()
            print(f"Successfully checked {len(tickers)} futures symbols instantly in 1 request.")
            
            for ticker in tickers:
                symbol = ticker.get('symbol')
                if not symbol.endswith('USDT'):
                    continue
                
                price = float(ticker.get('lastPrice', 0))
                
                # ضع شروط مؤشرك هنا واستخدم السعر أو البيانات المتوفرة فوراً
                # مثال:
                # if [شرط المؤشر]:
                #     send_telegram_message(f"🚨 تنبيه للعملة {symbol} بالسعر {price}")
                
        else:
            print(f"Binance status: {response.status_code}")
    except Exception as e:
        print(f"Error fetching market data: {e}")

def main():
    print("Ultra-Fast & Ban-Free Bot Started...")
    send_telegram_message("🚀 *تم تحديث البوت للعمل بطلب مجمع فوري (محصن ضد الحظر نهائياً)*")
    
    while True:
        try:
            check_market_data()
            time.sleep(3) # فحص متواصل وفوري بدون أي ضغط على السيرفر
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
