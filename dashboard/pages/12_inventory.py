"""dashboard/pages/12_inventory.py — Reagent Inventory"""
import sys, time
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboard'))
from shared import inject_css, render_nav, hero, api_get, kpi_row, divider, section_label, badge

st.set_page_config(page_title="Inventory — AuroLab", page_icon="⚗", layout="wide",
                   initial_sidebar_state="collapsed")
inject_css()
render_nav("inventory")

hero("REAGENT INVENTORY",
     "Track lab reagent stock levels, expiry dates, and locations — get warned before a protocol runs dry",
     accent="#4ade80", tag="Stock · Expiry · Availability")

# Load inventory
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from services.translation_service.core.reagent_inventory import ReagentInventory
inv = ReagentInventory("./data/inventory.db")

all_reagents = inv.search()
low_stock    = inv.get_low_stock()
expired      = inv.get_expired()

# ── KPIs ──────────────────────────────────────────────────────────────────────
kpi_row([
    (len(all_reagents),  "Total reagents",  "#00f0c8"),
    (sum(1 for r in all_reagents if r.status == "ok"), "In stock", "#4ade80"),
    (len(low_stock),     "Low stock",       "#ffd33d"),
    (len(expired),       "Expired",         "#f87171"),
])
divider()

left, right = st.columns([2, 3], gap="large")

with left:
    section_label("Add reagent")
    with st.form("add_reagent_form", clear_on_submit=True):
        name     = st.text_input("Reagent name *", placeholder="e.g. BCA Protein Assay Reagent A")
        c1, c2   = st.columns(2)
        with c1: qty = st.number_input("Quantity", min_value=0.0, value=100.0, step=10.0)
        with c2: unit = st.selectbox("Unit", ["ml","g","L","µL","mg","units"])
        c3, c4   = st.columns(2)
        with c3: expiry  = st.text_input("Expiry (YYYY-MM-DD)", placeholder="2026-12-31")
        with c4: min_stk = st.number_input("Min stock", min_value=0.0, value=10.0, step=5.0)
        location = st.text_input("Location", placeholder="e.g. Fridge A, Shelf 2")
        supplier = st.text_input("Supplier", placeholder="e.g. Thermo Fisher")
        lot_num  = st.text_input("Lot number", placeholder="e.g. LOT2024A")
        hazard   = st.selectbox("Hazard class", ["none","low","medium","high","corrosive","flammable"])
        submitted = st.form_submit_button("Add to inventory", type="primary", use_container_width=True)

        if submitted and name:
            inv.add_reagent(
                name=name, quantity_ml=qty, unit=unit,
                expiry_date=expiry, location=location,
                supplier=supplier, lot_number=lot_num,
                hazard_class=hazard, minimum_stock=min_stk,
            )
            st.success(f"Added: {name}")
            time.sleep(0.3)
            st.rerun()

    # Check current protocol
    history = st.session_state.get("protocol_history", [])
    if history:
        divider()
        section_label("Check protocol")
        opts = {f"{p.get('title','?')} — {p.get('protocol_id','')[:8]}": p for p in history}
        sel = st.selectbox("Protocol", list(opts.keys()), label_visibility="collapsed")
        if st.button("Check availability", use_container_width=True):
            p = opts[sel]
            result = inv.check_protocol(p.get("protocol_id",""), p.get("reagents",[]))
            if result.all_available:
                st.success("All reagents available")
            else:
                if result.missing:
                    st.error(f"Missing: {', '.join(result.missing)}")
                if result.expired:
                    st.error(f"Expired: {', '.join(result.expired)}")
            for w in result.warnings:
                st.warning(w)

with right:
    section_label("Inventory")
    search_q = st.text_input("Search", placeholder="Name or location...", label_visibility="collapsed")
    reagents = inv.search(search_q) if search_q else all_reagents

    if not reagents:
        st.markdown("""
        <div style="text-align:center;padding:3rem;color:rgba(160,185,205,0.35);">
            <div style="font-size:2rem;margin-bottom:0.8rem;">🧪</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:0.82rem;">No reagents yet</div>
        </div>""", unsafe_allow_html=True)
    else:
        for r in reagents:
            sc = {"ok":"#4ade80","low":"#ffd33d","expired":"#f87171"}.get(r.status,"#888898")
            btype = {"ok":"safe","low":"warning","expired":"blocked"}.get(r.status,"idle")
            exp_html = f"<span style='font-size:0.65rem;color:rgba(160,185,205,0.3);'>exp:{r.expiry_date}</span>" if r.expiry_date else ""

            cols = st.columns([5, 1])
            with cols[0]:
                st.markdown(f"""
                <div style="background:rgba(0,240,200,0.015);border:1px solid rgba(0,240,200,0.07);
                    border-left:2px solid {sc};border-radius:0 8px 8px 0;
                    padding:8px 12px;margin:4px 0;">
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:3px;">
                        <div style="font-size:0.86rem;font-weight:500;color:#d0e4f0;flex:1;">{r.name}</div>
                        {badge(r.status.upper(), btype)}
                    </div>
                    <div style="font-family:'JetBrains Mono',monospace;font-size:0.62rem;
                        color:rgba(160,185,205,0.35);display:flex;gap:12px;">
                        <span style="color:{sc};font-weight:600;">{r.quantity_ml:.1f} {r.unit}</span>
                        <span>min:{r.minimum_stock}</span>
                        {f'<span>{r.location}</span>' if r.location else ''}
                        {exp_html}
                        {f'<span style="color:#f87171;">⚠ {r.hazard_class}</span>' if r.hazard_class not in ("none","") else ''}
                    </div>
                </div>""", unsafe_allow_html=True)
            with cols[1]:
                if st.button("Del", key=f"del_{r.reagent_id[:8]}", use_container_width=True):
                    inv.delete(r.reagent_id)
                    st.rerun()

        # Alerts
        if low_stock or expired:
            divider()
            section_label("Alerts")
            for r in expired:
                st.markdown(f"<div style='background:rgba(248,113,113,0.07);border:1px solid rgba(248,113,113,0.2);border-radius:6px;padding:8px 12px;margin:3px 0;font-size:0.8rem;color:#f87171;'>✗ EXPIRED: {r.name} (lot {r.lot_number})</div>", unsafe_allow_html=True)
            for r in low_stock:
                st.markdown(f"<div style='background:rgba(255,211,61,0.06);border:1px solid rgba(255,211,61,0.18);border-radius:6px;padding:8px 12px;margin:3px 0;font-size:0.8rem;color:#ffd33d;'>⚠ LOW: {r.name} — {r.quantity_ml:.1f} {r.unit} remaining</div>", unsafe_allow_html=True)