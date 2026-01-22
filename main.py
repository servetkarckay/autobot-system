import asyncio
import signal
import sys
import logging
import requests

from config.settings import settings
from config.logging_config import setup_logging, logger
from core.data_pipeline.event_engine import TradingDecisionEngine
from core.notification.telegram_manager import notification_manager


class AutobotSystem:
    def __init__(self):
        self.logger = logger
        self._trading_engine = None
        self._running = False
        self.symbols = ['1000PEPEUSDT']
        logger.info(f'Trading 1 symbol: 1000PEPEUSDT')
        
    async def run(self):
        self._running = True
        
        self.logger.info('='*60)
        self.logger.info('AUTOBOT SYSTEM STARTING')
        self.logger.info('='*60)
        self.logger.info(f'Environment: {settings.ENVIRONMENT}')
        self.logger.info(f'Mode: {"DRY RUN" if settings.is_dry_run else "LIVE TRADING"}')
        self.logger.info(f'Symbol: 1000PEPEUSDT')
        self.logger.info('='*60)
        
        notification_manager.send_info(
            title='AUTOBOT Started',
            message=f'System started in {settings.ENVIRONMENT} mode',
            environment=settings.ENVIRONMENT,
            symbols='1000PEPEUSDT',
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
        self.logger.info('Shutting down AUTOBOT...')
        self._running = False
        if self._trading_engine and self._trading_engine.ws_collector:
            await self._trading_engine.ws_collector.disconnect()
        notification_manager.send_info(
            title='AUTOBOT Stopped',
            message='Stopped scanning 1000PEPEUSDT'
        )


async def main():
    setup_logging()
    system = AutobotSystem()
    loop = asyncio.get_running_loop()
    
    def signal_handler():
        logger.info('Shutdown signal received')
        system._running = False
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    await system.run()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('Program interrupted')
        sys.exit(0)
