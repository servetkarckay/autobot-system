#\!/bin/bash
# AUTOBOT 48-72 Hour Observation Period Monitoring
# Generates stability report every 10 minutes

LOG_FILE="/root/autobot_system/logs/autobot.log"
REPORT_DIR="/root/autobot_system/reports"
REPORT_FILE="$REPORT_DIR/stability_$(date +%Y%m%d_%H%M%S).txt"
CRITICAL_LATCH="/root/autobot_system/.critical_latch.json"

mkdir -p "$REPORT_DIR"

run_report() {
    {
        echo "╔════════════════════════════════════════════════════════════════╗"
        echo "║     AUTOBOT TESTNET - 48-72 HOUR OBSERVATION REPORT            ║"
        echo "╚════════════════════════════════════════════════════════════════╝"
        echo ""
        echo "Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")"
        echo "Environment: TESTNET (DRY_RUN=false)"
        echo ""
        
        # Get process info
        echo "## 1. PROCESS HEALTH"
        ps aux | grep "python main.py" | grep -v grep | awk "{printf \"PID: %s | CPU: %s%% | MEM: %s%% | RSS: %sMB | UPTIME: %s\n\", \$2, \$3, \$4, int(\$6/1024), \$10}"
        
        # Check WebSocket
        echo ""
        echo "## 2. WEBSOCKET"
        tail -100 "$LOG_FILE" | grep -c "WebSocket connected successfully" >/dev/null 2>&1 && echo "Status: CONNECTED" || echo "Status: CHECK NEEDED"
        
        # Event flow sample
        echo ""
        echo "## 3. RECENT EVENTS (last 5)"
        tail -500 "$LOG_FILE" | grep "KLINE CLOSE TRIGGER" | tail -5 | sed "s/.*\"\(timestamp..:..:..\).*\"\(message.*\)\".*/\1 - \2/"
        
        # Redis
        echo ""
        echo "## 4. REDIS"
        redis-cli -h 127.0.0.1 ping 2>/dev/null && echo "Status: CONNECTED" || echo "Status: ERROR"
        
        # Warning/Error rate
        echo ""
        echo "## 5. WARNING/ERROR RATE (last 500 lines)"
        WARN=$(tail -500 "$LOG_FILE" | grep -c "\"level\": \"WARNING\"" 2>/dev/null || echo 0)
        ERR=$(tail -500 "$LOG_FILE" | grep -c "\"level\": \"ERROR\"" 2>/dev/null || echo 0)
        echo "Warnings: $WARN | Errors: $ERR"
        
        # Critical latch
        echo ""
        echo "## 6. CRITICAL LATCH"
        if [ -f "$CRITICAL_LATCH" ] && [ -s "$CRITICAL_LATCH" ]; then
            cat "$CRITICAL_LATCH"
        else
            echo "{} (empty - no critical events latched)"
        fi
        
        echo ""
        echo "╔════════════════════════════════════════════════════════════════╗"
        echo "║                   END OF REPORT                                  ║"
        echo "╚════════════════════════════════════════════════════════════════╝"
    } > "$REPORT_FILE"
    
    echo "Report saved: $REPORT_FILE"
    cat "$REPORT_FILE"
}

# Run once immediately
run_report

# Schedule every 10 minutes
echo "Monitoring active. Next report in 10 minutes..."
while true; do
    sleep 600
    run_report
done
