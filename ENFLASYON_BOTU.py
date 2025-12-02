import pandas as pd
from playwright.sync_api import sync_playwright
from datetime import datetime
import os
import re
import winreg
from urllib.parse import urlparse
import time

# --- AYARLAR ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TXT_DOSYASI = os.path.join(BASE_DIR, "URL VE CSS.txt")
EXCEL_DOSYASI = os.path.join(BASE_DIR, "TUFE_Konfigurasyon.xlsx")
CIKTI_DOSYASI = os.path.join(BASE_DIR, "Fiyat_Veritabani.xlsx")
SAYFA_ADI = "Madde_Sepeti"
LOG_SAYFASI = "Fiyat_Log"

# --- MARKET SEÇİCİLERİ ---
MARKET_SELECTORLERI = {
    "cimri": ["div.rTdMX", "div.sS0lR", ".offer-price"],
    "migros": ["fe-product-price .subtitle-1", "fe-product-price .single-price-amount", "fe-product-price .amount",
               "fe-product-price .sale-price", "fe-product-price .price"],
    "carrefoursa": [".item-price", ".price"],
    "sokmarket": [".pricetag", ".price-box"],
    "a101": [".current-price", ".product-price"],
    "trendyol": [".prc-dsc", ".product-price-container"],
    "hepsiburada": ["[data-test-id='price-current-price']", ".price"],
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
                            manual_prices.append(p);
                            selectors.append(None)
                        else:
                            selectors.append(content);
                            manual_prices.append(None)
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

        # Dosya açıksa hata vermemesi için koruma
        try:
            with pd.ExcelWriter(EXCEL_DOSYASI, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                df.to_excel(writer, sheet_name=SAYFA_ADI, index=False)
            return True
        except PermissionError:
            print("⚠️ UYARI: TUFE_Konfigurasyon dosyası açık! Veriler güncellenemedi.")
            return True
    except Exception as e:
        print(f"Sync Hatası: {e}");
        return False


def verileri_kaydet(yeni_veriler_df):
    """
    Excel'e kaydetme işlemini garantili yapan fonksiyon.
    Eski yöntemdeki 'overlay' sorununu çözer.
    """
    print("\n💾 Kayıt işlemi başlatılıyor...")
    try:
        if os.path.exists(CIKTI_DOSYASI):
            # Dosya varsa: Oku, birleştir, kaydet
            try:
                # Mevcut veriyi oku
                eski_df = pd.read_excel(CIKTI_DOSYASI, sheet_name=LOG_SAYFASI)
                # Yeni veriyi altına ekle (concat)
                birlestirilmis_df = pd.concat([eski_df, yeni_veriler_df], ignore_index=True)
            except ValueError:
                # Sayfa yoksa veya dosya boşsa direkt yeniyi al
                birlestirilmis_df = yeni_veriler_df

            # Tüm veriyi tekrar yaz (Bu en temiz yöntemdir)
            with pd.ExcelWriter(CIKTI_DOSYASI, engine='openpyxl', mode='w') as writer:
                birlestirilmis_df.to_excel(writer, sheet_name=LOG_SAYFASI, index=False)
        else:
            # Dosya yoksa sıfırdan oluştur
            with pd.ExcelWriter(CIKTI_DOSYASI, engine='openpyxl') as writer:
                yeni_veriler_df.to_excel(writer, sheet_name=LOG_SAYFASI, index=False)

        print(f"✅ Başarıyla kaydedildi. Toplam satır: {len(yeni_veriler_df)}")

    except PermissionError:
        yedek_isim = f"Fiyat_YEDEK_{datetime.now().strftime('%H%M%S')}.xlsx"
        yeni_veriler_df.to_excel(os.path.join(BASE_DIR, yedek_isim), index=False)
        print(f"❌ HATA: Ana dosya (Fiyat_Veritabani.xlsx) açık! Veriler '{yedek_isim}' adıyla yedeklendi.")
    except Exception as e:
        print(f"❌ Kayıt Hatası: {e}")


def botu_calistir():
    chrome_path = chrome_yolunu_bul()
    if not chrome_path: print("❌ HATA: Chrome bulunamadı."); return

    txt_dosyasini_excele_isle()
    print(f"🚀 Bot Başlatılıyor...")

    try:
        df = pd.read_excel(EXCEL_DOSYASI, sheet_name=SAYFA_ADI, dtype={'Kod': str})
        df['Kod'] = df['Kod'].apply(kod_standartlastir)
        # Sadece URL veya Manuel Fiyatı olanları al
        mask = (df['URL'].notna()) | (df['Manuel_Fiyat'].notna())
        takip_listesi = df[mask].copy()
        print(f"📋 Hedef: {len(takip_listesi)} ürün taranacak.")
    except Exception as e:
        print(f"Excel Hatası: {e}");
        return

    veriler = []
    total = len(takip_listesi)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=chrome_path,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        context.route("**/*",
                      lambda r: r.abort() if r.request.resource_type in ["image", "media", "font"] else r.continue_())
        page = context.new_page()

        for i, (index, row) in enumerate(takip_listesi.iterrows()):
            urun_adi = str(row.get('Madde adı', '---'))[:20]
            print(f"[{i + 1}/{total}] {urun_adi}...", end=" ")

            fiyat = None
            kaynak = ""

            # 1. Manuel Kontrol
            if pd.notna(row.get('Manuel_Fiyat')):
                val = float(row['Manuel_Fiyat'])
                if val > 0:
                    fiyat = val;
                    kaynak = "Manuel"
                    print(f"✅ Manuel: {fiyat}")

            # 2. Web Scraping
            elif pd.notna(row.get('URL')) and str(row['URL']).startswith("http"):
                url = row['URL']
                domain = urlparse(url).netloc.lower()
                selectors = []
                for m, s_list in MARKET_SELECTORLERI.items():
                    if m in domain: selectors = s_list; kaynak = f"Otomatik ({m})"; break
                if not selectors and pd.notna(row.get('CSS_Selector')):
                    selectors = [str(row.get('CSS_Selector')).strip()]
                    kaynak = "Özel CSS"

                if selectors:
                    try:
                        page.goto(url, timeout=25000, wait_until="domcontentloaded")
                        if "cimri" in domain:
                            try:
                                page.wait_for_selector("div.rTdMX", timeout=4000)
                                elements = page.locator("div.rTdMX").all_inner_texts()
                                prices = [p for p in [temizle_fiyat(e) for e in elements] if p]
                                if prices:
                                    if len(prices) > 4: prices.sort(); prices = prices[1:-1]
                                    fiyat = sum(prices) / len(prices)
                                    kaynak = f"Cimri ({len(prices)})"
                                    print(f"✅ Ort: {fiyat:.2f} TL")
                            except:
                                pass
                        else:
                            stok_yok = False
                            if "amazon" in domain:
                                try:
                                    av = page.locator("#availability").inner_text().lower()
                                    if "mevcut değil" in av or "stokta yok" in av: stok_yok = True
                                except:
                                    pass

                            if not stok_yok:
                                for sel in selectors:
                                    try:
                                        page.wait_for_selector(sel, timeout=3000)
                                        if "migros" in domain:
                                            el = page.locator(sel).first
                                            if el.count() > 0:
                                                val = temizle_fiyat(el.inner_text())
                                                if val: fiyat = val; break
                                        elif "amazon" in domain:
                                            el_text = page.locator(sel).first.inner_text()
                                            val = temizle_fiyat(el_text)
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
                                elif stok_yok:
                                    print("⚠️ Stok Yok")
                                else:
                                    print("⚠️ Fiyat Bulunamadı")
                    except:
                        print("❌ Bağlantı Hatası")
                else:
                    print("⏭️ Şablon Yok")
            else:
                print("⚪")

            veriler.append({
                "Tarih": datetime.now().strftime("%Y-%m-%d"),
                "Kod": row.get('Kod'),
                "Madde_Adi": row.get('Madde adı'),
                "Fiyat": fiyat,
                "Kaynak": kaynak,
                "URL": row.get('URL')
            })
        browser.close()

    if veriler:
        df_yeni = pd.DataFrame(veriler)
        verileri_kaydet(df_yeni)


if __name__ == "__main__":
    botu_calistir()