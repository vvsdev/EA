import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import time
from dotenv import load_dotenv
import os

load_dotenv()

SYMBOLS = ["XAUUSDm", "EURUSDm", "USDJPYm", "EURJPYm", "GBPJPYm"]
lot = 0.01
jumlah_candle = 100
FORCE_ENTRY = False

def connect():
    akun = int(os.getenv('LOGIN'))
    server = os.getenv('SERVER')
    password = os.getenv('PASSWORD')
    path = 'C:/Program Files/MetaTrader 5/terminal64.exe'

    if not mt5.initialize(path=path, login=akun, server=server, password=password):
        print("Gagal login ke MT5")
        return False
    print(f"Login MT5 berhasil ({akun})")
    return True

def hitung_fibonacci_levels(swing_high, swing_low, trend):
    fib_levels = {}
    if swing_high == swing_low:
        return {}
    if trend == 'BUY':
        fib_levels['0.0'] = swing_low
        fib_levels['0.382'] = swing_low + (swing_high - swing_low) * 0.382
        fib_levels['0.5'] = swing_low + (swing_high - swing_low) * 0.5
        fib_levels['0.618'] = swing_low + (swing_high - swing_low) * 0.618
        fib_levels['1.0'] = swing_high
    elif trend == 'SELL':
        fib_levels['0.0'] = swing_high
        fib_levels['0.382'] = swing_high - (swing_high - swing_low) * 0.382
        fib_levels['0.5'] = swing_high - (swing_high - swing_low) * 0.5
        fib_levels['0.618'] = swing_high - (swing_high - swing_low) * 0.618
        fib_levels['1.0'] = swing_low
    return fib_levels

def hitung_atr(df, period=14):
    df = df.copy()
    df['previous_close'] = df['close'].shift(1)
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['previous_close'])
    df['tr3'] = abs(df['low'] - df['previous_close'])
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df['atr'].iloc[-1]

def generate_heikin_ashi(df):
    ha_df = pd.DataFrame(index=df.index)
    ha_df['close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_open = []
    ha_high = []
    ha_low = []
    for i in range(len(df)):
        if i == 0:
            open_val = (df['open'].iloc[i] + df['close'].iloc[i]) / 2
        else:
            open_val = (ha_open[i-1] + ha_df['close'].iloc[i-1]) / 2
        high_val = max(df['high'].iloc[i], open_val, ha_df['close'].iloc[i])
        low_val = min(df['low'].iloc[i], open_val, ha_df['close'].iloc[i])
        ha_open.append(open_val)
        ha_high.append(high_val)
        ha_low.append(low_val)
    ha_df['open'] = ha_open
    ha_df['high'] = ha_high
    ha_df['low'] = ha_low
    return ha_df

def hitung_rsi(df, period=7):
    if 'close' not in df.columns:
        raise ValueError("DataFrame harus memiliki kolom 'close'")
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def detect_heikin_ashi_signal(ha_df):
    if ha_df is None or len(ha_df) < 2:
        return None
    prev_candle = ha_df.iloc[-2]
    curr_candle = ha_df.iloc[-1]
    prev_bullish = prev_candle['close'] > prev_candle['open']
    curr_bullish = curr_candle['close'] > curr_candle['open']
    if not prev_bullish and curr_bullish:
        return "BUY"
    elif prev_bullish and not curr_bullish:
        return "SELL"
    else:
        return None

def kirim_order(symbol, sinyal, price, sl, tp):
    if not mt5.symbol_select(symbol, True):
        print(f"{symbol} | Gagal memilih simbol")
        return

    info = mt5.symbol_info(symbol)
    if not info:
        print(f"{symbol} | Info simbol tidak ditemukan")
        return

    if info.trade_mode not in [mt5.SYMBOL_TRADE_MODE_FULL, mt5.SYMBOL_TRADE_MODE_LONGONLY, mt5.SYMBOL_TRADE_MODE_SHORTONLY]:
        print(f"{symbol} | Simbol tidak tersedia untuk trading (trade_mode: {info.trade_mode})")
        return

    volume = max(info.volume_min, min(lot, info.volume_max))
    volume = round(volume / info.volume_step) * info.volume_step

    stop_level = info.stops_level
    point = info.point

    if stop_level is None or stop_level == 0 or point is None or point == 0:
        print(f"{symbol} | stops_level/point tidak tersedia. Menggunakan default minimal 10 pips.")
        stop_level = 100  # fallback minimal 10 pips
        point = 0.0001 if "JPY" not in symbol else 0.01  # asumsi simbol 5 digit / JPY 3 digit

    min_distance = stop_level * point
    if abs(price - sl) < min_distance or abs(price - tp) < min_distance:
        print(f"{symbol} | SL/TP terlalu dekat. Jarak minimal: {min_distance:.5f}")
        return

    order_type = mt5.ORDER_TYPE_BUY if sinyal == "BUY" else mt5.ORDER_TYPE_SELL
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 123456,
        "comment": "TrendCatcherBot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"{symbol} | Gagal kirim order: {result.retcode} | {result.comment}")
    else:
        print(f"{symbol} | Entry {sinyal} @ {price:.2f} | SL: {sl:.2f} | TP: {tp:.2f}")

def run_bot(symbol):
    rates_m30 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, jumlah_candle)
    if rates_m30 is None or len(rates_m30) == 0:
        print(f"{symbol} | Data M30 kosong")
        return
    df_m30 = pd.DataFrame(rates_m30)
    df_m30['time'] = pd.to_datetime(df_m30['time'], unit='s')
    ha_df = generate_heikin_ashi(df_m30)
    sinyal_ha = detect_heikin_ashi_signal(ha_df)
    ha_valid = sinyal_ha is not None
    candles_m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 50)
    if candles_m15 is None or len(candles_m15) == 0:
        print(f"{symbol} | Data M15 kosong")
        return
    df_m15 = pd.DataFrame(candles_m15)
    df_m15['time'] = pd.to_datetime(df_m15['time'], unit='s')
    rsi_series = hitung_rsi(df_m15)
    latest_rsi = rsi_series.dropna().iloc[-1]
    sinyal_rsi = None
    if latest_rsi < 40:
        sinyal_rsi = "BUY"
    elif latest_rsi > 60:
        sinyal_rsi = "SELL"
    rsi_valid = sinyal_rsi is not None
    fibo_levels = {}
    fibo_valid = False
    sinyal_fibo = None
    harga_sekarang = df_m15['close'].iloc[-1]
    high = df_m15['high'].max()
    low = df_m15['low'].min()
    for direction in ["BUY", "SELL"]:
        fibo = hitung_fibonacci_levels(high, low, direction)
        if "0.5" in fibo and "0.618" in fibo:
            if direction == "BUY" and fibo["0.5"] <= harga_sekarang <= fibo["0.618"]:
                fibo_valid = True
                sinyal_fibo = "BUY"
            elif direction == "SELL" and fibo["0.5"] >= harga_sekarang >= fibo["0.618"]:
                fibo_valid = True
                sinyal_fibo = "SELL"
            if fibo_valid:
                fibo_levels = fibo
                break
    sinyal = sinyal_ha or sinyal_rsi or sinyal_fibo
    if not sinyal and FORCE_ENTRY:
        sinyal = "BUY"
    if not sinyal and not FORCE_ENTRY:
        print(f"{symbol} | Tidak ada sinyal")
        return
    atr = hitung_atr(df_m30)
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print(f"{symbol} | Gagal ambil harga")
        return
    price = tick.ask if sinyal == "BUY" else tick.bid
    sl = price - atr if sinyal == "BUY" else price + atr
    tp = price + atr * 1.5 if sinyal == "BUY" else price - atr * 1.5
    print(f"{symbol} | {datetime.now().strftime('%H:%M:%S')} | Sinyal: {sinyal} | Harga: {price:.2f}")
    if fibo_levels:
        print(f"RSI: {latest_rsi:.2f} | Fibo: {fibo_levels['0.5']:.2f} - {fibo_levels['0.618']:.2f}")
    else:
        print(f"RSI: {latest_rsi:.2f} | Fibo: Tidak valid")
    if ha_valid or rsi_valid or fibo_valid or FORCE_ENTRY:
        kirim_order(symbol, sinyal, price, sl, tp)
    else:
        print(f"{symbol} | Tidak ada konfirmasi valid")

if __name__ == "__main__":
    if not connect():
        exit()
    while True:
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Menjalankan bot...")
        for symbol in SYMBOLS:
            print(f"Mengecek: {symbol}")
            run_bot(symbol)
        print("Menunggu 15 menit...\n")
        time.sleep(900)