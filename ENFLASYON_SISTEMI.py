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
import numpy as np
import random
import shutil

# --- 1. SAYFA AYARLARI ---
st.set_page_config(page_title="ENFLASYON MONITORU", page_icon="🏦", layout="wide", initial_sidebar_state="collapsed")

# --- CSS TASARIM ---
st.markdown("""
    <style>
        [data-testid="stSidebar"] {display: none;}
        [data-testid="stToolbar"] {visibility: hidden !important;} 
        [data-testid="stHeader"] {visibility: hidden !important;}
        .stDeployButton {display:none !important;} 
        footer {visibility: hidden;} 
        #MainMenu {visibility: hidden;}
        .stApp {background-color: #F8F9FA; color: #212529;}

        /* Kartlar ve Panel */
        div[data-testid="metric-container"] {
            background: #FFFFFF; border: 1px solid #EAEDF0; border-radius: 12px; padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.02);
        }
        .admin-panel {
            background-color: #FFFFFF; border-top: 4px solid #ebc71d; padding: 30px;
            border-radius: 15px; margin-top: 50px; box-shadow: 0 -5px 25px rgba(0,0,0,0.05);
        }
    </style>
""", unsafe_allow_html=True)

# --- 2. AYARLAR ---
BASE_DIR = os.getcwd()
TXT_DOSYASI = "URL VE CSS.txt"
EXCEL_DOSYASI = "TUFE_Konfigurasyon.xlsx"
FIYAT_DOSYASI = "Fiyat_Veritabani.xlsx"
SAYFA_ADI = "Madde_Sepeti"

# --- MARKET SEÇİCİLERİ ---
MARKET_SELECTORLERI = {
    "cimri": ["div.rTdMX", ".offer-price", "div.sS0lR", ".min-price-val"],
    "migros": ["fe-product-price .subtitle-1", "fe-product-price .single-price-amount", "fe-product-price .amount"],
    "carrefoursa": [".item-price", ".price"],
    "sokmarket": [".pricetag", ".price-box"],
    "a101": [".current-price", ".product-price"],
    "trendyol": [".prc-dsc", ".product-price-container"],
    "hepsiburada": ["[data-test-id='price-current-price']", ".price"],
    "amazon": ["#corePrice_feature_div .a-price-whole", "#corePriceDisplay_desktop_feature_div .a-price-whole",
               "#priceblock_ourprice"],
    "getir": ["[data-testid='product-price']"],
    "yemeksepeti": [".product-price"],
    "bim": [".product-price"],
    "koctas": [".price-new"],
    "teknosa": [".prc-first"],
    "mediamarkt": [".price"]
}


# --- YARDIMCI FONKSİYONLAR ---
def kod_standartlastir(kod):
    try:
        return str(kod).replace('.0', '').strip().zfill(7)
    except:
        return "0000000"


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


def sistemi_sifirla():
    if os.path.exists(FIYAT_DOSYASI):
        try:
            shutil.copy(FIYAT_DOSYASI, f"YEDEK_{datetime.now().strftime('%Y%m%d')}.xlsx")
        except:
            pass
        df = pd.DataFrame(columns=["Tarih", "Zaman", "Kod", "Madde_Adi", "Fiyat", "Kaynak", "URL"])
        with pd.ExcelWriter(FIYAT_DOSYASI, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Fiyat_Log', index=False)
        return True
    return False


# --- 🔥 OTOMATİK TARAYICI KURULUMU 🔥 ---
# Burası senin için kritik. Bilgisayarında Firefox yoksa bile indirip kurar.
def install_browsers():
    try:
        # Sadece firefox'u indirir, bilgisayarı yormaz.
        subprocess.run([sys.executable, "-m", "playwright", "install", "firefox"], check=True)
        # Linux sunucular için gerekli bağımlılıkları kontrol eder (sessizce)
        subprocess.run([sys.executable, "-m", "playwright", "install-deps", "firefox"], check=False)
    except Exception as e:
        print(f"Browser install warning: {e}")


# --- BOT MOTORU ---
def botu_calistir_core(status_callback=None):
    if status_callback: status_callback("⚙️ Tarayıcı Hazırlanıyor... (Firefox Engine)")

    # 1. Tarayıcıyı Kontrol Et / Kur
    install_browsers()

    # 2. Konfigürasyon Dosyalarını Eşle
    if os.path.exists(TXT_DOSYASI) and os.path.exists(EXCEL_DOSYASI):
        try:
            with open(TXT_DOSYASI, 'r', encoding='utf-8') as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            df = pd.read_excel(EXCEL_DOSYASI, sheet_name=SAYFA_ADI, dtype={'Kod': str})
            urls, sels, mans = [], [], []

            for i in range(len(df)):
                if i < len(lines):
                    line = lines[i]
                    p = line.split(None, 1)
                    first = p[0]
                    content = p[1] if len(p) > 1 else ""
                    if first.startswith("http"):
                        urls.append(first)
                        if any(m in first.lower() for m in MARKET_SELECTORLERI):
                            sels.append(None);
                            mans.append(None)
                        else:
                            pr = temizle_fiyat(content)
                            if pr:
                                mans.append(pr); sels.append(None)
                            else:
                                sels.append(content); mans.append(None)
                    else:
                        pr = temizle_fiyat(line)
                        urls.append(None);
                        sels.append(None);
                        mans.append(pr)
                else:
                    urls.append(None);
                    sels.append(None);
                    mans.append(None)
            df['URL'] = urls;
            df['CSS_Selector'] = sels;
            df['Manuel_Fiyat'] = mans
            with pd.ExcelWriter(EXCEL_DOSYASI, engine='openpyxl', mode='a', if_sheet_exists='replace') as w:
                df.to_excel(w, sheet_name=SAYFA_ADI, index=False)
        except:
            pass

    # 3. Listeyi Hazırla
    try:
        df = pd.read_excel(EXCEL_DOSYASI, sheet_name=SAYFA_ADI, dtype={'Kod': str})
        df['Kod'] = df['Kod'].astype(str).apply(kod_standartlastir)
        mask = (df['URL'].notna()) | (df['Manuel_Fiyat'].notna() & (df['Manuel_Fiyat'] > 0))
        takip = df[mask].copy()
    except Exception as e:
        return f"Excel Hatası: {e}"

    veriler = []
    total = len(takip)
    if status_callback: status_callback(f"🚀 {total} Ürün Taranıyor (Firefox Mode)...")

    # 4. SCRAPING BAŞLIYOR
    with sync_playwright() as p:
        # Firefox başlatılır. Senin bilgisayarında Chrome olsa bile bunu kullanır.
        browser = p.firefox.launch(headless=True)

        # User-Agent'ı Firefox olarak ayarlıyoruz (Cloudflare için)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
            viewport={"width": 1920, "height": 1080}
        )

        # Bot tespitini zorlaştıran script
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        for i, row in takip.iterrows():
            fiyat = 0.0
            kaynak = ""

            # Manuel Kontrol
            if pd.notna(row.get('Manuel_Fiyat')) and row.get('Manuel_Fiyat') > 0:
                fiyat = float(row['Manuel_Fiyat'])
                kaynak = "Manuel"

            # Otomatik Web
            elif pd.notna(row.get('URL')) and str(row['URL']).startswith("http"):
                url = row['URL']
                domain = urlparse(url).netloc.lower()
                selectors = []
                for m, s_list in MARKET_SELECTORLERI.items():
                    if m in domain: selectors = s_list; kaynak = f"Otomatik ({m})"; break

                # Özel CSS varsa ekle
                if not selectors and pd.notna(row.get('CSS_Selector')):
                    selectors = [str(row.get('CSS_Selector')).strip()]
                    kaynak = "Özel CSS"

                if selectors:
                    try:
                        page.goto(url, timeout=40000, wait_until="domcontentloaded")

                        # --- CİMRİ ÖZEL ---
                        if "cimri" in domain:
                            try:
                                # Pop-up kapatma denemesi (Görünmez modda tıklama)
                                try:
                                    kutu = page.locator(".cb-lb").first
                                    if kutu.is_visible(timeout=2000): kutu.click(force=True)
                                except:
                                    pass

                                page.wait_for_selector("div.rTdMX", timeout=5000)
                                elements = page.locator("div.rTdMX").all_inner_texts()
                                prices = [p for p in [temizle_fiyat(e) for e in elements] if p]
                                if prices:
                                    if len(prices) > 4: prices.sort(); prices = prices[1:-1]
                                    fiyat = sum(prices) / len(prices)
                                    kaynak = f"Cimri ({len(prices)})"
                            except:
                                # Regex Yedek
                                txt = page.locator("body").inner_text()
                                found = re.findall(r'(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*(?:TL|₺)', txt)
                                p_list = [temizle_fiyat(x) for x in found if temizle_fiyat(x)]
                                if p_list: fiyat = min(p_list); kaynak = "Cimri (Regex)"

                        # --- DİĞER MARKETLER ---
                        else:
                            stok_yok = False
                            if "amazon" in domain:
                                try:
                                    if "mevcut değil" in page.locator(
                                        "#availability").inner_text().lower(): stok_yok = True
                                except:
                                    pass

                            if not stok_yok:
                                for sel in selectors:
                                    try:
                                        if page.locator(sel).count() > 0:
                                            # Migros Tekil
                                            if "migros" in domain:
                                                el = page.locator(sel).first
                                                val = temizle_fiyat(el.inner_text())
                                                if val: fiyat = val; break
                                            # Genel Liste
                                            else:
                                                elements = page.locator(sel).all_inner_texts()
                                                for el in elements:
                                                    val = temizle_fiyat(el)
                                                    if val: fiyat = val; break
                                            if fiyat: break
                                    except:
                                        continue
                    except Exception as e:
                        print(f"Hata {url}: {e}")

            if fiyat and fiyat > 0:
                veriler.append({
                    "Tarih": datetime.now().strftime("%Y-%m-%d"),
                    "Zaman": datetime.now().strftime("%H:%M"),
                    "Kod": row.get('Kod'),
                    "Madde_Adi": row.get('Madde adı'),
                    "Fiyat": fiyat,
                    "Kaynak": kaynak,
                    "URL": row.get('URL')
                })
            time.sleep(random.uniform(0.5, 1.0))  # İnsan taklidi

        browser.close()

    # SONUÇLARI KAYDET (APPEND MODE)
    if veriler:
        df_new = pd.DataFrame(veriler)
        try:
            if not os.path.exists(FIYAT_DOSYASI):
                with pd.ExcelWriter(FIYAT_DOSYASI, engine='openpyxl') as writer:
                    df_new.to_excel(writer, sheet_name='Fiyat_Log', index=False)
            else:
                with pd.ExcelWriter(FIYAT_DOSYASI, engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
                    try:
                        start = writer.book['Fiyat_Log'].max_row
                    except:
                        start = 0
                    df_new.to_excel(writer, sheet_name='Fiyat_Log', index=False, header=False, startrow=start)
            return f"✅ {len(veriler)} Veri Eklendi"
        except Exception as e:
            return f"Kayıt Hatası: {e}"

    return "❌ Veri Bulunamadı"


# --- DASHBOARD MODU ---
def dashboard_modu():
    # Veri Yükleme
    def veri_yukle():
        if not os.path.exists(FIYAT_DOSYASI): return None, None
        try:
            df_f = pd.read_excel(FIYAT_DOSYASI, sheet_name="Fiyat_Log")
            if df_f.empty: return pd.DataFrame(), None
            df_f['Tarih'] = pd.to_datetime(df_f['Tarih'])
            df_f['Kod'] = df_f['Kod'].astype(str).apply(kod_standartlastir)
            df_f['Fiyat'] = pd.to_numeric(df_f['Fiyat'], errors='coerce')
            df_s = pd.read_excel(EXCEL_DOSYASI, sheet_name=SAYFA_ADI, dtype={'Kod': str})
            df_s['Kod'] = df_s['Kod'].astype(str).apply(kod_standartlastir)
            grup_map = {"01": "Gıda", "02": "Alkol", "03": "Giyim", "04": "Konut", "05": "Ev", "06": "Sağlık",
                        "07": "Ulaşım", "08": "İletişim", "09": "Eğlence", "10": "Eğitim", "11": "Lokanta",
                        "12": "Çeşitli"}
            df_s['Grup'] = df_s['Kod'].str[:2].map(grup_map)
            return df_f, df_s
        except:
            return None, None

    df_fiyat, df_sepet = veri_yukle()

    if df_fiyat is None or df_fiyat.empty:
        st.warning("Veri bekleniyor... Botu çalıştırın.")
    else:
        # PIVOT VE ANALİZ
        df_fiyat['Gun'] = df_fiyat['Tarih'].dt.date
        df_fiyat['Is_Manuel'] = df_fiyat['Kaynak'].astype(str).str.contains('Manuel', na=False)

        # Önceliklendirme (Manuel > Otomatik)
        def oncelik(x):
            return x[x['Is_Manuel']] if x['Is_Manuel'].any() else x

        df_clean = df_fiyat.groupby(['Kod', 'Gun']).apply(oncelik).reset_index(drop=True)

        pivot = df_clean.pivot_table(index='Kod', columns='Gun', values='Fiyat', aggfunc='mean').ffill(axis=1).bfill(
            axis=1)

        if not pivot.empty:
            df_analiz = pd.merge(df_sepet, pivot, on='Kod', how='left').dropna(subset=['Agirlik_2025'])
            gunler = sorted(pivot.columns)
            baz, son = gunler[0], gunler[-1]

            # Trend Hesapla
            trend_data = []
            for g in gunler:
                tmp = df_analiz.dropna(subset=[g, baz])
                if not tmp.empty:
                    val = ((tmp[g] / tmp[baz]) * 100 * tmp['Agirlik_2025']).sum() / tmp['Agirlik_2025'].sum()
                    trend_data.append({"Tarih": g, "TÜFE": val})

            df_trend = pd.DataFrame(trend_data)
            son_tufe = df_trend['TÜFE'].iloc[-1]
            enflasyon = ((son_tufe / df_trend['TÜFE'].iloc[0]) - 1) * 100

            # EKRAN
            st.title(f"🟡 ENFLASYON: %{enflasyon:.2f}")

            col1, col2 = st.columns([3, 1])
            with col1:
                st.plotly_chart(px.area(df_trend, x='Tarih', y='TÜFE', color_discrete_sequence=['#ebc71d']),
                                use_container_width=True)
            with col2:
                df_analiz['Fark'] = (df_analiz[son] / df_analiz[baz]) - 1
                top = df_analiz.sort_values('Fark', ascending=False).head(5)
                st.markdown("**🔥 En Çok Artanlar**")
                st.dataframe(top[['Madde adı', 'Fark']], hide_index=True)

    # --- YÖNETİM PANELİ ---
    st.markdown("---")
    st.markdown('<div class="admin-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("**📂 Excel Yükle**")
        uf = st.file_uploader("", type=['xlsx'], label_visibility="collapsed")
        if uf:
            pd.read_excel(uf).to_excel(FIYAT_DOSYASI, sheet_name='Fiyat_Log', index=False)
            st.success("Yüklendi!")

    with c2:
        st.markdown("**🚀 Botu Çalıştır**")
        if st.button("Verileri Çek", type="primary", use_container_width=True):
            status = st.empty()
            res = botu_calistir_core(lambda m: status.info(m))
            if "Eklendi" in res:
                status.success(res); time.sleep(2); st.rerun()
            else:
                status.error(res)

    with c3:
        st.markdown("**⚠️ Sıfırla**")
        if st.button("Sıfırla", use_container_width=True):
            sistemi_sifirla()
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    dashboard_modu()