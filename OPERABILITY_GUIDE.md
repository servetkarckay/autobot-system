# AUTOBOT Operability Guide

## Daily Operations

### Starting the System

```bash
# 1. Verify environment
cat .env | grep ENVIRONMENT

# 2. Check Redis is running
redis-cli ping

# 3. Start the system
python main.py
```

### Stopping the System

```bash
# Graceful stop (Ctrl+C)
# System will save state before exiting
```

### Monitoring

```bash
# View logs
tail -f logs/autobot.log

# Check system status
# (via Telegram heartbeat)
```

## Emergency Procedures

### 1. Data Feed Loss

Symptom: No market data updates

Action:
1. Check internet connectivity
2. Check Binance status page
3. Review logs for WebSocket errors
4. If unresolved > 5 min: System auto-enters SAFE_MODE

### 2. API Rate Limit

Symptom: 429 errors from Binance

Action:
1. Reduce polling frequency
2. System auto-queues requests
3. Wait 15 minutes before full operation

### 3. Drawdown Limit Breach

Symptom: Kill-switch triggered

Action:
1. System closes all positions automatically
2. System halts all trading
3. Manual review required before restart
4. Review trade history for cause

### 4. Stale Positions

Symptom: Open positions not matching system state

Action:
1. Query exchange for actual positions
2. Reconcile with system state
3. Manually update or close mismatched positions

## Maintenance Tasks

### Daily
- Review daily PnL summary
- Check for ERROR/WARNING notifications
- Verify open positions

### Weekly
- Review strategy performance
- Check adaptive parameter drift
- Verify log rotation working

### Monthly
- Update static metadata manually
- Review and rotate API keys
- Backup Redis state

## Configuration Changes

### Changing Parameters

1. Edit .env file
2. Restart system
3. Verify new settings in logs

### Adding a New Strategy

1. Implement strategy class in strategies/
2. Register in strategies/registry.py
3. Add rules to Decision Engine
4. Restart system
5. Monitor in DRY_RUN first

## Troubleshooting

Issue: Won not start - Check: .env exists? - Solution: Copy from .env.example
Issue: No orders - Check: DRY_RUN=true? - Solution: Set ENVIRONMENT=LIVE
Issue: No alerts - Check: Telegram token? - Solution: Check bot token in .env
Issue: Redis error - Check: Redis running? - Solution: systemctl start redis
Issue: High memory - Check: Log rotation? - Solution: Check logs/ size
