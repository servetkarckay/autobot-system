import sys
sys.path.insert(0, '/root/autobot_system')

from core.notification.telegram_manager import notification_manager

print('='*60)
print('DUZELTILMIS TELEGRAM TESTI')
print('='*60)

print('[1] INFO gonderiliyor...')
result1 = notification_manager.send_info(
    title='TEST INFO',
    message='Bu bir INFO test mesajidir.',
    test='info'
)
print(f'     Result: {result1}')

print('[2] CRITICAL gonderiliyor...')
result2 = notification_manager.send_critical(
    title='TEST CRITICAL',
    message='Bu bir CRITICAL test mesajidir.',
    test='critical'
)
print(f'     Result: {result2}')

print('='*60)
print('Telegram grubunu kontrol edin: -1002657942300')
print('='*60)
