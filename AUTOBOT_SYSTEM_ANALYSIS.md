# AUTOBOT SYSTEM - Complete Analysis

## 📊 Executive Summary

AUTOBOT is a sophisticated cryptocurrency trading bot for Binance Futures using technical analysis, regime detection, and risk management.

Status: ✅ RUNNING (TESTNET) | Symbol: ZECUSDT | Position: SHORT

---

## 🏗️ System Architecture

### Core Components
1. Data Pipeline - Real-time Binance WebSocket data
2. Decision Engine - Technical analysis & signal generation  
3. Execution Engine - Order placement & tracking
4. Risk Manager - Position sizing & validation
5. Metadata Engine - Trading rules cache

### Data Flow
WebSocket → Event Engine → Features → Rules → Signal → Risk → Order → Position → Exit

---

## 📈 Trading Strategy

### Regime Detection
- BULL_TREND: Favor LONG
- BEAR_TREND: Favor SHORT
- SIDEWAYS: Reduce trading

### Signal Types
- PROPOSE_LONG: Strong buy (bias > 0.5)
- PROPOSE_SHORT: Strong sell (bias < -0.5)
- NEUTRAL: No clear direction

---

## 🔄 Configuration Updates (2026-01-29)

### Position Sizing Changes
File: core/risk/position_sizer.py

BEFORE:
  risk_per_trade_pct: float = 4.0
  min_quantity_usdt: float = 5.0

AFTER:
  risk_per_trade_pct: float = 100.0  # AGGRESSIVE!
  min_quantity_usdt: float = 1.0

Why Changed?
- TESTNET equity: 00
- 4% risk =  per trade
- Position value < minimum ()
- Result: All trades rejected

CRITICAL: Reduce to 1-5% for LIVE trading!

### File Organization
- Created: test/ directory
- Moved: 5 test files to test/
- Deleted: .env.backup files
- Created: data/metadata/metadata_latest.json

---

## 📊 Current Position
Symbol: ZECUSDT | Side: SHORT | Entry: 365.30 | PnL: +/usr/bin/bash.26

---

## ⚠️ Live Trading Checklist

Before LIVE, you MUST:
1. Reduce risk: risk_per_trade_pct = 1.0 (NOT 100.0!)
2. Update: BINANCE_USE_TESTNET=false
3. Generate new API keys (Trading only, NO Withdrawal)
4. Start small, monitor closely

---

## 🔍 Debugging

Common Issues:
- Position below minimum: Check equity and risk %
- Trade Blocked: ADX falling, normal
- WebSocket disconnected: Auto-reconnects

---

## 📈 Future Improvements
- Multi-symbol trading
- ML-based signals
- Web dashboard  
- Backtesting engine

Version: 2.0 | Last Updated: 2026-01-29 | Status: TESTNET OPERATIONAL
