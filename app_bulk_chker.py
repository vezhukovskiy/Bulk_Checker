import streamlit as st
import pandas as pd
import json
import os
import time
import random
import re
from urllib.parse import urlparse
from typing import Optional, Tuple

# --- Playwright ---
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

# Файл хранения
LOCAL_PROXY_FILE = "saved_proxies.json"

RESTRICT_PATTERNS = [
    r"not available in your country", r"unavailable in your jurisdiction",
    r"does not accept players from", r"access (is )?restricted", 
    r"country not allowed", r"service is not available",
    r"доступ ограничен", r"не обслуживаем", r"prohibited territory",
    r"your ip address is blocked", r"location not authorized"
]

# ==========================================
# 1. ЛОГИКА PROXY
# ==========================================

def load_proxies():
    proxies = {}
    # 1. Secrets (Cloud)
    if "proxies" in st.secrets:
        for name, url in st.secrets["proxies"].items():
            p_type = "rotating" if "{geo}" in url else "static"
            proxies[name] = {
                "url": url, 
                "type": p_type,
                "geo": "Unknown" if p_type == "static" else "Multi",
                "desc": "🔒 From Secrets"
            }

    # 2. Local File
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

def get_final_url(data, target_geo):
    tpl = data['url']
    if data.get('type') == 'rotating' and "{geo}" in tpl:
        return tpl.replace("{geo}", target_geo.lower()).replace("{GEO}", target_geo.upper())
    return tpl

# ==========================================
# 2. ДВИЖОК
# ==========================================

def check_browser_stealth(url: str, proxy_url: str, timeout_s: int, headless: bool):
    if not proxy_url: return "ERROR", "No Proxy", ""
    
    if proxy_url == "test":
        time.sleep(random.uniform(0.5, 1.0))
        return random.choice([("OK", "Simulated OK", ""), ("RESTRICTED", "Simulated Ban", "")])

    if sync_playwright is None: return "ERROR", "Playwright Missing", ""
    if not url.startswith("http"): url = f"https://{url}"

    pw_proxy = None
    try:
        u = urlparse(proxy_url)
        pw_proxy = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
        if u.username: 
            pw_proxy["username"] = u.username
            pw_proxy["password"] = u.password
    except Exception as e: return "ERROR", f"Proxy Parse: {e}", ""

    args = ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-infobars"]
    
    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.launch(headless=headless, args=args)
            context = browser.new_context(
                proxy=pw_proxy,
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            )
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = context.new_page()
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
            except Exception as e:
                return "PROXY_FAIL", f"Conn Error: {str(e)[:50]}", ""

            try: page.mouse.move(random.randint(100,500), random.randint(100,500))
            except: pass
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
# 3. UI
# ==========================================

st.set_page_config(page_title="Geo Scanner v8", layout="wide", page_icon="🌍")

if 'proxies' not in st.session_state:
    st.session_state.proxies = load_proxies()

def refresh(): st.session_state.proxies = load_proxies()

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

st.title("🌍 Affiliate Geo Scanner v8")

tab_manual, tab_bulk, tab_manage = st.tabs(["🤚 Manual Check", "🚀 Bulk Scan", "🛠 Proxy Manager"])

# === 1. PROXY MANAGER ===
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
            st.info("ℹ️ **Rotating**: Used for scanning multiple countries. Must include `{geo}`.")
            new_url = st.text_input("Template URL", value=val_url, placeholder="http://user-{geo}:pass@gate.io:port", disabled=is_secret)
            new_geo = "Multi"
        else:
            st.info("ℹ️ **Static**: Fixed IP address.")
            new_url = st.text_input("Proxy URL", value=val_url, placeholder="http://user:pass@1.2.3.4:8080", disabled=is_secret)
            new_geo = st.text_input("Assigned GEO Code", value=val_geo, placeholder="e.g. US", max_chars=2, disabled=is_secret).upper()

        new_desc = st.text_input("Notes", value=val_desc)
        st.divider()
        col_s, col_d = st.columns([1, 1])
        
        with col_s:
            if st.button("💾 Save Proxy", type="primary", disabled=is_secret):
                if not new_name or not new_url: st.error("Required fields missing")
                elif p_type == "static" and not new_geo: st.error("Static Proxy needs GEO code")
                else:
                    if not is_new and new_name != val_name: delete_proxy_local(val_name)
                    save_proxy_local(new_name, {"url": new_url, "type": p_type, "geo": new_geo, "desc": new_desc})
                    refresh()
                    st.success("Saved!")
                    time.sleep(0.5)
                    st.rerun()

        with col_d:
            if not is_new and not is_secret and st.button("🗑 Delete Proxy", type="secondary"):
                delete_proxy_local(val_name)
                refresh()
                st.rerun()

# === 2. MANUAL CHECK ===
with tab_manual:
    c1, c2, c3 = st.columns([3, 1, 2])
    dom = c1.text_input("Domain", "stake.com")
    geo = c2.text_input("Check GEO", "US").upper()
    
    proxies = st.session_state.proxies
    p_keys = sorted(list(proxies.keys()))
    p_sel = c3.selectbox("Select Proxy", [""] + p_keys, 
                         format_func=lambda x: "" if x == "" else format_proxy_label(x, proxies[x]))
    
    if st.button("Check One", type="primary"):
        if p_sel:
            p_data = proxies[p_sel]
            if p_data['type'] == 'static' and p_data['geo'] != geo:
                st.warning(f"⚠️ Mismatch: Proxy is {p_data['geo']}, checking {geo}.")
            
            with st.status(f"Checking via {format_proxy_label(p_sel, p_data)}..."):
                res, note, html = check_browser_stealth(dom, get_final_url(p_data, geo), timeout, headless)
                if res == "OK": st.success(f"{res}: {note}")
                elif res == "RESTRICTED": st.error(f"{res}: {note}")
                else: st.warning(f"{res}: {note}")
                with st.expander("Source"): st.code(html[:1000])

# === 3. BULK SCAN (IMPROVED) ===
with tab_bulk:
    # 1. Сначала выбираем прокси, так как от него зависит поле GEO
    p_keys_bulk = sorted(list(st.session_state.proxies.keys()))
    b_sel = st.selectbox("1. Select Proxy Strategy", [""] + p_keys_bulk, 
                         format_func=lambda x: "Select a Proxy..." if x == "" else format_proxy_label(x, st.session_state.proxies[x]),
                         key="bulk_p")
    
    # Логика блокировки поля GEO
    geo_disabled = False
    geo_value = "US, DE, CA" # Значение по умолчанию
    geo_placeholder = "Enter codes: US, DE, FR..."
    proxy_info_msg = ""

    if b_sel:
        p_data = st.session_state.proxies[b_sel]
        if p_data.get('type') == 'static':
            geo_disabled = True
            geo_value = p_data.get('geo', '??')
            proxy_info_msg = f"🔒 **Static Proxy selected.** GEO locked to **{geo_value}**."
        else:
            geo_disabled = False
            proxy_info_msg = "✅ **Rotating Proxy.** You can specify multiple target countries."

    # 2. Поле GEO (зависимое)
    if proxy_info_msg:
        st.info(proxy_info_msg)
        
    b_geos = st.text_input("2. Target GEOs", value=geo_value, disabled=geo_disabled, placeholder=geo_placeholder)
    
    # 3. Файл
    b_file = st.file_uploader("3. Upload CSV (Column 'Domain')", type=["csv"])

    if st.button("🚀 Run Bulk Scan"):
        if b_file and b_sel:
            df = pd.read_csv(b_file)
            d_col = next((c for c in df.columns if 'domain' in c.lower()), None)
            if d_col:
                domains = df[d_col].dropna().unique().tolist()
                geos = [g.strip().upper() for g in b_geos.split(",") if g.strip()]
                p_data = st.session_state.proxies[b_sel]

                res_list = []
                bar = st.progress(0)
                txt = st.empty()
                tot = len(domains) * len(geos)
                n = 0
                
                for d in domains:
                    for g in geos:
                        txt.text(f"Scanning {d} in {g}...")
                        f_url = get_final_url(p_data, g)
                        r, note, h = check_browser_stealth(d, f_url, timeout, headless)
                        res_list.append({"Domain": d, "GEO": g, "Status": r, "Note": note})
                        n += 1
                        bar.progress(n/tot)
                
                txt.success("Done!")
                rdf = pd.DataFrame(res_list)
                try:
                    piv = rdf.pivot(index="Domain", columns="GEO", values="Status")
                    st.dataframe(piv.style.map(color_status))
                except: pass
                st.download_button("Download CSV", rdf.to_csv(index=False).encode('utf-8'), "report.csv")
        else:
            st.error("Please select a proxy and upload a file.")
