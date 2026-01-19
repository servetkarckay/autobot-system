# AUTOBOT SYSTEM ARCHITECTURE
## Production-Ready Implementation v1.0

**Document ID:** AUTOBOT_ARCH_IMPL_V1.0  
**Date:** 2026-01-19  
**Status:** PRODUCTION REFERENCE

---

## 1. SYSTEM OVERVIEW

AUTOBOT is a rule-based, autonomous quantitative trading system that:
- Executes predetermined trading strategies on Binance Futures (USD-M)
- Detects market regimes (BULL_TREND, BEAR_TREND, RANGE) and activates appropriate strategies
- Implements hierarchical risk controls (veto chain) for all trading decisions
- Adapts limited parameters based on historical performance
- Operates 24/7 with millisecond-level consistency

---

## 2. DIRECTORY STRUCTURE

```
autobot_system/
├── config/                    # Configuration management
├── core/                      # Core modules
│   ├── data_pipeline/         # Data collection & validation
│   ├── feature_engine/        # Indicators & regime detection
│   ├── decision/              # Signal generation
│   ├── risk/                  # Risk management & veto chain
│   ├── execution/             # Order execution
│   ├── adaptive/              # Parameter tuning
│   ├── metadata/              # Instrument metadata
│   ├── notification/          # Alerts & monitoring
│   └── state/                 # State persistence
├── strategies/                # Trading strategies
├── utils/                     # Utilities
├── tests/                     # Test suite
├── data/                      # Data storage
└── logs/                      # Log files
```

---

## 3. DATA FLOW (NORMAL)

WebSocket -> Data Validator -> Feature Engine -> Regime Detector 
-> Decision Engine -> Risk Brain -> Execution Engine -> State Manager

---

## 4. DATA FLOW (ERROR)

Any Layer -> Error Logging -> Notification -> Recovery Action
- DATA_LOSS_SAFE_MODE (data feed issues)
- RETRY_WITH_BACKOFF (API errors)
- SAFE_MODE (critical failures)
- SYSTEM_HALTED (kill-switch)

---

## 5. CORE MECHANISMS

### 5.1 State Management
- System state persisted to Redis after every trade
- On restart: reconcile with exchange state
- Continue operation seamlessly

### 5.2 Risk Veto Chain (Hard Stop)
1. Position Size Veto
2. Correlation Veto
3. Max Positions Veto
4. Volatility Veto
5. Liquidity Veto
ANY veto = trade rejected (final)

### 5.3 Decision-Execution Separation
- Decision Engine: produces signals
- Risk Brain: can veto any signal
- Execution Engine: only receives approved signals

---

## 6. OPERABILITY CRITERIA

### System States
| State | Trading |
|-------|---------|
| RUNNING | Yes |
| DEGRADED | Yes (caution) |
| SAFE_MODE | No |
| HALTED | No |

### Self-Stop Conditions
- Daily loss limit exceeded (e.g., -3%)
- Maximum drawdown exceeded (e.g., -15%)
- Data feed loss > 30 seconds
- API authentication failure

---

## 7. TESTING MODES

| Mode | Description |
|------|-------------|
| DRY_RUN | Signals only, no orders |
| TESTNET | Real data, testnet execution |
| LIVE | Full production |
