"""
ui/app.py — Streamlit chat interface for the AI Infrastructure Advisor.
Owner: Person 3
Status: IMPLEMENTED (Epic 8, updated Epic 13, Epic 14)

Entry point: streamlit run ui/app.py
"""

import html as html_mod
import logging
import pathlib
from datetime import datetime

import markdown
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from region_validator import is_valid_region  # noqa: F401
from db.database import init_db
from cache.redis_cache import get_scan_cache, write_scan_cache
from db.session_manager import (
    create_session,
    list_sessions,
    delete_session,
    update_session_name,
    save_message,
    load_messages,
    generate_session_name,
)

logger = logging.getLogger(__name__)

_REFRESH_TRIGGERS = (
    "refresh", "rescan", "re-scan", "re-fetch",
    "refetch", "update",
)

SUPPORTED_REGIONS = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "ca-central-1", "eu-west-1", "eu-west-2", "eu-central-1",
    "ap-southeast-1", "ap-southeast-2", "ap-northeast-1", "ap-south-1",
]

REGION_LABELS = {
    "us-east-1": "🇺🇸 US East (N. Virginia)",
    "us-east-2": "🇺🇸 US East (Ohio)",
    "us-west-1": "🇺🇸 US West (N. California)",
    "us-west-2": "🇺🇸 US West (Oregon)",
    "ca-central-1": "🇨🇦 Canada (Central)",
    "eu-west-1": "🇪🇺 EU West (Ireland)",
    "eu-west-2": "🇬🇧 EU West (London)",
    "eu-central-1": "🇩🇪 EU Central (Frankfurt)",
    "ap-southeast-1": "🇸🇬 AP Southeast (Singapore)",
    "ap-southeast-2": "🇦🇺 AP Southeast (Sydney)",
    "ap-northeast-1": "🇯🇵 AP Northeast (Tokyo)",
    "ap-south-1": "🇮🇳 AP South (Mumbai)",
}

STAR_TOOLTIP = "More signals = higher confidence in findings."

USER_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" '
    'stroke="white" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round">'
    '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>'
    '<circle cx="12" cy="7" r="4"/></svg>'
)

BOT_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" '
    'stroke="white" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round">'
    '<path d="M12 8V4H8"/>'
    '<rect width="16" height="12" x="4" y="8" rx="2"/>'
    '<path d="M2 14h2"/><path d="M20 14h2"/>'
    '<path d="M15 13v2"/><path d="M9 13v2"/></svg>'
)


# ---------------------------------------------------------------------------
# DB init
# ---------------------------------------------------------------------------

if "db_available" not in st.session_state:
    st.session_state.db_available = init_db()

db_available = st.session_state.db_available

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="AI Infrastructure Advisor",
    page_icon="🔍",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Load CSS
# ---------------------------------------------------------------------------

_CSS_PATH = pathlib.Path(__file__).parent / "styles.css"
if _CSS_PATH.exists():
    st.markdown(
        f"<style>{_CSS_PATH.read_text()}</style>",
        unsafe_allow_html=True,
    )
else:
    logger.warning("styles.css not found at %s", _CSS_PATH)


# ---------------------------------------------------------------------------
# Markdown → HTML
# ---------------------------------------------------------------------------

def _md_to_html(text: str) -> str:
    return markdown.markdown(
        text,
        extensions=[
            "tables", "fenced_code", "nl2br",
            "sane_lists", "smarty",
        ],
    )


# ---------------------------------------------------------------------------
# Chat bubble renderer
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now().strftime("%I:%M %p")


def render_bubble(role: str, content: str, timestamp: str = "") -> None:
    if role == "user":
        row_cls = "user-row"
        bubble_cls = "user-bubble"
        avatar_cls = "user-avatar"
        icon = USER_ICON
        align = "flex-end"
    else:
        row_cls = "assistant-row"
        bubble_cls = "assistant-bubble"
        avatar_cls = "assistant-avatar"
        icon = BOT_ICON
        align = "flex-start"

    time_html = ""
    if timestamp:
        time_html = (
            f'<div class="chat-time">'
            f"{html_mod.escape(timestamp)}</div>"
        )

    content_html = _md_to_html(content)

    st.markdown(
        f'<div class="chat-row {row_cls}">'
        f'<div class="chat-avatar {avatar_cls}">{icon}</div>'
        f'<div style="display:flex;flex-direction:column;'
        f"align-items:{align};max-width:75%;min-width:0;flex:1;"
        f'">'
        f'<div class="chat-bubble {bubble_cls}">'
        f"{content_html}"
        f"</div>"
        f"{time_html}"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_typing_indicator() -> None:
    st.markdown(
        f'<div class="chat-row assistant-row">'
        f'<div class="chat-avatar assistant-avatar">{BOT_ICON}</div>'
        f'<div style="display:flex;flex-direction:column;'
        f'align-items:flex-start;max-width:75%;min-width:0;flex:1;">'
        f'<div class="typing-bubble">'
        f"<span></span><span></span><span></span>"
        f"</div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_scan_animation() -> None:
    st.markdown(
        f'<div class="chat-row assistant-row">'
        f'<div class="chat-avatar assistant-avatar">{BOT_ICON}</div>'
        f'<div style="display:flex;flex-direction:column;gap:0.4rem;'
        f'align-items:flex-start;max-width:75%;min-width:0;flex:1;">'
        f'<div class="typing-bubble">'
        f"<span></span><span></span><span></span>"
        f"</div>"
        f'<div class="scan-progress">'
        f'<div class="scan-progress-bar">'
        f'<div class="scan-progress-fill"></div></div>'
        f'<div class="scan-progress-text">'
        f"Scanning infrastructure…</div>"
        f"</div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_all_messages() -> None:
    for msg in st.session_state.get("messages", []):
        render_bubble(
            msg["role"], msg["content"], msg.get("timestamp", ""),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def confidence_to_stars(confidence) -> str:
    return {"high": "⭐⭐⭐", "medium": "⭐⭐", "low": "⭐"}.get(
        confidence, "⭐"
    )


def _start_new_session(region: str) -> None:
    for key in list(st.session_state.keys()):
        if key not in ("db_available",):
            del st.session_state[key]

    session_id = create_session(region) if db_available else None
    st.session_state.region = region
    st.session_state.session_id = session_id
    st.session_state.messages = []
    st.session_state.scan_done = False
    st.session_state.session_named = False
    st.session_state.waiting_for_response = False
    st.session_state.pending_prompt = None
    st.session_state.renaming_session = None

    from agent.agent import create_agent
    st.session_state.agent = create_agent(
        region, session_id=session_id, db_available=db_available,
    )


def get_agent_response(agent, prompt: str) -> str:
    try:
        response = agent.invoke({"input": prompt})
        return response.get("output", "I couldn't generate a response.")
    except Exception as exc:
        logger.error("Agent error: %s", exc, exc_info=True)
        return f"I encountered an error: {exc}"


# ---------------------------------------------------------------------------
# Dashboard renderers
# ---------------------------------------------------------------------------

def render_resource_cards(scan_data: dict) -> None:
    ec2 = scan_data.get("ec2", {})
    rds = scan_data.get("rds", {})
    overview = scan_data.get("resource_overview", {}).get("overview", {})
    s3d = overview.get("s3", {})
    ld = overview.get("lambda", {})
    oth = overview.get("other", {})

    ei = ec2.get("instances", [])
    ri = rds.get("instances", [])

    cards = [
        ("EC2", len(ei), "🖥️", "#3b82f6", "#6366f1", "rgba(59,130,246,0.1)"),
        ("RDS", len(ri), "🗄️", "#0ea5e9", "#06b6d4", "rgba(14,165,233,0.1)"),
        ("S3", s3d.get("total_buckets", 0), "🪣",
         "#f59e0b", "#f97316", "rgba(245,158,11,0.1)"),
        ("Lambda", ld.get("total_functions", 0), "⚡",
         "#8b5cf6", "#a855f7", "rgba(139,92,246,0.1)"),
        ("VPCs", oth.get("vpcs", 0), "🌐",
         "#10b981", "#059669", "rgba(16,185,129,0.1)"),
        ("EBS", oth.get("unattached_ebs_volumes", 0), "💾",
         "#64748b", "#475569", "rgba(100,116,139,0.1)"),
        ("EIPs", oth.get("unattached_elastic_ips", 0), "📡",
         "#ec4899", "#f43f5e", "rgba(236,72,153,0.1)"),
    ]

    st.markdown(
        '<div class="infra-section-title">'
        "Infrastructure Overview</div>",
        unsafe_allow_html=True,
    )
    cols = st.columns(len(cards))
    for col, (lbl, cnt, ico, cf, ct, ibg) in zip(cols, cards):
        with col:
            bd = ""
            st.markdown(
                f'<div class="infra-card">'
                f'<div class="infra-card-bar" style="background:'
                f'linear-gradient(90deg,{cf},{ct});"></div>'
                f'<div class="infra-card-icon" '
                f'style="background:{ibg};">{ico}</div>'
                f'<div class="infra-card-count" style="background:'
                f"linear-gradient(135deg,{cf},{ct});"
                f"-webkit-background-clip:text;"
                f"-webkit-text-fill-color:transparent;"
                f'background-clip:text;">{cnt}</div>'
                f'<div class="infra-card-label">{lbl}</div>'
                + (f'<div style="margin-top:6px;">{bd}</div>'
                   if bd else "")
                + "</div>",
                unsafe_allow_html=True,
            )


def render_proactive_summary(sec_ct, waste, res_ct, conf) -> None:
    st.markdown(
        '<div class="infra-section-title">Quick Actions</div>',
        unsafe_allow_html=True,
    )

    action_cards = [
        ("🔴", "Security", f"{sec_ct} critical/high",
         "#ef4444", "#f87171", "rgba(239,68,68,0.1)",
         "Tell me about the security risks",
         "Critical and high severity findings needing attention."),
        ("💰", "Cost Savings", f"${waste:.0f}/month",
         "#f59e0b", "#fbbf24", "rgba(245,158,11,0.1)",
         "What is the total I could save?",
         "Estimated savings from idle and overprovisioned resources."),
        ("📦", "Resources", f"{res_ct} scanned",
         "#3b82f6", "#60a5fa", "rgba(59,130,246,0.1)",
         "Give me an overview of all my resources",
         "Total EC2 and RDS instances analyzed across this region."),
    ]

    cs = confidence_to_stars(conf) if conf else "—"
    conf_label = conf.capitalize() if conf else "N/A"

    cols = st.columns(len(action_cards) + 1)

    for col, (ico, label, value, cf, ct, ibg, prefill, tip) in zip(
        cols, action_cards
    ):
        with col:
            if st.button(
                f"{ico}  {label}: {value}",
                key=f"action_{label.lower().replace(' ', '_')}",
                use_container_width=True,
            ):
                st.session_state.prefill_input = prefill
                st.rerun()
            st.markdown(
                f'<div class="infra-card" style="cursor:pointer;">'
                f'<div class="infra-card-bar" style="background:'
                f'linear-gradient(90deg,{cf},{ct});"></div>'
                f'<div class="infra-card-icon" '
                f'style="background:{ibg};">{ico}</div>'
                f'<div class="infra-card-count" style="background:'
                f"linear-gradient(135deg,{cf},{ct});"
                f"-webkit-background-clip:text;"
                f"-webkit-text-fill-color:transparent;"
                f'background-clip:text;">{value}</div>'
                f'<div class="infra-card-label">{label}</div>'
                f'<div style="font-size:0.75rem;color:#94a3b8 !important;'
                f'line-height:1.4;margin-top:4px;">{tip}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )

    with cols[-1]:
        if st.button(
            f"🎯  Confidence: {cs} {conf_label}",
            key="action_confidence",
            use_container_width=True,
        ):
            st.session_state.prefill_input = (
                "Explain the confidence scores for my infrastructure findings"
            )
            st.rerun()
        st.markdown(
            f'<div class="infra-card" style="cursor:pointer;">'
            f'<div class="infra-card-bar" style="background:'
            f'linear-gradient(90deg,#6366f1,#8b5cf6);"></div>'
            f'<div class="infra-card-icon" '
            f'style="background:rgba(99,102,241,0.1);">🎯</div>'
            f'<div class="infra-card-count" style="background:'
            f"linear-gradient(135deg,#6366f1,#8b5cf6);"
            f"-webkit-background-clip:text;"
            f"-webkit-text-fill-color:transparent;"
            f'background-clip:text;">{cs}</div>'
            f'<div class="infra-card-label">Confidence</div>'
            f'<div style="font-size:0.75rem;color:#94a3b8 !important;'
            f'line-height:1.4;margin-top:4px;">{STAR_TOOLTIP}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown(
        '<div style="text-align:center;padding:0.8rem 0 0.4rem;">'
        '<div style="font-size:2.4rem;line-height:1;margin-bottom:0.35rem;'
        'filter:drop-shadow(0 0 14px rgba(99,102,241,0.5));">🔍</div>'
        '<div style="font-size:1.1rem;font-weight:800;'
        "background:linear-gradient(135deg,#818cf8,#c084fc);"
        "-webkit-background-clip:text;"
        "-webkit-text-fill-color:transparent;"
        'background-clip:text;">AI Infra Advisor</div>'
        '<div style="font-size:0.55rem;color:#3e4c63 !important;'
        "font-weight:600;letter-spacing:1.5px;"
        'text-transform:uppercase;margin-top:3px;">'
        "AWS Intelligence Suite</div></div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    if not db_available:
        st.warning("⚠️ DB unavailable — history not saved.")

    current_region = st.session_state.get("region", "us-east-1")
    default_idx = (
        SUPPORTED_REGIONS.index(current_region)
        if current_region in SUPPORTED_REGIONS else 0
    )
    selected_region = st.selectbox(
        "AWS Region", SUPPORTED_REGIONS, index=default_idx,
        format_func=lambda r: REGION_LABELS.get(r, r),
        key="region_selector",
    )
    st.markdown(
        f'<div style="text-align:center;margin:-0.4rem 0 0.5rem;">'
        f'<span style="font-size:0.63rem;background:rgba(99,102,241,0.1);'
        f"color:#818cf8;padding:3px 12px;border-radius:20px;"
        f'font-family:monospace;font-weight:600;">'
        f"{selected_region}</span></div>",
        unsafe_allow_html=True,
    )

    if (
        "region" in st.session_state
        and selected_region != st.session_state.region
    ):
        try:
            with st.spinner(f"Switching to {selected_region}..."):
                _start_new_session(selected_region)
            st.rerun()
        except EnvironmentError as exc:
            st.error(f"Configuration error: {exc}")
        except Exception as exc:
            st.error(f"Failed to switch region: {exc}")

    st.markdown("---")

    # ── Session list with 3-dot menu ──────────────────────────────
    if db_available:
        st.markdown(
            '<div class="sidebar-label">'
            '<span style="font-size:0.85rem;">💬</span>'
            " Chat Sessions</div>",
            unsafe_allow_html=True,
        )
        sessions = list_sessions()
        active_id = st.session_state.get("session_id")

        # Init rename state
        if "renaming_session" not in st.session_state:
            st.session_state.renaming_session = None

        if not sessions:
            st.markdown(
                '<div style="text-align:center;padding:0.8rem 0.5rem;'
                "color:#293548 !important;font-size:0.78rem;"
                'font-style:italic;">No sessions yet</div>',
                unsafe_allow_html=True,
            )

        for s in sessions:
            is_active = s["id"] == active_id
            is_renaming = st.session_state.renaming_session == s["id"]

            # ── Rename mode ──
            if is_renaming:
                rc1, rc2 = st.columns([4, 1])
                with rc1:
                    new_name = st.text_input(
                        "New name",
                        value=s["name"],
                        key=f"rename_input_{s['id']}",
                        label_visibility="collapsed",
                        placeholder="Enter new name…",
                    )
                with rc2:
                    if st.button("✓", key=f"rename_ok_{s['id']}",
                                 use_container_width=True):
                        if new_name.strip():
                            update_session_name(s["id"], new_name.strip())
                        st.session_state.renaming_session = None
                        st.rerun()
                continue

            # ── Normal mode: session name + 3-dot menu ──
            cn, cd = st.columns([6, 1])

            with cn:
                pf = "▸ " if is_active else "  "
                if st.button(
                    f"{pf}{s['name']}",
                    key=f"sess_{s['id']}",
                    use_container_width=True,
                ):
                    st.session_state.session_id = s["id"]
                    st.session_state.messages = load_messages(s["id"])
                    st.session_state.scan_done = True
                    st.session_state.session_named = True
                    st.session_state.waiting_for_response = False
                    st.session_state.pending_prompt = None
                    st.session_state.renaming_session = None
                    st.rerun()

            with cd:
                with st.popover("⋮", use_container_width=True):
                    if st.button(
                        "Rename",
                        key=f"menu_rename_{s['id']}",
                        use_container_width=True,
                    ):
                        st.session_state.renaming_session = s["id"]
                        st.rerun()

                    if st.button(
                        "Delete",
                        key=f"menu_delete_{s['id']}",
                        use_container_width=True,
                    ):
                        delete_session(s["id"])
                        if active_id == s["id"]:
                            _start_new_session(st.session_state.region)
                        st.session_state.renaming_session = None
                        st.rerun()

        st.markdown(
            '<div style="height:0.35rem;"></div>',
            unsafe_allow_html=True,
        )
        if st.button(
            "＋  New Session", type="primary",
            use_container_width=True,
        ):
            _start_new_session(st.session_state.region)
            st.rerun()

    st.markdown("---")
    st.markdown(
        '<div class="sidebar-label">'
        '<span style="font-size:0.85rem;">⚙️</span> Actions</div>',
        unsafe_allow_html=True,
    )

    if st.button("Refresh Data", use_container_width=True):
        if db_available and st.session_state.get("session_id"):
            write_scan_cache(
                st.session_state.session_id,
                st.session_state.get("region", ""), None,
            )
        for k in ("scan_done", "scan_data"):
            st.session_state.pop(k, None)
        st.rerun()

    if st.button("End Session", use_container_width=True):
        for k in list(st.session_state.keys()):
            if k != "db_available":
                del st.session_state[k]
        st.rerun()

    st.markdown(
        '<div style="margin-top:2rem;padding:0.8rem 0;text-align:center;">'
        '<div style="font-size:0.58rem;color:#293548 !important;">'
        "Built with ❤️  SICubed </div>"
        '<div style="font-size:0.48rem;color:#1a2234 !important;'
        'margin-top:2px;">v2.0</div></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Init session
# ---------------------------------------------------------------------------

if "region" not in st.session_state:
    try:
        with st.spinner(f"Initializing for {selected_region}..."):
            _start_new_session(selected_region)
        st.rerun()
    except EnvironmentError as exc:
        st.error(f"Configuration error: {exc}")
        st.stop()
    except Exception as exc:
        logger.error("Failed to create agent: %s", exc)
        st.error(f"Failed to start session: {exc}")
        st.stop()

# Ensure state keys
if "waiting_for_response" not in st.session_state:
    st.session_state.waiting_for_response = False
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None
if "renaming_session" not in st.session_state:
    st.session_state.renaming_session = None

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

st.title("AI Infrastructure Advisor")
st.caption(
    f"Region: `{st.session_state.region}` — Analyze your AWS "
    f"infrastructure for cost savings opportunities, security risks, and "
    f"best practice violations."
)

# ---------------------------------------------------------------------------
# Proactive scan
# ---------------------------------------------------------------------------

if not st.session_state.get("scan_done", False):
    from agent.prompts import PROACTIVE_SCAN_PROMPT

    scan_placeholder = st.empty()
    with scan_placeholder.container():
        render_scan_animation()

    try:
        scan_prompt = PROACTIVE_SCAN_PROMPT.format(
            region=st.session_state.region,
        )
        response = st.session_state.agent.invoke({"input": scan_prompt})
        summary = response.get(
            "output", "Scan failed. Please try asking manually.",
        )
    except Exception as exc:
        logger.error("Proactive scan failed: %s", exc)
        summary = (
            f"Initial scan encountered an error: {exc}. "
            f"You can ask me to scan manually."
        )

    scan_placeholder.empty()

    st.session_state.messages.append({
        "role": "assistant",
        "content": summary,
        "timestamp": _now(),
    })

    if db_available and st.session_state.get("session_id"):
        save_message(st.session_state.session_id, "assistant", summary)

    if not st.session_state.get("session_named", False):
        name = generate_session_name(
            summary, st.session_state.region, is_scan=True,
        )
        if db_available and st.session_state.get("session_id"):
            update_session_name(st.session_state.session_id, name)
        st.session_state.session_named = True

    try:
        cached = None
        if st.session_state.get("session_id"):
            cached = get_scan_cache(
                st.session_state.session_id,
                st.session_state.region, ttl_minutes=60,
            )
        if cached:
            st.session_state.scan_data = cached
        else:
            # Build scan_data from tool caches populated during the proactive scan
            assembled = {}
            if "ec2_cache" in st.session_state:
                assembled["ec2"] = st.session_state.ec2_cache
            if "rds_cache" in st.session_state:
                assembled["rds"] = st.session_state.rds_cache
            if "security_cache" in st.session_state:
                assembled["security"] = st.session_state.security_cache
            st.session_state.scan_data = assembled
            # Write to DB cache if available
            if assembled and db_available and st.session_state.get("session_id"):
                write_scan_cache(
                    st.session_state.session_id,
                    st.session_state.region,
                    assembled,
                )
    except Exception:
        st.session_state.scan_data = {}

    st.session_state.scan_done = True
    st.rerun()

# ---------------------------------------------------------------------------
# Dashboard cards
# ---------------------------------------------------------------------------

scan_data = st.session_state.get("scan_data", {})
if scan_data:
    render_resource_cards(scan_data)

    sf = scan_data.get("security", {}).get("findings", [])
    ch = [f for f in sf if f.get("severity") in ("critical", "high")]
    ei = scan_data.get("ec2", {}).get("instances", [])
    ri = scan_data.get("rds", {}).get("instances", [])
    waste = (
        sum(i.get("monthly_cost_usd", 0) for i in ei
            if i.get("classification") == "idle")
        + sum(i.get("savings_usd", 0) or 0 for i in ei
              if i.get("classification") == "overprovisioned")
        + sum(i.get("monthly_cost_usd", 0) for i in ri
              if i.get("classification") == "idle")
        + sum(i.get("savings_usd", 0) or 0 for i in ri
              if i.get("classification") == "overprovisioned")
    )
    rc = len(ei) + len(ri)
    cfs = [i.get("confidence") for i in ei + ri if i.get("confidence")]
    oc = (
        "high" if "high" in cfs
        else "medium" if "medium" in cfs
        else "low" if cfs else None
    )
    st.markdown("---")
    render_proactive_summary(len(ch), waste, rc, oc)
    st.markdown("---")

# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------

render_all_messages()

# ---------------------------------------------------------------------------
# Phase 2: waiting for response — show typing then fetch
# ---------------------------------------------------------------------------

if st.session_state.waiting_for_response:
    pending = st.session_state.pending_prompt

    typing_placeholder = st.empty()
    with typing_placeholder.container():
        render_typing_indicator()

    answer = get_agent_response(st.session_state.agent, pending)

    typing_placeholder.empty()

    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "timestamp": _now(),
    })
    if db_available and st.session_state.get("session_id"):
        save_message(st.session_state.session_id, "assistant", answer)

    st.session_state.waiting_for_response = False
    st.session_state.pending_prompt = None
    st.rerun()

# ---------------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------------

prefill = st.session_state.pop("prefill_input", None)
prompt = st.chat_input(
    "Ask about your AWS infrastructure...", key="chat_input",
)
if prefill and not prompt:
    prompt = prefill

if prompt:
    if any(t in prompt.lower() for t in _REFRESH_TRIGGERS):
        write_scan_cache(
            st.session_state.get("session_id"),
            st.session_state.region, None,
        )

    now = _now()
    st.session_state.messages.append({
        "role": "user", "content": prompt, "timestamp": now,
    })
    if db_available and st.session_state.get("session_id"):
        save_message(st.session_state.session_id, "user", prompt)

    if not st.session_state.get("session_named", False):
        name = generate_session_name(
            prompt, st.session_state.region, is_scan=False,
        )
        if db_available and st.session_state.get("session_id"):
            update_session_name(st.session_state.session_id, name)
        st.session_state.session_named = True

    st.session_state.waiting_for_response = True
    st.session_state.pending_prompt = prompt
    st.rerun()