import streamlit as st
from linkedin_api import Linkedin
import requests, json, os, time, threading

# ── Config ────────────────────────────────────────────────────────────────────
SESSION_FILE  = os.path.join(os.path.dirname(__file__), ".li_session.json")
COOKIES_DIR   = os.path.join(os.path.dirname(__file__), ".li_cookies")
SENT_LOG_FILE = os.path.join(os.path.dirname(__file__), "sent_log.json")
os.makedirs(COOKIES_DIR, exist_ok=True)

# ── Sent-history helpers ──────────────────────────────────────────────────────

def load_sent_log() -> dict:
    """Returns {urn_id: {name, headline, message, sent_at}} map."""
    if os.path.exists(SENT_LOG_FILE):
        try:
            with open(SENT_LOG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_sent_log(log: dict):
    with open(SENT_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)

def already_messaged(urn_id: str) -> bool:
    return urn_id in load_sent_log()

def record_sent(urn_id: str, name: str, headline: str, message: str,
                method: str = "direct_message", degree: str = "?"):
    log = load_sent_log()
    log[urn_id] = {
        "name":     name,
        "headline": headline,
        "message":  message,
        "method":   method,
        "degree":   degree,
        "sent_at":  time.strftime("%Y-%m-%d %H:%M:%S")
    }
    save_sent_log(log)

st.set_page_config(
    page_title="Nexus AI | LinkedIn Agent",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* Dark theme overrides */
.stApp { background: #0a0b0e; }

/* Sidebar */
section[data-testid="stSidebar"] > div {
    background: #12141a;
    border-right: 1px solid rgba(255,255,255,0.05);
}

/* Metric cards */
[data-testid="metric-container"] {
    background: #12141a;
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 12px;
    padding: 16px;
}

/* Buttons */
.stButton > button {
    background: #6366f1 !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    transition: all 0.2s !important;
}
.stButton > button:hover {
    background: #4f46e5 !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 15px rgba(99,102,241,0.4) !important;
}

/* Status badge */
.status-connected {
    display: inline-flex; align-items: center; gap: 8px;
    background: rgba(16,185,129,0.1);
    border: 1px solid rgba(16,185,129,0.3);
    color: #10b981;
    padding: 6px 14px;
    border-radius: 99px;
    font-size: 0.85rem;
    font-weight: 600;
}
.status-dot { width:8px; height:8px; background:#10b981;
    border-radius:50%; display:inline-block;
    box-shadow: 0 0 6px #10b981; }

/* Terminal log */
.terminal {
    background: #020305;
    border-radius: 10px;
    padding: 16px 20px;
    font-family: 'Consolas', monospace;
    font-size: 0.82rem;
    border: 1px solid rgba(255,255,255,0.05);
    max-height: 400px;
    overflow-y: auto;
}
.log-info    { color: #94a3b8; }
.log-success { color: #4ade80; }
.log-warn    { color: #fbbf24; }
.log-error   { color: #f87171; }
.log-msg     { color: #a78bfa; }

/* Section headers */
h1 { font-size: 1.7rem !important; font-weight: 700 !important; color: #f8fafc !important; }
h2 { font-size: 1.2rem !important; font-weight: 600 !important; color: #f8fafc !important; }
h3 { font-size: 1rem !important; font-weight: 600 !important; color: #94a3b8 !important;
     text-transform: uppercase; letter-spacing: 0.08em; }
</style>
""", unsafe_allow_html=True)

# ── Session Helpers ───────────────────────────────────────────────────────────

def save_session(data: dict):
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f)

def load_session():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE) as f:
            return json.load(f)
    return None

def clear_session():
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)

def build_api_cookies(li_at, jsessionid):
    api = Linkedin("", "", authenticate=False)
    api.client.session.cookies.set("li_at", li_at, domain=".linkedin.com")
    clean_jsession = jsessionid.replace('"', '')
    api.client.session.cookies.set("JSESSIONID", clean_jsession, domain=".linkedin.com")
    api.client.session.headers["csrf-token"] = clean_jsession
    return api

def build_api_password(email, password):
    return Linkedin(email, password, cookies_dir=COOKIES_DIR)

def extract_profile(raw):
    if not raw or not isinstance(raw, dict):
        return {"name": "LinkedIn User", "headline": "Connected"}
    mini = raw.get("miniProfile") or raw
    first = mini.get("firstName") or mini.get("localizedFirstName") or ""
    last  = mini.get("lastName")  or mini.get("localizedLastName")  or ""
    headline = mini.get("occupation") or mini.get("headline") or "Connected"
    return {"name": f"{first} {last}".strip() or "LinkedIn User", "headline": headline}

# ── Restore saved session on first load ───────────────────────────────────────

if "api" not in st.session_state:
    st.session_state.api     = None
    st.session_state.profile = None
    st.session_state.logs    = []
    st.session_state.running = False

    saved = load_session()
    if saved:
        try:
            method = saved.get("method", "cookies")
            if method == "password":
                api = build_api_password(saved["email"], saved["password"])
            else:
                api = build_api_cookies(saved["li_at"], saved["jsessionid"])

            st.session_state.api = api
            try:
                raw = api.get_user_profile()
                st.session_state.profile = extract_profile(raw)
            except Exception:
                st.session_state.profile = {
                    "name": saved.get("email", "LinkedIn User"),
                    "headline": "Session restored"
                }
        except Exception as e:
            pass  # Don't wipe session — just show login form

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚡ Nexus AI")
    st.markdown("---")

    if st.session_state.api:
        name     = st.session_state.profile.get("name", "LinkedIn User") if st.session_state.profile else "LinkedIn User"
        headline = st.session_state.profile.get("headline", "") if st.session_state.profile else ""
        initials = "".join(w[0] for w in name.split()[:2]).upper()

        st.markdown(f"""
        <div style='display:flex;align-items:center;gap:12px;margin-bottom:12px'>
            <div style='width:42px;height:42px;border-radius:50%;
                background:linear-gradient(135deg,#6366f1,#a855f7);
                display:flex;align-items:center;justify-content:center;
                font-weight:700;color:white;font-size:1rem;flex-shrink:0'>{initials}</div>
            <div>
                <div style='font-weight:600;font-size:0.95rem'>{name}</div>
                <div style='color:#64748b;font-size:0.78rem'>{headline}</div>
            </div>
        </div>
        <div class='status-connected'><span class='status-dot'></span> Session Active</div>
        """, unsafe_allow_html=True)

        st.markdown("")
        if st.button("⏻  Disconnect", use_container_width=True):
            st.session_state.api     = None
            st.session_state.profile = None
            clear_session()
            st.rerun()

    else:
        st.markdown("### Login")
        tab_pw, tab_ck = st.tabs(["📧 Email & Password", "🍪 Cookies"])

        with tab_pw:
            email    = st.text_input("LinkedIn Email", placeholder="you@email.com", key="email")
            password = st.text_input("Password", type="password", key="password")

            if st.button("Sign In", use_container_width=True, key="btn_pw"):
                with st.spinner("Signing in..."):
                    try:
                        # Force refresh cookies on manual sign in to avoid using expired cached ones
                        api = Linkedin(email, password, cookies_dir=COOKIES_DIR, refresh_cookies=True)
                        st.session_state.api = api
                        try:
                            raw = api.get_user_profile()
                            st.session_state.profile = extract_profile(raw)
                        except Exception:
                            st.session_state.profile = {"name": email, "headline": "Connected"}
                        save_session({"method": "password", "email": email, "password": password})
                        st.success("✅ Signed in!")
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as e:
                        err = str(e)
                        if "CHALLENGE" in err.upper():
                            st.error("LinkedIn sent a security challenge. Open LinkedIn in your browser, complete any verification email/SMS, then try again.")
                        else:
                            st.error(f"Login failed: {err}")

        with tab_ck:
            li_at      = st.text_input("li_at cookie", type="password", key="li_at")
            jsessionid = st.text_input("JSESSIONID cookie", type="password", key="jsessionid")
            st.caption("F12 → Application → Cookies → copy `li_at` and `JSESSIONID`")

            if st.button("Connect", use_container_width=True, key="btn_ck"):
                with st.spinner("Connecting..."):
                    try:
                        api = build_api_cookies(li_at, jsessionid)
                        st.session_state.api = api
                        try:
                            raw = api.get_user_profile()
                            st.session_state.profile = extract_profile(raw)
                        except Exception:
                            st.session_state.profile = {"name": "LinkedIn User", "headline": "Connected"}
                        save_session({"method": "cookies", "li_at": li_at, "jsessionid": jsessionid})
                        st.success("✅ Connected!")
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")

    st.markdown("---")
    st.markdown("### 🤖 Ollama Settings")
    ollama_base = st.text_input("Ollama URL", value="http://localhost:11434", key="ollama_base")

    # Fetch available models
    available_models = []
    try:
        r = requests.get(f"{ollama_base}/api/tags", timeout=2)
        available_models = [m["name"] for m in r.json().get("models", [])]
        st.success(f"✓ {len(available_models)} model(s) found")
    except:
        st.warning("Ollama offline — run: `ollama serve`")

    selected_model = st.selectbox(
        "AI Model",
        available_models if available_models else ["(no models found)"],
        key="model"
    )

# ── Main Content ──────────────────────────────────────────────────────────────

st.title("⚡ Nexus AI — LinkedIn Automation Agent")
st.markdown("Search profiles, evaluate with AI, send personalized messages — all automated.")
st.markdown("---")

if not st.session_state.api:
    st.info("👈 Connect your LinkedIn account from the sidebar to get started.")
    st.stop()

# ── Campaign Config ───────────────────────────────────────────────────────────

col1, col2 = st.columns([1.2, 1])

with col1:
    st.subheader("🚀 Campaign Settings")

    kw_col, lim_col = st.columns([2, 1])
    with kw_col:
        keyword = st.text_input("Target Keywords", placeholder="e.g. Hiring Manager Python startup")
    with lim_col:
        limit = st.number_input("Max Profiles", min_value=1, max_value=50, value=5)

    persona = st.text_area(
        "Agent Persona & Targeting Rules",
        height=200,
        placeholder=(
            "Describe who to target.\n\n"
            "Example:\nTarget Hiring Managers or Engineering Managers at tech companies.\n"
            "MATCH if headline contains: 'Hiring', 'CTO', 'Engineering Manager', 'Recruiter', 'Head of Engineering'.\n"
            "REJECT if: student, sales, or another job seeker.\n\n"
            "For MATCH, write a short warm outreach (under 280 chars) as a software developer "
            "actively looking for new opportunities."
        )
    )

    auto_send = st.toggle("⚠️ Auto-send messages immediately", value=False)
    if auto_send:
        st.warning("Auto-send is ON — messages will be sent without review.")

    run_col, stop_col = st.columns(2)

    with run_col:
        start = st.button("▶  Deploy Agent", use_container_width=True, type="primary",
                          disabled=st.session_state.running)
    with stop_col:
        stop = st.button("⏹  Abort", use_container_width=True,
                         disabled=not st.session_state.running)

with col2:
    st.subheader("📟 Live Agent Log")

    log_placeholder = st.empty()

    def render_logs():
        if not st.session_state.logs:
            log_placeholder.markdown(
                "<div class='terminal'><span class='log-info'>[System] Agent ready. Deploy a campaign to begin.</span></div>",
                unsafe_allow_html=True
            )
            return
        html = "<div class='terminal'>"
        for entry in st.session_state.logs[-80:]:  # Show last 80 lines
            cls = f"log-{entry.get('level', 'info')}"
            msg = entry['message'].replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
            html += f"<div class='{cls}'>[{entry['time']}] {msg}</div>"
        html += "</div>"
        log_placeholder.markdown(html, unsafe_allow_html=True)

    render_logs()

# ── Stop Handler ──────────────────────────────────────────────────────────────

if stop:
    st.session_state.running = False
    st.session_state.logs.append({
        "time": time.strftime("%H:%M:%S"),
        "message": "⛔ Abort requested. Stopping after current profile...",
        "level": "warn"
    })

# ── Campaign Runner ───────────────────────────────────────────────────────────

def add_log(msg, level="info"):
    st.session_state.logs.append({
        "time": time.strftime("%H:%M:%S"),
        "message": msg,
        "level": level
    })

if start:
    if not keyword.strip():
        st.error("Please enter target keywords.")
    elif not persona.strip():
        st.error("Please define the agent persona.")
    elif not available_models:
        st.error("No Ollama models available. Start Ollama and pull a model first.")
    else:
        st.session_state.running = True
        st.session_state.logs = []
        ollama_url = f"{ollama_base}/api/generate"

        add_log("🚀 Campaign started. Searching LinkedIn...", "info")

        progress_bar = st.progress(0, text="Searching profiles...")
        status_text  = st.empty()

        try:
            # ── Patch: intercept the raw response for better diagnostics ──────────
            import json as _json
            _orig_request = st.session_state.api.client.session.request
            _last_response = {}

            def _patched_request(*args, **kwargs):
                resp = _orig_request(*args, **kwargs)
                _last_response['status']  = resp.status_code
                _last_response['content'] = resp.text[:500]
                return resp

            st.session_state.api.client.session.request = _patched_request
            # ─────────────────────────────────────────────────────────────────────

            try:
                results = st.session_state.api.search_people(keywords=keyword, limit=int(limit))
                status = _last_response.get('status', 200)
                if status in (401, 403):
                    raise Exception("Session expired or Unauthorized (HTTP 401/403).")
            except Exception as e:
                status  = _last_response.get('status', '?')
                snippet = _last_response.get('content', '')
                if 'login' in snippet.lower() or 'signin' in snippet.lower() or '<html' in snippet.lower():
                    raise Exception(
                        "LinkedIn returned a login/CAPTCHA page (session expired or IP-flagged). "
                        "Please re-enter your cookies — open LinkedIn in a browser, log in fresh, "
                        "and copy new li_at + JSESSIONID values."
                    )
                raise Exception(
                    f"LinkedIn returned an error (HTTP {status}): {str(e)}. "
                    f"This usually means your session is expired or LinkedIn is rate-limiting you. "
                    f"Please Disconnect and Sign In again, or refresh your cookies."
                )
            finally:
                # Restore original method
                st.session_state.api.client.session.request = _orig_request

            total = len(results)
            add_log(f"✅ Found {total} profiles. Starting AI evaluation...", "success")

            for idx, person in enumerate(results):
                if not st.session_state.running:
                    add_log("⛔ Campaign aborted.", "warn")
                    break

                name     = person.get('name', 'Unknown')
                urn_id   = person.get('urn_id', '')
                headline = person.get('headline', '')

                progress_bar.progress((idx + 1) / total, text=f"Evaluating {idx+1}/{total}: {name}")

                # ── Duplicate guard ───────────────────────────────────────
                if urn_id and already_messaged(urn_id):
                    add_log(f"🔁 [{idx+1}/{total}] SKIPPED (already messaged): {name}", "warn")
                    render_logs()
                    continue
                # ─────────────────────────────────────────────────────────

                add_log(f"── [{idx+1}/{total}] {name} | {headline}", "info")
                add_log("🧠 AI analyzing prospect...", "info")

                prompt = (
                    f"You are an expert sales recruiter.\n"
                    f"Target Persona Rules:\n{persona}\n\n"
                    f"Prospect Name: {name}\n"
                    f"Prospect Headline: {headline}\n\n"
                    f"Reply with 'MATCH' or 'REJECT' on the first line.\n"
                    f"If MATCH, write a personalized message under 280 characters on the next lines.\n"
                    f"Do NOT wrap the message in quotes."
                )

                try:
                    ai_res = requests.post(
                        ollama_url,
                        json={"model": selected_model, "prompt": prompt, "stream": False},
                        timeout=90
                    )
                    if ai_res.status_code == 200:
                        response_text = ai_res.json().get("response", "").strip()
                        is_match = response_text.upper().startswith("MATCH")

                        if is_match:
                            add_log(f"🎯 MATCH: {name}", "success")
                            lines   = response_text.split("\n", 1)
                            message = lines[1].strip() if len(lines) > 1 else ""
                            if message:
                                add_log(f"✉️  Draft:\n{message}", "msg")
                                if auto_send:
                                    # ── Verify connection degree ──────────────
                                    degree = "UNKNOWN"
                                    try:
                                        # Use the distance provided natively by the search results to save API calls
                                        dist_val = str(person.get("distance", ""))
                                        if "1" in dist_val:
                                            degree = "1st"
                                        elif "2" in dist_val:
                                            degree = "2nd"
                                        elif "3" in dist_val:
                                            degree = "3rd"
                                        else:
                                            degree = dist_val or "UNKNOWN"
                                        
                                        add_log(f"🔗 Connection degree: {degree}", "info")
                                    except Exception as de:
                                        add_log(f"⚠️ Could not evaluate degree ({de}) — defaulting to connect request", "warn")
                                        degree = "UNKNOWN"
                                    # ─────────────────────────────────────────

                                    try:
                                        if degree == "1st":
                                            # Direct message — confirmed delivery
                                            st.session_state.api.send_message(
                                                message_body=message[:280],
                                                recipients=[urn_id]
                                            )
                                            record_sent(urn_id, name, headline, message[:280],
                                                        method="direct_message", degree=degree)
                                            add_log(f"📤 Message sent directly to {name} (1st°) ✔ Logged.", "success")
                                        else:
                                            # Not connected — send connection request with note
                                            note = message[:300]  # LinkedIn invite note limit
                                            if urn_id:
                                                st.session_state.api.add_connection(
                                                    profile_public_id="",
                                                    message=note,
                                                    profile_urn=urn_id
                                                )
                                                record_sent(urn_id, name, headline, note,
                                                            method="connection_request", degree=degree)
                                                add_log(f"🤝 Connection request + note sent to {name} ({degree}°) ✔ Logged.", "success")
                                            else:
                                                add_log(f"⚠️ No urn_id for {name} — cannot send connection request.", "warn")
                                    except Exception as e:
                                        add_log(f"❌ Send failed for {name}: {e}", "error")
                                else:
                                    add_log("💾 Auto-send OFF — review above draft.", "info")
                        else:
                            add_log(f"⏭️  REJECTED: {name}", "warn")
                    else:
                        add_log(f"⚠️ Ollama HTTP {ai_res.status_code}", "error")

                except requests.exceptions.ConnectionError:
                    add_log("❌ Cannot reach Ollama. Is `ollama serve` running?", "error")
                except Exception as e:
                    add_log(f"❌ AI error: {e}", "error")

                # Re-render logs live
                render_logs()
                time.sleep(2)  # rate limit

            add_log("🏁 Campaign complete!", "success")
            progress_bar.progress(1.0, text="Complete!")

        except Exception as e:
            err_msg = str(e)
            add_log(f"❌ Search failed: {err_msg}", "error")
            if "session expired" in err_msg.lower() or "login" in err_msg.lower() or "captcha" in err_msg.lower():
                add_log("💡 Fix: Disconnect → reconnect with fresh cookies from your browser.", "warn")
            elif "rate" in err_msg.lower():
                add_log("💡 Fix: Wait 10–15 minutes before retrying.", "warn")

        st.session_state.running = False
        render_logs()
        st.rerun()

# ── Sent History Tab ──────────────────────────────────────────────────────────

st.markdown("---")
st.subheader("📋 Sent Message History")

sent_log = load_sent_log()

if not sent_log:
    st.info("No messages sent yet. Run a campaign with Auto-send ON to populate this log.")
else:
    h_col1, h_col2 = st.columns([3, 1])
    with h_col1:
        search_q = st.text_input("🔍 Search by name or headline", placeholder="e.g. Milan", key="hist_search", label_visibility="collapsed")
    with h_col2:
        if st.button("🗑️ Clear All History", use_container_width=True):
            save_sent_log({})
            st.success("History cleared.")
            st.rerun()

    rows = [
        {"Name": v["name"], "Headline": v.get("headline", ""),
         "Sent At": v["sent_at"], "Message": v["message"],
         "Method": v.get("method", "direct_message"),
         "Degree": v.get("degree", "?"), "URN": k}
        for k, v in sent_log.items()
    ]
    rows.sort(key=lambda r: r["Sent At"], reverse=True)

    if search_q:
        q = search_q.lower()
        rows = [r for r in rows if q in r["Name"].lower() or q in r["Headline"].lower()]

    st.markdown(f"**{len(rows)} record(s)**")

    for r in rows:
        method_icon = "📤" if r["Method"] == "direct_message" else "🤝"
        method_label = "Direct Message" if r["Method"] == "direct_message" else "Connection Request + Note"
        with st.expander(f"{method_icon} {r['Name']}  —  {r['Sent At']}  [{r['Degree']}° · {method_label}]"):
            st.markdown(f"**Headline:** {r['Headline']}")
            st.markdown(f"**Delivery method:** `{method_label}` (connection degree: **{r['Degree']}**°)")
            st.markdown("**Message sent:**")
            st.code(r["Message"], language=None)
            st.caption(f"LinkedIn URN: `{r['URN']}`")
