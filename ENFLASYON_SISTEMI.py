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

# --- 1. SAYFA VE TASARIM AYARLARI ---
st.set_page_config(page_title="ENFLASYON MONITORU", page_icon="🏦", layout="wide", initial_sidebar_state="collapsed")

# --- CSS (ESKİ HAVALI TASARIM) ---
st.markdown("""
    <style>
        /* Temel Gizlemeler */
        [data-testid="stSidebar"] {display: none;}
        [data-testid="stToolbar"] {visibility: hidden !important;} 
        [data-testid="stHeader"] {visibility: hidden !important;}
        .stDeployButton {display:none !important;} 
        footer {visibility: hidden;} 
        #MainMenu {visibility: hidden;}

        .stApp {background-color: #F8F9FA; color: #212529;}

        /* Ticker (Kayan Yazı) */
        .ticker-wrap {
            width: 100%; overflow: hidden; background-color: #FFFFFF;
            border-bottom: 2px solid #ebc71d; white-space: nowrap;
            padding: 12px 0; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 20px;
        }
        .ticker { display: inline-block; animation: ticker 60s linear infinite; }
        .ticker-item { display: inline-block; padding: 0 2rem; font-family: 'Segoe UI', sans-serif; font-weight: 600; font-size: 14px; }
        @keyframes ticker { 0% { transform: translateX(100%); } 100% { transform: translateX(-100%); } }

        /* Metrik Kartları */
        div[data-testid="metric-container"] {
            background: #FFFFFF; border: 1px solid #EAEDF0; border-radius: 12px; padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.02); transition: all 0.3s ease;
        }
        div[data-testid="metric-container"]:hover {
            transform: translateY(-3px); box-shadow: 0 8px 20px rgba(0,0,0,0.08); border-color: #ebc71d;
        }

        /* Alt Yönetim Paneli */
        .admin-panel {
            background-color: #FFFFFF; border-top: 4px solid #ebc71d; padding: 30px;
            border-radius: 15px; margin-top: 50px; box-shadow: 0 -5px 25px rgba(0,0,0,0.05);
        }
        .admin-header {
            font-size: 20px; font-weight: bold; color: #2C3E50; margin-bottom: 20px; border-bottom: 1px solid #eee; padding-bottom: 10px;
        }

        /* Terminal Log Görünümü */
        .stCodeBlock {
            border: 2px solid #ebc71d !important;
            border-radius: 5px;
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
def install_browsers():
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "firefox"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install-deps", "firefox"], check=False)
    except Exception as e:
        print(f"Browser install warning: {e}")


# --- BOT MOTORU (LOG GÖSTEREN VERSİYON) ---
def botu_calistir_core(log_callback=None):
    # 1. Tarayıcıyı Kur
    if log_callback: log_callback("🔧 Sürücüler kontrol ediliyor (Firefox)...")
    install_browsers()

    # 2. Dosya Senkronizasyonu
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

    # 4. SCRAPING BAŞLIYOR
    if log_callback: log_callback(f"🚀 {total} Ürün için tarayıcı başlatılıyor...")

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        for i, row in takip.iterrows():
            urun_adi = str(row.get('Madde adı', 'Bilinmeyen'))[:25]

            # --- ANLIK LOG YAZDIRMA ---
            log_msg = f"🔎 [{i + 1}/{total}] İnceleniyor: {urun_adi}..."
            if log_callback: log_callback(log_msg)
            # --------------------------

            fiyat = 0.0
            kaynak = ""

            # Manuel Kontrol
            if pd.notna(row.get('Manuel_Fiyat')) and row.get('Manuel_Fiyat') > 0:
                fiyat = float(row['Manuel_Fiyat'])
                kaynak = "Manuel"
                if log_callback: log_callback(f"{log_msg}\n✅ Manuel Fiyat: {fiyat} TL")

            # Otomatik Web
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
                        page.goto(url, timeout=40000, wait_until="domcontentloaded")

                        # --- CİMRİ ÖZEL ---
                        if "cimri" in domain:
                            try:
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
                                            if "migros" in domain:
                                                el = page.locator(sel).first
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
                        if log_callback: log_callback(f"{log_msg}\n❌ Hata: {str(e)[:50]}")

            if fiyat and fiyat > 0:
                if log_callback: log_callback(f"{log_msg}\n💰 Fiyat Bulundu: {fiyat:.2f} TL ({kaynak})")
                veriler.append({
                    "Tarih": datetime.now().strftime("%Y-%m-%d"),
                    "Zaman": datetime.now().strftime("%H:%M"),
                    "Kod": row.get('Kod'),
                    "Madde_Adi": row.get('Madde adı'),
                    "Fiyat": fiyat,
                    "Kaynak": kaynak,
                    "URL": row.get('URL')
                })
            else:
                if log_callback: log_callback(f"{log_msg}\n⚠️ Fiyat Bulunamadı")

            time.sleep(random.uniform(0.5, 1.0))

        browser.close()

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


# --- DASHBOARD MODU (FULL DETAYLI) ---
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
            df_f.loc[df_f['Fiyat'] <= 0, 'Fiyat'] = np.nan

            df_s = pd.read_excel(EXCEL_DOSYASI, sheet_name=SAYFA_ADI, dtype={'Kod': str})
            df_s['Kod'] = df_s['Kod'].astype(str).apply(kod_standartlastir)
            grup_map = {"01": "Gıda", "02": "Alkol", "03": "Giyim", "04": "Konut", "05": "Ev", "06": "Sağlık",
                        "07": "Ulaşım", "08": "İletişim", "09": "Eğlence", "10": "Eğitim", "11": "Lokanta",
                        "12": "Çeşitli"}
            df_s['Grup'] = df_s['Kod'].str[:2].map(grup_map)
            emoji_map = {"01": "🍎", "02": "🍷", "03": "👕", "04": "🏠", "05": "🛋️", "06": "💊", "07": "🚗", "08": "📱",
                         "09": "🎭", "10": "🎓", "11": "🍽️", "12": "💅"}
            df_s['Emoji'] = df_s['Kod'].str[:2].map(emoji_map).fillna("📦")
            return df_f, df_s
        except:
            return None, None

    df_fiyat, df_sepet = veri_yukle()

    # --- PIVOT VE ANALİZ ---
    if df_fiyat is not None and not df_fiyat.empty:
        df_fiyat['Gun'] = df_fiyat['Tarih'].dt.date
        df_fiyat['Is_Manuel'] = df_fiyat['Kaynak'].astype(str).str.contains('Manuel', na=False)

        def oncelik(x):
            return x[x['Is_Manuel']] if x['Is_Manuel'].any() else x

        df_clean = df_fiyat.groupby(['Kod', 'Gun']).apply(oncelik).reset_index(drop=True)
        pivot = df_clean.pivot_table(index='Kod', columns='Gun', values='Fiyat', aggfunc='mean').ffill(axis=1).bfill(
            axis=1)

        if not pivot.empty:
            df_analiz = pd.merge(df_sepet, pivot, on='Kod', how='left').dropna(subset=['Agirlik_2025'])
            gunler = sorted(pivot.columns)
            baz, son = gunler[0], gunler[-1]

            trend_data = []
            for g in gunler:
                tmp = df_analiz.dropna(subset=[g, baz])
                if not tmp.empty:
                    val = ((tmp[g] / tmp[baz]) * 100 * tmp['Agirlik_2025']).sum() / tmp['Agirlik_2025'].sum()
                    trend_data.append({"Tarih": g, "TÜFE": val})
            df_trend = pd.DataFrame(trend_data)

            son_tufe = df_trend['TÜFE'].iloc[-1]
            enflasyon = ((son_tufe / df_trend['TÜFE'].iloc[0]) - 1) * 100
            gunluk_deg = ((son_tufe / df_trend['TÜFE'].iloc[-2]) - 1) * 100 if len(df_trend) > 1 else 0

            df_analiz['Fark'] = (df_analiz[son] / df_analiz[baz]) - 1
            top_artis = df_analiz.sort_values('Fark', ascending=False).iloc[0]

            # --- 1. TICKER (KAYAN YAZI) ---
            ticker_html = ""
            top_up = df_analiz.sort_values('Fark', ascending=False).head(5)
            top_down = df_analiz.sort_values('Fark', ascending=True).head(5)
            ticker_items = pd.concat([top_up, top_down])
            for _, r in ticker_items.iterrows():
                val = r['Fark']
                color = "#dc3545" if val > 0 else "#28a745" if val < 0 else "#6c757d"
                symbol = "▲" if val > 0 else "▼" if val < 0 else "▬"
                ticker_html += f"<span style='color:{color}'>{symbol} {r['Madde adı']} %{val * 100:.1f}</span> &nbsp;&nbsp;&nbsp;&nbsp; "
            st.markdown(
                f"""<div class="ticker-wrap"><div class="ticker"><div class="ticker-item">CANLI PİYASA: &nbsp;&nbsp; {ticker_html}</div></div></div>""",
                unsafe_allow_html=True)

            # --- 2. BAŞLIK VE METRİKLER ---
            st.title("🟡 ENFLASYON MONİTÖRÜ")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("ENDEKS", f"{son_tufe:.2f}", "Baz: 100")
            c2.metric("ENFLASYON", f"%{enflasyon:.2f}", f"{gunluk_deg:.2f}% (Günlük)", delta_color="inverse")
            c3.metric("ZAM ŞAMPİYONU", f"{top_artis['Madde adı'][:12]}..", f"%{top_artis['Fark'] * 100:.1f}",
                      delta_color="inverse")
            c4.metric("VERİ GÜVENİ", f"%{100 - (df_analiz[son].isna().sum() / len(df_analiz) * 100):.0f}",
                      f"{len(gunler)} Gün")

            st.markdown("---")

            # --- 3. GRAFİKLER ---
            c_left, c_right = st.columns([2, 1])
            with c_left:
                fig_area = px.area(df_trend, x='Tarih', y='TÜFE', markers=True, color_discrete_sequence=['#ebc71d'])
                fig_area.update_layout(plot_bgcolor='white', xaxis=dict(showgrid=False),
                                       yaxis=dict(gridcolor='#f0f0f0'))
                st.plotly_chart(fig_area, use_container_width=True)
            with c_right:
                val = min(max(0, abs(enflasyon)), 100)
                fig_gauge = go.Figure(go.Indicator(mode="gauge+number", value=val,
                                                   gauge={'axis': {'range': [None, 50]}, 'bar': {'color': "#dc3545"},
                                                          'bgcolor': "white"}))
                st.plotly_chart(fig_gauge, use_container_width=True)

            # --- 4. TABS ---
            tab1, tab2, tab3, tab4 = st.tabs(["SEKTÖREL", "ETKİ ANALİZİ", "DETAYLI LİSTE", "SİMÜLASYON"])
            with tab1:
                df_analiz['Grup_Degisim'] = df_analiz.groupby('Grup')['Fark'].transform('mean') * 100
                grup_data = df_analiz[['Grup', 'Grup_Degisim']].drop_duplicates().sort_values('Grup_Degisim')
                st.plotly_chart(go.Figure(go.Bar(y=grup_data['Grup'], x=grup_data['Grup_Degisim'], orientation='h',
                                                 marker=dict(color=grup_data['Grup_Degisim'], colorscale='RdYlGn_r'))),
                                use_container_width=True)
            with tab2:
                grup_katki = df_analiz.groupby('Grup')['Fark'].mean().sort_values(ascending=False).head(10) * 100
                st.plotly_chart(go.Figure(
                    go.Waterfall(orientation="v", measure=["relative"] * len(grup_katki), x=grup_katki.index,
                                 y=grup_katki.values)), use_container_width=True)
            with tab3:
                st.dataframe(df_analiz[['Emoji', 'Madde adı', 'Grup', 'Fark', son]].rename(columns={son: "Son Fiyat"}),
                             use_container_width=True)
            with tab4:
                st.info("Kutucuklara beklediğiniz % zam oranını girin.")
                cols = st.columns(4)
                sim_inputs = {grp: cols[i % 4].number_input(f"{grp} (%)", -100.0, 100.0, 0.0) for i, grp in
                              enumerate(sorted(df_analiz['Grup'].unique()))}
                etki = sum(
                    [(df_analiz[df_analiz['Grup'] == g]['Agirlik_2025'].sum() / df_analiz['Agirlik_2025'].sum()) * v for
                     g, v in sim_inputs.items()])
                st.metric("Simüle Enflasyon", f"%{enflasyon + etki:.2f}", f"{etki:+.2f}% Etki", delta_color="inverse")

    else:
        st.info("⚠️ Veri Bulunamadı. Lütfen Botu Çalıştırın.")

    # --- YÖNETİM PANELİ ---
    st.markdown('<div class="admin-panel"><div class="admin-header">⚙️ SİSTEM YÖNETİMİ</div>', unsafe_allow_html=True)
    c_load, c_bot, c_reset = st.columns(3)

    with c_load:
        st.markdown("**📂 Excel Yükle**")
        uf = st.file_uploader("", type=['xlsx'], label_visibility="collapsed")
        if uf:
            pd.read_excel(uf).to_excel(FIYAT_DOSYASI, sheet_name='Fiyat_Log', index=False)
            st.success("Yüklendi!")
            time.sleep(1);
            st.rerun()

    with c_bot:
        st.markdown("**🚀 Botu Çalıştır (Canlı Log)**")
        if st.button("Verileri Çek", type="primary", use_container_width=True):
            # CANLI LOG ALANI
            log_container = st.empty()

            def log_yazici(mesaj):
                # Her mesajda kodu günceller, böylece saniyelik akış görünür
                log_container.code(mesaj, language="yaml")

            sonuc = botu_calistir_core(log_yazici)

            if "Eklendi" in sonuc:
                st.success(sonuc)
                time.sleep(2)
                st.rerun()
            else:
                st.error(sonuc)

    with c_reset:
        st.markdown("**⚠️ Sıfırla**")
        if st.button("Sıfırla", use_container_width=True):
            sistemi_sifirla()
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="signature">Fatih Arslan Tarafından yapılmıştır</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    dashboard_modu()