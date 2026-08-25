import os
import json
import csv
import io
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    url_for,
    session,
    flash,
    Response
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

        print("Timetable error:", e)

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
        default=datetime.now
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
        default=datetime.now
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

with app.app_context():

    db.create_all()

    # Create default admin if it doesn't exist
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

        db.session.add(admin_user)
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

        if not session.get("user_id"):

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
# DATA HELPERS
# ============================================================

def get_faculties():

    return list(
        timetable.keys()
    )


def get_years(faculty):

    return list(
        timetable
        .get(faculty, {})
        .keys()
    )


def get_day_data(
    faculty,
    year,
    day
):

    return (
        timetable
        .get(faculty, {})
        .get(year, {})
        .get(day, {})
    )


def lecture_text(value):

    if isinstance(value, str):

        return value

    if isinstance(value, dict):

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


def parse_time(value):

    try:

        value = value.strip()

        hour, minute = map(
            int,
            value.split(":")[:2]
        )

        return hour * 60 + minute

    except Exception:

        return None


def parse_slot(slot):

    try:

        start, end = slot.split("-")

        return (
            parse_time(start),
            parse_time(end)
        )

    except Exception:

        return None, None


def current_minutes():

    now = datetime.now()

    return (
        now.hour * 60
        + now.minute
    )


def is_current_slot(
    slot,
    day
):

    today = datetime.now().strftime(
        "%A"
    )

    if day != today:
        return False

    start, end = parse_slot(slot)

    if start is None or end is None:
        return False

    now = current_minutes()

    return start <= now < end


def get_current_lectures(
    faculty,
    year
):

    today = datetime.now().strftime(
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

        start, end = parse_slot(slot)

        if start is None or end is None:
            continue

        if start <= now < end:

            result.append(
                (
                    slot,
                    lecture_text(value)
                )
            )

    return result


def get_next_lectures(
    faculty,
    year
):

    today = datetime.now().strftime(
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

        start, end = parse_slot(slot)

        if start is None:
            continue

        if start > now:

            upcoming.append(
                (
                    start,
                    slot,
                    lecture_text(value)
                )
            )

    upcoming.sort(
        key=lambda x: x[0]
    )

    if not upcoming:
        return []

    first = upcoming[0][0]

    return [
        (slot, subject)
        for start, slot, subject
        in upcoming
        if start == first
    ]


def get_status(
    record_date,
    faculty,
    year,
    day,
    slot
):

    record = Attendance.query.filter_by(
        record_date=record_date,
        faculty=faculty,
        year=year,
        day=day,
        slot=slot
    ).first()

    if record:

        return record.status

    return None


# ============================================================
# REPORT HELPERS
# ============================================================

def date_range_for_period(period):

    today = date.today()

    if period == "today":

        return today, today

    if period == "week":

        start = today - timedelta(
            days=today.weekday()
        )

        return (
            start,
            start + timedelta(days=6)
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
            next_month - timedelta(days=1)
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

    return today, today


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
        Attendance.slot.asc()
    ).all()


def calculate_stats(records):

    total = len(records)

    taken = sum(
        1 for r in records
        if r.status == "taken"
    )

    not_taken = sum(
        1 for r in records
        if r.status == "not_taken"
    )

    cancelled = sum(
        1 for r in records
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


def subject_statistics(records):

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

.logo {
    color: white;
    font-size: 19px;
    font-weight: 800;
}

.logo small {
    display: block;
    color: #9ca3af;
    font-size: 9px;
    margin-top: 2px;
}

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

@media(max-width:700px) {

    .navbar {
        flex-direction: column;
        align-items: flex-start;
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

    .attendance-buttons .btn {
        flex: 1;
        text-align: center;
    }
}

</style>

</head>

<body>

<nav class="navbar">

<a href="{{ url_for('home') }}">

<div class="logo">
🎓 SGB COLLEGE
<small>MANAGEMENT SYSTEM</small>
</div>

</a>

<div class="nav-links">

<a href="{{ url_for('home') }}">🏠 Home</a>

<a href="{{ url_for('timetable_page') }}">
📅 Timetable
</a>

<a href="{{ url_for('reports') }}">
📊 Reports
</a>

{% if session.get("user_id") %}

<a href="{{ url_for('attendance') }}">
📝 Attendance
</a>

{% if session.get("is_admin") %}

<a href="{{ url_for('access_control') }}">
👥 Access
</a>

{% endif %}

<a href="{{ url_for('logout') }}">
Logout
</a>

{% else %}

<a href="{{ url_for('login') }}">
🔐 Login
</a>

{% endif %}

</div>

</nav>

<div class="container">

{% with messages = get_flashed_messages() %}

{% if messages %}

{% for message in messages %}

<div class="alert">
{{ message }}
</div>

{% endfor %}

{% endif %}

{% endwith %}

{{ content|safe }}

</div>

<div class="footer">

SGB College Management System

<br>

Timetable • Attendance • Reports

</div>

</body>

</html>
"""


def render_page(content, **context):

    body = render_template_string(
        content,
        **context
    )

    return render_template_string(
        BASE_HTML,
        content=body,
        **context
    )


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    faculties = get_faculties()

    faculty = request.args.get(
        "faculty",
        faculties[0] if faculties else ""
    )

    years = get_years(
        faculty
    )

    year = request.args.get(
        "year",
        years[0] if years else ""
    )

    today = datetime.now().strftime(
        "%A"
    )

    current = get_current_lectures(
        faculty,
        year
    )

    next_lectures = get_next_lectures(
        faculty,
        year
    )

    content = """

<div class="hero">

<h1>🎓 SGB College Management</h1>

<p>
Smart timetable, attendance and reports
</p>

</div>

<form class="filters">

<div class="filter-grid">

<div>

<label>Faculty</label>

<select
name="faculty"
onchange="this.form.submit()"
>

{% for f in faculties %}

<option
value="{{ f }}"
{% if f == faculty %}selected{% endif %}
>
{{ f }}
</option>

{% endfor %}

</select>

</div>

<div>

<label>Year</label>

<select
name="year"
onchange="this.form.submit()"
>

{% for y in years %}

<option
value="{{ y }}"
{% if y == year %}selected{% endif %}
>
{{ y }}
</option>

{% endfor %}

</select>

</div>

</div>

</form>

<div class="cards">

<div class="stat">

<div class="stat-title">
CURRENT LECTURE
</div>

<div class="stat-value green">

{% if current %}
LIVE
{% else %}
—
{% endif %}

</div>

</div>

<div class="stat">

<div class="stat-title">
NEXT LECTURE
</div>

<div class="stat-value blue">

{% if next_lectures %}
{{ next_lectures[0][0] }}
{% else %}
—
{% endif %}

</div>

</div>

<div class="stat">

<div class="stat-title">
TODAY
</div>

<div class="stat-value">
{{ today }}
</div>

</div>

</div>

<div class="section">

<h2>🟢 Current Lecture</h2>

{% if current %}

{% for slot, subject in current %}

<div class="lecture live">

<div class="time">
{{ slot }}
</div>

<div class="subject">
{{ subject }}
</div>

<span class="badge badge-live">
LIVE NOW
</span>

</div>

{% endfor %}

{% else %}

<div class="empty">
No lecture running right now.
</div>

{% endif %}

</div>

<div class="section">

<h2>⏭ Next Lecture</h2>

{% if next_lectures %}

{% for slot, subject in next_lectures %}

<div class="lecture next">

<div class="time">
{{ slot }}
</div>

<div class="subject">
{{ subject }}
</div>

<span class="badge badge-next">
NEXT
</span>

</div>

{% endfor %}

{% else %}

<div class="empty">
No more lectures today.
</div>

{% endif %}

</div>
"""

    return render_page(
        content,
        faculties=faculties,
        faculty=faculty,
        years=years,
        year=year,
        today=today,
        current=current,
        next_lectures=next_lectures
    )


# ============================================================
# TIMETABLE
# ============================================================

@app.route("/timetable")
def timetable_page():

    faculties = get_faculties()

    faculty = request.args.get(
        "faculty",
        faculties[0] if faculties else ""
    )

    years = get_years(
        faculty
    )

    year = request.args.get(
        "year",
        years[0] if years else ""
    )

    day = request.args.get(
        "day",
        datetime.now().strftime("%A")
    )

    if day not in DAYS:
        day = "Monday"

    data = get_day_data(
        faculty,
        year,
        day
    )

    content = """

<div class="hero">

<h1>📅 Timetable</h1>

<p>
{{ faculty }} • {{ year }} • {{ day }}
</p>

</div>

<form class="filters">

<div class="filter-grid">

<div>

<label>Faculty</label>

<select
name="faculty"
onchange="this.form.submit()"
>

{% for f in faculties %}

<option
value="{{ f }}"
{% if f == faculty %}selected{% endif %}
>
{{ f }}
</option>

{% endfor %}

</select>

</div>

<div>

<label>Year</label>

<select
name="year"
onchange="this.form.submit()"
>

{% for y in years %}

<option
value="{{ y }}"
{% if y == year %}selected{% endif %}
>
{{ y }}
</option>

{% endfor %}

</select>

</div>

<div>

<label>Day</label>

<select
name="day"
onchange="this.form.submit()"
>

{% for d in days %}

<option
value="{{ d }}"
{% if d == day %}selected{% endif %}
>
{{ d }}
</option>

{% endfor %}

</select>

</div>

</div>

</form>

<div class="section">

<h2>{{ day }} Schedule</h2>

{% if data %}

{% for slot, value in data.items() %}

{% set subject = lecture_text(value) %}

{% set status = get_status(
today_date,
faculty,
year,
day,
slot
) %}

<div class="lecture
{% if is_current_slot(slot, day) %}
live
{% endif %}
">

<div class="time">

{{ slot }}

{% if is_current_slot(slot, day) %}

<br>

<span class="badge badge-live">
LIVE
</span>

{% endif %}

</div>

<div class="subject">
{{ subject }}
</div>

<div>

{% if status == "taken" %}

<span class="badge badge-taken">
✓ TAKEN
</span>

{% elif status == "not_taken" %}

<span class="badge badge-not">
✕ NOT TAKEN
</span>

{% elif status == "cancelled" %}

<span class="badge badge-cancel">
CANCELLED
</span>

{% endif %}

</div>

</div>

{% endfor %}

{% else %}

<div class="empty">
📚
<br><br>
No timetable available.
</div>

{% endif %}

</div>
"""

    return render_page(
        content,
        faculties=faculties,
        faculty=faculty,
        years=years,
        year=year,
        day=day,
        days=DAYS,
        data=data,
        lecture_text=lecture_text,
        get_status=get_status,
        today_date=date.today(),
        is_current_slot=is_current_slot
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        user = User.query.filter_by(
            username=username
        ).first()

        if user and check_password_hash(
            user.password_hash,
            password
        ):

            session.clear()

            session["user_id"] = user.id
            session["username"] = user.username
            session["is_admin"] = (
                user.username == ADMIN_USERNAME
            )

            next_url = request.args.get(
                "next"
            )

            if next_url:
                return redirect(next_url)

            if user.attendance_access:
                return redirect(
                    url_for("attendance")
                )

            return redirect(
                url_for("home")
            )

        flash(
            "Invalid username or password."
        )

    content = """

<div class="login-box">

<h1>🔐 Login</h1>

<p>
Only authorised users can mark attendance.
</p>

<form method="post">

<label>Username</label>

<input
name="username"
required
placeholder="Username"
>

<br><br>

<label>Password</label>

<input
type="password"
name="password"
required
placeholder="Password"
>

<br><br>

<button
class="btn btn-blue"
type="submit"
>
Login
</button>

</form>

<br>

<p style="font-size:12px;color:#667085;">
Students, teachers and other visitors can view
the timetable and reports without login.
</p>

</div>
"""

    return render_page(
        content
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("home")
    )


# ============================================================
# ATTENDANCE
# ============================================================

@app.route("/attendance")
@attendance_access_required
def attendance():

    faculties = get_faculties()

    faculty = request.args.get(
        "faculty",
        faculties[0] if faculties else ""
    )

    years = get_years(
        faculty
    )

    year = request.args.get(
        "year",
        years[0] if years else ""
    )

    day = request.args.get(
        "day",
        datetime.now().strftime("%A")
    )

    if day not in DAYS:
        day = "Monday"

    data = get_day_data(
        faculty,
        year,
        day
    )

    content = """

<div class="hero">

<h1>📝 Attendance</h1>

<p>
Logged in as {{ session.get("username") }}
</p>

</div>

<form class="filters">

<div class="filter-grid">

<div>

<label>Faculty</label>

<select
name="faculty"
onchange="this.form.submit()"
>

{% for f in faculties %}

<option
value="{{ f }}"
{% if f == faculty %}selected{% endif %}
>
{{ f }}
</option>

{% endfor %}

</select>

</div>

<div>

<label>Year</label>

<select
name="year"
onchange="this.form.submit()"
>

{% for y in years %}

<option
value="{{ y }}"
{% if y == year %}selected{% endif %}
>
{{ y }}
</option>

{% endfor %}

</select>

</div>

<div>

<label>Day</label>

<select
name="day"
onchange="this.form.submit()"
>

{% for d in days %}

<option
value="{{ d }}"
{% if d == day %}selected{% endif %}
>
{{ d }}
</option>

{% endfor %}

</select>

</div>

</div>

</form>

<div class="section">

<h2>{{ day }} Attendance</h2>

{% if data %}

{% for slot, value in data.items() %}

{% set subject = lecture_text(value) %}

{% set status = get_status(
today_date,
faculty,
year,
day,
slot
) %}

<div class="lecture">

<div class="time">
{{ slot }}
</div>

<div class="subject">
{{ subject }}
</div>

<div class="attendance-buttons">

{% if status == "taken" %}

<span class="badge badge-taken">
✓ TAKEN
</span>

{% elif status == "not_taken" %}

<span class="badge badge-not">
✕ NOT TAKEN
</span>

{% elif status == "cancelled" %}

<span class="badge badge-cancel">
CANCELLED
</span>

{% endif %}

<form
method="post"
action="{{ url_for('mark_attendance') }}"
>

<input
type="hidden"
name="faculty"
value="{{ faculty }}"
>

<input
type="hidden"
name="year"
value="{{ year }}"
>

<input
type="hidden"
name="day"
value="{{ day }}"
>

<input
type="hidden"
name="slot"
value="{{ slot }}"
>

<input
type="hidden"
name="subject"
value="{{ subject }}"
>

<button
name="status"
value="taken"
class="btn btn-green"
>
✓ Taken
</button>

<button
name="status"
value="not_taken"
class="btn btn-red"
>
✕ Not Taken
</button>

<button
name="status"
value="cancelled"
class="btn btn-orange"
>
Cancel
</button>

<button
name="status"
value="clear"
class="btn btn-gray"
>
Undo
</button>

</form>

</div>

</div>

{% endfor %}

{% else %}

<div class="empty">
No classes scheduled.
</div>

{% endif %}

</div>
"""

    return render_page(
        content,
        faculties=faculties,
        faculty=faculty,
        years=years,
        year=year,
        day=day,
        days=DAYS,
        data=data,
        lecture_text=lecture_text,
        get_status=get_status,
        today_date=date.today()
    )


# ============================================================
# MARK ATTENDANCE
# ============================================================

@app.route(
    "/attendance/mark",
    methods=["POST"]
)
@attendance_access_required
def mark_attendance():

    faculty = request.form.get(
        "faculty",
        ""
    )

    year = request.form.get(
        "year",
        ""
    )

    day = request.form.get(
        "day",
        ""
    )

    slot = request.form.get(
        "slot",
        ""
    )

    subject = request.form.get(
        "subject",
        ""
    )

    status = request.form.get(
        "status",
        ""
    )

    user = current_user()

    if status == "clear":

        record = Attendance.query.filter_by(
            record_date=date.today(),
            faculty=faculty,
            year=year,
            day=day,
            slot=slot
        ).first()

        if record:

            db.session.delete(record)
            db.session.commit()

            flash(
                "Attendance record removed."
            )

    elif status in [
        "taken",
        "not_taken",
        "cancelled"
    ]:

        record = Attendance.query.filter_by(
            record_date=date.today(),
            faculty=faculty,
            year=year,
            day=day,
            slot=slot
        ).first()

        if record:

            record.subject = subject
            record.status = status
            record.marked_by = user.name
            record.marked_at = datetime.now()

        else:

            record = Attendance(
                record_date=date.today(),
                faculty=faculty,
                year=year,
                day=day,
                slot=slot,
                subject=subject,
                status=status,
                marked_by=user.name
            )

            db.session.add(record)

        db.session.commit()

        flash(
            "Class marked as "
            + status.replace("_", " ").upper()
            + "."
        )

    return redirect(
        url_for(
            "attendance",
            faculty=faculty,
            year=year,
            day=day
        )
    )


# ============================================================
# ACCESS CONTROL
# ============================================================

@app.route(
    "/access",
    methods=["GET", "POST"]
)
@admin_required
def access_control():

    if request.method == "POST":

        action = request.form.get(
            "action"
        )

        if action == "create":

            name = request.form.get(
                "name",
                ""
            ).strip()

            username = request.form.get(
                "username",
                ""
            ).strip()

            password = request.form.get(
                "password",
                ""
            )

            access = (
                request.form.get(
                    "attendance_access"
                ) == "on"
            )

            if not name or not username or not password:

                flash(
                    "Please fill all required fields."
                )

            elif User.query.filter_by(
                username=username
            ).first():

                flash(
                    "Username already exists."
                )

            else:

                user = User(
                    name=name,
                    username=username,
                    password_hash=generate_password_hash(
                        password
                    ),
                    attendance_access=access
                )

                db.session.add(user)
                db.session.commit()

                flash(
                    "New person added successfully."
                )

        elif action == "toggle":

            user_id = request.form.get(
                "user_id"
            )

            user = User.query.get(
                int(user_id)
            )

            if user and user.username != ADMIN_USERNAME:

                user.attendance_access = (
                    not user.attendance_access
                )

                db.session.commit()

                flash(
                    "Attendance access updated."
                )

        elif action == "delete":

            user_id = request.form.get(
                "user_id"
            )

            user = User.query.get(
                int(user_id)
            )

            if user and user.username != ADMIN_USERNAME:

                db.session.delete(user)
                db.session.commit()

                flash(
                    "Person deleted."
                )

    users = User.query.order_by(
        User.id.asc()
    ).all()

    content = """

<div class="hero">

<h1>👥 Access Control</h1>

<p>
Admin can decide who can mark attendance.
</p>

</div>

<div class="section">

<h2>➕ Add Person</h2>

<form method="post">

<input
type="hidden"
name="action"
value="create"
>

<div class="filter-grid">

<div>

<label>Person Name</label>

<input
name="name"
required
placeholder="Teacher / Staff Name"
>

</div>

<div>

<label>Username</label>

<input
name="username"
required
placeholder="Username"
>

</div>

<div>

<label>Password</label>

<input
type="password"
name="password"
required
placeholder="Password"
>

</div>

<div>

<label>
☑ Attendance Access
</label>

<input
type="checkbox"
name="attendance_access"
style="width:auto;"
checked
>

<span style="font-size:12px;">
Allow this person to mark attendance
</span>

</div>

</div>

<br>

<button
class="btn btn-blue"
type="submit"
>
➕ Add Person
</button>

</form>

</div>


<div class="section">

<h2>👤 People & Access</h2>

<div class="table-wrap">

<table>

<thead>

<tr>

<th>Name</th>
<th>Username</th>
<th>Attendance Access</th>
<th>Action</th>

</tr>

</thead>

<tbody>

{% for u in users %}

<tr>

<td>
<strong>{{ u.name }}</strong>
</td>

<td>
{{ u.username }}
</td>

<td>

{% if u.attendance_access %}

<span class="access-on">
☑ ALLOWED
</span>

{% else %}

<span class="access-off">
☐ NOT ALLOWED
</span>

{% endif %}

</td>

<td>

{% if u.username == admin_username %}

<span class="badge badge-taken">
ADMIN
</span>

{% else %}

<form
method="post"
style="display:inline;"
>

<input
type="hidden"
name="action"
value="toggle"
>

<input
type="hidden"
name="user_id"
value="{{ u.id }}"
>

<button
class="btn btn-blue"
type="submit"
>
☑ Toggle Access
</button>

</form>

<form
method="post"
style="display:inline;"
onsubmit="return confirm('Delete this person?')"
>

<input
type="hidden"
name="action"
value="delete"
>

<input
type="hidden"
name="user_id"
value="{{ u.id }}"
>

<button
class="btn btn-red"
type="submit"
>
Delete
</button>

</form>

{% endif %}

</td>

</tr>

{% endfor %}

</tbody>

</table>

</div>

</div>
"""

    return render_page(
        content,
        users=users,
        admin_username=ADMIN_USERNAME
    )


# ============================================================
# REPORTS
# ============================================================

@app.route("/reports")
def reports():

    faculties = get_faculties()

    faculty = request.args.get(
        "faculty",
        faculties[0] if faculties else ""
    )

    years = get_years(
        faculty
    )

    year = request.args.get(
        "year",
        years[0] if years else ""
    )

    period = request.args.get(
        "period",
        "month"
    )

    subject = request.args.get(
        "subject",
        ""
    )

    if period == "custom":

        try:

            start_date = datetime.strptime(
                request.args.get(
                    "start_date"
                ),
                "%Y-%m-%d"
            ).date()

            end_date = datetime.strptime(
                request.args.get(
                    "end_date"
                ),
                "%Y-%m-%d"
            ).date()

        except Exception:

            start_date, end_date = (
                date_range_for_period(
                    "month"
                )
            )

    else:

        start_date, end_date = (
            date_range_for_period(
                period
            )
        )

    records = get_report_records(
        faculty,
        year,
        start_date,
        end_date,
        subject if subject else None
    )

    (
        total,
        taken,
        not_taken,
        cancelled,
        percentage
    ) = calculate_stats(
        records
    )

    subjects = sorted({
        r.subject
        for r in Attendance.query.filter_by(
            faculty=faculty,
            year=year
        ).all()
    })

    subject_stats = subject_statistics(
        records
    )

    content = """

<div class="hero">

<h1>📊 Attendance Reports</h1>

<p>
Daily • Weekly • Monthly • Yearly • Subject-wise
</p>

</div>

<form class="filters" method="get">

<div class="filter-grid">

<div>

<label>Faculty</label>

<select name="faculty">

{% for f in faculties %}

<option
value="{{ f }}"
{% if f == faculty %}selected{% endif %}
>
{{ f }}
</option>

{% endfor %}

</select>

</div>

<div>

<label>Year</label>

<select name="year">

{% for y in years %}

<option
value="{{ y }}"
{% if y == year %}selected{% endif %}
>
{{ y }}
</option>

{% endfor %}

</select>

</div>

<div>

<label>Period</label>

<select name="period">

<option value="today"
{% if period == "today" %}selected{% endif %}
>
Today
</option>

<option value="week"
{% if period == "week" %}selected{% endif %}
>
This Week
</option>

<option value="month"
{% if period == "month" %}selected{% endif %}
>
This Month
</option>

<option value="year"
{% if period == "year" %}selected{% endif %}
>
This Year
</option>

<option value="custom"
{% if period == "custom" %}selected{% endif %}
>
Custom
</option>

</select>

</div>

<div>

<label>Subject</label>

<select name="subject">

<option value="">
All Subjects
</option>

{% for s in subjects %}

<option
value="{{ s }}"
{% if s == subject %}selected{% endif %}
>
{{ s }}
</option>

{% endfor %}

</select>

</div>

<div>

<label>Start Date</label>

<input
type="date"
name="start_date"
value="{{ start_date }}"
>

</div>

<div>

<label>End Date</label>

<input
type="date"
name="end_date"
value="{{ end_date }}"
>

</div>

<div>

<label>&nbsp;</label>

<button
class="btn btn-blue"
type="submit"
>
Generate Report
</button>

</div>

<div>

<label>&nbsp;</label>

<a
class="btn btn-green"
href="{{ url_for(
'export_csv',
faculty=faculty,
year=year,
period=period,
subject=subject,
start_date=start_date,
end_date=end_date
) }}"
>
⬇ CSV
</a>

</div>

</div>

</form>

<div class="cards">

<div class="stat">

<div class="stat-title">
RECORDED
</div>

<div class="stat-value blue">
{{ total }}
</div>

</div>

<div class="stat">

<div class="stat-title">
TAKEN
</div>

<div class="stat-value green">
{{ taken }}
</div>

</div>

<div class="stat">

<div class="stat-title">
NOT TAKEN
</div>

<div class="stat-value red">
{{ not_taken }}
</div>

</div>

<div class="stat">

<div class="stat-title">
CANCELLED
</div>

<div class="stat-value orange">
{{ cancelled }}
</div>

</div>

<div class="stat">

<div class="stat-title">
COMPLETION
</div>

<div class="stat-value green">
{{ "%.1f"|format(percentage) }}%
</div>

</div>

</div>

<div class="section">

<h2>📚 Subject-wise Report</h2>

{% if subject_stats %}

<div class="table-wrap">

<table>

<thead>

<tr>
<th>Subject</th>
<th>Total</th>
<th>Taken</th>
<th>Not Taken</th>
<th>Cancelled</th>
<th>Percentage</th>
</tr>

</thead>

<tbody>

{% for name, data in subject_stats.items() %}

<tr>

<td>
<strong>{{ name }}</strong>
</td>

<td>{{ data.total }}</td>

<td class="green">
{{ data.taken }}
</td>

<td class="red">
{{ data.not_taken }}
</td>

<td class="orange">
{{ data.cancelled }}
</td>

<td>

{{ "%.1f"|format(data.percentage) }}%

<div class="progress">

<div
class="progress-bar"
style="width:{{ data.percentage }}%"
></div>

</div>

</td>

</tr>

{% endfor %}

</tbody>

</table>

</div>

{% else %}

<div class="empty">
No attendance records found.
</div>

{% endif %}

</div>

<div class="section">

<h2>📝 Detailed Records</h2>

{% if records %}

<div class="table-wrap">

<table>

<thead>

<tr>
<th>Date</th>
<th>Day</th>
<th>Time</th>
<th>Subject</th>
<th>Status</th>
<th>Marked By</th>
</tr>

</thead>

<tbody>

{% for r in records %}

<tr>

<td>
{{ r.record_date.strftime("%d-%m-%Y") }}
</td>

<td>
{{ r.day }}
</td>

<td>
{{ r.slot }}
</td>

<td>
{{ r.subject }}
</td>

<td>

{% if r.status == "taken" %}

<span class="badge badge-taken">
✓ TAKEN
</span>

{% elif r.status == "not_taken" %}

<span class="badge badge-not">
✕ NOT TAKEN
</span>

{% else %}

<span class="badge badge-cancel">
CANCELLED
</span>

{% endif %}

</td>

<td>
{{ r.marked_by or "-" }}
</td>

</tr>

{% endfor %}

</tbody>

</table>

</div>

{% else %}

<div class="empty">
No records found.
</div>

{% endif %}

</div>
"""

    return render_page(
        content,
        faculties=faculties,
        faculty=faculty,
        years=years,
        year=year,
        period=period,
        subject=subject,
        subjects=subjects,
        start_date=start_date,
        end_date=end_date,
        total=total,
        taken=taken,
        not_taken=not_taken,
        cancelled=cancelled,
        percentage=percentage,
        subject_stats=subject_stats,
        records=records
    )


# ============================================================
# CSV EXPORT
# ============================================================

@app.route("/reports/export.csv")
def export_csv():

    faculties = get_faculties()

    faculty = request.args.get(
        "faculty",
        faculties[0] if faculties else ""
    )

    years = get_years(
        faculty
    )

    year = request.args.get(
        "year",
        years[0] if years else ""
    )

    period = request.args.get(
        "period",
        "month"
    )

    subject = request.args.get(
        "subject",
        ""
    )

    if period == "custom":

        try:

            start_date = datetime.strptime(
                request.args.get(
                    "start_date"
                ),
                "%Y-%m-%d"
            ).date()

            end_date = datetime.strptime(
                request.args.get(
                    "end_date"
                ),
                "%Y-%m-%d"
            ).date()

        except Exception:

            start_date, end_date = (
                date_range_for_period(
                    "month"
                )
            )

    else:

        start_date, end_date = (
            date_range_for_period(
                period
            )
        )

    records = get_report_records(
        faculty,
        year,
        start_date,
        end_date,
        subject if subject else None
    )

    output = io.StringIO()

    writer = csv.writer(
        output
    )

    writer.writerow([
        "Date",
        "Faculty",
        "Year",
        "Day",
        "Time",
        "Subject",
        "Status",
        "Marked By",
        "Marked At"
    ])

    for r in records:

        writer.writerow([
            r.record_date.strftime(
                "%Y-%m-%d"
            ),
            r.faculty,
            r.year,
            r.day,
            r.slot,
            r.subject,
            r.status,
            r.marked_by or "",
            r.marked_at.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        ])

    filename = (
        "SGB_Attendance_"
        f"{start_date}_"
        f"{end_date}.csv"
    )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
            f"attachment; filename={filename}"
        }
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return {
        "status": "ok",
        "application": "SGB College Management System"
    }


# ============================================================
# 404
# ============================================================

@app.errorhandler(404)
def not_found(error):

    content = """

<div class="empty">

<h1>404</h1>

<p>
Page not found.
</p>

<a
href="{{ url_for('home') }}"
class="btn btn-blue"
>
Go Home
</a>

</div>
"""

    return render_page(
        content
    ), 404


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("SGB COLLEGE MANAGEMENT SYSTEM")
    print("=" * 60)
    print()
    print("Computer:")
    print("http://127.0.0.1:5000")
    print()
    print("Phone / Same Wi-Fi:")
    print("http://192.168.1.16:5000")
    print()
    print("Public deployment:")
    print("Deploy this application to a cloud server.")
    print()
    print("Admin username:")
    print(ADMIN_USERNAME)
    print()
    print("Default admin password:")
    print(ADMIN_PASSWORD)
    print()
    print("=" * 60)

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=False
    )