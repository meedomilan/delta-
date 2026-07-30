from datetime import datetime
import time
import requests

# بيانات التيليجرام الخاصة بك
TELEGRAM_BOT_TOKEN = "8640721796:AAHrKDS6WPYQ7_B4N-Aj459pOSmZS-_LPu8"
TELEGRAM_CHAT_ID = "-1004437537280"


def send_telegram_message(text):
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {
      "chat_id": TELEGRAM_CHAT_ID,
      "text": text,
      "parse_mode": "Markdown",
      "disable_web_page_preview": True,
  }
  try:
    response = requests.post(url, json=payload, timeout=10)
    return response.json()
  except Exception as e:
    print(f"Error sending telegram message: {e}")
    return None


def get_current_time_saudi():
  return datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")


print("Standalone Market Watcher Bot Started Successfully.")

# حلقة عمل مستمرة لمراقبة السوق عبر Binance Futures API مباشرة
while True:
  try:
    # جلب الأسعار ومعلومات الشموع من باينانس مباشرة بدون مكتبات معقدة
    url = "https://fapi.binance.com/fapi/v1/ticker/price"
    response = requests.get(url, timeout=10)
    data = response.json()

    print(f"Checked {len(data)} futures pairs successfully.")

    # يمكنك هنا إضافة منطق فحص شروط مؤشرك لكل عملة وإرسال التنبيه فوراً عبر send_telegram_message()

  except Exception as e:
    print(f"Error fetching market data: {e}")

  # الانتظار قبل الفحص القادم
  time.sleep(60)
