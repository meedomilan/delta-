from datetime import datetime
from flask import Flask, jsonify, request
import requests

app = Flask(__name__)

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


@app.route("/", methods=["POST"])
def webhook():
  try:
    data = request.get_json(force=True)
    if not data:
      return jsonify({"status": "error", "message": "No JSON data"}), 400

    # استخراج البيانات المرسلة
    alert_type = str(data.get("type", "")).strip().lower()
    symbol = data.get("symbol", "BTCUSDT.P")
    timeframe = data.get("timeframe", "15m")
    price = data.get("price", "0.00")
    power = data.get("power", "91%")
    tv_link = data.get(
        "link",
        f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol.replace('.P', '')}",
    )

    # الوقت بتوقيت السعودية
    current_time = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
    message = ""

    # 1. تنبيهات دخول الآن (شراء / بيع)
    if alert_type == "entry_buy":
      message = (
          f"🟢 دخول الآن شراء\n\n"
          f"💰 العملة: #{symbol}\n"
          f"⏰ الفريم: {timeframe}\n"
          f"💵 السعر: {price}\n"
          f"📊 الحالة: تأكد زخم الشراء\n"
          f"🕒 الوقت: {current_time} بتوقيت السعودية\n\n"
          f"🔗 [TradingView]({tv_link})"
      )

    elif alert_type == "entry_sell":
      message = (
          f"🔴 دخول الآن — بيع\n\n"
          f"💰 العملة: #{symbol}\n"
          f"⏰ الفريم: {timeframe}\n"
          f"💵 السعر: {price}\n"
          f"📊 الحالة: تأكد زخم البيع\n"
          f"🕒 الوقت: {current_time} بتوقيت السعودية\n\n"
          f"🔗 [TradingView]({tv_link})"
      )

    # 2. تنبيهات الاستعداد (شراء / بيع)
    elif alert_type == "ready_buy":
      message = (
          f"🟡 استعداد شراء\n\n"
          f"💰 العملة: #{symbol}\n"
          f"⏰ الفريم: {timeframe}\n"
          f"💵 السعر: {price}\n"
          f"📊 الحالة: احتمال تكوّن دخول شراء\n"
          f"⚠️ انتظر إشارة دخول الآن\n"
          f"🕒 الوقت: {current_time} بتوقيت السعودية\n\n"
          f"🔗 [TradingView]({tv_link})"
      )

    elif alert_type == "ready_sell":
      message = (
          f"🟠 استعداد بيع\n\n"
          f"💰 العملة: #{symbol}\n"
          f"⏰ الفريم: {timeframe}\n"
          f"💵 السعر: {price}\n"
          f"📊 الحالة: احتمال تكوّن دخول بيع\n"
          f"⚠️ انتظر إشارة دخول الآن\n"
          f"🕒 الوقت: {current_time} بتوقيت السعودية\n\n"
          f"🔗 [TradingView]({tv_link})"
      )

    # 3. تنبيهات Delta (Buy / Sell)
    elif alert_type == "delta_buy":
      message = (
          f"⚡ DELTA BUY\n\n"
          f"💰 العملة: #{symbol}\n"
          f"⏰ الفريم: {timeframe}\n"
          f"💵 السعر: {price}\n"
          f"📊 تدفق الأوامر تحول إلى الشراء\n"
          f"🕒 الوقت: {current_time} بتوقيت السعودية\n\n"
          f"🔗 [TradingView]({tv_link})"
      )

    elif alert_type == "delta_sell":
      message = (
          f"⚡ DELTA SELL\n\n"
          f"💰 العملة: #{symbol}\n"
          f"⏰ الفريم: {timeframe}\n"
          f"💵 السعر: {price}\n"
          f"📊 تدفق الأوامر تحول إلى البيع\n"
          f"🕒 الوقت: {current_time} بتوقيت السعودية\n\n"
          f"🔗 [TradingView]({tv_link})"
      )

    # 4. تنبيهات Smart Money (أول ظهور شراء / بيع)
    elif alert_type == "smart_buy":
      message = (
          f"🚀 SMART MONEY BUY — أول ظهور\n\n"
          f"💰 العملة: #{symbol}\n"
          f"⏰ الفريم: {timeframe}\n"
          f"💵 السعر: {price}\n"
          f"📊 القوة: {power}\n"
          f"🐋 سيولة ذكية شرائية\n"
          f"🕒 الوقت: {current_time} بتوقيت السعودية\n\n"
          f"🔗 [TradingView]({tv_link})"
      )

    elif alert_type == "smart_sell":
      message = (
          f"🚀 SMART MONEY SELL — أول ظهور\n\n"
          f"💰 العملة: #{symbol}\n"
          f"⏰ الفريم: {timeframe}\n"
          f"💵 السعر: {price}\n"
          f"📊 القوة: {power}\n"
          f"🐋 سيولة ذكية بيعية\n"
          f"🕒 الوقت: {current_time} بتوقيت السعودية\n\n"
          f"🔗 [TradingView]({tv_link})"
      )

    else:
      return jsonify({"status": "ignored", "message": "Unknown alert type"}), 200

    res = send_telegram_Message(message)
    return jsonify({"status": "success", "telegram_response": res}), 200

  except Exception as e:
    return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=8080)
