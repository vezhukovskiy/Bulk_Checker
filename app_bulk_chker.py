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

    try:
        with sync_playwright() as p:
            # Проверка наличия бинарника
            browser = p.chromium.launch(headless=True)
            browser.close()
    except Exception as e:
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            placeholder = st.empty()
            placeholder.warning("⚙️ First launch: Installing Chromium browser... (Wait ~45s)")
            try:
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                placeholder.success("✅ Installed! Reloading...")
                time.sleep(1)
                st.rerun()
            except Exception as install_err:
                placeholder.error(f"Install failed: {install_err}")
                st.stop()

# Проверка при старте
ensure_playwright_installed()

from playwright.sync_api import sync_playwright

# Файлы
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
                return json.load(f)
        except: return []
    return []

def save_to_history(new_records):
    history = load_history()
    now_str = datetime.now().isoformat()
    for rec in new_records:
        rec['timestamp'] = now_str
        history.append(rec)
    
    # Очистка старых (>7 дней)
    cutoff = datetime.now() - timedelta(days=7)
    clean_history = []
    for rec in history:
        try:
            if datetime.fromisoformat(rec['timestamp']) > cutoff:
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
                return "PROXY_FAIL", f"Conn Error: {str(e)[:100]}", ""

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
# 4. UI
# ==========================================

st.set_page_config(page_title="Geo Scanner v13", layout="wide", page_icon="🌍")

if 'proxies' not in st.session_state:
    st.session_state.proxies = load_proxies()

def refresh_proxies(): st.session_state.proxies = load_proxies()

def color_status(val):
    if val == 'OK': return 'background-color: #d4edda; color: black'
    elif val == 'RESTRICTED': return 'background-color: #f8d7da; color: black; font-weight: bold'
    elif val == 'PROXY_FAIL': return 'background-color: #e2e3e5; color: gray'
    return ''

with st.sidebar:
    st.header("⚙️ Settings")
    headless = st.checkbox("Headless Mode", value=True)
    timeout = st.number_input("Timeout", value=30)
    st.caption("v13: Stable Release")

st.title("🌍 Affiliate Geo Scanner v13")

tab_manual, tab_bulk, tab_manage, tab_history = st.tabs(["🤚 Manual Check", "🚀 Bulk Scan", "🛠 Proxy Manager", "📜 History"])

# === TAB 1: MANUAL CHECK ===
with tab_manual:
    c1, c2, c3 = st.columns([3, 1, 2])
    dom = c1.text_input("Domain", "stake.com")
    
    proxies = st.session_state.proxies
    p_keys = sorted(list(proxies.keys()))
    select_opts = [""] + p_keys + ["⚡ Custom (One-time)"]
    
    p_sel = c3.selectbox("Select Proxy", select_opts, 
        format_func=lambda x: "⚡ Custom (One-time)" if x == "⚡ Custom (One-time)" else (format_proxy_label(x, proxies[x]) if x in proxies else ""))
    
    active_data = None
    if p_sel == "⚡ Custom (One-time)":
        with c3.expander("Setup Custom Proxy", expanded=True):
            ct = st.radio("Type", ["rotating", "static"], horizontal=True, key="m_ct")
            cu = st.text_input("URL", placeholder="http://...", key="m_cu")
            cg = ""
            if ct == "static": cg = st.text_input("GEO", placeholder="US", max_chars=2, key="m_cg").upper()
            if cu: active_data = {"url": cu, "type": ct, "geo": cg}
    elif p_sel and p_sel in proxies:
        active_data = proxies[p_sel]

    geo_v = "US"
    geo_d = False
    if active_data and active_data['type'] == 'static':
        geo_v = active_data['geo']
        geo_d = True
        c2.info(f"🔒 Locked: {geo_v}")
    
    check_geo = c2.text_input("Check GEO", value=geo_v, disabled=geo_d, key="m_geo").upper()

    if st.button("Check One", type="primary"):
        if active_data:
            f_url = get_final_url(active_data['url'], active_data['type'], check_geo)
            with st.status(f"Scanning via {p_sel if 'Custom' not in p_sel else 'Custom Proxy'}..."):
                res, note, html = check_browser_stealth(dom, f_url, timeout, headless)
                if res == "OK": st.success(f"{res}: {note}")
                elif res == "RESTRICTED": st.error(f"{res}: {note}")
                else: st.warning(f"{res}: {note}")
                
                save_to_history([{"Domain": dom, "GEO": check_geo, "Status": res, "Note": note, "Proxy Used": p_sel}])
                with st.expander("HTML Source"): st.code(html[:1000])
        else: st.error("Configure proxy first.")

# === TAB 2: BULK SCAN ===
with tab_bulk:
    b_sel = st.selectbox("1. Proxy Strategy", select_opts, 
        format_func=lambda x: "⚡ Custom" if "Custom" in x else (format_proxy_label(x, proxies[x]) if x in proxies else "Select..."), key="b_p")

    b_data = None
    if b_sel == "⚡ Custom (One-time)":
        with st.expander("Setup Custom Bulk Proxy", expanded=True):
            bct = st.radio("Type", ["rotating", "static"], horizontal=True, key="b_ct")
            bcu = st.text_input("URL Template", placeholder="http://...", key="b_cu")
            bcg = ""
            if bct == "static": bcg = st.text_input("GEO", placeholder="US", max_chars=2, key="b_cg").upper()
            if bcu: b_data = {"url": bcu, "type": bct, "geo": bcg}
    elif b_sel and b_sel in proxies:
        b_data = proxies[b_sel]

    bg_d = False
    bg_v = "US, DE, CA"
    if b_data and b_data['type'] == 'static':
        bg_d = True
        bg_v = b_data['geo']
        st.info(f"🔒 Static Proxy: Scanning only **{bg_v}**")
    
    b_geos = st.text_input("2. Target GEOs", value=bg_v, disabled=bg_d, key="b_g")
    b_file = st.file_uploader("3. Upload CSV", type=["csv"])

    if st.button("🚀 Run Bulk Scan"):
        if b_file and b_data:
            df = pd.read_csv(b_file)
            col = next((c for c in df.columns if 'domain' in c.lower()), None)
            if col:
                doms = df[col].dropna().unique().tolist()
                geos = [g.strip().upper() for g in b_geos.split(",") if g.strip()]
                res_l = []
                bar = st.progress(0)
                txt = st.empty()
                tot = len(doms) * len(geos)
                n = 0
                
                for d in doms:
                    for g in geos:
                        txt.text(f"Scanning {d} in {g}...")
                        fu = get_final_url(b_data['url'], b_data['type'], g)
                        r, no, h = check_browser_stealth(d, fu, timeout, headless)
                        res_l.append({"Domain": d, "GEO": g, "Status": r, "Note": no, "Proxy Used": b_sel})
                        n += 1; bar.progress(n/tot)
                
                txt.success("Done!")
                save_to_history(res_l)
                rdf = pd.DataFrame(res_l)
                try:
                    piv = rdf.pivot(index="Domain", columns="GEO", values="Status")
                    # FIX: width="stretch" убирает желтые предупреждения
                    st.dataframe(piv.style.map(color_status), width="stretch")
                except: pass
                st.download_button("Download CSV", rdf.to_csv(index=False).encode('utf-8'), "report.csv")
        else: st.error("Incomplete setup.")

# === TAB 3: PROXY MANAGER ===
with tab_manage:
    c1, c2 = st.columns([1, 2])
    with c1:
        st.subheader("Saved Proxies")
        rk = sorted(list(st.session_state.proxies.keys()))
        s_opt = st.radio("Select:", ["➕ Create New"] + rk, 
            format_func=lambda x: x if "Create" in x else format_proxy_label(x, st.session_state.proxies[x]))

    with c2:
        st.subheader("Editor")
        if "Create" in s_opt:
            vn, vu, vt, vg, vd = "", "", "rotating", "", ""
            is_n, is_s = True, False
        else:
            d = st.session_state.proxies[s_opt]
            vn, vu, vt, vg, vd = s_opt, d['url'], d.get('type','rotating'), d.get('geo',''), d.get('desc','')
            is_n, is_s = False, "Secrets" in vd

        nn = st.text_input("Name", value=vn, disabled=is_s)
        nt = st.radio("Type", ["rotating", "static"], index=0 if vt=='rotating' else 1, horizontal=True, disabled=is_s)
        
        if nt == "rotating":
            st.info("ℹ️ Must use `{geo}`.")
            nu = st.text_input("Template", value=vu, placeholder="http://user-{geo}:pass@...", disabled=is_s)
            ng = "Multi"
        else:
            st.info("ℹ️ Fixed IP.")
            nu = st.text_input("URL", value=vu, placeholder="http://ip:port", disabled=is_s)
            ng = st.text_input("GEO Code", value=vg, max_chars=2, disabled=is_s).upper()

        nd = st.text_input("Notes", value=vd)
        st.divider()
        cs, cd = st.columns([1, 1])
        with cs:
            if st.button("💾 Save", type="primary", disabled=is_s):
                if not nn or not nu: st.error("Missing fields")
                elif nt=="static" and not ng: st.error("Missing GEO")
                else:
                    if not is_n and nn != vn: delete_proxy_local(vn)
                    save_proxy_local(nn, {"url": nu, "type": nt, "geo": ng, "desc": nd})
                    refresh_proxies(); st.success("Saved!"); time.sleep(0.5); st.rerun()
        with cd:
            if not is_n and not is_s and st.button("🗑 Delete", type="secondary"):
                delete_proxy_local(vn); refresh_proxies(); st.rerun()

# === TAB 4: HISTORY ===
with tab_history:
    st.header("📜 Recent History")
    hd = load_history()
    if hd:
        dfh = pd.DataFrame(hd).sort_values(by="timestamp", ascending=False)
        cf1, cf2 = st.columns(2)
        fd = cf1.text_input("Filter Domain")
        fs = cf2.multiselect("Filter Status", dfh['Status'].unique())
        
        if fd: dfh = dfh[dfh['Domain'].str.contains(fd, case=False, na=False)]
        if fs: dfh = dfh[dfh['Status'].isin(fs)]
            
        # FIX: width="stretch" убирает желтые предупреждения
        st.dataframe(dfh.style.map(color_status, subset=['Status']), width="stretch")
        st.download_button("Download CSV", dfh.to_csv(index=False).encode('utf-8'), "history.csv")
    else: st.info("No history yet.")
