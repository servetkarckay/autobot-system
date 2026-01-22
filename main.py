"""
AUTOBOT System - Main Entry Point v1.3

FIXES:
- Improved shutdown handling
- Added health check support
- Added graceful cleanup
- Better error handling
"""
import asyncio
import signal
import sys
import logging
import socket
from typing import Optional

from config.settings import setup_logging, logger, settings
from core.data_pipeline.event_engine import TradingDecisionEngine
from core.notifier import notification_manager
from core.state_manager import state_manager


class AutobotSystem:
    def __init__(self):
        self.logger = logger
        self._trading_engine = None
        self._running = False
        self._shutdown_event = asyncio.Event()
        self.symbols = settings.TRADING_SYMBOLS
        logger.info(f'Trading {len(self.symbols)} symbols: {", ".join(self.symbols)}')

    def health_check(self) -> dict:
        """Return system health status"""
        redis_ok = state_manager.is_connected()
        engine_running = self._trading_engine is not None and self._trading_engine.ws_collector.is_connected if self._trading_engine else False
        
        return {
            "status": "RUNNING" if self._running else "STOPPED",
            "environment": settings.ENVIRONMENT,
            "mode": "DRY_RUN" if settings.is_dry_run else "LIVE",
            "symbols": self.symbols,
            "redis_connected": redis_ok,
            "websocket_connected": engine_running,
            "uptime_seconds": 0  # Could add uptime tracking
        }

    async def run(self):
        self._running = True
        
        self.logger.info('='*60)
        self.logger.info('AUTOBOT SYSTEM STARTING')
        self.logger.info('='*60)
        self.logger.info(f'Environment: {settings.ENVIRONMENT}')
        self.logger.info(f'Mode: {"DRY RUN" if settings.is_dry_run else "LIVE TRADING"}')
        self.logger.info(f'Symbols: {", ".join(self.symbols)}')
        self.logger.info('='*60)
        
        notification_manager.send_info(
            title='AUTOBOT Started',
            message=f'System started in {settings.ENVIRONMENT} mode',
            environment=settings.ENVIRONMENT,
            symbols=", ".join(self.symbols),
            dry_run=settings.is_dry_run
        )
        
        try:
            self._trading_engine = TradingDecisionEngine()
            await self._trading_engine.start(self.symbols)
        except asyncio.CancelledError:
            self.logger.info('Task cancelled')
        except Exception as e:
            self.logger.error(f'Fatal error: {e}', exc_info=True)
            notification_manager.send_critical(
                title='AUTOBOT Fatal Error',
                message=str(e)
            )
        finally:
            await self._shutdown()

    async def _shutdown(self):
        """Graceful shutdown with proper cleanup"""
        self.logger.info('Shutting down AUTOBOT...')
        self._running = False
        
        # Stop trading engine first
        if self._trading_engine:
            try:
                if hasattr(self._trading_engine, 'ws_collector') and self._trading_engine.ws_collector:
                    await asyncio.wait_for(self._trading_engine.ws_collector.disconnect(), timeout=10.0)
            except asyncio.TimeoutError:
                self.logger.warning('WebSocket disconnect timed out')
            except Exception as e:
                self.logger.error(f'Error disconnecting WebSocket: {e}')
        
        # Cleanup state manager
        try:
            state_manager.cleanup()
        except Exception as e:
            self.logger.error(f'Error cleaning up state manager: {e}')
        
        # Cleanup notification manager
        try:
            notification_manager.shutdown()
        except Exception as e:
            self.logger.error(f'Error shutting down notification manager: {e}')
        
        notification_manager.send_info(
            title='AUTOBOT Stopped',
            message=f'Stopped scanning {", ".join(self.symbols)}'
        )
        
        self._shutdown_event.set()


async def main():
    setup_logging()
    system = AutobotSystem()
    loop = asyncio.get_running_loop()
    
    def signal_handler():
        logger.info('Shutdown signal received')
        if system._running:
            asyncio.create_task(system._shutdown())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        await system.run()
    except KeyboardInterrupt:
        logger.info('Program interrupted')
    finally:
        # Wait for shutdown to complete
        await system._shutdown_event.wait()
        sys.exit(0)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('Program interrupted')
        sys.exit(0)
    except Exception as e:
        logger.error(f'Unhandled exception: {e}', exc_info=True)
        sys.exit(1)
