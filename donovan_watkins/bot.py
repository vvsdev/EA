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
DEVIATION = 10
MAGIC = 123456

def connect():
    if not mt5.initialize():
        print(f'Gagal terkoneksi ke MT5: {mt5.last_error()}')
        quit()
    print('Berhasil terkoneksi ke MT5')

def disconnect():
    mt5.shutdown()
    print('Koneksi MT5 berhasil diputus')

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
        window_high = highs[i-WINDOW:i+WINDOW+1]
        window_low = lows[i-WINDOW:i+WINDOW+1]

        if highs[i] == max(window_high):
            swing_high.append((df['time'][i], highs[i]))
        if lows[i] == min(window_low):
            swing_low.append((df['time'][i], lows[i]))

    return swing_high[-1:] if swing_high else None, swing_low[-1:] if swing_low else None

# function to detect the trend
def detect_trend(df):
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['ema200'] = df['close'].ewm(span=200).mean()
    
    if df['ema50'].iloc[-1] > df['ema200'].iloc[-1]:
        return 'bullish'
    else:
        return 'bearish'

# function to detect trend strength
def detect_trend_strength(df, threshold=1.0):
    df['ema50'] = df['close'].ewm(span=50).mean()
    slope = df['ema50'].iloc[-1] - df['ema50'].iloc[-6]
    return 'strong' if abs(slope) > threshold else 'normal'

# function to calculate fibo level
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

def auto_open_trade(trend, fib, strength):
    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.ask if trend == 'bullish' else tick.bid

    entry_level = fib['fib_382'] if strength == 'strong' else fib['fib_618']
    sl = fib['fib_100']
    tp = fib['fib_0']

    if trend == 'bullish' and price <= entry_level:
        order_type = mt5.ORDER_TYPE_BUY
    elif trend == 'bearish' and price >= entry_level:
        order_type = mt5.ORDER_TYPE_SELL
    else:
        print(f"Harga {price} belum menyentuh level entry ({entry_level})")
        return

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
        'comment': 'Auto fibonacci entry',
        'type_name': mt5.ORDER_TIME_GTC,
        'type_filling': mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f'Gagal open order: {result.retcode}')
    else:
        print(f"Order {['SELL', 'BUY'][order_type==mt5.ORDER_TYPE_BUY]} berhasil: {price} | Strength: {strength}")

def check_open_positions():
    positions = mt5.positions_get(symbol=SYMBOL)
    return len(positions) > 0

# main function
def main_loop():
    connect()
    while True:
        try:
            # get major trend
            df_trend = get_latest_candle(SYMBOL, TREND_TIMEFRAME, 200)
            trend = detect_trend(df_trend)
            strength = detect_trend_strength(df_trend)
            
            # get swing
            df_m15 = get_latest_candle(SYMBOL, TIMEFRAME, CANDLE_COUNT)
            sh, sl = detect_fractal(df_m15)

            # fibo position
            if trend == 'bullish' and sh and sl:
                fibo = calculate_fibonacci_level(sh[0][1], sl[0][1], trend)
            elif trend == 'bearish' and sh and sl:
                fibo = calculate_fibonacci_level(sh[0][1], sl[0][1], trend)
            else:
                print(f'Swing atau trend tidak valid')
                time.sleep(60)
                continue

            print(f'\nTrend: {trend.upper()} | Strength: {strength.upper()}')
            print(f'Swing high: {sh[0][1]} | Swing low: {sl[0][1]}')
            print(f"TP: {fibo['fib_0']} | SL: {fibo['fib_100']}")
            print(f"ENTRY: {fibo['fib_618'] if  strength == 'normal' else fibo['fib_382']}\n")

            if not check_open_positions():
                auto_open_trade(trend, fibo, strength)
            else:
                print('Sudah ada open posisi')

        except Exception as e:
            print(f'Terjadi kesalahan: {e}')
        time.sleep(60)
    # disconnect()

if __name__ == '__main__':
    main_loop()