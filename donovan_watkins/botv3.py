from datetime import datetime, date, timedelta
import MetaTrader5 as mt5
import pandas as pd
import time
import logging
import numpy as np

# --- CONFIG ---
SYMBOL = 'XAUUSDm'
TIMEFRAME = mt5.TIMEFRAME_M15
TREND_TIMEFRAME = mt5.TIMEFRAME_H1
HIGHER_TF = mt5.TIMEFRAME_H4
WINDOW = 2
CANDLE_COUNT = 100
BASE_LOT = 0.01
DEVIATION = 20
MAGIC = 123456

BE_TRIGGER = 100
BE_OFFSET = 20
TRAIL_START = 150
PARTIAL_TRIGGER = 200
PARTIAL_CLOSE_RATIO = 0.5

ATR_PERIOD = 14
MAX_DRAWDOWN_PERCENT = 5  # Max drawdown per hari (%)
MAX_OPEN_POSITIONS = 3
NOTIFY_EMAIL = 'your@email.com'  # Placeholder, implementasi bisa pakai email/Telegram

LOG_FILE = 'auto_trade_log.txt'

# --- SETUP LOGGING ---
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='%(asctime)s %(levelname)s: %(message)s')

# --- CONNECT TO MT5 ---
def connect():
    if not mt5.initialize():
        logging.error(f'Gagal koneksi MT5: {mt5.last_error()}')
        quit()
    logging.info('Koneksi MT5 berhasil')

def disconnect():
    mt5.shutdown()
    logging.info('Koneksi MT5 ditutup')

# --- NOTIFICATION (Dummy, bisa diganti dengan email/telegram API) ---
def send_notification(message):
    print(f"NOTIFIKASI: {message}")
    # Implementasi bisa menggunakan API email/telegram

# --- GET DATA ---
def get_latest_candle(symbol, timeframe, count):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        logging.warning(f'Gagal ambil data candles {symbol}')
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

# --- INDICATORS ---
def calculate_ema(df, span):
    return df['close'].ewm(span=span, adjust=False).mean()

def detect_trend(df):
    ema50 = calculate_ema(df, 50)
    ema200 = calculate_ema(df, 200)
    if ema50.iloc[-1] > ema200.iloc[-1]:
        return 'bullish'
    else:
        return 'bearish'

def detect_trend_strength(df, threshold=1.0):
    ema50 = calculate_ema(df, 50)
    slope = ema50.iloc[-1] - ema50.iloc[-6]
    return 'strong' if abs(slope) > threshold else 'normal'

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.ewm(com=period-1, min_periods=period).mean()
    return atr

# --- FRACTAL SWING ---
def detect_fractals(df, window=WINDOW, count=3):
    highs = df['high']
    lows = df['low']
    swing_highs = []
    swing_lows = []

    for i in range(window, len(df) - window):
        window_high = highs[i - window:i + window + 1]
        window_low = lows[i - window:i + window + 1]

        if highs[i] == max(window_high):
            swing_highs.append((df['time'][i], highs[i]))
        if lows[i] == min(window_low):
            swing_lows.append((df['time'][i], lows[i]))

    return swing_highs[-count:], swing_lows[-count:]

# --- FIBONACCI LEVEL ---
def calculate_fibonacci_level(swing_high, swing_low, trend):
    if trend == 'bullish':
        fib_100 = swing_low
        fib_0 = swing_high
    else:
        fib_100 = swing_high
        fib_0 = swing_low

    fib_382 = fib_100 + (fib_0 - fib_100) * 0.618
    fib_500 = fib_100 + (fib_0 - fib_100) * 0.5
    fib_618 = fib_100 + (fib_0 - fib_100) * 0.382

    return {
        'fib_0': round(fib_0, 2),
        'fib_382': round(fib_382, 2),
        'fib_500': round(fib_500, 2),
        'fib_618': round(fib_618, 2),
        'fib_100': round(fib_100, 2),
    }

# --- POSITION CHECK ---
def check_open_positions():
    positions = mt5.positions_get(symbol=SYMBOL)
    return positions if positions else []

# --- POSITION SIZING BASED ON ATR ---
def calculate_lot_size(atr, risk_per_trade=0.01, balance=1000):
    if atr == 0:
        return BASE_LOT
    lot = (balance * risk_per_trade) / (atr * 10)
    lot = max(BASE_LOT, round(lot, 2))
    return lot

# --- ENTRY CONFIRMATION ---
def confirm_entry_candle(df, trend, fib_level):
    last_close = df['close'].iloc[-1]
    if trend == 'bullish':
        return last_close > fib_level
    else:
        return last_close < fib_level

# --- ORDER SEND ---
def send_order(order_type, volume, price, sl, tp):
    request = {
        'action': mt5.TRADE_ACTION_DEAL,
        'symbol': SYMBOL,
        'volume': volume,
        'type': order_type,
        'price': price,
        'sl': sl,
        'tp': tp,
        'deviation': DEVIATION,
        'magic': MAGIC,
        'comment': 'Auto entry (RSI/Fibo)',
        'type_time': mt5.ORDER_TIME_GTC,
        'type_filling': mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    return result

# --- DYNAMIC SL/TP BASED ON ATR ---
def dynamic_sl_tp(price, trend, atr, min_distance, digits):
    sl_dist = atr * 1.5
    tp_dist = atr * 2
    if trend == 'bullish':
        sl = max(price - sl_dist, price - min_distance)
        tp = price + tp_dist
    else:
        sl = min(price + sl_dist, price + min_distance)
        tp = price - tp_dist
    return round(sl, digits), round(tp, digits)

# --- AUTO OPEN TRADE ---
def auto_open_trade(trend, fib, strength, rsi_value, df_m15, atr, balance, higher_tf_trend):
    symbol_info = mt5.symbol_info(SYMBOL)
    tick = mt5.symbol_info_tick(SYMBOL)
    if not symbol_info or not tick:
        logging.warning('Symbol info or tick data tidak tersedia')
        return

    digits = symbol_info.digits
    point = symbol_info.point
    ask = round(tick.ask, digits)
    bid = round(tick.bid, digits)
    price = ask if trend == 'bullish' else bid

    # Tambahkan filter multi-timeframe: hanya entry jika trend H1 dan H4 sama
    if trend != higher_tf_trend:
        logging.info(f"Trend H1 dan H4 tidak searah. Entry dibatalkan.")
        return

    entry_level = fib['fib_382'] if strength == 'strong' else fib['fib_618']
    # Konfirmasi candle close di atas/bawah level entry fibonacci
    if not confirm_entry_candle(df_m15, trend, entry_level):
        logging.info(f'Entry candle tidak konfirmasi level Fibonacci. Close terakhir: {df_m15["close"].iloc[-1]}')
        return

    entry_by_fibo = (trend == 'bullish' and price <= entry_level) or (trend == 'bearish' and price >= entry_level)
    entry_by_rsi = (trend == 'bullish' and rsi_value < 30) or (trend == 'bearish' and rsi_value > 70)

    if not (entry_by_fibo or entry_by_rsi):
        logging.info(f'Tidak ada sinyal entry | Price: {price} | RSI: {rsi_value:.2f}')
        return

    order_type = mt5.ORDER_TYPE_BUY if trend == 'bullish' else mt5.ORDER_TYPE_SELL

    lot = calculate_lot_size(atr, risk_per_trade=0.01, balance=balance)
    lot = min(lot, symbol_info.volume_max)
    lot = max(lot, symbol_info.volume_min)

    stop_level = symbol_info.trade_stops_level
    min_distance = stop_level * point

    # Dynamic SL/TP berdasarkan ATR
    sl, tp = dynamic_sl_tp(price, trend, atr, min_distance, digits)

    if abs(price - sl) < min_distance or abs(tp - price) < min_distance:
        logging.info(f"SL/TP tidak memenuhi syarat minimum. SL: {sl}, TP: {tp}, Min: {min_distance}")
        return

    logging.info(f"[ENTRY] {'RSI' if entry_by_rsi else 'Fibo'} | Trend: {trend.upper()} | Price: {price} | RSI: {rsi_value:.2f} | Lot: {lot}")
    logging.info(f" SL: {sl} | TP: {tp} | Min Stop (point): {stop_level} ({min_distance})")

    result = send_order(order_type, lot, price, sl, tp)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logging.error(f"Gagal open order: {result.retcode} | Detail: {result.comment}")
        send_notification(f"Gagal open order: {result.retcode} | {result.comment}")
    else:
        logging.info(f"Order berhasil: {'BUY' if order_type == mt5.ORDER_TYPE_BUY else 'SELL'} @ {price}")
        send_notification(f"Order berhasil: {'BUY' if order_type == mt5.ORDER_TYPE_BUY else 'SELL'} @ {price}")

# --- MANAGE POSITIONS ---
def manage_positions():
    positions = check_open_positions()
    if not positions:
        return

    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    point = info.point
    digits = info.digits

    for pos in positions:
        price_open = pos.price_open
        volume = pos.volume
        ticket = pos.ticket
        sl = pos.sl
        pos_type = pos.type

        if pos_type == mt5.ORDER_TYPE_BUY:
            profit_point = (tick.bid - price_open) / point
            be_price = round(price_open + BE_OFFSET * point, digits)
            trail_price = round(tick.bid - TRAIL_START * point, digits)
        else:
            profit_point = (price_open - tick.ask) / point
            be_price = round(price_open - BE_OFFSET * point, digits)
            trail_price = round(tick.ask + TRAIL_START * point, digits)

        # Partial close jika profit sudah cukup dan volume cukup
        if profit_point > PARTIAL_TRIGGER and volume >= BASE_LOT * 2:
            close_partial_position(ticket, volume * PARTIAL_CLOSE_RATIO)

        # Set break-even stop loss
        if profit_point > BE_TRIGGER and (sl == 0 or (pos_type == mt5.ORDER_TYPE_BUY and sl < be_price) or (pos_type == mt5.ORDER_TYPE_SELL and sl > be_price)):
            modify_sl(ticket, be_price)

        # Trailing stop dinamis berdasarkan ATR
        atr = calculate_atr(get_latest_candle(SYMBOL, TIMEFRAME, CANDLE_COUNT), ATR_PERIOD).iloc[-1]
        if profit_point > TRAIL_START:
            if pos_type == mt5.ORDER_TYPE_BUY:
                trail_sl = round(tick.bid - atr, digits)
            else:
                trail_sl = round(tick.ask + atr, digits)
            modify_sl(ticket, trail_sl)

# --- MODIFY SL ---
def modify_sl(ticket, new_sl):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        logging.warning(f'Posisi dengan ticket {ticket} tidak ditemukan saat modify SL')
        return
    pos = pos[0]
    result = mt5.order_send({
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl": new_sl,
        "tp": pos.tp,
        "symbol": pos.symbol,
        "magic": pos.magic,
        "comment": "Modify SL",
    })
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logging.info(f"SL berhasil diubah ke {new_sl}")
    else:
        logging.error(f"Gagal modify SL: {result.retcode} | {result.comment}")
        send_notification(f"Gagal modify SL: {result.retcode} | {result.comment}")

# --- PARTIAL CLOSE ---
def close_partial_position(ticket, volume_to_close):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        logging.warning(f'Posisi dengan ticket {ticket} tidak ditemukan saat partial close')
        return
    pos = pos[0]
    tick = mt5.symbol_info_tick(pos.symbol)
    price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": round(volume_to_close, 2),
        "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "position": ticket,
        "price": price,
        "deviation": DEVIATION,
        "magic": MAGIC,
        "comment": "Partial Close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logging.info(f"Partial close berhasil: {round(volume_to_close, 2)}")
        send_notification(f"Partial close berhasil: {round(volume_to_close, 2)}")
    else:
        logging.error(f"Gagal partial close: {result.retcode} | {result.comment}")
        send_notification(f"Gagal partial close: {result.retcode} | {result.comment}")

# --- DAILY DRAWDOWN CHECK ---
def get_daily_drawdown():
    today = datetime.combine(date.today(), datetime.min.time())
    now = datetime.now()
    history = mt5.history_deals_get(today, now)
    if not history:
        return 0
    pnl_today = sum([deal.profit for deal in history if deal.symbol == SYMBOL])
    balance = mt5.account_info().balance if mt5.account_info() else 1000
    drawdown_percent = abs(pnl_today) / balance * 100
    return drawdown_percent

# --- MAIN LOOP ---
def main_loop():
    connect()
    balance = mt5.account_info().balance if mt5.account_info() else 1000
    logging.info(f'Balance akun: {balance}')
    while True:
        try:
            # --- Risk Management: Cek drawdown harian ---
            drawdown = get_daily_drawdown()
            if drawdown > MAX_DRAWDOWN_PERCENT:
                logging.warning(f"Max drawdown harian tercapai: {drawdown:.2f}%")
                send_notification(f"Trading dihentikan, drawdown harian: {drawdown:.2f}%")
                time.sleep(3600)  # Pause 1 jam
                continue

            # --- Get Trend Multi-Timeframe ---
            df_trend = get_latest_candle(SYMBOL, TREND_TIMEFRAME, 200)
            df_higher = get_latest_candle(SYMBOL, HIGHER_TF, 200)
            if df_trend is None or df_higher is None:
                time.sleep(60)
                continue

            trend = detect_trend(df_trend)
            strength = detect_trend_strength(df_trend)
            higher_tf_trend = detect_trend(df_higher)

            df_m15 = get_latest_candle(SYMBOL, TIMEFRAME, CANDLE_COUNT)
            if df_m15 is None:
                time.sleep(60)
                continue

            rsi_series = calculate_rsi(df_m15)
            rsi_value = rsi_series.iloc[-1]

            atr_series = calculate_atr(df_m15, ATR_PERIOD)
            atr = atr_series.iloc[-1]

            swing_highs, swing_lows = detect_fractals(df_m15)
            if not swing_highs or not swing_lows:
                logging.info("Swing tidak ditemukan")
                time.sleep(60)
                continue

            sh_time, sh_price = swing_highs[-1]
            sl_time, sl_price = swing_lows[-1]
            fibo = calculate_fibonacci_level(sh_price, sl_price, trend)

            logging.info(f"\nTrend: {trend.upper()} | Strength: {strength.upper()} | RSI: {rsi_value:.2f} | H4 Trend: {higher_tf_trend.upper()}")
            logging.info(f"Swing High: {sh_price} | Swing Low: {sl_price}")
            logging.info(f"TP: {fibo['fib_0']} | SL: {fibo['fib_100']}")
            logging.info(f"ENTRY LEVEL: {fibo['fib_382'] if strength == 'strong' else fibo['fib_618']}")

            positions = check_open_positions()
            if len(positions) < MAX_OPEN_POSITIONS:
                auto_open_trade(trend, fibo, strength, rsi_value, df_m15, atr, balance, higher_tf_trend)
            else:
                manage_positions()

        except Exception as e:
            logging.error(f"Error: {e}")
            send_notification(f"Error: {e}")

        time.sleep(60)

if __name__ == '__main__':
    main_loop()
