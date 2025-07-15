from datetime import datetime
import MetaTrader5 as mt5
import pandas as pd
import time

# ===== Konstanta utama =====
SYMBOL = 'XAUUSDm'
TIMEFRAME = mt5.TIMEFRAME_M15
TREND_TIMEFRAME = mt5.TIMEFRAME_H1
WINDOW = 2
CANDLE_COUNT = 100
LOT = 0.01
DEVIATION = 20
MAGIC = 123456

# ===== Koneksi =====
def connect():
    if not mt5.initialize():
        print(f'❌ Gagal terkoneksi ke MT5: {mt5.last_error()}')
        quit()
    print('✅ Berhasil terkoneksi ke MT5')

def disconnect():
    mt5.shutdown()
    print('🔌 Koneksi MT5 diputus')

# ===== Ambil candle data =====
def get_latest_candle(symbol, timeframe, count):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

# ===== Deteksi swing high/low pakai fractal =====
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

# ===== Deteksi trend utama pakai EMA 50 & EMA 200 =====
def detect_trend(df):
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['ema200'] = df['close'].ewm(span=200).mean()
    return 'bullish' if df['ema50'].iloc[-1] > df['ema200'].iloc[-1] else 'bearish'

# ===== Deteksi kekuatan trend pakai slope EMA50 =====
def detect_trend_strength(df, threshold=1.0):
    df['ema50'] = df['close'].ewm(span=50).mean()
    slope = df['ema50'].iloc[-1] - df['ema50'].iloc[-6]
    return 'strong' if abs(slope) > threshold else 'normal'

# ===== Hitung RSI =====
def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi

# ===== Hitung Fibonacci Level dari swing =====
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

# ===== Cek open posisi =====
def check_open_positions():
    positions = mt5.positions_get(symbol=SYMBOL)
    return len(positions) > 0

# ===== Eksekusi order =====
def auto_open_trade(trend, fib, strength, rsi_value):
    symbol_info = mt5.symbol_info(SYMBOL)
    if symbol_info is None:
        print("❌ Symbol info tidak ditemukan.")
        return

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print("❌ Gagal ambil harga tick.")
        return

    digits = symbol_info.digits
    ask = round(tick.ask, digits)
    bid = round(tick.bid, digits)
    price = ask if trend == 'bullish' else bid

    entry_level = fib['fib_382'] if strength == 'strong' else fib['fib_618']
    sl = fib['fib_100']
    tp = fib['fib_0']

    # Konfirmasi dari Fibo dan RSI
    entry_by_fibo = (trend == 'bullish' and price <= entry_level) or (trend == 'bearish' and price >= entry_level)
    entry_by_rsi = (trend == 'bullish' and rsi_value < 30) or (trend == 'bearish' and rsi_value > 70)

    if not (entry_by_fibo or entry_by_rsi):
        print(f"⏳ Belum ada sinyal entry dari Fibo atau RSI | Harga: {price} | RSI: {rsi_value:.2f}")
        return

    min_stop = symbol_info.trade_stops_level / (10 ** digits)
    if trend == 'bullish':
        if price - sl < min_stop:
            sl = price - min_stop
        if tp - price < min_stop:
            tp = price + min_stop
        order_type = mt5.ORDER_TYPE_BUY
    else:
        if sl - price < min_stop:
            sl = price + min_stop
        if price - tp < min_stop:
            tp = price - min_stop
        order_type = mt5.ORDER_TYPE_SELL

    sl = round(sl, digits)
    tp = round(tp, digits)
    price = round(price, digits)

    print(f"[ENTRY ✅] Reason: {'RSI' if entry_by_rsi else 'Fibo'} | Trend: {trend.upper()} | Price: {price} | RSI: {rsi_value:.2f}")

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
        print(f"❌ Gagal open order: {result.retcode} | Detail: {result.comment}")
    else:
        print(f"✅ Order {'BUY' if order_type == mt5.ORDER_TYPE_BUY else 'SELL'} berhasil @ {price}")

# ===== Main loop =====
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
                print("❌ Swing high/low tidak ditemukan")
                time.sleep(60)
                continue

            print(f"\n🧠 Trend: {trend.upper()} | Strength: {strength.upper()} | RSI: {rsi_value:.2f}")
            print(f"Swing High: {sh[0][1]} | Swing Low: {sl[0][1]}")
            print(f"TP: {fibo['fib_0']} | SL: {fibo['fib_100']}")
            print(f"ENTRY: {fibo['fib_382'] if strength == 'strong' else fibo['fib_618']}\n")

            if not check_open_positions():
                auto_open_trade(trend, fibo, strength, rsi_value)
            else:
                print("⚠️ Masih ada posisi terbuka")

        except Exception as e:
            print(f"🚨 Terjadi kesalahan: {e}")
        time.sleep(60)

# ===== Run =====
if __name__ == '__main__':
    main_loop()
