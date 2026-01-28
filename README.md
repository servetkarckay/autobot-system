# AUTOBOT Trading System

\![Python](https://img.shields.io/badge/Python-3.12-blue)
\![License](https://img.shields.io/badge/License-Proprietary-red)
\![Status](https://img.shields.io/badge/Status-Active-green)
\![Environment](https://img.shields.io/badge/Env-TESTNET-orange)

## 📖 Overview

AUTOBOT is an **algorithmic cryptocurrency trading system** designed for Binance Futures. It uses multi-factor analysis, regime detection, and risk management to make automated trading decisions.

### Key Features

- **Multi-Factor Signal Generation**: 8 trading rules with bias aggregation
- **Regime Detection**: Identifies market conditions (RANGE, BULL_TREND, BEAR_TREND)
- **ADX Gate**: Trend confirmation and choppy market filtering
- **Risk Management**: Position sizing, stop-loss, pre-trade vetoes
- **Real-time Data**: Binance WebSocket integration
- **State Persistence**: Redis-based state management
- **Telegram Notifications**: Real-time trade alerts
- **10x Leverage**: Futures trading with configurable leverage

---

## 🏗️ Architecture

```
autobot_system/
├── main.py                          # Entry point
├── config/                          # Configuration
│   ├── settings.py                  # Trading settings
│   └── logging_config.py            # Logging setup
├── core/
│   ├── data_pipeline/               # Data collection & processing
│   │   ├── event_engine.py          # Main trading engine
│   │   └── websocket_collector.py   # Binance WebSocket
│   ├── decision/                    # Signal generation
│   │   ├── rule_engine.py           # Trading rules
│   │   └── bias_generator.py        # Bias calculation
│   ├── execution/                   # Order execution
│   │   ├── order_manager.py         # Binance orders
│   │   └── exit_manager.py          # Exit strategies
│   ├── feature_engine/              # Technical indicators
│   │   ├── indicators.py            # TA calculations
│   │   ├── incremental_indicators.py # Real-time updates
│   │   └── regime_detector.py       # Market regime
│   ├── risk/                        # Risk management
│   │   ├── adx_entry_gate.py        # Trend filter
│   │   ├── position_sizer.py        # Position sizing
│   │   └── pre_trade_veto.py        # Pre-trade checks
│   ├── state_manager.py             # Redis state persistence
│   ├── notifier.py                  # Telegram notifications
│   └── constants.py                 # System constants
├── strategies/
│   └── trading_rules.py             # Trading rule definitions
├── utils/
│   ├── binance_client.py            # Binance API client
│   └── validation_helpers.py        # Validation utilities
└── requirements.txt                 # Dependencies
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Redis server
- Binance Futures account (TESTNET supported)
- Telegram bot (for notifications)

### Installation

```bash
# Clone repository
cd autobot_system

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure settings
cp config/settings.py config/settings.py.local
# Edit settings.py.local with your API keys
```

### Configuration

Edit `config/settings.py`:

```python
# Binance API Credentials
BINANCE_API_KEY = "your_api_key"
BINANCE_API_SECRET = "your_api_secret"

# Trading Settings
TRADING_SYMBOLS = ["ETHUSDT"]
LEVERAGE = 10
MAX_POSITIONS = 1
ACTIVATION_THRESHOLD = 0.7

# Environment
ENVIRONMENT = "TESTNET"  # or "PRODUCTION"
DRY_RUN = False  # Set True for paper trading

# Telegram
TELEGRAM_BOT_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_chat_id"
```

### Running

```bash
# Start the bot
python3 main.py

# Run in background
nohup python3 main.py > bot_output.log 2>&1 &

# Using PM2
pm2 start main.py --name autobot
```

---

## 📊 System Components

### 1. Data Pipeline (`core/data_pipeline/`)

**WebSocketCollector**: Real-time market data from Binance
- Kline (candlestick) data
- Book ticker (bid/ask)
- Aggregated trades
- Multi-connection support for scalability
- Latency tracking and reconnection logic

**EventEngine**: Main trading orchestrator
- Signal evaluation
- Position management
- Exit checking
- State synchronization

### 2. Decision Engine (`core/decision/`)

**RuleEngine**: Multi-factor signal generation
- 8 independent trading rules
- Bias aggregation (-1.0 to +1.0)
- Confidence calculation
- Veto chain integration

**BiasGenerator**: Signal combination logic
- Weighted rule voting
- Confidence thresholding
- Neutral signal handling

### 3. Feature Engine (`core/feature_engine/`)

**Indicators**: Technical analysis
- RSI (Relative Strength Index)
- MACD (Moving Average Convergence Divergence)
- EMA crossovers
- Bollinger Bands
- ATR (Average True Range)

**RegimeDetector**: Market condition identification
- RANGE: Sideways market
- BULL_TREND: Upward trend
- BEAR_TREND: Downward trend
- Volatility classification

### 4. Risk Management (`core/risk/`)

**ADXEntryGate**: Trend confirmation filter
- Minimum ADX threshold (25)
- ADX falling detection (chop filter)
- Trend stability check

**PositionSizer**: Position sizing algorithm
- Risk-per-trade calculation
- ATR-based stops
- Minimum position validation

**PreTradeVeto**: Final safety checks
- Correlation analysis
- Volatility limits
- Maximum drawdown protection

### 5. Execution (`core/execution/`)

**OrderManager**: Binance order handling
- Market orders
- Leverage setting
- Filter validation
- Order reconciliation

**ExitManager**: Position exit logic
- Stop-loss
- Take-profit
- Regime change exits
- Time-based exits

---

## 🎯 Trading Logic

### Signal Generation Flow

```
1. WebSocket Data Arrives
   ↓
2. Update Indicators (RSI, MACD, EMA, etc.)
   ↓
3. Detect Market Regime (RANGE/BULL/BEAR)
   ↓
4. Evaluate Trading Rules (8 rules)
   ↓
5. Aggregate Biases → Signal (PROPOSE_LONG/SHORT/NEUTRAL)
   ↓
6. ADX Gate Check (trend confirmation)
   ↓
7. Pre-Trade Veto (final safety checks)
   ↓
8. Position Sizing (calculate quantity)
   ↓
9. Order Execution (Binance Futures)
   ↓
10. Position Monitoring (exit checks)
```

### Trading Rules

1. **Trend Following**: EMA crossover signals
2. **Momentum**: RSI overbought/oversold
3. **Breakout**: Bollinger Band penetration
4. **Mean Reversion**: Price deviation from moving average
5. **Volume Spike**: Unusual volume activity
6. **MACD Signal**: MACD line crossovers
7. **Volatility**: ATR-based entries
8. **Custom**: User-defined strategy

---

## 📈 Performance Metrics

### Current Settings

| Parameter | Value |
|-----------|-------|
| Symbols | ETHUSDT |
| Leverage | 10x |
| Max Positions | 1 |
| Activation Threshold | 0.7 |
| ADX Minimum | 25 |
| ADX Chop Filter | Enabled |
| Environment | TESTNET |

### Risk Parameters

| Parameter | Value |
|-----------|-------|
| Risk Per Trade | 1% |
| Max Drawdown | 10% |
| Stop Loss | ATR-based |
| Take Profit | 2x risk |

---

## 🔧 Maintenance

### Logs

- **Main Log**: `bot_output.log` (JSON format)
- **PM2 Logs**: `/root/.pm2/logs/`

### Monitoring

```bash
# Check process
ps aux | grep main.py

# View live logs
tail -f bot_output.log | jq

# Filter INFO logs
grep level:INFO bot_output.log | jq

# Check Redis state
redis-cli
> GET autobot:state
```

### Troubleshooting

**Issue**: No trades being executed
- Check activation threshold (0.7)
- Verify ADX gate isn't blocking
- Confirm confidence scores > threshold

**Issue**: WebSocket disconnects
- Check network connectivity
- Verify Binance TESTNET status
- Review reconnection logic in logs

**Issue**: Redis connection errors
- Confirm Redis is running: `systemctl status redis`
- Check connection settings in `settings.py`

---

## 📝 API Reference

### State Manager

```python
from core.state_manager import state_manager

# Save signal
await state_manager.save_signal(signal)

# Get positions
positions = await state_manager.get_positions()

# Update system status
await state_manager.update_status(SystemStatus.RUNNING)
```

### Notification Manager

```python
from core.notifier import notification_manager

# Send info
notification_manager.send_info("Bot started")

# Send warning
notification_manager.send_warning("High volatility")

# Send error
notification_manager.send_error("API error occurred")
```

---

## 🤝 Contributing

This is a proprietary trading system. For inquiries:

- **Email**: support@kuberasystem.tech
- **Telegram**: @kubera_system

---

## ⚖️ License

Proprietary - All rights reserved

---

## 📜 Changelog

### v1.3 (Current)
- Improved shutdown handling
- Added health check endpoint
- Better error handling
- Graceful cleanup on signals

### v1.2
- ADX chop filter enhancement
- Position sizing fixes
- WebSocket reconnection improvements

### v1.1
- Regime detection added
- Multi-symbol support
- Redis state persistence

### v1.0
- Initial release
- Basic trading functionality
- TESTNET support

---

## ⚠️ Disclaimer

**This software is for educational purposes only. Cryptocurrency trading involves substantial risk of loss. Past performance is not indicative of future results.**

- Use TESTNET first
- Start with small amounts
- Never risk more than you can afford to lose
- Understand the risks of leveraged trading

---

**Built with ❤️ by Kubera System Technology**
