import json
import re
import time
from datetime import datetime
import pandas as pd
import streamlit as st
from google import genai
import openai
import anthropic

st.set_page_config(
    page_title="AI Multi-User Test Platform", page_icon="Test", layout="wide"
)

if "logged_in" not in st.session_state:
  st.session_state.logged_in = False
if "username" not in st.session_state:
  st.session_state.username = ""
if "role" not in st.session_state:
  st.session_state.role = ""
if "current_test" not in st.session_state:
  st.session_state.current_test = None
if "test_active" not in st.session_state:
  st.session_state.test_active = False

if "mock_users" not in st.session_state:
  st.session_state.mock_users = {
      "admin": {"password": "123", "role": "admin"},
      "user1": {"password": "123", "role": "student"},
  }
if "mock_tests" not in st.session_state:
  st.session_state.mock_tests = []
if "mock_results" not in st.session_state:
  st.session_state.mock_results = []


def parse_plain_questions(text):
  blocks = re.split(r"\n\s*\n+", text.strip())
  questions = []
  for block in blocks:
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if len(lines) < 5:
      continue
    q_line = re.sub(r"^(Q\s*\d*[\.\:\)]\s*)", "", lines[0], flags=re.IGNORECASE).strip()
    opts = []
    ans = "A"
    for ln in lines[1:]:
      m_ans = re.match(r"^(?:Answer|Ans|Correct)\s*[:\-]\s*([A-Da-d])", ln, flags=re.IGNORECASE)
      if m_ans:
        ans = m_ans.group(1).upper()
        continue
      m_opt = re.match(r"^([A-Da-d])[\)\.\:\-]\s*(.+)$", ln)
      if m_opt:
        opts.append(m_opt.group(2).strip())
    if q_line and len(opts) >= 4:
      questions.append({
          "question": q_line,
          "options": opts[:4],
          "answer": ans,
      })
  return questions


def submit_test(test):
  st.session_state.test_active = False
  score = 0
  detailed = []
  questions = test["questions"]
  for i, q in enumerate(questions):
    u_ans = st.session_state.user_answers.get(i, "None")
    correct = u_ans == q["answer"]
    if correct:
      score += 1
    detailed.append({
        "question": q["question"],
        "correct": q["answer"],
        "user": u_ans,
        "is_correct": correct,
    })

  res_entry = {
      "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
      "username": st.session_state.username,
      "test_name": test["test_name"],
      "score": f"{score}/{len(questions)}",
      "percentage": round((score / len(questions)) * 100, 2) if len(questions) > 0 else 0,
      "details": detailed,
  }
  st.session_state.mock_results.append(res_entry)
  st.success(f"Test Submitted! Aapka Score: {score} / {len(questions)}")
  if st.button("Wapas Test Menu Par Jayein"):
    st.rerun()


def auth_screen():
  st.markdown(
      "<h2 style='text-align: center;'>AI Practice Test Portal - Login</h2>",
      unsafe_allow_html=True,
  )
  col1, col2, col3 = st.columns([1, 2, 1])

  with col2:
    tab1, tab2 = st.tabs(["Login", "Sign Up (New User)"])

    with tab1:
      l_user = st.text_input("Username", key="l_user")
      l_pass = st.text_input("Password", type="password", key="l_pass")
      if st.button("Login", use_container_width=True):
        if (
            l_user in st.session_state.mock_users
            and st.session_state.mock_users[l_user]["password"] == l_pass
        ):
          st.session_state.logged_in = True
          st.session_state.username = l_user
          st.session_state.role = st.session_state.mock_users[l_user]["role"]
          st.success("Login Successful!")
          st.rerun()
        else:
          st.error("Galat Username ya Password!")

    with tab2:
      s_user = st.text_input("Choose Username", key="s_user")
      s_pass = st.text_input("Choose Password", type="password", key="s_pass")
      if st.button("Register Account", use_container_width=True):
        if s_user in st.session_state.mock_users:
          st.warning("Ye username pehle se hai!")
        elif s_user:
          st.session_state.mock_users[s_user] = {
              "password": s_pass,
              "role": "student",
          }
          st.success("Account ban gaya! Ab login tab me jakar login karein.")
        else:
          st.error("Kripya details bharein.")


if not st.session_state.logged_in:
  auth_screen()
else:
  st.sidebar.title(
      f"Welcome, {st.session_state.username} ({st.session_state.role.upper()})"
  )

  menu = [
      "Take Test & Practice",
      "Upload Questions (File / Text)",
      "AI Test Generator",
  ]
  if st.session_state.role == "admin":
    menu.append("Admin Dashboard (All Users)")

  choice = st.sidebar.selectbox("Navigation", menu)

  if st.sidebar.button("Logout"):
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""
    st.session_state.test_active = False
    st.rerun()

  if choice == "Take Test & Practice":
    if not st.session_state.test_active:
      st.subheader("Available Tests")
      if not st.session_state.mock_tests:
        st.info(
            "Abhi koi test available nahi hai. 'Upload Questions' ya 'AI Test"
            " Generator' se test add karein!"
        )
      else:
        for idx, t in enumerate(st.session_state.mock_tests):
          with st.container():
            st.markdown(f"### Test #{idx+1}: {t['test_name']}")
            st.write(
                f"**Created By:** {t['creator']} | **Total Qs:** {len(t['questions'])}"
            )
            t_mins = st.number_input(
                f"Test Timer (Minutes) for Test #{idx+1}",
                min_value=1,
                value=5,
                key=f"time_{idx}",
            )
            if st.button(f"Start Test #{idx+1}", key=f"start_{idx}"):
              st.session_state.current_test = t
              st.session_state.test_active = True
              st.session_state.test_duration = t_mins * 60
              st.session_state.start_time = time.time()
              st.session_state.user_answers = {}
              st.rerun()
            st.divider()
    else:
      test = st.session_state.current_test
      st.subheader(f"Test: {test['test_name']}")

      elapsed = time.time() - st.session_state.start_time
      remaining = int(st.session_state.test_duration - elapsed)

      if remaining <= 0:
        st.warning("Time Khatam Ho Gaya!")
        submit_test(test)
      else:
        m, s = divmod(remaining, 60)
        st.markdown(f"### Time Left: {m:02d}:{s:02d}")

      questions = test["questions"]
      for i, q in enumerate(questions):
        st.write(f"**Q{i+1}: {q['question']}**")
        choice_opt = st.radio(
            f"Select option for Q{i+1}", q["options"], key=f"ans_{i}", index=None
        )
        if choice_opt:
          idx_opt = q["options"].index(choice_opt)
          st.session_state.user_answers[i] = ["A", "B", "C", "D"][idx_opt]
        st.divider()

      if st.button("Submit Test"):
        submit_test(test)

  elif choice == "Upload Questions (File / Text)":
    st.subheader("File ya Text se Questions Upload Karein")
    test_title = st.text_input(
        "Test ka Naam", "Station Master Arithmetic Set"
    )

    tab_excel, tab_text = st.tabs(["Excel / CSV Upload", "Text / TXT Paste"])

    with tab_excel:
      st.write(
          "Columns rakhein: `Question`, `OptionA`, `OptionB`, `OptionC`,"
          " `OptionD`, `Answer` (A/B/C/D)"
      )
      up_file = st.file_uploader(
          "Excel (.xlsx) ya CSV (.csv) chunein", type=["xlsx", "csv"]
      )
      if up_file is not None:
        df = (
            pd.read_csv(up_file)
            if up_file.name.endswith(".csv")
            else pd.read_excel(up_file)
        )
        st.dataframe(df.head(), use_container_width=True)

        if st.button("Excel se Test Publish Karein"):
          questions = []
          for _, row in df.iterrows():
            q_text = str(row.get("Question", "")).strip()
            if q_text and q_text.lower() != "nan":
              questions.append({
                  "question": q_text,
                  "options": [
                      str(row.get("OptionA", "")).strip(),
                      str(row.get("OptionB", "")).strip(),
                      str(row.get("OptionC", "")).strip(),
                      str(row.get("OptionD", "")).strip(),
                  ],
                  "answer": str(row.get("Answer", "A")).strip().upper(),
              })
          if questions:
            st.session_state.mock_tests.append({
                "test_name": test_title,
                "creator": st.session_state.username,
                "prompt": f"Uploaded file: {up_file.name}",
                "questions": questions,
            })
            st.success(f"{len(questions)} questions publish ho gaye!")
          else:
            st.error("Valid questions nahi mile. Column names check karein.")

    with tab_text:
      st.write(
          "Har question block ke baad ek blank line rakhein, options A)/B)/C)/D)"
          " me likhein, aur `Answer: A` likhein."
      )
      txt_upload = st.file_uploader("Ya .txt file upload karein", type=["txt"])
      default_txt = ""
      if txt_upload is not None:
        default_txt = txt_upload.read().decode("utf-8", errors="ignore")

      raw_text = st.text_area(
          "Questions + Options + Answer paste karein:",
          value=default_txt,
          height=220,
          placeholder=(
              "Q1. 25% of 200 is?\nA) 25\nB) 50\nC) 75\nD) 100\nAnswer: B\n\n"
              "Q2. 12 * 15 = ?\nA) 150\nB) 160\nC) 180\nD) 200\nAnswer: C"
          ),
      )

      if st.button("Text se Test Publish Karein"):
        parsed_qs = parse_plain_questions(raw_text)
        if parsed_qs:
          st.session_state.mock_tests.append({
              "test_name": test_title,
              "creator": st.session_state.username,
              "prompt": "Uploaded/Pasted plain text",
              "questions": parsed_qs,
          })
          st.success(f"{len(parsed_qs)} questions publish ho gaye!")
        else:
          st.error(
              "Format match nahi hua. Har sawal me 4 options (A/B/C/D) aur"
              " Answer: A/B/C/D rakhein."
          )

  elif choice == "AI Test Generator":
    st.subheader("AI se Naya Test Banayein (Multi-AI Support)")
    st.info(
        "Yahan aap kisi bhi AI (Gemini, ChatGPT, ya Claude) ka use karke naya"
        " test generate kar sakte hain jo sabhi users ko dikhega."
    )

    ai_provider = st.selectbox(
        "AI Provider Chunein",
        ["Google Gemini", "OpenAI ChatGPT", "Anthropic Claude"],
    )
    api_key = st.text_input(
        f"{ai_provider} API Key", type="password", placeholder="Enter API Key..."
    )

    test_title = st.text_input(
        "Test ka Naam (Jaise: Railway Maths Set 1)",
        "Railway Station Master Math Practice",
    )
    prompt_text = st.text_area(
        "Prompt likhein:",
        "Railway Station Master exam ke liye intermediate arithmetic ke 10"
        " questions options (A, B, C, D) ke sath do.",
    )

    if st.button("Test Generate Karke Publish Karein"):
      if not api_key:
        st.error("Kripya API Key darj karein!")
      elif not prompt_text:
        st.error("Prompt khali nahi ho sakta.")
      else:
        with st.spinner(f"{ai_provider} se questions generate ho rahe hain..."):
          try:
            questions = []
            structured_prompt = f"""{prompt_text}
You must return ONLY a valid JSON array of objects. Do not include markdown ```json. Each object must have:
"question": "The question text",
"options": ["Opt A", "Opt B", "Opt C", "Opt D"],
"answer": "A" (or B, C, D)"""

            if ai_provider == "Google Gemini":
              client = genai.Client(api_key=api_key)
              models_to_try = ["gemini-3.8-flash", "gemini-2.5-flash"]
              response = None
              last_err = None
              for m_name in models_to_try:
                for _ in range(2):
                  try:
                    response = client.models.generate_content(
                        model=m_name,
                        contents=structured_prompt,
                        config={"max_output_tokens": 8192},
                    )
                    break
                  except Exception as ex:
                    last_err = ex
                    time.sleep(2)
                if response:
                  break
              if not response:
                raise last_err
              raw = (
                  response.text.replace("```json", "")
                  .replace("```", "")
                  .strip()
              )
              questions = json.loads(raw)

            elif ai_provider == "OpenAI ChatGPT":
              client = openai.OpenAI(api_key=api_key)
              response = client.chat.completions.create(
                  model="gpt-4o-mini",
                  messages=[{"role": "user", "content": structured_prompt}],
              )
              raw = (
                  response.choices[0]
                  .message.content.replace("```json", "")
                  .replace("```", "")
                  .strip()
              )
              questions = json.loads(raw)

            elif ai_provider == "Anthropic Claude":
              client = anthropic.Anthropic(api_key=api_key)
              message = client.messages.create(
                  model="claude-3-5-sonnet-20241022",
                  max_tokens=2000,
                  messages=[{"role": "user", "content": structured_prompt}],
              )
              raw = (
                  message.content[0]
                  .text.replace("```json", "")
                  .replace("```", "")
                  .strip()
              )
              questions = json.loads(raw)

            if questions:
              new_test = {
                  "test_name": test_title,
                  "creator": st.session_state.username,
                  "prompt": prompt_text,
                  "questions": questions,
              }
              st.session_state.mock_tests.append(new_test)
              st.success(
                  "Test successfully generate hokar sabke liye publish ho gaya!"
              )
          except Exception as e:
            st.error(f"Error aayi: {e}")

  elif choice == "Admin Dashboard (All Users)" and st.session_state.role == "admin":
    st.subheader("Admin Dashboard - Sabhi Users ki Performance")

    if not st.session_state.mock_results:
      st.info("Abhi tak kisi bhi user ne test nahi diya hai.")
    else:
      df_res = pd.DataFrame([
          {
              "Time": r["timestamp"],
              "User": r["username"],
              "Test Name": r["test_name"],
              "Score": r["score"],
              "Percentage": f"{r['percentage']}%",
          }
          for r in st.session_state.mock_results
      ])
      st.dataframe(df_res, use_container_width=True)

      st.markdown("### Detailed User Answers Review")
      for idx, res in enumerate(st.session_state.mock_results):
        with st.expander(
            f"User: {res['username']} | Test: {res['test_name']} | Score:"
            f" {res['score']} ({res['timestamp']})"
        ):
          for q_i, d in enumerate(res["details"]):
            status = "Sahi" if d["is_correct"] else "Galat"
            st.write(f"**Q{q_i+1}: {d['question']}** - {status}")
            st.write(
                f"- Sahi Jawab: `{d['correct']}` | User ka Jawab: `{d['user']}`"
            )
