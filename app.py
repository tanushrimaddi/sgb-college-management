import os
import json
import csv
import io

from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from functools import wraps

from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    url_for,
    session,
    flash,
    Response,
    send_file
)

from flask_sqlalchemy import SQLAlchemy

from werkzeug.security import (
    check_password_hash,
    generate_password_hash
)


# ============================================================
# APP CONFIG
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "CHANGE-THIS-SGB-SECRET-KEY"
)

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(
        BASE_DIR,
        "college.db"
    )
)

if DATABASE_URL.startswith("postgres://"):

    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ============================================================
# INDIA TIMEZONE
# ============================================================

IST = ZoneInfo("Asia/Kolkata")


def now_ist():

    return datetime.now(IST)


def today_ist():

    return now_ist().date()


def now_ist_naive():

    return now_ist().replace(
        tzinfo=None
    )


# ============================================================
# ADMIN DEFAULT
# ============================================================

ADMIN_USERNAME = os.environ.get(
    "ADMIN_USERNAME",
    "admin"
)

ADMIN_PASSWORD = os.environ.get(
    "ADMIN_PASSWORD",
    "admin123"
)


# ============================================================
# DAYS
# ============================================================

DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday"
]


# ============================================================
# TIMETABLE FILE
# ============================================================

TIMETABLE_FILE = os.path.join(
    BASE_DIR,
    "timetable.json"
)


# ============================================================
# COLLEGE LOGO
# ============================================================

COLLEGE_LOGO_FILE = os.path.join(
    BASE_DIR,
    "college_logo.png"
)


def load_timetable():

    if not os.path.exists(TIMETABLE_FILE):

        return {}

    try:

        with open(
            TIMETABLE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception as e:

        print(
            "Timetable error:",
            e
        )

        return {}


timetable = load_timetable()


# ============================================================
# DATABASE MODELS
# ============================================================

class User(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(200),
        nullable=False
    )

    username = db.Column(
        db.String(100),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(300),
        nullable=False
    )

    attendance_access = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=now_ist_naive
    )


class Attendance(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    record_date = db.Column(
        db.Date,
        nullable=False,
        index=True
    )

    faculty = db.Column(
        db.String(200),
        nullable=False,
        index=True
    )

    year = db.Column(
        db.String(100),
        nullable=False,
        index=True
    )

    day = db.Column(
        db.String(30),
        nullable=False
    )

    slot = db.Column(
        db.String(100),
        nullable=False
    )

    subject = db.Column(
        db.String(300),
        nullable=False,
        index=True
    )

    status = db.Column(
        db.String(30),
        nullable=False
    )

    marked_by = db.Column(
        db.String(200),
        nullable=True
    )

    marked_at = db.Column(
        db.DateTime,
        default=now_ist_naive
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

with app.app_context():

    db.create_all()

    admin_user = User.query.filter_by(
        username=ADMIN_USERNAME
    ).first()

    if not admin_user:

        admin_user = User(
            name="Administrator",
            username=ADMIN_USERNAME,
            password_hash=generate_password_hash(
                ADMIN_PASSWORD
            ),
            attendance_access=True
        )

        db.session.add(
            admin_user
        )

        db.session.commit()


# ============================================================
# AUTH HELPERS
# ============================================================

def current_user():

    user_id = session.get(
        "user_id"
    )

    if not user_id:

        return None

    return User.query.get(
        user_id
    )


def login_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not session.get(
            "user_id"
        ):

            return redirect(
                url_for(
                    "login",
                    next=request.path
                )
            )

        return function(
            *args,
            **kwargs
        )

    return wrapper


def admin_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        user = current_user()

        if not user:

            return redirect(
                url_for(
                    "login",
                    next=request.path
                )
            )

        if user.username != ADMIN_USERNAME:

            flash(
                "Admin access required."
            )

            return redirect(
                url_for("home")
            )

        return function(
            *args,
            **kwargs
        )

    return wrapper


def attendance_access_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        user = current_user()

        if not user:

            return redirect(
                url_for(
                    "login",
                    next=request.path
                )
            )

        if not user.attendance_access:

            flash(
                "You do not have attendance access."
            )

            return redirect(
                url_for("home")
            )

        return function(
            *args,
            **kwargs
        )

    return wrapper


# ============================================================
# COLLEGE LOGO ROUTE
# ============================================================

@app.route("/college-logo.png")
def college_logo():

    if not os.path.exists(
        COLLEGE_LOGO_FILE
    ):

        return (
            "college_logo.png not found",
            404
        )

    return send_file(
        COLLEGE_LOGO_FILE,
        mimetype="image/png"
    )


# ============================================================
# DATA HELPERS
# ============================================================

def get_faculties():

    return list(
        timetable.keys()
    )


def get_years(faculty):

    return list(
        timetable
        .get(
            faculty,
            {}
        )
        .keys()
    )


def get_day_data(
    faculty,
    year,
    day
):

    return (
        timetable
        .get(
            faculty,
            {}
        )
        .get(
            year,
            {}
        )
        .get(
            day,
            {}
        )
    )


# ============================================================
# LECTURE HELPERS
# ============================================================

def lecture_text(value):

    if isinstance(
        value,
        str
    ):

        return value

    if isinstance(
        value,
        dict
    ):

        for key in [
            "class",
            "subject",
            "lecture",
            "name"
        ]:

            if key in value:

                return str(
                    value[key]
                )

    return str(value)


def get_lecture_list(value):

    if isinstance(
        value,
        list
    ):

        result = []

        for item in value:

            text = lecture_text(
                item
            ).strip()

            if text:

                result.append(
                    text
                )

        return result


    if isinstance(
        value,
        tuple
    ):

        result = []

        for item in value:

            text = lecture_text(
                item
            ).strip()

            if text:

                result.append(
                    text
                )

        return result


    if isinstance(
        value,
        dict
    ):

        for key in [
            "lectures",
            "subjects",
            "classes"
        ]:

            if key in value:

                items = value[key]

                if isinstance(
                    items,
                    list
                ):

                    result = []

                    for item in items:

                        text = lecture_text(
                            item
                        ).strip()

                        if text:

                            result.append(
                                text
                            )

                    return result


    text = lecture_text(
        value
    ).strip()

    if text:

        return [text]

    return []


# ============================================================
# TIME HELPERS
# ============================================================

def parse_time(value):

    try:

        value = value.strip()

        hour, minute = map(
            int,
            value.split(":")[:2]
        )

        return (
            hour * 60
            + minute
        )

    except Exception:

        return None


def parse_slot(slot):

    try:

        start, end = slot.split(
            "-",
            1
        )

        return (
            parse_time(start),
            parse_time(end)
        )

    except Exception:

        return None, None


def current_minutes():

    now = now_ist()

    return (
        now.hour * 60
        + now.minute
    )


def is_current_slot(
    slot,
    day
):

    today = now_ist().strftime(
        "%A"
    )

    if day != today:

        return False

    start, end = parse_slot(
        slot
    )

    if start is None or end is None:

        return False

    now = current_minutes()

    return (
        start <= now < end
    )


# ============================================================
# CURRENT LECTURES
# ============================================================

def get_current_lectures(
    faculty,
    year
):

    today = now_ist().strftime(
        "%A"
    )

    data = get_day_data(
        faculty,
        year,
        today
    )

    now = current_minutes()

    result = []

    for slot, value in data.items():

        start, end = parse_slot(
            slot
        )

        if start is None or end is None:

            continue

        if start <= now < end:

            lectures = get_lecture_list(
                value
            )

            for subject in lectures:

                result.append(
                    (
                        slot,
                        subject
                    )
                )

    return result


# ============================================================
# NEXT LECTURES
# ============================================================

def get_next_lectures(
    faculty,
    year
):

    today = now_ist().strftime(
        "%A"
    )

    data = get_day_data(
        faculty,
        year,
        today
    )

    now = current_minutes()

    upcoming = []

    for slot, value in data.items():

        start, end = parse_slot(
            slot
        )

        if start is None:

            continue

        if start > now:

            lectures = get_lecture_list(
                value
            )

            for subject in lectures:

                upcoming.append(
                    (
                        start,
                        slot,
                        subject
                    )
                )

    upcoming.sort(
        key=lambda x: x[0]
    )

    if not upcoming:

        return []

    first = upcoming[0][0]

    return [
        (
            slot,
            subject
        )
        for start, slot, subject
        in upcoming
        if start == first
    ]


# ============================================================
# ATTENDANCE STATUS
# ============================================================

def get_status(
    record_date,
    faculty,
    year,
    day,
    slot,
    subject
):

    record = Attendance.query.filter_by(
        record_date=record_date,
        faculty=faculty,
        year=year,
        day=day,
        slot=slot,
        subject=subject
    ).first()

    if record:

        return record.status

    return None


# ============================================================
# REPORT HELPERS
# ============================================================

def date_range_for_period(
    period
):

    today = today_ist()

    if period == "today":

        return (
            today,
            today
        )

    if period == "week":

        start = (
            today
            - timedelta(
                days=today.weekday()
            )
        )

        return (
            start,
            start + timedelta(
                days=6
            )
        )

    if period == "month":

        start = today.replace(
            day=1
        )

        if start.month == 12:

            next_month = start.replace(
                year=start.year + 1,
                month=1,
                day=1
            )

        else:

            next_month = start.replace(
                month=start.month + 1,
                day=1
            )

        return (
            start,
            next_month - timedelta(
                days=1
            )
        )

    if period == "year":

        return (
            today.replace(
                month=1,
                day=1
            ),
            today.replace(
                month=12,
                day=31
            )
        )

    return (
        today,
        today
    )


def get_report_records(
    faculty,
    year,
    start_date,
    end_date,
    subject=None
):

    query = Attendance.query.filter(
        Attendance.record_date >= start_date,
        Attendance.record_date <= end_date
    )

    if faculty:

        query = query.filter(
            Attendance.faculty == faculty
        )

    if year:

        query = query.filter(
            Attendance.year == year
        )

    if subject:

        query = query.filter(
            Attendance.subject == subject
        )

    return query.order_by(
        Attendance.record_date.desc(),
        Attendance.slot.asc(),
        Attendance.subject.asc()
    ).all()


def calculate_stats(
    records
):

    total = len(records)

    taken = sum(
        1
        for r in records
        if r.status == "taken"
    )

    not_taken = sum(
        1
        for r in records
        if r.status == "not_taken"
    )

    cancelled = sum(
        1
        for r in records
        if r.status == "cancelled"
    )

    percentage = (
        taken / total * 100
        if total
        else 0
    )

    return (
        total,
        taken,
        not_taken,
        cancelled,
        percentage
    )


def subject_statistics(
    records
):

    result = {}

    for record in records:

        subject = record.subject

        if subject not in result:

            result[subject] = {
                "total": 0,
                "taken": 0,
                "not_taken": 0,
                "cancelled": 0
            }

        result[subject]["total"] += 1

        if record.status == "taken":

            result[subject]["taken"] += 1

        elif record.status == "not_taken":

            result[subject]["not_taken"] += 1

        elif record.status == "cancelled":

            result[subject]["cancelled"] += 1

    for subject, data in result.items():

        data["percentage"] = (
            data["taken"]
            / data["total"]
            * 100
            if data["total"]
            else 0
        )

    return result


# ============================================================
# HTML BASE
# ============================================================

BASE_HTML = """

<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
name="viewport"
content="width=device-width, initial-scale=1.0"
>

<title>SGB College Management</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: Arial, sans-serif;
    background: #f1f5f9;
    color: #172033;
}

a {
    text-decoration: none;
}

.navbar {
    background: #111827;
    color: white;
    min-height: 64px;
    padding: 10px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 15px;
    position: sticky;
    top: 0;
    z-index: 100;
}


/* ========================================================
   COLLEGE LOGO
   ======================================================== */

.college-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    color: white;
}

.college-logo {
    width: 46px;
    height: 46px;
    object-fit: contain;
    border-radius: 8px;
    background: white;
    padding: 2px;
}

.logo-text {
    color: white;
    font-size: 18px;
    font-weight: 800;
    line-height: 1.1;
}

.logo-text small {
    display: block;
    color: #9ca3af;
    font-size: 9px;
    margin-top: 3px;
    letter-spacing: .5px;
}


/* ========================================================
   NAVIGATION
   ======================================================== */

.nav-links {
    display: flex;
    gap: 5px;
    flex-wrap: wrap;
}

.nav-links a {
    color: white;
    padding: 9px 11px;
    border-radius: 7px;
    font-size: 13px;
}

.nav-links a:hover {
    background: #1f2937;
}


/* ========================================================
   MAIN
   ======================================================== */

.container {
    width: min(1150px, 94%);
    margin: auto;
    padding: 20px 0 40px;
}

.hero {
    background: linear-gradient(
        135deg,
        #2563eb,
        #7c3aed
    );
    color: white;
    padding: 27px;
    border-radius: 17px;
    margin-bottom: 18px;
}

.hero h1 {
    margin: 0 0 7px;
    font-size: 28px;
}

.hero p {
    margin: 0;
    opacity: .9;
}

.filters,
.section,
.stat {
    background: white;
    border-radius: 13px;
    box-shadow: 0 2px 8px rgba(0,0,0,.05);
}

.filters {
    padding: 16px;
    margin-bottom: 18px;
}

.filter-grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(170px, 1fr));
    gap: 11px;
}

label {
    display: block;
    font-size: 12px;
    font-weight: bold;
    color: #667085;
    margin-bottom: 5px;
}

select,
input {
    width: 100%;
    padding: 10px;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    font-size: 14px;
    background: white;
}

button,
.btn {
    border: 0;
    border-radius: 8px;
    padding: 10px 14px;
    cursor: pointer;
    font-weight: bold;
    display: inline-block;
}

.btn-blue {
    background: #2563eb;
    color: white;
}

.btn-green {
    background: #16a34a;
    color: white;
}

.btn-red {
    background: #dc2626;
    color: white;
}

.btn-orange {
    background: #ea580c;
    color: white;
}

.btn-gray {
    background: #e5e7eb;
    color: #172033;
}

.cards {
    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(160px, 1fr));
    gap: 11px;
    margin-bottom: 18px;
}

.stat {
    padding: 16px;
}

.stat-title {
    color: #667085;
    font-size: 11px;
    font-weight: bold;
}

.stat-value {
    font-size: 25px;
    font-weight: 800;
    margin-top: 7px;
}

.green {
    color: #16a34a;
}

.red {
    color: #dc2626;
}

.orange {
    color: #ea580c;
}

.blue {
    color: #2563eb;
}

.section {
    padding: 18px;
    margin-bottom: 18px;
}

.section h2 {
    margin-top: 0;
}

.lecture {
    border: 1px solid #e5e7eb;
    border-left: 5px solid #94a3b8;
    border-radius: 11px;
    padding: 13px;
    margin-bottom: 9px;
    display: flex;
    align-items: center;
    gap: 13px;
}

.lecture.live {
    background: #ecfdf3;
    border-left-color: #16a34a;
}

.lecture.next {
    background: #eff6ff;
    border-left-color: #2563eb;
}

.time {
    min-width: 125px;
    font-weight: bold;
    color: #2563eb;
}

.subject {
    flex: 1;
    font-weight: bold;
}

.badge {
    display: inline-block;
    padding: 5px 9px;
    border-radius: 20px;
    color: white;
    font-size: 10px;
    font-weight: bold;
}

.badge-taken,
.badge-live {
    background: #16a34a;
}

.badge-not {
    background: #dc2626;
}

.badge-cancel {
    background: #ea580c;
}

.badge-next {
    background: #2563eb;
}

.attendance-buttons {
    display: flex;
    gap: 5px;
    flex-wrap: wrap;
    align-items: center;
}

.attendance-form {
    display: flex;
    gap: 5px;
    flex-wrap: wrap;
}

.table-wrap {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
    min-width: 650px;
}

th,
td {
    padding: 10px;
    border-bottom: 1px solid #e5e7eb;
    text-align: left;
}

th {
    background: #f3f4f6;
    font-size: 12px;
}

.progress {
    height: 8px;
    background: #e5e7eb;
    border-radius: 8px;
    overflow: hidden;
}

.progress-bar {
    height: 100%;
    background: #16a34a;
}

.alert {
    padding: 11px 14px;
    background: #eff6ff;
    color: #1d4ed8;
    border-radius: 8px;
    margin-bottom: 14px;
}

.empty {
    text-align: center;
    padding: 40px 15px;
    color: #667085;
}

.login-box {
    max-width: 420px;
    margin: 45px auto;
    padding: 25px;
    background: white;
    border-radius: 15px;
    box-shadow: 0 3px 15px rgba(0,0,0,.08);
}

.footer {
    text-align: center;
    padding: 25px;
    color: #667085;
    font-size: 12px;
}

.access-on {
    color: #16a34a;
    font-weight: bold;
}

.access-off {
    color: #dc2626;
    font-weight: bold;
}

.current-time {
    font-size: 12px;
    color: #64748b;
    margin-top: 5px;
}


/* ========================================================
   MOBILE
   ======================================================== */

@media(max-width:700px) {

    .navbar {
        flex-direction: column;
        align-items: flex-start;
    }

    .college-brand {
        width: 100%;
    }

    .college-logo {
        width: 42px;
        height: 42px;
    }

    .logo-text {
        font-size: 17px;
    }

    .nav-links {
        width: 100%;
        overflow-x: auto;
        flex-wrap: nowrap;
    }

    .nav-links a {
        white-space: nowrap;
    }

    .container {
        width: 96%;
    }

    .hero h1 {
        font-size: 23px;
    }

    .lecture {
        flex-direction: column;
        align-items: flex-start;
    }

    .time {
        min-width: auto;
    }

    .attendance-buttons {
        width: 100%;
    }

    .attendance-form {
        width: 100%;
    }

    .attendance-form .btn {
        flex: 1;
        text-align: center;
    }

}

</style>

</head>

<body>


<!-- ========================================================
     NAVBAR
     ======================================================== -->

<nav class="navbar">


<a
href="{{ url_for('home') }}"
class="college-brand"
>

<img
src="{{ url_for('college_logo') }}"
class="college-logo"
alt="SGB College Logo"
onerror="this.style.display='none';"
>

<div class="logo-text">

SGB COLLEGE

<small>
MANAGEMENT SYSTEM
</small>

</div>

</a>


<div class="nav-links">

<a href="{{ url_for('home') }}">
🏠 Home
</a>

<a href="{{ url_for('
