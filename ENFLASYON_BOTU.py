import pandas as pd
from playwright.sync_api import sync_playwright
from datetime import datetime
import os
import re
import winreg
from urllib.parse import urlparse
import time
import shutil

# --- AYARLAR ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TXT_DOSYASI = os.path.join(BASE_DIR, "URL VE CSS.txt")
EXCEL_DOSYASI = os.path.join(BASE_DIR, "TUFE_Konfigurasyon.xlsx")
# Botun hafızasını kaydedeceği klasör (Bunu silme, çerezler burada birikir)
PROFIL_KLASORU = os.path.join(BASE_DIR, "chrome_profil_data")
SAYFA_ADI = "Madde_Sepeti"

# --- MARKET SEÇİCİLERİ ---
MARKET_SELECTORLERI = {
    "cimri": ["div.rTdMX", ".offer-price", "div.sS0lR", ".min-price-val"],
    "migros": ["fe-product-price .subtitle-1", "fe-product-price .single-price-amount", "fe-product-price .amount"],
    "carrefoursa": [".item-price", ".price"],
    "sokmarket": [".pricetag", ".price-box"],
    "a101": [".current-price", ".product-price"],
    "trendyol": [".prc-dsc", ".product-price-container"],
    "hepsiburada": ["[data-test-id='price-current-price']", ".price", "div[data-test-id='price-container']"],
    "amazon": ["#corePrice_feature_div .a-price-whole", "#corePriceDisplay_desktop_feature_div .a-price-whole",
               "#priceblock_ourprice"],
    "getir": ["[data-testid='product-price']", "div[data-testid='text-price']"],
    "yemeksepeti": [".product-price"],
    "bim": [".product-price"],
    "koctas": [".price-new"],
    "teknosa": [".prc-first"],
    "mediamarkt": [".price"]
}


def chrome_yolunu_bul():
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe")
        path, _ = winreg.QueryValueEx(key, "")
        if os.path.exists(path): return path
    except:
        pass
    yollar = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
    for y in yollar:
        if os.path.exists(y): return y
    return None


def temizle_fiyat(text):
    if not text: return None
    text = str(text)
    text = re.sub('<[^<]+?>', '', text)
    text = text.replace('TL', '').replace('₺', '').replace('TRY', '').strip()
    if ',' in text and '.' in text:
        text = text.replace('.', '').replace(',', '.')
    elif ',' in text:
        text = text.replace(',', '.')
    text = re.sub(r'[^\d.]', '', text)
    try:
        val = float(text)
        return val if val > 0.5 else None
    except:
        return None


def kod_standartlastir(kod):
    try:
        return str(kod).replace('.0', '').strip().zfill(7)
    except:
        return "0000000"


def txt_dosyasini_excele_isle():
    print("🔄 Excel Senkronizasyonu...")
    if not os.path.exists(TXT_DOSYASI) or not os.path.exists(EXCEL_DOSYASI): return False
    try:
        with open(TXT_DOSYASI, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        df = pd.read_excel(EXCEL_DOSYASI, sheet_name=SAYFA_ADI, dtype={'Kod': str})

        urls, selectors, manual_prices = [], [], []
        for i in range(len(df)):
            if i < len(lines):
                line = lines[i]
                parts = line.split(None, 1)
                first = parts[0]
                content = parts[1] if len(parts) > 1 else ""
                if first.startswith("http"):
                    urls.append(first)
                    is_known = any(m in urlparse(first).netloc.lower() for m in MARKET_SELECTORLERI)
                    if is_known:
                        selectors.append(None);
                        manual_prices.append(None)
                    else:
                        p = temizle_fiyat(content)
                        if p:
                            manual_prices.append(p); selectors.append(None)
                        else:
                            selectors.append(content); manual_prices.append(None)
                else:
                    p = temizle_fiyat(line)
                    urls.append(None);
                    selectors.append(None)
                    manual_prices.append(p) if p else manual_prices.append(None)
            else:
                urls.append(None);
                selectors.append(None);
                manual_prices.append(None)

        df['URL'] = urls;
        df['CSS_Selector'] = selectors;
        df['Manuel_Fiyat'] = manual_prices
        try:
            with pd.ExcelWriter(EXCEL_DOSYASI, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                df.to_excel(writer, sheet_name=SAYFA_ADI, index=False)
            return True
        except PermissionError:
            print("⚠️ UYARI: Konfigürasyon dosyası açık! Devam ediliyor.")
            return True
    except Exception as e:
        print(f"Sync Hatası: {e}");
        return False


def botu_calistir():
    chrome_path = chrome_yolunu_bul()
    if not chrome_path: print("❌ HATA: Chrome bulunamadı."); return

    txt_dosyasini_excele_isle()
    print(f"🚀 Bot Başlatılıyor... (ANTI-DETECT MOD)")

    # Profil klasörü yoksa oluştur
    if not os.path.exists(PROFIL_KLASORU):
        os.makedirs(PROFIL_KLASORU)

    try:
        df = pd.read_excel(EXCEL_DOSYASI, sheet_name=SAYFA_ADI, dtype={'Kod': str})
        df['Kod'] = df['Kod'].apply(kod_standartlastir)
        mask = (df['URL'].notna()) | (df['Manuel_Fiyat'].notna())
        takip_listesi = df[mask].copy()
        print(f"📋 Hedef: {len(takip_listesi)} ürün taranacak.")
    except Exception as e:
        print(f"Excel Hatası: {e}");
        return

    veriler = []
    total = len(takip_listesi)

    with sync_playwright() as p:
        # --- KRİTİK DEĞİŞİKLİK: launch_persistent_context ---
        # Bu özellik tarayıcıyı her açtığında çerezleri ve geçmişi hatırlar.
        # Böylece Cloudflare seni "sürekli gelen güvenilir kullanıcı" sanar.
        browser = p.chromium.launch_persistent_context(
            user_data_dir=PROFIL_KLASORU,  # Hafıza buraya kaydedilecek
            executable_path=chrome_path,
            headless=False,
            slow_mo=50,
            # Bot tespitini engelleyen özel argümanlar
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--no-sandbox",
                "--disable-infobars"
            ],
            viewport={"width": 1920, "height": 1080}
        )

        page = browser.pages[0] if browser.pages else browser.new_page()

        # --- GİZLİLİK TAKTİĞİ: webdriver özelliğini sil ---
        # Sitelerin "Bu bir bot mu?" diye baktığı ilk değişkeni yok ediyoruz.
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        for i, (index, row) in enumerate(takip_listesi.iterrows()):
            urun_adi = str(row.get('Madde adı', '---'))[:20]
            print(f"[{i + 1}/{total}] {urun_adi}...", end=" ")

            fiyat = None
            kaynak = ""
            url = row['URL']

            # 1. Manuel
            if pd.notna(row.get('Manuel_Fiyat')):
                val = float(row['Manuel_Fiyat'])
                if val > 0:
                    fiyat = val;
                    kaynak = "Manuel"
                    print(f"✅ Manuel: {fiyat}")

            # 2. Web Scraping
            elif pd.notna(url) and str(url).startswith("http"):
                domain = urlparse(url).netloc.lower()
                selectors = []
                for m, s_list in MARKET_SELECTORLERI.items():
                    if m in domain: selectors = s_list; kaynak = f"Otomatik ({m})"; break
                if not selectors and pd.notna(row.get('CSS_Selector')):
                    selectors = [str(row.get('CSS_Selector')).strip()]
                    kaynak = "Özel CSS"

                try:
                    page.goto(url, timeout=60000, wait_until="domcontentloaded")

                    if "cimri" in domain:
                        print("⏳ (Cimri Kontrolü...)", end=" ")

                        # Otomatik Kutu Avcısı (15 sn)
                        kutu_tiklandi = False
                        for saniye in range(15):
                            if page.locator("div.rTdMX").first.is_visible():
                                break  # Fiyatlar zaten açıksa bekleme

                            kutu = page.locator(".cb-lb").first
                            if kutu.is_visible():
                                print("🤖 Robot Kutusu Geçiliyor...", end=" ")
                                kutu.hover()
                                time.sleep(random.uniform(0.3, 0.7))  # Rastgele bekleme (İnsan gibi)
                                page.mouse.down()
                                time.sleep(random.uniform(0.1, 0.3))
                                page.mouse.up()
                                page.wait_for_timeout(3000)
                                kutu_tiklandi = True
                                break
                            time.sleep(1)

                        page.mouse.wheel(0, 500)

                        # Fiyat Ara
                        bulundu = False
                        for sel in selectors:
                            try:
                                if page.locator(sel).count() > 0:
                                    elements = page.locator(sel).all_inner_texts()
                                    prices = [p for p in [temizle_fiyat(e) for e in elements] if p]
                                    if prices:
                                        if len(prices) > 4: prices.sort(); prices = prices[1:-1]
                                        fiyat = sum(prices) / len(prices)
                                        kaynak = f"Cimri ({len(prices)})"
                                        print(f"✅ {fiyat:.2f} TL")
                                        bulundu = True
                                        break
                            except:
                                pass

                        if not bulundu:
                            # Regex
                            body_text = page.locator("body").inner_text()
                            bulunanlar = re.findall(r'(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*(?:TL|₺)', body_text)
                            fiyatlar = []
                            for ham in bulunanlar:
                                temiz = temizle_fiyat(ham)
                                if temiz: fiyatlar.append(temiz)
                            if fiyatlar:
                                fiyatlar.sort()
                                mantikli = fiyatlar[:max(1, len(fiyatlar) // 2)]
                                fiyat = sum(mantikli) / len(mantikli)
                                kaynak = "Cimri (Regex)"
                                print(f"✅ Regex: {fiyat:.2f} TL")
                            else:
                                print("⚠️ Bulunamadı")

                    elif selectors:
                        # Diğer marketler (Hızlandırılmış)
                        time.sleep(1)
                        for sel in selectors:
                            try:
                                if "migros" in domain:
                                    el = page.locator(sel).first
                                    if el.count() > 0:
                                        val = temizle_fiyat(el.inner_text())
                                        if val: fiyat = val; break
                                else:
                                    elements = page.locator(sel).all_inner_texts()
                                    for el in elements:
                                        val = temizle_fiyat(el)
                                        if val: fiyat = val; break
                                    if fiyat: break
                            except:
                                continue
                        if fiyat:
                            print(f"✅ {fiyat} TL")
                        else:
                            print("⚠️ Bulunamadı")
                    else:
                        print("⏭️ Şablon Yok")
                except Exception as e:
                    print(f"❌ Hata: {e}")
            else:
                print("⚪ URL Yok")

            veriler.append({
                "Tarih": datetime.now().strftime("%Y-%m-%d"),
                "Kod": row.get('Kod'),
                "Madde_Adi": row.get('Madde adı'),
                "Fiyat": fiyat,
                "Kaynak": kaynak,
                "URL": row.get('URL')
            })

        # Tarayıcıyı kapatmıyoruz ki hafıza silinmesin, sadece script biter.
        browser.close()

    if veriler:
        print("\n💾 Dosya oluşturuluyor...")
        zaman_damgasi = datetime.now().strftime("%d_%m_%Y__%H_%M_%S")
        yeni_dosya_adi = f"Fiyatlar_{zaman_damgasi}.xlsx"
        tam_yol = os.path.join(BASE_DIR, yeni_dosya_adi)
        try:
            df_yeni = pd.DataFrame(veriler)
            df_yeni.to_excel(tam_yol, index=False)
            print(f"✅ DOSYA HAZIR: {yeni_dosya_adi}")
        except Exception as e:
            print(f"❌ Kayıt Hatası: {e}")


if __name__ == "__main__":
    botu_calistir()