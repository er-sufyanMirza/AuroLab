"""
dashboard/shared.py — AuroLab Design System v4
Aesthetic: Futuristic · Neon · Robotic · Minimal
No CSS custom properties. Streamlit-safe.
"""

import streamlit as st
import httpx

API_BASE = "http://localhost:8080"

# ─────────────────────────────────────────────────────────────────────────────
GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Orbitron:wght@400;600;700;800&family=Inter:wght@300;400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
    background: #020408 !important;
    color: #d0e4f0 !important;
}
*, *::before, *::after { box-sizing: border-box; }

#MainMenu, footer, header, [data-testid="stToolbar"],
[data-testid="stDecoration"], .stDeployButton,
[data-testid="collapsedControl"] { display: none !important; }
[data-testid="stSidebar"] { display: none !important; }
section[data-testid="stSidebarContent"] { display: none !important; }

.main .block-container { padding: 0 !important; max-width: 100% !important; }
.main { padding-top: 0 !important; background: transparent !important; }
.stApp { background: #020408 !important; }

h1,h2,h3 { font-family:'Orbitron',monospace !important; letter-spacing:0.02em !important; }

.stButton > button {
    background: rgba(0,240,200,0.06) !important;
    border: 1px solid rgba(0,240,200,0.25) !important;
    border-radius: 8px !important;
    color: #00f0c8 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.06em !important;
    padding: 0.5rem 1.25rem !important;
    text-transform: uppercase !important;
    transition: all 0.2s ease !important;
}
.stButton > button:hover {
    background: rgba(0,240,200,0.14) !important;
    border-color: rgba(0,240,200,0.6) !important;
    color: #fff !important;
    box-shadow: 0 0 20px rgba(0,240,200,0.15), 0 0 40px rgba(0,240,200,0.08) !important;
    transform: translateY(-1px) !important;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, rgba(108,76,220,0.4), rgba(0,240,200,0.2)) !important;
    border: 1px solid rgba(108,76,220,0.6) !important;
    color: #d0c8ff !important;
    box-shadow: 0 0 20px rgba(108,76,220,0.2) !important;
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, rgba(108,76,220,0.6), rgba(0,240,200,0.3)) !important;
    border-color: #6c4cdc !important;
    box-shadow: 0 0 30px rgba(108,76,220,0.4), 0 0 60px rgba(108,76,220,0.15) !important;
    transform: translateY(-2px) !important;
}
.stSelectbox > div > div,
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    background: rgba(0,240,200,0.03) !important;
    border: 1px solid rgba(0,240,200,0.15) !important;
    border-radius: 8px !important;
    color: #d0e4f0 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
}
.stSelectbox > div > div:hover,
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: rgba(0,240,200,0.5) !important;
    box-shadow: 0 0 0 3px rgba(0,240,200,0.08), 0 0 20px rgba(0,240,200,0.05) !important;
}
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid rgba(0,240,200,0.08) !important;
    gap: 0 !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    color: rgba(160,185,205,0.4) !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.72rem !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    padding: 0.7rem 1.2rem !important;
    transition: all 0.2s !important;
}
.stTabs [aria-selected="true"] {
    color: #00f0c8 !important;
    border-bottom-color: #00f0c8 !important;
    text-shadow: 0 0 12px rgba(0,240,200,0.5) !important;
}
.stExpander {
    background: rgba(0,240,200,0.02) !important;
    border: 1px solid rgba(0,240,200,0.1) !important;
    border-radius: 10px !important;
}
.stSlider > div > div > div { background: rgba(0,240,200,0.2) !important; }
.stSlider > div > div > div > div { background: #00f0c8 !important; box-shadow: 0 0 8px #00f0c8 !important; }
.stDownloadButton > button {
    background: rgba(0,240,200,0.04) !important;
    border-color: rgba(0,240,200,0.2) !important;
    color: #00f0c8 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.72rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
}
div[data-testid="stFileUploader"] {
    background: rgba(0,240,200,0.02) !important;
    border: 1px dashed rgba(0,240,200,0.2) !important;
    border-radius: 12px !important;
}
div[data-testid="stFileUploader"]:hover {
    border-color: rgba(0,240,200,0.4) !important;
    box-shadow: 0 0 20px rgba(0,240,200,0.06) !important;
}

::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: rgba(0,240,200,0.02); }
::-webkit-scrollbar-thumb { background: rgba(0,240,200,0.15); border-radius:10px; }
::-webkit-scrollbar-thumb:hover { background: rgba(0,240,200,0.3); }

@keyframes fadeUp { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }
@keyframes pulse-glow { 0%,100%{opacity:1;box-shadow:0 0 6px #00f0c8} 50%{opacity:0.7;box-shadow:0 0 14px #00f0c8,0 0 24px rgba(0,240,200,0.3)} }
@keyframes scan-down { 0%{top:-2px;opacity:0} 5%{opacity:1} 90%{opacity:0.4} 100%{top:100vh;opacity:0} }
@keyframes grid-drift { 0%{background-position:0 0} 100%{background-position:48px 48px} }
@keyframes neon-border { 0%,100%{border-color:rgba(0,240,200,0.15)} 50%{border-color:rgba(0,240,200,0.35)} }
</style>
"""

# The futuristic background — grid + orbs + scan line
BG_HTML = """
<div id="al-bg" style="
    position:fixed;top:0;left:0;width:100%;height:100%;
    background-image:
        linear-gradient(rgba(0,240,200,0.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,240,200,0.035) 1px, transparent 1px);
    background-size:48px 48px;
    animation:grid-drift 25s linear infinite;
    z-index:-2;pointer-events:none;
"></div>
<div style="
    position:fixed;top:-200px;left:5%;
    width:700px;height:700px;
    background:radial-gradient(circle,rgba(108,76,220,0.1) 0%,transparent 65%);
    z-index:-1;pointer-events:none;
    animation:fadeUp 2s ease;
"></div>
<div style="
    position:fixed;bottom:-150px;right:0%;
    width:600px;height:600px;
    background:radial-gradient(circle,rgba(0,240,200,0.07) 0%,transparent 65%);
    z-index:-1;pointer-events:none;
"></div>
<div id="al-scan" style="
    position:fixed;top:0;left:0;right:0;height:2px;
    background:linear-gradient(90deg,transparent 0%,rgba(0,240,200,0.5) 50%,transparent 100%);
    z-index:999;pointer-events:none;
    animation:scan-down 10s linear infinite;
"></div>
"""

# Top navigation
NAV_CSS = """
<style>
#al-nav {
    position:sticky;top:0;z-index:100;
    display:flex;align-items:center;
    padding:0 2rem;height:56px;
    background:rgba(2,4,8,0.9);
    border-bottom:1px solid rgba(0,240,200,0.1);
    backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);
}
.al-logo {
    font-family:'Orbitron',monospace;font-size:0.9rem;font-weight:800;
    letter-spacing:0.2em;
    background:linear-gradient(90deg,#00f0c8,#7c6af7);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    margin-right:2rem;white-space:nowrap;
}
.al-links { display:flex;gap:2px;flex:1; }
.al-link {
    padding:5px 12px;border-radius:6px;
    font-family:'JetBrains Mono',monospace;
    font-size:0.62rem;font-weight:500;
    color:rgba(160,185,205,0.45);
    letter-spacing:0.1em;text-transform:uppercase;
    border:1px solid transparent;
    cursor:pointer;transition:all 0.15s;
}
.al-link:hover { color:#00f0c8;border-color:rgba(0,240,200,0.2);background:rgba(0,240,200,0.05); }
.al-link.al-active {
    color:#00f0c8;
    border-color:rgba(0,240,200,0.28);
    background:rgba(0,240,200,0.07);
    text-shadow:0 0 10px rgba(0,240,200,0.4);
}
.al-status-dot {
    width:6px;height:6px;border-radius:50%;
    background:#00f0c8;
    animation:pulse-glow 2s infinite;
}
.al-page { padding:0 2rem 4rem;animation:fadeUp 0.3s ease; }
</style>
"""

PLOTLY_DARK = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="JetBrains Mono, monospace", color="rgba(160,185,205,0.5)", size=10),
    xaxis=dict(gridcolor="rgba(0,240,200,0.06)", linecolor="rgba(0,240,200,0.08)",
               tickfont=dict(color="rgba(160,185,205,0.4)"), zerolinecolor="rgba(0,240,200,0.06)"),
    yaxis=dict(gridcolor="rgba(0,240,200,0.06)", linecolor="rgba(0,240,200,0.08)",
               tickfont=dict(color="rgba(160,185,205,0.4)"), zerolinecolor="rgba(0,240,200,0.06)"),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="rgba(160,185,205,0.6)", size=10),
                bordercolor="rgba(0,240,200,0.1)"),
    margin=dict(l=8, r=8, t=36, b=8),
    hoverlabel=dict(bgcolor="#0a1018", bordercolor="rgba(0,240,200,0.3)",
                    font=dict(family="JetBrains Mono, monospace", color="#d0e4f0")),
)


def inject_css():
    st.markdown(GLOBAL_CSS + NAV_CSS, unsafe_allow_html=True)
    st.markdown(BG_HTML, unsafe_allow_html=True)


def render_nav(active: str = ""):
    health = api_get("/health", silent=True)
    online = health is not None
    dot_glow = "box-shadow:0 0 8px #00f0c8;" if online else ""
    dot_bg   = "background:#00f0c8;" if online else "background:#f87171;"
    status_color = "#00f0c8" if online else "#f87171"
    status_text  = "SYS·ONLINE" if online else "SYS·OFFLINE"

    # Logo + status bar (pure HTML — not interactive)
    st.markdown(f"""
    <div style="
        position:sticky;top:0;z-index:100;
        display:flex;align-items:center;
        padding:0 1.5rem;height:56px;
        background:rgba(2,4,8,0.92);
        border-bottom:1px solid rgba(0,240,200,0.1);
        backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);
        margin-bottom:0;
    ">
        <div style="font-family:'Orbitron',monospace;font-size:0.9rem;font-weight:800;
            letter-spacing:0.2em;
            background:linear-gradient(90deg,#00f0c8,#7c6af7);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent;
            margin-right:1.5rem;white-space:nowrap;">AURO·LAB</div>
        <div style="flex:1;"></div>
        <div style="display:flex;align-items:center;gap:7px;">
            <div style="width:6px;height:6px;border-radius:50%;{dot_bg}{dot_glow}animation:pulse-glow 2s infinite;"></div>
            <span style="font-family:'JetBrains Mono',monospace;font-size:0.6rem;
                letter-spacing:0.12em;color:{status_color};">{status_text}</span>
        </div>
    </div>""", unsafe_allow_html=True)

    # Real clickable nav using st.page_link — styled with CSS injection
    st.markdown("""
    <style>
    /* Style all page_link buttons to look like neon nav items */
    /* Nav link styling — both rows */
    [data-testid="stPageLink"] a,
    [data-testid="stPageLink"] a:visited {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        padding: 4px 6px !important;
        border-radius: 5px !important;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 0.58rem !important;
        font-weight: 500 !important;
        color: rgba(160,185,205,0.45) !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        border: 1px solid transparent !important;
        text-decoration: none !important;
        transition: all 0.15s !important;
        background: transparent !important;
        white-space: nowrap !important;
        width: 100% !important;
        min-width: 0 !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    [data-testid="stPageLink"] a:hover {
        color: #00f0c8 !important;
        border-color: rgba(0,240,200,0.25) !important;
        background: rgba(0,240,200,0.06) !important;
        text-shadow: 0 0 8px rgba(0,240,200,0.4) !important;
    }
    [data-testid="stPageLink-active"] a {
        color: #00f0c8 !important;
        border-color: rgba(0,240,200,0.3) !important;
        background: rgba(0,240,200,0.09) !important;
        text-shadow: 0 0 10px rgba(0,240,200,0.5) !important;
    }
    /* Collapse column padding so links sit flush */
    div[data-testid="column"] {
        padding-left: 2px !important;
        padding-right: 2px !important;
        min-width: 0 !important;
    }
    </style>""", unsafe_allow_html=True)

    # ── Nav links — two rows so all pages fit and none are truncated ──────────
    # Row 1: core pages
    row1 = [
        ("app.py",                   "Home"),
        ("pages/1_generate.py",      "Generate"),
        ("pages/2_knowledge.py",     "Knowledge"),
        ("pages/3_eval.py",          "Eval"),
        ("pages/4_history.py",       "History"),
        ("pages/5_health.py",        "Health"),
        ("pages/6_vision.py",        "Vision"),
        ("pages/7_analytics.py",     "Analytics"),
        ("pages/8_fleet.py",         "Fleet"),
    ]
    # Row 2: advanced pages
    row2 = [
        ("pages/9_rl_optimiser.py",  "RL Opt"),
        ("pages/10_digital_twin.py", "Twin"),
        ("pages/11_compare.py",      "Compare"),
        ("pages/12_inventory.py",    "Inventory"),
        ("pages/13_reflect.py",      "Reflect"),
        ("pages/14_workflows.py",    "Workflows"),
        ("pages/15_templates.py",    "Templates"),
        ("pages/16_report.py",       "Report"),
        ("pages/17_optimize.py",     "Optimise"),
        ("pages/18_batch.py",        "Batch"),
        ("pages/19_notebook.py",     "Notebook"),
        ("pages/20_search.py",       "Search"),
        ("pages/21_scheduler.py",    "Scheduler"),
        ("pages/22_eln.py",          "ELN"),
    ]

    def _nav_row(pages_list):
        cols = st.columns(len(pages_list))
        for col, (page_file, label) in zip(cols, pages_list):
            with col:
                try:
                    st.page_link(page_file, label=label, use_container_width=True)
                except Exception:
                    st.markdown(
                        f"<div style='font-family:JetBrains Mono,monospace;"
                        f"font-size:0.58rem;color:rgba(160,185,205,0.35);"
                        f"text-align:center;padding:4px 2px;'>{label}</div>",
                        unsafe_allow_html=True)

    _nav_row(row1)
    st.markdown('<div style="height:2px;"></div>', unsafe_allow_html=True)
    _nav_row(row2)
    st.markdown('<div style="border-bottom:1px solid rgba(0,240,200,0.06);margin-bottom:1.5rem;margin-top:4px;"></div>',
                unsafe_allow_html=True)


def page_close():
    pass  # no-op — div wrapper removed to avoid layout issues


def hero(title: str, subtitle: str, accent: str = "#00f0c8", tag: str = ""):
    """
    Hero section. Uses only sanitizer-safe HTML — no -webkit-background-clip,
    no -webkit-text-fill-color. Those get stripped by Streamlit and show raw HTML.
    """
    if tag:
        st.markdown(
            f'<p style="font-family:JetBrains Mono,monospace;font-size:0.6rem;'
            f'letter-spacing:0.25em;color:{accent};text-transform:uppercase;'
            f'margin:0.5rem 0 0.3rem;opacity:0.8;">⬡  {tag}</p>',
            unsafe_allow_html=True)

    # Title: plain color, no gradient clip (stripped by sanitizer)
    st.markdown(
        f'<div style="font-size:2.1rem;font-weight:800;color:#e8f4ff;'
        f'font-family:Orbitron,monospace;letter-spacing:0.04em;'
        f'margin:0 0 0.5rem;line-height:1.1;border-left:3px solid {accent};'
        f'padding-left:0.8rem;">{title}</div>',
        unsafe_allow_html=True)

    st.markdown(
        f'<p style="color:rgba(160,185,205,0.55);font-size:0.88rem;'
        f'margin:0 0 1.5rem 0;max-width:580px;line-height:1.75;'
        f'padding-left:0.95rem;">{subtitle}</p>',
        unsafe_allow_html=True)

    st.markdown(
        '<div style="border-top:1px solid rgba(0,240,200,0.07);margin:0 0 1.5rem;"></div>',
        unsafe_allow_html=True)


def divider():
    st.markdown('<div style="border-top:1px solid rgba(0,240,200,0.06);margin:1.5rem 0;"></div>',
                unsafe_allow_html=True)


def section_label(text: str, color: str = "#00f0c8"):
    st.markdown(
        f'<div style="font-family:JetBrains Mono,monospace;font-size:0.58rem;'
        f'font-weight:700;color:{color};text-transform:uppercase;letter-spacing:0.18em;'
        f'margin-bottom:10px;opacity:0.7;">'
        f'// {text}</div>',
        unsafe_allow_html=True)


def kpi_row(cards: list, accent_top: str = "#00f0c8"):
    """cards = list of (value, label, color) — uses direct hex, Streamlit-safe"""
    html = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:1.2rem 0;">'
    for value, label, color in cards:
        html += f"""
        <div style="
            background:rgba(0,240,200,0.02);
            border:1px solid rgba(0,240,200,0.1);
            border-top:2px solid {color};
            border-radius:10px;padding:1rem 1.1rem;
            position:relative;overflow:hidden;
            transition:border-color 0.2s;
        ">
            <div style="
                font-family:'Orbitron',monospace;font-size:1.6rem;font-weight:700;
                color:#e8f4ff;line-height:1;margin-bottom:6px;
                text-shadow:0 0 20px rgba(0,240,200,0.15);
            ">{value}</div>
            <div style="
                font-family:'JetBrains Mono',monospace;font-size:0.58rem;font-weight:500;
                color:rgba(160,185,205,0.4);text-transform:uppercase;letter-spacing:0.12em;
            ">{label}</div>
            <div style="
                position:absolute;bottom:0;left:0;right:0;height:1px;
                background:linear-gradient(90deg,transparent,{color},transparent);opacity:0.3;
            "></div>
        </div>"""
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


def neon_card(content_html: str, glow_color: str = "#00f0c8", corners: bool = True):
    corner_html = ""
    if corners:
        c = glow_color
        corner_html = f"""
        <div style="position:absolute;top:8px;left:8px;width:10px;height:10px;border-top:1px solid {c};border-left:1px solid {c};opacity:0.5;"></div>
        <div style="position:absolute;top:8px;right:8px;width:10px;height:10px;border-top:1px solid {c};border-right:1px solid {c};opacity:0.5;"></div>
        <div style="position:absolute;bottom:8px;left:8px;width:10px;height:10px;border-bottom:1px solid {c};border-left:1px solid {c};opacity:0.5;"></div>
        <div style="position:absolute;bottom:8px;right:8px;width:10px;height:10px;border-bottom:1px solid {c};border-right:1px solid {c};opacity:0.5;"></div>"""
    st.markdown(f"""
    <div style="
        background:rgba(255,255,255,0.015);
        border:1px solid rgba(0,240,200,0.1);
        border-radius:12px;padding:1.25rem;
        position:relative;overflow:hidden;
    ">
        {corner_html}
        {content_html}
    </div>""", unsafe_allow_html=True)


def badge(text: str, kind: str = "default"):
    configs = {
        "safe":    ("rgba(0,240,200,0.1)",   "#00f0c8",  "rgba(0,240,200,0.25)",   "0 0 8px rgba(0,240,200,0.2)"),
        "warning": ("rgba(255,211,61,0.1)",  "#ffd33d",  "rgba(255,211,61,0.25)",  "0 0 8px rgba(255,211,61,0.2)"),
        "blocked": ("rgba(248,113,113,0.1)", "#f87171",  "rgba(248,113,113,0.25)", "0 0 8px rgba(248,113,113,0.2)"),
        "running": ("rgba(0,184,255,0.1)",   "#00b8ff",  "rgba(0,184,255,0.25)",   "0 0 8px rgba(0,184,255,0.2)"),
        "idle":    ("rgba(100,120,140,0.1)", "#6478a0",  "rgba(100,120,140,0.2)",  "none"),
        "online":  ("rgba(0,240,200,0.1)",   "#00f0c8",  "rgba(0,240,200,0.25)",   "0 0 8px rgba(0,240,200,0.2)"),
        "offline": ("rgba(248,113,113,0.1)", "#f87171",  "rgba(248,113,113,0.25)", "0 0 8px rgba(248,113,113,0.2)"),
        "default": ("rgba(108,76,220,0.1)",  "#a89ef8",  "rgba(108,76,220,0.25)",  "0 0 8px rgba(108,76,220,0.2)"),
    }
    bg, fg, border, shadow = configs.get(kind, configs["default"])
    return (f'<span style="background:{bg};color:{fg};border:1px solid {border};'
            f'padding:2px 10px;border-radius:4px;'
            f'font-family:JetBrains Mono,monospace;font-size:0.62rem;font-weight:500;'
            f'letter-spacing:0.08em;text-transform:uppercase;'
            f'box-shadow:{shadow};">{text}</span>')


def stats_strip(items: list):
    """items = list of (label, value) tuples"""
    html = '<div style="display:flex;flex-wrap:wrap;gap:2rem;padding:0.9rem 1.4rem;background:rgba(0,240,200,0.02);border:1px solid rgba(0,240,200,0.08);border-radius:10px;margin:1rem 0;">'
    for label, value in items:
        html += f'<div style="display:flex;align-items:center;gap:8px;"><span style="font-family:JetBrains Mono,monospace;font-size:0.58rem;letter-spacing:0.1em;color:rgba(160,185,205,0.35);text-transform:uppercase;">{label}</span><span style="font-family:Orbitron,monospace;font-size:0.72rem;font-weight:600;color:#00f0c8;">{value}</span></div>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


# ── API helpers ───────────────────────────────────────────────────────────────
def api_get(path: str, silent: bool = False) -> dict | None:
    try:
        r = httpx.get(f"{API_BASE}{path}", timeout=12.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        if not silent:
            st.error(f"API error: {e}")
        return None


def api_post(path: str, silent: bool = False, **kwargs) -> dict | None:
    try:
        r = httpx.post(f"{API_BASE}{path}", timeout=90.0, **kwargs)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        if not silent:
            try:    detail = e.response.json().get("detail", str(e))
            except: detail = str(e)
            st.error(f"API {e.response.status_code}: {detail}")
        return None
    except Exception as e:
        if not silent:
            st.error(f"Backend offline — uvicorn services.translation_service.main:app --port 8080 --reload")
        return None


def api_delete(path: str) -> bool:
    try:
        r = httpx.delete(f"{API_BASE}{path}", timeout=12.0)
        return r.status_code in (200, 204)
    except Exception:
        return False


# ── Protocol rendering ────────────────────────────────────────────────────────
def render_step_card(step: dict):
    cites = ", ".join(step.get("citations", [])) or "GENERAL"
    meta_parts = []
    if step.get("duration_seconds"):
        m, s = divmod(int(step["duration_seconds"]), 60)
        meta_parts.append(f"{m}m {s}s" if m else f"{s}s")
    if step.get("temperature_celsius") is not None:
        meta_parts.append(f"{step['temperature_celsius']}°C")
    if step.get("volume_ul") is not None:
        meta_parts.append(f"{step['volume_ul']} µL")
    meta = " · ".join(meta_parts)
    meta_html = f' <span style="color:rgba(160,185,205,0.3);font-size:0.65rem;">· {meta}</span>' if meta else ""
    safety = f'<div style="background:rgba(255,211,61,0.07);border:1px solid rgba(255,211,61,0.2);border-radius:6px;padding:6px 10px;margin-top:8px;font-size:0.75rem;color:#ffd33d;letter-spacing:0.02em;">⚠ {step["safety_note"]}</div>' if step.get("safety_note") else ""
    st.markdown(f"""
    <div style="
        background:rgba(0,240,200,0.015);
        border:1px solid rgba(0,240,200,0.08);
        border-left:2px solid #00f0c8;
        border-radius:0 10px 10px 0;
        padding:0.9rem 1.1rem;margin:7px 0;
        transition:background 0.15s;
        position:relative;overflow:hidden;
    ">
        <div style="
            position:absolute;bottom:0;left:0;right:0;height:1px;
            background:linear-gradient(90deg,#00f0c8,transparent);opacity:0.15;
        "></div>
        <div style="font-family:'JetBrains Mono',monospace;color:#00f0c8;font-size:0.62rem;font-weight:500;text-transform:uppercase;letter-spacing:0.12em;margin-bottom:5px;opacity:0.8;">
            &gt; STEP {step['step_number']}{meta_html}
        </div>
        <div style="color:#d0e4f0;line-height:1.65;font-size:0.9rem;letter-spacing:0.01em;">{step['instruction']}</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:0.62rem;color:rgba(0,240,200,0.35);margin-top:5px;">// SRC: {cites}</div>
        {safety}
    </div>""", unsafe_allow_html=True)


def render_protocol_header(p: dict):
    safety = p.get("safety_level", "safe")
    conf   = p.get("confidence_score", 0)
    model  = p.get("model_used", "")
    gen_ms = p.get("generation_ms", 0)
    h1, h2, h3 = st.columns([4, 1, 1])
    with h1:
        st.markdown(f"""
        <div style="font-family:'Orbitron',monospace;font-size:1.3rem;font-weight:700;
            color:#e8f4ff;letter-spacing:0.03em;margin-bottom:4px;">{p.get('title','Untitled')}</div>
        <div style="font-size:0.82rem;color:rgba(160,185,205,0.5);letter-spacing:0.01em;">{p.get('description','')}</div>
        """, unsafe_allow_html=True)
    with h2:
        st.markdown(f"<br>{badge(safety.upper(), safety)}", unsafe_allow_html=True)
        st.markdown(f"<div style='font-family:JetBrains Mono,monospace;font-size:0.62rem;color:rgba(160,185,205,0.35);margin-top:4px;letter-spacing:0.05em;'>{gen_ms:.0f}ms · {model[:12]}</div>",
                    unsafe_allow_html=True)
    with h3:
        fill = int(conf * 100)
        glow_col = "#00f0c8" if conf > 0.8 else ("#ffd33d" if conf > 0.6 else "#f87171")
        st.markdown(f"""
        <br>
        <div style="font-family:JetBrains Mono,monospace;font-size:0.58rem;color:rgba(160,185,205,0.35);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:4px;">Confidence</div>
        <div style="background:rgba(0,240,200,0.06);border-radius:2px;height:4px;overflow:hidden;border:1px solid rgba(0,240,200,0.1);">
            <div style="background:{glow_col};height:100%;width:{fill}%;border-radius:2px;box-shadow:0 0 8px {glow_col};"></div>
        </div>
        <div style="font-family:'Orbitron',monospace;font-size:0.85rem;font-weight:600;color:{glow_col};margin-top:4px;text-shadow:0 0 10px {glow_col};">{conf:.0%}</div>
        """, unsafe_allow_html=True)


def export_buttons(p: dict, key_prefix: str = ""):
    import json
    c1, c2, c3 = st.columns([1, 1, 4])
    with c1:
        st.download_button("⬇ JSON",
            data=json.dumps(p, indent=2),
            file_name=f"protocol_{p.get('protocol_id','x')[:8]}.json",
            mime="application/json", key=f"{key_prefix}_json")
    with c2:
        lines = [f"# {p.get('title','')}", p.get("description",""), ""]
        for s in p.get("steps", []):
            lines.append(f"[{s['step_number']}] {s['instruction']}")
        st.download_button("⬇ TXT",
            data="\n".join(lines),
            file_name=f"protocol_{p.get('protocol_id','x')[:8]}.txt",
            mime="text/plain", key=f"{key_prefix}_txt")
    with c3:
        st.markdown(f"<span style='font-family:JetBrains Mono,monospace;font-size:0.65rem;color:rgba(160,185,205,0.25);letter-spacing:0.08em;'>// ID: {p.get('protocol_id','')}</span>",
                    unsafe_allow_html=True)


# ── Backward-compatibility shims ─────────────────────────────────────────────
def kpi_card(value, label, color="#00f0c8"):
    """Single KPI card rendered directly via st.markdown. Shim for old pages."""
    st.markdown(f"""
    <div style="background:rgba(0,240,200,0.02);border:1px solid rgba(0,240,200,0.1);border-top:2px solid {color};border-radius:10px;padding:1rem 1.1rem;position:relative;overflow:hidden;">
        <div style="font-family:'Orbitron',monospace;font-size:1.6rem;font-weight:700;color:#e8f4ff;line-height:1;margin-bottom:6px;text-shadow:0 0 20px rgba(0,240,200,0.15);">{value}</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:0.58rem;font-weight:500;color:rgba(160,185,205,0.4);text-transform:uppercase;letter-spacing:0.12em;">{label}</div>
        <div style="position:absolute;bottom:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,{color},transparent);opacity:0.3;"></div>
    </div>""", unsafe_allow_html=True)


def page_header(title: str, subtitle: str = ""):
    """Compatibility shim — calls hero() with default accent."""
    hero(title, subtitle, accent="#00f0c8")