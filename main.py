"""
AUTOBOT Main Application Entry Point
Event-driven autonomous trading system - ALL PERPETUAL USDT PAIRS (541 symbols)
"""
import asyncio
import signal
import sys
import logging
import requests

from config.settings import settings
from config.logging_config import setup_logging, logger
from core.data_pipeline.event_engine import TradingDecisionEngine
from core.notification.telegram_manager import notification_manager


def get_all_perpetual_symbols() -> list:
    """Fetch ALL perpetual USDT pairs from Binance Futures"""
    try:
        # Get exchangeInfo to find all perpetual contracts
        exchange_response = requests.get('https://fapi.binance.com/fapi/v1/exchangeInfo', timeout=10)
        exchange_response.raise_for_status()
        exchange_data = exchange_response.json()
        
        perpetual_symbols = []
        for s in exchange_data['symbols']:
            if (s['status'] == 'TRADING' 
                and s['quoteAsset'] == 'USDT' 
                and s['contractType'] == 'PERPETUAL'):
                perpetual_symbols.append(s['symbol'])
        
        logger.info(f"Fetched {len(perpetual_symbols)} ALL perpetual USDT pairs from Binance Futures")
        return sorted(perpetual_symbols)
    
    except Exception as e:
        logger.error(f"Failed to fetch symbols from Binance: {e}")
        # Fallback to default symbols
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


class AutobotSystem:
    """Main system orchestrator"""
    
    def __init__(self):
        self.logger = logger
        self._trading_engine = None
        self._running = False
        
        # Fetch ALL perpetual USDT pairs
        self.symbols = get_all_perpetual_symbols()
        logger.info(f"Trading {len(self.symbols)} symbols (ALL perpetual USDT pairs)")
        
    async def run(self):
        """Main system event loop"""
        
        self._running = True
        
        self.logger.info("="*60)
        self.logger.info("AUTOBOT SYSTEM STARTING")
        self.logger.info("="*60)
        self.logger.info(f"Environment: {settings.ENVIRONMENT}")
        self.logger.info(f"Mode: {"DRY RUN" if settings.is_dry_run else "LIVE TRADING"}")
        self.logger.info(f"Symbols: {len(self.symbols)} ALL perpetual USDT pairs")
        self.logger.info("="*60)
        
        # Send startup notification
        notification_manager.send_info(
            title="AUTOBOT Started",
            message=f"System started in {settings.ENVIRONMENT} mode\nScanning ALL {len(self.symbols)} perpetual USDT pairs",
            environment=settings.ENVIRONMENT,
            symbols=f"{len(self.symbols)} ALL pairs",
            dry_run=settings.is_dry_run
        )
        
        try:
            # Initialize and start trading engine
            self._trading_engine = TradingDecisionEngine()
            
            # Start event-driven trading
            await self._trading_engine.start(self.symbols)
            
        except asyncio.CancelledError:
            self.logger.info("Task cancelled")
        except Exception as e:
            self.logger.error(f"Fatal error in main loop: {e}", exc_info=True)
            notification_manager.send_critical(
                title="AUTOBOT Fatal Error",
                message=str(e)
            )
        finally:
            await self._shutdown()
    
    async def _shutdown(self):
        """Graceful shutdown"""
        
        self.logger.info("Shutting down AUTOBOT...")
        self._running = False
        
        # Disconnect WebSocket
        if self._trading_engine and self._trading_engine.ws_collector:
            await self._trading_engine.ws_collector.disconnect()
        
        notification_manager.send_info(
            title="AUTOBOT Stopped",
            message=f"Stopped scanning {len(self.symbols)} symbols"
        )


async def main():
    """Entry point"""
    
    # Setup logging
    setup_logging()
    
    # Create system instance
    system = AutobotSystem()
    
    # Setup signal handlers
    loop = asyncio.get_running_loop()
    
    def signal_handler():
        logger.info("Shutdown signal received")
        system._running = False
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    # Run system
    await system.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Program interrupted")
        sys.exit(0)
