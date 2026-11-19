import html
import json
import re
import time
import uuid
from datetime import datetime
from urllib.parse import quote
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import streamlit as st
from google import genai

st.set_page_config(
    page_title="Practice Test & Analysis Hub",
    page_icon="Test",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ================= CUSTOM THEME & STYLING =================
st.markdown(
    """
    <style>
        .stApp {
            background: linear-gradient(180deg, #0f172a 0%, #111827 100%);
            color: #f8fafc;
        }
        .hero-card {
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid #334155;
            border-radius: 14px;
            padding: 18px 22px;
            margin-bottom: 16px;
        }
        .metric-card {
            background: #1e293b;
            border: 1px solid #334155;
            border-left: 5px solid #38bdf8;
            border-radius: 12px;
            padding: 14px 16px;
            margin-bottom: 10px;
        }
        .metric-label {
            font-size: 13px;
            color: #94a3b8;
            margin-bottom: 4px;
        }
        .metric-value {
            font-size: 24px;
            font-weight: 700;
            color: #f8fafc;
        }
        .timer-pill {
            background: #450a0a;
            border: 1px solid #f87171;
            color: #fecaca;
            padding: 8px 16px;
            border-radius: 999px;
            font-weight: 700;
            font-size: 16px;
            display: inline-block;
        }
        .paused-pill {
            background: #422006;
            border: 1px solid #f59e0b;
            color: #fde68a;
            padding: 8px 16px;
            border-radius: 999px;
            font-weight: 700;
            font-size: 16px;
            display: inline-block;
        }
        .q-card {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 16px 18px;
            margin-bottom: 14px;
        }
        .review-right {
            background: rgba(20, 83, 45, 0.35);
            border: 1px solid #22c55e;
            border-left: 6px solid #22c55e;
            border-radius: 12px;
            padding: 14px 18px;
            margin-bottom: 10px;
        }
        .review-wrong {
            background: rgba(127, 29, 29, 0.35);
            border: 1px solid #ef4444;
            border-left: 6px solid #ef4444;
            border-radius: 12px;
            padding: 14px 18px;
            margin-bottom: 10px;
        }
        .review-skip {
            background: rgba(120, 53, 15, 0.35);
            border: 1px solid #f59e0b;
            border-left: 6px solid #f59e0b;
            border-radius: 12px;
            padding: 14px 18px;
            margin-bottom: 10px;
        }
        .badge-right {
            background: #16a34a;
            color: #ffffff;
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 700;
        }
        .badge-wrong {
            background: #dc2626;
            color: #ffffff;
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 700;
        }
        .badge-skip {
            background: #d97706;
            color: #ffffff;
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 700;
        }
        div.stButton > button {
            background: linear-gradient(90deg, #0284c7 0%, #2563eb 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            padding: 0.5rem 1rem;
        }
        div.stButton > button:hover {
            background: linear-gradient(90deg, #0369a1 0%, #1d4ed8 100%);
            color: white;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ================= GOOGLE SHEETS CONNECTION =================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TAB_HEADERS = {
    "Users": ["Username", "Password", "Role"],
    "Tests": ["TestID", "TestName", "CreatedBy", "CreatedAt", "QuestionsJSON"],
    "Results": [
        "Timestamp",
        "Username",
        "TestName",
        "Score",
        "Percentage",
        "TotalTimeSec",
        "DetailsJSON",
    ],
    "Sessions": ["SessionID", "Username", "CreatedAt"],
}


@st.cache_resource
def get_spreadsheet():
  if "gcp_service_account" not in st.secrets or "SHEET_URL" not in st.secrets:
    return None
  creds = Credentials.from_service_account_info(
      dict(st.secrets["gcp_service_account"]), scopes=SCOPES
  )
  client = gspread.authorize(creds)
  return client.open_by_url(st.secrets["SHEET_URL"])


def ensure_worksheet(ss, title):
  try:
    ws = ss.worksheet(title)
  except gspread.WorksheetNotFound:
    ws = ss.add_worksheet(title=title, rows=1000, cols=10)
  headers = TAB_HEADERS[title]
  first_row = ws.row_values(1)
  if first_row != headers:
    ws.update("A1", [headers])
  return ws


def load_users_from_sheet(ss):
  ws = ensure_worksheet(ss, "Users")
  rows = ws.get_all_values()
  users = {}
  for r in rows[1:]:
    if len(r) >= 2 and r[0].strip():
      uname = r[0].strip()
      pwd = r[1].strip()
      role = r[2].strip().lower() if len(r) >= 3 and r[2].strip() else "student"
      users[uname] = {"password": pwd, "role": role}
  if not users:
    ws.append_row(["admin", "123", "admin"], value_input_option="RAW")
    users["admin"] = {"password": "123", "role": "admin"}
  return users


def add_user_to_sheet(ss, username, password, role="student"):
  ws = ensure_worksheet(ss, "Users")
  ws.append_row([username, password, role], value_input_option="RAW")


def save_session_to_sheet(ss, sid, username):
  ws = ensure_worksheet(ss, "Sessions")
  ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  ws.append_row([sid, username, ts], value_input_option="RAW")


def get_session_username(ss, sid):
  if not sid:
    return None
  ws = ensure_worksheet(ss, "Sessions")
  rows = ws.get_all_values()
  for r in reversed(rows[1:]):
    if len(r) >= 2 and r[0].strip() == sid:
      return r[1].strip()
  return None


def delete_session_from_sheet(ss, sid):
  if not sid:
    return
  ws = ensure_worksheet(ss, "Sessions")
  rows = ws.get_all_values()
  for idx in range(len(rows), 1, -1):
    if len(rows[idx - 1]) >= 1 and rows[idx - 1][0].strip() == sid:
      ws.delete_rows(idx)
      break


def load_tests_from_sheet(ss):
  ws = ensure_worksheet(ss, "Tests")
  rows = ws.get_all_values()
  tests = []
  for row_num, r in enumerate(rows[1:], start=2):
    if len(r) >= 5 and r[1].strip() and r[4].strip():
      try:
        qs = json.loads(r[4])
        if isinstance(qs, list) and qs:
          tests.append({
              "row_num": row_num,
              "test_id": r[0].strip(),
              "test_name": r[1].strip(),
              "creator": r[2].strip() or "admin",
              "created_at": r[3].strip(),
              "questions": qs,
          })
      except Exception:
        continue
  return tests


def add_test_to_sheet(ss, test_name, creator, questions):
  ws = ensure_worksheet(ss, "Tests")
  test_id = f"T-{uuid.uuid4().hex[:8].upper()}"
  created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
  ws.append_row(
      [
          test_id,
          test_name,
          creator,
          created_at,
          json.dumps(questions, ensure_ascii=False),
      ],
      value_input_option="RAW",
  )


def rename_test_in_sheet(ss, test_obj, new_name):
  ws = ensure_worksheet(ss, "Tests")
  rows = ws.get_all_values()
  tid = test_obj.get("test_id", "")
  for idx in range(2, len(rows) + 1):
    r = rows[idx - 1]
    if (tid and len(r) >= 1 and r[0].strip() == tid) or (
        len(r) >= 2 and r[1].strip() == test_obj.get("test_name", "")
    ):
      ws.update_cell(idx, 2, new_name.strip())
      return True
  return False


def delete_test_from_sheet(ss, test_obj):
  ws = ensure_worksheet(ss, "Tests")
  rows = ws.get_all_values()
  tid = test_obj.get("test_id", "")
  for idx in range(len(rows), 1, -1):
    r = rows[idx - 1]
    if (tid and len(r) >= 1 and r[0].strip() == tid) or (
        len(r) >= 2 and r[1].strip() == test_obj.get("test_name", "")
    ):
      ws.delete_rows(idx)
      return True
  return False


def load_results_from_sheet(ss):
  ws = ensure_worksheet(ss, "Results")
  rows = ws.get_all_values()
  results = []
  for r in rows[1:]:
    if len(r) >= 7 and r[1].strip():
      try:
        pct = float(r[4]) if r[4].strip() else 0.0
      except Exception:
        pct = 0.0
      try:
        t_sec = float(r[5]) if r[5].strip() else 0.0
      except Exception:
        t_sec = 0.0
      try:
        details = json.loads(r[6]) if r[6].strip() else []
      except Exception:
        details = []
      results.append({
          "timestamp": r[0].strip(),
          "username": r[1].strip(),
          "test_name": r[2].strip(),
          "score": r[3].strip(),
          "percentage": pct,
          "total_time_sec": t_sec,
          "details": details,
      })
  return results


def add_result_to_sheet(ss, res_entry):
  ws = ensure_worksheet(ss, "Results")
  ws.append_row(
      [
          res_entry["timestamp"],
          res_entry["username"],
          res_entry["test_name"],
          res_entry["score"],
          str(res_entry["percentage"]),
          str(round(res_entry["total_time_sec"], 2)),
          json.dumps(res_entry["details"], ensure_ascii=False),
      ],
      value_input_option="RAW",
  )


try:
  spreadsheet = get_spreadsheet()
except Exception as conn_err:
  st.error(f"Google Sheet connection error: {conn_err}")
  st.stop()

if spreadsheet is None:
  st.error(
      "Streamlit Secrets me `SHEET_URL` aur `[gcp_service_account]` configure"
      " nahi hai. Pehle Secrets save karein."
  )
  st.stop()

# ================= REFRESH-SAFE SESSION RESTORE =================
query_sid = st.query_params.get("sid")
if "logged_in" not in st.session_state:
  st.session_state.logged_in = False
if "username" not in st.session_state:
  st.session_state.username = ""
if "role" not in st.session_state:
  st.session_state.role = ""
if "session_token" not in st.session_state:
  st.session_state.session_token = ""

if not st.session_state.logged_in and query_sid:
  restored_user = get_session_username(spreadsheet, query_sid)
  if restored_user:
    users_map = load_users_from_sheet(spreadsheet)
    if restored_user in users_map:
      st.session_state.logged_in = True
      st.session_state.username = restored_user
      st.session_state.role = users_map[restored_user]["role"]
      st.session_state.session_token = query_sid

if "current_test" not in st.session_state:
  st.session_state.current_test = None
if "test_active" not in st.session_state:
  st.session_state.test_active = False
if "test_paused" not in st.session_state:
  st.session_state.test_paused = False
if "paused_at" not in st.session_state:
  st.session_state.paused_at = None
if "total_paused_sec" not in st.session_state:
  st.session_state.total_paused_sec = 0.0
if "q_index" not in st.session_state:
  st.session_state.q_index = 0
if "q_last_tick" not in st.session_state:
  st.session_state.q_last_tick = time.time()
if "q_times" not in st.session_state:
  st.session_state.q_times = {}
if "user_answers" not in st.session_state:
  st.session_state.user_answers = {}
if "latest_result" not in st.session_state:
  st.session_state.latest_result = None
if "doubt_explanations" not in st.session_state:
  st.session_state.doubt_explanations = {}


# ================= HELPER FUNCTIONS =================
def format_duration(seconds):
  seconds = max(0, int(round(seconds)))
  mins, secs = divmod(seconds, 60)
  if mins > 0:
    return f"{mins}m {secs:02d}s"
  return f"{secs}s"


def get_active_elapsed():
  if not st.session_state.test_active:
    return 0.0
  now = time.time()
  paused_extra = 0.0
  if st.session_state.test_paused and st.session_state.paused_at is not None:
    paused_extra = max(0.0, now - st.session_state.paused_at)
  return max(
      0.0,
      (now - st.session_state.get("start_time", now))
      - st.session_state.get("total_paused_sec", 0.0)
      - paused_extra,
  )


def record_current_q_time():
  if st.session_state.test_active and not st.session_state.test_paused:
    now = time.time()
    spent = max(0.0, now - st.session_state.q_last_tick)
    idx = st.session_state.q_index
    st.session_state.q_times[idx] = st.session_state.q_times.get(idx, 0.0) + spent
    st.session_state.q_last_tick = now


def pause_test_timer():
  if st.session_state.test_active and not st.session_state.test_paused:
    record_current_q_time()
    st.session_state.test_paused = True
    st.session_state.paused_at = time.time()


def resume_test_timer():
  if st.session_state.test_active and st.session_state.test_paused:
    now = time.time()
    if st.session_state.paused_at is not None:
      st.session_state.total_paused_sec = st.session_state.get(
          "total_paused_sec", 0.0
      ) + max(0.0, now - st.session_state.paused_at)
    st.session_state.paused_at = None
    st.session_state.test_paused = False
    st.session_state.q_last_tick = now


def normalize_questions_df(df):
  col_map = {c.strip().lower(): c for c in df.columns}
  q_col = col_map.get("question") or col_map.get("q")
  a_col = col_map.get("optiona") or col_map.get("a") or col_map.get("option 1")
  b_col = col_map.get("optionb") or col_map.get("b") or col_map.get("option 2")
  c_col = col_map.get("optionc") or col_map.get("c") or col_map.get("option 3")
  d_col = col_map.get("optiond") or col_map.get("d") or col_map.get("option 4")
  ans_col = (
      col_map.get("answer") or col_map.get("ans") or col_map.get("correct")
  )
  exp_col = (
      col_map.get("explanation")
      or col_map.get("solution")
      or col_map.get("hint")
  )

  if not all([q_col, a_col, b_col, c_col, d_col, ans_col]):
    return []

  questions = []
  for _, row in df.iterrows():
    q_txt = str(row[q_col]).strip()
    if not q_txt or q_txt.lower() == "nan":
      continue
    opts = [
        f"A) {str(row[a_col]).strip()}",
        f"B) {str(row[b_col]).strip()}",
        f"C) {str(row[c_col]).strip()}",
        f"D) {str(row[d_col]).strip()}",
    ]
    ans_raw = str(row[ans_col]).strip().upper()
    m_ans = re.search(r"[ABCD]", ans_raw)
    ans_let = m_ans.group(0) if m_ans else "A"
    exp_txt = ""
    if exp_col and pd.notna(row[exp_col]):
      exp_txt = str(row[exp_col]).strip()

    questions.append({
        "question": q_txt,
        "options": opts,
        "answer": ans_let,
        "explanation": exp_txt,
    })
  return questions


def parse_plain_questions(text):
  blocks = re.split(r"\n\s*\n+", text.strip())
  questions = []
  for block in blocks:
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if len(lines) < 5:
      continue
    q_line = re.sub(
        r"^(Q\s*\d*[\.\:\)]\s*)", "", lines[0], flags=re.IGNORECASE
    ).strip()
    opts = []
    ans = "A"
    exp = ""
    for ln in lines[1:]:
      m_exp = re.match(
          r"^(?:Explanation|Solution|Exp)\s*[:\-]\s*(.+)$",
          ln,
          flags=re.IGNORECASE,
      )
      if m_exp:
        exp = m_exp.group(1).strip()
        continue
      m_ans = re.match(
          r"^(?:Answer|Ans|Correct)\s*[:\-]\s*([A-Da-d])",
          ln,
          flags=re.IGNORECASE,
      )
      if m_ans:
        ans = m_ans.group(1).upper()
        continue
      m_opt = re.match(r"^([A-Da-d])[\)\.\:\-]\s*(.+)$", ln)
      if m_opt:
        opts.append(f"{m_opt.group(1).upper()}) {m_opt.group(2).strip()}")
    if q_line and len(opts) >= 4:
      questions.append({
          "question": q_line,
          "options": opts[:4],
          "answer": ans,
          "explanation": exp,
      })
  return questions


def get_correct_option_text(d):
  ans_let = str(d.get("correct", "")).strip().upper()
  for opt in d.get("options", []):
    s = str(opt).strip()
    if re.match(rf"^{re.escape(ans_let)}[\)\.\:\-\s]", s, flags=re.IGNORECASE):
      return s
  return ans_let


def build_doubt_prompt(q_num, d):
  opts_text = "\n".join(d.get("options", []))
  return (
      f"Question {q_num}: {d['question']}\n"
      f"Options:\n{opts_text}\n"
      f"My Answer: {d['user']} | Correct Answer: {d['correct']}\n\n"
      "Is sawal ka clear step-by-step solution aur shortcut trick samjhaiye "
      "ki sahi jawab kyun hai aur mera/chhuta hua attempt kyun galat/skip hua."
  )


def ask_gemini_doubt(prompt_text, api_key):
  client = genai.Client(api_key=api_key.strip())
  response = client.models.generate_content(
      model="gemini-2.5-flash",
      contents=prompt_text,
      config={"max_output_tokens": 1200},
  )
  return (response.text or "").strip()


def render_doubt_box(unique_key, q_num, d):
  prompt_str = build_doubt_prompt(q_num, d)
  encoded_q = quote(prompt_str)

  st.markdown("**Doubt / Solution Poochhein:**")
  b1, b2, b3 = st.columns(3)
  with b1:
    ask_gem_clicked = st.button(
        "Ask Gemini", key=f"ask_gem_{unique_key}", use_container_width=True
    )
  with b2:
    st.link_button(
        "Ask ChatGPT",
        f"https://chatgpt.com/?q={encoded_q}",
        use_container_width=True,
    )
  with b3:
    st.link_button(
        "Ask Claude",
        f"https://claude.ai/new?q={encoded_q}",
        use_container_width=True,
    )

  if ask_gem_clicked:
    gem_key = st.session_state.get("gemini_doubt_key", "").strip()
    if not gem_key:
      st.warning(
          "Ask Gemini ke liye sidebar me 'Gemini API Key (Doubts)' daalein, ya"
          " Ask ChatGPT / Ask Claude button use karein."
      )
    else:
      with st.spinner("Gemini solution de raha hai..."):
        try:
          ans_txt = ask_gemini_doubt(prompt_str, gem_key)
          st.session_state.doubt_explanations[unique_key] = ans_txt
        except Exception as e:
          st.error(f"Gemini error: {e}")

  if unique_key in st.session_state.doubt_explanations:
    st.info(st.session_state.doubt_explanations[unique_key])

  with st.expander("Prompt Copy Karein (Agar manual paste karna ho)"):
    st.code(prompt_str, language="text")


def render_progress_summary(user_results):
  if not user_results:
    return

  total_attempts = len(user_results)
  avg_acc = round(
      sum(r.get("percentage", 0.0) for r in user_results) / total_attempts, 2
  )
  best_acc = max(r.get("percentage", 0.0) for r in user_results)
  total_q_solved = sum(len(r.get("details", [])) for r in user_results)
  total_correct_all = sum(
      sum(1 for d in r.get("details", []) if d.get("status") == "Correct")
      for r in user_results
  )
  total_time_all = sum(r.get("total_time_sec", 0.0) for r in user_results)

  p1, p2, p3, p4, p5 = st.columns(5)
  p_cards = [
      (p1, "Total Attempts", str(total_attempts), "#38bdf8"),
      (p2, "Avg Accuracy", f"{avg_acc}%", "#a78bfa"),
      (p3, "Best Accuracy", f"{best_acc}%", "#22c55e"),
      (p4, "Right / Total Qs", f"{total_correct_all}/{total_q_solved}", "#f59e0b"),
      (p5, "Total Study Time", format_duration(total_time_all), "#ec4899"),
  ]
  for col, lbl, val, accent in p_cards:
    with col:
      st.markdown(
          f"""
          <div class="metric-card" style="border-left-color:{accent};">
              <div class="metric-label">{lbl}</div>
              <div class="metric-value">{html.escape(str(val))}</div>
          </div>
          """,
          unsafe_allow_html=True,
      )

  trend_df = pd.DataFrame([
      {
          "Attempt": f"#{i+1} ({r['test_name'][:18]})",
          "Accuracy (%)": r.get("percentage", 0.0),
      }
      for i, r in enumerate(user_results)
  ]).set_index("Attempt")
  st.markdown("#### Accuracy Progress Trend")
  st.line_chart(trend_df)


def render_test_analysis(result_obj, scope_prefix="res"):
  correct_cnt = sum(1 for d in result_obj["details"] if d["status"] == "Correct")
  wrong_cnt = sum(1 for d in result_obj["details"] if d["status"] == "Wrong")
  skip_cnt = sum(1 for d in result_obj["details"] if d["status"] == "Skipped")
  total_time_str = format_duration(result_obj.get("total_time_sec", 0))
  accuracy = result_obj.get("percentage", 0)

  safe_title = html.escape(str(result_obj["test_name"]))
  safe_user = html.escape(str(result_obj["username"]))
  safe_ts = html.escape(str(result_obj["timestamp"]))

  st.markdown(
      f"""
      <div class="hero-card">
          <h3 style="margin:0 0 6px 0; color:#38bdf8;">Test Analysis & Answer Key: {safe_title}</h3>
          <div style="color:#cbd5e1; font-size:14px;">
              User: <b>{safe_user}</b> | Submitted: <b>{safe_ts}</b> | Total Time Taken: <b>{total_time_str}</b>
          </div>
      </div>
      """,
      unsafe_allow_html=True,
  )

  c1, c2, c3, c4, c5 = st.columns(5)
  cards = [
      (c1, "Score", result_obj["score"], "#38bdf8"),
      (c2, "Accuracy", f"{accuracy}%", "#a78bfa"),
      (c3, "Correct", str(correct_cnt), "#22c55e"),
      (c4, "Wrong", str(wrong_cnt), "#ef4444"),
      (c5, "Skipped", str(skip_cnt), "#f59e0b"),
  ]
  for col, lbl, val, accent in cards:
    with col:
      st.markdown(
          f"""
          <div class="metric-card" style="border-left-color:{accent};">
              <div class="metric-label">{lbl}</div>
              <div class="metric-value">{html.escape(str(val))}</div>
          </div>
          """,
          unsafe_allow_html=True,
      )

  # Full Answer Key Summary Table
  st.markdown("### Complete Answer Key Sheet")
  key_rows = []
  for idx, d in enumerate(result_obj["details"]):
    key_rows.append({
        "Q.No": idx + 1,
        "Your Answer": d["user"],
        "Correct Answer": d["correct"],
        "Correct Option": get_correct_option_text(d),
        "Status": d["status"],
        "Time": format_duration(d.get("time_sec", 0)),
    })
  if key_rows:
    st.dataframe(pd.DataFrame(key_rows), use_container_width=True, hide_index=True)

  st.markdown("### Question-by-Question Breakdown & Solutions")
  for idx, d in enumerate(result_obj["details"]):
    q_time_str = format_duration(d.get("time_sec", 0))
    status = d["status"]
    safe_q = html.escape(str(d["question"]))
    safe_u = html.escape(str(d["user"]))
    safe_c = html.escape(str(d["correct"]))
    safe_ans_opt = html.escape(get_correct_option_text(d))
    exp_raw = str(d.get("explanation", "") or "").strip()

    if status == "Correct":
      box_cls = "review-right"
      badge_cls = "badge-right"
      badge_txt = "CORRECT"
    elif status == "Wrong":
      box_cls = "review-wrong"
      badge_cls = "badge-wrong"
      badge_txt = "WRONG"
    else:
      box_cls = "review-skip"
      badge_cls = "badge-skip"
      badge_txt = "SKIPPED"

    opts_html = "".join([
        f"<div style='font-size:13px; color:#cbd5e1; margin:2px 0;'>{html.escape(str(o))}</div>"
        for o in d.get("options", [])
    ])

    exp_html = (
        f"<div style='margin-top:8px; padding:8px 12px; background:rgba(15,23,42,0.55); border-radius:8px; font-size:13px; color:#e2e8f0;'><b>Solution / Explanation:</b> {html.escape(exp_raw)}</div>"
        if exp_raw
        else ""
    )

    st.markdown(
        f"""
        <div class="{box_cls}">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                <span class="{badge_cls}">{badge_txt}</span>
                <span style="font-size:13px; color:#e2e8f0;">Time Spent: <b>{q_time_str}</b></span>
            </div>
            <div style="font-size:16px; font-weight:600; margin-bottom:8px;">Q{idx+1}. {safe_q}</div>
            {opts_html}
            <div style="margin-top:10px; font-size:14px;">
                Your Answer: <b>{safe_u}</b> &nbsp;|&nbsp; Answer Key: <b>{safe_c} ({safe_ans_opt})</b>
            </div>
            {exp_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if status in ("Wrong", "Skipped"):
      render_doubt_box(f"{scope_prefix}_{safe_ts}_{idx}", idx + 1, d)


def submit_test(test):
  record_current_q_time()
  total_elapsed = get_active_elapsed()
  st.session_state.test_active = False
  st.session_state.test_paused = False
  st.session_state.paused_at = None
  st.session_state.total_paused_sec = 0.0

  score = 0
  detailed = []
  questions = test["questions"]

  for i, q in enumerate(questions):
    u_ans = st.session_state.user_answers.get(i)
    correct_ans = str(q.get("answer", "A")).strip().upper()
    q_sec = st.session_state.q_times.get(i, 0.0)

    if not u_ans:
      status = "Skipped"
      u_display = "Not Answered"
    elif u_ans.upper() == correct_ans:
      status = "Correct"
      u_display = u_ans.upper()
      score += 1
    else:
      status = "Wrong"
      u_display = u_ans.upper()

    detailed.append({
        "question": q["question"],
        "options": q.get("options", []),
        "correct": correct_ans,
        "user": u_display,
        "status": status,
        "time_sec": round(q_sec, 1),
        "explanation": str(q.get("explanation", "") or "").strip(),
    })

  pct = round((score / len(questions)) * 100, 2) if len(questions) > 0 else 0.0
  res_entry = {
      "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
      "username": st.session_state.username,
      "test_name": test["test_name"],
      "score": f"{score}/{len(questions)}",
      "percentage": pct,
      "total_time_sec": total_elapsed,
      "details": detailed,
  }
  add_result_to_sheet(spreadsheet, res_entry)
  st.session_state.latest_result = res_entry
  st.rerun()


# ================= LOGIN / SIGNUP SCREEN =================
def auth_screen():
  st.markdown(
      """
      <div class="hero-card" style="text-align:center; max-width:680px; margin: 24px auto;">
          <h2 style="margin:0; color:#38bdf8;">Practice Test & Analysis Portal</h2>
          <p style="color:#94a3b8; margin-top:6px;">Google Sheets connected: permanent tests, progress tracking aur doubt help</p>
      </div>
      """,
      unsafe_allow_html=True,
  )
  _, col2, _ = st.columns([1, 2, 1])

  with col2:
    tab1, tab2 = st.tabs(["Login", "Sign Up (New User)"])

    with tab1:
      l_user = st.text_input("Username", key="l_user").strip()
      l_pass = st.text_input("Password", type="password", key="l_pass").strip()
      if st.button("Login", use_container_width=True):
        users = load_users_from_sheet(spreadsheet)
        if l_user in users and users[l_user]["password"] == l_pass:
          sid = uuid.uuid4().hex[:16]
          save_session_to_sheet(spreadsheet, sid, l_user)
          st.query_params["sid"] = sid
          st.session_state.session_token = sid
          st.session_state.logged_in = True
          st.session_state.username = l_user
          st.session_state.role = users[l_user]["role"]
          st.session_state.latest_result = None
          st.rerun()
        else:
          st.error("Galat Username ya Password!")

    with tab2:
      s_user = st.text_input("Choose Username", key="s_user").strip()
      s_pass = st.text_input("Choose Password", type="password", key="s_pass").strip()
      if st.button("Register Account", use_container_width=True):
        users = load_users_from_sheet(spreadsheet)
        if s_user in users:
          st.warning("Ye username pehle se hai!")
        elif s_user and s_pass:
          add_user_to_sheet(spreadsheet, s_user, s_pass, role="student")
          st.success("Account Google Sheet me save ho gaya! Ab Login karein.")
        else:
          st.error("Username aur Password dono bharein.")


# ================= MAIN APP =================
if not st.session_state.logged_in:
  auth_screen()
else:
  is_admin = st.session_state.role == "admin"

  st.sidebar.markdown(
      f"""
      <div class="metric-card" style="border-left-color:#22c55e;">
          <div class="metric-label">LOGGED IN AS</div>
          <div style="font-size:18px; font-weight:700;">{html.escape(st.session_state.username)}</div>
          <div style="font-size:12px; color:#38bdf8; margin-top:2px;">ROLE: {html.escape(st.session_state.role.upper())}</div>
      </div>
      """,
      unsafe_allow_html=True,
  )

  st.sidebar.text_input(
      "Gemini API Key (Doubts)",
      type="password",
      key="gemini_doubt_key",
      placeholder="Optional - Ask Gemini ke liye",
  )

  menu = [
      "Take Test & Analysis",
      "Progress & Past Tests",
  ]
  if is_admin:
    menu.append("Upload Questions (File / Text)")
    menu.append("Admin Dashboard (All Users)")

  choice = st.sidebar.radio("Navigation", menu)

  if st.sidebar.button("Logout", use_container_width=True):
    sid = st.session_state.get("session_token") or st.query_params.get("sid")
    delete_session_from_sheet(spreadsheet, sid)
    st.query_params.clear()
    st.session_state.session_token = ""
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""
    st.session_state.test_active = False
    st.session_state.test_paused = False
    st.session_state.latest_result = None
    st.rerun()

  saved_tests = load_tests_from_sheet(spreadsheet)
  saved_results = load_results_from_sheet(spreadsheet)

  # ---------------- 1. TAKE TEST & INSTANT ANALYSIS ----------------
  if choice == "Take Test & Analysis":
    if (
        st.session_state.latest_result is not None
        and not st.session_state.test_active
    ):
      render_test_analysis(st.session_state.latest_result, scope_prefix="latest")
      if st.button("Back to Available Tests"):
        st.session_state.latest_result = None
        st.rerun()

    elif not st.session_state.test_active:
      st.markdown(
          """
          <div class="hero-card">
              <h2 style="margin:0; color:#38bdf8;">Available Practice Tests</h2>
              <p style="color:#94a3b8; margin:4px 0 0 0;">Sabhi tests Google Sheet me permanently saved hain. Timer set karein aur start karein.</p>
          </div>
          """,
          unsafe_allow_html=True,
      )

      if not saved_tests:
        st.info(
            "Abhi koi test available nahi hai. Admin login se 'Upload Questions"
            " (File / Text)' me test add karein."
        )
      else:
        for idx, t in enumerate(saved_tests):
          st.markdown(
              f"""
              <div class="q-card">
                  <div style="font-size:18px; font-weight:700; color:#f8fafc;">Test #{idx+1}: {html.escape(str(t['test_name']))}</div>
                  <div style="font-size:13px; color:#94a3b8; margin-top:4px;">
                      ID: <b>{html.escape(str(t.get('test_id', '')))}</b> | Created By: <b>{html.escape(str(t['creator']))}</b> | Questions: <b>{len(t['questions'])}</b> | Saved: <b>{html.escape(str(t.get('created_at', '')))}</b>
                  </div>
              </div>
              """,
              unsafe_allow_html=True,
          )
          col_t, col_b = st.columns([1, 2])
          with col_t:
            t_mins = st.number_input(
                "Timer (Minutes)",
                min_value=1,
                value=max(5, len(t["questions"])),
                key=f"time_{idx}",
            )
          with col_b:
            st.write("")
            st.write("")
            if st.button(f"Start Test #{idx+1}", key=f"start_{idx}"):
              now = time.time()
              st.session_state.current_test = t
              st.session_state.test_active = True
              st.session_state.test_paused = False
              st.session_state.paused_at = None
              st.session_state.total_paused_sec = 0.0
              st.session_state.test_duration = t_mins * 60
              st.session_state.start_time = now
              st.session_state.q_last_tick = now
              st.session_state.q_index = 0
              st.session_state.q_times = {}
              st.session_state.user_answers = {}
              st.session_state.latest_result = None
              st.rerun()

          if is_admin:
            with st.expander(f"Admin: Rename / Delete '{t['test_name']}'"):
              new_t_name = st.text_input(
                  "New Test Name",
                  value=t["test_name"],
                  key=f"rename_inp_{idx}",
              )
              adm_c1, adm_c2 = st.columns(2)
              with adm_c1:
                if st.button(
                    "Save Name", key=f"rename_btn_{idx}", use_container_width=True
                ):
                  if new_t_name.strip():
                    if rename_test_in_sheet(spreadsheet, t, new_t_name):
                      st.success("Test ka naam update ho gaya!")
                      st.rerun()
                    else:
                      st.error("Sheet me test row nahi mili.")
                  else:
                    st.warning("Khali naam save nahi ho sakta.")
              with adm_c2:
                if st.button(
                    "Delete Test",
                    key=f"del_test_btn_{idx}",
                    use_container_width=True,
                ):
                  if delete_test_from_sheet(spreadsheet, t):
                    st.success("Test delete ho gaya!")
                    st.rerun()
                  else:
                    st.error("Test delete nahi ho saka.")

          st.divider()

    else:
      test = st.session_state.current_test
      questions = test["questions"]
      total_q = len(questions)

      elapsed = get_active_elapsed()
      remaining = int(st.session_state.test_duration - elapsed)

      if remaining <= 0 and not st.session_state.test_paused:
        submit_test(test)
      else:
        m, s = divmod(max(0, remaining), 60)
        top_l, top_m, top_r = st.columns([2.5, 1, 1.2])
        with top_l:
          st.markdown(f"### {test['test_name']}")
          st.progress((st.session_state.q_index + 1) / total_q)
        with top_m:
          st.write("")
          if st.session_state.test_paused:
            if st.button("Resume Test", use_container_width=True):
              resume_test_timer()
              st.rerun()
          else:
            if st.button("Pause Test", use_container_width=True):
              pause_test_timer()
              st.rerun()
        with top_r:
          if st.session_state.test_paused:
            st.markdown(
                f'<div class="paused-pill">PAUSED ({m:02d}:{s:02d})</div>',
                unsafe_allow_html=True,
            )
          else:
            st.markdown(
                f'<div class="timer-pill">Time Left: {m:02d}:{s:02d}</div>',
                unsafe_allow_html=True,
            )

        if st.session_state.test_paused:
          st.info(
              "Test abhi **PAUSED** hai — timer ruka hua hai. Aage badhne ke"
              " liye **Resume Test** dabayein."
          )
        else:
          st.caption("Question Palette:")
          pal_cols = st.columns(min(10, total_q))
          for p_i in range(total_q):
            with pal_cols[p_i % len(pal_cols)]:
              mark = "*" if p_i in st.session_state.user_answers else ""
              if st.button(f"{p_i+1}{mark}", key=f"pal_{p_i}"):
                record_current_q_time()
                st.session_state.q_index = p_i
                st.rerun()

          cur_i = st.session_state.q_index
          q = questions[cur_i]
          cur_spent = st.session_state.q_times.get(cur_i, 0.0) + max(
              0.0, time.time() - st.session_state.q_last_tick
          )

          saved_letter = st.session_state.user_answers.get(cur_i)
          letters = ["A", "B", "C", "D"]
          default_idx = (
              letters.index(saved_letter) if saved_letter in letters else None
          )

          st.markdown(
              f"""
              <div class="q-card">
                  <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                      <span style="color:#38bdf8; font-weight:700;">Question {cur_i+1} of {total_q}</span>
                      <span style="color:#94a3b8; font-size:13px;">This Question Time: <b>{format_duration(cur_spent)}</b></span>
                  </div>
                  <div style="font-size:18px; font-weight:600; line-height:1.5;">{html.escape(str(q['question']))}</div>
              </div>
              """,
              unsafe_allow_html=True,
          )

          choice_opt = st.radio(
              "Apna option chunein:",
              q["options"],
              key=f"radio_q_{cur_i}",
              index=default_idx,
          )
          if choice_opt is not None:
            opt_idx = q["options"].index(choice_opt)
            if opt_idx < len(letters):
              st.session_state.user_answers[cur_i] = letters[opt_idx]

          nav1, nav2, nav3, nav4 = st.columns(4)
          with nav1:
            if st.button(
                "Previous", disabled=(cur_i == 0), use_container_width=True
            ):
              record_current_q_time()
              st.session_state.q_index = max(0, cur_i - 1)
              st.rerun()
          with nav2:
            if st.button("Clear Selection", use_container_width=True):
              st.session_state.user_answers.pop(cur_i, None)
              st.rerun()
          with nav3:
            if st.button(
                "Next Question",
                disabled=(cur_i >= total_q - 1),
                use_container_width=True,
            ):
              record_current_q_time()
              st.session_state.q_index = min(total_q - 1, cur_i + 1)
              st.rerun()
          with nav4:
            if st.button(
                "Submit Test", type="primary", use_container_width=True
            ):
              submit_test(test)

  # ---------------- 2. PROGRESS & PAST TESTS ----------------
  elif choice == "Progress & Past Tests":
    st.markdown(
        """
        <div class="hero-card">
            <h2 style="margin:0; color:#38bdf8;">My Progress & Past Test History</h2>
            <p style="color:#94a3b8; margin:4px 0 0 0;">Har attempt ka score, accuracy, time aur complete answer key yahan saved hai.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    my_results = [
        r for r in saved_results if r["username"] == st.session_state.username
    ]

    if not my_results:
      st.info("Aapne abhi tak koi test submit nahi kiya hai.")
    else:
      render_progress_summary(my_results)

      st.markdown("#### Past Attempts Summary")
      hist_df = pd.DataFrame([
          {
              "Attempt": i + 1,
              "Date & Time": r["timestamp"],
              "Test Name": r["test_name"],
              "Score": r["score"],
              "Accuracy (%)": r["percentage"],
              "Time Taken": format_duration(r.get("total_time_sec", 0)),
          }
          for i, r in enumerate(my_results)
      ])
      st.dataframe(hist_df, use_container_width=True, hide_index=True)

      st.markdown("#### Inspect Any Past Attempt (Answer Key & Solutions)")
      labels = [
          f"#{i+1} | {r['test_name']} | {r['score']} ({r['percentage']}%) | {r['timestamp']}"
          for i, r in enumerate(my_results)
      ]
      sel_idx = st.selectbox(
          "Attempt chunein:",
          range(len(labels)),
          format_func=lambda i: labels[i],
      )
      render_test_analysis(my_results[sel_idx], scope_prefix=f"hist_{sel_idx}")

  # ---------------- 3. UPLOAD QUESTIONS (ADMIN ONLY) ----------------
  elif choice == "Upload Questions (File / Text)":
    if not is_admin:
      st.error("Access Denied: Sirf Admin questions upload kar sakta hai.")
      st.stop()

    st.markdown(
        """
        <div class="hero-card">
            <h2 style="margin:0; color:#38bdf8;">Upload Practice Test Questions</h2>
            <p style="color:#94a3b8; margin:4px 0 0 0;">Excel / CSV / JSON file upload karein ya plain text paste karke test publish karein.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    test_title = st.text_input(
        "Test Name / Title", placeholder="e.g. Station Master Latest 2D Set 1"
    ).strip()

    up_tab1, up_tab2 = st.tabs(
        ["Excel / CSV / JSON File Upload", "Paste Questions Text"]
    )

    with up_tab1:
      st.caption(
          "Columns: Question, OptionA, OptionB, OptionC, OptionD, Answer"
          " (Optional: Explanation)"
      )
      uploaded_file = st.file_uploader(
          "File chunein (.xlsx, .xls, .csv, .json)",
          type=["xlsx", "xls", "csv", "json"],
      )
      if uploaded_file is not None:
        try:
          if uploaded_file.name.lower().endswith(".csv"):
            df_q = pd.read_csv(uploaded_file)
            parsed_q = normalize_questions_df(df_q)
          elif uploaded_file.name.lower().endswith((".xlsx", ".xls")):
            df_q = pd.read_excel(uploaded_file)
            parsed_q = normalize_questions_df(df_q)
          else:
            raw_json = json.load(uploaded_file)
            parsed_q = raw_json if isinstance(raw_json, list) else []

          st.success(f"{len(parsed_q)} valid questions mile.")
          if st.button("Publish File Test to Google Sheet", type="primary"):
            final_name = (
                test_title
                or uploaded_file.name.rsplit(".", 1)[0]
                or "Uploaded Test"
            )
            if not parsed_q:
              st.error("File me valid questions nahi mile.")
            else:
              add_test_to_sheet(
                  spreadsheet, final_name, st.session_state.username, parsed_q
              )
              st.success(
                  f"Test '{final_name}' ({len(parsed_q)} questions) publish ho"
                  " gaya!"
              )
              st.rerun()
        except Exception as e:
          st.error(f"File read error: {e}")

    with up_tab2:
      sample_txt = (
          "Q1. भारत की राजधानी क्या है?\n"
          "A) मुंबई\n"
          "B) नई दिल्ली\n"
          "C) कोलकाता\n"
          "D) चेन्नई\n"
          "Answer: B\n"
          "Explanation: नई दिल्ली भारत की राजधानी है।\n\n"
          "Q2. 15 * 6 का मान क्या है?\n"
          "A) 75\n"
          "B) 80\n"
          "C) 90\n"
          "D) 95\n"
          "Answer: C\n"
          "Explanation: 15 × 6 = 90।"
      )
      raw_text = st.text_area(
          "Questions paste karein:", value=sample_txt, height=240
      )
      if st.button("Parse & Publish Text Test", type="primary"):
        qs = parse_plain_questions(raw_text)
        if not test_title:
          st.warning("Kripya Test Name likhein.")
        elif not qs:
          st.error(
              "Format check karein: har question ke baad 4 options aur Answer:"
              " A/B/C/D hona chahiye."
          )
        else:
          add_test_to_sheet(
              spreadsheet, test_title, st.session_state.username, qs
          )
          st.success(
              f"Test '{test_title}' ({len(qs)} questions) Google Sheet me save"
              " ho gaya!"
          )
          st.rerun()

  # ---------------- 4. ADMIN DASHBOARD (ADMIN ONLY) ----------------
  elif choice == "Admin Dashboard (All Users)":
    if not is_admin:
      st.error("Access Denied: Sirf Admin is page ko dekh sakta hai.")
      st.stop()

    st.markdown(
        """
        <div class="hero-card">
            <h2 style="margin:0; color:#38bdf8;">Admin Overview — All Users & Attempts</h2>
            <p style="color:#94a3b8; margin:4px 0 0 0;">Google Sheet me saved sabhi tests, users aur test attempts ka record.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    users_map = load_users_from_sheet(spreadsheet)
    a1, a2, a3 = st.columns(3)
    a1.metric("Total Users", len(users_map))
    a2.metric("Total Published Tests", len(saved_tests))
    a3.metric("Total Attempts", len(saved_results))

    st.markdown("#### Published Tests Management")
    if saved_tests:
      t_df = pd.DataFrame([
          {
              "Test ID": t.get("test_id", ""),
              "Test Name": t["test_name"],
              "Questions": len(t["questions"]),
              "Created By": t["creator"],
              "Created At": t.get("created_at", ""),
          }
          for t in saved_tests
      ])
      st.dataframe(t_df, use_container_width=True, hide_index=True)

    if not saved_results:
      st.info("Abhi tak kisi user ne test submit nahi kiya hai.")
    else:
      all_df = pd.DataFrame([
          {
              "Date & Time": r["timestamp"],
              "Username": r["username"],
              "Test Name": r["test_name"],
              "Score": r["score"],
              "Accuracy (%)": r["percentage"],
              "Time Taken": format_duration(r.get("total_time_sec", 0)),
          }
          for r in saved_results
      ])
      st.dataframe(all_df, use_container_width=True, hide_index=True)
