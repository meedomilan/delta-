import os
import time
from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask

app = Flask(__name__)

# =========================================================
# إعدادات Railway Variables
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN غير موجود في Railway Variables")

if not CHAT_ID:
    raise RuntimeError("TELEGRAM_CHAT_ID غير موجود في Railway Variables")


# =========================================================
# تيليجرام
# =========================================================
def send_telegram_message(text: str):
    """إرسال رسالة إلى تيليجرام مع إظهار نتيجة الإرسال في السجل."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()

        result = response.json()
        if result.get("ok"):
            print("✅ Telegram message sent successfully.", flush=True)
        else:
            print(f"❌ Telegram API response: {result}", flush=True)

        return result

    except requests.RequestException as exc:
        print(f"❌ Telegram request error: {exc}", flush=True)
        return None

    except Exception as exc:
        print(f"❌ Telegram unexpected error: {exc}", flush=True)
        return None


def get_saudi_time() -> str:
    """إرجاع الوقت الحالي بتوقيت السعودية UTC+3."""
    saudi_tz = timezone(timedelta(hours=3))
    return datetime.now(saudi_tz).strftime("%Y-%m-%d %I:%M:%S %p")


# =========================================================
# Binance Futures
# =========================================================
exchange = ccxt.binance(
    {
        "options": {"defaultType": "future"},
        "enableRateLimit": True,
        "timeout": 20000,
    }
)

# يمنع تكرار نفس نوع الإشارة على الشمعة نفسها.
last_signals = {}

# يمنع بدء دورتين فحص في الوقت نفسه.
scan_running = False


def fetch_data(symbol: str, timeframe: str, limit: int = 60):
    """جلب بيانات الشموع مع تجاهل الزوج مؤقتًا عند حدوث خطأ."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

        if not ohlcv:
            return None

        return pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )

    except Exception as exc:
        print(
            f"⚠️ Fetch failed | symbol={symbol} | timeframe={timeframe} | {exc}",
            flush=True,
        )
        return None


def get_futures_symbols():
    """جلب عقود USDT الدائمة النشطة فقط."""
    exchange.load_markets(reload=True)

    symbols = []

    for symbol, market in exchange.markets.items():
        is_valid = (
            market.get("active", True)
            and market.get("swap", False)
            and market.get("linear", False)
            and market.get("quote") == "USDT"
            and market.get("settle") == "USDT"
        )

        if is_valid:
            symbols.append(symbol)

    return sorted(set(symbols))


def format_ticker(symbol: str) -> str:
    """تحويل BTC/USDT:USDT إلى BTCUSDT.P."""
    base = symbol.split("/")[0]
    return f"{base}USDT.P"


def tradingview_url(ticker_name: str) -> str:
    tv_symbol = ticker_name.replace(".P", "")
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{tv_symbol}.P"


# =========================================================
# التحليل
# =========================================================
def analyze_market():
    global scan_running

    if scan_running:
        print("⏭️ Previous scan is still running; skipping this cycle.", flush=True)
        return

    scan_running = True
    scan_started = time.time()
    checked_charts = 0
    sent_before = len(last_signals)

    try:
        print("🔄 Loading Binance Futures symbols...", flush=True)

        futures_symbols = get_futures_symbols()

        print(
            f"✅ Successfully fetched {len(futures_symbols)} USDT perpetual symbols.",
            flush=True,
        )

        timeframes = ("15m", "1h", "4h")

        for symbol_index, symbol in enumerate(futures_symbols, start=1):
            ticker_name = format_ticker(symbol)

            for timeframe in timeframes:
                df = fetch_data(symbol, timeframe, limit=60)

                if df is None or len(df) < 30:
                    continue

                checked_charts += 1

                candle_timestamp = int(df["timestamp"].iloc[-1])
                close = float(df["close"].iloc[-1])
                high = float(df["high"].iloc[-1])
                low = float(df["low"].iloc[-1])
                volume = float(df["volume"].iloc[-1])
                previous_close = float(df["close"].iloc[-2])

                candle_range = max(high - low, 1e-8)
                close_position = max(
                    0.0,
                    min(1.0, (close - low) / candle_range),
                )

                buy_pct = close_position * 100.0
                sell_pct = (1.0 - close_position) * 100.0

                signal_key = f"{symbol}_{timeframe}"
                tv_url = tradingview_url(ticker_name)

                # -------------------------------------------------
                # 1) دخول الآن — فريم 15 دقيقة
                # -------------------------------------------------
                if timeframe == "15m":
                    if buy_pct >= 75 and close > previous_close:
                        unique_key = signal_key + "_entry_buy"

                        if last_signals.get(unique_key) != candle_timestamp:
                            message = (
                                "🟢 <b>دخول الآن شراء</b>\n\n"
                                f"💰 العملة: #{ticker_name}\n"
                                f"⏰ الفريم: {timeframe}\n"
                                f"💵 السعر: {close}\n"
                                f"📊 ضغط الشراء: {buy_pct:.1f}%\n"
                                "📈 الحالة: تأكد زخم الشراء\n"
                                f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                                f"🔗 <a href='{tv_url}'>TradingView</a>"
                            )

                            if send_telegram_message(message):
                                last_signals[unique_key] = candle_timestamp

                    elif sell_pct >= 75 and close < previous_close:
                        unique_key = signal_key + "_entry_sell"

                        if last_signals.get(unique_key) != candle_timestamp:
                            message = (
                                "🔴 <b>دخول الآن — بيع</b>\n\n"
                                f"💰 العملة: #{ticker_name}\n"
                                f"⏰ الفريم: {timeframe}\n"
                                f"💵 السعر: {close}\n"
                                f"📊 ضغط البيع: {sell_pct:.1f}%\n"
                                "📉 الحالة: تأكد زخم البيع\n"
                                f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                                f"🔗 <a href='{tv_url}'>TradingView</a>"
                            )

                            if send_telegram_message(message):
                                last_signals[unique_key] = candle_timestamp

                # -------------------------------------------------
                # 2) استعداد — فريم الساعة
                # -------------------------------------------------
                if timeframe == "1h":
                    if 58 <= buy_pct < 75:
                        unique_key = signal_key + "_ready_buy"

                        if last_signals.get(unique_key) != candle_timestamp:
                            message = (
                                "🟡 <b>استعداد شراء</b>\n\n"
                                f"💰 العملة: #{ticker_name}\n"
                                f"⏰ الفريم: {timeframe}\n"
                                f"💵 السعر: {close}\n"
                                f"📊 ضغط الشراء: {buy_pct:.1f}%\n"
                                "⚠️ انتظر إشارة دخول الآن\n"
                                f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                                f"🔗 <a href='{tv_url}'>TradingView</a>"
                            )

                            if send_telegram_message(message):
                                last_signals[unique_key] = candle_timestamp

                    elif 58 <= sell_pct < 75:
                        unique_key = signal_key + "_ready_sell"

                        if last_signals.get(unique_key) != candle_timestamp:
                            message = (
                                "🟠 <b>استعداد بيع</b>\n\n"
                                f"💰 العملة: #{ticker_name}\n"
                                f"⏰ الفريم: {timeframe}\n"
                                f"💵 السعر: {close}\n"
                                f"📊 ضغط البيع: {sell_pct:.1f}%\n"
                                "⚠️ انتظر إشارة دخول الآن\n"
                                f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                                f"🔗 <a href='{tv_url}'>TradingView</a>"
                            )

                            if send_telegram_message(message):
                                last_signals[unique_key] = candle_timestamp

                # -------------------------------------------------
                # 3) Delta — فريم 4 ساعات
                # تنبيه عند تحقق الشرط، وليس Delta حقيقيًا من دفتر الأوامر.
                # -------------------------------------------------
                if timeframe == "4h":
                    delta_value = buy_pct - sell_pct

                    if delta_value > 25:
                        unique_key = signal_key + "_delta_buy"

                        if last_signals.get(unique_key) != candle_timestamp:
                            message = (
                                "⚡ <b>DELTA BUY</b>\n\n"
                                f"💰 العملة: #{ticker_name}\n"
                                f"⏰ الفريم: {timeframe}\n"
                                f"💵 السعر: {close}\n"
                                f"📊 قوة الضغط: {delta_value:.1f}\n"
                                "📈 تدفق الحركة يميل إلى الشراء\n"
                                f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                                f"🔗 <a href='{tv_url}'>TradingView</a>"
                            )

                            if send_telegram_message(message):
                                last_signals[unique_key] = candle_timestamp

                    elif delta_value < -25:
                        unique_key = signal_key + "_delta_sell"

                        if last_signals.get(unique_key) != candle_timestamp:
                            message = (
                                "⚡ <b>DELTA SELL</b>\n\n"
                                f"💰 العملة: #{ticker_name}\n"
                                f"⏰ الفريم: {timeframe}\n"
                                f"💵 السعر: {close}\n"
                                f"📊 قوة الضغط: {abs(delta_value):.1f}\n"
                                "📉 تدفق الحركة يميل إلى البيع\n"
                                f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                                f"🔗 <a href='{tv_url}'>TradingView</a>"
                            )

                            if send_telegram_message(message):
                                last_signals[unique_key] = candle_timestamp

                # -------------------------------------------------
                # 4) Smart Money — فريم 15 دقيقة
                # -------------------------------------------------
                if timeframe == "15m":
                    average_volume = float(
                        df["volume"].rolling(20).mean().iloc[-1]
                    )

                    high_volume = (
                        average_volume > 0
                        and volume > average_volume * 1.5
                    )

                    if high_volume and buy_pct >= 80:
                        unique_key = signal_key + "_sm_buy"

                        if last_signals.get(unique_key) != candle_timestamp:
                            message = (
                                "🚀 <b>SMART MONEY BUY — أول ظهور</b>\n\n"
                                f"💰 العملة: #{ticker_name}\n"
                                f"⏰ الفريم: {timeframe}\n"
                                f"💵 السعر: {close}\n"
                                f"📊 ضغط الشراء: {buy_pct:.1f}%\n"
                                "🐋 حجم مرتفع مع سيطرة شرائية\n"
                                f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                                f"🔗 <a href='{tv_url}'>TradingView</a>"
                            )

                            if send_telegram_message(message):
                                last_signals[unique_key] = candle_timestamp

                    elif high_volume and sell_pct >= 80:
                        unique_key = signal_key + "_sm_sell"

                        if last_signals.get(unique_key) != candle_timestamp:
                            message = (
                                "🚀 <b>SMART MONEY SELL — أول ظهور</b>\n\n"
                                f"💰 العملة: #{ticker_name}\n"
                                f"⏰ الفريم: {timeframe}\n"
                                f"💵 السعر: {close}\n"
                                f"📊 ضغط البيع: {sell_pct:.1f}%\n"
                                "🐋 حجم مرتفع مع سيطرة بيعية\n"
                                f"🕒 الوقت: {get_saudi_time()} بتوقيت السعودية\n\n"
                                f"🔗 <a href='{tv_url}'>TradingView</a>"
                            )

                            if send_telegram_message(message):
                                last_signals[unique_key] = candle_timestamp

            if symbol_index % 25 == 0:
                print(
                    f"🔎 Progress: {symbol_index}/{len(futures_symbols)} symbols.",
                    flush=True,
                )

        duration = time.time() - scan_started
        new_signal_states = len(last_signals) - sent_before

        print(
            "✅ Scan completed | "
            f"charts={checked_charts} | "
            f"new_signal_states={new_signal_states} | "
            f"duration={duration:.1f}s",
            flush=True,
        )

    except Exception as exc:
        print(f"❌ Market analysis error: {exc}", flush=True)

    finally:
        scan_running = False


# =========================================================
# Flask health check
# =========================================================
@app.route("/")
def index():
    return "Bot is running successfully!", 200


@app.route("/health")
def health():
    return {
        "status": "ok",
        "scanner_running": scan_running,
        "saved_signal_states": len(last_signals),
        "saudi_time": get_saudi_time(),
    }, 200


# =========================================================
# التشغيل
# =========================================================
def start_scheduler():
    scheduler = BackgroundScheduler(
        timezone=timezone(timedelta(hours=3)),
        daemon=True,
    )

    # يبدأ أول فحص مباشرة، ثم يحاول تشغيل دورة كل دقيقة.
    # max_instances=1 يمنع تداخل دورات الفحص.
    scheduler.add_job(
        func=analyze_market,
        trigger="interval",
        minutes=1,
        id="market_scanner",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.start()
    return scheduler


if __name__ == "__main__":
    print("✅ Script execution started.", flush=True)
    print("🚀 Starting Binance Futures scanner...", flush=True)

    scheduler = start_scheduler()

    print("✅ Scanner scheduler started.", flush=True)

    port = int(os.environ.get("PORT", "8080"))

    print(f"🌐 Starting Flask server on 0.0.0.0:{port}", flush=True)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )
