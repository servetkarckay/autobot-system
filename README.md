# AUTOBOT System

## 📊 Overview

AUTOBOT is a Python-based cryptocurrency trading bot for Binance Futures with algorithmic trading strategies.

## ⚙️ Configuration

### Environment Setup
1. Copy .env.example to .env
2. Configure Binance API credentials
3. Set trading parameters

### Key Parameters
- TRADING_SYMBOLS: ZECUSDT
- MAX_POSITIONS: 1
- LEVERAGE: 10x
- ACCOUNT_EQUITY_USDT: 100.0

### Position Sizing (IMPORTANT!)
Current: risk_per_trade_pct=100.0 (AGGRESSIVE!)
WARNING: For LIVE trading, change to 1-5%!

## 🚀 Installation
```bash
git clone https://github.com/servetkarckay/autobot-system.git
cd autobot-system
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
pm2 start main.py --name autobot --interpreter python3
pm2 logs autobot
```

## 📁 Project Structure
```
autobot_system/
├── main.py                    # Entry point
├── config/                    # Configuration
├── core/                      # Core modules
│   ├── data_pipeline/         # Data ingestion
│   ├── decision/              # Trading decisions
│   ├── execution/             # Order execution
│   ├── metadata/              # Trading metadata
│   └── risk/                  # Risk management
├── data/metadata/             # Cached metadata
├── test/                      # Test files
├── logs/                      # Application logs
└── README.md
```

## 📊 Trading Signals
- LONG: Buy signal
- SHORT: Sell signal
- NEUTRAL: No clear direction

## 🛡️ Risk Management
- Position sizing: 100% equity (configurable)
- Stop loss: 2.5x ATR
- Trailing stop: 2.0x ATR
- Max drawdown: 15%

## 📱 Notifications
Telegram for: startup, signals, entries/exits, errors

## 🔧 Maintenance
```bash
pm2 list
pm2 logs autobot
redis-cli GET autobot:state
```

## ⚠️ Warnings
TESTNET uses fake money. LIVE uses real money!
For LIVE: reduce risk to 1-5%, set BINANCE_USE_TESTNET=false

## 🔄 Recent Updates (2026-01-29)
1. Position sizing: 100% risk (TESTNET only)
2. Test files moved to test/
3. .env.backup removed
4. metadata_latest.json initialized

## 📞 Support
GitHub: https://github.com/servetkarckay/autobot-system

Last Updated: 2026-01-29 | Version: 1.2.0 | Status: TESTNET RUNNING
