import ccxt
import pytz
import secret
import schedule
import pandas as pd
pd.set_option('display.max_rows', None)

import warnings
warnings.filterwarnings('ignore')

import numpy as np
from datetime import datetime
import time


# for binance exchange
exchange = ccxt.binance({
    "apiKey": secret.BINANCE_API_KEY,
    "secret": secret.BINANCE_SECRET_KEY,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future'
    }
})

# input data for trading
name = 'Supertrend Engulfing'
symbol = 'BTCUSDT'
timeframe = '5m'
usdt_amount = 110
leverage = 20
callback_rate = 0.5 # trailing stop

# input data for strategy
sma_period = 10
atr_period = 10
atr_multiplier = 3

# fetch last price of symbol
ticker = exchange.fetch_ticker(symbol)
last_price = float(ticker['last'])
amount = usdt_amount / last_price

# global variables
bot_status = True
adjusted_leverage = False
in_long_position = False
in_short_position = False
stop_loss_put_for_long = True
stop_loss_put_for_short = True

# get bot start run time
def get_bot_start_run_time():
    return time.strftime('%Y-%m-%d %H:%M:%S')

# fetch your account balance
def get_balance():
    account_info = exchange.fetch_balance()
    return round(account_info['total']['USDT'], 2)

# adjust leverage
def adjust_leverage():
    global adjusted_leverage
    response = exchange.fapiprivate_post_leverage({
        'symbol': symbol,
        'leverage': leverage
    })
    adjusted_leverage = True
    print(f"\n=> Leverage adjusted successfully to: {response['leverage']}x\n")

# start check bull candle
def check_bull_candle(data):
    bull_candle = None
    
    # 3 Line Strike
    bullSig = data['prev_close3'] < data['prev_open3'] and data['prev_close2'] < data['prev_close2'] and data['open'] < data['prev_open1'] and data['close'] > data['prev_open1']
    bearSig = data['prev_close3'] > data['prev_open3'] and data['prev_close2'] > data['prev_close2'] and data['open'] > data['prev_open1'] and data['close'] < data['prev_open1']
    # Engulfing Candle
    bullishEngulfing = data['open'] < data['prev_open1'] and data['close'] > data['prev_open1']
    bearishEngulfing = data['open'] > data['prev_open1'] and data['close'] < data['prev_open1']

    if bullSig or bullishEngulfing:
        bull_candle = True
    if bearSig or bearishEngulfing:
        bull_candle = False
    return bull_candle
# end check bull candle

# start supertrend
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
    hl2 = (df['high'] + df['low']) / 2
    df['atr'] = atr(df, atr_period)
    df['upperband'] = hl2 + (atr_multiplier * df['atr'])
    df['lowerband'] = hl2 - (atr_multiplier * df['atr'])
    df['bull_candle'] = df.apply(check_bull_candle, axis=1)
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
# end supertrend

# Fetch open positions
def get_open_positions():
    # positions = exchange.fetch_positions_risk(symbols=[symbol])
    positions = exchange.fapiprivatev2_get_positionrisk()
    return [position for position in positions if position['symbol'] == symbol]

# Fetch open orders
def get_open_orders():
    return exchange.fetch_open_orders(symbol)

# create trailing stop market order
def create_trailing_stop_market_order(positionSide, amount):
    side = None
    trailing_stop_params = {
        'positionSide': positionSide,
        'callbackRate': callback_rate,
        'priceProtect': True
    }
    if positionSide == 'SHORT':
        side = 'buy'
    if positionSide == 'LONG':
        side = 'sell'
    return exchange.create_order(symbol=symbol, type='trailing_stop_market', side=side, amount=abs(amount), params=trailing_stop_params)

# change default timezone
def change_datetime_zone(update_time, timezone='Asia/Yangon'):
    utc_datetime = datetime.utcfromtimestamp(update_time)
    target_timezone = pytz.timezone(timezone)  # Replace timezone with the desired timezone
    return utc_datetime.replace(tzinfo=pytz.utc).astimezone(target_timezone) # retun is updatetime

# start check buy sell orders
def check_buy_sell_orders(df):
    global in_long_position
    global in_short_position
    global stop_loss_put_for_long
    global stop_loss_put_for_short

    last_row_index = len(df.index) - 1
    previous_row_index = last_row_index - 1

    print(df.tail(5))

    # market changed
    if not df['in_uptrend'][previous_row_index-1] and df['in_uptrend'][previous_row_index]:
        print("\n=> Market just changed to UP-TREND!")
    if df['in_uptrend'][previous_row_index-1] and not df['in_uptrend'][previous_row_index]:
        print("\n=> Market just changed to DOWN-TREND!")

    open_positions = get_open_positions()
    # print(open_positions)

    for position in open_positions:
        position_symbol = position['symbol']
        position_side = position['positionSide']
        position_leverage = position['leverage']
        position_entry_price = float(position['entryPrice'])
        position_mark_price = float(position['markPrice'])
        position_amount = float(position['positionAmt'])
        position_pnl = round(float(position['unRealizedProfit']), 2)
        position_liquidation_price = round(float(position['liquidationPrice']), 2)
        position_amount_usdt =  round((position_amount * position_entry_price), 2)
        position_update_time = float(position['updateTime']) / 1000.0
        
        # change default timezone to local
        position_running_time = change_datetime_zone(position_update_time).strftime('%Y-%m-%d %H:%M:%S')

        # get long position and put trailing stop
        if position_side == 'LONG' and position_amount != 0:
            in_long_position = True
            print(f"\n=> {position_side} position is running since {position_running_time}")
            print(f"=> {position_symbol} | {position_leverage}x | {position_side} | {position_amount_usdt} USDT | Entry: {position_entry_price} | Mark: {round(position_mark_price, 2)} | Liquidation: {position_liquidation_price} | PNL: {position_pnl} USDT")

            # get open orders
            open_orders = get_open_orders()

            if len(open_orders) == 0:
                stop_loss_put_for_long = False

            if len(open_orders) > 0:
                for open_order in open_orders:
                    if open_order['info']['symbol'] == position_symbol and open_order['info']['positionSide'] != position_side and open_order['side'] != 'sell':
                        stop_loss_put_for_long = False

            if not stop_loss_put_for_long:
                trailing_stop_market_order = create_trailing_stop_market_order(positionSide=position_side, amount=position_amount)
                stop_loss_put_for_long = True
                print(trailing_stop_market_order)
                print(f"\n=> Trailing stop market ordered for {position_side} position of {position_symbol}!")

        # get short position and put trailing stop
        if position_side == 'SHORT' and position_amount != 0:
            in_short_position = True
            print(f"\n=> {position_side} position is running since {position_running_time}")
            print(f"=> {position_symbol} | {position_leverage}x | {position_side} | {position_amount_usdt} USDT | Entry: {position_entry_price} | Mark: {round(position_mark_price, 2)} | Liquidation: {position_liquidation_price} | PNL: {position_pnl} USDT")

            # get open orders
            open_orders = get_open_orders()

            if len(open_orders) == 0:
                stop_loss_put_for_short = False

            if len(open_orders) > 0:
                for open_order in open_orders:
                    if open_order['info']['symbol'] == position_symbol and open_order['info']['positionSide'] != position_side and open_order['side'] != 'buy':
                        stop_loss_put_for_short = False

            if not stop_loss_put_for_short:
                trailing_stop_market_order = create_trailing_stop_market_order(positionSide=position_side, amount=position_amount)
                stop_loss_put_for_short = True
                print(f"\n=> Trailing stop market ordered for {position_side} position of {position_symbol}!")
                # print(trailing_stop_order)

    if not in_long_position and not in_short_position:
        print("\nThere is no LONG or SHORT position!")

    # get account balance
    account_balance = get_balance()
    print(f"\n=> Last price of {symbol} = {last_price} | Account Balance = {account_balance} USDT\n")

    # long position
    if not in_long_position:

        if df['in_uptrend'][previous_row_index]:
            print("=> [1-3] Market is in UP-TREND and waiting for BULL Candle..........")

            for i in range(len(df.index)-2, 0, -1):
                if df['in_uptrend'][i] and df['bull_candle'][i] == True and df['open'][i] < df['sma'][i]:
                    print(f"=> [2-3] BULL Candle is occured at {df['timestamp'][i]} and waiting to LONG at SMA..........")

                    if last_price <= df['sma'][last_row_index]:
                        print(f"=> [3-3] Price reached at SMA, {df['sma'][last_row_index]}")

                        if account_balance > 1:
                            buy_order = exchange.create_market_buy_order(symbol=symbol, amount=amount, params={'positionSide': 'LONG'})
                            in_long_position = True
                            stop_loss_put_for_long = False
                            # print(buy_order)
                            print(f"=> Market BUY ordered {buy_order['info']['symbol']} | {buy_order['amount'] * buy_order['price']} USDT at {buy_order['price']}")
                        else:
                            print("=> Not enough balance for LONG position!")
                    break
                

    # short position
    if not in_short_position:

        if not df['in_uptrend'][previous_row_index]:
            print("=> [1-3] Market is in DOWN-TREND and waiting for BEAR Candle..........")

            for i in range(len(df.index)-2, 0, -1):
                if not df['in_uptrend'][i] and df['bull_candle'][i] == False and df['open'][i] > df['sma'][i]:
                    print(f"=> [2-3] BEAR Candle is occured at {df['timestamp'][i]} and waiting to SHORT at SMA..........")

                    if last_price >= df['sma'][last_row_index]:
                        print(f"=> [3-3] Price reached at SMA, {df['sma'][last_row_index]}")

                        if account_balance > 1:
                            sell_order = exchange.create_market_sell_order(symbol=symbol, amount=amount, params={'positionSide': 'SHORT'})
                            in_short_position = True
                            stop_loss_put_for_short = False
                            # print(sell_order)
                            print(f"=> Market SELL ordered {sell_order['info']['symbol']} | {sell_order['amount'] * sell_order['price']} USDT at {sell_order['price']}")
                        else:
                            print("=> Not enough balance for SHORT position!")
                    break

    if in_long_position and in_short_position:
        print("=> Both LONG and SHORT positions are already running.")
# end check buy sell orders

bot_start_run_time = get_bot_start_run_time()

def run_bot():
    try:
        print("\n\n#######################################################################################################################")
        print(f"\t\t{name} Trading Bot is running {symbol} | {timeframe} | {leverage}x | Since {bot_start_run_time}")
        print("#######################################################################################################################")
        print(f"Fetching new bars for {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        bars = exchange.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC')
        
        # Convert to Myanmar timezone (UTC +6:30)
        myanmar_timezone = pytz.timezone('Asia/Yangon')
        df['timestamp'] = df['timestamp'].dt.tz_convert(myanmar_timezone)

        # change leverage to default
        if not adjusted_leverage:
            adjust_leverage()
            time.sleep(1)

        # call all functions
        supertrend_data = supertrend(df, atr_period, atr_multiplier)
        check_buy_sell_orders(supertrend_data)
        
    except Exception as e:
        print(f"An error occurred: {e}")

schedule.every(5).seconds.do(run_bot)

while bot_status:
    schedule.run_pending()
    time.sleep(1)
