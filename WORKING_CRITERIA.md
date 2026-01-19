# AUTOBOT Working Criteria

## Definition of "System is Working"

### 1. System States

| State | Condition | Trading Allowed |
|-------|-----------|-----------------|
| RUNNING | All systems operational, data feed active | YES |
| DEGRADED | Non-critical issues (e.g., high latency) | YES (with caution) |
| SAFE_MODE | Critical issue, requires human intervention | NO |
| HALTED | Kill-switch triggered | NO |

### 2. Startup Requirements

For system to be considered "running", ALL of the following must be true:

- Configuration loaded successfully (no ValidationError)
- Redis connection established
- System state loaded (or created fresh)
- Static metadata loaded (or fetched from exchange)
- Telegram bot initialized (if enabled)
- WebSocket connections established

### 3. Runtime Requirements

System remains "working" when:

- Data feed heartbeat received within last 30 seconds
- Last API request succeeded (no authentication errors)
- Current drawdown < max drawdown limit
- Daily PnL > daily loss limit
- No CRITICAL level alerts in last hour

### 4. Self-Stop Conditions

System MUST stop trading and transition to SAFE_MODE when:

1. Data Loss: No data received for >30 seconds
2. API Failure: Authentication error or 5 consecutive failures
3. Drawdown Limit: Current drawdown >= MAX_DRAWDOWN_PCT (15%)
4. Daily Loss Limit: Daily PnL <= -DAILY_LOSS_LIMIT_PCT (-3%)
5. Kill-Switch: Manual kill-switch activated

### 5. Degradation Triggers

System degrades (reduces position sizes, tightens stops) when:

1. High Latency: API latency > 2x baseline
2. High Slippage: Slippage > MAX_SLIPPAGE_PCT (0.1%)
3. Partial Data: Some symbols missing data

### 6. Recovery Procedures

#### From Data Loss
1. WebSocket: Auto-reconnect with exponential backoff
2. If reconnect fails >10 attempts: SAFE_MODE
3. Manual intervention required if data does not resume

#### From API Failure
1. Retry with exponential backoff (1s, 2s, 4s, 8s, 16s)
2. If 5 consecutive failures: SAFE_MODE
3. Check API key validity, IP whitelist

#### From Safe Mode
1. Root cause analysis required
2. Manual fix / configuration change
3. Manual system restart required

### 7. Monitoring Checklist

Every 5 minutes, system should verify:
- Data feed latency < 500ms
- API latency < 1000ms
- Open positions match exchange
- Stop-loss orders active for all positions
- State persisted to Redis recently

Every 24 hours, system should:
- Send daily summary to Telegram
- Update static metadata from exchange
- Rotate log files
- Check adaptive parameters for drift

### 8. Acceptance Criteria

System is "production ready" when:

1. All core modules implemented and tested
2. State persistence verified (survives restart)
3. Risk veto chain tested with edge cases
4. Dry-run mode operates 24h without errors
5. Testnet mode completes 10 trades successfully
6. Kill-switch tested and functional
7. Telegram notifications working for all priorities
8. Logs are structured JSON and searchable
