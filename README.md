# AUTOBOT - Autonomous Trading System

## 1. Overview

**AUTOBOT** is a fully autonomous, rule-based quantitative trading system designed for the Binance Futures market. It operates 24/7, processing real-time market data to execute trades based on a predefined set of technical analysis rules. The system is built for robustness and includes a multi-layered risk management framework to operate safely in various market conditions.

### 1.1. Key Features

- **Fully Automated**: Operates without human intervention.
- **Rule-Based**: Trading decisions are 100% deterministic and based on technical indicators.
- **Risk Management**: Includes pre-trade veto checks, dynamic position sizing, and ATR-based stop-losses.
- **Real-Time Monitoring**: Sends priority-based notifications via Telegram for all major events (trades, errors, status changes).
- **Persistent State**: Uses Redis to save and restore its state, allowing for seamless restarts.
- **Multi-Environment**: Supports `DRY_RUN`, `TESTNET`, and `LIVE` trading modes.

## 2. Getting Started

### 2.1. Prerequisites

- Python 3.12+
- Redis server
- A Binance Futures account (Testnet or Live)
- A Telegram Bot and Chat ID

### 2.2. Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd autobot_system
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

### 2.3. Configuration

1.  **Create a `.env` file** by copying the example file:
    ```bash
    cp .env.example .env
    ```

2.  **Edit the `.env` file** with your specific settings:
    - `BINANCE_API_KEY` and `BINANCE_API_SECRET`
    - `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
    - `REDIS_HOST` and `REDIS_PASSWORD` (if applicable)
    - Set the `ENVIRONMENT` to `DRY_RUN` to start safely.

## 3. How to Use

### 3.1. Running the Bot

You can run the bot directly or using a process manager like `pm2`.

**Directly:**

```bash
# Make sure your virtual environment is activated
source venv/bin/activate

# Start the bot
python main.py
```

**Using PM2 (Recommended for Production):**

The `ecosystem.config.js` file is configured to run the bot with `pm2`.

```bash
# Start the bot using the ecosystem file
pm2 start ecosystem.config.js

# To stop the bot
pm2 stop autobot

# To restart
pm2 restart autobot
```

### 3.2. Monitoring the Bot

Monitoring is crucial for ensuring the bot is operating as expected.

**Real-Time Logs:**

You can stream the bot's logs in real-time to see detailed information about its operations.

```bash
# Follow the log file in real-time
tail -f logs/autobot.log
```

If you are using `pm2`, you can use its logging tools:

```bash
# Stream logs for the 'autobot' process
pm2 logs autobot
```

**Telegram Notifications:**

The bot will send notifications to your configured Telegram chat for important events:
- **System Status**: Startup, shutdown, and critical errors.
- **Trades**: Entry, exit, and stop-loss updates.
- **Warnings**: Vetoed trades, connection issues, or other non-fatal problems.

## 4. System Architecture Overview

The bot follows an event-driven architecture, processing data through a pipeline:

1.  **Data Pipeline**: Collects real-time data from Binance via WebSockets.
2.  **Feature Engine**: Calculates technical indicators (RSI, EMAs, etc.) and determines the market regime (e.g., trend, range).
3.  **Decision Engine**: Evaluates a set of predefined trading rules based on the features and regime.
4.  **Risk Management**: Vetoes trades that violate risk parameters (e.g., max drawdown) and calculates a safe position size.
5.  **Execution Engine**: Places and manages orders on the Binance exchange.
6.  **State & Notifications**: Records state in Redis and sends alerts via Telegram.

For a more detailed explanation, please refer to the `AUTOBOT_SYSTEM_ANALYSIS.md` document.

## 5. Risk Management

The system includes several layers of risk management:

- **Pre-Trade Vetoes**: Before any trade, the system checks:
    - Maximum position size
    - Total number of open positions
    - System-wide maximum drawdown
    - Daily loss limits
- **Dynamic Position Sizing**: Position sizes are calculated based on market volatility (ATR), ensuring constant risk per trade.
- **Stop-Losses**: All positions are protected by an ATR-based stop-loss.

## 6. Security

- **API Keys**: Store your API keys in the `.env` file and **never** commit this file to version control.
- **IP Whitelisting**: For live trading, it is highly recommended to whitelist your server's IP address in your Binance account settings.
- **Run as Non-Root**: Do not run the application as the `root` user in a production environment.

---
*This document provides a general guide. For detailed technical information, refer to the source code and the system analysis document.*