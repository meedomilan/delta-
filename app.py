
import asyncio
import json
import logging
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import aiohttp
import numpy as np
import pandas as pd
import uvicorn
from fastapi import FastAPI
from zoneinfo import ZoneInfo

BINANCE_REST = os.getenv("BINANCE_REST", "https://fapi.binance.com").rstrip("/")

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_TOKEN", "").strip()
)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

BREAKOUT_TIMEFRAME = "15m"
HIGHER_TIMEFRAMES = ("1h", "4h")
TF_SECONDS = {"15m": 900, "1h": 3600, "4h": 14400}
CONFIRM_TF = "1m"
CONTEXT_TF = "5m"

STRUCTURE_SCAN_SECONDS = int(os.getenv("STRUCTURE_SCAN_SECONDS", "20"))
RETEST_SCAN_SECONDS = int(os.getenv("RETEST_SCAN_SECONDS", "5"))
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "14"))
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "120"))
MIN_QUOTE_VOLUME = float(os.getenv("MIN_QUOTE_VOLUME", "3000000"))

LOOKBACK_BARS = int(os.getenv("LOOKBACK_BARS", "20"))
ATR_LENGTH = int(os.getenv("ATR_LENGTH", "14"))
BREAKOUT_BUFFER_ATR = float(os.getenv("BREAKOUT_BUFFER_ATR", "0.06"))
MIN_BREAKOUT_ATR = float(os.getenv("MIN_BREAKOUT_ATR", "0.05"))
MAX_BREAKOUT_EXTENSION_ATR = float(os.getenv("MAX_BREAKOUT_EXTENSION_ATR", "0.90"))

RETEST_ZONE_ATR = float(os.getenv("RETEST_ZONE_ATR", "0.14"))
RETEST_MAX_PENETRATION_ATR = float(os.getenv("RETEST_MAX_PENETRATION_ATR", "0.36"))
RECLAIM_BUFFER_ATR = float(os.getenv("RECLAIM_BUFFER_ATR", "0.015"))
MIN_CONFIRM_BODY_RATIO = float(os.getenv("MIN_CONFIRM_BODY_RATIO", "0.45"))
MIN_CONFIRM_CLOSE_POS = float(os.getenv("MIN_CONFIRM_CLOSE_POS", "0.62"))

SETUP_EXPIRY_15M_MIN = int(os.getenv("SETUP_EXPIRY_15M_MIN", "90"))
MAX_ENTRY_DISTANCE_ATR = float(os.getenv("MAX_ENTRY_DISTANCE_ATR", "0.24"))

SL_BUFFER_ATR = float(os.getenv("SL_BUFFER_ATR", "0.12"))
SWING_LOOKBACK_5M = int(os.getenv("SWING_LOOKBACK_5M", "12"))
MIN_RISK_ATR = float(os.getenv("MIN_RISK_ATR", "0.25"))
MAX_RISK_ATR = float(os.getenv("MAX_RISK_ATR", "0.85"))
TP1_R = float(os.getenv("TP1_R", "1.25"))
TP2_R = float(os.getenv("TP2_R", "2.0"))
TP3_R = float(os.getenv("TP3_R", "3.0"))

COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "240"))
SEND_SETUP_ALERT = os.getenv("SEND_SETUP_ALERT", "false").lower() == "true"
SEND_TEST_ON_START = os.getenv("SEND_TEST_ON_START", "true").lower() == "true"

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
if not DATA_DIR.exists():
    DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = Path(
    os.getenv("DATABASE_PATH", str(DATA_DIR / "retest_entry.db"))
)

TZ = ZoneInfo("Asia/Riyadh")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("ahmed-retest-entry-trader")

app = FastAPI(title="Ahmed Retest Entry Trader", version="4.0.0")

STATE: Dict[str, Any] = {
    "version": "4.0.0",
    "running": False,
    "symbols": 0,
    "active_setups": 0,
    "entries_sent": 0,
    "last_structure_scan": None,
    "last_retest_scan": None,
    "last_error": None,
    "started_at": datetime.now(TZ).isoformat(),
}

@dataclass
class BreakoutSetup:
    setup_key: str
    symbol: str
    timeframe: str
    direction: str
    breakout_level: float
    breakout_price: float
    atr_value: float
    breakout_time: int
    expires_at: int
    touched: bool
    touch_time: Optional[int]
    touch_price: Optional[float]
    invalidated: bool


def ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )

def db() -> sqlite3.Connection:
    connection = sqlite3.connect(str(DATABASE_PATH))
    connection.row_factory = sqlite3.Row

    connection.execute("""
        CREATE TABLE IF NOT EXISTS setups (
            setup_key TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            direction TEXT NOT NULL,
            breakout_level REAL NOT NULL,
            breakout_price REAL NOT NULL,
            atr_value REAL NOT NULL,
            breakout_time INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            touched INTEGER NOT NULL DEFAULT 0,
            touch_time INTEGER,
            touch_price REAL,
            invalidated INTEGER NOT NULL DEFAULT 0,
            entry_sent INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            entry_key TEXT PRIMARY KEY,
            setup_key TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            direction TEXT NOT NULL,
            breakout_level REAL NOT NULL,
            retest_price REAL NOT NULL,
            entry_low REAL NOT NULL,
            entry_high REAL NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            tp1 REAL NOT NULL,
            tp2 REAL NOT NULL,
            tp3 REAL NOT NULL,
            risk REAL NOT NULL,
            created_at INTEGER NOT NULL,
            outcome TEXT,
            outcome_time INTEGER,
            mfe_percent REAL,
            mae_percent REAL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_key TEXT NOT NULL,
            minutes_after INTEGER NOT NULL,
            price REAL NOT NULL,
            return_percent REAL NOT NULL,
            mfe_percent REAL NOT NULL,
            mae_percent REAL NOT NULL,
            evaluated_at INTEGER NOT NULL,
            UNIQUE(entry_key, minutes_after)
        )
    """)

    # ترقية قاعدة البيانات القديمة بدون حذف أي بيانات.
    ensure_column(connection, "entries", "tp1_hit", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "entries", "tp2_hit", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "entries", "tp3_hit", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "entries", "sl_hit", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "entries", "tp1_hit_time", "INTEGER")
    ensure_column(connection, "entries", "tp2_hit_time", "INTEGER")
    ensure_column(connection, "entries", "tp3_hit_time", "INTEGER")
    ensure_column(connection, "entries", "sl_hit_time", "INTEGER")
    ensure_column(connection, "entries", "first_event", "TEXT")
    ensure_column(connection, "entries", "first_event_time", "INTEGER")
    ensure_column(connection, "entries", "max_mfe_percent", "REAL")
    ensure_column(connection, "entries", "max_mae_percent", "REAL")
    ensure_column(connection, "entries", "last_evaluated_at", "INTEGER")

    connection.commit()
    return connection

def save_setup(setup: BreakoutSetup) -> None:
    with db() as connection:
        connection.execute("""
            INSERT OR IGNORE INTO setups (
                setup_key, symbol, timeframe, direction,
                breakout_level, breakout_price, atr_value,
                breakout_time, expires_at,
                touched, touch_time, touch_price,
                invalidated, entry_sent, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """, (
            setup.setup_key,
            setup.symbol,
            setup.timeframe,
            setup.direction,
            setup.breakout_level,
            setup.breakout_price,
            setup.atr_value,
            setup.breakout_time,
            setup.expires_at,
            int(setup.touched),
            setup.touch_time,
            setup.touch_price,
            int(setup.invalidated),
            int(time.time()),
        ))
        connection.commit()

def load_active_setups() -> List[BreakoutSetup]:
    now = int(time.time())
    with db() as connection:
        rows = connection.execute("""
            SELECT *
            FROM setups
            WHERE invalidated = 0
              AND entry_sent = 0
              AND expires_at > ?
            ORDER BY breakout_time ASC
        """, (now,)).fetchall()

    return [
        BreakoutSetup(
            setup_key=row["setup_key"],
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            direction=row["direction"],
            breakout_level=float(row["breakout_level"]),
            breakout_price=float(row["breakout_price"]),
            atr_value=float(row["atr_value"]),
            breakout_time=int(row["breakout_time"]),
            expires_at=int(row["expires_at"]),
            touched=bool(row["touched"]),
            touch_time=int(row["touch_time"]) if row["touch_time"] else None,
            touch_price=float(row["touch_price"]) if row["touch_price"] else None,
            invalidated=bool(row["invalidated"]),
        )
        for row in rows
    ]

def mark_touched(setup_key: str, price: float) -> None:
    with db() as connection:
        connection.execute("""
            UPDATE setups
            SET touched = 1,
                touch_time = ?,
                touch_price = ?
            WHERE setup_key = ?
        """, (int(time.time()), price, setup_key))
        connection.commit()

def invalidate_setup(setup_key: str) -> None:
    with db() as connection:
        connection.execute("""
            UPDATE setups
            SET invalidated = 1
            WHERE setup_key = ?
        """, (setup_key,))
        connection.commit()

def mark_entry_sent(setup_key: str) -> None:
    with db() as connection:
        connection.execute("""
            UPDATE setups
            SET entry_sent = 1
            WHERE setup_key = ?
        """, (setup_key,))
        connection.commit()

def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default

def convert_klines(raw: List[List[Any]]) -> pd.DataFrame:
    columns = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ]
    data = pd.DataFrame(raw, columns=columns)

    for column in [
        "open_time", "open", "high", "low", "close",
        "volume", "quote_volume", "taker_buy_base",
        "taker_buy_quote",
    ]:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    return data.dropna().reset_index(drop=True)

def atr(data: pd.DataFrame, length: int = ATR_LENGTH) -> pd.Series:
    previous_close = data["close"].shift(1)
    true_range = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return true_range.ewm(alpha=1 / length, adjust=False).mean()

def candle_close_position(row: pd.Series) -> float:
    candle_range = max(row["high"] - row["low"], 1e-12)
    return float(np.clip((row["close"] - row["low"]) / candle_range, 0, 1))

def candle_body_ratio(row: pd.Series) -> float:
    candle_range = max(row["high"] - row["low"], 1e-12)
    return abs(row["close"] - row["open"]) / candle_range

def setup_expiry_minutes(timeframe: str) -> int:
    return SETUP_EXPIRY_15M_MIN

async def get_json(
    session: aiohttp.ClientSession,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    retries: int = 3,
) -> Any:
    url = f"{BINANCE_REST}{endpoint}"

    for attempt in range(retries):
        try:
            async with session.get(
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=18),
            ) as response:
                if response.status in (418, 429):
                    await asyncio.sleep(2.5 * (attempt + 1))
                    continue

                if response.status == 451:
                    raise RuntimeError("Binance HTTP 451")

                response.raise_for_status()
                return await response.json()

        except Exception:
            if attempt == retries - 1:
                raise

            await asyncio.sleep(1.3 * (attempt + 1))

async def send_telegram(
    session: aiohttp.ClientSession,
    message: str,
) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram variables are missing.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    async with session.post(
        url,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=18),
    ) as response:
        body = await response.text()

        if response.status != 200:
            raise RuntimeError(f"Telegram error {response.status}: {body[:300]}")

async def load_symbols(
    session: aiohttp.ClientSession,
) -> List[str]:
    exchange_info, tickers = await asyncio.gather(
        get_json(session, "/fapi/v1/exchangeInfo"),
        get_json(session, "/fapi/v1/ticker/24hr"),
    )

    volume_map = {
        item["symbol"]: safe_float(item.get("quoteVolume"))
        for item in tickers
    }

    symbols: List[str] = []

    for item in exchange_info.get("symbols", []):
        symbol = item.get("symbol")

        if (
            symbol
            and item.get("status") == "TRADING"
            and item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT"
            and volume_map.get(symbol, 0) >= MIN_QUOTE_VOLUME
        ):
            symbols.append(symbol)

    return sorted(symbols)


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def higher_timeframe_direction(data: pd.DataFrame) -> str:
    """
    يحدد اتجاه الفريم الكبير من الشموع المغلقة فقط.
    لا نطلب اتجاهًا مثاليًا حتى لا نتأخر:
    - BUY: الإغلاق فوق EMA50 مع EMA25 >= EMA50 أو ميل EMA50 صاعد.
    - SELL: الإغلاق تحت EMA50 مع EMA25 <= EMA50 أو ميل EMA50 هابط.
    - غير ذلك NEUTRAL.
    """
    if len(data) < 60:
        return "NEUTRAL"

    closed = data.iloc[:-1].copy()
    if len(closed) < 55:
        return "NEUTRAL"

    close = closed["close"]
    ema25 = ema(close, 25)
    ema50 = ema(close, 50)

    last_close = float(close.iloc[-1])
    e25 = float(ema25.iloc[-1])
    e50 = float(ema50.iloc[-1])
    e50_prev = float(ema50.iloc[-4])

    slope_up = e50 > e50_prev
    slope_down = e50 < e50_prev

    if last_close > e50 and (e25 >= e50 or slope_up):
        return "BUY"

    if last_close < e50 and (e25 <= e50 or slope_down):
        return "SELL"

    return "NEUTRAL"


async def validate_higher_timeframes(
    session: aiohttp.ClientSession,
    symbol: str,
    breakout_direction: str,
) -> Tuple[bool, str, str]:
    """
    1H هو الاتجاه الرئيسي.
    4H يجب ألا يكون معاكسًا بقوة.
    هذا يحافظ على السرعة ولا يجعل الفلتر صارمًا جدًا.
    """
    raw_1h, raw_4h = await asyncio.gather(
        get_json(session, "/fapi/v1/klines", {
            "symbol": symbol,
            "interval": "1h",
            "limit": 80,
        }),
        get_json(session, "/fapi/v1/klines", {
            "symbol": symbol,
            "interval": "4h",
            "limit": 80,
        }),
    )

    dir_1h = higher_timeframe_direction(convert_klines(raw_1h))
    dir_4h = higher_timeframe_direction(convert_klines(raw_4h))

    # 1H يجب أن يوافق الكسر أو يكون محايدًا.
    if dir_1h not in (breakout_direction, "NEUTRAL"):
        return False, dir_1h, dir_4h

    # 4H لا نطلب منه الموافقة الكاملة، فقط ألا يكون معاكسًا.
    if dir_4h not in (breakout_direction, "NEUTRAL"):
        return False, dir_1h, dir_4h

    # على الأقل أحد الفريمين يجب أن يوافق الاتجاه فعليًا.
    if breakout_direction not in (dir_1h, dir_4h):
        return False, dir_1h, dir_4h

    return True, dir_1h, dir_4h


async def analyze_structure(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    symbol: str,
    timeframe: str,
) -> Optional[BreakoutSetup]:

    async with semaphore:
        try:
            raw = await get_json(
                session,
                "/fapi/v1/klines",
                {
                    "symbol": symbol,
                    "interval": timeframe,
                    "limit": KLINE_LIMIT,
                },
            )

            data = convert_klines(raw)

            if len(data) < max(LOOKBACK_BARS + ATR_LENGTH + 5, 40):
                return None

            current = data.iloc[-1]
            closed = data.iloc[:-1].copy()

            atr_value = safe_float(atr(closed, ATR_LENGTH).iloc[-1])

            if atr_value <= 0:
                return None

            recent = closed.iloc[-LOOKBACK_BARS:]

            resistance = float(recent["high"].max())
            support = float(recent["low"].min())

            live_price = float(current["close"])

            buy_break_distance = (live_price - resistance) / atr_value
            sell_break_distance = (support - live_price) / atr_value

            if (
                buy_break_distance >= MIN_BREAKOUT_ATR
                and buy_break_distance <= MAX_BREAKOUT_EXTENSION_ATR
            ):
                direction = "BUY"
                level = resistance

            elif (
                sell_break_distance >= MIN_BREAKOUT_ATR
                and sell_break_distance <= MAX_BREAKOUT_EXTENSION_ATR
            ):
                direction = "SELL"
                level = support

            else:
                return None

            required_buffer = atr_value * BREAKOUT_BUFFER_ATR

            if direction == "BUY" and live_price < level + required_buffer:
                return None

            if direction == "SELL" and live_price > level - required_buffer:
                return None

            higher_ok, direction_1h, direction_4h = await validate_higher_timeframes(
                session,
                symbol,
                direction,
            )

            if not higher_ok:
                return None

            breakout_bucket = int(time.time()) // TF_SECONDS[timeframe]

            setup_key = (
                f"{symbol}:{timeframe}:{direction}:"
                f"{round(level, 10)}:{breakout_bucket}"
            )

            now = int(time.time())

            return BreakoutSetup(
                setup_key=setup_key,
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                breakout_level=level,
                breakout_price=live_price,
                atr_value=atr_value,
                breakout_time=now,
                expires_at=now + setup_expiry_minutes(timeframe) * 60,
                touched=False,
                touch_time=None,
                touch_price=None,
                invalidated=False,
            )

        except Exception as error:
            log.warning("Structure failed %s %s: %s", symbol, timeframe, error)
            return None

async def structure_scan(
    session: aiohttp.ClientSession,
    symbols: List[str],
) -> None:
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    results = await asyncio.gather(
        *[
            analyze_structure(
                session,
                semaphore,
                symbol,
                BREAKOUT_TIMEFRAME,
            )
            for symbol in symbols
        ]
    )

    for setup in results:
        if setup is None:
            continue

        with db() as connection:
            exists = connection.execute(
                "SELECT setup_key FROM setups WHERE setup_key = ?",
                (setup.setup_key,),
            ).fetchone()

        if exists:
            continue

        save_setup(setup)

        log.info(
            "Breakout setup %s %s %s level=%s",
            setup.symbol,
            setup.timeframe,
            setup.direction,
            setup.breakout_level,
        )

        if SEND_SETUP_ALERT:
            direction_ar = "شراء" if setup.direction == "BUY" else "بيع"

            await send_telegram(
                session,
                (
                    f"👀 <b>رصد كسر — انتظار إعادة الاختبار</b>\n\n"
                    f"💰 العملة: <b>#{setup.symbol}.P</b>\n"
                    f"⏰ الفريم: <b>{setup.timeframe.upper()}</b>\n"
                    f"🧭 الاتجاه: <b>{direction_ar}</b>\n"
                    f"📍 مستوى الكسر: <code>{setup.breakout_level:.10g}</code>\n\n"
                    f"⏳ لا دخول الآن — ننتظر إعادة الاختبار."
                ),
            )

async def get_latest_prices(
    session: aiohttp.ClientSession,
) -> Dict[str, float]:
    raw = await get_json(session, "/fapi/v1/ticker/price")

    return {
        item["symbol"]: safe_float(item.get("price"))
        for item in raw
        if item.get("symbol")
    }

async def get_micro_klines(
    session: aiohttp.ClientSession,
    symbol: str,
    interval: str,
    limit: int = 8,
) -> pd.DataFrame:
    raw = await get_json(
        session,
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
    )
    return convert_klines(raw)

def retest_zone(
    setup: BreakoutSetup,
) -> Tuple[float, float]:
    width = setup.atr_value * RETEST_ZONE_ATR
    return (
        setup.breakout_level - width,
        setup.breakout_level + width,
    )

def is_hard_invalidated(
    setup: BreakoutSetup,
    price: float,
) -> bool:
    penetration = setup.atr_value * RETEST_MAX_PENETRATION_ATR

    if setup.direction == "BUY":
        return price < setup.breakout_level - penetration

    return price > setup.breakout_level + penetration

def price_touched_zone(
    setup: BreakoutSetup,
    price: float,
) -> bool:
    zone_low, zone_high = retest_zone(setup)
    return zone_low <= price <= zone_high

def entry_too_far(
    setup: BreakoutSetup,
    price: float,
) -> bool:
    distance = abs(price - setup.breakout_level) / max(setup.atr_value, 1e-12)
    return distance > MAX_ENTRY_DISTANCE_ATR

def micro_confirmation(
    setup: BreakoutSetup,
    one_minute: pd.DataFrame,
    five_minute: pd.DataFrame,
) -> bool:
    if len(one_minute) < 3:
        return False

    candle = one_minute.iloc[-2]
    body_ratio = candle_body_ratio(candle)
    close_pos = candle_close_position(candle)
    reclaim_buffer = setup.atr_value * RECLAIM_BUFFER_ATR

    context_ok = True

    if len(five_minute) >= 3:
        five_closed = five_minute.iloc[-2]
        five_pos = candle_close_position(five_closed)

        if setup.direction == "BUY":
            context_ok = five_pos >= 0.32
        else:
            context_ok = five_pos <= 0.68

    if not context_ok:
        return False

    if setup.direction == "BUY":
        bullish = candle["close"] > candle["open"]
        reclaimed = candle["close"] > setup.breakout_level + reclaim_buffer
        rejection = (
            candle["low"]
            <= setup.breakout_level + setup.atr_value * RETEST_ZONE_ATR
        )
        strong_close = close_pos >= MIN_CONFIRM_CLOSE_POS

        return (
            bullish
            and reclaimed
            and rejection
            and strong_close
            and body_ratio >= MIN_CONFIRM_BODY_RATIO
        )

    bearish = candle["close"] < candle["open"]
    reclaimed = candle["close"] < setup.breakout_level - reclaim_buffer
    rejection = (
        candle["high"]
        >= setup.breakout_level - setup.atr_value * RETEST_ZONE_ATR
    )
    strong_close = close_pos <= 1 - MIN_CONFIRM_CLOSE_POS

    return (
        bearish
        and reclaimed
        and rejection
        and strong_close
        and body_ratio >= MIN_CONFIRM_BODY_RATIO
    )

def build_trade_plan(
    setup: BreakoutSetup,
    confirmation_data: pd.DataFrame,
    context_data: pd.DataFrame,
    current_price: float,
) -> Dict[str, float]:
    # الوقف يعتمد على هيكل إعادة الاختبار 5M وليس ذيول 1M الصغيرة.
    closed_1m = confirmation_data.iloc[:-1].tail(4)
    closed_5m = context_data.iloc[:-1].tail(SWING_LOOKBACK_5M)
    closed = closed_5m if not closed_5m.empty else closed_1m
    zone_low, zone_high = retest_zone(setup)

    if setup.direction == "BUY":
        retest_swing = float(closed["low"].min())

        stop_candidate = min(
            retest_swing - setup.atr_value * SL_BUFFER_ATR,
            setup.breakout_level - setup.atr_value * MIN_RISK_ATR,
        )

        raw_risk = current_price - stop_candidate
        min_risk = setup.atr_value * MIN_RISK_ATR
        risk = max(raw_risk, min_risk)

        # الوقف الحقيقي يبقى أسفل آخر قاع 5M + هامش، ولا نقربه صناعيًا.
        stop_loss = current_price - risk

        entry_low = min(
            current_price,
            max(
                zone_low,
                setup.breakout_level - setup.atr_value * 0.04,
            ),
        )

        entry_high = current_price

        tp1 = current_price + risk * TP1_R
        tp2 = current_price + risk * TP2_R
        tp3 = current_price + risk * TP3_R

    else:
        retest_swing = float(closed["high"].max())

        stop_candidate = max(
            retest_swing + setup.atr_value * SL_BUFFER_ATR,
            setup.breakout_level + setup.atr_value * MIN_RISK_ATR,
        )

        raw_risk = stop_candidate - current_price
        min_risk = setup.atr_value * MIN_RISK_ATR
        risk = max(raw_risk, min_risk)

        # الوقف الحقيقي يبقى أعلى آخر قمة 5M + هامش، ولا نقربه صناعيًا.
        stop_loss = current_price + risk

        entry_low = current_price

        entry_high = max(
            current_price,
            min(
                zone_high,
                setup.breakout_level + setup.atr_value * 0.04,
            ),
        )

        tp1 = current_price - risk * TP1_R
        tp2 = current_price - risk * TP2_R
        tp3 = current_price - risk * TP3_R

    return {
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_price": current_price,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk": risk,
        "retest_swing": retest_swing,
    }

def save_entry(
    setup: BreakoutSetup,
    plan: Dict[str, float],
) -> str:
    entry_key = f"{setup.setup_key}:ENTRY:{int(time.time())}"

    with db() as connection:
        connection.execute("""
            INSERT INTO entries (
                entry_key, setup_key, symbol, timeframe, direction,
                breakout_level, retest_price,
                entry_low, entry_high, entry_price,
                stop_loss, tp1, tp2, tp3, risk, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry_key,
            setup.setup_key,
            setup.symbol,
            setup.timeframe,
            setup.direction,
            setup.breakout_level,
            setup.touch_price or setup.breakout_level,
            plan["entry_low"],
            plan["entry_high"],
            plan["entry_price"],
            plan["stop_loss"],
            plan["tp1"],
            plan["tp2"],
            plan["tp3"],
            plan["risk"],
            int(time.time()),
        ))
        connection.commit()

    return entry_key

def build_entry_message(
    setup: BreakoutSetup,
    plan: Dict[str, float],
) -> str:
    is_buy = setup.direction == "BUY"

    title = (
        "🔵 دخول الآن بعد إعادة الاختبار — شراء"
        if is_buy
        else
        "🔵 دخول الآن بعد إعادة الاختبار — بيع"
    )

    now_text = datetime.now(TZ).strftime("%d-%m-%Y %H:%M:%S")

    tv = (
        "https://www.tradingview.com/chart/"
        f"?symbol=BINANCE:{quote(setup.symbol)}.P"
    )

    bn = f"https://www.binance.com/en/futures/{setup.symbol}"

    distance_atr = abs(
        plan["entry_price"] - setup.breakout_level
    ) / max(setup.atr_value, 1e-12)

    return (
        f"<b>{title}</b>\n\n"
        f"💰 العملة: <b>#{setup.symbol}.P</b>\n"
        f"⏰ فريم الكسر: <b>15M</b>\n"
        f"🧭 اتجاه أعلى: <b>1H / 4H</b>\n"
        f"⚡ تأكيد إعادة الاختبار: <b>1M</b>\n\n"
        f"📍 مستوى الكسر: <code>{setup.breakout_level:.10g}</code>\n"
        f"🎯 منطقة الدخول: "
        f"<code>{plan['entry_low']:.10g} – {plan['entry_high']:.10g}</code>\n"
        f"💵 دخول مرجعي: <code>{plan['entry_price']:.10g}</code>\n"
        f"🛑 وقف الخسارة: <code>{plan['stop_loss']:.10g}</code>\n\n"
        f"✅ TP1: <code>{plan['tp1']:.10g}</code> ({TP1_R:.1f}R)\n"
        f"✅ TP2: <code>{plan['tp2']:.10g}</code> ({TP2_R:.1f}R)\n"
        f"✅ TP3: <code>{plan['tp3']:.10g}</code> ({TP3_R:.1f}R)\n\n"
        f"📏 بعد الدخول عن مستوى الكسر: <b>{distance_atr:.2f} ATR</b>\n"
        f"✅ الكسر تم أولًا\n"
        f"✅ السعر عاد إلى منطقة الكسر\n"
        f"✅ شمعة 1M أكدت الاسترداد/الرفض\n"
        f"✅ لم ننتظر إغلاق شمعة 1H أو 4H\n\n"
        f"🕒 {now_text} (السعودية)\n"
        f'🔗 <a href="{bn}">Binance</a> | '
        f'<a href="{tv}">TradingView</a>\n\n'
        f"⚠️ خطة تداول احتمالية وليست ضمانًا"
    )

async def retest_scan(
    session: aiohttp.ClientSession,
) -> None:
    setups = load_active_setups()
    STATE["active_setups"] = len(setups)

    if not setups:
        STATE["last_retest_scan"] = datetime.now(TZ).isoformat()
        return

    price_map = await get_latest_prices(session)

    for setup in setups:
        price = price_map.get(setup.symbol)

        if not price or price <= 0:
            continue

        if is_hard_invalidated(setup, price):
            invalidate_setup(setup.setup_key)
            log.info(
                "Setup invalidated %s %s %s",
                setup.symbol,
                setup.timeframe,
                setup.direction,
            )
            continue

        if not setup.touched:
            if price_touched_zone(setup, price):
                mark_touched(setup.setup_key, price)

                setup.touched = True
                setup.touch_time = int(time.time())
                setup.touch_price = price

                log.info(
                    "Retest touched %s %s %s price=%s",
                    setup.symbol,
                    setup.timeframe,
                    setup.direction,
                    price,
                )
            else:
                continue

        if entry_too_far(setup, price):
            continue

        try:
            one_minute, five_minute = await asyncio.gather(
                get_micro_klines(session, setup.symbol, CONFIRM_TF, 8),
                get_micro_klines(session, setup.symbol, CONTEXT_TF, 6),
            )

            if not micro_confirmation(setup, one_minute, five_minute):
                continue

            plan = build_trade_plan(setup, one_minute, five_minute, price)

            save_entry(setup, plan)
            mark_entry_sent(setup.setup_key)

            await send_telegram(
                session,
                build_entry_message(setup, plan),
            )

            STATE["entries_sent"] += 1

            log.info(
                "ENTRY SENT %s %s %s price=%s",
                setup.symbol,
                setup.timeframe,
                setup.direction,
                price,
            )

        except Exception as error:
            log.warning(
                "Retest confirm failed %s: %s",
                setup.setup_key,
                error,
            )

    STATE["last_retest_scan"] = datetime.now(TZ).isoformat()

CHECKPOINTS = (5, 15, 30, 60)


async def evaluate_entries(
    session: aiohttp.ClientSession,
) -> None:
    """
    يتابع كل دخول:
    - نقاط 5/15/30/60 دقيقة.
    - TP1 / TP2 / TP3 / SL.
    - أول حدث تحقق.
    - MFE / MAE القصوى.
    """
    now = int(time.time())

    with db() as connection:
        entries = connection.execute("""
            SELECT *
            FROM entries
            WHERE created_at >= ?
            ORDER BY created_at ASC
            LIMIT 1000
        """, (now - 7 * 86400,)).fetchall()

    for entry in entries:
        entry_price = float(entry["entry_price"])
        direction = entry["direction"]

        # ---------------- Checkpoints ----------------
        for minutes_after in CHECKPOINTS:
            due = int(entry["created_at"]) + minutes_after * 60
            if now < due:
                continue

            with db() as connection:
                exists = connection.execute("""
                    SELECT id
                    FROM checkpoints
                    WHERE entry_key = ?
                      AND minutes_after = ?
                """, (
                    entry["entry_key"],
                    minutes_after,
                )).fetchone()

            if exists:
                continue

            try:
                raw = await get_json(
                    session,
                    "/fapi/v1/klines",
                    {
                        "symbol": entry["symbol"],
                        "interval": "1m",
                        "startTime": int(entry["created_at"]) * 1000,
                        "endTime": due * 1000,
                        "limit": 1000,
                    },
                )

                data = convert_klines(raw)
                if data.empty:
                    continue

                final_price = float(data["close"].iloc[-1])

                if direction == "BUY":
                    ret = (final_price - entry_price) / entry_price * 100
                    mfe = (data["high"].max() - entry_price) / entry_price * 100
                    mae = (data["low"].min() - entry_price) / entry_price * 100
                else:
                    ret = (entry_price - final_price) / entry_price * 100
                    mfe = (entry_price - data["low"].min()) / entry_price * 100
                    mae = (entry_price - data["high"].max()) / entry_price * 100

                with db() as connection:
                    connection.execute("""
                        INSERT OR IGNORE INTO checkpoints (
                            entry_key, minutes_after, price,
                            return_percent, mfe_percent,
                            mae_percent, evaluated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        entry["entry_key"],
                        minutes_after,
                        final_price,
                        round(ret, 4),
                        round(mfe, 4),
                        round(mae, 4),
                        now,
                    ))
                    connection.commit()

            except Exception as error:
                log.warning(
                    "Checkpoint error %s %sm: %s",
                    entry["entry_key"],
                    minutes_after,
                    error,
                )

        # ---------------- TP/SL + MFE/MAE ----------------
        try:
            # حتى 1000 دقيقة من الدخول في كل تقييم؛ كافٍ لمعظم صفقات هذا النظام.
            raw = await get_json(
                session,
                "/fapi/v1/klines",
                {
                    "symbol": entry["symbol"],
                    "interval": "1m",
                    "startTime": int(entry["created_at"]) * 1000,
                    "limit": 1000,
                },
            )

            data = convert_klines(raw)
            if data.empty:
                continue

            if direction == "BUY":
                max_mfe = (data["high"].max() - entry_price) / entry_price * 100
                max_mae = (data["low"].min() - entry_price) / entry_price * 100
            else:
                max_mfe = (entry_price - data["low"].min()) / entry_price * 100
                max_mae = (entry_price - data["high"].max()) / entry_price * 100

            tp1_hit = bool(entry["tp1_hit"])
            tp2_hit = bool(entry["tp2_hit"])
            tp3_hit = bool(entry["tp3_hit"])
            sl_hit = bool(entry["sl_hit"])

            tp1_time = entry["tp1_hit_time"]
            tp2_time = entry["tp2_hit_time"]
            tp3_time = entry["tp3_hit_time"]
            sl_time = entry["sl_hit_time"]
            first_event = entry["first_event"]
            first_event_time = entry["first_event_time"]

            for _, candle in data.iterrows():
                candle_time = int(candle["open_time"] / 1000)

                if direction == "BUY":
                    hit_sl = candle["low"] <= float(entry["stop_loss"])
                    hit_tp1 = candle["high"] >= float(entry["tp1"])
                    hit_tp2 = candle["high"] >= float(entry["tp2"])
                    hit_tp3 = candle["high"] >= float(entry["tp3"])
                else:
                    hit_sl = candle["high"] >= float(entry["stop_loss"])
                    hit_tp1 = candle["low"] <= float(entry["tp1"])
                    hit_tp2 = candle["low"] <= float(entry["tp2"])
                    hit_tp3 = candle["low"] <= float(entry["tp3"])

                # إذا TP1 والوقف في نفس شمعة 1m فلا نخمن أيهما سبق.
                if not first_event and hit_sl and hit_tp1:
                    first_event = "AMBIGUOUS_SAME_1M"
                    first_event_time = candle_time

                elif not first_event:
                    if hit_sl:
                        first_event = "SL_FIRST"
                        first_event_time = candle_time
                    elif hit_tp1:
                        first_event = "TP1_FIRST"
                        first_event_time = candle_time

                if hit_tp1 and not tp1_hit:
                    tp1_hit = True
                    tp1_time = candle_time

                if hit_tp2 and not tp2_hit:
                    tp2_hit = True
                    tp2_time = candle_time

                if hit_tp3 and not tp3_hit:
                    tp3_hit = True
                    tp3_time = candle_time

                if hit_sl and not sl_hit:
                    sl_hit = True
                    sl_time = candle_time

            # توافق مع عمود outcome القديم.
            outcome = first_event

            with db() as connection:
                connection.execute("""
                    UPDATE entries
                    SET
                        tp1_hit = ?,
                        tp2_hit = ?,
                        tp3_hit = ?,
                        sl_hit = ?,
                        tp1_hit_time = ?,
                        tp2_hit_time = ?,
                        tp3_hit_time = ?,
                        sl_hit_time = ?,
                        first_event = ?,
                        first_event_time = ?,
                        outcome = ?,
                        outcome_time = ?,
                        max_mfe_percent = ?,
                        max_mae_percent = ?,
                        mfe_percent = ?,
                        mae_percent = ?,
                        last_evaluated_at = ?
                    WHERE entry_key = ?
                """, (
                    int(tp1_hit),
                    int(tp2_hit),
                    int(tp3_hit),
                    int(sl_hit),
                    tp1_time,
                    tp2_time,
                    tp3_time,
                    sl_time,
                    first_event,
                    first_event_time,
                    outcome,
                    first_event_time,
                    round(float(max_mfe), 4),
                    round(float(max_mae), 4),
                    round(float(max_mfe), 4),
                    round(float(max_mae), 4),
                    now,
                    entry["entry_key"],
                ))
                connection.commit()

        except Exception as error:
            log.warning(
                "Outcome error %s: %s",
                entry["entry_key"],
                error,
            )

async def main_loop() -> None:
    STATE["running"] = True

    connector = aiohttp.TCPConnector(
        limit=MAX_CONCURRENCY * 2,
        ttl_dns_cache=300,
    )

    async with aiohttp.ClientSession(connector=connector) as session:

        if SEND_TEST_ON_START:
            try:
                await send_telegram(
                    session,
                    (
                        "✅ <b>Ahmed Retest Entry Trader يعمل</b>\n\n"
                        "🎯 الدخول: بعد إعادة الاختبار فقط\n"
                        "🧭 الاتجاه: 1H و4H\n"
                        "💥 الكسر وإعادة الاختبار: 15M\n"
                        "⚡ تأكيد الدخول: 1M\n"
                        "🚫 لا ينتظر إغلاق شمعة 1H/4H\n"
                        "🛑 SL + TP1/TP2/TP3\n\n"
                        f"🕒 {datetime.now(TZ).strftime('%d-%m-%Y %H:%M:%S')} "
                        "(السعودية)"
                    ),
                )
            except Exception as error:
                log.error(
                    "Startup Telegram failed: %s",
                    error,
                )

        symbols: List[str] = []

        last_symbols_refresh = 0.0
        last_structure_scan = 0.0
        last_retest_scan = 0.0
        last_evaluation = 0.0

        while True:
            cycle_start = time.time()

            try:
                if (
                    not symbols
                    or time.time() - last_symbols_refresh > 3600
                ):
                    symbols = await load_symbols(session)
                    last_symbols_refresh = time.time()
                    STATE["symbols"] = len(symbols)

                    log.info(
                        "Loaded %d symbols",
                        len(symbols),
                    )

                if (
                    time.time() - last_structure_scan
                    >= STRUCTURE_SCAN_SECONDS
                ):
                    await structure_scan(session, symbols)
                    last_structure_scan = time.time()
                    STATE["last_structure_scan"] = datetime.now(TZ).isoformat()

                if (
                    time.time() - last_retest_scan
                    >= RETEST_SCAN_SECONDS
                ):
                    await retest_scan(session)
                    last_retest_scan = time.time()

                if (
                    time.time() - last_evaluation
                    >= 300
                ):
                    await evaluate_entries(session)
                    last_evaluation = time.time()

                STATE["last_error"] = None

            except Exception as error:
                STATE["last_error"] = str(error)
                log.exception("Main loop error")

            elapsed = time.time() - cycle_start

            await asyncio.sleep(
                max(
                    1.0,
                    min(
                        RETEST_SCAN_SECONDS,
                        RETEST_SCAN_SECONDS - elapsed,
                    ),
                )
            )

@app.on_event("startup")
async def startup_event() -> None:
    db().close()
    asyncio.create_task(main_loop())

@app.get("/")
async def root() -> Dict[str, Any]:
    return {"status": "ok", **STATE}

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "healthy", **STATE}

@app.get("/stats")
async def stats() -> Dict[str, Any]:
    with db() as connection:
        total_setups = connection.execute(
            "SELECT COUNT(*) AS c FROM setups"
        ).fetchone()["c"]

        touched = connection.execute(
            "SELECT COUNT(*) AS c FROM setups WHERE touched = 1"
        ).fetchone()["c"]

        invalidated = connection.execute(
            "SELECT COUNT(*) AS c FROM setups WHERE invalidated = 1"
        ).fetchone()["c"]

        entries = connection.execute(
            "SELECT COUNT(*) AS c FROM entries"
        ).fetchone()["c"]

        buy_entries = connection.execute(
            "SELECT COUNT(*) AS c FROM entries WHERE direction = 'BUY'"
        ).fetchone()["c"]

        sell_entries = connection.execute(
            "SELECT COUNT(*) AS c FROM entries WHERE direction = 'SELL'"
        ).fetchone()["c"]

        tp1_hits = connection.execute(
            "SELECT COUNT(*) AS c FROM entries WHERE tp1_hit = 1"
        ).fetchone()["c"]

        tp2_hits = connection.execute(
            "SELECT COUNT(*) AS c FROM entries WHERE tp2_hit = 1"
        ).fetchone()["c"]

        tp3_hits = connection.execute(
            "SELECT COUNT(*) AS c FROM entries WHERE tp3_hit = 1"
        ).fetchone()["c"]

        sl_hits = connection.execute(
            "SELECT COUNT(*) AS c FROM entries WHERE sl_hit = 1"
        ).fetchone()["c"]

        tp1_first = connection.execute(
            "SELECT COUNT(*) AS c FROM entries WHERE first_event = 'TP1_FIRST'"
        ).fetchone()["c"]

        sl_first = connection.execute(
            "SELECT COUNT(*) AS c FROM entries WHERE first_event = 'SL_FIRST'"
        ).fetchone()["c"]

        ambiguous = connection.execute(
            "SELECT COUNT(*) AS c FROM entries WHERE first_event = 'AMBIGUOUS_SAME_1M'"
        ).fetchone()["c"]

        pending = connection.execute(
            "SELECT COUNT(*) AS c FROM entries WHERE first_event IS NULL"
        ).fetchone()["c"]

        averages = connection.execute("""
            SELECT
                ROUND(AVG(max_mfe_percent), 4) AS avg_mfe,
                ROUND(AVG(max_mae_percent), 4) AS avg_mae
            FROM entries
            WHERE max_mfe_percent IS NOT NULL
        """).fetchone()

        by_direction = [
            dict(row)
            for row in connection.execute("""
                SELECT
                    direction,
                    COUNT(*) AS entries,
                    SUM(CASE WHEN tp1_hit = 1 THEN 1 ELSE 0 END) AS tp1_hits,
                    SUM(CASE WHEN tp2_hit = 1 THEN 1 ELSE 0 END) AS tp2_hits,
                    SUM(CASE WHEN tp3_hit = 1 THEN 1 ELSE 0 END) AS tp3_hits,
                    SUM(CASE WHEN sl_hit = 1 THEN 1 ELSE 0 END) AS sl_hits,
                    SUM(CASE WHEN first_event = 'TP1_FIRST' THEN 1 ELSE 0 END) AS tp1_first,
                    SUM(CASE WHEN first_event = 'SL_FIRST' THEN 1 ELSE 0 END) AS sl_first,
                    ROUND(AVG(max_mfe_percent), 4) AS avg_mfe,
                    ROUND(AVG(max_mae_percent), 4) AS avg_mae
                FROM entries
                GROUP BY direction
                ORDER BY direction
            """).fetchall()
        ]

    decided = tp1_first + sl_first

    return {
        "version": "4.0.0",
        "strategy": "1H/4H trend -> 15M breakout -> 5M retest -> 1M confirmation",
        "total_breakout_setups": total_setups,
        "retests_touched": touched,
        "invalidated_setups": invalidated,
        "entries_after_retest": entries,
        "buy_entries": buy_entries,
        "sell_entries": sell_entries,
        "tp1_hits": tp1_hits,
        "tp2_hits": tp2_hits,
        "tp3_hits": tp3_hits,
        "sl_hits": sl_hits,
        "tp1_first": tp1_first,
        "sl_first": sl_first,
        "ambiguous_same_1m": ambiguous,
        "pending_entries": pending,
        "tp1_before_sl_rate": (
            round(tp1_first / decided * 100, 2)
            if decided else None
        ),
        "tp1_hit_rate_all_entries": (
            round(tp1_hits / entries * 100, 2)
            if entries else None
        ),
        "tp2_hit_rate_all_entries": (
            round(tp2_hits / entries * 100, 2)
            if entries else None
        ),
        "tp3_hit_rate_all_entries": (
            round(tp3_hits / entries * 100, 2)
            if entries else None
        ),
        "average_mfe_percent": averages["avg_mfe"],
        "average_mae_percent": averages["avg_mae"],
        "by_direction": by_direction,
    }


@app.get("/trades")
async def trades(limit: int = 100) -> Dict[str, Any]:
    limit = max(1, min(limit, 500))

    with db() as connection:
        rows = connection.execute("""
            SELECT
                entry_key,
                symbol,
                timeframe,
                direction,
                breakout_level,
                retest_price,
                entry_low,
                entry_high,
                entry_price,
                stop_loss,
                tp1,
                tp2,
                tp3,
                created_at,
                tp1_hit,
                tp2_hit,
                tp3_hit,
                sl_hit,
                first_event,
                max_mfe_percent,
                max_mae_percent
            FROM entries
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

    return {
        "count": len(rows),
        "trades": [dict(row) for row in rows],
    }


@app.get("/stats/by-direction")
async def stats_by_direction() -> Dict[str, Any]:
    with db() as connection:
        rows = connection.execute("""
            SELECT
                direction,
                COUNT(*) AS entries,
                SUM(CASE WHEN tp1_hit = 1 THEN 1 ELSE 0 END) AS tp1_hits,
                SUM(CASE WHEN tp2_hit = 1 THEN 1 ELSE 0 END) AS tp2_hits,
                SUM(CASE WHEN tp3_hit = 1 THEN 1 ELSE 0 END) AS tp3_hits,
                SUM(CASE WHEN sl_hit = 1 THEN 1 ELSE 0 END) AS sl_hits,
                SUM(CASE WHEN first_event = 'TP1_FIRST' THEN 1 ELSE 0 END) AS tp1_first,
                SUM(CASE WHEN first_event = 'SL_FIRST' THEN 1 ELSE 0 END) AS sl_first,
                ROUND(AVG(max_mfe_percent), 4) AS avg_mfe,
                ROUND(AVG(max_mae_percent), 4) AS avg_mae
            FROM entries
            GROUP BY direction
            ORDER BY direction
        """).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        decided = (item["tp1_first"] or 0) + (item["sl_first"] or 0)
        item["tp1_before_sl_rate"] = (
            round((item["tp1_first"] or 0) / decided * 100, 2)
            if decided else None
        )
        result.append(item)

    return {"by_direction": result}


@app.get("/checkpoints")
async def checkpoints() -> Dict[str, Any]:
    with db() as connection:
        rows = connection.execute("""
            SELECT
                entries.timeframe,
                entries.direction,
                checkpoints.minutes_after,
                COUNT(*) AS cases,
                ROUND(AVG(checkpoints.return_percent), 4)
                    AS average_return,
                ROUND(AVG(checkpoints.mfe_percent), 4)
                    AS average_mfe,
                ROUND(AVG(checkpoints.mae_percent), 4)
                    AS average_mae
            FROM checkpoints
            INNER JOIN entries
                ON entries.entry_key = checkpoints.entry_key
            GROUP BY
                entries.timeframe,
                entries.direction,
                checkpoints.minutes_after
            ORDER BY
                entries.timeframe,
                entries.direction,
                checkpoints.minutes_after
        """).fetchall()

    return {
        "checkpoint_statistics": [
            dict(row)
            for row in rows
        ]
    }

@app.get("/active-setups")
async def active_setups() -> Dict[str, Any]:
    setups = load_active_setups()

    return {
        "count": len(setups),
        "setups": [
            {
                "symbol": item.symbol,
                "timeframe": item.timeframe,
                "direction": item.direction,
                "breakout_level": item.breakout_level,
                "breakout_price": item.breakout_price,
                "atr": item.atr_value,
                "touched": item.touched,
                "expires_at": item.expires_at,
            }
            for item in setups[:100]
        ],
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
