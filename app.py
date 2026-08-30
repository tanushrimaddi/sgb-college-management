```python
import os
import json
import csv
import io
import sqlite3
from datetime import datetime, date
from functools import wraps
from zoneinfo import ZoneInfo

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
from werkzeug.security import generate_password_hash, check_password_hash


# ============================================================
# CONFIG
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "sgbm-college-secret-key-change-this"
)

TIMETABLE_FILE = "timetable.json"

DATABASE = os.environ.get(
    "DATABASE_PATH",
    "attendance.db"
)

ADMIN_USERNAME = os.environ.get(
    "ADMIN_USERNAME",
    "admin"
)

# IMPORTANT:
# Set ADMIN_PASSWORD_HASH in production.
# If it is not present, ADMIN_PASSWORD will be used once.
ADMIN_PASSWORD_HASH = os.environ.get(
    "ADMIN_PASSWORD_HASH",
    ""
)

ADMIN_PASSWORD = os.environ.get(
    "ADMIN_PASSWORD",
    "admin123"
)

IST = ZoneInfo("Asia/Kolkata")


FACULTIES = [
    "Science",
    "Arts",
    "Commerce"
]

YEARS = [
    "1st Year",
    "2nd Year",
    "3rd Year"
]

DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday"
]

STATUS_LABELS = {
    "taken": "Taken",
    "not_taken": "Not Taken",
    "cancelled": "Cancelled"
}


# ============================================================
# TIME / DATE HELPERS
# ============================================================

def now_ist():
    return datetime.now(IST)


def today_ist():
    return now_ist().date()


def today_string():
    return today_ist().isoformat()


def current_day_ist():
    return now_ist().strftime("%A")


def time_to_minutes(value):

    try:
        value = value.strip()
        h, m = map(int, value.split(":"))
        return h * 60 + m
    except Exception:
        return 9999


def time_sort_key(value):

    try:
        start = value.split("-")[0].strip()
        return time_to_minutes(start)
    except Exception:
        return 9999


def parse_time_range(value):

    try:
        start, end = value.split("-", 1)

        return (
            time_to_minutes(start),
            time_to_minutes(end)
        )

    except Exception:
        return None, None


def current_time_minutes():

    now = now_ist()

    return now.hour * 60 + now.minute


def is_current_slot(time_slot):

    start, end = parse_time_range(time_slot)

    if start is None or end is None:
        return False

    now = current_time_minutes()

    return start <= now < end


# ============================================================
# TIMETABLE
# ============================================================

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


def get_subjects(
    timetable,
    faculty,
    year,
    day,
    time_slot
):

    try:

        data = (
            timetable
            .get(faculty, {})
            .get(year, {})
            .get(day, {})
            .get(time_slot, [])
        )

        if isinstance(data, str):
            return [data]

        if isinstance(data, list):
            return data

        return []

    except Exception:
        return []


def get_all_time_slots(
    timetable,
    faculty,
    year
):

    slots = set()

    year_data = (
        timetable
        .get(faculty, {})
        .get(year, {})
    )

    for day in DAYS:

        day_data = year_data.get(day, {})

        if isinstance(day_data, dict):

            for slot in day_data:
                slots.add(slot)

    return sorted(
        slots,
        key=time_sort_key
    )


def get_current_lectures(
    timetable,
    faculty,
    year
):

    today = current_day_ist()

    result = []

    day_data = (
        timetable
        .get(faculty, {})
        .get(year, {})
        .get(today, {})
    )

    for time_slot in sorted(
        day_data.keys(),
        key=time_sort_key
    ):

        if is_current_slot(time_slot):

            subjects = day_data.get(
                time_slot,
                []
            )

            if isinstance(subjects, str):
                subjects = [subjects]

            for subject in subjects:

                result.append({
                    "time": time_slot,
                    "lecture": subject
                })

    return result


def get_next_lecture(
    timetable,
    faculty,
    year
):

    today = current_day_ist()

    now = current_time_minutes()

    day_data = (
        timetable
        .get(faculty, {})
        .get(year, {})
        .get(today, {})
    )

    possible = []

    for time_slot in day_data:

        start, end = parse_time_range(
            time_slot
        )

        if (
            start is not None
            and start > now
        ):

            possible.append(
                (start, time_slot)
            )

    possible.sort()

    if not possible:
        return None

    slot = possible[0][1]

    subjects = day_data.get(
        slot,
        []
    )

    if isinstance(subjects, str):
        subjects = [subjects]

    return {
        "time": slot,
        "lectures": subjects
    }


# ============================================================
# DATABASE
# ============================================================

def get_db():

    conn = sqlite3.connect(
        DATABASE,
        timeout=30
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            attendance_date TEXT NOT NULL,

            faculty TEXT NOT NULL,

            year TEXT NOT NULL,

            day TEXT NOT NULL,

            time_slot TEXT NOT NULL,

            lecture TEXT NOT NULL,

            status TEXT NOT NULL,

            marked_by TEXT,

            marked_at TEXT,

            UNIQUE (
                attendance_date,
                faculty,
                year,
                day,
                time_slot
            )
        )
    """)

    # Indexes for faster report searching.
    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_attendance_date
        ON attendance(attendance_date)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_attendance_faculty_year
        ON attendance(faculty, year)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_attendance_subject
        ON attendance(lecture)
    """)

    conn.commit()
    conn.close()


init_db()


# ============================================================
# LOGIN
# ============================================================

def admin_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not session.get(
            "admin_logged_in"
        ):

            return redirect(
                url_for(
                    "login",
                    next=request.path
                )
            )

        return function(*args, **kwargs)

    return wrapper


def verify_admin_password(password):

    if ADMIN_PASSWORD_HASH:

        try:
            return check_password_hash(
                ADMIN_PASSWORD_HASH,
                password
            )
        except Exception:
            return False

    return password == ADMIN_PASSWORD


# ============================================================
# SHARED CSS
# ============================================================

BASE_CSS = r"""
* {
    box-sizing:border-box;
}

body {
    margin:0;
    font-family:Arial, sans-serif;
    background:#f1f5f9;
    color:#1e293b;
}

.navbar {
    background:#111827;
    color:white;
    padding:14px 24px;
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:20px;
}

.logo {
    font-size:20px;
    font-weight:bold;
}

.logo small {
    display:block;
    font-size:9px;
    opacity:.65;
    margin-top:3px;
}

.nav {
    display:flex;
    flex-wrap:wrap;
    gap:12px;
}

.nav a {
    color:white;
    text-decoration:none;
    padding:7px 9px;
    border-radius:7px;
    font-size:13px;
}

.nav a:hover {
    background:#374151;
}

.container {
    max-width:1400px;
    margin:auto;
    padding:22px;
}

.hero {
    background:linear-gradient(135deg,#2563eb,#7c3aed);
    color:white;
    padding:30px;
    border-radius:18px;
    margin-bottom:20px;
}

.hero h1 {
    margin:0;
    font-size:30px;
}

.hero p {
    margin-bottom:0;
    opacity:.9;
}

.box {
    background:white;
    padding:20px;
    border-radius:14px;
    margin-bottom:20px;
    box-shadow:0 4px 15px rgba(0,0,0,.05);
}

.controls {
    display:flex;
    gap:12px;
    flex-wrap:wrap;
    align-items:end;
}

.field {
    flex:1;
    min-width:170px;
}

label {
    display:block;
    font-weight:bold;
    margin-bottom:6px;
    font-size:13px;
}

input,
select {
    width:100%;
    padding:11px;
    border:1px solid #cbd5e1;
    border-radius:8px;
    background:white;
    font-size:14px;
}

button,
.btn {
    display:inline-block;
    border:0;
    border-radius:8px;
    padding:11px 16px;
    background:#2563eb;
    color:white;
    cursor:pointer;
    text-decoration:none;
    font-weight:bold;
}

.btn.green {
    background:#16a34a;
}

.btn.gray {
    background:#475569;
}

.btn.red {
    background:#dc2626;
}

.btn.dark {
    background:#111827;
}

.btn.purple {
    background:#7c3aed;
}

.btn.small {
    padding:7px 10px;
    font-size:12px;
}

.cards {
    display:grid;
    grid-template-columns:repeat(4,1fr);
    gap:15px;
    margin-bottom:20px;
}

.card {
    background:white;
    padding:20px;
    border-radius:14px;
    box-shadow:0 4px 15px rgba(0,0,0,.05);
}

.card-title {
    color:#64748b;
    font-size:12px;
    text-transform:uppercase;
}

.card-value {
    font-size:25px;
    font-weight:bold;
    margin-top:8px;
}

.green-text {
    color:#16a34a;
}

.blue-text {
    color:#2563eb;
}

.red-text {
    color:#dc2626;
}

.purple-text {
    color:#7c3aed;
}

.table-wrapper {
    overflow-x:auto;
}

table {
    width:100%;
    border-collapse:collapse;
    min-width:850px;
}

th {
    background:#172554;
    color:white;
    padding:11px;
    border:1px solid #cbd5e1;
    text-align:center;
}

td {
    padding:10px;
    border:1px solid #dbe3ee;
    text-align:center;
    vertical-align:middle;
}

.time {
    background:#f1f5f9;
    font-weight:bold;
}

.subject {
    display:block;
    background:#eff6ff;
    color:#1e3a8a;
    padding:7px;
    margin:3px;
    border-radius:6px;
    font-size:13px;
}

.badge {
    display:inline-block;
    padding:5px 9px;
    border-radius:20px;
    font-size:11px;
    font-weight:bold;
}

.badge.taken {
    background:#dcfce7;
    color:#166534;
}

.badge.not_taken {
    background:#fee2e2;
    color:#991b1b;
}

.badge.cancelled {
    background:#e2e8f0;
    color:#475569;
}

.badge.unmarked {
    background:#fef3c7;
    color:#92400e;
}

.live-row {
    background:#dcfce7;
}

.flash {
    padding:12px;
    border-radius:8px;
    background:#dcfce7;
    color:#166534;
    margin-bottom:15px;
}

.stat-grid {
    display:grid;
    grid-template-columns:repeat(5,1fr);
    gap:12px;
}

.stat {
    padding:15px;
    border-radius:10px;
    background:#f8fafc;
    text-align:center;
}

.stat strong {
    display:block;
    font-size:22px;
    margin-top:5px;
}

.empty {
    text-align:center;
    padding:30px;
    color:#64748b;
}

@media(max-width:900px) {
    .cards {
        grid-template-columns:repeat(2,1fr);
    }

    .stat-grid {
        grid-template-columns:repeat(2,1fr);
    }
}

@media(max-width:600px) {
    .navbar {
        flex-direction:column;
        align-items:flex-start;
    }

    .container {
        padding:12px;
    }

    .cards {
        grid-template-columns:1fr;
    }

    .stat-grid {
        grid-template-columns:1fr;
    }

    .hero h1 {
        font-size:23px;
    }
}

@media print {
    .navbar,
    .no-print,
    .controls,
    .top-buttons {
        display:none !important;
    }

    body {
        background:white;
    }

    .box {
        box-shadow:none;
    }
}
"""


# ============================================================
# HOME PAGE
# ============================================================

HOME_PAGE = r"""
<!DOCTYPE html>
<html>
<head>
<title>SGB College Management</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
{{ base_css }}
</style>
</head>

<body>

<div class="navbar">

<div class="logo">
🎓 SGB COLLEGE
<small>MANAGEMENT SYSTEM</small>
</div>

<div class="nav">
<a href="/">⌂ Home</a>
<a href="/timetable">📅 Timetable</a>
<a href="/master-timetable">📋 Master</a>
<a href="/attendance">☑ Attendance</a>
<a href="/reports">📊 Reports</a>

{% if session.get("admin_logged_in") %}
<a href="/logout">Logout</a>
{% else %}
<a href="/login">🔐 Admin</a>
{% endif %}
</div>

</div>


<div class="container">

<div class="hero">

<h1>🎓 SGB College Management</h1>

<p>
Smart timetable, live lecture, attendance and reports
</p>

<p>
Current IST Time:
<strong>{{ current_datetime }}</strong>
</p>

</div>


<div class="box">

<form method="GET" class="controls">

<div class="field">

<label>Faculty</label>

<select name="faculty">

{% for f in faculties %}

<option value="{{ f }}"
{% if f == selected_faculty %}selected{% endif %}>
{{ f }}
</option>

{% endfor %}

</select>

</div>


<div class="field">

<label>Year</label>

<select name="year">

{% for y in years %}

<option value="{{ y }}"
{% if y == selected_year %}selected{% endif %}>
{{ y }}
</option>

{% endfor %}

</select>

</div>


<div>
<button>VIEW</button>
</div>

</form>

</div>


<div class="cards">

<div class="card">

<div class="card-title">
Current Lecture
</div>

<div class="card-value green-text">

{% if current_lectures %}
LIVE NOW
{% else %}
No Live Lecture
{% endif %}

</div>

</div>


<div class="card">

<div class="card-title">
Next Lecture
</div>

<div class="card-value blue-text">

{% if next_lecture %}
{{ next_lecture.time }}
{% else %}
—
{% endif %}

</div>

</div>


<div class="card">

<div class="card-title">
Today
</div>

<div class="card-value purple-text">
{{ today }}
</div>

</div>


<div class="card">

<div class="card-title">
Selected Class
</div>

<div class="card-value">
{{ selected_faculty }}
</div>

<div>
{{ selected_year }}
</div>

</div>

</div>


<div class="box">

<h2>🟢 Current Lecture</h2>

{% if current_lectures %}

{% for item in current_lectures %}

<div style="
padding:15px;
margin:8px 0;
background:#ecfdf5;
border-left:5px solid #16a34a;
border-radius:8px;
">

<strong>{{ item.time }}</strong>

&nbsp; — &nbsp;

{{ item.lecture }}

<span class="badge taken"
style="float:right;">
LIVE NOW
</span>

</div>

{% endfor %}

{% else %}

<div class="empty">
No lecture is currently running.
</div>

{% endif %}

</div>


<div class="box">

<h2>➡️ Next Lecture</h2>

{% if next_lecture %}

<p>
<strong>{{ next_lecture.time }}</strong>
</p>

{% for subject in next_lecture.lectures %}

<span class="subject">
{{ subject }}
</span>

{% endfor %}

{% else %}

<p>No more lectures scheduled for today.</p>

{% endif %}

</div>


<div class="box">

<h2>📅 Today's Timetable</h2>

<div class="table-wrapper">

<table>

<tr>
<th>TIME</th>
<th>LECTURE</th>
</tr>

{% for slot in today_slots %}

<tr {% if slot in current_slots %}
class="live-row"
{% endif %}>

<td class="time">
{{ slot }}
</td>

<td>

{% for subject in today_data.get(slot,[]) %}

<span class="subject">
{{ subject }}
</span>

{% endfor %}

</td>

</tr>

{% endfor %}

</table>

</div>

</div>


<div class="box" style="
background:linear-gradient(135deg,#111827,#1e3a8a);
color:white;
text-align:center;
">

<h2>📚 All Class Timetable</h2>

<p>
Science + Arts + Commerce<br>
1st Year + 2nd Year + 3rd Year
</p>

<a href="/master-timetable"
class="btn">
OPEN MASTER TIMETABLE
</a>

</div>


<div class="box" style="
text-align:center;
">

<h2>📊 Attendance Reports</h2>

<p>
Admin can retrieve old attendance by date, date range,
faculty, year, day and subject.
</p>

<a href="/reports"
class="btn purple">
OPEN REPORTS
</a>

</div>


</div>


<script>

setTimeout(function() {
    location.reload();
}, 30000);

</script>

</body>
</html>
"""


@app.route("/")
def home():

    timetable = load_timetable()

    selected_faculty = request.args.get(
        "faculty",
        "Science"
    )

    selected_year = request.args.get(
        "year",
        "1st Year"
    )

    if selected_faculty not in FACULTIES:
        selected_faculty = "Science"

    if selected_year not in YEARS:
        selected_year = "1st Year"

    today = current_day_ist()

    today_data = (
        timetable
        .get(selected_faculty, {})
        .get(selected_year, {})
        .get(today, {})
    )

    today_slots = sorted(
        today_data.keys(),
        key=time_sort_key
    )

    current_lectures = get_current_lectures(
        timetable,
        selected_faculty,
        selected_year
    )

    current_slots = [
        x["time"]
        for x in current_lectures
    ]

    next_lecture = get_next_lecture(
        timetable,
        selected_faculty,
        selected_year
    )

    return render_template_string(
        HOME_PAGE,
        base_css=BASE_CSS,
        faculties=FACULTIES,
        years=YEARS,
        selected_faculty=selected_faculty,
        selected_year=selected_year,
        current_lectures=current_lectures,
        current_slots=current_slots,
        next_lecture=next_lecture,
        today=today,
        today_data=today_data,
        today_slots=today_slots,
        current_datetime=now_ist().strftime(
            "%d-%m-%Y %I:%M:%S %p"
        )
    )


# ============================================================
# MASTER TIMETABLE
# ============================================================

MASTER_PAGE = r"""
<!DOCTYPE html>
<html>
<head>
<title>Master Timetable</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
{{ base_css }}

.faculty {
    margin-bottom:40px;
}

.faculty-title {
    background:linear-gradient(135deg,#172554,#2563eb);
    color:white;
    padding:18px;
    border-radius:12px 12px 0 0;
}

.year-title {
    background:white;
    padding:14px;
    font-size:19px;
    font-weight:bold;
    border-left:5px solid #2563eb;
}

.empty {
    color:#94a3b8;
}
</style>
</head>

<body>

<div class="navbar">

<div class="logo">
🎓 SGB COLLEGE
</div>

<div class="nav">
<a href="/">⌂ Home</a>
<a href="/timetable">📅 Timetable</a>
<a href="/attendance">☑ Attendance</a>
<a href="/reports">📊 Reports</a>
</div>

</div>


<div class="container">

<div class="box no-print">

<a href="/" class="btn gray">
← Home
</a>

<button
onclick="window.print()"
class="btn green">
🖨 Print All
</button>

</div>


{% for faculty in faculties %}

<div class="faculty">

<div class="faculty-title">
<h2>{{ faculty }}</h2>
</div>


{% for year in years %}

{% if year in timetable.get(faculty,{}) %}

<div class="year-title">
{{ year }}
</div>


{% set times = get_all_time_slots(
    timetable,
    faculty,
    year
) %}


<div class="table-wrapper">

<table>

<thead>

<tr>

<th>TIME</th>

{% for day in days %}

<th>{{ day }}</th>

{% endfor %}

</tr>

</thead>


<tbody>

{% for slot in times %}

<tr>

<td class="time">
{{ slot }}
</td>


{% for day in days %}

<td>

{% set subjects =
get_subjects(
    timetable,
    faculty,
    year,
    day,
    slot
)
%}


{% if subjects %}

{% for subject in subjects %}

<span class="subject">
{{ subject }}
</span>

{% endfor %}

{% else %}

<span class="empty">—</span>

{% endif %}

</td>

{% endfor %}

</tr>

{% endfor %}

</tbody>

</table>

</div>

<br>

{% endif %}

{% endfor %}

</div>

{% endfor %}

</div>

</body>
</html>
"""


@app.route("/master-timetable")
def master_timetable():

    timetable = load_timetable()

    return render_template_string(
        MASTER_PAGE,
        base_css=BASE_CSS,
        timetable=timetable,
        faculties=FACULTIES,
        years=YEARS,
        days=DAYS,
        get_all_time_slots=get_all_time_slots,
        get_subjects=get_subjects
    )


# ============================================================
# DAILY TIMETABLE
# ============================================================

TIMETABLE_PAGE = r"""
<!DOCTYPE html>
<html>
<head>
<title>Daily Timetable</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
{{ base_css }}
</style>
</head>

<body>

<div class="navbar">

<div class="logo">🎓 SGB COLLEGE</div>

<div class="nav">
<a href="/">⌂ Home</a>
<a href="/master-timetable">📋 Master</a>
<a href="/attendance">☑ Attendance</a>
<a href="/reports">📊 Reports</a>
</div>

</div>


<div class="container">

<div class="box">

<h1>📅 Daily Timetable</h1>

<form method="GET" class="controls">

<div class="field">
<label>Faculty</label>

<select name="faculty">

{% for f in faculties %}

<option value="{{ f }}"
{% if f == faculty %}selected{% endif %}>
{{ f }}
</option>

{% endfor %}

</select>
</div>


<div class="field">
<label>Year</label>

<select name="year">

{% for y in years %}

<option value="{{ y }}"
{% if y == year %}selected{% endif %}>
{{ y }}
</option>

{% endfor %}

</select>
</div>


<div class="field">
<label>Day</label>

<select name="day">

{% for d in days %}

<option value="{{ d }}"
{% if d == selected_day %}selected{% endif %}>
{{ d }}
</option>

{% endfor %}

</select>
</div>


<button>VIEW</button>

</form>

</div>


<div class="box">

<h2>
{{ selected_day }} —
{{ faculty }} —
{{ year }}
</h2>

<div class="table-wrapper">

<table>

<tr>
<th>TIME</th>
<th>{{ selected_day }}</th>
</tr>


{% for slot in slots %}

<tr>

<td class="time">
{{ slot }}
</td>

<td>

{% for subject in data.get(slot,[]) %}

<span class="subject">
{{ subject }}
</span>

{% endfor %}

</td>

</tr>

{% endfor %}

</table>

</div>

</div>

</div>

</body>
</html>
"""


@app.route("/timetable")
def timetable_page():

    timetable = load_timetable()

    faculty = request.args.get(
        "faculty",
        "Science"
    )

    year = request.args.get(
        "year",
        "1st Year"
    )

    selected_day = request.args.get(
        "day",
        current_day_ist()
    )

    if faculty not in FACULTIES:
        faculty = "Science"

    if year not in YEARS:
        year = "1st Year"

    if selected_day not in DAYS:
        selected_day = "Monday"

    data = (
        timetable
        .get(faculty, {})
        .get(year, {})
        .get(selected_day, {})
    )

    slots = sorted(
        data.keys(),
        key=time_sort_key
    )

    return render_template_string(
        TIMETABLE_PAGE,
        base_css=BASE_CSS,
        faculties=FACULTIES,
        years=YEARS,
        days=DAYS,
        faculty=faculty,
        year=year,
        selected_day=selected_day,
        data=data,
        slots=slots
    )


# ============================================================
# LOGIN
# ============================================================

LOGIN_PAGE = r"""
<!DOCTYPE html>
<html>
<head>
<title>Admin Login</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
{{ base_css }}

.login-box {
    max-width:420px;
    margin:80px auto;
}
</style>
</head>

<body>

<div class="container">

<div class="box login-box">

<h1 style="text-align:center">
🔐 Admin Login
</h1>


{% with messages = get_flashed_messages() %}

{% for message in messages %}

<div class="flash">
{{ message }}
</div>

{% endfor %}

{% endwith %}


<form method="POST">

<label>Username</label>

<input
type="text"
name="username"
required
>


<label style="margin-top:12px">
Password
</label>

<input
type="password"
name="password"
required
>


<button
style="width:100%;margin-top:15px;">
LOGIN
</button>

</form>


<p style="
text-align:center;
margin-top:20px;
">

<a href="/">
← Back to Home
</a>

</p>

</div>

</div>

</body>
</html>
"""


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

        if (
            username == ADMIN_USERNAME
            and verify_admin_password(password)
        ):

            session.clear()

            session["admin_logged_in"] = True
            session["admin_username"] = username

            next_url = request.args.get(
                "next",
                "/"
            )

            if not next_url.startswith("/"):
                next_url = "/"

            return redirect(next_url)

        flash(
            "Invalid username or password."
        )

    return render_template_string(
        LOGIN_PAGE,
        base_css=BASE_CSS
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# ============================================================
# ATTENDANCE PAGE
# ============================================================

ATTENDANCE_PAGE = r"""
<!DOCTYPE html>
<html>
<head>
<title>Class Attendance</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
{{ base_css }}

.action-form {
    display:flex;
    gap:5px;
    flex-wrap:wrap;
    justify-content:center;
}

.action-form button {
    padding:7px 10px;
    font-size:11px;
}
</style>
</head>

<body>

<div class="navbar">

<div class="logo">
🎓 SGB COLLEGE
</div>

<div class="nav">
<a href="/">⌂ Home</a>
<a href="/timetable">📅 Timetable</a>
<a href="/master-timetable">📋 Master</a>
<a href="/reports">📊 Reports</a>

{% if session.get("admin_logged_in") %}
<a href="/logout">Logout</a>
{% else %}
<a href="/login">🔐 Admin</a>
{% endif %}

</div>

</div>


<div class="container">

<div class="box">

<h1>☑ Class Attendance</h1>

{% with messages = get_flashed_messages() %}

{% for message in messages %}

<div class="flash">
{{ message }}
</div>

{% endfor %}

{% endwith %}


<form method="GET" class="controls">

<div class="field">

<label>Faculty</label>

<select name="faculty">

{% for f in faculties %}

<option value="{{ f }}"
{% if f == faculty %}selected{% endif %}>
{{ f }}
</option>

{% endfor %}

</select>

</div>


<div class="field">

<label>Year</label>

<select name="year">

{% for y in years %}

<option value="{{ y }}"
{% if y == year %}selected{% endif %}>
{{ y }}
</option>

{% endfor %}

</select>

</div>


<div class="field">

<label>Day</label>

<select name="day">

{% for d in days %}

<option value="{{ d }}"
{% if d == selected_day %}selected{% endif %}>
{{ d }}
</option>

{% endfor %}

</select>

</div>


<div>
<button>VIEW</button>
</div>

</form>

</div>


<div class="box">

<h2>
{{ selected_day }} —
{{ faculty }} —
{{ year }}
</h2>

<p>
Attendance date:
<strong>{{ attendance_date }}</strong>
</p>


{% if not session.get("admin_logged_in") %}

<div style="
background:#fef3c7;
color:#92400e;
padding:12px;
border-radius:8px;
margin-bottom:15px;
">
🔒 Login as admin to mark or edit attendance.
</div>

{% endif %}


<div class="table-wrapper">

<table>

<tr>

<th>TIME</th>
<th>LECTURE</th>
<th>STATUS</th>
<th>ACTION</th>

</tr>


{% for item in lectures %}

<tr>

<td class="time">
{{ item.time }}
</td>


<td>

{% for subject in item.subjects %}

<span class="subject">
{{ subject }}
</span>

{% endfor %}

</td>


<td>

{% if item.status == "taken" %}

<span class="badge taken">
Taken
</span>

{% elif item.status == "not_taken" %}

<span class="badge not_taken">
Not Taken
</span>

{% elif item.status == "cancelled" %}

<span class="badge cancelled">
Cancelled
</span>

{% else %}

<span class="badge unmarked">
Not Marked
</span>

{% endif %}

</td>


<td>

{% if session.get("admin_logged_in") %}

<form
method="POST"
action="/attendance/mark"
class="action-form"
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
value="{{ selected_day }}"
>

<input
type="hidden"
name="time_slot"
value="{{ item.time }}"
>

<input
type="hidden"
name="lecture"
value="{{ item.subject_text }}"
>


<button
name="status"
value="taken"
style="background:#16a34a;"
>
✓ Taken
</button>


<button
name="status"
value="not_taken"
style="background:#dc2626;"
>
✗ Not Taken
</button>


<button
name="status"
value="cancelled"
style="background:#64748b;"
>
Cancelled
</button>

</form>

{% else %}

<a href="/login"
class="btn small">
Admin Login
</a>

{% endif %}

</td>

</tr>

{% endfor %}

</table>

</div>

</div>

</div>

</body>
</html>
"""


@app.route("/attendance")
def attendance():

    timetable = load_timetable()

    faculty = request.args.get(
        "faculty",
        "Science"
    )

    year = request.args.get(
        "year",
        "1st Year"
    )

    selected_day = request.args.get(
        "day",
        current_day_ist()
    )

    if faculty not in FACULTIES:
        faculty = "Science"

    if year not in YEARS:
        year = "1st Year"

    if selected_day not in DAYS:
        selected_day = "Monday"

    data = (
        timetable
        .get(faculty, {})
        .get(year, {})
        .get(selected_day, {})
    )

    slots = sorted(
        data.keys(),
        key=time_sort_key
    )

    # Attendance page always shows today's date.
    attendance_date = today_string()

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM attendance
        WHERE attendance_date=?
        AND faculty=?
        AND year=?
        AND day=?
    """, (
        attendance_date,
        faculty,
        year,
        selected_day
    )).fetchall()

    conn.close()

    status_map = {}

    for row in rows:

        status_map[
            row["time_slot"]
        ] = row["status"]

    lectures = []

    for slot in slots:

        subjects = data.get(
            slot,
            []
        )

        if isinstance(subjects, str):
            subjects = [subjects]

        lectures.append({

            "time": slot,

            "subjects": subjects,

            "subject_text": " | ".join(
                str(x)
                for x in subjects
            ),

            "status": status_map.get(
                slot,
                ""
            )

        })

    return render_template_string(
        ATTENDANCE_PAGE,
        base_css=BASE_CSS,
        faculties=FACULTIES,
        years=YEARS,
        days=DAYS,
        faculty=faculty,
        year=year,
        selected_day=selected_day,
        lectures=lectures,
        attendance_date=attendance_date
    )


# ============================================================
# MARK / UPDATE ATTENDANCE
# ============================================================

@app.route(
    "/attendance/mark",
    methods=["POST"]
)
@admin_required
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

    time_slot = request.form.get(
        "time_slot",
        ""
    )

    lecture = request.form.get(
        "lecture",
        ""
    )

    status = request.form.get(
        "status",
        ""
    )

    if faculty not in FACULTIES:
        return redirect("/attendance")

    if year not in YEARS:
        return redirect("/attendance")

    if day not in DAYS:
        return redirect("/attendance")

    if status not in STATUS_LABELS:
        status = "not_taken"

    attendance_date = today_string()

    marked_at = now_ist().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    marked_by = session.get(
        "admin_username",
        ADMIN_USERNAME
    )

    conn = get_db()

    existing = conn.execute("""
        SELECT id
        FROM attendance
        WHERE attendance_date=?
        AND faculty=?
        AND year=?
        AND day=?
        AND time_slot=?
    """, (
        attendance_date,
        faculty,
        year,
        day,
        time_slot
    )).fetchone()

    if existing:

        conn.execute("""
            UPDATE attendance

            SET lecture=?,
                status=?,
                marked_by=?,
                marked_at=?

            WHERE id=?
        """, (
            lecture,
            status,
            marked_by,
            marked_at,
            existing["id"]
        ))

    else:

        conn.execute("""
            INSERT INTO attendance
            (
                attendance_date,
                faculty,
                year,
                day,
                time_slot,
                lecture,
                status,
                marked_by,
                marked_at
            )

            VALUES
            (?,?,?,?,?,?,?,?,?)
        """, (
            attendance_date,
            faculty,
            year,
            day,
            time_slot,
            lecture,
            status,
            marked_by,
            marked_at
        ))

    conn.commit()
    conn.close()

    flash(
        f"Attendance updated: {STATUS_LABELS[status]}"
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
# REPORT HELPERS
# ============================================================

def safe_date(value, default_value):

    try:
        return datetime.strptime(
            value,
            "%Y-%m-%d"
        ).date()
    except Exception:
        return default_value


def build_report_filters():

    today = today_ist()

    default_from = today.replace(
        day=1
    )

    from_date = safe_date(
        request.args.get(
            "from_date",
            ""
        ),
        default_from
    )

    to_date = safe_date(
        request.args.get(
            "to_date",
            ""
        ),
        today
    )

    if from_date > to_date:
        from_date, to_date = (
            to_date,
            from_date
        )

    faculty = request.args.get(
        "faculty",
        ""
    ).strip()

    year = request.args.get(
        "year",
        ""
    ).strip()

    day = request.args.get(
        "day",
        ""
    ).strip()

    subject = request.args.get(
        "subject",
        ""
    ).strip()

    status = request.args.get(
        "status",
        ""
    ).strip()

    if faculty not in FACULTIES:
        faculty = ""

    if year not in YEARS:
        year = ""

    if day not in DAYS:
        day = ""

    if status not in STATUS_LABELS:
        status = ""

    return {
        "from_date": from_date,
        "to_date": to_date,
        "faculty": faculty,
        "year": year,
        "day": day,
        "subject": subject,
        "status": status
    }


def report_where_clause(filters):

    conditions = [
        "attendance_date BETWEEN ? AND ?"
    ]

    params = [
        filters["from_date"].isoformat(),
        filters["to_date"].isoformat()
    ]

    if filters["faculty"]:

        conditions.append(
            "faculty=?"
        )

        params.append(
            filters["faculty"]
        )

    if filters["year"]:

        conditions.append(
            "year=?"
        )

        params.append(
            filters["year"]
        )

    if filters["day"]:

        conditions.append(
            "day=?"
        )

        params.append(
            filters["day"]
        )

    if filters["subject"]:

        conditions.append(
            "lecture LIKE ?"
        )

        params.append(
            "%" + filters["subject"] + "%"
        )

    if filters["status"]:

        conditions.append(
            "status=?"
        )

        params.append(
            filters["status"]
        )

    return (
        " WHERE " + " AND ".join(conditions),
        params
    )


def calculate_percentage(taken, total_valid):

    if total_valid <= 0:
        return 0.0

    return round(
        (taken / total_valid) * 100,
        2
    )


# ============================================================
# REPORT PAGE
# ============================================================

REPORT_PAGE = r"""
<!DOCTYPE html>
<html>

<head>

<title>Attendance Reports</title>

<meta name="viewport"
content="width=device-width,initial-scale=1">

<style>

{{ base_css }}

.report-header {
    background:linear-gradient(135deg,#172554,#7c3aed);
    color:white;
    padding:25px;
    border-radius:15px;
    margin-bottom:20px;
}

.percentage {
    font-size:22px;
    font-weight:bold;
}

.progress {
    height:9px;
    background:#e2e8f0;
    border-radius:20px;
    overflow:hidden;
    min-width:100px;
}

.progress-bar {
    height:100%;
    background:#16a34a;
}

@media print {

    .report-filter,
    .no-print,
    .navbar {
        display:none !important;
    }

}

</style>

</head>


<body>


<div class="navbar">

<div class="logo">
🎓 SGB COLLEGE
</div>

<div class="nav">

<a href="/">⌂ Home</a>
<a href="/timetable">📅 Timetable</a>
<a href="/master-timetable">📋 Master</a>
<a href="/attendance">☑ Attendance</a>

{% if session.get("admin_logged_in") %}
<a href="/logout">Logout</a>
{% endif %}

</div>

</div>


<div class="container">


<div class="report-header">

<h1>
📊 Attendance Reports
</h1>

<p>
Retrieve saved attendance anytime using filters.
</p>

<p>
<strong>
{{ filters.from_date }} → {{ filters.to_date }}
</strong>
</p>

</div>


<div class="box report-filter">

<h2>🔎 Report Filters</h2>


<form method="GET"
class="controls">


<div class="field">

<label>From Date</label>

<input
type="date"
name="from_date"
value="{{ filters.from_date }}"
>

</div>


<div class="field">

<label>To Date</label>

<input
type="date"
name="to_date"
value="{{ filters.to_date }}"
>

</div>


<div class="field">

<label>Faculty</label>

<select name="faculty">

<option value="">All Faculties</option>

{% for f in faculties %}

<option value="{{ f }}"
{% if filters.faculty == f %}
selected
{% endif %}>
{{ f }}
</option>

{% endfor %}

</select>

</div>


<div class="field">

<label>Year</label>

<select name="year">

<option value="">All Years</option>

{% for y in years %}

<option value="{{ y }}"
{% if filters.year == y %}
selected
{% endif %}>
{{ y }}
</option>

{% endfor %}

</select>

</div>


<div class="field">

<label>Day</label>

<select name="day">

<option value="">All Days</option>

{% for d in days %}

<option value="{{ d }}"
{% if filters.day == d %}
selected
{% endif %}>
{{ d }}
</option>

{% endfor %}

</select>

</div>


<div class="field">

<label>Subject / Lecture</label>

<input
type="text"
name="subject"
placeholder="Search subject..."
value="{{ filters.subject }}"
>

</div>


<div class="field">

<label>Status</label>

<select name="status">

<option value="">All Status</option>

<option value="taken"
{% if filters.status == "taken" %}
selected
{% endif %}>
Taken
</option>

<option value="not_taken"
{% if filters.status == "not_taken" %}
selected
{% endif %}>
Not Taken
</option>

<option value="cancelled"
{% if filters.status == "cancelled" %}
selected
{% endif %}>
Cancelled
</option>

</select>

</div>


<div>

<button>
🔎 Generate Report
</button>

</div>

</form>

</div>


<div class="box no-print">

<strong>Export:</strong>

<a
href="{{ csv_url }}"
class="btn green">
⬇ Download CSV
</a>

<button
onclick="window.print()"
class="btn gray">
🖨 Print
</button>

</div>


<div class="stat-grid">

<div class="stat">

Total Records

<strong>
{{ stats.total }}
</strong>

</div>


<div class="stat">

Taken

<strong class="green-text">
{{ stats.taken }}
</strong>

</div>


<div class="stat">

Not Taken

<strong class="red-text">
{{ stats.not_taken }}
</strong>

</div>


<div class="stat">

Cancelled

<strong>
{{ stats.cancelled }}
</strong>

</div>


<div class="stat">

Attendance %

<strong class="purple-text">
{{ stats.percentage }}%
</strong>

</div>

</div>


<div class="box">

<h2>
📚 Subject-wise Summary
</h2>


{% if summary %}

<div class="table-wrapper">

<table>

<tr>

<th>Subject / Lecture</th>

<th>Total</th>

<th>Taken</th>

<th>Not Taken</th>

<th>Cancelled</th>

<th>Attendance %</th>

</tr>


{% for row in summary %}

<tr>

<td>
<strong>
{{ row.subject }}
</strong>
</td>

<td>
{{ row.total }}
</td>

<td class="green-text">
{{ row.taken }}
</td>

<td class="red-text">
{{ row.not_taken }}
</td>

<td>
{{ row.cancelled }}
</td>

<td>

<div class="percentage">
{{ row.percentage }}%
</div>

<div class="progress">

<div
class="progress-bar"
style="width:{{ row.percentage }}%;">
</div>

</div>

</td>

</tr>

{% endfor %}

</table>

</div>

{% else %}

<div class="empty">
No attendance records found for these filters.
</div>

{% endif %}

</div>


<div class="box">

<h2>
📋 Detailed Attendance Report
</h2>


{% if recent %}

<div class="table-wrapper">

<table>

<thead>

<tr>

<th>Date</th>
<th>Day</th>
<th>Faculty</th>
<th>Year</th>
<th>Time</th>
<th>Lecture / Subject</th>
<th>Status</th>
<th>Marked By</th>
<th>Marked At</th>

</tr>

</thead>


<tbody>

{% for row in recent %}

<tr>

<td>
{{ row.attendance_date }}
</td>

<td>
{{ row.day }}
</td>

<td>
{{ row.faculty }}
</td>

<td>
{{ row.year }}
</td>

<td class="time">
{{ row.time_slot }}
</td>

<td style="text-align:left;">
{{ row.lecture }}
</td>

<td>

{% if row.status == "taken" %}

<span class="badge taken">
Taken
</span>

{% elif row.status == "not_taken" %}

<span class="badge not_taken">
Not Taken
</span>

{% else %}

<span class="badge cancelled">
Cancelled
</span>

{% endif %}

</td>

<td>
{{ row.marked_by or "—" }}
</td>

<td>
{{ row.marked_at or "—" }}
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


</div>

</body>

</html>
"""


@app.route("/reports")
@admin_required
def reports():

    filters = build_report_filters()

    where, params = report_where_clause(
        filters
    )

    conn = get_db()


    # --------------------------------------------------------
    # Detailed records
    # --------------------------------------------------------

    recent = conn.execute(
        """
        SELECT *
        FROM attendance
        """
        + where +
        """
        ORDER BY attendance_date DESC,
                 time_slot ASC,
                 faculty ASC,
                 year ASC
        """,
        params
    ).fetchall()


    # --------------------------------------------------------
    # Overall stats
    # --------------------------------------------------------

    stats_row = conn.execute(
        """
        SELECT

            COUNT(*) AS total,

            SUM(
                CASE
                WHEN status='taken'
                THEN 1 ELSE 0
                END
            ) AS taken,

            SUM(
                CASE
                WHEN status='not_taken'
                THEN 1 ELSE 0
                END
            ) AS not_taken,

            SUM(
                CASE
                WHEN status='cancelled'
                THEN 1 ELSE 0
                END
            ) AS cancelled

        FROM attendance
        """
        + where,
        params
    ).fetchone()


    total = stats_row["total"] or 0
    taken = stats_row["taken"] or 0
    not_taken = stats_row["not_taken"] or 0
    cancelled = stats_row["cancelled"] or 0

    # Cancelled lectures are excluded from attendance %
    valid_lectures = (
        taken + not_taken
    )

    percentage = calculate_percentage(
        taken,
        valid_lectures
    )


    # --------------------------------------------------------
    # Subject summary
    # --------------------------------------------------------

    summary_rows = conn.execute(
        """
        SELECT

            lecture,

            COUNT(*) AS total,

            SUM(
                CASE
                WHEN status='taken'
                THEN 1 ELSE 0
                END
            ) AS taken,

            SUM(
                CASE
                WHEN status='not_taken'
                THEN 1 ELSE 0
                END
            ) AS not_taken,

            SUM(
                CASE
                WHEN status='cancelled'
                THEN 1 ELSE 0
                END
            ) AS cancelled

        FROM attendance
        """
        + where +
        """
        GROUP BY lecture
        ORDER BY lecture
        """,
        params
    ).fetchall()


    summary = []

    for row in summary_rows:

        subject_taken = row["taken"] or 0
        subject_not_taken = row["not_taken"] or 0

        subject_valid = (
            subject_taken
            + subject_not_taken
        )

        summary.append({

            "subject": row["lecture"],

            "total": row["total"] or 0,

            "taken": subject_taken,

            "not_taken": subject_not_taken,

            "cancelled": row["cancelled"] or 0,

            "percentage":
                calculate_percentage(
                    subject_taken,
                    subject_valid
                )

        })


    conn.close()


    stats = {
        "total": total,
        "taken": taken,
        "not_taken": not_taken,
        "cancelled": cancelled,
        "percentage": percentage
    }


    csv_query = request.query_string.decode(
        "utf-8"
    )

    csv_url = (
        url_for("export_report")
        + ("?" + csv_query if csv_query else "")
    )


    return render_template_string(
        REPORT_PAGE,
        base_css=BASE_CSS,
        faculties=FACULTIES,
        years=YEARS,
        days=DAYS,
        filters={
            "from_date":
                filters["from_date"].isoformat(),

            "to_date":
                filters["to_date"].isoformat(),

            "faculty":
                filters["faculty"],

            "year":
                filters["year"],

            "day":
                filters["day"],

            "subject":
                filters["subject"],

            "status":
                filters["status"]
        },
        stats=stats,
        summary=summary,
        recent=recent,
        csv_url=csv_url
    )


# ============================================================
# CSV EXPORT
# ============================================================

@app.route("/reports/export")
@admin_required
def export_report():

    filters = build_report_filters()

    where, params = report_where_clause(
        filters
    )

    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            attendance_date,
            day,
            faculty,
            year,
            time_slot,
            lecture,
            status,
            marked_by,
            marked_at

        FROM attendance
        """
        + where +
        """
        ORDER BY attendance_date DESC,
                 time_slot ASC,
                 faculty ASC,
                 year ASC
        """,
        params
    ).fetchall()

    conn.close()


    output = io.StringIO()

    writer = csv.writer(
        output
    )

    writer.writerow([
        "Date",
        "Day",
        "Faculty",
        "Year",
        "Time",
        "Lecture / Subject",
        "Status",
        "Marked By",
        "Marked At"
    ])


    for row in rows:

        writer.writerow([
            row["attendance_date"],
            row["day"],
            row["faculty"],
            row["year"],
            row["time_slot"],
            row["lecture"],
            STATUS_LABELS.get(
                row["status"],
                row["status"]
            ),
            row["marked_by"] or "",
            row["marked_at"] or ""
        ])


    filename = (
        "attendance_report_"
        + filters["from_date"].isoformat()
        + "_to_"
        + filters["to_date"].isoformat()
        + ".csv"
    )


    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                f'attachment; filename="{filename}"'
        }
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return "SGB College Management System is running."


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
```
