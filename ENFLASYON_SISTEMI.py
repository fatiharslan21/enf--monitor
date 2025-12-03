import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from playwright.sync_api import sync_playwright
import os
import re
from urllib.parse import urlparse
from datetime import datetime
import time
import sys
import subprocess
import shutil

# --- AYARLAR ---
BASE_DIR = os.getcwd()
TXT_DOSYASI = "URL VE CSS.txt"
EXCEL_DOSYASI = "TUFE_Konfigurasyon.xlsx"
FIYAT_DOSYASI = "Fiyat_Veritabani.xlsx"  # Ana veritabanımız bu
PROFIL_KLASORU = os.path.join(BASE_DIR, "firefox_profil_data")  # Hafıza klasörü
SAYFA_ADI = "Madde_Sepeti"

st.set_page_config(page_title="ENFLASYON MONITORU", layout="wide", initial_sidebar_state="collapsed")

# --- CSS (Arayüz) ---
st.markdown("""
    <style>
        [data-testid="stSidebar"] {display: none;}
        .stApp {background-color: #f0f2f6;}
        .admin-panel {background: white; padding: 20px; border-radius: 10px; border-top: 5px solid #ff4b4b; box-shadow: 0 4px 6px rgba(0,0,0,0.1);}
    </style>
""", unsafe_allow_html=True)

# --- MARKET SEÇİCİLERİ ---
MARKET_SELECTORLERI = {
    "cimri": ["div.rTdMX", ".offer-price", "div.sS0lR", ".min-price-val"],
    "migros": ["fe-product-price .subtitle-1", "fe-product-price .single-price-amount"],
    "carrefoursa": [".item-price", ".price"],
    "sokmarket": [".pricetag", ".price-box"],
    "a101": [".current-price", ".product-price"],
    "trendyol": [".prc-dsc", ".product-price-container"],
    "hepsiburada": ["[data-test-id='price-current-price']", ".price"],
    "amazon": ["#corePrice_feature_div .a-price-whole", "#priceblock_ourprice"],
    "getir": ["[data-testid='product-price']"],
    "bim": [".product-price"]
}


# --- YARDIMCI FONKSİYONLAR ---
def temizle_fiyat(text):
    if not text: return None
    text = str(text)
    text = re.sub('<[^<]+?>', '', text)  # HTML temizle
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


def veriyi_dosyaya_ekle(yeni_veri_listesi):
    """
    Bu fonksiyon yeni gelen verileri mevcudun ÜZERİNE YAZMAZ,
    mevcut dosyanın ALTINA EKLER.
    """
    if not yeni_veri_listesi:
        return False

    df_yeni = pd.DataFrame(yeni_veri_listesi)

    if os.path.exists(FIYAT_DOSYASI):
        try:
            # Mevcut dosyayı oku
            df_eski = pd.read_excel(FIYAT_DOSYASI, sheet_name='Fiyat_Log')
            # Eskisi ile yenisini birleştir (Concat)
            df_toplam = pd.concat([df_eski, df_yeni], ignore_index=True)
            # Tarihe göre sırala (En yeni en altta)
            df_toplam = df_toplam.sort_values(by="Tarih")
        except:
            # Dosya bozuksa veya okunamazsa direkt yenisini yaz
            df_toplam = df_yeni
    else:
        # Dosya yoksa direkt yenisini yaz
        df_toplam = df_yeni

    # Kaydet
    with pd.ExcelWriter(FIYAT_DOSYASI, engine='openpyxl') as writer:
        df_toplam.to_excel(writer, sheet_name='Fiyat_Log', index=False)

    return True


# --- BOT MOTORU ---
def botu_calistir(status_callback=None):
    import sys
    is_windows = os.name == 'nt'

    # PC ise Görünür, Sunucu ise Gizli
    headless_mode = not is_windows

    if status_callback: status_callback(f"Bot Başlatılıyor... ({'GÖRÜNÜR' if is_windows else 'GİZLİ'})")

    # 1. Hazırlık
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "firefox"], check=False)
    except:
        pass

    if not os.path.exists(PROFIL_KLASORU): os.makedirs(PROFIL_KLASORU)

    # 2. Listeyi Excel'den Oku
    try:
        df = pd.read_excel(EXCEL_DOSYASI, sheet_name=SAYFA_ADI, dtype={'Kod': str})
        df['Kod'] = df['Kod'].apply(kod_standartlastir)
        # Sadece URL'si olanları al
        mask = (df['URL'].notna())
        takip = df[mask].copy()
    except:
        return "Ayar Dosyası Okunamadı"

    veriler = []

    with sync_playwright() as p:
        # Tarayıcıyı Başlat
        browser = p.firefox.launch_persistent_context(
            user_data_dir=PROFIL_KLASORU,
            headless=headless_mode,  # Windows'ta tarayıcıyı gör
            viewport={"width": 1366, "height": 768},
            slow_mo=100 if is_windows else 0,  # İnsan gibi yavaşla (sadece Windows'ta)
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
        )

        page = browser.pages[0] if browser.pages else browser.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        for i, row in takip.iterrows():
            urun_adi = str(row.get('Madde adı'))[:15]
            url = row['URL']

            if status_callback: status_callback(f"Taranıyor [{i + 1}/{len(takip)}]: {urun_adi}")

            fiyat = 0.0
            kaynak = ""

            # --- MANUEL FİYAT KONTROLÜ ---
            if pd.notna(row.get('Manuel_Fiyat')) and float(row.get('Manuel_Fiyat') or 0) > 0:
                # Manuel fiyat varsa internete gitme, direkt ekle
                veriler.append({
                    "Tarih": datetime.now().strftime("%Y-%m-%d"),
                    "Zaman": datetime.now().strftime("%H:%M"),
                    "Kod": row.get('Kod'),
                    "Madde_Adi": row.get('Madde adı'),
                    "Fiyat": float(row.get('Manuel_Fiyat')),
                    "Kaynak": "Manuel",
                    "URL": url
                })
                continue

            # --- ONLINE FİYAT ÇEKME ---
            if str(url).startswith("http"):
                try:
                    # Sayfaya git (Max 30 sn bekle, açılmazsa geç)
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")

                    domain = urlparse(url).netloc.lower()

                    # Seçiciyi Bul
                    selectors = []
                    for m, s_list in MARKET_SELECTORLERI.items():
                        if m in domain: selectors = s_list; kaynak = f"Otomatik ({m})"; break

                    # Eğer özel CSS varsa onu da ekle
                    if pd.notna(row.get('CSS_Selector')):
                        selectors.insert(0, str(row.get('CSS_Selector')).strip())
                        kaynak = "Özel CSS"

                    # --- FİYATI ARA ---
                    if selectors:
                        # 1. Hızlı Deneme (3 saniye bekle)
                        try:
                            # İlk seçiciyi bekle
                            page.wait_for_selector(selectors[0], timeout=3000)
                        except:
                            # Bulamadıysa çok zorlama, belki robot kontrolü vardır
                            if "cimri" in domain and is_windows:
                                # Windows'taysan ve Cimri'deysen Robot kutusu var mı bak
                                try:
                                    if page.locator(".cb-lb").first.is_visible(timeout=1000):
                                        # Kutu var, kullanıcı tıklasın diye bekleme yapmıyoruz
                                        # Ama log'a yazabiliriz
                                        pass
                                except:
                                    pass

                        # Elemanları Tara
                        for sel in selectors:
                            try:
                                elements = page.locator(sel).all_inner_texts()
                                # Bulunan metinleri temizle ve sayıya çevir
                                prices = [p for p in [temizle_fiyat(e) for e in elements] if p]

                                if prices:
                                    # Cimri mantığı: Ortalamayı al (çünkü çok fiyat var)
                                    if "cimri" in domain and len(prices) > 1:
                                        if len(prices) > 4: prices.sort(); prices = prices[1:-1]  # Uçları at
                                        fiyat = sum(prices) / len(prices)
                                    else:
                                        # Diğer marketler: İlk mantıklı fiyatı al
                                        fiyat = prices[0]
                                    break  # Fiyat bulunduysa diğer selectorlara bakma
                            except:
                                continue

                except Exception as e:
                    print(f"Hata ({urun_adi}): {e}")

            # Fiyat bulunduysa listeye ekle
            if fiyat > 0:
                veriler.append({
                    "Tarih": datetime.now().strftime("%Y-%m-%d"),
                    "Zaman": datetime.now().strftime("%H:%M"),
                    "Kod": row.get('Kod'),
                    "Madde_Adi": row.get('Madde adı'),
                    "Fiyat": fiyat,
                    "Kaynak": kaynak,
                    "URL": url
                })

        browser.close()

    # --- VERİLERİ MEVCUT DOSYAYA EKLE ---
    if veriler:
        if status_callback: status_callback("💾 Veriler Veritabanına Kaydediliyor...")
        basari = veriyi_dosyaya_ekle(veriler)
        if basari:
            return f"Tamamlandı! {len(veriler)} yeni fiyat eklendi."
        else:
            return "Kayıt Hatası"
    else:
        return "Hiç yeni fiyat bulunamadı."


# --- DASHBOARD KODLARI ---
def dashboard_modu():
    # Başlangıç Dosyası Kontrolü
    if not os.path.exists(FIYAT_DOSYASI):
        df = pd.DataFrame(columns=["Tarih", "Zaman", "Kod", "Madde_Adi", "Fiyat", "Kaynak", "URL"])
        df.to_excel(FIYAT_DOSYASI, sheet_name='Fiyat_Log', index=False)

    st.title("📊 ENFLASYON TAKİP SİSTEMİ")

    # Veriyi Oku
    try:
        df_fiyat = pd.read_excel(FIYAT_DOSYASI, sheet_name="Fiyat_Log")
    except:
        df_fiyat = pd.DataFrame()

    if not df_fiyat.empty:
        son_tarih = df_fiyat['Tarih'].max()
        kayit_sayisi = len(df_fiyat)
        st.info(f"📁 Veritabanı Durumu: Toplam {kayit_sayisi} kayıt var. Son güncelleme: {son_tarih}")

        # Son 5 kayıt (Örnek)
        st.dataframe(df_fiyat.tail(5), use_container_width=True)
    else:
        st.warning("Henüz veri yok. Botu çalıştırın.")

    # --- YÖNETİM PANELİ ---
    st.markdown('<div class="admin-panel">', unsafe_allow_html=True)
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("🚀 Bot Kontrolü")
        if st.button("Verileri Tara ve Ekle", type="primary"):
            status_box = st.empty()
            sonuc = botu_calistir(lambda msg: status_box.info(f"⚙️ {msg}"))
            status_box.success(sonuc)
            time.sleep(2)
            st.rerun()

    with c2:
        st.subheader("📥 Veritabanını İndir")
        if os.path.exists(FIYAT_DOSYASI):
            with open(FIYAT_DOSYASI, "rb") as f:
                st.download_button(
                    label="Excel Olarak İndir (Fiyat_Veritabani.xlsx)",
                    data=f,
                    file_name="Fiyat_Veritabani.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    st.markdown('</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    dashboard_modu()