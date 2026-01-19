"""
AUTOBOT Main Application Entry Point
Event-driven autonomous trading system
"""
import asyncio
import signal
import sys
import logging

from config.settings import settings
from config.logging_config import setup_logging, logger
from core.data_pipeline.event_engine import TradingDecisionEngine
from core.notification.telegram_manager import notification_manager


class AutobotSystem:
    """Main system orchestrator"""
    
    def __init__(self):
        self.logger = logger
        self._trading_engine = None
        self._running = False
        
        # Symbols to trade
        self.symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
        
    async def run(self):
        """Main system event loop"""
        
        self._running = True
        
        self.logger.info("="*60)
        self.logger.info("AUTOBOT SYSTEM STARTING")
        self.logger.info("="*60)
        self.logger.info(f"Environment: {settings.ENVIRONMENT}")
        self.logger.info(f"Mode: {"DRY RUN" if settings.is_dry_run else "LIVE TRADING"}")
        self.logger.info(f"Symbols: {self.symbols}")
        self.logger.info("="*60)
        
        # Send startup notification
        notification_manager.send_info(
            title="AUTOBOT Started",
            message=f"System started in {settings.ENVIRONMENT} mode",
            environment=settings.ENVIRONMENT,
            symbols=", ".join(self.symbols),
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
            message="System shutdown complete"
        )
        
        self.logger.info("Shutdown complete")
    
    def stop(self):
        """Signal the system to stop"""
        self.logger.info("Stop signal received")
        self._running = False


async def main():
    """Application entry point"""
    
    system = AutobotSystem()
    
    # Setup signal handlers
    loop = asyncio.get_running_loop()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(system._shutdown()))
    
    await system.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
