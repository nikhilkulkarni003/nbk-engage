"""
Admin console: manage the question bank, build question sets,
import questions from Excel, and browse/download past sessions.
"""

from __future__ import annotations

import streamlit as st

from components import session_report as session_report_component
from services import analytics, database as db
from utils import auth
from utils.excel_export import build_session_results_workbook
from utils.excel_import import ExcelImportError, generate_template_bytes, parse_and_validate
from utils.validation import ALLOWED_DIFFICULTIES, ALLOWED_TYPES, validate_question_dict

SUGGESTED_CATEGORIES = [
    "Accounting", "Finance", "FinTech", "BFSI", "Taxation",
    "Financial Markets", "Leadership", "Communication", "General",
]


def render(on_switch_role) -> None:
    if not auth.render_login_gate("Enter the trainer password to manage the question bank."):
        return

    ok, msg = db.check_connection()
    if not ok:
        st.error(f"⚠️ Can't reach the database right now.\n\n({msg})")
        return

    top_l, top_r1, top_r2 = st.columns([4, 1, 1])
    with top_l:
        st.markdown("## 📚 Admin Console")
    with top_r1:
        if st.button("🎤 Host", use_container_width=True):
            on_switch_role("host")
    with top_r2:
        if st.button("🚪 Log Out", use_container_width=True):
            auth.log_out()
            on_switch_role("participant")

    tab_bank, tab_sets, tab_import, tab_sessions = st.tabs(
        ["📖 Question Bank", "🗂️ Question Sets", "📤 Excel Import", "📊 Sessions & Results"]
    )
    with tab_bank:
        _render_question_bank_tab()
    with tab_sets:
        _render_question_sets_tab()
    with tab_import:
        _render_import_tab()
    with tab_sessions:
        _render_sessions_tab()


# ---------------------------------------------------------------
# Question bank
# ---------------------------------------------------------------
def _render_question_bank_tab() -> None:
    with st.expander("➕ Add New Question", expanded=False):
        _render_add_question_form()

    st.markdown("#### Search & Filter")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        search = st.text_input("Search", placeholder="Search question text...")
    with c2:
        categories = ["All"] + sorted(set(SUGGESTED_CATEGORIES) | set(db.list_categories()))
        category = st.selectbox("Category", categories)
    with c3:
        difficulty = st.selectbox("Difficulty", ["All"] + ALLOWED_DIFFICULTIES)
    with c4:
        q_type = st.selectbox("Type", ["All"] + ALLOWED_TYPES)

    questions = db.list_questions(search=search, category=category, difficulty=difficulty, q_type=q_type)
    st.caption(f"{len(questions)} question(s)")

    for q in questions:
        title = f"[{q['type']}] {q['question'][:70]}"
        with st.expander(title):
            _render_question_editor(q)


def _render_add_question_form() -> None:
    q_type = st.selectbox("Question Type", ALLOWED_TYPES, key="admin_new_q_type")

    with st.form("add_question_form", clear_on_submit=True):
        question_text = st.text_area("Question")
        cat_col, diff_col = st.columns(2)
        with cat_col:
            category = st.text_input("Category", value="General",
                                      help=f"Suggestions: {', '.join(SUGGESTED_CATEGORIES)}")
        with diff_col:
            difficulty = st.selectbox("Difficulty", ALLOWED_DIFFICULTIES, index=1)

        option_a = option_b = option_c = option_d = ""
        correct_answer = ""
        explanation = ""
        points = 0
        timer_seconds = 30
        min_label = max_label = ""
        min_response_length = 2
        extra_options_raw = ""

        if q_type in ("MCQ", "POLL"):
            oc1, oc2 = st.columns(2)
            with oc1:
                option_a = st.text_input("Option A")
                option_c = st.text_input("Option C (optional)")
            with oc2:
                option_b = st.text_input("Option B")
                option_d = st.text_input("Option D (optional)")
            if q_type == "POLL":
                extra_options_raw = st.text_area(
                    "Additional options (optional, one per line, for a poll with more than 4 choices)"
                )

        if q_type == "MCQ":
            correct_answer = st.selectbox("Correct Answer", ["A", "B", "C", "D"])
            explanation = st.text_area("Explanation (shown after reveal)")
            points = st.number_input("Points for a correct answer", min_value=0, value=1, step=1)

        if q_type in ("MCQ", "POLL", "WORDCLOUD", "RATING", "OPEN_ENDED"):
            timer_seconds = st.number_input("Timer (seconds, 0 = no limit)", min_value=0, value=30, step=5)

        if q_type == "RATING":
            rc1, rc2 = st.columns(2)
            with rc1:
                min_label = st.text_input("Label for 1 (optional)", placeholder="Poor")
            with rc2:
                max_label = st.text_input("Label for 5 (optional)", placeholder="Excellent")

        if q_type == "WORDCLOUD":
            min_response_length = st.number_input("Minimum word length to include", min_value=1,
                                                    value=2, step=1)

        image_url = st.text_input("Image URL (optional)")

        submitted = st.form_submit_button("➕ Add Question", use_container_width=True)

    if not submitted:
        return

    row = {
        "question": question_text, "type": q_type,
        "option_a": option_a, "option_b": option_b, "option_c": option_c, "option_d": option_d,
        "correct_answer": correct_answer, "explanation": explanation,
        "points": points, "timer_seconds": timer_seconds,
        "category": category, "difficulty": difficulty,
    }
    errors = validate_question_dict(row)
    if errors:
        for e in errors:
            st.error(e)
        return

    config = {}
    if q_type == "RATING":
        config = {"min": 1, "max": 5, "min_label": min_label, "max_label": max_label}
    elif q_type == "WORDCLOUD":
        config = {"min_response_length": int(min_response_length)}
    elif q_type == "POLL" and extra_options_raw.strip():
        config = {"extra_options": [l.strip() for l in extra_options_raw.splitlines() if l.strip()][:4]}

    db.create_question(
        question=question_text.strip(), type=q_type,
        option_a=option_a or None, option_b=option_b or None,
        option_c=option_c or None, option_d=option_d or None,
        correct_answer=(correct_answer or None) if q_type == "MCQ" else None,
        explanation=explanation or None,
        points=int(points), timer_seconds=int(timer_seconds),
        category=category.strip() or "General", difficulty=difficulty,
        image_url=image_url or None, config=config,
    )
    st.success("Question added.")
    st.rerun()


def _render_question_editor(q: dict) -> None:
    with st.form(f"edit_q_{q['id']}"):
        question_text = st.text_area("Question", value=q["question"])
        cat_col, diff_col = st.columns(2)
        with cat_col:
            category = st.text_input("Category", value=q["category"])
        with diff_col:
            difficulty = st.selectbox(
                "Difficulty", ALLOWED_DIFFICULTIES,
                index=ALLOWED_DIFFICULTIES.index(q["difficulty"]) if q["difficulty"] in ALLOWED_DIFFICULTIES else 1,
            )

        option_a = option_b = option_c = option_d = None
        correct_answer = q.get("correct_answer")
        explanation = q.get("explanation") or ""
        points = q.get("points", 1)
        timer_seconds = q.get("timer_seconds", 30)

        if q["type"] in ("MCQ", "POLL"):
            oc1, oc2 = st.columns(2)
            with oc1:
                option_a = st.text_input("Option A", value=q.get("option_a") or "")
                option_c = st.text_input("Option C", value=q.get("option_c") or "")
            with oc2:
                option_b = st.text_input("Option B", value=q.get("option_b") or "")
                option_d = st.text_input("Option D", value=q.get("option_d") or "")

        if q["type"] == "MCQ":
            letters = ["A", "B", "C", "D"]
            correct_answer = st.selectbox("Correct Answer", letters,
                                           index=letters.index(correct_answer) if correct_answer in letters else 0)
            explanation = st.text_area("Explanation", value=explanation)
            points = st.number_input("Points for a correct answer", min_value=0, value=int(points), step=1)

        if q["type"] in ("MCQ", "POLL", "WORDCLOUD", "RATING", "OPEN_ENDED"):
            timer_seconds = st.number_input("Timer (seconds, 0 = no limit)", min_value=0,
                                             value=int(timer_seconds), step=5)

        image_url = st.text_input("Image URL (optional)", value=q.get("image_url") or "")

        b1, b2, b3 = st.columns(3)
        save = b1.form_submit_button("💾 Save Changes", use_container_width=True)
        duplicate = b2.form_submit_button("📄 Duplicate", use_container_width=True)
        delete = b3.form_submit_button("🗑️ Delete", use_container_width=True)

    if save:
        row = {
            "question": question_text, "type": q["type"],
            "option_a": option_a, "option_b": option_b, "option_c": option_c, "option_d": option_d,
            "correct_answer": correct_answer, "explanation": explanation,
            "points": points, "timer_seconds": timer_seconds,
            "category": category, "difficulty": difficulty,
        }
        errors = validate_question_dict(row)
        if errors:
            for e in errors:
                st.error(e)
            return
        db.update_question(
            q["id"], question=question_text.strip(),
            option_a=option_a or None, option_b=option_b or None,
            option_c=option_c or None, option_d=option_d or None,
            correct_answer=(correct_answer or None) if q["type"] == "MCQ" else None,
            explanation=explanation or None, points=int(points), timer_seconds=int(timer_seconds),
            category=category.strip() or "General", difficulty=difficulty, image_url=image_url or None,
        )
        st.success("Saved.")
        st.rerun()
    elif duplicate:
        db.duplicate_question(q["id"])
        st.success("Duplicated.")
        st.rerun()
    elif delete:
        db.delete_question(q["id"])
        st.success("Deleted.")
        st.rerun()


# ---------------------------------------------------------------
# Question sets
# ---------------------------------------------------------------
def _render_question_sets_tab() -> None:
    st.markdown("#### Create a Question Set")
    all_questions = db.list_questions()
    if not all_questions:
        st.info("Add some questions to the bank first.")
    else:
        options = {f"[{q['type']}] {q['question'][:60]}": q["id"] for q in all_questions}
        with st.form("create_set_form"):
            title = st.text_input("Set Title", placeholder="e.g. Session 1 - Financial Statements Basics")
            description = st.text_input("Description (optional)")
            category = st.text_input("Category", value="General")
            chosen = st.multiselect("Questions (in order)", options=list(options.keys()))
            submitted = st.form_submit_button("Create Set", use_container_width=True)
        if submitted:
            if not title.strip():
                st.error("Please enter a title.")
            elif not chosen:
                st.error("Please select at least one question.")
            else:
                qs = db.create_question_set(title.strip(), description, category.strip() or "General")
                db.set_question_set_items(qs["id"], [options[c] for c in chosen])
                st.success(f"Created question set '{title}' with {len(chosen)} question(s).")
                st.rerun()

    st.divider()
    st.markdown("#### Existing Question Sets")
    all_questions = db.list_questions()
    options = {f"[{q['type']}] {q['question'][:60]}": q["id"] for q in all_questions}
    for qs in db.list_question_sets():
        with st.expander(f"{qs['title']} ({qs['question_count']} questions)"):
            items = db.get_question_set_items(qs["id"])
            for it in items:
                st.write(f"- [{it['type']}] {it['question']}")
            current_ids = {it["id"] for it in items}
            current_labels = [label for label, qid in options.items() if qid in current_ids]
            new_selection = st.multiselect(
                "Edit questions in this set", options=list(options.keys()),
                default=current_labels, key=f"edit_set_{qs['id']}",
            )
            e1, e2 = st.columns(2)
            with e1:
                if st.button("💾 Save Changes", key=f"save_set_{qs['id']}", use_container_width=True):
                    db.set_question_set_items(qs["id"], [options[c] for c in new_selection])
                    st.success("Updated.")
                    st.rerun()
            with e2:
                if st.button("🗑️ Delete Set", key=f"del_set_{qs['id']}", use_container_width=True):
                    db.delete_question_set(qs["id"])
                    st.success("Deleted.")
                    st.rerun()


# ---------------------------------------------------------------
# Excel import
# ---------------------------------------------------------------
def _render_import_tab() -> None:
    st.markdown("#### Bulk Import Questions from Excel")
    st.download_button(
        "⬇️ Download Excel Template",
        data=generate_template_bytes(),
        file_name="nbk_engage_question_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    uploaded = st.file_uploader("Upload .xlsx file", type=["xlsx"])
    if not uploaded:
        return

    try:
        valid_rows, errors = parse_and_validate(uploaded.getvalue())
    except ExcelImportError as exc:
        st.error(str(exc))
        return

    if errors:
        st.error(f"Found {len(errors)} issue(s). Fix these in the Excel file and re-upload:")
        for e in errors:
            st.write(f"- {e}")

    if valid_rows:
        st.success(f"{len(valid_rows)} row(s) passed validation and are ready to import.")
        st.dataframe(
            [{"Question": r["question"][:60], "Type": r["type"], "Category": r["category"]} for r in valid_rows],
            hide_index=True, use_container_width=True,
        )
        if st.button(f"📥 Import {len(valid_rows)} Question(s)", type="primary", use_container_width=True):
            count = db.bulk_insert_questions(valid_rows)
            st.success(f"Imported {count} question(s) into the bank.")
            st.rerun()
    elif not errors:
        st.warning("No valid rows found in the file.")


# ---------------------------------------------------------------
# Sessions & results
# ---------------------------------------------------------------
def _render_sessions_tab() -> None:
    sessions = db.list_sessions(limit=100)
    if not sessions:
        st.info("No sessions have been created yet.")
        return

    for s in sessions:
        with st.expander(f"{s['title']} · {s['session_code']} · {s['status']} · {s['participant_count']} joined"):
            st.write(f"Created: {s['created_at']}")
            st.write(f"Started: {s.get('started_at') or '—'}")
            st.write(f"Ended: {s.get('ended_at') or '—'}")

            if s["participant_count"] > 0:
                session_report_component.render_session_report(s["id"])
                st.divider()

            summary = analytics.get_session_summary(s["id"])
            workbook_bytes = build_session_results_workbook(summary)
            st.download_button(
                "⬇️ Download Results (Excel)",
                data=workbook_bytes,
                file_name=f"nbk_engage_results_{s['session_code']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dl_{s['id']}",
                use_container_width=True,
            )
