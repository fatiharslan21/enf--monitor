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
import shutil
import random

# --- 1. SAYFA AYARLARI ---
st.set_page_config(page_title="ENFLASYON MONITORU (Firefox)", page_icon="🦊", layout="wide",
                   initial_sidebar_state="collapsed")

# --- CSS SİHİRBAZLIĞI (Arayüz Aynı Kaldı) ---
st.markdown("""
    <style>
        [data-testid="stSidebar"] {display: none;}
        [data-testid="stToolbar"] {visibility: hidden !important;} 
        [data-testid="stHeader"] {visibility: hidden !important;}
        header {visibility: hidden !important;} 
        .stDeployButton {display:none !important;} 
        footer {visibility: hidden;} 
        #MainMenu {visibility: hidden;}
        .stApp {background-color: #F8F9FA; color: #212529;}

        /* Ticker */
        .ticker-wrap {
            width: 100%; overflow: hidden; background-color: #FFFFFF;
            border-bottom: 3px solid #ff5722; white-space: nowrap; /* Firefox Turuncusu */
            padding: 12px 0; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 20px;
        }
        .ticker { display: inline-block; animation: ticker 60s linear infinite; }
        .ticker-item { display: inline-block; padding: 0 2rem; font-family: 'Segoe UI', sans-serif; font-weight: 600; font-size: 14px; }
        @keyframes ticker { 0% { transform: translateX(100%); } 100% { transform: translateX(-100%); } }

        /* Kartlar */
        div[data-testid="metric-container"] {
            background: #FFFFFF; border: 1px solid #EAEDF0; border-radius: 12px; padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.02); transition: all 0.3s ease;
        }
        div[data-testid="metric-container"]:hover {
            transform: translateY(-3px); box-shadow: 0 8px 20px rgba(0,0,0,0.08); border-color: #ff5722;
        }

        .admin-panel {
            background-color: #FFFFFF; border-top: 4px solid #ff5722; padding: 30px;
            border-radius: 15px; margin-top: 50px; box-shadow: 0 -5px 25px rgba(0,0,0,0.05);
        }
        .signature { text-align: center; padding: 20px; color: #adb5bd; font-size: 12px; }
    </style>
""", unsafe_allow_html=True)

# --- 2. AYARLAR ---
BASE_DIR = os.getcwd()
TXT_DOSYASI = "URL VE CSS.txt"
EXCEL_DOSYASI = "TUFE_Konfigurasyon.xlsx"
FIYAT_DOSYASI = "Fiyat_Veritabani.xlsx"
PROFIL_KLASORU = os.path.join(BASE_DIR, "firefox_profil_data")  # Firefox Hafızası
SAYFA_ADI = "Madde_Sepeti"

# --- MARKET SEÇİCİLERİ (Güncellendi) ---
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


# --- 3. YARDIMCI FONKSİYONLAR ---
def get_local_python():
    if os.name == 'nt':
        return sys.executable
    return sys.executable


def baslangic_dosyasi_olustur():
    if not os.path.exists(FIYAT_DOSYASI):
        try:
            df = pd.DataFrame(columns=["Tarih", "Zaman", "Kod", "Madde_Adi", "Fiyat", "Kaynak", "URL"])
            with pd.ExcelWriter(FIYAT_DOSYASI, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Fiyat_Log', index=False)
        except:
            pass


baslangic_dosyasi_olustur()


def sistemi_sifirla():
    if os.path.exists(FIYAT_DOSYASI):
        yedek_ad = f"YEDEK_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        try:
            shutil.copy(FIYAT_DOSYASI, yedek_ad)
        except:
            pass
        df = pd.DataFrame(columns=["Tarih", "Zaman", "Kod", "Madde_Adi", "Fiyat", "Kaynak", "URL"])
        with pd.ExcelWriter(FIYAT_DOSYASI, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Fiyat_Log', index=False)
        return True
    return False


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


# --- TXT ve EXCEL SENKRONİZASYONU ---
def txt_dosyasini_excele_isle():
    if not os.path.exists(TXT_DOSYASI) or not os.path.exists(EXCEL_DOSYASI): return
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
                    selectors.append(None);
                    manual_prices.append(p if p else None)
            else:
                urls.append(None);
                selectors.append(None);
                manual_prices.append(None)

        df['URL'] = urls;
        df['CSS_Selector'] = selectors;
        df['Manuel_Fiyat'] = manual_prices
        with pd.ExcelWriter(EXCEL_DOSYASI, engine='openpyxl', mode='a', if_sheet_exists='replace') as w:
            df.to_excel(w, sheet_name=SAYFA_ADI, index=False)
    except:
        pass


# --- BOT MODU (FIREFOX ENTEGRASYONU - DÜZELTİLMİŞ) ---
# --- BOT MODU (FIREFOX - HIZLANDIRILMIŞ VERSİYON) ---
def botu_calistir_firefox(status_callback=None):
    import sys

    # Windows ise GÖRÜNÜR, Linux (Streamlit Cloud) ise GİZLİ çalış
    is_windows = os.name == 'nt'
    headless_mode = not is_windows

    if status_callback:
        mode_text = "GÖRÜNÜR MOD (PC)" if is_windows else "GİZLİ MOD (Sunucu)"
        status_callback(f"Firefox Başlatılıyor... ({mode_text})")

    # 1. Gerekli Kurulumlar
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "firefox"], check=False)
    except:
        pass

    txt_dosyasini_excele_isle()

    # 2. Excel Oku
    try:
        df = pd.read_excel(EXCEL_DOSYASI, sheet_name=SAYFA_ADI, dtype={'Kod': str})
        df['Kod'] = df['Kod'].apply(kod_standartlastir)
        mask = (df['URL'].notna()) | (df['Manuel_Fiyat'].notna())
        takip = df[mask].copy()
    except:
        return "Excel Hatası"

    veriler = []

    if not os.path.exists(PROFIL_KLASORU): os.makedirs(PROFIL_KLASORU)

    if status_callback: status_callback(f"Hedef: {len(takip)} Ürün. Hafıza yükleniyor...")

    with sync_playwright() as p:
        # Hafızalı Tarayıcıyı Aç
        browser = p.firefox.launch_persistent_context(
            user_data_dir=PROFIL_KLASORU,
            headless=headless_mode,
            viewport={"width": 1366, "height": 768},
            # Windows'ta biraz bekleme payı koyuyoruz ki Cloudflare bizi insan sansın
            # Ama sayfa yüklendiği an veriyi alıp geçeceğiz
            slow_mo=50 if is_windows else 0,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
        )

        page = browser.pages[0] if browser.pages else browser.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        for i, row in takip.iterrows():
            if status_callback: status_callback(
                f"İşleniyor ({i + 1}/{len(takip)}): {str(row.get('Madde adı'))[:15]}...")

            fiyat = 0.0
            kaynak = ""
            url = row['URL']

            # Manuel Fiyat Varsa Direkt Geç
            if pd.notna(row.get('Manuel_Fiyat')) and float(row.get('Manuel_Fiyat') or 0) > 0:
                fiyat = float(row['Manuel_Fiyat'])
                kaynak = "Manuel"
                veriler.append({"Tarih": datetime.now().strftime("%Y-%m-%d"), "Zaman": datetime.now().strftime("%H:%M"),
                                "Kod": row.get('Kod'), "Madde_Adi": row.get('Madde adı'), "Fiyat": fiyat,
                                "Kaynak": kaynak, "URL": url})
                continue  # Döngünün başına dön

            # Link Kontrolü
            if pd.notna(url) and str(url).startswith("http"):
                domain = urlparse(url).netloc.lower()
                selectors = []
                for m, s_list in MARKET_SELECTORLERI.items():
                    if m in domain: selectors = s_list; kaynak = f"Otomatik ({m})"; break
                if not selectors and pd.notna(row.get('CSS_Selector')):
                    selectors = [str(row.get('CSS_Selector')).strip()]
                    kaynak = "Özel CSS"

                if selectors:
                    try:
                        # Sayfaya Git
                        page.goto(url, timeout=60000, wait_until="domcontentloaded")

                        # --- CİMRİ ÖZEL MANTIĞI (REVİZE EDİLDİ) ---
                        if "cimri" in domain:
                            # 1. ADIM: HIZLI KONTROL (Fiyat zaten var mı?)
                            # Eğer fiyat listesi görünüyorsa, robot kontrolünü TAMAMEN ATLA.
                            fiyat_gorundu_mu = False
                            try:
                                # Yarım saniye içinde fiyat görünüyor mu bak
                                if page.locator("div.rTdMX").first.is_visible(timeout=500):
                                    fiyat_gorundu_mu = True
                            except:
                                pass

                            # Fiyat yoksa Robot Kontrolü Yap
                            if not fiyat_gorundu_mu:
                                try:
                                    # Cloudflare kutusu var mı?
                                    kutu = page.locator(".cb-lb").first
                                    if kutu.is_visible(timeout=2000):  # 2 saniye bekle, yoksa geç
                                        if is_windows:  # Sadece Windows'ta tıkla
                                            time.sleep(random.uniform(0.5, 1.5))
                                            kutu.hover()
                                            time.sleep(0.2)
                                            kutu.click()
                                            # Tıkladıktan sonra fiyatın gelmesini bekle
                                            page.wait_for_selector("div.rTdMX", timeout=5000)
                                except:
                                    pass

                            # 2. ADIM: FİYATI ÇEK
                            try:
                                # Selector'ı bekle (En fazla 3 saniye)
                                page.wait_for_selector("div.rTdMX", timeout=3000)
                                elements = page.locator("div.rTdMX").all_inner_texts()
                                prices = [p for p in [temizle_fiyat(e) for e in elements] if p]
                                if prices:
                                    if len(prices) > 4: prices.sort(); prices = prices[1:-1]
                                    fiyat = sum(prices) / len(prices)
                                    kaynak = f"Cimri ({len(prices)})"
                            except:
                                # Regex (Son Çare)
                                try:
                                    body = page.locator("body").inner_text()
                                    bulunanlar = re.findall(r'(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*(?:TL|₺)', body)
                                    fiyatlar = [temizle_fiyat(h) for h in bulunanlar if temizle_fiyat(h)]
                                    if fiyatlar:
                                        fiyatlar.sort()
                                        mantikli = fiyatlar[:max(1, len(fiyatlar) // 2)]
                                        fiyat = sum(mantikli) / len(mantikli)
                                        kaynak = "Cimri (Regex)"
                                except:
                                    pass

                        # --- DİĞER SİTELER ---
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
                                        # Amazon hariç diğerlerinde çok bekleme
                                        to = 3000 if "amazon" in domain else 1000
                                        try:
                                            page.wait_for_selector(sel, timeout=to)
                                        except:
                                            pass

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

                    except Exception as e:
                        print(f"Hata: {e}")

            if fiyat > 0:
                veriler.append({
                    "Tarih": datetime.now().strftime("%Y-%m-%d"),
                    "Zaman": datetime.now().strftime("%H:%M"),
                    "Kod": row.get('Kod'),
                    "Madde_Adi": row.get('Madde adı'),
                    "Fiyat": fiyat,
                    "Kaynak": kaynak,
                    "URL": row.get('URL')
                })

        browser.close()

    # Verileri Kaydet
    if veriler:
        df_new = pd.DataFrame(veriler)
        try:
            if not os.path.exists(FIYAT_DOSYASI):
                with pd.ExcelWriter(FIYAT_DOSYASI, engine='openpyxl') as w:
                    df_new.to_excel(w, sheet_name='Fiyat_Log', index=False)
            else:
                with pd.ExcelWriter(FIYAT_DOSYASI, engine='openpyxl', mode='a', if_sheet_exists='overlay') as w:
                    try:
                        start = w.sheets['Fiyat_Log'].max_row
                    except:
                        start = 0
                    df_new.to_excel(w, sheet_name='Fiyat_Log', index=False, header=False, startrow=start)
        except:
            pass
        return "OK"
    return "Veri Yok"


# --- DASHBOARD MODU ---
def dashboard_modu():
    def kod_standartlastir(kod):
        try:
            return str(kod).replace('.0', '').strip().zfill(7)
        except:
            return "0000000"

    def veri_yukle():
        if not os.path.exists(FIYAT_DOSYASI): return None, None
        try:
            df_f = pd.read_excel(FIYAT_DOSYASI, sheet_name="Fiyat_Log")
            if df_f.empty: return pd.DataFrame(), None
            df_f['Tarih'] = pd.to_datetime(df_f['Tarih'])
            df_f['Kod'] = df_f['Kod'].astype(str).apply(kod_standartlastir)
            df_f['Fiyat'] = pd.to_numeric(df_f['Fiyat'], errors='coerce')
            df_f.loc[df_f['Fiyat'] <= 0, 'Fiyat'] = np.nan

            df_s = pd.read_excel(EXCEL_DOSYASI, sheet_name=SAYFA_ADI, dtype={'Kod': str})
            df_s['Kod'] = df_s['Kod'].astype(str).apply(kod_standartlastir)
            grup_map = {"01": "Gıda", "02": "Alkol-Tütün", "03": "Giyim", "04": "Konut", "05": "Ev Eşyası",
                        "06": "Sağlık", "07": "Ulaştırma", "08": "Haberleşme", "09": "Eğlence", "10": "Eğitim",
                        "11": "Lokanta", "12": "Çeşitli"}
            df_s['Grup'] = df_s['Kod'].str[:2].map(grup_map)
            emoji_map = {"01": "🍎", "02": "🍷", "03": "👕", "04": "🏠", "05": "🛋️", "06": "💊", "07": "🚗", "08": "📱",
                         "09": "🎭", "10": "🎓", "11": "🍽️", "12": "💅"}
            df_s['Emoji'] = df_s['Kod'].str[:2].map(emoji_map).fillna("📦")
            return df_f, df_s
        except Exception as e:
            st.error(f"Veri Hatası: {e}");
            return None, None

    def veri_temizle_ve_pivotla(df_fiyat):
        df_fiyat['Gun'] = df_fiyat['Tarih'].dt.date
        df_fiyat['Kaynak'] = df_fiyat['Kaynak'].astype(str)
        df_fiyat['Is_Manuel'] = df_fiyat['Kaynak'].str.contains('Manuel', case=False, na=False)

        def oncelik_sec(x):
            if x['Is_Manuel'].any(): return x[x['Is_Manuel']]
            return x

        df_clean = df_fiyat.groupby(['Kod', 'Gun']).apply(oncelik_sec).reset_index(drop=True)

        def geo_mean(x):
            d = x.dropna();
            d = d[d > 0]
            return np.exp(np.mean(np.log(d))) if len(d) > 0 else np.nan

        pivot = df_clean.pivot_table(index='Kod', columns='Gun', values='Fiyat', aggfunc=geo_mean)
        pivot = pivot.ffill(axis=1).bfill(axis=1)
        return pivot

    # --- ANA EKRAN ---
    df_fiyat, df_sepet = veri_yukle()
    if df_fiyat is None or df_fiyat.empty:
        st.info("Veri bekleniyor... Aşağıdaki panelden Veri Yükleyin veya Botu Çalıştırın.");
    else:
        pivot = veri_temizle_ve_pivotla(df_fiyat)
        if not pivot.empty:
            df_analiz = pd.merge(df_sepet, pivot, on='Kod', how='left').dropna(subset=['Agirlik_2025'])
            gunler = sorted(pivot.columns)
            baz_gun, son_gun = gunler[0], gunler[-1]

            trend_data = []
            for g in gunler:
                temp = df_analiz.copy().dropna(subset=[g, baz_gun])
                if not temp.empty:
                    toplam_ag = temp['Agirlik_2025'].sum()
                    temp['Puan'] = (temp[g] / temp[baz_gun]) * 100 * (temp['Agirlik_2025'])
                    val = temp['Puan'].sum() / toplam_ag if toplam_ag > 0 else 100
                    trend_data.append({"Tarih": g, "TÜFE": val})
            df_trend = pd.DataFrame(trend_data)

            if not df_trend.empty:
                son_tufe = df_trend['TÜFE'].iloc[-1]
                aylik_deg = ((son_tufe / df_trend['TÜFE'].iloc[-2]) - 1) * 100 if len(df_trend) > 1 else 0
                toplam_deg = ((son_tufe / df_trend['TÜFE'].iloc[0]) - 1) * 100
                df_analiz['Fark'] = (df_analiz[son_gun] / df_analiz[baz_gun]) - 1
                top_artis = df_analiz.sort_values('Fark', ascending=False).iloc[0]

                # TICKER
                ticker_html = ""
                top_up = df_analiz.sort_values('Fark', ascending=False).head(5)
                top_down = df_analiz.sort_values('Fark', ascending=True).head(5)
                ticker_items = pd.concat([top_up, top_down])
                for _, r in ticker_items.iterrows():
                    val = r['Fark']
                    color = "#dc3545" if val > 0 else ("#28a745" if val < 0 else "#6c757d")
                    text = f"{'▲' if val > 0 else '▼'} {r['Madde adı']} %{val * 100:.1f}"
                    ticker_html += f"<span style='color:{color}'>{text}</span> &nbsp;&nbsp;&nbsp;&nbsp; "
                st.markdown(
                    f"""<div class="ticker-wrap"><div class="ticker"><div class="ticker-item">{ticker_html}</div></div></div>""",
                    unsafe_allow_html=True)

                st.title("🦊 ENFLASYON MONİTÖRÜ (Firefox Edition)")

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("ENDEKS", f"{son_tufe:.2f}", "Baz: 100")
                c2.metric("ENFLASYON (KÜMÜLATİF)", f"%{toplam_deg:.2f}", f"{aylik_deg:.2f}% (Günlük)",
                          delta_color="inverse")
                c3.metric("EN YÜKSEK ARTIŞ", f"{top_artis['Madde adı'][:12]}..", f"%{top_artis['Fark'] * 100:.1f}",
                          delta_color="inverse")
                c4.metric("VERİ GÜVENİ", f"%{100 - (df_analiz[son_gun].isna().sum() / len(df_analiz) * 100):.0f}",
                          f"{len(gunler)} Gün")

                st.markdown("---")
                # Grafikler
                c_left, c_right = st.columns([2, 1])
                with c_left:
                    fig_area = px.area(df_trend, x='Tarih', y='TÜFE', markers=True, color_discrete_sequence=['#ff5722'])
                    st.plotly_chart(fig_area, use_container_width=True)
                with c_right:
                    val = min(max(0, abs(toplam_deg)), 100)
                    fig_gauge = go.Figure(go.Indicator(mode="gauge+number", value=val,
                                                       gauge={'axis': {'range': [None, 50]},
                                                              'bar': {'color': "#dc3545"}, 'bgcolor': "white"}))
                    st.plotly_chart(fig_gauge, use_container_width=True)

                # Tablar
                tab1, tab2, tab3 = st.tabs(["SEKTÖREL", "DETAYLI LİSTE", "SİMÜLASYON"])
                with tab1:
                    df_analiz['Grup_Degisim'] = df_analiz.groupby('Grup')['Fark'].transform('mean') * 100
                    grup_data = df_analiz[['Grup', 'Grup_Degisim']].drop_duplicates().sort_values('Grup_Degisim')
                    fig_bar = go.Figure(go.Bar(y=grup_data['Grup'], x=grup_data['Grup_Degisim'], orientation='h',
                                               marker=dict(color=grup_data['Grup_Degisim'], colorscale='RdYlGn_r')))
                    st.plotly_chart(fig_bar, use_container_width=True)
                with tab2:
                    st.dataframe(df_analiz[['Kod', 'Madde adı', 'Grup', 'Fark', son_gun]], use_container_width=True)
                with tab3:
                    st.info("Simülasyon Modülü Aktif")

    # --- ALT YÖNETİM PANELİ ---
    st.markdown("---")
    st.markdown('<div class="admin-panel"><div class="admin-header">⚙️ SİSTEM YÖNETİMİ</div>', unsafe_allow_html=True)
    c_load, c_bot, c_reset = st.columns(3)

    with c_load:
        st.markdown("**📂 Excel Yükle**")
        uf = st.file_uploader("Fiyat_Veritabani.xlsx", type=['xlsx'], label_visibility="collapsed")
        if uf:
            try:
                xls = pd.ExcelFile(uf)
                sheet = "Fiyat_Log" if "Fiyat_Log" in xls.sheet_names else xls.sheet_names[0]
                df_temp = pd.read_excel(uf, sheet_name=sheet)
                with pd.ExcelWriter(FIYAT_DOSYASI, engine='openpyxl') as writer:
                    df_temp.to_excel(writer, sheet_name='Fiyat_Log', index=False)
                st.success("Yüklendi!")
                time.sleep(1);
                st.rerun()
            except:
                st.error("Hata")

    with c_bot:
        st.markdown("**🦊 Firefox Botu Çalıştır**")
        if st.button("Verileri Çek (Anti-Detect)", type="primary", use_container_width=True):
            placeholder = st.empty()

            def update_status(msg):
                placeholder.info(f"⚙️ {msg}")

            try:
                # Subprocess yerine direkt fonksiyonu çağırıyoruz ki output görebilelim
                res = botu_calistir_firefox(update_status)
                placeholder.success("İşlem Tamamlandı! Sayfa yenileniyor...")
                time.sleep(2)
                st.rerun()
            except Exception as e:
                placeholder.error(f"Bot Hatası: {e}")

    with c_reset:
        st.markdown("**⚠️ Sıfırla**")
        if st.button("Sıfırla", type="secondary", use_container_width=True):
            sistemi_sifirla();
            st.success("Sıfırlandı!");
            time.sleep(1);
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="signature">Fatih Arslan Tarafından yapılmıştır</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--bot-modu":
        botu_calistir_firefox()
    else:
        dashboard_modu()