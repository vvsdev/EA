from datetime import datetime
import MetaTrader5 as mt5
import pandas as pd
import time

SYMBOL = 'XAUUSDm'
TIMEFRAME = mt5.TIMEFRAME_M15
TREND_TIMEFRAME = mt5.TIMEFRAME_H1
WINDOW = 2
CANDLE_COUNT = 100
LOT = 0.01
DEVIATION = 20
MAGIC = 123456

BE_TRIGGER = 100
BE_OFFSET = 20
TRAIL_START = 150
TRAIL_STEP = 50
PARTIAL_TRIGGER = 200
PARTIAL_CLOSE_RATIO = 0.5

def connect():
    if not mt5.initialize():
        print(f'Gagal koneksi MT5: {mt5.last_error()}')
        quit()
    print('Koneksi MT5 berhasil')

def disconnect():
    mt5.shutdown()
    print('Koneksi MT5 ditutup')

def get_latest_candle(symbol, timeframe, count):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def detect_fractal(df):
    highs = df['high']
    lows = df['low']
    swing_high = []
    swing_low = []

    for i in range(WINDOW, len(df) - WINDOW):
        window_high = highs[i - WINDOW:i + WINDOW + 1]
        window_low = lows[i - WINDOW:i + WINDOW + 1]

        if highs[i] == max(window_high):
            swing_high.append((df['time'][i], highs[i]))
        if lows[i] == min(window_low):
            swing_low.append((df['time'][i], lows[i]))

    return swing_high[-1:] if swing_high else None, swing_low[-1:] if swing_low else None

def detect_trend(df):
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['ema200'] = df['close'].ewm(span=200).mean()
    return 'bullish' if df['ema50'].iloc[-1] > df['ema200'].iloc[-1] else 'bearish'

def detect_trend_strength(df, threshold=1.0):
    df['ema50'] = df['close'].ewm(span=50).mean()
    slope = df['ema50'].iloc[-1] - df['ema50'].iloc[-6]
    return 'strong' if abs(slope) > threshold else 'normal'

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_fibonacci_level(swing_high, swing_low, trend):
    if trend == 'bullish':
        fib_100 = swing_low
        fib_0 = swing_high
    else:
        fib_100 = swing_high
        fib_0 = swing_low

    fib_382 = fib_100 + (fib_0 - fib_100) * 0.618
    fib_500 = fib_100 + (fib_0 - fib_100) * 0.500
    fib_618 = fib_100 + (fib_0 - fib_100) * 0.382

    return {
        'fib_0': round(fib_0, 2),
        'fib_382': round(fib_382, 2),
        'fib_500': round(fib_500, 2),
        'fib_618': round(fib_618, 2),
        'fib_100': round(fib_100, 2),
    }

def check_open_positions():
    positions = mt5.positions_get(symbol=SYMBOL)
    return len(positions) > 0

def auto_open_trade(trend, fib, strength, rsi_value):
    symbol_info = mt5.symbol_info(SYMBOL)
    tick = mt5.symbol_info_tick(SYMBOL)
    if not symbol_info or not tick:
        return

    digits = symbol_info.digits
    point = symbol_info.point
    ask = round(tick.ask, digits)
    bid = round(tick.bid, digits)
    price = ask if trend == 'bullish' else bid

    entry_level = fib['fib_382'] if strength == 'strong' else fib['fib_618']
    sl = fib['fib_100']
    tp = fib['fib_0']

    entry_by_fibo = (trend == 'bullish' and price <= entry_level) or (trend == 'bearish' and price >= entry_level)
    entry_by_rsi = (trend == 'bullish' and rsi_value < 30) or (trend == 'bearish' and rsi_value > 70)

    if not (entry_by_fibo or entry_by_rsi):
        print(f"Tidak ada sinyal entry | Price: {price} | RSI: {rsi_value:.2f}")
        return

    order_type = mt5.ORDER_TYPE_BUY if trend == 'bullish' else mt5.ORDER_TYPE_SELL

    stop_level = symbol_info.trade_stops_level
    min_distance = stop_level * point

    if trend == 'bullish':
        sl = min(sl, price - min_distance)
        tp = max(tp, price + min_distance)
    else:
        sl = max(sl, price + min_distance)
        tp = min(tp, price - min_distance)

    if abs(price - sl) < min_distance or abs(tp - price) < min_distance:
        print(f"SL/TP tidak memenuhi syarat minimum. SL: {sl}, TP: {tp}, Min: {min_distance}")
        return

    sl = round(sl, digits)
    tp = round(tp, digits)
    price = round(price, digits)

    print(f"[ENTRY] {'RSI' if entry_by_rsi else 'Fibo'} | Trend: {trend.upper()} | Price: {price} | RSI: {rsi_value:.2f}")
    print(f" SL: {sl} | TP: {tp} | Min Stop (point): {stop_level} ({min_distance})")

    request = {
        'action': mt5.TRADE_ACTION_DEAL,
        'symbol': SYMBOL,
        'volume': LOT,
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
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Gagal open order: {result.retcode} | Detail: {result.comment}")
    else:
        print(f"Order berhasil: {'BUY' if order_type == mt5.ORDER_TYPE_BUY else 'SELL'} @ {price}")

def manage_positions():
    positions = mt5.positions_get(symbol=SYMBOL)
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
            trail_price = round(tick.bid - TRAIL_STEP * point, digits)
        else:
            profit_point = (price_open - tick.ask) / point
            be_price = round(price_open - BE_OFFSET * point, digits)
            trail_price = round(tick.ask + TRAIL_STEP * point, digits)

        if profit_point > PARTIAL_TRIGGER and volume >= LOT * 2:
            close_partial_position(ticket, volume * PARTIAL_CLOSE_RATIO)

        if profit_point > BE_TRIGGER:
            modify_sl(ticket, be_price)

        if profit_point > TRAIL_START:
            modify_sl(ticket, trail_price)

def modify_sl(ticket, new_sl):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
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
        print(f"SL berhasil diubah ke {new_sl}")
    else:
        print(f"Gagal modify SL: {result.retcode} | {result.comment}")

def close_partial_position(ticket, volume_to_close):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
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
        print(f"Partial close berhasil: {round(volume_to_close, 2)}")
    else:
        print(f"Gagal partial close: {result.retcode} | {result.comment}")

def main_loop():
    connect()
    while True:
        try:
            df_trend = get_latest_candle(SYMBOL, TREND_TIMEFRAME, 200)
            trend = detect_trend(df_trend)
            strength = detect_trend_strength(df_trend)

            df_m15 = get_latest_candle(SYMBOL, TIMEFRAME, CANDLE_COUNT)
            rsi_series = calculate_rsi(df_m15)
            rsi_value = rsi_series.iloc[-1]

            sh, sl = detect_fractal(df_m15)
            if sh and sl:
                fibo = calculate_fibonacci_level(sh[0][1], sl[0][1], trend)
            else:
                print("Swing tidak ditemukan")
                time.sleep(60)
                continue

            print(f"\nTrend: {trend.upper()} | Strength: {strength.upper()} | RSI: {rsi_value:.2f}")
            print(f"Swing High: {sh[0][1]} | Swing Low: {sl[0][1]}")
            print(f"TP: {fibo['fib_0']} | SL: {fibo['fib_100']}")
            print(f"ENTRY LEVEL: {fibo['fib_382'] if strength == 'strong' else fibo['fib_618']}\n")

            if not check_open_positions():
                auto_open_trade(trend, fibo, strength, rsi_value)
            else:
                manage_positions()

        except Exception as e:
            print(f"Error: {e}")
        time.sleep(60)

if __name__ == '__main__':
    main_loop()