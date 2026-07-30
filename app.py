import os
import requests
from flask import Flask, request, jsonify
from datetime import datetime
import pytz

app = Flask(__name__)

# التوكن ومعرف الشات الخاص بك
BOT_TOKEN = "8711875284:AAHxIFwTC6JDBUeVX2EnsJgWvQQ0s2bLYw8"
CHAT_ID = "-1004394911035"

def get_saudi_time():
    saudi_tz = pytz.timezone('Asia/Riyadh')
    return datetime.now(saudi_tz).strftime('%H:%M:%S')

def format_timeframe(tf):
    if tf == "15": return "15m"
    if tf == "60": return "1h"
    if tf == "240": return "4h"
    return f"{tf}m"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        alert_type = data.get('type')
        coin = data.get('coin', 'UNKNOWN')
        tf_raw = data.get('timeframe', '15')
        price = data.get('price', '0.00')
        strength = data.get('strength', '91%')
        
        timeframe = format_timeframe(tf_raw)
        saudi_time = get_saudi_time()
        
        # رابط ترندينغ فيو لعملات الفيوتشر
        clean_coin = coin.replace('.P', 'PERP')
        tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{clean_coin}"

        # القوالب المطابقة تماماً لما طلبته
        if alert_type == "enter_buy":
            msg = f"🟢 دخول الآن شراء\n\n💰 العملة: #{coin}\n⏰ الفريم: {timeframe}\n💵 السعر: {price}\n📊 الحالة: تأكد زخم الشراء\n🕒 الوقت: {saudi_time} بتوقيت السعودية\n\n🔗 <a href='{tv_link}'>TradingView</a>"
        
        elif alert_type == "enter_sell":
            msg = f"🔴 دخول الآن — بيع\n\n💰 العملة: #{coin}\n⏰ الفريم: {timeframe}\n💵 السعر: {price}\n📊 الحالة: تأكد زخم البيع\n🕒 الوقت: {saudi_time} بتوقيت السعودية\n\n🔗 <a href='{tv_link}'>TradingView</a>"
        
        elif alert_type == "ready_buy":
            msg = f"🟡 استعداد شراء\n\n💰 العملة: #{coin}\n⏰ الفريم: {timeframe}\n💵 السعر: {price}\n📊 الحالة: احتمال تكوّن دخول شراء\n⚠️ انتظر إشارة دخول الآن\n🕒 الوقت: {saudi_time} بتوقيت السعودية\n\n🔗 <a href='{tv_link}'>TradingView</a>"
        
        elif alert_type == "ready_sell":
            msg = f"🟠 استعداد بيع\n\n💰 العملة: #{coin}\n⏰ الفريم: {timeframe}\n💵 السعر: {price}\n📊 الحالة: احتمال تكوّن دخول بيع\n⚠️ انتظر إشارة دخول الآن\n🕒 الوقت: {saudi_time} بتوقيت السعودية\n\n🔗 <a href='{tv_link}'>TradingView</a>"
        
        elif alert_type == "delta_buy":
            msg = f"⚡ DELTA BUY\n\n💰 العملة: #{coin}\n⏰ الفريم: {timeframe}\n💵 السعر: {price}\n📊 تدفق الأوامر تحول إلى الشراء\n🕒 الوقت: {saudi_time} بتوقيت السعودية\n\n🔗 <a href='{tv_link}'>TradingView</a>"
        
        elif alert_type == "delta_sell":
            msg = f"⚡ DELTA SELL\n\n💰 العملة: #{coin}\n⏰ الفريم: {timeframe}\n💵 السعر: {price}\n📊 تدفق الأوامر تحول إلى البيع\n🕒 الوقت: {saudi_time} بتوقيت السعودية\n\n🔗 <a href='{tv_link}'>TradingView</a>"
        
        elif alert_type == "smart_buy":
            msg = f"🚀 SMART MONEY BUY — أول ظهور\n\n💰 العملة: #{coin}\n⏰ الفريم: {timeframe}\n💵 السعر: {price}\n📊 القوة: {strength}\n🐋 سيولة ذكية شرائية\n🕒 الوقت: {saudi_time} بتوقيت السعودية\n\n🔗 <a href='{tv_link}'>TradingView</a>"
        
        elif alert_type == "smart_sell":
            msg = f"🚀 SMART MONEY SELL — أول ظهور\n\n💰 العملة: #{coin}\n⏰ الفريم: {timeframe}\n💵 السعر: {price}\n📊 القوة: {strength}\n🐋 سيولة ذكية بيعية\n🕒 الوقت: {saudi_time} بتوقيت السعودية\n\n🔗 <a href='{tv_link}'>TradingView</a>"
        else:
            return jsonify({"status": "ignored"}), 200

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        requests.post(url, json=payload, timeout=5)
        
        return jsonify({"status": "success"}), 200

    except Exception as e:
        return jsonify({"status": "error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
