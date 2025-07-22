import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator

# Config
SYMBOL = 'XAUUSDm'
LOT = 0.01
MAGIC = 123456
TP_RUPIAH = 5000
USD_IDR_RATE = 16000
RSI_PERIOD = 14
TIMEFRAME = mt5.TIMEFRAME_M1
ENTRY_INTERVAL_MINUTES = 5

# Connect
def init_mt5():
    if not mt5.initialize():
        print("Gagal terkoneksi ke MT5")
        quit()
    if not mt5.symbol_select(SYMBOL, True):
        print(f"Gagal menemukan symbol {SYMBOL}")
        quit()
    print("Berhasil terkoneksi ke MT5")

# RSI
def get_rsi(symbol, timeframe, period):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 50)
    if rates is None:
        return None
    df = pd.DataFrame(rates)
    df['close'] = df['close'].astype(float)
    rsi = RSIIndicator(close=df['close'], window=period).rsi()
    return rsi.iloc[-1]

# Open position
def has_open_position():
    positions = mt5.positions_get(symbol=SYMBOL)
    return positions and len(positions) > 0

# Calculate TP
def calculate_tp_distance(lot):
    usd_target = TP_RUPIAH / USD_IDR_RATE
    pip_value = 1.0 * lot
    pip_target = usd_target / pip_value
    return round(pip_target * 0.01, 2)

# Entry
def open_order(order_type, lot):
    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    tp_distance = calculate_tp_distance(lot)
    tp_price = round(price+tp_distance, 2) if order_type == mt5.ORDER_TYPE_BUY else round(price-tp_distance, 2)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": lot,
        "type": order_type,
        "price": price,
        "tp": tp_price,
        "sl": 0.0,
        "magic": MAGIC,
        "comment": f"EA XAUUSD RSI {order_type}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        direction = "BUY" if order_type == mt5.ORDER_TYPE_BUY else "SELL"
        print(f"[{datetime.now()}] {direction} berhasil @ {price:.2f}, TP: {tp_price:.2f}")
    else:
        print(f"[{datetime.now()}] gagal order: {result.retcode} - {result.comment}")

# Main
def main():
    init_mt5()

    next_entry = datetime.now()
    
    while True:
        now = datetime.now()

        if now >= next_entry:
            if not has_open_position():
                rsi = get_rsi(SYMBOL, TIMEFRAME, RSI_PERIOD)
                if rsi is None:
                    print("Gagal mengambil RSI")
                else:
                    print(f"[{now}] RSI: {rsi:.2f}")
                    if rsi < 30:
                        open_order(mt5.ORDER_TYPE_BUY, LOT)
                    elif rsi > 70:
                        open_order(mt5.ORDER_TYPE_SELL, LOT)
                    elif rsi > 50:
                        open_order(mt5.ORDER_TYPE_BUY, LOT)
                    elif rsi < 50:
                        open_order(mt5.ORDER_TYPE_SELL, LOT)
            else:
                print(f"[{now}] masih ada open posisi")
            
            next_entry = now + timedelta(minutes=ENTRY_INTERVAL_MINUTES)
            time.sleep(5)

if __name__ == '__main__':
    main()