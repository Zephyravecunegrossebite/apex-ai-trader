import os
import time
import logging
import requests
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIGURATION ───────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RR_RATIO = float(os.getenv("RR_RATIO", "2.0"))
RISK_PCT = float(os.getenv("RISK_PCT", "2.0"))
TIMEFRAME = os.getenv("TIMEFRAME", "60")          # minutes
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "300"))  # secondes entre chaque scan
LANG = os.getenv("LANG", "fr")

# Paires à surveiller
PAIRS = {
    "XAUUSD": {"name": "XAU/USD", "type": "OR",     "atr_pct": 0.004},
    "EURUSD": {"name": "EUR/USD", "type": "FOREX",  "atr_pct": 0.0008},
    "BTCUSD": {"name": "BTC/USD", "type": "CRYPTO", "atr_pct": 0.012},
}

# ─── LOGGING ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("ApexTrader")

# ─── ÉTAT ────────────────────────────────────────────────────
last_signals = {pair: None for pair in PAIRS}
signal_count = 0


# ═══════════════════════════════════════════════════════════════
#  RÉCUPÉRATION DES PRIX (Twelve Data — gratuit 8 calls/min)
# ═══════════════════════════════════════════════════════════════
def get_price_data(symbol: str, interval: str = "1h", outputsize: int = 50) -> list[float] | None:
    """
    Récupère les prix de clôture via Twelve Data (gratuit).
    Retourne une liste de prix de clôture ou None si erreur.
    """
    API_KEY = os.getenv("TWELVE_DATA_KEY", "demo")
    
    # Adapter le symbole pour Twelve Data
    td_symbol = symbol.replace("BTCUSD", "BTC/USD").replace("XAUUSD", "XAU/USD").replace("EURUSD", "EUR/USD")
    interval_map = {"15": "15min", "30": "30min", "60": "1h", "240": "4h", "1440": "1day"}
    td_interval = interval_map.get(TIMEFRAME, "1h")

    try:
        url = (
            f"https://api.twelvedata.com/time_series"
            f"?symbol={td_symbol}&interval={td_interval}"
            f"&outputsize={outputsize}&apikey={API_KEY}"
        )
        r = requests.get(url, timeout=10)
        data = r.json()

        if data.get("status") == "error" or "values" not in data:
            log.warning(f"{symbol}: Erreur API Twelve Data → {data.get('message', 'inconnue')}")
            return None

        closes = [float(v["close"]) for v in reversed(data["values"])]
        return closes

    except Exception as e:
        log.error(f"{symbol}: Impossible de récupérer les prix → {e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  INDICATEURS TECHNIQUES
# ═══════════════════════════════════════════════════════════════
def ema(prices: list[float], period: int) -> float:
    arr = np.array(prices)
    k = 2 / (period + 1)
    ema_val = arr[0]
    for p in arr[1:]:
        ema_val = p * k + ema_val * (1 - k)
    return ema_val


def rsi(prices: list[float], period: int = 14) -> float:
    deltas = np.diff(prices[-period - 1:])
    gains = deltas[deltas > 0].mean() if len(deltas[deltas > 0]) > 0 else 0
    losses = -deltas[deltas < 0].mean() if len(deltas[deltas < 0]) > 0 else 0
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))


def macd(prices: list[float]) -> tuple[float, float]:
    """Retourne (macd_line, signal_line)"""
    ema12 = ema(prices, 12)
    ema26 = ema(prices, 26)
    macd_line = ema12 - ema26
    # Signal = EMA 9 du MACD (simplifié)
    signal_line = ema(prices[-9:], 9) * 0.1
    return macd_line, signal_line


def atr(prices: list[float], period: int = 14) -> float:
    highs = np.array(prices[-period:]) * 1.002
    lows = np.array(prices[-period:]) * 0.998
    closes = np.array(prices[-period:])
    tr = np.maximum(highs - lows, np.abs(highs - np.roll(closes, 1)))
    return tr[1:].mean()


def bollinger_bands(prices: list[float], period: int = 20) -> tuple[float, float, float]:
    arr = np.array(prices[-period:])
    mid = arr.mean()
    std = arr.std()
    return mid + 2 * std, mid, mid - 2 * std


# ═══════════════════════════════════════════════════════════════
#  CALCUL DES NIVEAUX SL / TP
# ═══════════════════════════════════════════════════════════════
def compute_levels(symbol: str, direction: str, price: float, atr_val: float) -> dict:
    sl_dist = atr_val * 1.5
    tp1_dist = sl_dist * RR_RATIO
    tp2_dist = sl_dist * RR_RATIO * 1.5

    decimals = 5 if symbol == "EURUSD" else 2

    if direction == "BUY":
        return {
            "entry": round(price, decimals),
            "sl":    round(price - sl_dist, decimals),
            "tp1":   round(price + tp1_dist, decimals),
            "tp2":   round(price + tp2_dist, decimals),
            "ratio": f"1:{RR_RATIO:.1f}",
        }
    else:
        return {
            "entry": round(price, decimals),
            "sl":    round(price + sl_dist, decimals),
            "tp1":   round(price - tp1_dist, decimals),
            "tp2":   round(price - tp2_dist, decimals),
            "ratio": f"1:{RR_RATIO:.1f}",
        }


# ═══════════════════════════════════════════════════════════════
#  LOGIQUE DE SIGNAL
# ═══════════════════════════════════════════════════════════════
def analyze(symbol: str, prices: list[float]) -> str | None:
    """
    Retourne 'BUY', 'SELL', 'CLOSE' ou None.
    Conditions :
      BUY  → RSI < 40  + MACD haussier + EMA20 > EMA50
      SELL → RSI > 60  + MACD baissier + EMA20 < EMA50
      CLOSE→ position ouverte + signal inversé
    """
    if len(prices) < 50:
        log.warning(f"{symbol}: Pas assez de données ({len(prices)} bougies)")
        return None

    rsi_val = rsi(prices)
    macd_line, signal_line = macd(prices)
    ema20 = ema(prices, 20)
    ema50 = ema(prices, 50)
    bb_upper, bb_mid, bb_lower = bollinger_bands(prices)
    current_price = prices[-1]

    log.info(
        f"{symbol} | Prix: {current_price:.5f} | RSI: {rsi_val:.1f} | "
        f"MACD: {macd_line:.5f} | EMA20: {ema20:.5f} | EMA50: {ema50:.5f}"
    )

    macd_bull = macd_line > signal_line
    trend_bull = ema20 > ema50
    near_lower_bb = current_price <= bb_lower * 1.002
    near_upper_bb = current_price >= bb_upper * 0.998

    # Signal ACHAT
    if rsi_val < 40 and macd_bull and trend_bull and near_lower_bb:
        return "BUY"

    # Signal VENTE
    if rsi_val > 60 and not macd_bull and not trend_bull and near_upper_bb:
        return "SELL"

    # Fermeture si signal inversé
    prev = last_signals.get(symbol)
    if prev == "BUY" and rsi_val > 60 and not macd_bull:
        return "CLOSE"
    if prev == "SELL" and rsi_val < 40 and macd_bull:
        return "CLOSE"

    return None


# ═══════════════════════════════════════════════════════════════
#  TELEGRAM
# ═══════════════════════════════════════════════════════════════
def build_message(symbol: str, direction: str, levels: dict, rsi_val: float, macd_line: float) -> str:
    pair_info = PAIRS[symbol]
    tf_label = {"15": "15 MIN", "30": "30 MIN", "60": "1H", "240": "4H", "1440": "D1"}.get(TIMEFRAME, "1H")
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    icons = {"BUY": "🟢", "SELL": "🔴", "CLOSE": "🔵"}
    dir_fr = {"BUY": "ACHAT", "SELL": "VENTE", "CLOSE": "FERMER POSITION"}
    dir_en = {"BUY": "BUY", "SELL": "SELL", "CLOSE": "CLOSE POSITION"}

    if LANG == "fr":
        return (
            f"{icons[direction]} <b>SIGNAL {dir_fr[direction]} — {pair_info['name']}</b>\n\n"
            f"📊 <b>Paire :</b> {symbol}\n"
            f"⏱ <b>Timeframe :</b> {tf_label}\n"
            f"💰 <b>Prix entrée :</b> {levels['entry']}\n"
            f"🛑 <b>Stop Loss :</b> {levels['sl']}\n"
            f"🎯 <b>Take Profit 1 :</b> {levels['tp1']}\n"
            f"🎯 <b>Take Profit 2 :</b> {levels['tp2']}\n"
            f"📐 <b>Ratio R:R :</b> {levels['ratio']}\n\n"
            f"📈 <b>Indicateurs :</b>\n"
            f"• RSI : {rsi_val:.1f}\n"
            f"• MACD : {'haussier ↑' if macd_line > 0 else 'baissier ↓'}\n"
            f"• EMA : tendance {'haussière' if direction == 'BUY' else 'baissière'}\n\n"
            f"⚠️ <i>Gérez votre risque. Max {RISK_PCT}% du capital par trade.</i>\n\n"
            f"🤖 <i>APEX AI Trader • {now}</i>"
        )
    else:
        return (
            f"{icons[direction]} <b>{dir_en[direction]} SIGNAL — {pair_info['name']}</b>\n\n"
            f"📊 <b>Pair:</b> {symbol}\n"
            f"⏱ <b>Timeframe:</b> {tf_label}\n"
            f"💰 <b>Entry:</b> {levels['entry']}\n"
            f"🛑 <b>Stop Loss:</b> {levels['sl']}\n"
            f"🎯 <b>Take Profit 1:</b> {levels['tp1']}\n"
            f"🎯 <b>Take Profit 2:</b> {levels['tp2']}\n"
            f"📐 <b>R:R Ratio:</b> {levels['ratio']}\n\n"
            f"📈 <b>Indicators:</b>\n"
            f"• RSI: {rsi_val:.1f}\n"
            f"• MACD: {'bullish ↑' if macd_line > 0 else 'bearish ↓'}\n"
            f"• EMA: {'bullish' if direction == 'BUY' else 'bearish'} trend\n\n"
            f"⚠️ <i>Manage your risk. Max {RISK_PCT}% per trade.</i>\n\n"
            f"🤖 <i>APEX AI Trader • {now}</i>"
        )


def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Token ou Chat ID Telegram manquant !")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        data = r.json()
        if data.get("ok"):
            log.info("✅ Alerte Telegram envoyée")
            return True
        else:
            log.error(f"❌ Telegram error: {data.get('description')}")
            return False
    except Exception as e:
        log.error(f"❌ Erreur réseau Telegram: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  BOUCLE PRINCIPALE
# ═══════════════════════════════════════════════════════════════
def run():
    global signal_count, last_signals

    log.info("🚀 APEX AI Trader démarré — surveillance 24/7")
    log.info(f"📊 Paires : {', '.join(PAIRS.keys())}")
    log.info(f"🎯 Ratio R:R minimum : 1:{RR_RATIO}")
    log.info(f"⏱ Scan toutes les {SCAN_INTERVAL} secondes")

    # Message de démarrage Telegram
    send_telegram(
        "🚀 <b>APEX AI Trader — DÉMARRÉ</b>\n\n"
        f"📊 Paires : {', '.join(PAIRS.keys())}\n"
        f"🎯 R:R minimum : 1:{RR_RATIO}\n"
        f"⏱ Scan : toutes les {SCAN_INTERVAL}s\n\n"
        f"<i>Surveillance active 24h/7j — {datetime.now().strftime('%d/%m/%Y %H:%M')}</i>"
    )

    while True:
        log.info(f"── Scan #{signal_count + 1} ─────────────────────────")

        for symbol in PAIRS:
            try:
                prices = get_price_data(symbol)
                if prices is None:
                    continue

                direction = analyze(symbol, prices)

                if direction is None:
                    log.info(f"{symbol}: Pas de signal — en attente")
                    continue

                # Éviter de répéter le même signal
                if direction == last_signals[symbol] and direction != "CLOSE":
                    log.info(f"{symbol}: Signal {direction} déjà envoyé, skip")
                    continue

                price = prices[-1]
                atr_val = atr(prices)
                levels = compute_levels(symbol, direction, price, atr_val)
                rsi_val = rsi(prices)
                macd_line, _ = macd(prices)

                msg = build_message(symbol, direction, levels, rsi_val, macd_line)
                sent = send_telegram(msg)

                if sent:
                    last_signals[symbol] = direction if direction != "CLOSE" else None
                    signal_count += 1
                    log.info(f"📤 Signal {direction} envoyé pour {symbol}")

                # Pause entre paires (éviter rate limit API)
                time.sleep(15)

            except Exception as e:
                log.error(f"Erreur sur {symbol}: {e}")

        log.info(f"✅ Scan terminé — prochain dans {SCAN_INTERVAL}s")
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run()
