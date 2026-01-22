#!/usr/bin/env python3
"""
AUTOBOT Credentials Validation Script
Tests if API keys are valid before rotation
"""
import sys
import os

# Add project to path
sys.path.insert(0, '/root/autobot_system')

def test_binance_connection():
    """Test Binance API connection"""
    try:
        from binance import AsyncClient
        from config.settings import settings
        
        print("Testing Binance API connection...")
        
        async def test():
            try:
                client = await AsyncClient.create(
                    api_key=settings.binance_api_key,
                    api_secret=settings.binance_api_secret,
                    testnet=settings.BINANCE_TESTNET
                )
                
                # Test server time (simple ping)
                server_time = await client.ping()
                print(f"  ✓ Binance API connection successful")
                print(f"    - Testnet: {settings.BINANCE_TESTNET}")
                print(f"    - Base URL: {settings.BINANCE_BASE_URL}")
                
                # Test account info
                account = await client.futures_account()
                print(f"    - Account access: ✓")
                print(f"    - Total Wallet Balance: {float(account['totalWalletBalance']):.2f} USDT")
                
                await client.close_connection()
                return True
            except Exception as e:
                print(f"  ✗ Binance API connection failed: {e}")
                return False
        
        import asyncio
        return asyncio.run(test())
        
    except ImportError as e:
        print(f"  ✗ Missing dependencies: {e}")
        return False
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def test_telegram_connection():
    """Test Telegram bot connection"""
    try:
        from telegram import Bot
        from config.settings import settings
        
        print("Testing Telegram bot connection...")
        
        async def test():
            try:
                bot = Bot(token=settings.telegram_bot_token)
                
                # Get bot info
                bot_info = await bot.get_me()
                print(f"  ✓ Telegram bot connection successful")
                print(f"    - Bot Name: @{bot_info.username}")
                print(f"    - Chat ID: {settings.TELEGRAM_CHAT_ID}")
                
                # Send test message
                from datetime import datetime, timezone
                msg = await bot.send_message(
                    chat_id=settings.TELEGRAM_CHAT_ID,
                    text=f"🔔 <b>CREDENTIALS TEST</b>\n✅ AUTOBOT connection test successful\n📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
                    parse_mode='HTML'
                )
                print(f"    - Test message sent: ✓")
                
                return True
            except Exception as e:
                print(f"  ✗ Telegram connection failed: {e}")
                return False
        
        import asyncio
        return asyncio.run(test())
        
    except ImportError as e:
        print(f"  ✗ python-telegram-bot not installed: {e}")
        return False
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def main():
    print("="*60)
    print("AUTOBOT CREDENTIALS VALIDATION")
    print("="*60)
    print()
    
    binance_ok = test_binance_connection()
    print()
    telegram_ok = test_telegram_connection()
    print()
    
    print("="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Binance API: {'✓ VALID' if binance_ok else '✗ INVALID'}")
    print(f"Telegram Bot: {'✓ VALID' if telegram_ok else '✗ INVALID'}")
    print()
    
    if binance_ok and telegram_ok:
        print("✓ All credentials are valid!")
        return 0
    else:
        print("✗ Some credentials are invalid. Please check:")
        if not binance_ok:
            print("  - Binance API keys")
        if not telegram_ok:
            print("  - Telegram bot token")
        return 1

if __name__ == '__main__':
    sys.exit(main())
