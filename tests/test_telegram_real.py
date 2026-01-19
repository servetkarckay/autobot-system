import asyncio
import sys
sys.path.insert(0, '/root/autobot_system')

from telegram import Bot
from config.settings import settings

async def test_telegram_api():
    print('='*60)
    print('GERCEK TELEGRAM API TESTI')
    print('='*60)
    
    token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
    chat_id = settings.TELEGRAM_CHAT_ID
    
    print(f'Bot Token: {token[:15]}...')
    print(f'Chat ID: {chat_id}')
    print(f'Notifications Enabled: {settings.TELEGRAM_NOTIFICATIONS_ENABLED}')
    
    try:
        bot = Bot(token=token)
        
        print('[1] Bot bilgileri aliniyor...')
        bot_info = await bot.get_me()
        print(f'     Bot adi: @{bot_info.username}')
        print(f'     Bot ID: {bot_info.id}')
        
        print('[2] Test mesaji gonderiliyor...')
        message = await bot.send_message(
            chat_id=chat_id,
            text=f'TEST AUTOBOT\n\nTimestamp: {asyncio.get_event_loop().time()}\n\nEger bu mesaji goruyorsaniz Telegram calisiyor.'
        )
        print(f'     Mesaj ID: {message.message_id}')
        print('     MESAJ BASARIYLA GONDERILDI!')
        
        await bot.close()
        return True
        
    except Exception as e:
        print(f'     HATA: {type(e).__name__}: {e}')
        return False

if __name__ == '__main__':
    result = asyncio.run(test_telegram_api())
    print('='*60)
    if result:
        print('TELEGRAM API TEST: BASARILI')
    else:
        print('TELEGRAM API TEST: BASARISIZ')
    print('='*60)
