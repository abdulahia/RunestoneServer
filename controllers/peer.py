# *******************************
# |docname| - route to a textbook
# *******************************
# This controller provides routes to admin functions
#
# Imports
# =======
# These are listed in the order prescribed by `PEP 8
# <http://www.python.org/dev/peps/pep-0008/#imports>`_.
#
# Standard library
# ----------------
import json
import logging
import os

# Third Party
# -----------
import altair as alt
import pandas as pd
import redis


logger = logging.getLogger(settings.logger)
logger.setLevel(settings.log_level)


@auth.requires(
    lambda: verifyInstructorStatus(auth.user.course_id, auth.user),
    requires_login=True,
)
def instructor():
    assignments = db(db.assignments.is_peer == True).select(
        orderby=~db.assignments.duedate
    )

    return dict(
        course_id=auth.user.course_name,
        course=get_course_row(db.courses.ALL),
        assignments=assignments,
    )


@auth.requires(
    lambda: verifyInstructorStatus(auth.user.course_id, auth.user),
    requires_login=True,
)
def dashboard():

    assignment_id = request.vars.assignment_id
    if request.vars.next == "Next":
        next = True
    else:
        next = False
    current_question = _get_current_question(assignment_id, next)

    return dict(
        course_id=auth.user.course_name,
        course=get_course_row(db.courses.ALL),
        current_question=current_question,
        assignment_id=assignment_id,
    )


def _get_current_question(assignment_id, get_next):

    assignment = db(db.assignments.id == assignment_id).select().first()
    idx = 0
    if get_next:
        idx = assignment.current_index + 1
    a_qs = db(db.assignment_questions.assignment_id == assignment_id).select(
        orderby=db.assignment_questions.sorting_priority
    )
    logger.debug(f"{idx=} {len(a_qs)=}")
    if idx > len(a_qs) - 1:
        idx = len(a_qs) - 1
    current_question_id = a_qs[idx].question_id
    current_question = db(db.questions.id == current_question_id).select().first()

    return current_question


def _get_n_answers(num_answer, div_id, course_name):
    dburl = settings.database_uri.replace("postgres://", "postgresql://")

    df = pd.read_sql_query(
        f"""
    WITH first_answer AS (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY sid
                ORDER BY
                    id
            ) AS rn
        FROM
            mchoice_answers
        WHERE
            div_id = '{div_id}'
            AND course_name = '{course_name}'
    )
    SELECT
        *
    FROM
        first_answer
    WHERE
        rn <= {num_answer}
    ORDER BY
        sid
    limit 4000    
    """,
        dburl,
    )
    df = df.dropna(subset=["answer"])
    logger.debug(df.head())
    df["answer"] = df.answer.astype("int64")

    return df


@auth.requires(
    lambda: verifyInstructorStatus(auth.user.course_id, auth.user),
    requires_login=True,
)
def chartdata():
    response.headers["content-type"] = "application/json"
    div_id = request.vars.div_id
    course_name = auth.user.course_name
    logger.debug(f"divid = {div_id}")
    df = _get_n_answers(2, div_id, course_name)
    df["letter"] = df.answer.map(lambda x: chr(65 + x))
    c = alt.Chart(df[df.rn == 1]).mark_bar().encode(x="letter", y="count()")
    d = alt.Chart(df[df.rn == 2]).mark_bar().encode(x="letter", y="count()")

    return alt.vconcat(c, d).to_json()


#
# Student Facing pages
#
@auth.requires_login()
def student():
    assignments = db(db.assignments.is_peer == True).select(
        orderby=~db.assignments.duedate
    )

    return dict(
        course_id=auth.user.course_name,
        course=get_course_row(db.courses.ALL),
        assignments=assignments,
    )


@auth.requires_login()
def peer_question():
    assignment_id = request.vars.assignment_id

    current_question = _get_current_question(assignment_id, False)

    return dict(
        course_id=auth.user.course_name,
        course=get_course_row(db.courses.ALL),
        current_question=current_question,
        assignment_id=assignment_id,
    )


@auth.requires(
    lambda: verifyInstructorStatus(auth.user.course_id, auth.user),
    requires_login=True,
)
def make_pairs():
    response.headers["content-type"] = "application/json"
    div_id = request.vars.div_id
    df = _get_n_answers(1, div_id, auth.user.course_name)
    answers = list(df.answer.unique())
    correct = df[df.correct == "T"][["sid", "answer"]]
    answers.remove(correct.iloc[0].answer)
    correct_list = correct.sid.to_list()
    incorrect = df[df.correct == "F"][["sid", "answer"]]
    incorrect_list = incorrect.sid.to_list()
    logger.debug(f"{correct_list=}")
    logger.debug(f"{incorrect_list=}")
    r = redis.from_url(os.environ.get("REDIS_URI", "redis://redis:6379/0"))
    for i in range(min(len(correct_list), len(incorrect_list))):
        p1 = incorrect_list.pop()
        p2 = correct_list.pop()
        r.hset("partnerdb", p1, p2)
        r.hset("partnerdb", p2, p1)

    remaining = correct_list or incorrect_list
    if remaining:
        done = False
        while not done:
            try:
                p1 = remaining.pop()
                p2 = remaining.pop()
                r.hset("partnerdb", p1, p2)
                r.hset("partnerdb", p2, p1)
            except IndexError():
                done = True

    return json.dumps("success")


def clear_pairs():
    response.headers["content-type"] = "application/json"
    r = redis.from_url(os.environ.get("REDIS_URI", "redis://redis:6379/0"))
    r.delete("partnerdb")
    return json.dumps("success")
