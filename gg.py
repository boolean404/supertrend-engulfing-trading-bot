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

# For binance exchange
exchange = ccxt.binance({
    "apiKey": secret.BINANCE_API_KEY,
    "secret": secret.BINANCE_SECRET_KEY,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future'
        
    }
})

# For okx exchange
# exchange = ccxt.okx({
#     "apiKey": secret.OKX_API_KEY,
#     "secret": secret.OKX_SECRET_KEY,
#     "password": secret.OKX_PASSWORD,
#     'enableRateLimit': True,
#     'options': {
#         'defaultType': 'future',
#     },
# })

# Input data for trading
name = 'Supertrend Engulfing'
symbol = 'BTCUSDT'
timeframe = '1m'
usdt_amount = 110
leverage = 120
trailing_stop_loss_percentage = 0.25

# Strategy input
sma_period = 10
atr_period = 10
atr_multiplier = 3

# Fetch last price by symbol
ticker = exchange.fetch_ticker(symbol)
last_price = float(ticker['last'])

# print(ticker['ask'])
print(last_price)
# print(ticker['bid'])
amount = usdt_amount / 36000

# Fetch your account information
account_info = exchange.fetch_balance()
# print(account_info)
# total_balance = account_info['total']
# print(total_balance)
balance = account_info['total']['USDT']
# for i in balance:
#     print(i)
print(balance)




# Check if leverage has been adjusted already
adjusted_leverage = False

# # Function to adjust leverage
# def adjust_leverage():
#     global adjusted_leverage
#     response = exchange.fapiprivate_post_leverage({
#         'symbol': symbol,
#         'leverage': leverage
#     })
#     print('=> Leverage adjusted successfully to:', response['leverage'], 'x')
#     adjusted_leverage = True

# # Check if leverage has been adjusted before attempting to adjust it again
# if not adjusted_leverage:
#     adjust_leverage()

buy_order_params = {
    'positionSide': 'LONG',
}

try:
    # buy_order = exchange.create_limit_buy_order(symbol=symbol, amount=amount, price=36000, params=order_params)
    # buy_order = exchange.create_market_buy_order(symbol=symbol, amount=amount, params=buy_order_params)
    # print(buy_order) # important to read
    
    # time.sleep(2)

    # Calculate stop price
    stop_price = last_price - (last_price * trailing_stop_loss_percentage / 100)

    # trailing_stop_order_params = {
    #     # 'symbol': symbol,
    #     # 'type': 'TRAILING_STOP_MARKET',
    #     'type': 'TRAILING_STOP_MARKET',
    #     # 'amount': amount,
    #     'callbackRate': trailing_stop_loss_percentage,
    #     # 'priceProtect': True,
    #     # 'stopPrice': stop_price,
    #     # 'activationPrice': last_price
    # }
    # trailing_stop_market_order = exchange.create_market_order(symbol=symbol,side='sell', amount=0.003, params=trailing_stop_order_params)
    # # stop_loss_put_for_long = True
    # print(trailing_stop_market_order) # important 
    # print(f"=> Trailing stop loss market ordered for {symbol} position!")

    # Define trailing stop parameters
    # callback_rate = 0.01  # 1% callback rate
    activation_price = None  # Set to None to use the last price initially

    # Function to place a trailing stop order
    orders = exchange.fetch_open_orders(symbol)
    print(orders)
    # trailing_order = exchange.edit_order(id= orders[0]['id'], symbol=symbol, type='limit', side='buy', amount=0.003, price=36000)
    # print(trailing_order)


    trailing_stop_params = {
        'positionSide': 'SHORT',
        'callbackRate': 1,
        'priceProtect': True
    }
    trailing_stop_order = exchange.create_order(symbol=symbol, type='trailing_stop_market', side='buy', amount=0.003, params=trailing_stop_params)
    print(trailing_stop_order)


    open_orders = exchange.fetch_open_orders(symbol)
    print(orders)



except Exception as e:
    print(f"An error occurred: {e}")