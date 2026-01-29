from binance.client import Client

api_key = "KO8pZmBfoWHIb699JheJ5oaJmpSNMovgp6Xjrl4MB08KPJHjncDXe56eqF6GXee4"
api_secret = "DVe7roP49Q4a0GkZxRgJz4T9xl2fhbBCjtHUfrIosTFRMa49TU3FUowY7oMTmjMz"

client = Client(api_key, api_secret, testnet=True)

print("=== LEVERAGE AYARLA ===")
client.futures_change_leverage(symbol="ETHUSDT", leverage=10)
print("Leverage 10x ayarlandi")

print("\n=== TEST MARKET ORDER (LONG) ===")
order = client.futures_create_order(
    symbol="ETHUSDT",
    side="BUY",
    type="MARKET",
    quantity=0.001
)
print("Order ID:", order["orderId"])
print("Status:", order["status"])
print("Avg Price:", order.get("avgPrice", "MARKET"))
print("Executed Qty:", order["executedQty"])

print("\n=== ACIK POZISYONLAR ===")
positions = client.futures_position_information(symbol="ETHUSDT")
for p in positions:
    amt = float(p["positionAmt"])
    if amt != 0:
        side = "LONG" if amt > 0 else "SHORT"
        print("Symbol:", p["symbol"])
        print("Side:", side)
        print("Quantity:", p["positionAmt"])
        print("Entry Price:", p["entryPrice"])
        print("Unrealized PNL: $" + p["unRealizedProfit"])
