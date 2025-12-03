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

# --- PLATFORM KONTROLÜ (LINUX/WINDOWS UYUMU) ---
try:
    import winreg
except ImportError:
    winreg = None

# --- 1. SAYFA AYARLARI ---
st.set_page_config(page_title="ENFLASYON MONITORU", page_icon="🏦", layout="wide", initial_sidebar_state="collapsed")

# --- CSS SİHİRBAZLIĞI ---
st.markdown("""
    <style>
        /* Sidebar ve Üst Bar Gizle */
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
            border-bottom: 2px solid #ebc71d; white-space: nowrap;
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
            transform: translateY(-3px); box-shadow: 0 8px 20px rgba(0,0,0,0.08); border-color: #ebc71d;
        }

        /* Alt Panel */
        .admin-panel {
            background-color: #FFFFFF; border-top: 4px solid #ebc71d; padding: 30px;
            border-radius: 15px; margin-top: 50px; box-shadow: 0 -5px 25px rgba(0,0,0,0.05);
        }
        .admin-header {
            font-size: 20px; font-weight: bold; color: #2C3E50; margin-bottom: 20px; border-bottom: 1px solid #eee; padding-bottom: 10px;
        }

        /* İmza Stili */
        .signature {
            text-align: center;
            padding: 20px;
            color: #adb5bd;
            font-size: 12px;
            font-family: 'Segoe UI', sans-serif;
            margin-top: 20px;
        }
    </style>
""", unsafe_allow_html=True)

# --- 2. AYARLAR ---
BASE_DIR = os.getcwd()
TXT_DOSYASI = "URL VE CSS.txt"
EXCEL_DOSYASI = "TUFE_Konfigurasyon.xlsx"
FIYAT_DOSYASI = "Fiyat_Veritabani.xlsx"
SAYFA_ADI = "Madde_Sepeti"

# --- MARKET SEÇİCİLERİ (GÜNCELLENMİŞ) ---
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
        user_profile = os.environ.get('USERPROFILE')
        local_py = os.path.join(user_profile, "Desktop", ".venv", "Scripts", "python.exe")
        return local_py if os.path.exists(local_py) else sys.executable
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
        yedek_ad = f"YEDEK_Fiyat_DB_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        try:
            shutil.copy(FIYAT_DOSYASI, os.path.join(BASE_DIR, yedek_ad))
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


# --- BOT MOTORU (FIREFOX ENTEGRASYONLU) ---
def botu_calistir_core(status_callback=None):
    if status_callback: status_callback("🔧 Bot Hazırlanıyor (Firefox Mode)...")

    # Playwright Kurulum Kontrolü (Streamlit Cloud için önemli)
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "firefox"], check=False)
    except:
        pass

    # TXT Dosyasını Excel'e Senkronize Et
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
        except Exception as e:
            if status_callback: status_callback(f"Excel Sync Hatası: {e}")

    # Veriyi Oku
    try:
        df = pd.read_excel(EXCEL_DOSYASI, sheet_name=SAYFA_ADI, dtype={'Kod': str})
        df['Kod'] = df['Kod'].astype(str).apply(kod_standartlastir)
        mask = (df['URL'].notna()) | (df['Manuel_Fiyat'].notna() & (df['Manuel_Fiyat'] > 0))
        takip = df[mask].copy()
    except:
        return "Excel Okuma Hatası"

    veriler = []
    total = len(takip)
    if status_callback: status_callback(f"🚀 Hedef: {total} Ürün (Taranıyor)...")

    # --- FIREFOX İLE SCRAPING ---
    with sync_playwright() as p:
        # Streamlit Cloud'da Headless=True olmalı. Firefox tespit edilmesi daha zordur.
        browser = p.firefox.launch(headless=True)

        # Kullanıcı ajanı sahtekarlığı (Cloudflare için)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
        )

        # Webdriver özelliğini gizle (JS Enjeksiyonu)
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        for i, row in takip.iterrows():
            fiyat = 0.0
            kaynak = ""

            # 1. Manuel
            if pd.notna(row.get('Manuel_Fiyat')) and row.get('Manuel_Fiyat') > 0:
                fiyat = float(row['Manuel_Fiyat'])
                kaynak = "Manuel"

            # 2. Otomatik
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
                        # Sayfaya Git
                        page.goto(url, timeout=45000, wait_until="domcontentloaded")

                        # --- CIMRI ÖZEL MANTIK ---
                        if "cimri" in domain:
                            try:
                                # Kutu tıklama simülasyonu
                                try:
                                    kutu = page.locator(".cb-lb").first
                                    if kutu.is_visible(timeout=3000):
                                        kutu.click(force=True)  # Headless modda mouse hover zor, click force
                                        time.sleep(2)
                                except:
                                    pass

                                # Fiyatları Topla
                                page.wait_for_selector("div.rTdMX", timeout=5000)
                                elements = page.locator("div.rTdMX").all_inner_texts()
                                prices = [p for p in [temizle_fiyat(e) for e in elements] if p]
                                if prices:
                                    if len(prices) > 4: prices.sort(); prices = prices[1:-1]
                                    fiyat = sum(prices) / len(prices)
                                    kaynak = f"Cimri ({len(prices)})"
                            except:
                                # Regex Yedek Planı
                                try:
                                    body_txt = page.locator("body").inner_text()
                                    bulunanlar = re.findall(r'(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*(?:TL|₺)',
                                                            body_txt)
                                    f_list = [temizle_fiyat(x) for x in bulunanlar if temizle_fiyat(x)]
                                    if f_list:
                                        fiyat = min(f_list)  # En düşük fiyat mantıklı olabilir
                                        kaynak = "Cimri (Regex)"
                                except:
                                    pass

                        # --- GENEL MARKET MANTIĞI ---
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
                                            # Migros özel
                                            if "migros" in domain:
                                                el = page.locator(sel).first
                                                val = temizle_fiyat(el.inner_text())
                                                if val: fiyat = val; break
                                            # Genel
                                            else:
                                                elements = page.locator(sel).all_inner_texts()
                                                for el in elements:
                                                    val = temizle_fiyat(el)
                                                    if val: fiyat = val; break
                                            if fiyat: break
                                    except:
                                        continue
                    except Exception as e:
                        print(f"Hata URL: {url} -> {e}")

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

            # İnsan taklidi için minik bekleme
            time.sleep(random.uniform(0.5, 1.5))

        browser.close()

    if veriler:
        df_new = pd.DataFrame(veriler)
        try:
            # APPEND MODE (Mevcut dosyanın altına ekle)
            if not os.path.exists(FIYAT_DOSYASI):
                with pd.ExcelWriter(FIYAT_DOSYASI, engine='openpyxl') as writer:
                    df_new.to_excel(writer, sheet_name='Fiyat_Log', index=False)
            else:
                with pd.ExcelWriter(FIYAT_DOSYASI, engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
                    try:
                        # Son satırı bul
                        if 'Fiyat_Log' in writer.book.sheetnames:
                            start_row = writer.book['Fiyat_Log'].max_row
                        else:
                            start_row = 0
                        df_new.to_excel(writer, sheet_name='Fiyat_Log', index=False, header=False, startrow=start_row)
                    except:
                        # Yedek plan
                        df_new.to_excel(writer, sheet_name='Fiyat_Log', index=False)
            return f"{len(veriler)} Veri Eklendi"
        except Exception as e:
            return f"Kaydetme Hatası: {e}"

    return "Veri Bulunamadı"


# --- DASHBOARD MODU ---
def dashboard_modu():
    python_exe = get_local_python()

    def veri_yukle():
        if not os.path.exists(FIYAT_DOSYASI): return None, None
        try:
            # 1. Fiyatları Yükle
            df_f = pd.read_excel(FIYAT_DOSYASI, sheet_name="Fiyat_Log")
            if df_f.empty: return pd.DataFrame(), None

            df_f['Tarih'] = pd.to_datetime(df_f['Tarih'])
            df_f['Kod'] = df_f['Kod'].astype(str).apply(kod_standartlastir)
            df_f['Fiyat'] = pd.to_numeric(df_f['Fiyat'], errors='coerce')
            df_f.loc[df_f['Fiyat'] <= 0, 'Fiyat'] = np.nan

            # 2. Sepeti Yükle
            df_s = pd.read_excel(EXCEL_DOSYASI, sheet_name=SAYFA_ADI, dtype={'Kod': str})
            df_s['Kod'] = df_s['Kod'].astype(str).apply(kod_standartlastir)
            grup_map = {"01": "Gıda", "02": "Alkol-Tütün", "03": "Giyim", "04": "Konut", "05": "Ev Eşyası",
                        "06": "Sağlık", "07": "Ulaştırma", "08": "Haberleşme", "09": "Eğlence", "10": "Eğitim",
                        "11": "Lokanta", "12": "Çeşitli"}
            df_s['Grup'] = df_s['Kod'].str[:2].map(grup_map)

            # Emoji
            emoji_map = {"01": "🍎", "02": "🍷", "03": "👕", "04": "🏠", "05": "🛋️", "06": "💊", "07": "🚗", "08": "📱",
                         "09": "🎭", "10": "🎓", "11": "🍽️", "12": "💅"}
            df_s['Emoji'] = df_s['Kod'].str[:2].map(emoji_map).fillna("📦")

            return df_f, df_s
        except Exception as e:
            st.error(f"Veri Hatası: {e}")
            return None, None

    # --- HESAPLAMA VE ÖNCELİKLENDİRME ---
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
                    if val == 0:
                        color = "#6c757d";
                        text = f"▬ {r['Madde adı']} DEĞİŞİM YOK"
                    elif val > 0:
                        color = "#dc3545";
                        text = f"▲ {r['Madde adı']} %{val * 100:.1f}"
                    else:
                        color = "#28a745";
                        text = f"▼ {r['Madde adı']} %{val * 100:.1f}"
                    ticker_html += f"<span style='color:{color}'>{text}</span> &nbsp;&nbsp;&nbsp;&nbsp; "

                st.markdown(
                    f"""<div class="ticker-wrap"><div class="ticker"><div class="ticker-item">CANLI PİYASA AKIŞI: &nbsp;&nbsp; {ticker_html}</div></div></div>""",
                    unsafe_allow_html=True)

                st.title("🟡 ENFLASYON MONİTÖRÜ")

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("ENDEKS", f"{son_tufe:.2f}", "Baz: 100")
                c2.metric("ENFLASYON (KÜMÜLATİF)", f"%{toplam_deg:.2f}", f"{aylik_deg:.2f}% (Günlük)",
                          delta_color="inverse")
                c3.metric("EN YÜKSEK ARTIŞ", f"{top_artis['Madde adı'][:12]}..", f"%{top_artis['Fark'] * 100:.1f}",
                          delta_color="inverse")
                c4.metric("VERİ GÜVENİ", f"%{100 - (df_analiz[son_gun].isna().sum() / len(df_analiz) * 100):.0f}",
                          f"{len(gunler)} Gün")

                st.markdown("---")
                c_left, c_right = st.columns([2, 1])
                with c_left:
                    fig_area = px.area(df_trend, x='Tarih', y='TÜFE', markers=True, color_discrete_sequence=['#ebc71d'])
                    fig_area.update_layout(plot_bgcolor='white', xaxis=dict(showgrid=False),
                                           yaxis=dict(gridcolor='#f0f0f0'))
                    st.plotly_chart(fig_area, use_container_width=True)
                with c_right:
                    val = min(max(0, abs(toplam_deg)), 100)
                    fig_gauge = go.Figure(go.Indicator(mode="gauge+number", value=val,
                                                       gauge={'axis': {'range': [None, 50]},
                                                              'bar': {'color': "#dc3545"}, 'bgcolor': "white"}))
                    st.plotly_chart(fig_gauge, use_container_width=True)

                tab1, tab2, tab3, tab4 = st.tabs(["SEKTÖREL", "ETKİ ANALİZİ", "DETAYLI LİSTE", "SİMÜLASYON"])
                with tab1:
                    df_analiz['Grup_Degisim'] = df_analiz.groupby('Grup')['Fark'].transform('mean') * 100
                    grup_data = df_analiz[['Grup', 'Grup_Degisim']].drop_duplicates().sort_values('Grup_Degisim')
                    fig_bar = go.Figure(go.Bar(y=grup_data['Grup'], x=grup_data['Grup_Degisim'], orientation='h',
                                               marker=dict(color=grup_data['Grup_Degisim'], colorscale='RdYlGn_r',
                                                           showscale=False)))
                    st.plotly_chart(fig_bar, use_container_width=True)
                with tab2:
                    grup_katki = df_analiz.groupby('Grup')['Fark'].mean().sort_values(ascending=False).head(10) * 100
                    fig_water = go.Figure(
                        go.Waterfall(orientation="v", measure=["relative"] * len(grup_katki), x=grup_katki.index,
                                     y=grup_katki.values, text=[f"%{x:.2f}" for x in grup_katki.values],
                                     connector={"line": {"color": "#333"}}, decreasing={"marker": {"color": "#28a745"}},
                                     increasing={"marker": {"color": "#dc3545"}}))
                    st.plotly_chart(fig_water, use_container_width=True)
                with tab3:
                    col_search, col_space = st.columns([3, 1])
                    arama_terimi = col_search.text_input("🔎 Ürün Ara...", "")
                    cols_recent = gunler[-15:] if len(gunler) > 15 else gunler
                    df_show = df_analiz.copy()
                    if arama_terimi:
                        keywords = arama_terimi.lower().split()
                        mask = np.ones(len(df_show), dtype=bool)
                        for k in keywords: mask &= df_show['Madde adı'].astype(str).str.contains(k, case=False,
                                                                                                 na=False)
                        df_show = df_show[mask]
                    df_show['Trend'] = df_show[cols_recent].values.tolist()
                    son_gun_str = "Son Fiyat"
                    df_show[son_gun_str] = df_show[son_gun]
                    df_show['Ürün'] = df_show['Emoji'] + " " + df_show['Madde adı']
                    st.dataframe(df_show[['Kod', 'Ürün', 'Grup', 'Trend', 'Fark', son_gun_str]],
                                 column_config={"Trend": st.column_config.LineChartColumn("Son 15 Gün", y_min=0),
                                                "Fark": st.column_config.ProgressColumn("Değişim", format="%.2f%%",
                                                                                        min_value=-0.5, max_value=0.5),
                                                son_gun_str: st.column_config.NumberColumn("Fiyat (TL)",
                                                                                           format="%.2f ₺")},
                                 hide_index=True, use_container_width=True, height=600)
                with tab4:
                    st.subheader("🔮 Gelecek Simülasyonu")
                    gruplar = sorted(df_analiz['Grup'].unique())
                    cols = st.columns(4)
                    sim_inputs = {}
                    for i, grp in enumerate(gruplar):
                        with cols[i % 4]:
                            sim_inputs[grp] = st.number_input(f"{grp} (%)", min_value=-100.0, max_value=100.0,
                                                              value=0.0, step=1.0)
                    tahmini_artis_toplam = 0
                    toplam_agirlik = df_analiz['Agirlik_2025'].sum()
                    for grp, artis in sim_inputs.items():
                        grp_agirlik = df_analiz[df_analiz['Grup'] == grp]['Agirlik_2025'].sum()
                        etki = (grp_agirlik / toplam_agirlik) * artis
                        tahmini_artis_toplam += etki
                    yeni_enf = toplam_deg + tahmini_artis_toplam
                    st.divider()
                    c_sim_res1, c_sim_res2 = st.columns(2)
                    c_sim_res1.metric("Mevcut Enflasyon", f"%{toplam_deg:.2f}")
                    c_sim_res2.metric("Simülasyon Sonucu", f"%{yeni_enf:.2f}", f"{tahmini_artis_toplam:+.2f}% Etki",
                                      delta_color="inverse")

    # --- ALT YÖNETİM PANELİ ---
    st.markdown("---")
    st.markdown('<div class="admin-panel"><div class="admin-header">⚙️ SİSTEM YÖNETİMİ</div>', unsafe_allow_html=True)
    c_load, c_bot, c_reset = st.columns(3)

    with c_load:
        st.markdown("**📂 Excel'den Yükle**")
        uf = st.file_uploader("Fiyat_Veritabani.xlsx", type=['xlsx'], label_visibility="collapsed")
        if uf:
            try:
                xls = pd.ExcelFile(uf)
                sheet = "Fiyat_Log" if "Fiyat_Log" in xls.sheet_names else xls.sheet_names[0]
                df_temp = pd.read_excel(uf, sheet_name=sheet)
                with pd.ExcelWriter(FIYAT_DOSYASI, engine='openpyxl') as writer:
                    df_temp.to_excel(writer, sheet_name='Fiyat_Log', index=False)
                st.success("Veriler Güncellendi!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Dosya hatası: {e}")

    with c_bot:
        st.markdown("**🚀 Botu Çalıştır (Firefox)**")
        # Streamlit içinde butonla tetiklenen fonksiyon
        if st.button("Verileri Çek", type="primary", use_container_width=True):
            with st.spinner("Firefox Başlatılıyor..."):
                status_placeholder = st.empty()
                sonuc = botu_calistir_core(lambda msg: status_placeholder.info(msg))
                if "Hata" not in sonuc:
                    status_placeholder.success(f"İşlem Tamam! {sonuc}")
                    time.sleep(2)
                    st.rerun()
                else:
                    status_placeholder.error(sonuc)

    with c_reset:
        st.markdown("**⚠️ Sıfırla**")
        if st.button("Sıfırla (Bugün=100)", type="secondary", use_container_width=True):
            sistemi_sifirla();
            st.success("Sıfırlandı!");
            time.sleep(1);
            st.rerun()

    if os.path.exists(FIYAT_DOSYASI):
        with open(FIYAT_DOSYASI, "rb") as f:
            st.download_button("📊 Raporu İndir", f, file_name="Enflasyon_Rapor.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="signature">Fatih Arslan Tarafından yapılmıştır</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--bot-modu":
        # Komut satırından çalıştırma (Opsiyonel)
        print(botu_calistir_core())
    else:
        dashboard_modu()