# AUTOBOT - Autonomous Trading System

## Overview

AUTOBOT is a rule-based, autonomous quantitative trading system for Binance Futures.

**Key Features:**
- Deterministic rule-based decision making (no AGI/LLM)
- Hierarchical risk controls with veto chain
- Market regime detection and adaptive strategy selection
- 24/7 operation with state persistence
- Telegram notifications for monitoring

## Architecture

```
Data Pipeline → Feature Engine → Decision Engine → Risk Brain → Execution Engine
```

### Core Modules

- **Data Pipeline**: WebSocket data collection and validation
- **Feature Engine**: Technical indicators and regime detection
- **Decision Engine**: Immutable rule-based signal generation
- **Risk Brain**: Pre-trade veto chain (hard stops)
- **Execution Engine**: Order management with slippage control
- **Adaptive Engine**: Limited parameter tuning
- **Notification**: Priority-based Telegram alerts

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys and settings
```

### 3. Run in Dry-Run Mode

```bash
python main.py
```

## Configuration

See `.env.example` for all configuration options.

Key settings:
- `ENVIRONMENT`: DRY_RUN, TESTNET, or LIVE
- `BINANCE_TESTNET`: true for testnet, false for live
- `MAX_POSITIONS`: Maximum concurrent positions
- `MAX_DRAWDOWN_PCT`: Kill-switch drawdown threshold
- `DAILY_LOSS_LIMIT_PCT`: Daily loss limit

## System States

| State | Trading | Description |
|-------|---------|-------------|
| RUNNING | Yes | Normal operation |
| DEGRADED | Yes | Non-critical issues |
| SAFE_MODE | No | Manual intervention required |
| HALTED | No | Kill-switch triggered |

## Testing

```bash
pytest tests/
```

## Documentation

- `ARCHITECTURE.md`: System architecture and design
- `docs/`: Comprehensive documentation (copied to scan server)

## Security

- API keys stored in `.env` (never in Git)
- Pydantic `SecretStr` for sensitive values
- IP whitelisting recommended
- Never run as root

## License

Proprietary - All rights reserved.
