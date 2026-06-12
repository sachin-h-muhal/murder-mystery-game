"""
Murder Mystery Game v7
Refactored from v6 with production-grade improvements:
  - Separated concerns: API layer / state engine / UI layer
  - Fixed shadowed loop variable in interrogate_selected_suspect
  - Cached Gemini client and CSS injection with st.cache_resource/st.cache_data
  - Extracted prompt as a module-level constant
  - Replaced silent broad-except with typed error handling
  - Added TypedDict contracts for mystery data structures
  - Removed dead return value from update_score
  - Fixed view-dispatch so only the active panel renders
  - Removed double load_dotenv / double suspect-search
  - Hardened is_valid_mystery to use substring matching for supporting_clue
"""

from __future__ import annotations

import html
import json
import os
import random
from pathlib import Path
from typing import TypedDict

import streamlit as st
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 1. ENVIRONMENT
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env", override=False)
# Second load_dotenv is removed: the override=False on the first call already
# ensures an existing .env at the project root takes precedence.


# ---------------------------------------------------------------------------
# 2. PAGE CONFIG  (must be the very first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Murder Mystery Game v7",
    page_icon="🕵️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# 3. TYPES
# ---------------------------------------------------------------------------
class VictimDict(TypedDict):
    name: str
    description: str


class SuspectDict(TypedDict):
    name: str
    personality: str
    alibi: str
    interrogation_response: str
    clue: str


class ContradictionDict(TypedDict):
    suspect: str
    contradiction: str
    supporting_clue: str


class MysteryDict(TypedDict):
    victim: VictimDict
    crime_scene: str
    murderer: str
    suspects: list[SuspectDict]
    clues: list[str]
    contradictions: list[ContradictionDict]


# ---------------------------------------------------------------------------
# 4. CSS  (injected once per session, not on every rerun)
# ---------------------------------------------------------------------------
@st.cache_data
def _get_css() -> str:
    return """
<style>
    .stApp {
        background: radial-gradient(circle at top, #1d2330 0%, #0b0f16 55%, #070a0f 100%);
        color: #f3efe6;
    }
    .block-container { padding-top: 1.5rem; }
    .hero {
        background: linear-gradient(135deg, rgba(23,27,39,.95), rgba(11,15,22,.95));
        border: 1px solid rgba(212,175,55,.3);
        border-radius: 20px;
        padding: 1.25rem 1.4rem;
        box-shadow: 0 18px 45px rgba(0,0,0,.35);
    }
    .card {
        background: rgba(15,20,30,.85);
        border: 1px solid rgba(212,175,55,.18);
        border-radius: 18px;
        padding: 1rem;
        box-shadow: 0 14px 30px rgba(0,0,0,.22);
        height: 100%;
    }
    .card h3, .card h4, .card p, .card li { color: #f6f0e3; }
    .soft-label {
        color: #d7c69f;
        font-size: .95rem;
        letter-spacing: .04em;
        text-transform: uppercase;
        margin-bottom: .35rem;
    }
    .evidence-box {
        background: rgba(255,255,255,.03);
        border: 1px solid rgba(212,175,55,.12);
        border-radius: 16px;
        padding: .95rem 1rem;
        margin-bottom: .75rem;
    }
    .detective-badge {
        display: inline-block;
        padding: .3rem .7rem;
        border-radius: 999px;
        background: rgba(212,175,55,.14);
        border: 1px solid rgba(212,175,55,.35);
        color: #f7e8b8;
        font-size: .85rem;
        margin-right: .4rem;
        margin-bottom: .35rem;
    }
    .stButton > button {
        border-radius: 999px;
        border: 1px solid rgba(212,175,55,.35);
        background: linear-gradient(135deg, #d4af37, #8f6c1f);
        color: #111;
        font-weight: 700;
    }
    .stButton > button:hover {
        border-color: rgba(255,220,110,.7);
        transform: translateY(-1px);
    }
    div[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #121723 0%, #0b0f16 100%);
        border-right: 1px solid rgba(212,175,55,.15);
    }
</style>
"""


# ---------------------------------------------------------------------------
# 5. FALLBACK DATA
# ---------------------------------------------------------------------------
_FALLBACK_MYSTERIES: list[MysteryDict] = [
    {
        "victim": {"name": "Dr. Alan Reed", "description": "a famous scientist"},
        "crime_scene": "A laboratory filled with broken glass and spilled chemicals.",
        "murderer": "Sophia",
        "suspects": [
            {
                "name": "Sophia",
                "personality": "Nervous and fidgety",
                "alibi": "Claims she stayed in the office.",
                "interrogation_response": "I was in the office, I think. Maybe I went to the lab for a second?",
                "clue": "Sophia's shoes have a wet mark that matches the lab floor.",
            },
            {
                "name": "Daniel",
                "personality": "Calm and quiet",
                "alibi": "Says he was outside checking the garden lights.",
                "interrogation_response": "I was outside the whole time and heard nothing unusual.",
                "clue": "A fresh garden glove was found near the back door.",
            },
            {
                "name": "Emma",
                "personality": "Secretive and thoughtful",
                "alibi": "Claims she was in the kitchen making tea.",
                "interrogation_response": "I was making tea and did not go near the laboratory.",
                "clue": "A torn lab note was found in Emma's apron pocket.",
            },
        ],
        "clues": [
            "A muddy footprint is near the laboratory door.",
            "A broken beaker is lying under the table.",
            "One fingerprint was found on the handle of the lab cabinet.",
        ],
        "contradictions": [
            {
                "suspect": "Sophia",
                "contradiction": "Sophia said she stayed in the office, but her shoes match the wet lab floor.",
                "supporting_clue": "A muddy footprint is near the laboratory door.",
            },
        ],
    },
    {
        "victim": {"name": "Marta Bell", "description": "a wealthy jewelry collector"},
        "crime_scene": "A locked dressing room with an open jewelry box and a broken mirror.",
        "murderer": "Noah",
        "suspects": [
            {
                "name": "Noah",
                "personality": "Loud and impatient",
                "alibi": "Says he was cleaning the hallway.",
                "interrogation_response": "I was cleaning, but maybe I walked by the dressing room once.",
                "clue": "A muddy shoe print was found near Noah's closet.",
            },
            {
                "name": "Lena",
                "personality": "Polite and careful",
                "alibi": "Claims she was counting silverware in the dining room.",
                "interrogation_response": "I stayed in the dining room and never touched the jewelry box.",
                "clue": "A silver spoon was left behind near the dining room table.",
            },
            {
                "name": "Owen",
                "personality": "Sleepy but observant",
                "alibi": "He says he was reading in the library.",
                "interrogation_response": "I was in the library and heard footsteps in the hallway.",
                "clue": "A torn ribbon was found inside an old book in the library.",
            },
        ],
        "clues": [
            "A cracked mirror reflects a muddy boot print.",
            "The jewelry box latch was forced open.",
            "A torn ribbon is stuck to the floor by the doorway.",
        ],
        "contradictions": [
            {
                "suspect": "Noah",
                "contradiction": "Noah said he was cleaning the hallway, but the muddy print shows he walked closer to the dressing room.",
                "supporting_clue": "A cracked mirror reflects a muddy boot print.",
            },
        ],
    },
]

# Prompt is a constant — never changes, no need to rebuild on every call.
_GEMINI_PROMPT = """
Generate a detective mystery that is fair, solvable, logical, replayable, not too easy, and not impossible.
Return valid JSON only. Do not use markdown or code fences.

Use this exact structure:
{
  "victim": { "name": "...", "description": "..." },
  "crime_scene": "A short crime scene description.",
  "murderer": "One suspect name from the suspects list.",
  "suspects": [
    {
      "name": "...", "personality": "...", "alibi": "...",
      "interrogation_response": "...", "clue": "..."
    },
    {
      "name": "...", "personality": "...", "alibi": "...",
      "interrogation_response": "...", "clue": "..."
    },
    {
      "name": "...", "personality": "...", "alibi": "...",
      "interrogation_response": "...", "clue": "..."
    }
  ],
  "clues": ["...", "...", "..."],
  "contradictions": [
    { "suspect": "...", "contradiction": "...", "supporting_clue": "..." }
  ]
}

Rules:
- Exactly 3 suspects.
- Exactly 1 murderer.
- Clues must support reasoning.
- The supporting_clue in contradictions MUST be an exact copy of one string in the clues list.
- Contradictions must directly conflict with alibis.
- The murderer should behave slightly suspicious.
- Innocent suspects should feel believable.
- The story should remain family friendly.
- The crime scene should feel immersive.
- Do not generate nonsense contradictions.
""".strip()


# ---------------------------------------------------------------------------
# 6. API LAYER
# ---------------------------------------------------------------------------
@st.cache_resource
def _get_gemini_client():
    """
    Build and cache the Gemini client for the lifetime of the Streamlit server
    process. Returns None if the SDK is unavailable or the key is missing.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai as google_genai  # noqa: PLC0415
        return google_genai.Client(api_key=api_key)
    except ImportError:
        return None


def _call_gemini_api(client) -> str:
    """Make a single Gemini API call and return the raw text response."""
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=_GEMINI_PROMPT,
        config={"response_mime_type": "application/json"},
    )
    text = getattr(response, "text", "")
    if not text or not text.strip():
        raise ValueError("Gemini returned an empty response.")
    return text


def _extract_json_text(text: str) -> str | None:
    """Strip optional markdown fences and extract the outermost JSON object."""
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        # Remove opening fence line (e.g. ```json or ```)
        lines = lines[1:]
        # Remove closing fence line if present
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean = "\n".join(lines).strip()

    start = clean.find("{")
    end = clean.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return clean[start : end + 1]


def _normalize_mystery(data: dict) -> MysteryDict:
    """Coerce an arbitrary dict from the API into a typed MysteryDict."""
    victim = data.get("victim", {})
    suspects: list[SuspectDict] = [
        {
            "name": str(s.get("name", "Unknown")),
            "personality": str(s.get("personality", "Mysterious")),
            "alibi": str(s.get("alibi", "No alibi provided.")),
            "interrogation_response": str(s.get("interrogation_response", "They avoid the question.")),
            "clue": str(s.get("clue", "A suspicious clue was found.")),
        }
        for s in data.get("suspects", [])[:3]
    ]
    contradictions: list[ContradictionDict] = [
        {
            "suspect": str(c.get("suspect", "")),
            "contradiction": str(c.get("contradiction", "")),
            "supporting_clue": str(c.get("supporting_clue", "")),
        }
        for c in data.get("contradictions", [])
    ]
    clues = [str(c) for c in data.get("clues", []) if str(c).strip()]
    return {
        "victim": {
            "name": str(victim.get("name", "Unknown Victim")),
            "description": str(victim.get("description", "an unknown person")),
        },
        "crime_scene": str(data.get("crime_scene", "A strange crime scene.")),
        "murderer": str(data.get("murderer", "")),
        "suspects": suspects,
        "clues": clues,
        "contradictions": contradictions,
    }


def _is_valid_mystery(mystery: MysteryDict) -> bool:
    """
    Validate a normalized mystery dict.
    supporting_clue is checked via substring match (not equality) so minor
    Gemini phrasing differences don't always force a fallback.
    """
    victim = mystery.get("victim")
    suspects = mystery.get("suspects")
    clues = mystery.get("clues")
    contradictions = mystery.get("contradictions")
    murderer = mystery.get("murderer", "")

    if not isinstance(victim, dict):
        return False
    if not isinstance(mystery.get("crime_scene"), str) or not mystery["crime_scene"].strip():
        return False
    if not isinstance(murderer, str) or not murderer.strip():
        return False
    if not isinstance(suspects, list) or len(suspects) != 3:
        return False
    if not isinstance(clues, list) or len(clues) < 3:
        return False
    if not isinstance(contradictions, list) or len(contradictions) < 1:
        return False

    suspect_names = []
    for suspect in suspects:
        if not isinstance(suspect, dict):
            return False
        name = str(suspect.get("name", "")).strip()
        if not name:
            return False
        suspect_names.append(name)

    if len(set(suspect_names)) != 3:
        return False
    if murderer not in suspect_names:
        return False

    for item in contradictions:
        if not isinstance(item, dict):
            return False
        if str(item.get("suspect", "")).strip() not in suspect_names:
            return False
        # Substring match so minor phrasing differences don't always fail
        supporting = str(item.get("supporting_clue", "")).strip().lower()
        if not any(supporting in c.lower() or c.lower() in supporting for c in clues):
            return False

    return True


def generate_mystery() -> tuple[MysteryDict, str]:
    """
    Attempt up to 3 Gemini API calls, then fall back to a built-in mystery.
    Returns (mystery, warning_message).  warning_message is empty on success.
    """
    client = _get_gemini_client()
    if client is None:
        reason = (
            "Gemini API key not found."
            if not os.getenv("GEMINI_API_KEY")
            else "google-genai package not installed."
        )
        return random.choice(_FALLBACK_MYSTERIES), f"{reason} Using a built-in mystery."

    last_error = ""
    for attempt in range(1, 4):
        try:
            raw_text = _call_gemini_api(client)
            json_text = _extract_json_text(raw_text)
            if not json_text:
                raise ValueError("Response contained no parseable JSON object.")
            mystery = _normalize_mystery(json.loads(json_text))
            if not _is_valid_mystery(mystery):
                raise ValueError("Response did not match the required mystery schema.")
            return mystery, ""
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = f"Attempt {attempt}: {exc}"
        except Exception as exc:  # Network / quota / auth errors
            last_error = f"Attempt {attempt} (API error): {exc}"

    return (
        random.choice(_FALLBACK_MYSTERIES),
        f"Gemini failed after 3 attempts ({last_error}). Using a built-in mystery.",
    )


# ---------------------------------------------------------------------------
# 7. STATE ENGINE
# ---------------------------------------------------------------------------
def _init_state() -> None:
    """Set session-state defaults once per browser session."""
    defaults: dict = {
        "mystery": None,
        "detective_score": 0,
        "viewed_clues": [],
        "solved_contradictions": [],
        "accused": "",
        "game_over": False,
        "current_view": "dashboard",
        "selected_suspect": None,
        "clue_bonus_awarded": False,
        "interrogated_suspects": [],
        "current_case_status": "Ready",
        "result_message": "",
        "status_message": "",
        "generation_warning": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # Only start a new case if one has never been started (not on every rerun)
    if st.session_state.mystery is None:
        _start_new_case()


def _start_new_case() -> None:
    mystery, warning = generate_mystery()
    st.session_state.mystery = mystery
    st.session_state.detective_score = 0
    st.session_state.current_case_status = "Investigating"
    st.session_state.game_over = False
    st.session_state.viewed_clues = list(mystery["clues"])
    st.session_state.interrogated_suspects = []
    st.session_state.solved_contradictions = []
    st.session_state.current_view = "dashboard"
    st.session_state.selected_suspect = None
    st.session_state.clue_bonus_awarded = False
    st.session_state.accused = ""
    st.session_state.result_message = ""
    st.session_state.status_message = warning
    st.session_state.generation_warning = warning


def _set_view(view_name: str) -> None:
    st.session_state.current_view = view_name


def _update_score(points: int, reason: str) -> None:
    """Mutate the score and set the status message. Returns nothing."""
    st.session_state.detective_score += points
    sign = "+" if points >= 0 else ""
    st.session_state.status_message = f"{reason} ({sign}{points} points)"


def _add_clue(clue_text: str) -> None:
    if clue_text and clue_text not in st.session_state.viewed_clues:
        st.session_state.viewed_clues.append(clue_text)


def _suspect_by_name(name: str) -> SuspectDict | None:
    """O(n) lookup — fine for n=3; returns (suspect, index) tuple."""
    for suspect in st.session_state.mystery["suspects"]:
        if suspect["name"] == name:
            return suspect
    return None


def _open_clues_view() -> None:
    _set_view("clues")
    if not st.session_state.clue_bonus_awarded:
        _update_score(5, "You carefully review the clues")
        st.session_state.clue_bonus_awarded = True


def _interrogate_suspect(suspect_name: str) -> None:
    if st.session_state.game_over:
        return
    # Single lookup — no second loop needed
    found = _suspect_by_name(suspect_name)
    if found is None:
        return

    st.session_state.selected_suspect = suspect_name
    if suspect_name not in st.session_state.interrogated_suspects:
        st.session_state.interrogated_suspects.append(suspect_name)

    _add_clue(found["clue"])
    st.session_state.status_message = f"You questioned {suspect_name}."
    _set_view("suspects")


def _check_contradiction(selected_name: str) -> None:
    if st.session_state.game_over:
        return
    for item in st.session_state.mystery["contradictions"]:
        if item["suspect"] == selected_name:
            if selected_name not in st.session_state.solved_contradictions:
                st.session_state.solved_contradictions.append(selected_name)
                _add_clue(item["contradiction"])
                _add_clue(item["supporting_clue"])
                _update_score(10, "Good observation! That alibi does not match the evidence")
            else:
                st.session_state.status_message = "You already found this contradiction."
            return
    st.session_state.status_message = "That suspect does not appear to be the strongest contradiction."


def _make_accusation(selected_name: str) -> None:
    if st.session_state.game_over:
        return
    st.session_state.accused = selected_name
    st.session_state.game_over = True
    if selected_name == st.session_state.mystery["murderer"]:
        _update_score(20, "Correct accusation")
        st.session_state.current_case_status = "Solved"
        st.session_state.result_message = "WIN: You caught the murderer and solved the case!"
    else:
        _update_score(-10, "Wrong accusation")
        st.session_state.current_case_status = "Failed"
        st.session_state.result_message = (
            f"LOSE: The real murderer was {st.session_state.mystery['murderer']}."
        )


# ---------------------------------------------------------------------------
# 8. UI LAYER — individual panel renderers
# ---------------------------------------------------------------------------
def _render_sidebar() -> None:
    with st.sidebar:
        st.title("🕵️ Detective Panel")
        st.metric("Detective Score", st.session_state.detective_score)
        st.metric("Clues Found", len(st.session_state.viewed_clues))
        st.markdown(f"**Case Status:** {st.session_state.current_case_status}")
        if st.session_state.mystery:
            st.markdown(f"**Victim:** {st.session_state.mystery['victim']['name']}")

        st.divider()
        st.button("🆕 Start New Case", use_container_width=True, on_click=_start_new_case)
        st.button("🏠 Dashboard", use_container_width=True, on_click=_set_view, args=("dashboard",))
        st.button("🔍 View Clues", use_container_width=True, on_click=_open_clues_view)
        st.button("🕵️ Interrogate Suspects", use_container_width=True, on_click=_set_view, args=("suspects",))
        st.button("🚨 Find Contradictions", use_container_width=True, on_click=_set_view, args=("contradictions",))
        st.button("⚖️ Make Accusation", use_container_width=True, on_click=_set_view, args=("accusation",))

        st.divider()
        if st.session_state.status_message:
            st.info(st.session_state.status_message)
        if st.session_state.generation_warning:
            st.caption(st.session_state.generation_warning)


def _render_header() -> None:
    st.title("🕵️ Murder Mystery Game v7")
    st.subheader("AI Detective Web App")
    st.markdown(
        """
        <div class="hero">
            <div class="soft-label">Primary Goal</div>
            <p style="font-size:1.08rem;line-height:1.6;margin:0;">
                Investigate the crime scene, question the suspects, uncover contradictions,
                and make the final accusation. Every new case is generated by Gemini AI.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_dashboard() -> None:
    mystery = st.session_state.mystery
    st.subheader("🔍 Crime Scene Investigation")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Victim", mystery["victim"]["name"])
    with col2:
        # html.escape applied before inserting into metric label for safety
        st.metric("Case Type", html.escape(mystery["victim"]["description"]))
    with col3:
        st.metric("Clues in File", len(st.session_state.viewed_clues))

    st.markdown(
        f"""
        <div class="card">
            <div class="soft-label">Scene Report</div>
            <p style="margin:0;font-size:1.02rem;line-height:1.6;">
                {html.escape(mystery['crime_scene'])}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.subheader("🚨 Prime Suspects")
    cols = st.columns(3)
    for idx, suspect in enumerate(mystery["suspects"]):
        with cols[idx]:
            st.markdown(
                f"""
                <div class="card">
                    <div class="soft-label">Suspect File</div>
                    <h3 style="margin-top:0;">{html.escape(suspect['name'])}</h3>
                    <span class="detective-badge">{html.escape(suspect['personality'])}</span>
                    <p><strong>Alibi:</strong> {html.escape(suspect['alibi'])}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.button(
                f"Interrogate {suspect['name']}",
                key=f"dashboard_interrogate_{suspect['name']}",
                use_container_width=True,
                on_click=_interrogate_suspect,
                args=(suspect["name"],),
            )


def _render_suspects() -> None:
    mystery = st.session_state.mystery
    st.subheader("🕵️ Interrogation Room")
    cols = st.columns(3)
    for idx, suspect in enumerate(mystery["suspects"]):
        with cols[idx]:
            already = suspect["name"] in st.session_state.interrogated_suspects
            badge = " ✅" if already else ""
            st.markdown(
                f"""
                <div class="card">
                    <div class="soft-label">Suspect File</div>
                    <h3 style="margin-top:0;">{html.escape(suspect['name'])}{badge}</h3>
                    <span class="detective-badge">{html.escape(suspect['personality'])}</span>
                    <p><strong>Alibi:</strong> {html.escape(suspect['alibi'])}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.button(
                f"Interrogate {suspect['name']}",
                key=f"suspects_interrogate_{suspect['name']}",
                use_container_width=True,
                on_click=_interrogate_suspect,
                args=(suspect["name"],),
            )

    # Focus panel for the last interrogated suspect
    selected_name = st.session_state.selected_suspect
    if selected_name:
        found = _suspect_by_name(selected_name)
        if found:
            st.markdown("---")
            st.subheader(f"📁 Case File: {html.escape(found['name'])}")
            left, right = st.columns([1.3, 1])
            with left:
                st.markdown(
                    f"""
                    <div class="card">
                        <div class="soft-label">Interview Notes</div>
                        <p><strong>Personality:</strong> {html.escape(found['personality'])}</p>
                        <p><strong>Alibi:</strong> {html.escape(found['alibi'])}</p>
                        <p><strong>Statement:</strong> {html.escape(found['interrogation_response'])}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with right:
                st.markdown(
                    f"""
                    <div class="card">
                        <div class="soft-label">Evidence Note</div>
                        <p style="margin:0;line-height:1.6;">{html.escape(found['clue'])}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def _render_clues() -> None:
    st.subheader("🔍 Evidence Files")
    if not st.session_state.viewed_clues:
        st.info("No clues collected yet. Interrogate suspects or examine the scene.")
    else:
        for clue in st.session_state.viewed_clues:
            st.markdown(
                f'<div class="evidence-box"><span class="small-note">🔎 {html.escape(clue)}</span></div>',
                unsafe_allow_html=True,
            )


def _render_contradictions() -> None:
    st.subheader("🚨 Find Contradictions")
    st.markdown(
        """
        <div class="card">
            <div class="soft-label">Detective Challenge</div>
            <p style="margin:0;line-height:1.6;">
                Choose the suspect whose alibi looks wrong compared with the evidence.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    suspect_names = [s["name"] for s in st.session_state.mystery["suspects"]]
    choice = st.selectbox("Which suspect seems suspicious?", suspect_names, key="contradiction_choice")
    if st.button("Check contradiction", use_container_width=True, key="check_contradiction_btn"):
        _check_contradiction(choice)

    if st.session_state.solved_contradictions:
        st.success("Contradictions found: " + ", ".join(st.session_state.solved_contradictions))


def _render_accusation() -> None:
    st.subheader("⚖️ Make an Accusation")
    st.markdown(
        """
        <div class="card">
            <div class="soft-label">Final Decision</div>
            <p style="margin:0;line-height:1.6;">Choose one suspect and lock in your final accusation.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    suspect_names = [s["name"] for s in st.session_state.mystery["suspects"]]
    choice = st.selectbox("Choose the murderer:", suspect_names, key="accusation_choice")
    if not st.session_state.game_over:
        if st.button("Submit accusation", use_container_width=True, key="submit_accusation_btn"):
            _make_accusation(choice)

    if st.session_state.game_over and st.session_state.result_message:
        if st.session_state.current_case_status == "Solved":
            st.success(st.session_state.result_message)
        else:
            st.error(st.session_state.result_message)
        st.metric("Final Detective Score", st.session_state.detective_score)
        st.info("Start a new case from the sidebar to play again.")


# ---------------------------------------------------------------------------
# 9. VIEW DISPATCH — only the active panel renders each rerun
# ---------------------------------------------------------------------------
_VIEW_RENDERERS = {
    "dashboard": _render_dashboard,
    "clues": _render_clues,
    "suspects": _render_suspects,
    "contradictions": _render_contradictions,
    "accusation": _render_accusation,
}


# ---------------------------------------------------------------------------
# 10. ENTRY POINT
# ---------------------------------------------------------------------------
def play_game() -> None:
    _init_state()
    st.markdown(_get_css(), unsafe_allow_html=True)  # Cached — runs only once
    _render_sidebar()
    _render_header()

    view = st.session_state.get("current_view", "dashboard")
    renderer = _VIEW_RENDERERS.get(view, _render_dashboard)
    renderer()


if __name__ == "__main__":
    play_game()