import streamlit as st
import pandas as pd
import json
import os
import time
import random
import re
from urllib.parse import urlparse
from typing import Optional, Tuple

# --- Playwright Import ---
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

# Файл для локального хранения (не пушить в GitHub!)
LOCAL_PROXY_FILE = "saved_proxies.json"

# Паттерны блокировок
RESTRICT_PATTERNS = [
    r"not available in your country", 
    r"unavailable in your jurisdiction",
    r"does not accept players from",
    r"access (is )?restricted", 
    r"country not allowed",
    r"service is not available",
    r"доступ ограничен",
    r"не обслуживаем",
    r"prohibited territory",
    r"your ip address is blocked",
    r"not available in your region",
    r"location not authorized"
]

# ==========================================
# 1. ЛОГИКА PROXY & CONFIG
# ==========================================

def load_proxies():
    """
    Гибридная загрузка:
    1. Сначала пробуем взять из st.secrets (для Облака)
    2. Если нет, пробуем взять из локального JSON (для Мака)
    """
    proxies = {}
    
    # A. Пробуем загрузить локальный файл
    if os.path.exists(LOCAL_PROXY_FILE):
        try:
            with open(LOCAL_PROXY_FILE, 'r') as f:
                proxies.update(json.load(f))
        except: pass
    
    # B. Пробуем загрузить из Secrets (Streamlit Cloud)
    # В Secrets прокси должны быть в секции [proxies]
    if "proxies" in st.secrets:
        # st.secrets возвращает объект, приводим к dict
        proxies.update(dict(st.secrets["proxies"]))
        
    return proxies

def save_local_proxy(name, url):
    """Сохраняет ТОЛЬКО локально. В Secrets программно писать нельзя."""
    current = {}
    if os.path.exists(LOCAL_PROXY_FILE):
        try:
            with open(LOCAL_PROXY_FILE, 'r') as f:
                current = json.load(f)
        except: pass
    
    current[name] = url
    with open(LOCAL_PROXY_FILE, 'w') as f:
        json.dump(current, f, indent=4)

def delete_local_proxy(name):
    if os.path.exists(LOCAL_PROXY_FILE):
        try:
            with open(LOCAL_PROXY_FILE, 'r') as f:
                current = json.load(f)
            if name in current:
                del current[name]
                with open(LOCAL_PROXY_FILE, 'w') as f:
                    json.dump(current, f, indent=4)
        except: pass

def get_proxy_for_geo(template: str, geo: str) -> str:
    if not template: return ""
    return template.replace("{geo}", geo.lower()).replace("{GEO}", geo.upper())

# ==========================================
# 2. ДВИЖОК ПРОВЕРКИ (PLAYWRIGHT)
# ==========================================

def check_browser_stealth(url: str, proxy: str, timeout_s: int, headless: bool):
    # --- KILL SWITCH ---
    if not proxy:
        return "ERROR", "No Proxy Provided", ""
    
    # Simulation Mode (для тестов без трат денег)
    if proxy == "test":
        time.sleep(random.uniform(0.5, 1.5))
        outcome = random.choice(["OK", "OK", "RESTRICTED", "CHALLENGE"])
        if outcome == "OK": return "OK", "Simulated: Site Loaded", "<html>Test Content</html>"
        if outcome == "RESTRICTED": return "RESTRICTED", "Simulated: Geo Ban", "<html>Not Available</html>"
        return "CHALLENGE", "Simulated: Cloudflare", "<html>Verify Human</html>"

    if sync_playwright is None:
        return "ERROR", "Playwright not installed", ""

    if not url.startswith("http"): url = f"https://{url}"

    # Parse Proxy
    pw_proxy = None
    try:
        u = urlparse(proxy)
        if not u.scheme or not u.netloc:
             return "ERROR", "Invalid Proxy Format", ""
        pw_proxy = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
        if u.username: 
            pw_proxy["username"] = u.username
            pw_proxy["password"] = u.password
    except Exception as e:
        return "ERROR", f"Proxy Parse Error: {e}", ""

    # Args for Chromium in Cloud (Linux)
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-infobars",
        "--disable-dev-shm-usage", # Важно для Docker/Cloud
        "--disable-gpu"
    ]

    with sync_playwright() as p:
        browser = None
        try:
            # В облаке headless должен быть True, иначе упадет
            browser = p.chromium.launch(headless=headless, args=args)
            
            context = browser.new_context(
                proxy=pw_proxy,
                locale="en-US",
                timezone_id="Europe/London",
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            )
            
            # Anti-detect
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            page = context.new_page()
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
            except Exception as e:
                # Не палим реальный IP, просто возвращаем ошибку прокси
                return "PROXY_FAIL", f"Connection Error: {str(e)[:50]}", ""

            # Имитация активности (Jiggle) - работает даже в headless, генерируя события
            try:
                page.mouse.move(random.randint(100, 500), random.randint(100, 500))
            except: pass

            # Wait for Cloudflare
            try:
                page.wait_for_selector("text=Just a moment", state="detached", timeout=8000)
            except: pass
            
            # Ждем прогрузки контента (React/Vue сайтов)
            page.wait_for_timeout(3000)
            
            content = page.content()
            title = page.title()
            
            # Analyze
            content_lower = content.lower()
            title_lower = (title or "").lower()

            # 1. Restricted Check
            for pat in RESTRICT_PATTERNS:
                if re.search(pat, content_lower):
                    return "RESTRICTED", f"Found: {pat}", content

            # 2. Tech Block Check
            if "just a moment" in title_lower or "verify you are human" in content_lower:
                return "CHALLENGE", "Cloudflare Block", content

            return "OK", title, content

        except Exception as e:
            return "ERROR", str(e), ""
        finally:
            if browser: browser.close()

# ==========================================
# 3. STREAMLIT UI
# ==========================================

st.set_page_config(page_title="Affiliate Geo Scanner", layout="wide", page_icon="🌍")

# Загружаем прокси при старте
if 'proxies' not in st.session_state:
    st.session_state.proxies = load_proxies()

def color_status(val):
    if val == 'OK': return 'background-color: #d4edda; color: black'
    elif val == 'RESTRICTED': return 'background-color: #f8d7da; color: black; font-weight: bold'
    elif val == 'CHALLENGE': return 'background-color: #fff3cd; color: black'
    elif val == 'PROXY_FAIL': return 'background-color: #e2e3e5; color: gray'
    return ''

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Settings")
    # В облаке всегда лучше Headless=True
    headless_mode = st.checkbox("Headless Mode", value=True, help="Keep checked for Streamlit Cloud")
    timeout_val = st.number_input("Timeout (sec)", value=30)
    
    st.info("ℹ️ **Note:** In Streamlit Cloud, browser runs invisibly (Headless).")

st.title("🌍 Casino/Affiliate Geo Scanner")

tab_manual, tab_bulk, tab_proxies = st.tabs(["🤚 Manual Check", "🚀 Bulk Scan (CSV)", "🔑 Proxy Manager"])

# === TAB: PROXY MANAGER ===
with tab_proxies:
    st.markdown("### 1. Add Local Proxy")
    st.write("Use this to test on your machine. For Cloud deployment, use **Streamlit Secrets**.")
    
    c1, c2 = st.columns(2)
    with c1:
        with st.form("add_local_proxy"):
            new_name = st.text_input("Name (Alias)", placeholder="My Resi Proxy")
            new_url = st.text_input("URL Template", placeholder="http://user-{geo}:pass@gate.io:port")
            submitted = st.form_submit_button("Save to Local File")
            if submitted and new_name and new_url:
                save_local_proxy(new_name, new_url)
                st.session_state.proxies = load_proxies() # Reload
                st.success(f"Saved locally: {new_name}")
                st.rerun()
                
    with c2:
        st.write("**Active Proxies (Local + Secrets):**")
        if st.session_state.proxies:
            st.table(pd.DataFrame(list(st.session_state.proxies.keys()), columns=["Available Proxy Alias"]))
        else:
            st.warning("No proxies found. Add one locally or set Secrets.")

# === TAB: MANUAL ===
with tab_manual:
    col1, col2, col3 = st.columns([3, 1, 2])
    m_domain = col1.text_input("Domain", "stake.com")
    m_geo = col2.text_input("GEO", "US")
    
    proxy_options = [""] + list(st.session_state.proxies.keys())
    m_proxy_name = col3.selectbox("Select Proxy", proxy_options, key="man_px")
    
    if st.button("Check One", type="primary"):
        if m_proxy_name:
            tpl = st.session_state.proxies[m_proxy_name]
            final_proxy = get_proxy_for_geo(tpl, m_geo)
            
            with st.status(f"Scanning {m_domain} via {m_geo}...", expanded=True) as status:
                res, note, html = check_browser_stealth(m_domain, final_proxy, timeout_val, headless_mode)
                
                if res == "OK": status.update(label="Available", state="complete")
                elif res == "RESTRICTED": status.update(label="Restricted (Target Found!)", state="error")
                else: status.update(label="Issue Detected", state="running")
                
                st.write(f"**Status:** {res}")
                st.write(f"**Note:** {note}")
                with st.expander("Show HTML"):
                    st.code(html[:2000], language='html')
        else:
            st.error("Select a proxy first.")

# === TAB: BULK ===
with tab_bulk:
    st.markdown("### Bulk Matrix Scan")
    
    b_file = st.file_uploader("Upload CSV (Column 'Domain')", type=["csv"])
    b_geos = st.text_input("Target GEOs (comma sep)", "US, DE, CA, FR, IT, AU, BR")
    b_proxy_name = st.selectbox("Select Proxy Strategy", proxy_options, key="bulk_px")
    
    if st.button("🚀 Run Bulk Scan"):
        if b_file and b_geos and b_proxy_name:
            df = pd.read_csv(b_file)
            # Гибкий поиск колонки domain
            dom_col = next((c for c in df.columns if 'domain' in c.lower()), None)
            
            if not dom_col:
                st.error("CSV error: No 'domain' column found.")
            else:
                domains = df[dom_col].dropna().unique().tolist()
                geos = [g.strip().upper() for g in b_geos.split(",") if g.strip()]
                tpl = st.session_state.proxies[b_proxy_name]
                
                results = []
                total = len(domains) * len(geos)
                bar = st.progress(0)
                status_txt = st.empty()
                cnt = 0
                
                for dom in domains:
                    for geo in geos:
                        status_txt.write(f"Checking **{dom}** in **{geo}**...")
                        
                        prox = get_proxy_for_geo(tpl, geo)
                        res, note, html = check_browser_stealth(dom, prox, timeout_val, headless_mode)
                        
                        results.append({
                            "Domain": dom, "GEO": geo, "Status": res, 
                            "Note": note, "HTML": html[:500]
                        })
                        cnt += 1
                        bar.progress(cnt/total)
                
                status_txt.success("Done!")
                
                # Report
                df_res = pd.DataFrame(results)
                
                st.divider()
                st.subheader("Availability Matrix")
                try:
                    pivot = df_res.pivot(index="Domain", columns="GEO", values="Status")
                    st.dataframe(pivot.style.map(color_status), use_container_width=True)
                except: st.warning("Pivot failed.")
                
                st.subheader("Detailed Logs")
                st.dataframe(df_res.style.map(color_status, subset=['Status']))
                
                csv_data = df_res.to_csv(index=False).encode('utf-8')
                st.download_button("Download CSV Report", csv_data, "geo_report.csv", "text/csv")
        else:
            st.error("Please fill all fields.")
