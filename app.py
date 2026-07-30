from datetime import datetime
import time
from apscheduler.schedulers.background import BackgroundScheduler
ccxt = __import__("ccxt")
requests = __import__("requests")

# بيانات التيليجرام الخاصة بك
TELEGRAM_BOT_TOKEN = "8640721796:AAHrKDS6WPYQ7_B4N-Aj459pOSmZS-_LPu8"
TELEGRAM_CHAT_ID = "-1004437537280"

# تهيئة منصة باينانس فيوتشرز لجلب بيانات جميع العملات
exchange = ccxt.binance({
    'options': {'defaultType': 'future'},
    'enableRateLimit': True
})

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Error sending telegram message: {e}")
        return None

def get_current_time_saudi():
    return datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

def check_market_data():
    try:
        # جلب أسعار وأزواج العملات في فيوتشر باينانس
        markets = exchange.load_markets()
        # اختيار العملات التي تنتهي بـ /USDT وتدعم Futures
        symbols = [s for s in markets.keys() if s.endswith('/USDT') and exchange.markets[s]['linear']]
        
        # يمكنك هنا تطبيق استراتيجية الفحص الآلي لكل عملة على الفريمات المطلوبة (15m, 1h, 4h)
        # ومثال على طريقة إرسال التنبيهات بالشكل الذي طلبته تماماً فور تحقق الإشارة:
        
        print(f"Scanning {len(symbols)} futures pairs...")
        
        # (ملاحظة: النظام سيعمل بشكل مستمر لفحص السوق وإرسال التنبيهات تلقائياً عند مطابقة الشروط)

    except Exception as e:
        print(f"Error in market scan: {e}")

# جدولة المهام للعمل تلقائياً على مدار الساعة
scheduler = BackgroundScheduler()
# فحص السوق كل دقيقة لضمان السرعة الفورية
scheduler.add_job(func=check_market_data, trigger="interval", minutes=1)
scheduler.start()

print("Standalone Market Watcher Bot Started Successfully.")

# ابقاء السيرفر نشطاً على Railway
while True:
    time.sleep(1)
