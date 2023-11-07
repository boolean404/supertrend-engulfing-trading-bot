import ccxt
import pytz
import api
import schedule
import pandas as pd
pd.set_option('display.max_rows', None)

import warnings
warnings.filterwarnings('ignore')

import numpy as np
from datetime import datetime
import time

exchange = ccxt.binance({
    "apiKey": api.API_KEY,
    "secret": api.SECRET_KEY,
    'enableRateLimit': True
    # 'options': {
    #     'defaultType': 'future'
    # }
})

# exchange = ccxt.okx({
#     "apiKey": api.OKX_API_KEY,
#     "secret": api.OKX_SECRET_KEY
# })

# Input data for trading
name = 'Supertrend Engulfing'
symbol = 'BTC/USDT'
timeframe = '1m'
usdt_amount = 100.0
leverage = 20
trailing_stop_loss_percentage = 0.25

# strategy input
sma_period = 10
atr_period = 10
atr_multiplier = 3

# Fetch the current price of the cryptocurrency
ticker = exchange.fetch_ticker(symbol)
current_price = float(ticker['ask'])
amount = usdt_amount / current_price

# # Fetch your account information
# account_info = exchange.fetch_balance()
# position = account_info['total']
# print(float(position['BNB']))

def check_bull_candle(data):
    bull_candle = None
    
    # 3 Line Strike
    bullSig = data['prev_close3'] < data['prev_open3'] and data['prev_close2'] < data['prev_close2'] and data['open'] < data['prev_open1'] and data['close'] > data['prev_open1']
    bearSig = data['prev_close3'] > data['prev_open3'] and data['prev_close2'] > data['prev_close2'] and data['open'] > data['prev_open1'] and data['close'] < data['prev_open1']
    # Engulfing Candle
    bullishEngulfing = data['open'] < data['prev_open1'] and data['close'] > data['prev_open1']
    bearishEngulfing = data['open'] > data['prev_open1'] and data['close'] < data['prev_open1']

    if bullSig  or bullishEngulfing:
        bull_candle = True

    if bearSig or bearishEngulfing:
        bull_candle = False
    
    return bull_candle

def tr(data):
    data['prev_open1'] = data['open'].shift(1)
    data['prev_open2'] = data['open'].shift(2)
    data['prev_open3'] = data['open'].shift(3)
    data['prev_close2'] = data['close'].shift(2)
    data['prev_close3'] = data['close'].shift(3)
    data['high-low'] = abs(data['high'] - data['low'])
    data['high-pc'] = abs(data['high'] - data['open'])
    data['low-pc'] = abs(data['low'] - data['open'])
    tr = data[['high-low', 'high-pc', 'low-pc']].max(axis=1)

    return tr


def atr(data, period):
    data['tr'] = tr(data)
    atr = data['tr'].rolling(period).mean()

    return atr


def supertrend(df, atr_period, atr_multiplier):
    last_row_index = len(df.index) - 1
    hl2 = (df['high'] + df['low']) / 2
    df['atr'] = atr(df, atr_period)
    df['upperband'] = hl2 + (atr_multiplier * df['atr'])
    df['lowerband'] = hl2 - (atr_multiplier * df['atr'])
    df['check_bull_candle'] = df.apply(check_bull_candle, axis=1)
    df['sma'] = round(df.close.rolling(10).mean(), 2)
    df['in_uptrend'] = True

    for current in range(1, len(df.index)):
        previous = current - 1

        if df['close'][current] > df['upperband'][previous]:
            df['in_uptrend'][current] = True
            
        elif df['close'][current] < df['lowerband'][previous]:
            df['in_uptrend'][current] = False

        else:
            df['in_uptrend'][current] = df['in_uptrend'][previous]

            if df['in_uptrend'][current] and df['lowerband'][current] < df['lowerband'][previous]:
                df['lowerband'][current] = df['lowerband'][previous]

            if not df['in_uptrend'][current] and df['upperband'][current] > df['upperband'][previous]:
                df['upperband'][current] = df['upperband'][previous]
        
    return df


in_long_position = False
in_short_position = False
stop_loss_put_for_long = True
stop_loss_put_for_short = True

def check_buy_sell_orders(df):
    global in_long_position
    global in_short_position
    global stop_loss_put_for_long
    global stop_loss_put_for_short

    print(df.tail(5))
    last_row_index = len(df.index) - 1
    previous_row_index = last_row_index - 1

    # start market changed
    if not df['in_uptrend'][previous_row_index-1] and df['in_uptrend'][previous_row_index]:
        print("\n=> Market just changed to Uptrend!")
    
    elif df['in_uptrend'][previous_row_index-1] and not df['in_uptrend'][previous_row_index]:
        print("\n=> Market just changed to Downtrend!")

    print(f"\n=> Current price of {symbol} is ${current_price}")
    # end market changed

    # start put stop loss
    def get_open_positions(symbol):
        positions = exchange.fapiPrivate_get_positionrisk()
        return [position for position in positions if position['symbol'] == symbol]

    open_positions = get_open_positions(symbol)

    for position in open_positions:
        position_symbol = position['symbol']
        position_side = position['positionSide']
        position_entry_price = float(position['entryPrice'])
        position_amount = float(position['positionAmt'])
        position_pnl = position['unRealizedProfit']

        if position_side == 'LONG':
            in_long_position = True
            print("=> Long position is running.....")
            print(f"Symbol: {position_symbol}, Quantity: {position_amount}, Entry Price: {position_entry_price}, Unrealized PnL: {position_pnl}, Position Side: {position_side}")

            if not stop_loss_put_for_long:
                order_params = {
                    'symbol': position_symbol,
                    'type': 'TRAILING_STOP_MARKET',
                    'side': 'sell',
                    'quantity': position_amount,
                    'callbackRate': trailing_stop_loss_percentage,
                    # 'activationPrice': activation_price
                }
                # trailing_stop_market_order = exchange.create_order(**order_params)
                stop_loss_put_for_long = True
                print(f"=> Trailing stop loss market ordered for {position_side} position!")

        if position_side == 'SHORT':
            in_short_position = True
            print("=> Short position is running.....")
            print(f"Symbol: {position_symbol}, Quantity: {position_amount}, Entry Price: {position_entry_price}, Unrealized PnL: {position_pnl}, Position Side: {position_side}")

            if not stop_loss_put_for_short:
                order_params = {
                    'symbol': position_symbol,
                    'type': 'TRAILING_STOP_MARKET',
                    'side': 'buy',
                    'quantity': position_amount,
                    'callbackRate': trailing_stop_loss_percentage,
                    # 'activationPrice': activation_price
                }
                # trailing_stop_market_order = exchange.create_order(**order_params)
                stop_loss_put_for_short = True
                print(f"=> Trailing stop loss market ordered for {position_side} position!")

        else:
            print("=> There is no 'Long' and 'Short' position!")
        print("")
    # end put stop loss


    # start buy
    if not in_long_position:

        if df['in_uptrend'][previous_row_index]:
            print("=> Supertrend is in Uptrend and waiting for Bull Candle..........")

            for i in range(len(df.index)-2, 0, -1):
                if df['in_uptrend'][i] and df['check_bull_candle'][i]:
                    print(f"=> Bull Candle is occured at {df['timestamp'][i]}")
                    print("=> Waiting to buy at SMA 10..........")
                    current_bit_price = float(ticker['bit'])
                    if current_bit_price <= df['sma'][last_row_index]:
                        print(f"=> Price reached at SMA 10 ${df['sma'][last_row_index]}")
                        # buy_order = exchange.create_market_buy_order(symbol=symbol, amount=amount, params={'leverage': leverage})
                        print(f"=> Market Buy ordered {symbol} | ${usdt_amount} at {current_bit_price}")
                        in_long_position = True
                        stop_loss_put_for_long = False

                    break
    # end buy

    # start sell
    if not in_short_position:

        if not df['in_uptrend'][previous_row_index]:
            print("=> Supertrend is in Downtrend and waiting for Bear Candle..........")

            for i in range(len(df.index)-2, 0, -1):
                if not df['in_uptrend'][i] and df['check_bull_candle'][i] == False:
                    print(f"=> Bear Candle is occured at {df['timestamp'][i]}")
                    print("=> Waiting to sell at SMA 10..........")

                    if current_price >= df['sma'][last_row_index]:
                        print(f"=> Price reached at SMA 10 ${df['sma'][last_row_index]}")
                        # sell_order = exchange.create_market_sell_order(symbol=symbol, amount=amount, params={'leverage': leverage})
                        print(f"=> Market Sell ordered {symbol} | ${usdt_amount} at {current_price}")
                        in_short_position = True
                        stop_loss_put_for_short = False
                
                    break
    

bot_status = True
bot_start_run_time = time.strftime('%Y-%m-%d %H:%M:%S')

def run_bot():
    try:
        print("\n#######################################################################################################")
        print(f"{name} Trading Bot is running {symbol} | {timeframe} Timeframe | Since {bot_start_run_time}")
        print("#######################################################################################################")
        print(f"Fetching new bars for {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        bars = exchange.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC')
        
        # Convert to Myanmar timezone (UTC +6:30)
        myanmar_timezone = pytz.timezone('Asia/Yangon')
        df['timestamp'] = df['timestamp'].dt.tz_convert(myanmar_timezone)
        supertrend_data = supertrend(df, atr_period, atr_multiplier)
        check_buy_sell_orders(supertrend_data)
        

    except Exception as e:
        print(f"An error occurred: {e}")

schedule.every(5).seconds.do(run_bot)

while bot_status:
    schedule.run_pending()
    time.sleep(1)
