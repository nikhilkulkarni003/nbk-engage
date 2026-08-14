"""
Admin console: build/manage question sets (adding, editing and
importing questions all happen nested inside a set -- there is
deliberately no separate standalone "question bank" screen, see
services/database.py::import_questions_into_set), and browse/download
past sessions.
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
    if not auth.render_login_gate("Enter the trainer password to manage question sets."):
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

    tab_sets, tab_import, tab_sessions = st.tabs(
        ["🗂️ Question Sets", "📤 Excel Import", "📊 Sessions & Results"]
    )
    with tab_sets:
        _render_question_sets_tab()
    with tab_import:
        _render_import_tab()
    with tab_sessions:
        _render_sessions_tab()


# ---------------------------------------------------------------
# Question sets -- the one place questions get created, edited,
# imported into, or removed. No separate question-bank screen.
# ---------------------------------------------------------------
def _render_question_sets_tab() -> None:
    st.markdown("#### Create a Question Set")
    with st.form("create_set_form"):
        title = st.text_input("Set Title", placeholder="e.g. Session 1 - Financial Statements Basics")
        description = st.text_input("Description (optional)")
        category = st.text_input("Category", value="General")
        submitted = st.form_submit_button("➕ Create Empty Set", use_container_width=True)
    if submitted:
        if not title.strip():
            st.error("Please enter a title.")
        else:
            db.create_question_set(title.strip(), description, category.strip() or "General")
            st.success(f"Created '{title}'. Add questions to it below.")
            st.rerun()

    st.divider()
    st.markdown("#### Your Question Sets")
    sets = db.list_question_sets()
    if not sets:
        st.info("No question sets yet. Create one above.")
        return

    all_questions = db.list_questions()

    for qs in sets:
        with st.expander(f"{qs['title']} ({qs['question_count']} questions)"):
            items = db.get_question_set_items(qs["id"])

            if items:
                st.markdown("**Questions in this set** (in order)")
                for it in items:
                    with st.expander(f"[{it['type']}] {it['question'][:70]}", expanded=False):
                        _render_question_editor(it, qs["id"], items)
            else:
                st.caption("No questions in this set yet -- add one below.")

            st.markdown("**➕ Add a new question to this set**")
            _render_add_question_form(qs["id"])

            st.markdown("**Add an existing question from another set**")
            item_ids = {it["id"] for it in items}
            other_questions = [q for q in all_questions if q["id"] not in item_ids]
            if other_questions:
                search = st.text_input(
                    "Search", key=f"search_existing_{qs['id']}",
                    placeholder="Filter by question text...", label_visibility="collapsed",
                )
                if search.strip():
                    other_questions = [
                        q for q in other_questions if search.strip().lower() in q["question"].lower()
                    ]
                other_options = {f"[{q['type']}] {q['question'][:60]}": q["id"] for q in other_questions}
                chosen = st.multiselect(
                    "Pick existing question(s) to add", options=list(other_options.keys()),
                    key=f"add_existing_{qs['id']}", label_visibility="collapsed",
                )
                if chosen and st.button("Add Selected", key=f"add_existing_btn_{qs['id']}"):
                    combined = [it["id"] for it in items] + [other_options[c] for c in chosen]
                    db.set_question_set_items(qs["id"], combined)
                    st.success(f"Added {len(chosen)} question(s).")
                    st.rerun()
            else:
                st.caption("No other existing questions to add.")

            st.divider()
            dc1, dc2 = st.columns(2)
            with dc1:
                if st.button("🗑️ Delete Set Only", key=f"del_set_{qs['id']}", use_container_width=True,
                              help="Removes this set. Its questions stay in your question bank, "
                                   "available to add to another set."):
                    db.delete_question_set(qs["id"])
                    st.success("Set deleted. Its questions are still in your question bank.")
                    st.rerun()
            with dc2:
                if st.button("🗑️ Delete Set + Its Questions", key=f"del_set_full_{qs['id']}",
                              use_container_width=True,
                              help="Deletes the set AND every question in it (unless a question was "
                                   "used in a past session, which keeps it in the bank for that "
                                   "session's historical record)."):
                    result = db.delete_question_set_and_questions(qs["id"])
                    msg = f"Set deleted along with {result['deleted_questions']} question(s)."
                    if result["kept_questions"]:
                        msg += (
                            f" {result['kept_questions']} question(s) were used in a past session "
                            f"and kept in your question bank instead of being deleted."
                        )
                    st.success(msg)
                    st.rerun()


def _render_add_question_form(target_set_id: str) -> None:
    q_type = st.selectbox("Question Type", ALLOWED_TYPES, key=f"new_q_type_{target_set_id}")

    with st.form(f"add_question_form_{target_set_id}", clear_on_submit=True):
        question_text = st.text_area("Question", key=f"new_q_text_{target_set_id}")
        cat_col, diff_col = st.columns(2)
        with cat_col:
            category = st.text_input("Category", value="General",
                                      help=f"Suggestions: {', '.join(SUGGESTED_CATEGORIES)}",
                                      key=f"new_q_cat_{target_set_id}")
        with diff_col:
            difficulty = st.selectbox("Difficulty", ALLOWED_DIFFICULTIES, index=1,
                                       key=f"new_q_diff_{target_set_id}")

        option_a = option_b = option_c = option_d = ""
        correct_answer = ""
        explanation = ""
        points = 1
        timer_seconds = 30
        min_label = max_label = ""
        min_response_length = 2
        extra_options_raw = ""

        if q_type in ("MCQ", "POLL"):
            oc1, oc2 = st.columns(2)
            with oc1:
                option_a = st.text_input("Option A", key=f"new_q_a_{target_set_id}")
                option_c = st.text_input("Option C (optional)", key=f"new_q_c_{target_set_id}")
            with oc2:
                option_b = st.text_input("Option B", key=f"new_q_b_{target_set_id}")
                option_d = st.text_input("Option D (optional)", key=f"new_q_d_{target_set_id}")
            if q_type == "POLL":
                extra_options_raw = st.text_area(
                    "Additional options (optional, one per line, for a poll with more than 4 choices)",
                    key=f"new_q_extra_{target_set_id}",
                )

        if q_type == "MCQ":
            correct_answer = st.selectbox("Correct Answer", ["A", "B", "C", "D"],
                                           key=f"new_q_correct_{target_set_id}")
            explanation = st.text_area("Explanation (shown after reveal)",
                                        key=f"new_q_expl_{target_set_id}")
            points = st.number_input("Points for a correct answer", min_value=0, value=1, step=1,
                                      key=f"new_q_points_{target_set_id}")

        if q_type in ("MCQ", "POLL", "WORDCLOUD", "RATING", "OPEN_ENDED"):
            timer_seconds = st.number_input(
                "Timer (seconds, 0 = no limit) -- only used if you enable the optional "
                "time-bonus scoring for this question", min_value=0, value=30, step=5,
                key=f"new_q_timer_{target_set_id}",
            )

        if q_type == "RATING":
            rc1, rc2 = st.columns(2)
            with rc1:
                min_label = st.text_input("Label for 1 (optional)", placeholder="Poor",
                                           key=f"new_q_minlabel_{target_set_id}")
            with rc2:
                max_label = st.text_input("Label for 5 (optional)", placeholder="Excellent",
                                           key=f"new_q_maxlabel_{target_set_id}")

        if q_type == "WORDCLOUD":
            min_response_length = st.number_input("Minimum word length to include", min_value=1,
                                                    value=2, step=1, key=f"new_q_minlen_{target_set_id}")

        image_url = st.text_input("Image URL (optional)", key=f"new_q_img_{target_set_id}")

        submitted = st.form_submit_button("➕ Add to This Set", use_container_width=True)

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

    created = db.create_question(
        question=question_text.strip(), type=q_type,
        option_a=option_a or None, option_b=option_b or None,
        option_c=option_c or None, option_d=option_d or None,
        correct_answer=(correct_answer or None) if q_type == "MCQ" else None,
        explanation=explanation or None,
        points=int(points), timer_seconds=int(timer_seconds),
        category=category.strip() or "General", difficulty=difficulty,
        image_url=image_url or None, config=config,
    )
    current_ids = [it["id"] for it in db.get_question_set_items(target_set_id)]
    db.set_question_set_items(target_set_id, current_ids + [created["id"]])
    st.success("Question added to this set.")
    st.rerun()


def _render_question_editor(q: dict, set_id: str, set_items: list[dict]) -> None:
    with st.form(f"edit_q_{set_id}_{q['id']}"):
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
            timer_seconds = st.number_input(
                "Timer (seconds, 0 = no limit) -- only used if you enable the optional "
                "time-bonus scoring for this question", min_value=0,
                value=int(timer_seconds), step=5,
            )

        image_url = st.text_input("Image URL (optional)", value=q.get("image_url") or "")

        b1, b2, b3 = st.columns(3)
        save = b1.form_submit_button("💾 Save Changes", use_container_width=True)
        duplicate = b2.form_submit_button("📄 Duplicate", use_container_width=True)
        delete = b3.form_submit_button("🗑️ Delete Everywhere", use_container_width=True)

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
        st.success("Duplicated -- use 'Add an existing question' below to add the copy to a set.")
        st.rerun()
    elif delete:
        # Deletes the question everywhere (cascades out of every set
        # it's in, not just this one) -- distinct from "remove from
        # this set only" below. A question already used in a past
        # session can't be deleted (its historical results/responses
        # depend on it) -- delete_question_safe reports that instead
        # of raising and crashing the page.
        if db.delete_question_safe(q["id"]):
            st.success("Deleted.")
            st.rerun()
        else:
            st.error(
                "Can't delete this question -- it was used in a past session, and deleting it "
                "would break that session's historical results. Use 'Remove from this set only' "
                "below instead if you just want it out of this set."
            )

    if st.button("➖ Remove from this set only (keeps the question)",
                  key=f"rm_{set_id}_{q['id']}", use_container_width=True):
        remaining = [it["id"] for it in set_items if it["id"] != q["id"]]
        db.set_question_set_items(set_id, remaining)
        st.success("Removed from this set.")
        st.rerun()


# ---------------------------------------------------------------
# Excel import -- imports straight into a chosen (or new) question
# set, no separate question-bank step. Duplicate questions (same text
# + type, case-insensitive) are flagged and reused instead of
# re-inserted. Every imported question is worth 1 point -- not an
# importable/editable column.
# ---------------------------------------------------------------
def _render_import_tab() -> None:
    st.markdown("#### Bulk Import Questions from Excel")
    st.caption("Every imported question is worth 1 point by default (not editable via import).")
    st.download_button(
        "⬇️ Download Excel Template",
        data=generate_template_bytes(),
        file_name="nbk_engage_question_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.markdown("#### Import Into")
    sets = db.list_question_sets()
    set_options = {qs["title"]: qs["id"] for qs in sets}
    target_choice = st.radio(
        "Target", options=["Add to an existing set", "Create a new set"],
        horizontal=True, label_visibility="collapsed",
    )
    target_set_id = None
    new_set_title = ""
    if target_choice == "Add to an existing set":
        if not set_options:
            st.info("No question sets yet -- choose 'Create a new set' instead.")
        else:
            chosen_label = st.selectbox("Question Set", options=list(set_options.keys()))
            target_set_id = set_options[chosen_label]
    else:
        new_set_title = st.text_input("New Set Title", placeholder="e.g. Session 2 - Working Capital")

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

    if not valid_rows:
        if not errors:
            st.warning("No valid rows found in the file.")
        return

    existing_keys = {(q["question"].strip().lower(), q["type"]) for q in db.list_questions()}
    seen_in_file: set[tuple[str, str]] = set()
    preview = []
    duplicate_preview_count = 0
    for r in valid_rows:
        key = (r["question"].strip().lower(), r["type"])
        is_dup = key in existing_keys or key in seen_in_file
        seen_in_file.add(key)
        if is_dup:
            duplicate_preview_count += 1
        preview.append({
            "Question": r["question"][:60], "Type": r["type"], "Category": r["category"],
            "Status": "🔁 Duplicate (will reuse existing)" if is_dup else "🆕 New",
        })

    st.success(f"{len(valid_rows)} row(s) passed validation and are ready to import.")
    if duplicate_preview_count:
        st.warning(
            f"{duplicate_preview_count} row(s) match a question that already exists (by text + type) -- "
            f"these will be flagged and linked into the set instead of creating duplicate questions."
        )
    st.dataframe(preview, hide_index=True, use_container_width=True)

    ready = bool(target_set_id) or (target_choice == "Create a new set" and new_set_title.strip())
    if st.button(f"📥 Import {len(valid_rows)} Question(s)", type="primary",
                 use_container_width=True, disabled=not ready):
        if target_choice == "Create a new set":
            qs = db.create_question_set(new_set_title.strip(), "", "General")
            target_set_id = qs["id"]
        result = db.import_questions_into_set(valid_rows, target_set_id)
        msg = f"Imported {result['new_count']} new question(s) into the set."
        if result["duplicate_count"]:
            msg += (
                f" {result['duplicate_count']} row(s) already existed and were flagged as "
                f"duplicates -- the existing question was reused instead of re-added."
            )
        st.success(msg)
        st.rerun()


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
