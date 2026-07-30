import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask

app = Flask(__name__)

# =========================================================
# Railway Variables
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN غير موجود في Railway Variables")
if not CHAT_ID:
    raise RuntimeError("TELEGRAM_CHAT_ID غير موجود في Railway Variables")

BINANCE_BASE_URL = os.environ.get(
    "BINANCE_FUTURES_BASE_URL", "https://fapi.binance.com"
).rstrip("/")

# إعدادات آمنة قابلة للتعديل من Railway Variables.
WORKERS = max(4, min(int(os.environ.get("SCAN_WORKERS", "16")), 30))
BATCH_SIZE = max(10, min(int(os.environ.get("SCAN_BATCH_SIZE", "40")), 80))
REQUEST_TIMEOUT = max(5, min(int(os.environ.get("REQUEST_TIMEOUT", "12")), 30))

SAUDI_TZ = timezone(timedelta(hours=3))

# =========================================================
# الحالة العامة
# =========================================================
state_lock = threading.Lock()
last_signals: Dict[str, int] = {}
active_symbols: List[str] = []
symbols_updated_at = 0.0
scan_positions = {"15m": 0, "1h": 0, "4h": 0}
scan_stats = {
    "15m": {"last_duration": 0.0, "last_checked": 0, "last_run": None},
    "1h": {"last_duration": 0.0, "last_checked": 0, "last_run": None},
    "4h": {"last_duration": 0.0, "last_checked": 0, "last_run": None},
}
thread_local = threading.local()


def get_session() -> requests.Session:
    """جلسة HTTP مستقلة لكل خيط لتقليل زمن الاتصال."""
    if not hasattr(thread_local, "session"):
        session = requests.Session()
        session.headers.update({"User-Agent": "Ahmed-Pro-Ultimate-Scanner/2.0"})
        thread_local.session = session
    return thread_local.session


def get_saudi_time() -> str:
    return datetime.now(SAUDI_TZ).strftime("%Y-%m-%d %I:%M:%S %p")


def send_telegram_message(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    for attempt in range(1, 4):
        try:
            response = get_session().post(url, json=payload, timeout=REQUEST_TIMEOUT)

            # احترام مهلة Telegram عند ضغط الرسائل.
            if response.status_code == 429:
                retry_after = response.json().get("parameters", {}).get("retry_after", 2)
                time.sleep(min(float(retry_after), 10.0))
                continue

            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                print("✅ Telegram message sent.", flush=True)
                return True

            print(f"❌ Telegram API response: {result}", flush=True)
            return False

        except requests.RequestException as exc:
            print(f"⚠️ Telegram attempt {attempt}/3 failed: {exc}", flush=True)
            if attempt < 3:
                time.sleep(attempt)

    return False


# =========================================================
# Binance Futures REST
# =========================================================
def refresh_symbols(force: bool = False) -> List[str]:
    """تحديث عقود USDT الدائمة كل 30 دقيقة بدل كل دورة فحص."""
    global active_symbols, symbols_updated_at

    with state_lock:
        fresh = active_symbols and (time.time() - symbols_updated_at < 1800)
        if fresh and not force:
            return list(active_symbols)

    url = f"{BINANCE_BASE_URL}/fapi/v1/exchangeInfo"
    response = get_session().get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()

    symbols = sorted(
        item["symbol"]
        for item in data.get("symbols", [])
        if item.get("status") == "TRADING"
        and item.get("contractType") == "PERPETUAL"
        and item.get("quoteAsset") == "USDT"
        and item.get("marginAsset") == "USDT"
    )

    if not symbols:
        raise RuntimeError("لم يتم العثور على عقود Binance Futures USDT نشطة")

    with state_lock:
        active_symbols = symbols
        symbols_updated_at = time.time()

    print(f"✅ Symbols refreshed: {len(symbols)}", flush=True)
    return symbols


def fetch_klines(symbol: str, timeframe: str, limit: int = 60) -> Optional[List[list]]:
    url = f"{BINANCE_BASE_URL}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": timeframe, "limit": limit}

    for attempt in range(1, 3):
        try:
            response = get_session().get(
                url, params=params, timeout=REQUEST_TIMEOUT
            )

            if response.status_code in (418, 429):
                wait_seconds = 2 * attempt
                print(
                    f"⚠️ Binance rate limit | {symbol} {timeframe} | wait={wait_seconds}s",
                    flush=True,
                )
                time.sleep(wait_seconds)
                continue

            response.raise_for_status()
            rows = response.json()
            return rows if isinstance(rows, list) and len(rows) >= 30 else None

        except requests.RequestException as exc:
            if attempt == 2:
                print(f"⚠️ Fetch failed | {symbol} {timeframe} | {exc}", flush=True)
            else:
                time.sleep(0.4)

    return None


def tradingview_url(symbol: str) -> str:
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}.P"


def mark_and_send(unique_key: str, candle_timestamp: int, message: str) -> bool:
    """حجز الإشارة قبل الإرسال لمنع التكرار مع الفحص المتوازي."""
    with state_lock:
        if last_signals.get(unique_key) == candle_timestamp:
            return False
        last_signals[unique_key] = candle_timestamp

    if send_telegram_message(message):
        return True

    # عند فشل الإرسال، نسمح بالمحاولة في الدورة القادمة.
    with state_lock:
        if last_signals.get(unique_key) == candle_timestamp:
            last_signals.pop(unique_key, None)
    return False


def analyze_symbol(symbol: str, timeframe: str) -> Tuple[bool, int]:
    rows = fetch_klines(symbol, timeframe, limit=60)
    if not rows:
        return False, 0

    current = rows[-1]  # الشمعة الحالية المفتوحة: تنبيه حي بدون انتظار الإغلاق.
    previous = rows[-2]

    candle_timestamp = int(current[0])
    open_price = float(current[1])
    high = float(current[2])
    low = float(current[3])
    close = float(current[4])
    volume = float(current[5])
    previous_close = float(previous[4])

    candle_range = max(high - low, 1e-12)
    close_position = max(0.0, min(1.0, (close - low) / candle_range))
    buy_pct = close_position * 100.0
    sell_pct = 100.0 - buy_pct

    ticker_name = f"{symbol}.P"
    tv_url = tradingview_url(symbol)
    sent = 0

    # وقت الاكتشاف الفعلي داخل البوت؛ لا ندّعي أنه وقت ظهور علامة TradingView.
    detected_time = get_saudi_time()

    if timeframe == "15m":
        if buy_pct >= 75 and close > previous_close:
            key = f"{symbol}_{timeframe}_entry_buy"
            message = (
                "🟢 <b>دخول الآن شراء</b>\n\n"
                f"💰 العملة: #{ticker_name}\n"
                f"⏰ الفريم: {timeframe}\n"
                f"💵 السعر: {close}\n"
                f"📊 ضغط الشراء: {buy_pct:.1f}%\n"
                "📈 الحالة: تأكد زخم الشراء\n"
                f"🕒 وقت الاكتشاف: {detected_time} بتوقيت السعودية\n\n"
                f"🔗 <a href='{tv_url}'>TradingView</a>"
            )
            sent += int(mark_and_send(key, candle_timestamp, message))

        elif sell_pct >= 75 and close < previous_close:
            key = f"{symbol}_{timeframe}_entry_sell"
            message = (
                "🔴 <b>دخول الآن — بيع</b>\n\n"
                f"💰 العملة: #{ticker_name}\n"
                f"⏰ الفريم: {timeframe}\n"
                f"💵 السعر: {close}\n"
                f"📊 ضغط البيع: {sell_pct:.1f}%\n"
                "📉 الحالة: تأكد زخم البيع\n"
                f"🕒 وقت الاكتشاف: {detected_time} بتوقيت السعودية\n\n"
                f"🔗 <a href='{tv_url}'>TradingView</a>"
            )
            sent += int(mark_and_send(key, candle_timestamp, message))

        volumes = [float(row[5]) for row in rows[-20:]]
        average_volume = sum(volumes) / len(volumes) if volumes else 0.0
        high_volume = average_volume > 0 and volume > average_volume * 1.5

        if high_volume and buy_pct >= 80:
            key = f"{symbol}_{timeframe}_sm_buy"
            message = (
                "🚀 <b>SMART MONEY BUY — أول ظهور</b>\n\n"
                f"💰 العملة: #{ticker_name}\n"
                f"⏰ الفريم: {timeframe}\n"
                f"💵 السعر: {close}\n"
                f"📊 ضغط الشراء: {buy_pct:.1f}%\n"
                "🐋 حجم مرتفع مع سيطرة شرائية\n"
                f"🕒 وقت الاكتشاف: {detected_time} بتوقيت السعودية\n\n"
                f"🔗 <a href='{tv_url}'>TradingView</a>"
            )
            sent += int(mark_and_send(key, candle_timestamp, message))

        elif high_volume and sell_pct >= 80:
            key = f"{symbol}_{timeframe}_sm_sell"
            message = (
                "🚀 <b>SMART MONEY SELL — أول ظهور</b>\n\n"
                f"💰 العملة: #{ticker_name}\n"
                f"⏰ الفريم: {timeframe}\n"
                f"💵 السعر: {close}\n"
                f"📊 ضغط البيع: {sell_pct:.1f}%\n"
                "🐋 حجم مرتفع مع سيطرة بيعية\n"
                f"🕒 وقت الاكتشاف: {detected_time} بتوقيت السعودية\n\n"
                f"🔗 <a href='{tv_url}'>TradingView</a>"
            )
            sent += int(mark_and_send(key, candle_timestamp, message))

    elif timeframe == "1h":
        if 58 <= buy_pct < 75:
            key = f"{symbol}_{timeframe}_ready_buy"
            message = (
                "🟡 <b>استعداد شراء</b>\n\n"
                f"💰 العملة: #{ticker_name}\n"
                f"⏰ الفريم: {timeframe}\n"
                f"💵 السعر: {close}\n"
                f"📊 ضغط الشراء: {buy_pct:.1f}%\n"
                "⚠️ انتظر إشارة دخول الآن\n"
                f"🕒 وقت الاكتشاف: {detected_time} بتوقيت السعودية\n\n"
                f"🔗 <a href='{tv_url}'>TradingView</a>"
            )
            sent += int(mark_and_send(key, candle_timestamp, message))

        elif 58 <= sell_pct < 75:
            key = f"{symbol}_{timeframe}_ready_sell"
            message = (
                "🟠 <b>استعداد بيع</b>\n\n"
                f"💰 العملة: #{ticker_name}\n"
                f"⏰ الفريم: {timeframe}\n"
                f"💵 السعر: {close}\n"
                f"📊 ضغط البيع: {sell_pct:.1f}%\n"
                "⚠️ انتظر إشارة دخول الآن\n"
                f"🕒 وقت الاكتشاف: {detected_time} بتوقيت السعودية\n\n"
                f"🔗 <a href='{tv_url}'>TradingView</a>"
            )
            sent += int(mark_and_send(key, candle_timestamp, message))

    elif timeframe == "4h":
        delta_value = buy_pct - sell_pct

        if delta_value > 25:
            key = f"{symbol}_{timeframe}_delta_buy"
            message = (
                "⚡ <b>DELTA BUY</b>\n\n"
                f"💰 العملة: #{ticker_name}\n"
                f"⏰ الفريم: {timeframe}\n"
                f"💵 السعر: {close}\n"
                f"📊 قوة الضغط: {delta_value:.1f}\n"
                "📈 تدفق الحركة يميل إلى الشراء\n"
                f"🕒 وقت الاكتشاف: {detected_time} بتوقيت السعودية\n\n"
                f"🔗 <a href='{tv_url}'>TradingView</a>"
            )
            sent += int(mark_and_send(key, candle_timestamp, message))

        elif delta_value < -25:
            key = f"{symbol}_{timeframe}_delta_sell"
            message = (
                "⚡ <b>DELTA SELL</b>\n\n"
                f"💰 العملة: #{ticker_name}\n"
                f"⏰ الفريم: {timeframe}\n"
                f"💵 السعر: {close}\n"
                f"📊 قوة الضغط: {abs(delta_value):.1f}\n"
                "📉 تدفق الحركة يميل إلى البيع\n"
                f"🕒 وقت الاكتشاف: {detected_time} بتوقيت السعودية\n\n"
                f"🔗 <a href='{tv_url}'>TradingView</a>"
            )
            sent += int(mark_and_send(key, candle_timestamp, message))

    # حذف الحالات القديمة دوريًا لتجنب نمو الذاكرة بلا حدود.
    if len(last_signals) > 20000:
        cutoff = int((time.time() - 7 * 86400) * 1000)
        with state_lock:
            stale = [key for key, ts in last_signals.items() if ts < cutoff]
            for key in stale:
                last_signals.pop(key, None)

    return True, sent


def scan_batch(timeframe: str) -> None:
    """
    يفحص دفعة صغيرة بشكل متكرر بدل انتظار دورة ضخمة لكل السوق.
    النتيجة: كل عملة تصلها نوبة فحص أسرع بكثير من النسخة القديمة.
    """
    started = time.time()

    try:
        symbols = refresh_symbols()
    except Exception as exc:
        print(f"❌ Symbols refresh error: {exc}", flush=True)
        return

    with state_lock:
        start = scan_positions[timeframe]
        count = min(BATCH_SIZE, len(symbols))
        batch = [symbols[(start + i) % len(symbols)] for i in range(count)]
        scan_positions[timeframe] = (start + count) % len(symbols)

    checked = 0
    sent = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {
            executor.submit(analyze_symbol, symbol, timeframe): symbol
            for symbol in batch
        }

        for future in as_completed(futures):
            symbol = futures[future]
            try:
                ok, sent_count = future.result()
                checked += int(ok)
                sent += sent_count
            except Exception as exc:
                print(f"⚠️ Analyze failed | {symbol} {timeframe} | {exc}", flush=True)

    duration = time.time() - started
    with state_lock:
        scan_stats[timeframe] = {
            "last_duration": round(duration, 2),
            "last_checked": checked,
            "last_sent": sent,
            "last_run": get_saudi_time(),
            "next_position": scan_positions[timeframe],
        }

    print(
        f"✅ Batch {timeframe} | checked={checked}/{len(batch)} | "
        f"sent={sent} | duration={duration:.2f}s | next={scan_positions[timeframe]}",
        flush=True,
    )


# =========================================================
# Flask health check
# =========================================================
@app.route("/")
def index():
    return "Bot is running successfully!", 200


@app.route("/health")
def health():
    with state_lock:
        return {
            "status": "ok",
            "symbols": len(active_symbols),
            "saved_signal_states": len(last_signals),
            "batch_size": BATCH_SIZE,
            "workers": WORKERS,
            "scan_positions": dict(scan_positions),
            "scan_stats": dict(scan_stats),
            "saudi_time": get_saudi_time(),
        }, 200


# =========================================================
# التشغيل
# =========================================================
def start_scheduler() -> BackgroundScheduler:
    # تحميل الرموز مرة واحدة عند البدء.
    refresh_symbols(force=True)

    scheduler = BackgroundScheduler(timezone=SAUDI_TZ, daemon=True)

    # دفعات صغيرة متداخلة زمنيًا:
    # 15m أعلى أولوية، ثم 1h، ثم 4h.
    scheduler.add_job(
        scan_batch,
        "interval",
        seconds=2,
        args=["15m"],
        id="scan_15m",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.add_job(
        scan_batch,
        "interval",
        seconds=5,
        args=["1h"],
        id="scan_1h",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=1),
    )
    scheduler.add_job(
        scan_batch,
        "interval",
        seconds=10,
        args=["4h"],
        id="scan_4h",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=2),
    )

    scheduler.start()
    return scheduler


if __name__ == "__main__":
    print("✅ Script execution started.", flush=True)
    print(
        f"🚀 Fast scanner starting | workers={WORKERS} | batch={BATCH_SIZE}",
        flush=True,
    )

    scheduler = start_scheduler()
    print("✅ Scanner scheduler started.", flush=True)

    port = int(os.environ.get("PORT", "8080"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
