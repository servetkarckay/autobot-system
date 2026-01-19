#!/bin/bash
LOG_FILE="/root/autobot_system/logs/autobot.log"
METRICS_FILE="/root/autobot_system/logs/metrics_$(date +%Y%m%d_%H%M%S).log"

echo "AUTOBOT 6-METRIC MONITORING"
echo "Start: $(date -u +%Y-%m-%d\ %H:%M:%S UTC)"
echo "=================================================="
echo ""

while true; do
    echo "[$(date -u +%H:%M:%S UTC)] METRIC CHECK"
    
    # 1. Process & Memory
    PID=$(pgrep -f 'python main.py' | head -1)
    if [ -n "$PID" ]; then
        RSS_KB=$(ps -o rss= -p $PID 2>/dev/null || echo "0")
        RSS_MB=$(echo "scale=1; $RSS_KB/1024" | bc)
        MEM_PCT=$(ps -o %mem= -p $PID 2>/dev/null || echo "0")
        UPTIME=$(ps -o etime= -p $PID 2>/dev/null || echo "unknown")
        echo "  [1] Process: PID=$PID, MEM=${RSS_MB}MB (${MEM_PCT}%), UPTIME=$UPTIME"
        
        # Memory trend check (ARTIYOR UYARI)
        if [ -f /root/autobot_system/.last_rss ]; then
            LAST_RSS=$(cat /root/autobot_system/.last_rss)
            if [ $RSS_KB -gt $LAST_RSS ]; then
                GROWTH=$(echo "scale=1; ($RSS_KB - $LAST_RSS)/1024" | bc)
                echo "     ⚠️  MEMORY +${GROWTH}MB since last check"
            fi
        fi
        echo $RSS_KB > /root/autobot_system/.last_rss
    else
        echo "  [1] Process: NOT RUNNING"
    fi
    
    # 2. WebSocket (log analysis)
    WS_CONNECTED=$(tail -100 "$LOG_FILE" 2>/dev/null | grep -c "WebSocket connected successfully" || echo "0")
    WS_ERRORS=$(tail -100 "$LOG_FILE" 2>/dev/null | grep -c "WebSocket.*Error" || echo "0")
    echo "  [2] WebSocket: Connected=$WS_CONNECTED (last 100 logs), Errors=$WS_ERRORS"
    
    # 3. Latency (p95/p99 from logs)
    LATENCY_P95=$(tail -1000 "$LOG_FILE" 2>/dev/null | grep -o 'latency=[0-9.]*' | cut -d= -f2 | awk '$1>p95{print $1"\n"}' | sort -n | awk 'NR==95{print "\ms"; exit}')
    if [ -n "$LATENCY_P95" ]; then
        LATENCY_INT=$(echo $LATENCY_P95 | cut -d. -f1)
        if [ $(echo "$LATENCY_INT > 500" | bc) -eq 1 ]; then
            echo "  [3] Latency: p95=$LATENCY_P95 ⚠️  HIGH LATENCY"
        else
            echo "  [3] Latency: p95=$LATENCY_P95"
        fi
    else
        echo "  [3] Latency: No data yet"
    fi
    
    # 4. Redis check
    REDIS_PING=$(redis-cli ping 2>/dev/null || echo "FAILED")
    REDIS_KEYS=$(redis-cli KEYS "autobot:*" 2>/dev/null | wc -l || echo "0")
    echo "  [4] Redis: $REDIS_PING, Keys=$REDIS_KEYS"
    
    # 5. WARNING rate (last 1000 logs)
    WARN_RATE=$(tail -1000 "$LOG_FILE" 2>/dev/null | grep -c '"level": "WARNING"' || echo "0")
    WARN_PERC=$(echo "scale=1; $WARN_RATE*100/1000" | bc)
    echo "  [5] Warnings: $WARN_RATE/1000 logs (${WARN_PERC}%)"
    
    # 6. Telegram status
    TG_SENT=$(tail -100 "$LOG_FILE" 2>/dev/null | grep -c "TELEGRAM SENT" || echo "0")
    TG_FAIL=$(tail -100 "$LOG_FILE" 2>/dev/null | grep -c "Telegram.*error" || echo "0")
    echo "  [6] Telegram: Sent=$TG_SENT, Errors=$TG_FAIL (last 100 logs)"
    
    echo ""
    sleep 300  # 5 dakikada bir
done
