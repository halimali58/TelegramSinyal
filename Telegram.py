import pandas as pd
import numpy as np
import yfinance as yf
import requests
from datetime import datetime, timedelta
from pytz import timezone
import time
import sys

# --- Türkçe Ay İsimleri ---
ay_isimleri = {
    1: 'Ocak', 2: 'Şubat', 3: 'Mart', 4: 'Nisan', 5: 'Mayıs', 6: 'Haziran',
    7: 'Temmuz', 8: 'Ağustos', 9: 'Eylül', 10: 'Ekim', 11: 'Kasım', 12: 'Aralık'
}

# --- Telegram Bot Yapılandırması ---
BOT_TOKEN = "7656972647:AAFIgK_-gwpgWF_PMCCvQWVHhFO2GjJZ_uA"
CHAT_ID = 5082522947
TR_TZ = timezone('Europe/Istanbul')

# Telegram'a mesaj gönderme fonksiyonu
def telegram_mesaj_gonder(mesaj):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    veri = {
        "chat_id": CHAT_ID,
        "text": mesaj,
        "parse_mode": "Markdown"
    }
    try:
        yanit = requests.post(url, json=veri)
        if yanit.status_code != 200:
            print(f"Telegram'a mesaj gönderilemedi: {yanit.text}")
        else:
            print(f"Telegram'a mesaj gönderildi: {mesaj}")
    except Exception as e:
        print(f"Telegram mesajı gönderilirken hata oluştu: {e}")

# Supertrend indikatörünü hesaplama
def supertrend_hesapla(df, atr_periyot=10, faktor=3.0, atr_cizgi=1.5):
    df = df.copy()
    df['TR'] = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift()).abs(),
        (df['Low'] - df['Close'].shift()).abs()
    ], axis=1).max(axis=1)
    df['ATR'] = df['TR'].rolling(window=atr_periyot).mean()
    df['hl2'] = (df['High'] + df['Low']) / 2
    df['ust_bant'] = df['hl2'] + faktor * df['ATR']
    df['alt_bant'] = df['hl2'] - faktor * df['ATR']

    n = len(df)
    yon = np.zeros(n, dtype=int)
    supertrend = np.zeros(n)

    kapanis = df['Close'].values
    ust_bant = df['ust_bant'].values
    alt_bant = df['alt_bant'].values

    if n > 0 and not np.isnan(alt_bant[0]):
        supertrend[0] = alt_bant[0]
        yon[0] = 1

    for i in range(1, n):
        kapanis_i = kapanis[i]
        supertrend_onceki = supertrend[i - 1]
        yon_onceki = yon[i - 1]
        ust_bant_i = ust_bant[i]
        alt_bant_i = alt_bant[i]

        if kapanis_i > supertrend_onceki:
            yon[i] = 1
        elif kapanis_i < supertrend_onceki:
            yon[i] = -1
        else:
            yon[i] = yon_onceki

        if yon[i] == 1:
            supertrend[i] = max(alt_bant_i, supertrend_onceki)
        else:
            supertrend[i] = min(ust_bant_i, supertrend_onceki)

    df['supertrend'] = supertrend
    df['yon'] = yon
    df['ust_atr_cizgi'] = df['supertrend'] + atr_cizgi * df['ATR']
    df['alt_atr_cizgi'] = df['supertrend'] - atr_cizgi * df['ATR']
    return df

# Son barın sinyal yönünü belirleme
def son_sinyal_al(df, min_onay_bar=3, max_onay_bar=10):
    yon = df['yon'].values
    kapanis = df['Close'].values
    supertrend = df['supertrend'].values
    hacim = df['Volume'].values
    bar_indeks = np.arange(len(df))

    yesile_don = np.insert((yon[1:] < yon[:-1]), 0, False)
    kirmiziya_don = np.insert((yon[1:] > yon[:-1]), 0, False)

    son_yesile_don_bar = bar_indeks[yesile_don][-1] if np.any(yesile_don) else np.nan
    son_kirmiziya_don_bar = bar_indeks[kirmiziya_don][-1] if np.any(kirmiziya_don) else np.nan

    yesilden_beri_bar = len(df) - 1 - son_yesile_don_bar if not np.isnan(son_yesile_don_bar) else np.nan
    kirmizidan_beri_bar = len(df) - 1 - son_kirmiziya_don_bar if not np.isnan(son_kirmiziya_don_bar) else np.nan

    son_sinyal = None
    if not np.isnan(son_yesile_don_bar) and min_onay_bar <= yesilden_beri_bar <= max_onay_bar:
        onay_al = True
        for i in range(min_onay_bar):
            idx = int(len(df) - 1 - i)
            if idx < 0 or kapanis[idx] <= supertrend[idx]:
                onay_al = False
                break
        if onay_al and yesile_don[int(son_yesile_don_bar)]:
            hacim_ortalama = np.mean(hacim[-10:]) if len(hacim) >= 10 else 0
            if hacim[int(son_yesile_don_bar)] > hacim_ortalama:
                son_sinyal = "AL"

    if not np.isnan(son_kirmiziya_don_bar) and min_onay_bar <= kirmizidan_beri_bar <= max_onay_bar:
        onay_sat = True
        for i in range(min_onay_bar):
            idx = int(len(df) - 1 - i)
            if idx < 0 or kapanis[idx] >= supertrend[idx]:
                onay_sat = False
                break
        if onay_sat and kirmiziya_don[int(son_kirmiziya_don_bar)]:
            hacim_ortalama = np.mean(hacim[-10:]) if len(hacim) >= 10 else 0
        if hacim[int(son_kirmiziya_don_bar)] > hacim_ortalama:
            son_sinyal = "SAT"

    return son_sinyal, son_yesile_don_bar, son_kirmiziya_don_bar, yesilden_beri_bar, kirmizidan_beri_bar

# Türkçe tarih formatı oluşturma
def turkce_tarih_formatla(tarih):
    if tarih is None or pd.isna(tarih):
        return "Bilinmiyor"
    dt = pd.to_datetime(tarih).astimezone(TR_TZ)
    return f"{dt.day} {ay_isimleri[dt.month]} {dt.year}"

# Sinyal oluşturma
def sinyaller_al(df, min_onay_bar=3, max_onay_bar=10, yakinlik_esigi=0.05, stop_loss_faktor=1.0):
    son_sinyal, son_yesile_don_bar, son_kirmiziya_don_bar, yesilden_beri_bar, kirmizidan_beri_bar = son_sinyal_al(df, min_onay_bar, max_onay_bar)
    son_al_sinyal = None
    son_sat_sinyal = None
    son_al_satir = None
    son_sat_satir = None
    alarm_rengi = None
    stop_loss_fiyat = np.nan
    sinyal_tarihi = None

    yon = df['yon'].values
    kapanis = df['Close'].values
    supertrend = df['supertrend'].values
    yuksek = df['High'].values
    dusuk = df['Low'].values
    atr = df['ATR'].values

    geriye_bakma_periyodu = min(10, len(df))
    son_dip = np.min(dusuk[-geriye_bakma_periyodu:]) if len(dusuk) >= geriye_bakma_periyodu else np.nan
    son_tepe = np.max(yuksek[-geriye_bakma_periyodu:]) if len(yuksek) >= geriye_bakma_periyodu else np.nan

    gecerli_al = False
    al_fiyat = np.nan
    if son_sinyal == "AL" and not np.isnan(son_yesile_don_bar):
        if min_onay_bar <= yesilden_beri_bar <= max_onay_bar:
            onay_al = True
            for i in range(min_onay_bar):
                idx = int(len(df) - 1 - i)
                if idx < 0 or kapanis[idx] <= supertrend[idx]:
                    onay_al = False
                    break
            gecerli_al = onay_al
            al_fiyat = son_dip if gecerli_al and not np.isnan(son_dip) else kapanis[int(son_yesile_don_bar)]
            sinyal_tarihi = turkce_tarih_formatla(df['Date'].iloc[int(son_yesile_don_bar)]) if gecerli_al else None

    gecerli_sat = False
    sat_fiyat = np.nan
    if son_sinyal == "SAT" and not np.isnan(son_kirmiziya_don_bar):
        if min_onay_bar <= kirmizidan_beri_bar <= max_onay_bar:
            onay_sat = True
            for i in range(min_onay_bar):
                idx = int(len(df) - 1 - i)
                if idx < 0 or kapanis[idx] >= supertrend[idx]:
                    onay_sat = False
                    break
            gecerli_sat = onay_sat
            sat_fiyat = son_tepe if gecerli_sat and not np.isnan(son_tepe) else kapanis[int(son_kirmiziya_don_bar)]
            sinyal_tarihi = turkce_tarih_formatla(df['Date'].iloc[int(son_kirmiziya_don_bar)]) if gecerli_sat else None

    guncel_kapanis = kapanis[-1] if len(kapanis) > 0 else np.nan
    sembol = df['Symbol'].iloc[0]
    son_atr = atr[-1] if len(atr) > 0 else np.nan

    def skaler_yap(deger):
        if isinstance(deger, (np.ndarray, pd.Series)):
            return deger.item() if deger.size == 1 else np.nan
        return deger if not np.isnan(deger) else np.nan

    al_fiyat = skaler_yap(al_fiyat)
    sat_fiyat = skaler_yap(sat_fiyat)
    guncel_kapanis = skaler_yap(guncel_kapanis)
    son_atr = skaler_yap(son_atr)

    if gecerli_al and not np.isnan(al_fiyat) and not np.isnan(son_atr):
        stop_loss_fiyat = al_fiyat - (son_atr * stop_loss_faktor)
        stop_loss_fiyat = max(0, stop_loss_fiyat)
    elif gecerli_sat and not np.isnan(sat_fiyat) and not np.isnan(son_atr):
        stop_loss_fiyat = sat_fiyat + (son_atr * stop_loss_faktor)

    print(f"\nHisse: {sembol}")
    print(f"Son sinyal: {son_sinyal}")
    print(f"Yeşilden beri bar: {yesilden_beri_bar}")
    print(f"Kırmızıdan beri bar: {kirmizidan_beri_bar}")
    print(f"AL fiyatı: {f'{al_fiyat:.2f}'.replace('.', ',') if not np.isnan(al_fiyat) else 'Yok'}")
    print(f"SAT fiyatı: {f'{sat_fiyat:.2f}'.replace('.', ',') if not np.isnan(sat_fiyat) else 'Yok'}")
    print(f"Güncel kapanış: {f'{guncel_kapanis:.2f}'.replace('.', ',') if not np.isnan(guncel_kapanis) else 'Yok'}")
    print(f"Stop-loss fiyatı: {f'{stop_loss_fiyat:.2f}'.replace('.', ',') if not np.isnan(stop_loss_fiyat) else 'Yok'}")
    print(f"Yakınlık eşiği: {f'{yakinlik_esigi:.2f}'.replace('.', ',')}")
    print(f"Sinyal Tarih: {sinyal_tarihi if sinyal_tarihi else 'Yok'}")
    print(f"Son dip: {f'{son_dip:.2f}'.replace('.', ',') if not np.isnan(son_dip) else 'Yok'}")
    print(f"Son tepe: {f'{son_tepe:.2f}'.replace('.', ',') if not np.isnan(son_tepe) else 'Yok'}")

    if gecerli_al and not np.isnan(al_fiyat) and not np.isnan(guncel_kapanis):
        if guncel_kapanis <= al_fiyat * (1 + yakinlik_esigi):
            fiyat_str = f"{al_fiyat:.2f}".replace('.', ',')
            stop_loss_str = f"{stop_loss_fiyat:.2f}".replace('.', ',') if not np.isnan(stop_loss_fiyat) else 'Yok'
            guncel_kapanis_str = f"{guncel_kapanis:.2f}".replace('.', ',')
            son_al_sinyal = f"{sembol} - AL => {fiyat_str} - Son: {guncel_kapanis_str} - Stop-loss: {stop_loss_str}"
            son_al_satir = [sembol, "AL", fiyat_str, guncel_kapanis_str, 'yesil', stop_loss_str, sinyal_tarihi]
            alarm_rengi = 'yesil'
            print(f"AL sinyali onaylandı: {son_al_sinyal}")
        else:
            fiyat_str = f"{al_fiyat:.2f}".replace('.', ',')
            stop_loss_str = f"{stop_loss_fiyat:.2f}".replace('.', ',') if not np.isnan(stop_loss_fiyat) else 'Yok'
            guncel_kapanis_str = f"{guncel_kapanis:.2f}".replace('.', ',')
            son_al_sinyal = f"{sembol} - AL => {fiyat_str} - Son: {guncel_kapanis_str} - Stop-loss: {stop_loss_str}"
            son_al_satir = [sembol, "AL", fiyat_str, guncel_kapanis_str, None, stop_loss_str, sinyal_tarihi]
            print(f"AL sinyali var ancak yakınlık eşiği sağlanmadı: {son_al_sinyal}")

    if gecerli_sat and not np.isnan(sat_fiyat) and not np.isnan(guncel_kapanis):
        if guncel_kapanis >= sat_fiyat * (1 - yakinlik_esigi):
            fiyat_str = f"{sat_fiyat:.2f}".replace('.', ',')
            stop_loss_str = f"{stop_loss_fiyat:.2f}".replace('.', ',') if not np.isnan(stop_loss_fiyat) else 'Yok'
            guncel_kapanis_str = f"{guncel_kapanis:.2f}".replace('.', ',')
            son_sat_sinyal = f"{sembol} - SAT => {fiyat_str} - Son: {guncel_kapanis_str} - Stop-loss: {stop_loss_str}"
            son_sat_satir = [sembol, "SAT", fiyat_str, guncel_kapanis_str, 'kirmizi', stop_loss_str, sinyal_tarihi]
            alarm_rengi = 'kirmizi'
            print(f"SAT sinyali onaylandı: {son_sat_sinyal}")
        else:
            fiyat_str = f"{sat_fiyat:.2f}".replace('.', ',')
            stop_loss_str = f"{stop_loss_fiyat:.2f}".replace('.', ',') if not np.isnan(stop_loss_fiyat) else 'Yok'
            guncel_kapanis_str = f"{guncel_kapanis:.2f}".replace('.', ',')
            son_sat_sinyal = f"{sembol} - SAT => {fiyat_str} - Son: {guncel_kapanis_str} - Stop-loss: {stop_loss_str}"
            son_sat_satir = [sembol, "SAT", fiyat_str, guncel_kapanis_str, None, stop_loss_str, sinyal_tarihi]
            print(f"SAT sinyali var ancak yakınlık eşiği sağlanmadı: {son_sat_sinyal}")

    return son_al_sinyal, son_sat_sinyal, son_al_satir, son_sat_satir, alarm_rengi

# 60 dakikalık verileri 2 saatlik verilere dönüştürme
def veriyi_2_saatlik_yap(df):
    df = df.copy()
    try:
        if not pd.api.types.is_datetime64_any_dtype(df['Date']):
            df['Date'] = pd.to_datetime(df['Date'])

        if df['Date'].dt.tz is None:
            df['Date'] = df['Date'].dt.tz_localize(TR_TZ)
        else:
            df['Date'] = df['Date'].dt.tz_convert(TR_TZ)

        gerekli_sutunlar = ['Open', 'High', 'Low', 'Close', 'Volume', 'Symbol']
        if not all(col in df.columns for col in gerekli_sutunlar):
            eksik_sutunlar = [col for col in gerekli_sutunlar if col not in df.columns]
            print(f"2 saatlik veri dönüşümünde eksik sütunlar: {eksik_sutunlar}")
            return pd.DataFrame()

        df.set_index('Date', inplace=True)
        df_filtered = df[(df.index.hour >= 9) & (df.index.hour < 18)]

        if df_filtered.empty:
            print("Filtrelenmiş veri boş: İşlem saatlerinde veri bulunamadı.")
            return pd.DataFrame()

        df_2h = df_filtered.resample('2h', closed='left', label='left').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum',
            'Symbol': 'last'
        }).dropna()

        df_2h.reset_index(inplace=True)
        df_2h['Date'] = df_2h['Date'].dt.tz_convert(TR_TZ)
        print(f"2 saatlik veri oluşturuldu: {len(df_2h)} satır")
        return df_2h
    except Exception as e:
        print(f"2 saatlik veri dönüşümünde hata: {e}")
        return pd.DataFrame()

# Sinyal takip sözlüğü
gonderilen_sinyaller = {}

# BIST hisseleri için tarama fonksiyonu
def bist_hisseleri_tara(hisseler, baslangic_tarihi, bitis_tarihi, min_onay_bar=3, max_onay_bar=10, yakinlik_esigi=0.05, stop_loss_faktor=1.0, interval='60m', gunluk_fallback=True):
    global gonderilen_sinyaller
    sinyaller = []

    for hisse in hisseler:
        try:
            ticker = hisse
            print(f"{hisse} için veri çekiliyor...")
            df = yf.download(ticker, start=baslangic_tarihi, end=bitis_tarihi, interval=interval, progress=False)
            if df.empty:
                print(f"Veri alınamadı: {hisse} (Boş veri seti)")
                if gunluk_fallback:
                    print(f"Günlük veriye geçiliyor: {hisse}")
                    df = yf.download(ticker, start=baslangic_tarihi, end=bitis_tarihi, interval='1d', progress=False)
                    if df.empty:
                        print(f"Günlük veri de alınamadı: {hisse}")
                        continue

            gerekli_sutunlar = ['Open', 'High', 'Low', 'Close', 'Volume']
            if not all(col in df.columns for col in gerekli_sutunlar):
                print(f"Veri alınamadı: {hisse} (Eksik sütunlar: {', '.join(set(gerekli_sutunlar) - set(df.columns))})")
                continue

            df.reset_index(inplace=True)
            df['Symbol'] = hisse.replace('.IS', '')

            if 'Datetime' in df.columns:
                df.rename(columns={'Datetime': 'Date'}, inplace=True)
            elif 'Date' not in df.columns:
                print(f"Uygun tarih sütunu bulunamadı: {hisse}")
                continue

            if df['Date'].dt.tz is None:
                df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(TR_TZ)
            else:
                df['Date'] = df['Date'].dt.tz_convert(TR_TZ)

            df = df[['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Symbol']]

            if interval == '60m':
                df_2h = veriyi_2_saatlik_yap(df)
                if df_2h.empty:
                    print(f"2 saatlik veri oluşturulamadı: {hisse}")
                    if gunluk_fallback:
                        print(f"Günlük veriye geçiliyor: {hisse}")
                        df = yf.download(ticker, start=baslangic_tarihi, end=bitis_tarihi, interval='1d', progress=False)
                        if df.empty:
                            print(f"Günlük veri de alınamadı: {hisse}")
                            continue
                        df.reset_index(inplace=True)
                        if df['Date'].dt.tz is None:
                            df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(TR_TZ)
                        else:
                            df['Date'] = df['Date'].dt.tz_convert(TR_TZ)
                        df['Symbol'] = hisse.replace('.IS', '')
                        df = df[['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Symbol']]
                else:
                    df = df_2h

            print(f"{hisse} için veri alındı: {len(df)} satır")

            if len(df) < min_onay_bar:
                print(f"Yetersiz veri: {hisse} için sadece {len(df)} satır mevcut, minimum {min_onay_bar} gerekli.")
                continue

            df = supertrend_hesapla(df)

            if df['supertrend'].isna().all():
                print(f"Supertrend hesaplanamadı: {hisse} için geçerli veri yok.")
                continue

            son_al_sinyal, son_sat_sinyal, son_al_satir, son_sat_satir, alarm_rengi = sinyaller_al(
                df, min_onay_bar, max_onay_bar, yakinlik_esigi, stop_loss_faktor
            )

            if son_al_satir and son_al_satir[4] == 'yesil':
                sinyal_anahtari = f"{hisse}_AL_{son_al_satir[6] if son_al_satir[6] else turkce_tarih_formatla(datetime.now(TR_TZ))}"
                if sinyal_anahtari not in gonderilen_sinyaller:
                    sinyal_fiyati = son_al_satir[2]
                    stop_loss_fiyati = son_al_satir[5]
                    guncel_kapanis = son_al_satir[3]
                    tarih = son_al_satir[6] if son_al_satir[6] else turkce_tarih_formatla(datetime.now(TR_TZ))

                    sinyaller.append({
                        'SİNYAL': 'AL',
                        'HİSSE': hisse.replace('.IS', ''),
                        'SİNYAL FİYATI': sinyal_fiyati,
                        'GÜNCEL KAPANIS': guncel_kapanis,
                        'STOP-LOSS': stop_loss_fiyati,
                        'SİNYAL TARİH': tarih
                    })
                    print(f"AL sinyali kaydedildi: {hisse}")
                    telegram_mesaj = (
                        f"🟢 *AL Sinyali* 🟢\n"
                        f"📊 *Hisse:* {hisse.replace('.IS', '')}\n"
                        f"📈 *Sinyal Fiyatı:* {sinyal_fiyati}\n"
                        f"💰 *Güncel Kapanış:* {guncel_kapanis}\n"
                        f"🚖 *Stop-loss:* {stop_loss_fiyati}\n"
                        f"🕒 *Sinyal Tarih:* {tarih}\n"
                        f"📅 *Tarih:* {datetime.now(TR_TZ).strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"🔸 *Grafik:* https://tr.tradingview.com/chart/iKuKZamY/?symbol=BIST%3A{hisse.replace('.IS', '')}"
                    )
                    telegram_mesaj_gonder(telegram_mesaj)
                    gonderilen_sinyaller[sinyal_anahtari] = True

            if son_sat_satir and son_sat_satir[4] == 'kirmizi':
                sinyal_anahtari = f"{hisse}_SAT_{son_sat_satir[6] if son_sat_satir[6] else turkce_tarih_formatla(datetime.now(TR_TZ))}"
                if sinyal_anahtari not in gonderilen_sinyaller:
                    sinyal_fiyati = son_sat_satir[2]
                    stop_loss_fiyati = son_sat_satir[5]
                    guncel_kapanis = son_sat_satir[3]
                    tarih = son_sat_satir[6] if son_sat_satir[6] else turkce_tarih_formatla(datetime.now(TR_TZ))

                    sinyaller.append({
                        'SİNYAL': 'SAT',
                        'HİSSE': hisse.replace('.IS', ''),
                        'SİNYAL FİYATI': sinyal_fiyati,
                        'GÜNCEL KAPANIS': guncel_kapanis,
                        'STOP-LOSS': stop_loss_fiyati,
                        'SİNYAL TARİH': tarih
                    })
                    print(f"SAT sinyali kaydedildi: {hisse}")
                    telegram_mesaj = (
                        f"🔴 *SAT Sinyali* 🔴\n"
                        f"📊 *Hisse:* {hisse.replace('.IS', '')}\n"
                        f"📉 *Sinyal Fiyatı:* {sinyal_fiyati}\n"
                        f"💰 *Güncel Kapanış:* {guncel_kapanis}\n"
                        f"🚖 *Stop-loss:* {stop_loss_fiyati}\n"
                        f"🕒 *Sinyal Tarih:* {tarih}\n"
                        f"📅 *Tarih:* {datetime.now(TR_TZ).strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"🔸 *Grafik:* https://tr.tradingview.com/chart/iKuKZamY/?symbol=BIST%3A{hisse.replace('.IS', '')}"
                    )
                    telegram_mesaj_gonder(telegram_mesaj)
                    gonderilen_sinyaller[sinyal_anahtari] = True

        except Exception as e:
            print(f"Hata oluştu ({hisse}): {e}")
            continue

    return sinyaller

# BIST hisseleri listesi
bist_hisseleri = [
    'A1CAP.IS', 'A1YEN.IS', 'ACSEL.IS', 'ADEL.IS', 'ADESE.IS', 'ADGYO.IS', 'AEFES.IS', 'AFYON.IS', 'AGESA.IS', 'AGHOL.IS',
    'AGROT.IS', 'AGYO.IS', 'AHGAZ.IS', 'AHSGY.IS', 'AKBNK.IS', 'AKCNS.IS', 'AKENR.IS', 'AKFGY.IS', 'AKFIS.IS', 'AKFYE.IS',
    'AKGRT.IS', 'AKMGY.IS', 'AKSA.IS', 'AKSEN.IS', 'AKSGY.IS', 'AKSUE.IS', 'AKYHO.IS', 'ALARK.IS', 'ALBRK.IS', 'ALCAR.IS',
    'ALCTL.IS', 'ALFAS.IS', 'ALGYO.IS', 'ALKA.IS', 'ALKIM.IS', 'ALKLC.IS', 'ALTNY.IS', 'ALVES.IS', 'ANELE.IS', 'ANGEN.IS',
    'ANHYT.IS', 'ANSGR.IS', 'ARASE.IS', 'ARCLK.IS', 'ARDYZ.IS', 'ARENA.IS', 'ARMGD.IS', 'ARSAN.IS', 'ARTMS.IS', 'ARZUM.IS',
    'ASELS.IS', 'ASGYO.IS', 'ASTOR.IS', 'ASUZU.IS', 'ATAGY.IS', 'ATAKP.IS', 'ATATP.IS', 'AVGYO.IS', 'AVHOL.IS', 'AVOD.IS',
    'AVPGY.IS', 'AVTUR.IS', 'AYCES.IS', 'AYDEM.IS', 'AYEN.IS', 'AYES.IS', 'AYGAZ.IS', 'AZTEK.IS', 'BAGFS.IS', 'BAHKM.IS',
    'BAKAB.IS', 'BALAT.IS', 'BALSU.IS', 'BANVT.IS', 'BARMA.IS', 'BASCM.IS', 'BASGZ.IS', 'BAYRK.IS', 'BEGYO.IS', 'BERA.IS',
    'BEYAZ.IS', 'BFREN.IS', 'BIENY.IS', 'BIGCH.IS', 'BIGEN.IS', 'BIMAS.IS', 'BINBN.IS', 'BINHO.IS', 'BIOEN.IS', 'BIZIM.IS',
    'BJKAS.IS', 'BLCYT.IS', 'BMSCH.IS', 'BMSTL.IS', 'BNTAS.IS', 'BOBET.IS', 'BORLS.IS', 'BORSK.IS', 'BOSSA.IS', 'BRISA.IS',
    'BRKSN.IS', 'BRKVY.IS', 'BRLSM.IS', 'BRSAN.IS', 'BRYAT.IS', 'BSOKE.IS', 'BTCIM.IS', 'BUCIM.IS', 'BULGS.IS', 'BURCE.IS',
    'BURVA.IS', 'BVSAN.IS', 'BYDNR.IS', 'CANTE.IS', 'CATES.IS', 'CCOLA.IS', 'CELHA.IS', 'CEMAS.IS', 'CEMTS.IS', 'CEMZY.IS',
    'CEOEM.IS', 'CGCAM.IS', 'CIMSA.IS', 'CLEBI.IS', 'CMBTN.IS', 'CMENT.IS', 'CONSE.IS', 'COSMO.IS', 'CRDFA.IS', 'CRFSA.IS',
    'CUSAN.IS', 'CVKMD.IS', 'CWENE.IS', 'DAGHL.IS', 'DAGI.IS', 'DAPGM.IS', 'DARDL.IS', 'DCTTR.IS', 'DENGE.IS', 'DERHL.IS',
    'DERIM.IS', 'DESA.IS', 'DESPC.IS', 'DEVA.IS', 'DGATE.IS', 'DGGYO.IS', 'DGNMO.IS', 'DITAS.IS', 'DMRGD.IS', 'DMSAS.IS',
    'DNISI.IS', 'DOAS.IS', 'DOBUR.IS', 'DOCO.IS', 'DOFER.IS', 'DOGUB.IS', 'DOHOL.IS', 'DOKTA.IS', 'DSTKF.IS', 'DURDO.IS',
    'DURKN.IS', 'DYOBY.IS', 'DZGYO.IS', 'EBEBK.IS', 'ECILC.IS', 'ECZYT.IS', 'EDATA.IS', 'EDIP.IS', 'EFORC.IS', 'EGEEN.IS',
    'EGEGY.IS', 'EGEPO.IS', 'EGGUB.IS', 'EGPRO.IS', 'EGSER.IS', 'EKGYO.IS', 'EKOS.IS', 'EKSUN.IS', 'ELITE.IS', 'EMKEL.IS',
    'ENDAE.IS', 'ENERY.IS', 'ENJSA.IS', 'ENKAI.IS', 'ENSRI.IS', 'ENTRA.IS', 'EPLAS.IS', 'ERBOS.IS', 'ERCB.IS', 'EREGL.IS',
    'ERSU.IS', 'ESCAR.IS', 'ESCOM.IS', 'ESEN.IS', 'ETILR.IS', 'EUPWR.IS', 'EUREN.IS', 'EYGYO.IS', 'FADE.IS', 'FENER.IS',
    'FLAP.IS', 'FMIZP.IS', 'FONET.IS', 'FORMT.IS', 'FORTE.IS', 'FRIGO.IS', 'FROTO.IS', 'FZLGY.IS', 'GARAN.IS', 'GARFA.IS',
    'GEDIK.IS', 'GEDZA.IS', 'GENIL.IS', 'GENTS.IS', 'GEREL.IS', 'GESAN.IS', 'GIPTA.IS', 'GLBMD.IS', 'GLCVY.IS', 'GLRMK.IS',
    'GLRYH.IS', 'GLYHO.IS', 'GMTAS.IS', 'GOKNR.IS', 'GOLTS.IS', 'GOODY.IS', 'GOZDE.IS', 'GRSEL.IS', 'GRTHO.IS', 'GSDDE.IS',
    'GSDHO.IS', 'GSRAY.IS', 'GUBRF.IS', 'GUNDG.IS', 'GWIND.IS', 'GZNMI.IS', 'HALKB.IS', 'HATEK.IS', 'HATSN.IS', 'HDFGS.IS',
    'HEDEF.IS', 'HEKTS.IS', 'HKTM.IS', 'HLGYO.IS', 'HOROZ.IS', 'HRKET.IS', 'HTTBT.IS', 'HUBVC.IS', 'HUNER.IS', 'HURGZ.IS',
    'ICBCT.IS', 'ICUGS.IS', 'IDGYO.IS', 'IEYHO.IS', 'IHAAS.IS', 'IHEVA.IS', 'IHGZT.IS', 'IHLAS.IS', 'IHLGM.IS', 'IHYAY.IS',
    'IMASM.IS', 'INDES.IS', 'INFO.IS', 'INGRM.IS', 'INTEK.IS', 'INTEM.IS', 'INVEO.IS', 'INVES.IS', 'IPEKE.IS', 'ISATR.IS',
    'ISBIR.IS', 'ISBTR.IS', 'ISCTR.IS', 'ISDMR.IS', 'ISFIN.IS', 'ISGSY.IS', 'ISGYO.IS', 'ISKPL.IS', 'ISMEN.IS', 'ISSEN.IS',
    'IZENR.IS', 'IZFAS.IS', 'IZINV.IS', 'IZMDC.IS', 'JANTS.IS', 'KAPLM.IS', 'KAREL.IS', 'KARSN.IS', 'KARTN.IS', 'KATMR.IS',
    'KAYSE.IS', 'KBORU.IS', 'KCAER.IS', 'KCHOL.IS', 'KENT.IS', 'KERVT.IS', 'KFEIN.IS', 'KGYO.IS', 'KIMMR.IS', 'KLGYO.IS',
    'KLKIM.IS', 'KLMSN.IS', 'KLNMA.IS', 'KLRHO.IS', 'KLSER.IS', 'KLSYN.IS', 'KLYPV.IS', 'KMPUR.IS', 'KNFRT.IS', 'KOCMT.IS',
    'KONKA.IS', 'KONTR.IS', 'KONYA.IS', 'KOPOL.IS', 'KORDS.IS', 'KOTON.IS', 'KOZAA.IS', 'KOZAL.IS', 'KRDMA.IS', 'KRDMB.IS',
    'KRDMD.IS', 'KRGYO.IS', 'KRONT.IS', 'KRPLS.IS', 'KRSTL.IS', 'KRTEK.IS', 'KRVGD.IS', 'KSTUR.IS', 'KTLEV.IS', 'KTSKR.IS',
    'KUTPO.IS', 'KUYAS.IS', 'KZBGY.IS', 'KZGYO.IS', 'LIDER.IS', 'LIDFA.IS', 'LILAK.IS', 'LINK.IS', 'LKMNH.IS', 'LMKDC.IS',
    'LOGO.IS', 'LRSHO.IS', 'LUKSK.IS', 'LYDHO.IS', 'LYDYE.IS', 'MAALT.IS', 'MACKO.IS', 'MAGEN.IS', 'MAKIM.IS', 'MAKTK.IS',
    'MANAS.IS', 'MARBL.IS', 'MARKA.IS', 'MARTI.IS', 'MAVI.IS', 'MEDTR.IS', 'MEGMT.IS', 'MEKAG.IS', 'MEPET.IS', 'MERCN.IS',
    'MERIT.IS', 'MERKO.IS', 'METRO.IS', 'METUR.IS', 'MGROS.IS', 'MHRGY.IS', 'MIATK.IS', 'MNDRS.IS', 'MNDTR.IS', 'MOBTL.IS',
    'MOGAN.IS', 'MOPAS.IS', 'MPARK.IS', 'MRGYO.IS', 'MRSHL.IS', 'MSGYO.IS', 'MTRKS.IS', 'MZHLD.IS', 'NATEN.IS', 'NETAS.IS',
    'NIBAS.IS', 'NTGAZ.IS', 'NTHOL.IS', 'NUGYO.IS', 'NUHCM.IS', 'OBAMS.IS', 'OBASE.IS', 'ODAS.IS', 'ODINE.IS', 'OFSYM.IS',
    'ONCSM.IS', 'ONRYT.IS', 'ORCAY.IS', 'ORGE.IS', 'ORMA.IS', 'OSMEN.IS', 'OSTIM.IS', 'OTKAR.IS', 'OTTO.IS', 'OYAKC.IS',
    'OYLUM.IS', 'OYYAT.IS', 'OZATD.IS', 'OZGYO.IS', 'OZKGY.IS', 'OZRDN.IS', 'OZSUB.IS', 'OZYSR.IS', 'PAGYO.IS', 'PAMEL.IS',
    'PAPIL.IS', 'PARSN.IS', 'PASEU.IS', 'PATEK.IS', 'PCILT.IS', 'PEHOL.IS', 'PEKGY.IS', 'PENGD.IS', 'PENTA.IS', 'PETKM.IS',
    'PETUN.IS', 'PGSUS.IS', 'PINSU.IS', 'PKART.IS', 'PKENT.IS', 'PLTUR.IS', 'PNLSN.IS', 'PNSUT.IS', 'POLHO.IS', 'POLTK.IS',
    'PRDGS.IS', 'PRKAB.IS', 'PRKME.IS', 'PRZMA.IS', 'PSDTC.IS', 'PSGYO.IS', 'QNBFK.IS', 'QNBTR.IS', 'QUAGR.IS', 'RALYH.IS',
    'RAYSG.IS', 'REEDR.IS', 'RGYAS.IS', 'RNPOL.IS', 'RODRG.IS', 'RTALB.IS', 'RUBNS.IS', 'RUZYE.IS', 'RYGYO.IS', 'RYSAS.IS',
    'SAFKR.IS', 'SAHOL.IS', 'SAMAT.IS', 'SANEL.IS', 'SANFM.IS', 'SANKO.IS', 'SARKY.IS', 'SASA.IS', 'SAYAS.IS', 'SDTTR.IS',
    'SEGMN.IS', 'SEGYO.IS', 'SEKFK.IS', 'SEKUR.IS', 'SELEC.IS', 'SELGD.IS', 'SELVA.IS', 'SERNT.IS', 'SEYKM.IS', 'SILVR.IS',
    'SISE.IS', 'SKBNK.IS', 'SKTAS.IS', 'SKYLP.IS', 'SKYMD.IS', 'SMART.IS', 'SMRTG.IS', 'SMRVA.IS', 'SNGYO.IS', 'SNICA.IS',
    'SNPAM.IS', 'SODSN.IS', 'SOKE.IS', 'SOKM.IS', 'SONME.IS', 'SRVGY.IS', 'SUMAS.IS', 'SUNTK.IS', 'SURGY.IS', 'SUWEN.IS',
    'TABGD.IS', 'TARKM.IS', 'TATEN.IS', 'TATGD.IS', 'TAVHL.IS', 'TBORG.IS', 'TCELL.IS', 'TCKRC.IS', 'TDGYO.IS', 'TEKTU.IS',
    'TERA.IS', 'TEZOL.IS', 'TGSAS.IS', 'THYAO.IS', 'TKFEN.IS', 'TKNSA.IS', 'TLMAN.IS', 'TMPOL.IS', 'TMSN.IS', 'TNZTP.IS',
    'TOASO.IS', 'TRCAS.IS', 'TRGYO.IS', 'TRILC.IS', 'TSGYO.IS', 'TSKB.IS', 'TSPOR.IS', 'TTKOM.IS', 'TTRAK.IS', 'TUCLK.IS',
    'TUKAS.IS', 'TUPRS.IS', 'TUREX.IS', 'TURGG.IS', 'TURSG.IS', 'UFUK.IS', 'ULAS.IS', 'ULKER.IS', 'ULUFA.IS', 'ULUSE.IS',
    'ULUUN.IS', 'UNLU.IS', 'USAK.IS', 'VAKBN.IS', 'VAKFN.IS', 'VAKKO.IS', 'VANGD.IS', 'VBTYZ.IS', 'VERTU.IS', 'VERUS.IS',
    'VESBE.IS', 'VESTL.IS', 'VKGYO.IS', 'VKING.IS', 'VRGYO.IS', 'VSNMD.IS', 'YAPRK.IS', 'YATAS.IS', 'YAYLA.IS', 'YBTAS.IS',
    'YEOTK.IS', 'YESIL.IS', 'YGGYO.IS', 'YIGIT.IS', 'YKBNK.IS', 'YKSLN.IS', 'YONGA.IS', 'YUNSA.IS', 'YYAPI.IS', 'YYLGD.IS',
    'ZEDUR.IS', 'ZOREN.IS', 'ZRGYO.IS'
]

# Tarih aralığı
bitis_tarihi = datetime(2025, 6, 12, tzinfo=TR_TZ)
baslangic_tarihi = bitis_tarihi - timedelta(days=60)

# Tarama fonksiyonu
def tarama_yap():
    print(f"Tarama başlatılıyor: {datetime.now(TR_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
    sinyaller = bist_hisseleri_tara(bist_hisseleri, baslangic_tarihi, bitis_tarihi, interval='60m', gunluk_fallback=True)
    if sinyaller:
        print("\nBulunan Sinyaller:")
        for sinyal in sinyaller:
            print(f"SİNYAL: {sinyal['SİNYAL']}")
            print(f"HİSSE: {sinyal['HİSSE']}")
            print(f"SİNYAL FİYATI: {sinyal['SİNYAL FİYATI']}")
            print(f"GÜNCEL KAPANIS: {sinyal['GÜNCEL KAPANIS']}")
            print(f"STOP-LOSS: {sinyal['STOP-LOSS']}")
            print(f"SİNYAL TARİH: {sinyal['SİNYAL TARİH']}")
            print()
    else:
        print("\nHiçbir sinyal bulunamadı. Veri veya parametreleri kontrol et.")
        print("Olası nedenler:")
        print("- Veri alınamadı veya yetersiz veri (hisse için yeterli bar yok).")
        print("- Sinyal kriterleri (onay barları, hacim, yakınlık eşiği) sağlanmadı.")
        print("- İşlem saatleri dışında veri (BIST: 09:00-18:00).")
        print("- Supertrend hesaplaması için yeterli veri yok.")

# Otomatik tarama için zamanlayıcı ayarları
def otomatik_tarama_ayarla():
    print("Otomatik tarama ayarlandı: Hafta içi 10:00-18:00 arasında sürekli tarama.")

# Ana fonksiyon
def main():
    print("Program başlatılıyor...")
    otomatik_tarama_ayarla()
    print("Manuel tarama da yapılabilir.")
    
    # İlk manuel tarama
    tarama_yap()
    
    # Otomatik tarama döngüsü
    while True:
        try:
            now = datetime.now(TR_TZ)
            # Hafta içi ve saat 10:00-18:00 arasında mı kontrol et
            if now.weekday() < 5 and 10 <= now.hour < 18:
                tarama_yap()
                time.sleep(60)  # Her 60 saniyede bir tarama yap
            else:
                # İşlem saatleri dışındaysa, bir sonraki 10:00'a kadar bekle
                print(f"İşlem saatleri dışında: {now.strftime('%Y-%m-%d %H:%M:%S')}. Bir sonraki işlem saatini bekliyor...")
                next_day = now + timedelta(days=1) if now.hour >= 18 else now
                next_run = datetime(next_day.year, next_day.month, next_day.day, 10, 0, tzinfo=TR_TZ)
                if now.weekday() >= 5:  # Hafta sonuysa, bir sonraki Pazartesi 10:00'a kadar bekle
                    next_run += timedelta(days=(7 - now.weekday()))
                wait_seconds = (next_run - now).total_seconds()
                print(f"Bir sonraki tarama: {next_run.strftime('%Y-%m-%d %H:%M:%S')}. {wait_seconds/3600:.2f} saat sonra.")
                time.sleep(max(wait_seconds, 60))  # En az 60 saniye bekle
        except KeyboardInterrupt:
            print("Program kullanıcı tarafından durduruldu.")
            break
        except Exception as e:
            print(f"Otomatik tarama sırasında hata oluştu: {e}")
            time.sleep(60)  # Hata durumunda 1 dakika bekle ve devam et

if __name__ == "__main__":
    main()
