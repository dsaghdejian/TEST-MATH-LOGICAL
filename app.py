import streamlit as st
import sqlite3
import hashlib
import hmac
import io
import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

APP_DIR = Path(__file__).parent
ASSET_DIR = APP_DIR / "assets"
DB_PATH = APP_DIR / "fym_test.db"
TOTAL_QUESTIONS = 20
TEST_SECONDS = 40 * 60

# Browser visibility + clipboard best-effort component.
_tab_monitor = components.declare_component("fym_tab_monitor", path=str(APP_DIR / "tab_monitor"))

st.set_page_config(
    page_title="Մաթեմատիկական–տրամաբանական թեստ | FYM",
    page_icon="⚫",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ----------------------------- Database ---------------------------------
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                age INTEGER NOT NULL DEFAULT 0,
                position TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL,
                answers_json TEXT NOT NULL,
                score INTEGER NOT NULL,
                correct_count INTEGER NOT NULL,
                incorrect_count INTEGER NOT NULL,
                tab_events_json TEXT NOT NULL DEFAULT '[]'
            )
        """)
        # Safe migration for databases created by the earlier version.
        columns = {r[1] for r in conn.execute("PRAGMA table_info(attempts)").fetchall()}
        if "position" not in columns:
            conn.execute("ALTER TABLE attempts ADD COLUMN position TEXT NOT NULL DEFAULT ''")
        row = conn.execute("SELECT value FROM settings WHERE key='hr_password_hash'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('hr_password_hash', ?)",
                (hash_password("1234"),)
            )

def get_password_hash():
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='hr_password_hash'").fetchone()
        return row["value"]

def set_password(password):
    with db() as conn:
        conn.execute(
            "UPDATE settings SET value=? WHERE key='hr_password_hash'",
            (hash_password(password),)
        )

def save_attempt(candidate, answers, started_epoch, duration_seconds, tab_events):
    correct = 0
    for q in QUESTIONS:
        if answers.get(str(q["id"])) == q["correct"]:
            correct += 1
    incorrect = TOTAL_QUESTIONS - correct
    now = datetime.now().astimezone()
    started = datetime.fromtimestamp(started_epoch).astimezone()
    with db() as conn:
        cur = conn.execute("""
            INSERT INTO attempts (
                first_name, last_name, age, position, started_at, completed_at,
                duration_seconds, answers_json, score, correct_count,
                incorrect_count, tab_events_json
            ) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            candidate["first_name"], candidate["last_name"], candidate["position"],
            started.isoformat(timespec="seconds"), now.isoformat(timespec="seconds"),
            int(duration_seconds), json.dumps(answers, ensure_ascii=False),
            correct, correct, incorrect, json.dumps(tab_events, ensure_ascii=False)
        ))
        return cur.lastrowid

# ----------------------------- Questions ---------------------------------
QUESTIONS = [
    {"id": 1, "text": "Եթե 2+2=6, 6+6=15, 15+15=34, 34+34=?", "options": ["72", "71", "74", "73"], "correct": "73"},
    {"id": 2, "text": "Եթե A 3 անգամ մեծ է B-ից, իսկ B երկու անգամ C-ից։ Որքա՞ն է A, եթե C հավասար է 5-ի։", "options": ["15", "7.5", "30", "35"], "correct": "30"},
    {"id": 3, "text": "Բացված է գրքի 31-րդ էջը, որը գրքի կենտրոնական էջն է։ Քանի՞ էջ ունի գիրքը։", "options": ["61", "60", "62", "63"], "correct": "61"},
    {"id": 4, "text": "Ո՞րն է հաջորդ թիվը։ 1, 5, 25, 125, ?", "options": ["225", "625", "525", "225"], "correct": "625"},
    {"id": 5, "text": "B-ի 10%-ը հավասար է 5-ի։ Որքա՞ն է B-ի 20%-ը։", "options": ["5", "10", "15", "20"], "correct": "10"},
    {"id": 6, "text": "Շերլոկ Հոլմսը մետաղադրամներով սնդուկ գտավ: Գտնված բոլոր մետաղադրամների ուղիղ կեսը նա տվեց միսիս Բրեյնին, 25%-ը տվեց պետությանը՝ հարկի տեսքով: Ոսկե մետաղադրամների 5-րդ մասը նա դրեց բանկում և իր մոտ մնաց 49 մետաղադրամ: Քանի՞ մետաղադրամ էր գտել Հոլմսը:", "options": ["650", "340", "880", "980"], "correct": "980"},
    {"id": 7, "text": "Գրիչն ու մատիտը միասին արժեն 110 դրամ: Գրիչը մատիտից թանկ է 100 դրամով: Որքա՞ն արժե մատիտը:", "options": ["30", "15", "5", "10"], "correct": "5"},
    {"id": 8, "text": "Փոքրիկ լճակում լողում էր ջրաշուշանը: Ամեն օր այն մեծանում էր 2 անգամ: 28-րդ օրը ջրաշուշանը զբաղեցրեց ամբողջ լճակը: Ո՞ր օրն էր ջրաշուշանը զբաղեցնում լճակի կեսը:", "options": ["12", "20", "14", "27"], "correct": "27"},
    {"id": 9, "text": "Վահեն բարձրահասակ է Արմանից և ցածրահասակ՝ Կարենից: Արամը բարձրահասակ է Գոռից և ցածրահասակ՝ Վահեից: Ո՞վ է ամենաբարձրահասակը:", "options": ["Արման", "Վահեն", "Գոռ", "Կարեն"], "correct": "Կարեն"},
    {"id": 10, "text": "Ամեն ծննդյան օր Աննայի խնայատուփի մեջ ծնողները ավելացնում էին այնքան մետաղադրամ, որքան նրա տարիքն է։ Այժմ խնայատուփի մեջ 21 մետաղադրամ կա։ Քանի՞ տարեկան է Աննան։", "options": ["6", "45", "15", "21"], "correct": "6"},
    {"id": 11, "text": "«Սառը» բառի հականիշի հականիշը կլինի։", "options": ["Տաք", "Սառը"], "correct": "Սառը"},
    {"id": 12, "text": "Տնից դուրս եկան Աշոտն ու Կառլենը և շարժվեցին հակառակ ուղղություններով: Ինչպիսի՞ն է հավանականությունը, որ 3 րոպեից նրանք կգտնվեն մեկ ուղիղ գծի վրա:", "options": ["50%", "100%", "25%", "Անհնար է պարզել"], "correct": "100%"},
    {"id": 13, "text": "Դու կատարել ես քո աշխատանքի 20%-ը: Աշխատանքի ո՞ր մասն է մնացել չարված։", "options": ["1/5", "4/5", "1/4", "7/10"], "correct": "4/5"},
    {"id": 14, "text": "Ո՞ր պատկերն է բաց թողնված։", "image": "14 HARTSOUM.png", "options": ["A. Շրջան՝ ներսում քառակուսի", "B. Շրջան՝ ներսում եռանկյուն", "C. Շրջան՝ ներսում շրջան", "D. Շրջան՝ ներսում աստղ"], "correct": "A. Շրջան՝ ներսում քառակուսի"},
    {"id": 15, "text": "Դասարանում կա 66 աշակերտ, որոնցից 1/3-ը բացակա է։ Քանի՞սն են ներկա։", "options": ["44", "22", "55", "33"], "correct": "44"},
    {"id": 16, "text": "10-ը հավասար է ո՞ր թվի 10%-ին։", "options": ["10", "100", "110", "1000"], "correct": "100"},
    {"id": 17, "text": "Բնակարանը գնվել է 20.000 ԱՄՆ դոլար արժողությամբ, որը տարեկան արժեզրկվում է 10%-ով։ Որքա՞ն կլինի բնակարանի արժեքը 2 տարի հետո։", "options": ["18000", "16000", "15200", "16200"], "correct": "16200"},
    {"id": 18, "text": "Հաճախորդը բացել է բանկային ավանդ 3 ամիս ժամկետով։ Ավանդի տարեկան եկամտաբերությունը 8% է, իսկ ստացված շահույթը կազմել է 20 000 ԱՄՆ դոլար: Որքա՞ն է կազմում սկզբնական ներդրման գումարի չափը։", "options": ["1 800 000", "1 600 000", "1 200 000", "1 000 000"], "correct": "1 000 000"},
    {"id": 19, "text": "Ո՞ր պատկերն է բաց թողնված։", "image": "19 HARTSOUM.png", "options": ["Քառակուսի՝ աջ կողմում գծով", "Քառակուսի՝ մեջտեղի գծով", "Քառակուսի՝ ձախ կողմում գծով", "Քառակուսի՝ վերևի կողմում գծով"], "correct": "Քառակուսի՝ մեջտեղի գծով"},
    {"id": 20, "text": "Ո՞ր թիվն է բաց թողնված։", "image": "20 hartsoum.png", "options": ["10", "11", "12", "13"], "correct": "11"},
]

init_db()

# ----------------------------- Styling -----------------------------------
st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"], .stApp {
    background: #ffffff !important;
    color: #000000 !important;
}
[data-testid="stHeader"] { background: #ffffff !important; }
/* Compact vertical rhythm so the header and test content stay together. */
.block-container { padding-top: 0.45rem !important; padding-bottom: 0.55rem !important; }
[data-testid="stVerticalBlock"] { gap: 0.45rem !important; }
[data-testid="stMarkdownContainer"] h3 { margin-top: 0.05rem !important; margin-bottom: 0.18rem !important; }
[data-testid="stMarkdownContainer"] p { margin-bottom: 0.25rem !important; }
[data-testid="stImage"] { margin-bottom: -0.2rem !important; }
[data-testid="stForm"] { border: 0 !important; padding-top: 0 !important; }
h1, h2, h3, p, label, span, div { color: #000000; }
.stButton > button, .stDownloadButton > button {
    background: #ffffff !important;
    color: #000000 !important;
    border: 1px solid #000000 !important;
    border-radius: 7px !important;
    min-height: 2.6rem;
    box-shadow: none !important;
}
.stButton > button:hover, .stDownloadButton > button:hover,
.stButton > button:focus, .stButton > button:active,
.stDownloadButton > button:focus, .stDownloadButton > button:active {
    background: #ffffff !important;
    color: #000000 !important;
    border: 2px solid #000000 !important;
    box-shadow: none !important;
}
input, textarea, [data-baseweb="select"] > div {
    background: #ffffff !important;
    color: #000000 !important;
    border-color: #000000 !important;
}
[data-testid="stRadio"] label { color: #000000 !important; }
hr { border-color: #000000 !important; margin-top: 0.12rem !important; margin-bottom: 0.12rem !important; }
footer { visibility: hidden; }
/* Best-effort restriction; browser/device-level bypasses remain possible. */
.test-no-select { user-select: none !important; -webkit-user-select: none !important; }
</style>
""", unsafe_allow_html=True)

def show_header():
    """Render the centered test title and FYM logo on the right using native Streamlit elements."""
    logo_candidates = [
        ASSET_DIR / "FYM_Logo_3_Black.png",
        APP_DIR / "FYM_Logo_3_Black.png",
        ASSET_DIR / "FYM_Logo_3_Black(2).png",
        APP_DIR / "FYM_Logo_3_Black(2).png",
        APP_DIR / "FYM_Logo_3_Black(1).png",
        APP_DIR / "FYM_Logo.png",
    ]
    logo = next((p for p in logo_candidates if p.exists()), None)
    if logo is None:
        st.error("Չի գտնվել FYM լոգոն։")
        return

    # Native Streamlit columns + st.image (no HTML base64 data URI)
    spacer_col, title_col, logo_col = st.columns([1.2, 4.6, 1.4], gap="small", vertical_alignment="center")
    with title_col:
        st.markdown(
            "<div style='text-align:center; font-size:17px; font-weight:650; line-height:1.25; "
            "color:#000000; margin:0; padding:0;'>"
            "Մաթեմատիկական–տրամաբանական թեստ"
            "</div>",
            unsafe_allow_html=True,
        )
    with logo_col:
        st.image(str(logo), use_container_width=True)
    st.markdown(
        "<div style='height:1px; background:#000000; margin:4px 0 8px 0;'></div>",
        unsafe_allow_html=True,
    )


def record_tab_event(event):
    if not isinstance(event, dict) or event.get("event") not in {"left", "returned"}:
        return
    events = st.session_state.setdefault("tab_events", [])
    # Ignore duplicate event notifications.
    if events and events[-1].get("event") == event.get("event"):
        return
    now = event.get("at") or datetime.now().astimezone().isoformat(timespec="seconds")
    if event.get("event") == "left":
        events.append({"event": "left", "at": now})
    else:
        if events and events[-1].get("event") == "left":
            left_at = events[-1].get("at")
            try:
                from datetime import datetime as _dt
                left_dt = _dt.fromisoformat(left_at.replace("Z", "+00:00"))
                right_dt = _dt.fromisoformat(now.replace("Z", "+00:00"))
                away = max(0, int((right_dt-left_dt).total_seconds()))
            except Exception:
                away = None
            events.append({"event": "returned", "at": now, "away_seconds": away})

def monitor_test_tab():
    event = _tab_monitor(key="fym_tab_monitor", default=None)
    if event:
        record_tab_event(event)


def go_home():
    for key in ["candidate", "answers", "question_index", "started_epoch", "deadline_epoch", "completed", "attempt_id", "tab_events", "candidate_first_name", "candidate_last_name", "candidate_position", "finish_redirect_at"]:
        st.session_state.pop(key, None)
    st.session_state.page = "home"
    st.rerun()

if "page" not in st.session_state:
    st.session_state.page = "home"

# ----------------------------- Completion --------------------------------
def finish_test():
    if st.session_state.get("completed"):
        return
    elapsed = max(0, int(time.time() - st.session_state.started_epoch))
    events = list(st.session_state.get("tab_events", []))
    if events and events[-1].get("event") == "left":
        now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
        record_tab_event({"event": "returned", "at": now_iso})
        events = list(st.session_state.get("tab_events", []))
    st.session_state.attempt_id = save_attempt(
        st.session_state.candidate,
        st.session_state.answers,
        st.session_state.started_epoch,
        elapsed,
        events,
    )
    st.session_state.completed = True
    st.session_state.page = "finished"

def format_duration(seconds):
    seconds = max(0, int(seconds or 0))
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes} րոպե {remainder} վայրկյան"

def count_tab_departures(raw):
    try:
        return sum(1 for item in json.loads(raw or "[]") if item.get("event") == "left")
    except Exception:
        return 0

def format_away_time(raw):
    try:
        events = json.loads(raw or "[]")
        values = [e.get("away_seconds") for e in events if e.get("event") == "returned" and e.get("away_seconds") is not None]
        total = sum(values)
        return f"{format_duration(total)} (ընդհանուր)"
    except Exception:
        return "Տվյալներ չկան"

# ----------------------------- Home page ---------------------------------
if st.session_state.page == "home":
    show_header()
    st.markdown("### Անձնական տվյալներ.")
    with st.form("candidate_form"):
        first_name = st.text_input("Անուն", autocomplete="off", key="candidate_first_name")
        last_name = st.text_input("Ազգանուն", autocomplete="off", key="candidate_last_name")
        position = st.text_input("Հաստիք", autocomplete="off", key="candidate_position")
        st.caption("Թեստի ընթացքում կարող են գրանցվել դիտարկվող էջից դուրս գալու դեպքերը։")
        start = st.form_submit_button("Սկսել թեստը", use_container_width=True)
    if start:
        if not first_name.strip() or not last_name.strip():
            st.error("Խնդրում ենք լրացնել անունը և ազգանունը։")
        else:
            st.session_state.candidate = {
                "first_name": first_name.strip(),
                "last_name": last_name.strip(),
                "position": position.strip(),
            }
            st.session_state.answers = {}
            st.session_state.tab_events = []
            st.session_state.question_index = 0
            st.session_state.started_epoch = time.time()
            st.session_state.deadline_epoch = st.session_state.started_epoch + TEST_SECONDS
            st.session_state.completed = False
            st.session_state.page = "test"
            st.rerun()

    st.write("")
    st.write("")
    st.divider()
    # HR entry intentionally at the bottom of the main page.
    with st.expander("HR մուտք"):
        with st.form("hr_login_form"):
            password = st.text_input("Գաղտնաբառ", type="password")
            login = st.form_submit_button("Մուտք", use_container_width=True)
        if login:
            if hmac.compare_digest(hash_password(password), get_password_hash()):
                st.session_state.hr_authenticated = True
                st.session_state.page = "hr"
                st.rerun()
            else:
                st.error("Սխալ գաղտնաբառ։")

# ----------------------------- Test page ---------------------------------
elif st.session_state.page == "test":
    show_header()
    st.markdown("<style>body, body * { -webkit-user-select: none !important; user-select: none !important; }</style>", unsafe_allow_html=True)
    monitor_test_tab()
    if time.time() >= st.session_state.deadline_epoch:
        finish_test()
        st.rerun()

    st_autorefresh(interval=1000, key="test_timer_tick")
    remaining = max(0, int(st.session_state.deadline_epoch - time.time()))
    mins, secs = divmod(remaining, 60)
    st.markdown(
        f"<div style='text-align:right;font-size:22px;font-weight:700;'>Մնացած ժամանակը՝ {mins:02d}:{secs:02d}</div>",
        unsafe_allow_html=True
    )
    st.progress((TOTAL_QUESTIONS - remaining / TEST_SECONDS) / TOTAL_QUESTIONS if False else 1 - remaining / TEST_SECONDS)
    idx = st.session_state.question_index
    q = QUESTIONS[idx]
    st.caption(f"Հարց {idx + 1} / {TOTAL_QUESTIONS}")
    st.markdown(f"### {q['text']}")
    if q.get("image"):
        image_path = ASSET_DIR / q["image"]
        if image_path.exists():
            # Keep the complete diagram visible at a controlled size.
            st.image(str(image_path), width=300)
        else:
            st.error(f"Չի գտնվել հարցի նկարը՝ {q['image']}")

    prior = st.session_state.answers.get(str(q["id"]))
    selected_index = q["options"].index(prior) if prior in q["options"] else None
    choice = st.radio(
        "Ընտրեք մեկ պատասխան․",
        q["options"],
        index=selected_index,
        key=f"answer_q_{q['id']}",
    )
    if choice:
        st.session_state.answers[str(q["id"])] = choice

    st.divider()
    left, right = st.columns(2)
    with left:
        if idx > 0 and st.button("Նախորդ", use_container_width=True):
            st.session_state.question_index -= 1
            st.rerun()
    with right:
        if idx < TOTAL_QUESTIONS - 1:
            if st.button("Հաջորդ", use_container_width=True):
                st.session_state.question_index += 1
                st.rerun()
        else:
            if st.button("Ավարտել թեստը", use_container_width=True):
                finish_test()
                st.rerun()

    st.caption("Պատասխանները պահպանվում են հարցերի միջև տեղաշարժվելիս։")
    st.caption("Թեստի էջից դուրս գալու դեպքերը գրանցվում են դիտարկման հնարավորությունների սահմաններում։")

# ----------------------------- Finished page -----------------------------
elif st.session_state.page == "finished":
    show_header()
    st.markdown("<div style='text-align:center; padding-top:35px;'>", unsafe_allow_html=True)
    st.markdown("## Շնորհակալություն թեստը լրացնելու համար։")
    st.markdown("### Ձեր արդյունքները պաշտպանված են և հասանելի են միայն HR բաժնին։")
    st.markdown("Թեստը հաջողությամբ ավարտված է։")
    st.markdown("</div>", unsafe_allow_html=True)
    st.info("Դուք կվերադառնաք գլխավոր էջ։")
    # Browser-side timed redirect back to the app's root.
    st.markdown(
        """<meta http-equiv="refresh" content="4">""",
        unsafe_allow_html=True
    )
    if st.button("Վերադառնալ գլխավոր էջ", use_container_width=True):
        go_home()
    # Automatic reset after a short confirmation period.
    if "finish_redirect_at" not in st.session_state:
        st.session_state.finish_redirect_at = time.time() + 4
    if time.time() >= st.session_state.finish_redirect_at:
        st.session_state.page = "home"
        for k in ["candidate", "answers", "question_index", "started_epoch", "deadline_epoch", "completed", "attempt_id", "tab_events", "candidate_first_name", "candidate_last_name", "candidate_position", "finish_redirect_at"]:
            st.session_state.pop(k, None)
        st.rerun()
    st_autorefresh(interval=1000, key="finish_redirect_tick")

# ----------------------------- HR portal ---------------------------------
elif st.session_state.page == "hr":
    if not st.session_state.get("hr_authenticated"):
        st.session_state.page = "home"
        st.rerun()

    show_header()
    st.title("HR վահանակ")
    st.caption("Թեկնածուների արդյունքներ և հաշվետվություններ")
    top1, top2 = st.columns(2)
    with top1:
        if st.button("Գլխավոր էջ", use_container_width=True):
            go_home()
    with top2:
        if st.button("Ելք HR-ից", use_container_width=True):
            st.session_state.hr_authenticated = False
            st.session_state.page = "home"
            st.rerun()

    with st.expander("Փոխել գաղտնաբառը"):
        with st.form("change_password_form"):
            current = st.text_input("Գործող գաղտնաբառ", type="password")
            new = st.text_input("Նոր գաղտնաբառ", type="password")
            confirm = st.text_input("Կրկնել նոր գաղտնաբառը", type="password")
            change = st.form_submit_button("Պահպանել նոր գաղտնաբառը")
        if change:
            if not hmac.compare_digest(hash_password(current), get_password_hash()):
                st.error("Գործող գաղտնաբառը սխալ է։")
            elif len(new) < 4:
                st.error("Գաղտնաբառը պետք է պարունակի առնվազն 4 նիշ։")
            elif new != confirm:
                st.error("Նոր գաղտնաբառերը չեն համընկնում։")
            else:
                set_password(new)
                st.success("Գաղտնաբառը փոխվել է։")

    with db() as conn:
        rows = conn.execute("SELECT * FROM attempts ORDER BY id DESC").fetchall()
    if not rows:
        st.info("Դեռևս ավարտված թեստեր չկան։")
    else:
        df = pd.DataFrame([dict(r) for r in rows])
        st.subheader("Թեկնածուների ցանկ")
        display = df[["id", "first_name", "last_name", "position", "completed_at", "score", "incorrect_count", "duration_seconds", "tab_events_json"]].copy()
        display["Տևողություն"] = display["duration_seconds"].apply(format_duration)
        display["Թեստից հեռանալու դեպքեր"] = display["tab_events_json"].apply(count_tab_departures)
        display["Ընդհանուր բացակայություն"] = display["tab_events_json"].apply(format_away_time)
        display = display[["id", "first_name", "last_name", "position", "completed_at", "score", "incorrect_count", "Տևողություն", "Թեստից հեռանալու դեպքեր", "Ընդհանուր բացակայություն"]]
        display.columns = ["ID", "Անուն", "Ազգանուն", "Հաստիք", "Ավարտման ամսաթիվ", "Միավոր", "Սխալ", "Տևողություն", "Թեստից հեռանալու դեպքեր", "Ընդհանուր բացակայություն"]
        st.dataframe(display, use_container_width=True, hide_index=True)

        chosen_id = st.selectbox("Ընտրեք թեկնածուին՝ մանրամասն արդյունքները դիտելու համար", df["id"].tolist())
        record = df[df["id"] == chosen_id].iloc[0]
        answers = json.loads(record["answers_json"])
        st.divider()
        st.subheader(f"{record['first_name']} {record['last_name']}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Միավոր", f"{record['score']}/20")
        c2.metric("Ճիշտ", int(record["correct_count"]))
        c3.metric("Սխալ", int(record["incorrect_count"]))
        c4.metric("Արդյունք", f"{record['score'] * 5}%")

        detail_rows = []
        for question in QUESTIONS:
            answer = answers.get(str(question["id"]), "Պատասխան չի ընտրվել")
            is_correct = answer == question["correct"]
            detail_rows.append({
                "Հարց": question["id"],
                "Թեկնածուի պատասխան": answer,
                "Ճիշտ պատասխան": question["correct"],
                "Արդյունք": "Ճիշտ" if is_correct else "Սխալ",
            })
        details = pd.DataFrame(detail_rows)
        st.dataframe(details, use_container_width=True, hide_index=True)

        st.subheader("Թեստից դուրս գալու դիտարկում")
        tab_events = json.loads(record.get("tab_events_json", "[]") or "[]")
        departures = [e for e in tab_events if e.get("event") == "left"]
        total_away = sum(int(e.get("away_seconds") or 0) for e in tab_events if e.get("event") == "returned")
        st.write(f"Թեստից դուրս գալու դեպքերի քանակը՝ **{len(departures)}**")
        st.write(f"Ընդհանուր բացակայության տևողությունը՝ **{format_duration(total_away)}**")
        if departures:
            tab_rows = []
            for i, event in enumerate(departures, 1):
                returned = next((e for e in tab_events[tab_events.index(event)+1:] if e.get("event") == "returned"), None)
                tab_rows.append({"Դեպք": i, "Դուրս գալու ժամ": event.get("at", ""), "Վերադառնալու ժամ": returned.get("at", "Չի գրանցվել") if returned else "Չի գրանցվել", "Բացակայության տևողություն": format_duration(returned.get("away_seconds", 0)) if returned else "Չի գրանցվել"})
            st.dataframe(pd.DataFrame(tab_rows), use_container_width=True, hide_index=True)
        else:
            st.caption("Դիտարկման ընթացքում թեստի էջից դուրս գալու դեպք չի գրանցվել։")

        # Individual Excel workbook for the selected candidate.
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            summary = pd.DataFrame([{
                "Անուն": record["first_name"],
                "Ազգանուն": record["last_name"],
                "Հաստիք": record["position"],
                "Թեստի սկիզբ": record["started_at"],
                "Ավարտման ամսաթիվ": record["completed_at"],
                "Տևողություն": format_duration(record["duration_seconds"]),
                "Թեստից դուրս գալու դեպքեր": len(departures),
                "Ընդհանուր բացակայության տևողություն": format_duration(total_away),
                "Ճիշտ պատասխաններ": record["correct_count"],
                "Սխալ պատասխաններ": record["incorrect_count"],
                "Միավոր": f"{record['score']}/20",
                "Տոկոս": f"{record['score'] * 5}%",
            }])
            summary.to_excel(writer, sheet_name="Ամփոփում", index=False)
            details.to_excel(writer, sheet_name="Հարցերի արդյունքներ", index=False)
        safe_name = f"{record['first_name']}_{record['last_name']}".replace(" ", "_")
        st.download_button(
            "Ներբեռնել թեկնածուի Excel ֆայլը",
            data=output.getvalue(),
            file_name=f"FYM_test_results_{safe_name}_{chosen_id}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        # Download all candidates in one workbook.
        all_output = io.BytesIO()
        all_summary = df[["id", "first_name", "last_name", "position", "started_at", "completed_at", "duration_seconds", "correct_count", "incorrect_count", "score", "tab_events_json"]].copy()
        all_summary["Տևողություն"] = all_summary["duration_seconds"].apply(format_duration)
        all_summary["Թեստից դուրս գալու դեպքեր"] = all_summary["tab_events_json"].apply(count_tab_departures)
        all_summary["Ընդհանուր բացակայություն"] = all_summary["tab_events_json"].apply(format_away_time)
        all_summary["Տոկոս"] = all_summary["score"] * 5
        all_summary = all_summary.drop(columns=["duration_seconds", "tab_events_json"])
        all_summary.to_excel(all_output, index=False, engine="openpyxl")
        st.download_button(
            "Ներբեռնել բոլոր թեկնածուների Excel ֆայլը",
            data=all_output.getvalue(),
            file_name="FYM_all_candidate_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

st.caption("FYM Hospitality Group")
