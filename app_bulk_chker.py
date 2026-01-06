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
            # Для секретов пытаемся угадать тип по наличию {geo}
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
    """Красивое отображение в списке"""
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
    
    # Simulation
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
            
            # Check
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

st.set_page_config(page_title="Bulk Checker", layout="wide", page_icon="🌍")

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

st.title("🌍 Bulk Checker")

tab_manual, tab_bulk, tab_manage = st.tabs(["🤚 Manual Check", "🚀 Bulk Scan", "🛠 Proxy Manager"])

# === 1. PROXY MANAGER ===
with tab_manage:
    c1, c2 = st.columns([1, 2])
    
    with c1:
        st.subheader("Saved Proxies")
        p_keys = list(st.session_state.proxies.keys())
        # Формируем список с красивыми иконками
        options_map = {k: format_proxy_label(k, st.session_state.proxies[k]) for k in p_keys}
        
        sel_key = st.radio("Select Proxy:", ["➕ Create New"] + p_keys, 
                           format_func=lambda x: "➕ Create New" if x == "➕ Create New" else options_map[x])

    with c2:
        st.subheader("Proxy Editor")
        
        # Init values
        if sel_key == "➕ Create New":
            d = {"url": "", "type": "rotating", "geo": "", "desc": ""}
            is_new = True
            pk = ""
        else:
            d = st.session_state.proxies[sel_key]
            is_new = False
            pk = sel_key

        with st.form("edit_form"):
            new_name = st.text_input("Name (Alias)", value=pk, disabled=not is_new and "Secrets" in d.get('desc',''))
            
            # --- ГЛАВНОЕ: ВЫБОР ТИПА ---
            p_type = st.radio("Proxy Category", ["rotating", "static"], 
                              index=0 if d.get('type') == 'rotating' else 1,
                              horizontal=True)
            
            if p_type == "rotating":
                st.info("ℹ️ **Rotating**: Must include `{geo}` tag. Script will replace it with target country.")
                new_url = st.text_input("Template URL", value=d.get('url', ''), placeholder="http://user-{geo}:pass@host:port")
                new_geo = "Multi" # Автоматически
                if new_url and "{geo}" not in new_url:
                    st.warning("⚠️ Template missing `{geo}` tag!")
            else:
                st.info("ℹ️ **Static**: Uses a fixed IP. You must specify which country this IP belongs to.")
                new_url = st.text_input("Proxy URL", value=d.get('url', ''), placeholder="http://user:pass@host:port")
                new_geo = st.text_input("Assigned GEO Code (e.g. US, DE)", value=d.get('geo', ''), max_chars=2).upper()

            new_desc = st.text_input("Notes", value=d.get('desc', ''))
            
            sv = st.form_submit_button("💾 Save Proxy")
            
            if sv:
                if "Secrets" in d.get('desc',''):
                    st.error("Read-only Secret.")
                elif not new_name or not new_url:
                    st.error("Name and URL required.")
                elif p_type == "static" and not new_geo:
                    st.error("Static proxy requires a GEO Code!")
                else:
                    save_data = {
                        "url": new_url,
                        "type": p_type,
                        "geo": new_geo,
                        "desc": new_desc
                    }
                    save_proxy_local(new_name, save_data)
                    refresh()
                    st.success("Saved!")
                    st.rerun()

        if not is_new and "Secrets" not in d.get('desc',''):
            if st.button("🗑 Delete"):
                if delete_proxy_local(pk):
                    refresh()
                    st.rerun()

# === 2. MANUAL CHECK ===
with tab_manual:
    c1, c2, c3 = st.columns([3, 1, 2])
    dom = c1.text_input("Domain")
    geo = c2.text_input("Check GEO").upper()
    
    # Dropdown с умными лейблами
    proxies = st.session_state.proxies
    p_opts = list(proxies.keys())
    p_sel = c3.selectbox("Select Proxy", [""] + p_opts, 
                         format_func=lambda x: "" if x == "" else format_proxy_label(x, proxies[x]))
    
    if st.button("Check One", type="primary"):
        if p_sel:
            p_data = proxies[p_sel]
            
            # --- ВАЛИДАЦИЯ ГЕО ---
            warning_msg = None
            if p_data['type'] == 'static':
                if p_data['geo'] != geo:
                    warning_msg = f"⚠️ **MISMATCH:** Using a **{p_data['geo']}** Static Proxy to check **{geo}**. Result may be invalid!"
            
            if warning_msg: st.warning(warning_msg)
            
            final_url = get_final_url(p_data, geo)
            
            with st.status(f"Checking via {format_proxy_label(p_sel, p_data)}..."):
                res, note, html = check_browser_stealth(dom, final_url, timeout, headless)
                if res == "OK": st.success(f"{res}: {note}")
                elif res == "RESTRICTED": st.error(f"{res}: {note}")
                else: st.warning(f"{res}: {note}")
                
                with st.expander("Source"): st.code(html[:1000])
        else:
            st.error("Select proxy.")

# === 3. BULK SCAN ===
with tab_bulk:
    b_file = st.file_uploader("CSV (Column 'Domain')", type=["csv"])
    b_geos = st.text_input("Target GEOs", "US, DE, CA")
    b_sel = st.selectbox("Proxy Strategy", [""] + p_opts, 
                         format_func=lambda x: "" if x == "" else format_proxy_label(x, proxies[x]),
                         key="bulk_p")
    
    if st.button("🚀 Run Bulk Scan"):
        if b_file and b_sel:
            df = pd.read_csv(b_file)
            d_col = next((c for c in df.columns if 'domain' in c.lower()), None)
            
            if d_col:
                domains = df[d_col].dropna().unique().tolist()
                geos = [g.strip().upper() for g in b_geos.split(",") if g.strip()]
                p_data = proxies[b_sel]
                
                # --- ВАЛИДАЦИЯ ДЛЯ БАЛКА ---
                if p_data['type'] == 'static':
                    st.warning(f"⚠️ You selected a STATIC proxy **({p_data['geo']})**. Checks for other countries ({geos}) will likely be inaccurate!")
                    time.sleep(2)

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
