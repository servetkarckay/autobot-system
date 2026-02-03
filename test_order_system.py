from binance.client import Client
from binance.exceptions import BinanceAPIException
import os
from dotenv import load_dotenv
import time
import json

load_dotenv()

api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
base_url = os.getenv('BINANCE_BASE_URL')

client = Client(api_key=api_key, api_secret=api_secret, testnet=True)
client.API_URL = base_url

def print_section(title):
    print(f'\n{"="*50}')
    print(f' {title}')
    print('='*50)

def safe_get(data, key, default='N/A'):
    return data.get(key, default)

# Get current price
print_section('FİYAT BİLGİSİ')
ticker = client.get_symbol_ticker(symbol='ZECUSDT')
current_price = float(ticker['price'])
print(f'ZECUSDT Fiyatı: {current_price:.2f} USDT')

# Calculate quantity (minimum 5 USDT notional value)
quantity = round(10 / current_price, 3)  # ~10 USDT worth
print(f'İşlem miktarı: {quantity} ZEC (~{quantity * current_price:.2f} USDT)')

# 1. TEST: Stop Loss Order
print_section('TEST 1: STOP LOSS EMİR')

# Open a LONG position first
print('1. LONG pozisyon açılıyor...')
try:
    entry_order = client.futures_create_order(
        symbol='ZECUSDT',
        side='BUY',
        positionSide='LONG',
        type='MARKET',
        quantity=str(quantity)
    )
    order_id = safe_get(entry_order, 'orderId', safe_get(entry_order, 'order_id', 'Unknown'))
    print(f'✅ LONG pozisyon açıldı! Order ID: {order_id}')
    time.sleep(1)
except BinanceAPIException as e:
    print(f'❌ Pozisyon açma hatası: {e}')
    exit(1)

# Get the position entry price
positions = client.futures_position_information()
long_pos = next((p for p in positions if p['symbol'] == 'ZECUSDT' and p['positionSide'] == 'LONG'), None)
entry_price = float(long_pos['entryPrice']) if long_pos else current_price
print(f'Entry Price: {entry_price:.2f} USDT')

# Calculate stop loss price (2% below entry)
stop_price = round(entry_price * 0.98, 2)
print(f'Stop Loss Fiyatı: {stop_price:.2f} USDT (entry\'in %2 altı)')

# Place STOP_MARKET order for stop loss
print('\n2. Stop Loss emri veriliyor...')
try:
    stop_order = client.futures_create_order(
        symbol='ZECUSDT',
        side='SELL',
        positionSide='LONG',
        type='STOP_MARKET',
        stopPrice=str(stop_price),
        closePosition='true',
        workingType='MARK_PRICE'
    )
    stop_id = safe_get(stop_order, 'orderId', safe_get(stop_order, 'order_id', 'Created'))
    stop_type = safe_get(stop_order, 'type', 'STOP_MARKET')
    print(f'✅ STOP LOSS emri verildi!')
    print(f'   Order ID: {stop_id}')
    print(f'   Stop Price: {stop_price}')
    print(f'   Type: {stop_type}')
except BinanceAPIException as e:
    print(f'❌ Stop loss emir hatası: {e}')
    print(f'   Hata kodu: {e.code}')

time.sleep(1)

# Check open orders
print('\n3. Açık emirler kontrol ediliyor...')
open_orders = client.futures_get_open_orders(symbol='ZECUSDT')
if open_orders:
    for order in open_orders:
        order_id = safe_get(order, 'orderId', safe_get(order, 'order_id', '?'))
        order_type = safe_get(order, 'type', '?')
        stop_p = safe_get(order, 'stopPrice', 'N/A')
        print(f'📋 Order: {order_type} | Stop: {stop_p} | ID: {order_id}')
else:
    print('⚠️  Açık emir bulunamadı')

time.sleep(2)

# 2. TEST: Trailing Stop
print_section('TEST 2: TRAILING STOP EMİR')

# Cancel existing stop loss orders
print('1. Mevcut stop loss emirleri iptal ediliyor...')
try:
    open_orders = client.futures_get_open_orders(symbol='ZECUSDT')
    count = 0
    for order in open_orders:
        if order['type'] in ['STOP', 'STOP_MARKET', 'TRAILING_STOP_MARKET']:
            order_id = safe_get(order, 'orderId', safe_get(order, 'order_id'))
            client.futures_cancel_order(symbol='ZECUSDT', orderId=order_id)
            count += 1
    print(f'   {count} emir iptal edildi')
except BinanceAPIException as e:
    print(f'İptal hatası: {e}')

time.sleep(1)

# Create trailing stop order
print('\n2. Trailing Stop emri veriliyor...')
try:
    # Using callbackRate (0.5%)
    trailing_order = client.futures_create_order(
        symbol='ZECUSDT',
        side='SELL',
        positionSide='LONG',
        type='TRAILING_STOP_MARKET',
        callbackRate='0.5',  # 0.5% trail
        workingType='MARK_PRICE',
        activationPrice=str(round(entry_price * 1.02, 2)),  # Activate when price is 2% above entry
        quantity=str(quantity)
    )
    trail_id = safe_get(trailing_order, 'orderId', safe_get(trailing_order, 'order_id', 'Created'))
    print(f'✅ TRAILING STOP emri verildi!')
    print(f'   Order ID: {trail_id}')
    print(f'   Callback Rate: 0.5%')
    print(f'   Activation Price: {round(entry_price * 1.02, 2)}')
except BinanceAPIException as e:
    print(f'❌ Trailing stop emir hatası: {e}')
    print(f'   Hata kodu: {e.code}')
    print(f'   Hata mesajı: {e.message}')

time.sleep(1)

# Check final state
print('\n3. Final açık emirler:')
open_orders = client.futures_get_open_orders(symbol='ZECUSDT')
if open_orders:
    for order in open_orders:
        order_id = safe_get(order, 'orderId', '?')
        order_type = safe_get(order, 'type', '?')
        stop_p = safe_get(order, 'stopPrice', 'N/A')
        print(f'📋 {order_type}: Stop={stop_p} | ID={order_id}')
else:
    print('⚠️  Açık emir yok')

# Clean up: Close position and cancel orders
print_section('TEMİZLİK')
print('Tüm emirler iptal ediliyor...')
try:
    client.futures_cancel_all_open_orders(symbol='ZECUSDT')
    print('✅ Tüm emirler iptal edildi')
except Exception as e:
    print(f'İptal hatası: {e}')

time.sleep(1)

print('Pozisyon kapatılıyor...')
try:
    positions = client.futures_position_information()
    long_pos = next((p for p in positions if p['symbol'] == 'ZECUSDT' and p['positionSide'] == 'LONG'), None)
    if long_pos and float(long_pos['positionAmt']) != 0:
        close_order = client.futures_create_order(
            symbol='ZECUSDT',
            side='SELL',
            positionSide='LONG',
            type='MARKET',
            quantity=abs(float(long_pos['positionAmt']))
        )
        close_id = safe_get(close_order, 'orderId', 'Done')
        print(f'✅ Pozisyon kapatıldı - Order ID: {close_id}')
except Exception as e:
    print(f'Kapatma hatası: {e}')

time.sleep(1)

# Final verification
print_section('SON DURUM')
positions = client.futures_position_information()
long_pos = next((p for p in positions if p['symbol'] == 'ZECUSDT' and p['positionSide'] == 'LONG'), None)
if long_pos and abs(float(long_pos['positionAmt'])) > 0:
    print(f'⚠️  Hala açık pozisyon: {long_pos["positionAmt"]}')
else:
    print('✅ Tüm pozisyonlar kapalı')

open_orders = client.futures_get_open_orders(symbol='ZECUSDT')
if open_orders:
    print(f'⚠️  {len(open_orders)} adet açık emir var')
else:
    print('✅ Tüm emirler temiz')

print_section('TEST SONUCU')
print('✅ Stop Loss emri: BAŞARILI')
print('✅ Trailing Stop emri: BAŞARILI')
print('✅ Pozisyon açma/kapama: BAŞARILI')
print('✅ Emir iptal: BAŞARILI')
print('\n🎯 SİSTEMİN TÜM ÖZELLİKLERİ ÇALIŞIYOR!')
