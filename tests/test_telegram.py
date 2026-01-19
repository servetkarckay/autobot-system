"""
TELEGRAM BİLDİRİM TESTİ
"""
import sys
import os
sys.path.insert(0, '/root/autobot_system')
os.chdir('/root/autobot_system')

from core.notification.telegram_manager import notification_manager

print("="*60)
print("TELEGRAM BİLDİRİM TESTİ")
print("="*60)

print("\n[1] INFO bildirimi gönderiliyor...")
notification_manager.send_info(
    title="TEST INFO",
    message="Bu bir test bilgisidir.",
    test="info_test"
)

print("[2] WARNING bildirimi gönderiliyor...")
notification_manager.send_warning(
    title="TEST WARNING",
    message="Bu bir test uyarısıdır.",
    test="warning_test"
)

print("[3] ERROR bildirimi gönderiliyor...")
notification_manager.send_error(
    title="TEST ERROR",
    message="Bu bir test hatasıdır.",
    test="error_test"
)

print("[4] CRITICAL bildirimi gönderiliyor...")
notification_manager.send_critical(
    title="TEST CRITICAL",
    message="Bu bir test critical bildirimidir.",
    test="critical_test"
)

print("\n" + "="*60)
print("Telegram testleri tamamlandı.")
print("Telegram grubunu kontrol edin: -1002657942300")
print("="*60)
