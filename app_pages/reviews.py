from datetime import date

import streamlit as st

from app_pages.common import employee_picker, get, request_key, run, show_write_result
from hr_analytics.models import Review, ValidationError

st.title("Submit a performance review")
st.caption("Writes to hr_oltp.reviews, then loads the review into hr_dw.fact_performance_reviews against the "
           "employee version that was current on the review date.")

emp = employee_picker(key="rev")
if not emp:
    st.stop()

with st.form("review"):
    a, b = st.columns(2)
    review_date = a.date_input("Review date", value=date.today(), max_value=date.today())
    score = b.slider("Performance score", 1.0, 5.0, 3.5, 0.05)
    goals = st.slider("Goals met (%)", 0, 100, 75)
    reviewer = st.number_input("Reviewer employee id (optional, 0 = none)", min_value=0, value=0, step=1)
    comments = st.text_area("Comments", max_chars=255)
    ok = st.form_submit_button("Submit review", type="primary")

if ok:
    try:
        review = Review(employee_id=int(emp["employee_id"]), review_date=review_date, performance_score=score,
                        goals_met_pct=goals, comments=comments, reviewer_id=int(reviewer) or None)
    except ValidationError as exc:
        st.warning(str(exc))
    else:
        key = request_key("submit_review", review.to_record())
        show_write_result(run(lambda: get("review").submit(review, request_key=key)))

st.subheader("Review history")
st.dataframe(run(lambda: get("review").for_employee(int(emp["employee_id"]))), hide_index=True,
             use_container_width=True)
