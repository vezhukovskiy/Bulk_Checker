import streamlit as st
import pandas as pd
import json
import os
import time
import random
import re
import subprocess
import sys
from datetime import datetime, timedelta
from urllib.parse import urlparse
from typing import Optional, Tuple

# ==========================================
# 0. AUTO-INSTALL FIX (SYSTEM LEVEL)
# ==========================================
def ensure_playwright_installed():
    """
    Автоматическая проверка и установка браузера при старте.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        st.error("Playwright library not found! Add 'playwright' to requirements.txt")
        st.stop()

    # Пробуем тестовый запуск
    try:
        with sync_playwright() as p:
            # Пытаемся запустить, чтобы проверить, есть ли бинарник
            browser = p.chromium.launch(headless=True)
            browser.close()
    except Exception as e:
        # Если ошибка указывает на отсутствие браузера
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            placeholder = st.empty()
            placeholder.warning("⚙️ First launch detected: Installing Chromium browser... (Please wait ~60 seconds)")
            
            try:
                # 1. Install Chromium
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                
                # 2. Install Deps (иногда нужно в чистом линуксе)
                # subprocess.run([sys.executable, "-m", "playwright", "install-deps"], check=True) 
                
                placeholder.success("✅ Browser installed! Reloading app...")
                time.sleep(2)
                st.rerun()
            except Exception as install_err:
                placeholder.error(f"Failed to install browser: {install_err}")
                st.stop()

# Запуск проверки при старте скрипта
ensure_playwright_installed()

from playwright.sync_api import sync_playwright

# Файлы хранения
LOCAL_PROXY_FILE = "saved_proxies.json"
HISTORY_FILE = "scan_history.json"

RESTRICT_PATTERNS = [
    r"not available in your country", r"unavailable in your jurisdiction",
    r"does not accept players from", r"access (is )?restricted", 
    r"country not allowed", r"service is not available",
    r"доступ ограничен", r"не обслуживаем", r"prohibited territory",
    r"your ip address is blocked", r"location not authorized"
]

# ==========================================
# 1. HISTORY MANAGER
# ==========================================

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                data = json.load(f)
            return data
        except: return []
    return []

def save_to_history(new_records):
    history = load_history()
    now_str = datetime.now().isoformat()
    for rec in new_records:
        rec['timestamp'] = now_str
        history.append(rec)
    
    cutoff = datetime.now() - timedelta(days=7)
    clean_history = []
    for rec in history:
        try:
            rec_dt = datetime.fromisoformat(rec['timestamp'])
            if rec_dt > cutoff:
                clean_history.append(rec)
        except: pass 
            
    with open(HISTORY_FILE, 'w') as f:
        json.dump(clean_history, f, indent=4)

# ==========================================
# 2. PROXY LOGIC
# ==========================================

def load_proxies():
    proxies = {}
    if "proxies" in st.secrets:
        for name, url in st.secrets["proxies"].items():
            p_type = "rotating" if "{geo}" in url else "static"
            proxies[name] = {
                "url": url, "type": p_type,
                "geo": "Unknown" if p_type == "static" else "Multi",
                "desc": "🔒 From Secrets"
            }
    if os.path.exists(LOCAL_PROXY_FILE):
        try:
            with open(LOCAL_PROXY_FILE, 'r') as f:
                proxies.update(json.load(f))
        except: pass
    return proxies

def save_proxy_local(name, data):
    current = {}
    if os.path.exists(LOCAL_PROXY_FILE):
        try:
            with open(LOCAL_PROXY_FILE, 'r') as f:
                current = json.load(f)
        except: pass
    current[name] = data
    with open(LOCAL_PROXY_FILE, 'w') as f:
        json.dump(current, f, indent=4)

def delete_proxy_local(name):
    if os.path.exists(LOCAL_PROXY_FILE):
        try:
            with open(LOCAL_PROXY_FILE, 'r') as f:
                cur = json.load(f)
            if name in cur:
                del cur[name]
                with open(LOCAL_PROXY_FILE, 'w') as f:
                    json.dump(cur, f, indent=4)
                return True
        except: pass
    return False

def format_proxy_label(name, data):
    p_type = data.get('type', 'rotating')
    p_geo = data.get('geo', '?')
    if p_type == 'static':
        return f"📍 [Static: {p_geo}] {name}"
    else:
        return f"🔄 [Rotating] {name}"

def get_final_url(url_template, p_type, target_geo):
    if p_type == 'rotating' and "{geo}" in url_template:
        return url_template.replace("{geo}", target_geo.lower()).replace("{GEO}", target_geo.upper())
    return url_template

# ==========================================
# 3. CORE ENGINE
# ==========================================

def check_browser_stealth(url: str, proxy_url: str, timeout_s: int, headless: bool):
    if not proxy_url: return "ERROR", "No Proxy", ""
    
    if proxy_url == "test":
        time.sleep(random.uniform(0.5, 1.0))
        return random.choice([("OK", "Simulated OK", ""), ("RESTRICTED", "Simulated Ban", "")])

    if not url.startswith("http"): url = f"https://{url}"

    pw_proxy = None
    try:
        u = urlparse(proxy_url)
        pw_proxy = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
        if u.username: 
            pw_proxy["username"] = u.username
            pw_proxy["password"] = u.password
    except Exception as e: return "ERROR", f"Proxy Parse: {e}", ""

    # Args optimized for Docker/Cloud environments
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-infobars",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-setuid-sandbox"
    ]
    
    with sync_playwright() as p:
        browser = None
        try:
            # Запускаем Chromium. 
            # args нужны чтобы не крашилось в контейнерах с малой памятью
            browser = p.chromium.launch(headless=headless, args=args)

            context = browser.new_context(
                proxy=pw_proxy,
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            )
            # Anti-detect script
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            page = context.new_page()
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
            except Exception as e:
                return "PROXY_FAIL", f"Conn Error: {str(e)[:100]}", ""

            # Human-like mouse move
            try: page.mouse.move(random.randint(100,500), random.randint(100,500))
            except: pass
            
            # Wait for potential Cloudflare challenge
            try: page.wait_for_selector("text=Just a moment", state="detached", timeout=6000)
            except: pass
            
            page.wait_for_timeout(3000)
            content = page.content()
            title = page.title()
            
            c_low = content.lower()
            for pat in RESTRICT_PATTERNS:
                if re.search(pat, c_low): return "RESTRICTED", f"Found: {pat}", content
            
            if "just a moment" in (title or "").lower(): return "CHALLENGE", "Cloudflare", content
            
            return "OK", title, content
        except Exception as e: return "ERROR", str(e), ""
        finally:
            if browser: browser.close()

# ==========================================
# 4. UI
# ==========================================

st.set_page_config(page_title="Geo Scanner v12", layout="wide", page_icon="🌍")

if 'proxies' not in st.session_state:
    st.session_state.proxies = load_proxies()

def refresh_proxies(): st.session_state.proxies = load_proxies()

def color_status(val):
    if val == 'OK': return 'background-color: #d4edda; color: black'
    elif val == 'RESTRICTED': return 'background-color: #f8d7da; color: black; font-weight: bold'
    elif val == 'PROXY_FAIL': return 'background-color: #e2e3e5; color: gray'
    return ''

# Sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    headless = st.checkbox("Headless Mode", value=True)
    timeout = st.number_input("Timeout", value=30)
    st.caption("v12: Clean & Robust")

st.title("🌍 Affiliate Geo Scanner v12")

tab_manual, tab_bulk, tab_manage, tab_history = st.tabs(["🤚 Manual Check", "🚀 Bulk Scan", "🛠 Proxy Manager", "📜 History"])

# === TAB 1: MANUAL CHECK ===
with tab_manual:
    c1, c2, c3 = st.columns([3, 1, 2])
    dom = c1.text_input("Domain", "stake.com")
    
    proxies = st.session_state.proxies
    p_keys = sorted(list(proxies.keys()))
    select_options = [""] + p_keys + ["⚡ Custom (One-time)"]
    
    p_sel = c3.selectbox("Select Proxy", select_options, 
                         format_func=lambda x: "⚡ Custom (One-time)" if x == "⚡ Custom (One-time)" else (format_proxy_label(x, proxies[x]) if x in proxies else ""))
    
    active_proxy_data = None
    if p_sel == "⚡ Custom (One-time)":
        with c3.expander("Configure Custom Proxy", expanded=True):
            cust_type = st.radio("Type", ["rotating", "static"], horizontal=True, key="man_cust_type")
            cust_url = st.text_input("URL", placeholder="http://...", key="man_cust_url")
            cust_geo = ""
            if cust_type == "static":
                cust_geo = st.text_input("Fixed GEO", placeholder="US", max_chars=2, key="man_cust_geo").upper()
            if cust_url:
                active_proxy_data = {"url": cust_url, "type": cust_type, "geo": cust_geo}
    elif p_sel and p_sel in proxies:
        active_proxy_data = proxies[p_sel]

    geo_val = "US"
    geo_disabled = False
    if active_proxy_data and active_proxy_data['type'] == 'static':
        geo_val = active_proxy_data['geo']
        geo_disabled = True
        c2.info(f"🔒 Locked to {geo_val}")
    
    check_geo = c2.text_input("Check GEO", value=geo_val, disabled=geo_disabled, key="man_geo").upper()

    if st.button("Check One", type="primary"):
        if active_proxy_data:
            final_url = get_final_url(active_proxy_data['url'], active_proxy_data['type'], check_geo)
            with st.status(f"Checking via {p_sel if p_sel != '⚡ Custom (One-time)' else 'Custom Proxy'}..."):
                res, note, html = check_browser_stealth(dom, final_url, timeout, headless)
                
                if res == "OK": st.success(f"{res}: {note}")
                elif res == "RESTRICTED": st.error(f"{res}: {note}")
                else: st.warning(f"{res}: {note}")
                
                rec = {"Domain": dom, "GEO": check_geo, "Status": res, "Note": note, "Proxy Used": p_sel}
                save_to_history([rec])
                
                with st.expander("Source"): st.code(html[:1000])
        else:
            st.error("Please configure a proxy.")

# === TAB 2: BULK SCAN ===
with tab_bulk:
    b_opts = [""] + p_keys + ["⚡ Custom (One-time)"]
    b_sel = st.selectbox("1. Select Proxy Strategy", b_opts, 
                         format_func=lambda x: "⚡ Custom (One-time)" if x == "⚡ Custom (One-time)" else (format_proxy_label(x, proxies[x]) if x in proxies else "Select..."),
                         key="bulk_p")

    b_active_data = None
    if b_sel == "⚡ Custom (One-time)":
        with st.expander("Configure Custom Bulk Proxy", expanded=True):
            b_cust_type = st.radio("Type", ["rotating", "static"], horizontal=True, key="blk_cust_type")
            b_cust_url = st.text_input("URL Template", placeholder="http://...", key="blk_cust_url")
            b_cust_geo = ""
            if b_cust_type == "static":
                b_cust_geo = st.text_input("Fixed GEO", placeholder="US", max_chars=2, key="blk_cust_geo").upper()
            if b_cust_url:
                b_active_data = {"url": b_cust_url, "type": b_cust_type, "geo": b_cust_geo}
    elif b_sel and b_sel in proxies:
        b_active_data = proxies[b_sel]

    bg_disabled = False
    bg_val = "US, DE, CA"
    if b_active_data and b_active_data['type'] == 'static':
        bg_disabled = True
        bg_val = b_active_data['geo']
        st.info(f"🔒 Static Proxy selected. Scan restricted to: **{bg_val}**")
    
    b_geos = st.text_input("2. Target GEOs", value=bg_val, disabled=bg_disabled, key="blk_geos")
    b_file = st.file_uploader("3. Upload CSV", type=["csv"])

    if st.button("🚀 Run Bulk Scan"):
        if b_file and b_active_data:
            df = pd.read_csv(b_file)
            d_col = next((c for c in df.columns if 'domain' in c.lower()), None)
            if d_col:
                domains = df[d_col].dropna().unique().tolist()
                geos = [g.strip().upper() for g in b_geos.split(",") if g.strip()]
                res_list = []
                bar = st.progress(0)
                txt = st.empty()
                tot = len(domains) * len(geos)
                n = 0
                
                for d in domains:
                    for g in geos:
                        txt.text(f"Scanning {d} in {g}...")
                        f_url = get_final_url(b_active_data['url'], b_active_data['type'], g)
                        r, note, h = check_browser_stealth(d, f_url, timeout, headless)
                        rec = {"Domain": d, "GEO": g, "Status": r, "Note": note, "Proxy Used": b_sel}
                        res_list.append(rec)
                        n += 1
                        bar.progress(n/tot)
                
                txt.success("Done!")
                save_to_history(res_list)
                rdf = pd.DataFrame(res_list)
                try:
                    piv = rdf.pivot(index="Domain", columns="GEO", values="Status")
                    # Исправление Deprecation Warning
                    st.dataframe(piv.style.map(color_status), use_container_width=True)
                except: pass
                st.download_button("Download CSV", rdf.to_csv(index=False).encode('utf-8'), "report.csv")
        else:
            st.error("Setup incomplete.")

# === TAB 3: PROXY MANAGER ===
with tab_manage:
    c1, c2 = st.columns([1, 2])
    with c1:
        st.subheader("Saved Proxies")
        raw_keys = sorted(list(st.session_state.proxies.keys()))
        options_list = ["➕ Create New"] + raw_keys
        sel_opt = st.radio("Select Proxy:", options_list, 
                           format_func=lambda x: x if x == "➕ Create New" else format_proxy_label(x, st.session_state.proxies[x]))

    with c2:
        st.subheader("Proxy Editor")
        if sel_opt == "➕ Create New":
            val_name, val_url, val_type, val_geo, val_desc = "", "", "rotating", "", ""
            is_new, is_secret = True, False
        else:
            d = st.session_state.proxies[sel_opt]
            val_name, val_url, val_type, val_geo, val_desc = sel_opt, d['url'], d.get('type', 'rotating'), d.get('geo', ''), d.get('desc', '')
            is_new, is_secret = False, "Secrets" in val_desc

        new_name = st.text_input("Name (Alias)", value=val_name, disabled=is_secret)
        p_type = st.radio("Category", ["rotating", "static"], index=0 if val_type == 'rotating' else 1, horizontal=True, disabled=is_secret)

        if p_type == "rotating":
            st.info("ℹ️ Must include `{geo}`.")
            new_url = st.text_input("Template URL", value=val_url, placeholder="http://user-{geo}:pass@gate.io:port", disabled=is_secret)
            new_geo = "Multi"
        else:
            st.info("ℹ️ Fixed IP.")
            new_url = st.text_input("Proxy URL", value=val_url, placeholder="http://ip:port", disabled=is_secret)
            new_geo = st.text_input("Assigned GEO Code", value=val_geo, max_chars=2, disabled=is_secret).upper()

        new_desc = st.text_input("Notes", value=val_desc)
        st.divider()
        col_s, col_d = st.columns([1, 1])
        with col_s:
            if st.button("💾 Save Proxy", type="primary", disabled=is_secret):
                if not new_name or not new_url: st.error("Missing fields")
                elif p_type == "static" and not new_geo: st.error("Missing GEO")
                else:
                    if not is_new and new_name != val_name: delete_proxy_local(val_name)
                    save_proxy_local(new_name, {"url": new_url, "type": p_type, "geo": new_geo, "desc": new_desc})
                    refresh_proxies()
                    st.success("Saved!")
                    time.sleep(0.5); st.rerun()
        with col_d:
            if not is_new and not is_secret and st.button("🗑 Delete", type="secondary"):
                delete_proxy_local(val_name); refresh_proxies(); st.rerun()

# === TAB 4: HISTORY ===
with tab_history:
    st.header("📜 Scan History (Last 7 Days)")
    hist_data = load_history()
    if hist_data:
        df_hist = pd.DataFrame(hist_data)
        df_hist = df_hist.sort_values(by="timestamp", ascending=False)
        
        c_f1, c_f2 = st.columns(2)
        f_dom = c_f1.text_input("Filter by Domain")
        f_stat = c_f2.multiselect("Filter by Status", df_hist['Status'].unique())
        
        if f_dom: df_hist = df_hist[df_hist['Domain'].str.contains(f_dom, case=False, na=False)]
        if f_stat: df_hist = df_hist[df_hist['Status'].isin(f_stat)]
            
        # Исправление Deprecation Warning
        st.dataframe(df_hist.style.map(color_status, subset=['Status']), use_container_width=True)
        csv_h = df_hist.to_csv(index=False).encode('utf-8')
        st.download_button("Download History CSV", csv_h, "full_history.csv")
    else:
        st.info("History is empty.")
