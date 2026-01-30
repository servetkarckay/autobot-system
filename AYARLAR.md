# AUTOBOT Sistem Ayarları - Tam Dökümantasyon

## 📁 Ayar Dosyaları ve Konumları

| Dosya | Konum | Açıklama |
|-------|-------|----------|
| `.env` | `/root/autobot_system/.env` | **ANA** ayar dosyası |
| `settings.py` | `config/settings.py` | Ayar sınıfları |

---

## 🔧 Ayarları Değiştirme

```bash
ssh root@116.203.73.93
cd /root/autobot_system
nano .env
pm2 restart autobot
```

---

## 📋 TÜM AYARLAR

### Binance
| Ayar | Varsayılan | Açıklama |
|------|-----------|----------|
| BINANCE_TESTNET | true | Testnet (true) / Live (false) |
| BINANCE_API_KEY | - | API Key |
| BINANCE_API_SECRET | - | API Secret |

### Trading
| Ayar | Varsayılan | Açıklama |
|------|-----------|----------|
| TRADING_SYMBOLS | ZECUSDT | Coin listesi |
| MAX_POSITIONS | 1 | Max açık pozisyon |
| LEVERAGE | 10 | Kaldıraç (1-125) |
| ENVIRONMENT | DRY_RUN | DRY_RUN / TESTNET / LIVE |

### Trailing Stop
| Ayar | Varsayılan | Açıklama |
|------|-----------|----------|
| TRAILING_STOP_ACTIVATION_PCT | 2.0 | Başlama yüzdesi |
| BREAK_EVEN_PCT | 2.0 | Break-even yüzdesi |
| TRAILING_STOP_RATE | 0.5 | Kaydırma oranı |

---

## ⚡ Hızlı Komutlar

```bash
# Ayarları görüntüle
cat .env

# Bot restart
pm2 restart autobot

# Logları izle
pm2 logs autobot
```
