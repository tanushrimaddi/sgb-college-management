```python
import os
import csv
import io
import json
import sqlite3
from datetime import datetime, date
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


# ============================================================
# CONFIG
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "sgbm-college-secret-key-change-this"
)

DATABASE = os.environ.get(
    "DATABASE_PATH",
    "attendance.db"
)

TIMETABLE_FILE = "timetable.json"

ADMIN_USERNAME = os.environ.get(
    "ADMIN_USERNAME",
    "admin"
)

ADMIN_PASSWORD = os.environ.get(
    "ADMIN_PASSWORD",
    "admin123"
)


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


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DATABASE)
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

            UNIQUE(
                attendance_date,
                faculty,
                year,
                day,
                time_slot
            )
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_attendance_date
        ON attendance(attendance_date)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_attendance_faculty_year
        ON attendance(faculty, year)
    """)

    conn.commit()
    conn.close()


init_db()


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
        ) as file:

            return json.load(file)

    except Exception as error:

        print("Timetable error:", error)

        return {}


# ============================================================
# LOGIN
# ============================================================

def admin_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not session.get("admin_logged_in"):

            return redirect(
                url_for(
                    "login",
                    next=request.path
                )
            )

        return function(*args, **kwargs)

    return wrapper


# ============================================================
# TIME FUNCTIONS
# ============================================================

def time_to_minutes(value):

    try:

        hours, minutes = map(
            int,
            value.strip().split(":")
        )

        return hours * 60 + minutes

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

        start, end = value.split("-")

        return (
            time_to_minutes(start),
            time_to_minutes(end)
        )

    except Exception:

        return None, None


def current_time_minutes():

    now = datetime.now()

    return now.hour * 60 + now.minute


def is_current_slot(time_slot):

    start, end = parse_time_range(time_slot)

    if start is None:
        return False

    now = current_time_minutes()

    return start <= now < end


# ============================================================
# SUBJECT FUNCTIONS
# ============================================================

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

        return data or []

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

        day_data = year_data.get(
            day,
            {}
        )

        for slot in day_data:
            slots.add(slot)

    return sorted(
        slots,
        key=time_sort_key
    )


# ============================================================
# CURRENT LECTURES
# ============================================================

def get_current_lectures(
    timetable,
    faculty,
    year
):

    today = datetime.now().strftime("%A")

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

    today = datetime.now().strftime("%A")

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

        if start is not None and start > now:

            possible.append(
                (start, time_slot)
            )

    possible.sort()

    if not possible:
        return None

    slot = possible[0][1]

    return {
        "time": slot,
        "lectures": day_data.get(
            slot,
            []
        )
    }


# ============================================================
# BASE CSS
# ============================================================

BASE_STYLE = """

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: Arial, sans-serif;
    background: #f1f5f9;
    color: #1e293b;
}

.navbar {
    background: #111827;
    color: white;
    padding: 15px 25px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
    flex-wrap: wrap;
}

.logo {
    font-size: 20px;
    font-weight: bold;
}

.logo small {
    display: block;
    font-size: 10px;
    opacity: .7;
}

.nav {
    display: flex;
    gap: 15px;
    flex-wrap: wrap;
}

.nav a {
    color: white;
    text-decoration: none;
    font-size: 14px;
}

.container {
    max-width: 1250px;
    margin: auto;
    padding: 22px;
}

.hero {
    background: linear-gradient(
        135deg,
        #2563eb,
        #7c3aed
    );
    color: white;
    padding: 30px;
    border-radius: 18px;
    margin-bottom: 20px;
}

.hero h1 {
    margin: 0;
}

.box {
    background: white;
    padding: 20px;
    border-radius: 14px;
    margin-bottom: 20px;
    box-shadow: 0 3px 14px rgba(0,0,0,.05);
}

.controls {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.control {
    flex: 1;
    min-width: 180px;
}

label {
    display: block;
    font-weight: bold;
    margin-bottom: 6px;
}

select,
input {
    width: 100%;
    padding: 11px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    font-size: 14px;
}

button,
.btn {
    padding: 11px 16px;
    border: 0;
    border-radius: 8px;
    background: #2563eb;
    color: white;
    text-decoration: none;
    cursor: pointer;
    font-weight: bold;
}

.btn-green {
    background: #16a34a;
}

.btn-dark {
    background: #111827;
}

.btn-red {
    background: #dc2626;
}

.btn-gray {
    background: #64748b;
}

.table-wrapper {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
}

th {
    background: #172554;
    color: white;
    padding: 11px;
    border: 1px solid #cbd5e1;
    white-space: nowrap;
}

td {
    padding: 10px;
    border: 1px solid #dbe3ee;
    text-align: center;
}

.badge {
    display: inline-block;
    padding: 6px 9px;
    border-radius: 20px;
    color: white;
    font-size: 12px;
    font-weight: bold;
}

.taken {
    background: #16a34a;
}

.not_taken {
    background: #dc2626;
}

.cancelled {
    background: #64748b;
}

.not_marked {
    background: #f59e0b;
}

.cards {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 15px;
}

.stat {
    background: white;
    padding: 20px;
    border-radius: 14px;
}

.stat-title {
    color: #64748b;
    font-size: 13px;
}

.stat-number {
    font-size: 28px;
    font-weight: bold;
    margin-top: 7px;
}

.success {
    color: #16a34a;
}

.danger {
    color: #dc2626;
}

.blue {
    color: #2563eb;
}

.orange {
    color: #d97706;
}

@media(max-width: 700px) {

    .cards {
        grid-template-columns: 1fr 1fr;
    }

    .navbar {
        align-items: flex-start;
    }

}

@media(max-width: 450px) {

    .cards {
        grid-template-columns: 1fr;
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

<meta name="viewport"
      content="width=device-width, initial-scale=1">

<style>
{{ style }}
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

<h1>
🎓 SGB College Management
</h1>

<p>
Smart Timetable • Attendance • Reports
</p>

</div>


<div class="box">

<form method="GET">

<div class="controls">

<div class="control">

<label>Faculty</label>

<select name="faculty">

{% for f in faculties %}

<option
value="{{ f }}"
{% if f == selected_faculty %}
selected
{% endif %}
>

{{ f }}

</option>

{% endfor %}

</select>

</div>


<div class="control">

<label>Year</label>

<select name="year">

{% for y in years %}

<option
value="{{ y }}"
{% if y == selected_year %}
selected
{% endif %}
>

{{ y }}

</option>

{% endfor %}

</select>

</div>


<div style="align-self:end">

<button>
VIEW
</button>

</div>

</div>

</form>

</div>


<div class="cards">

<div class="stat">

<div class="stat-title">
CURRENT LECTURE
</div>

<div class="stat-number success">

{% if current_lectures %}
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

<div class="stat-number blue">

{% if next_lecture %}
{{ next_lecture.time }}
{% else %}
—
{% endif %}

</div>

</div>


<div class="stat">

<div class="stat-title">
TODAY
</div>

<div class="stat-number">
{{ today }}
</div>

</div>


<div class="stat">

<div class="stat-title">
ATTENDANCE RECORDS
</div>

<div class="stat-number orange">
{{ attendance_count }}
</div>

</div>

</div>


<div class="box">

<h2>
🟢 Current Lecture
</h2>

{% if current_lectures %}

{% for item in current_lectures %}

<div style="
padding:14px;
margin:8px 0;
background:#ecfdf5;
border-left:4px solid #16a34a;
border-radius:8px;
">

<strong>
{{ item.time }}
</strong>

&nbsp;&nbsp;

{{ item.lecture }}

<span class="badge taken"
style="float:right">

LIVE NOW

</span>

</div>

{% endfor %}

{% else %}

<p>
No lecture is currently running.
</p>

{% endif %}

</div>


<div class="box">

<h2>
📅 Today's Timetable
</h2>

<div class="table-wrapper">

<table>

<tr>
<th>TIME</th>
<th>LECTURE</th>
</tr>

{% for slot in today_slots %}

<tr>

<td>
<strong>{{ slot }}</strong>
</td>

<td>

{% for subject in today_data.get(slot, []) %}

<div style="
background:#eff6ff;
padding:7px;
margin:3px;
border-radius:6px;
">

{{ subject }}

</div>

{% endfor %}

</td>

</tr>

{% endfor %}

</table>

</div>

</div>


<div class="box"
style="text-align:center;background:#111827;color:white">

<h2>
📊 Attendance Reports
</h2>

<p>
Old attendance can be retrieved anytime using date,
faculty, year, day and status filters.
</p>

<a class="btn"
href="/reports">

OPEN REPORTS

</a>

</div>


</div>


<script>

setTimeout(
    function() {
        location.reload();
    },
    30000
);

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

    today = datetime.now().strftime("%A")

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

    next_lecture = get_next_lecture(
        timetable,
        selected_faculty,
        selected_year
    )

    conn = get_db()

    attendance_count = conn.execute(
        "SELECT COUNT(*) AS total FROM attendance"
    ).fetchone()["total"]

    conn.close()

    return render_template_string(
        HOME_PAGE,
        style=BASE_STYLE,
        faculties=FACULTIES,
        years=YEARS,
        selected_faculty=selected_faculty,
        selected_year=selected_year,
        today=today,
        today_data=today_data,
        today_slots=today_slots,
        current_lectures=current_lectures,
        next_lecture=next_lecture,
        attendance_count=attendance_count
    )


# ============================================================
# MASTER TIMETABLE
# ============================================================

MASTER_PAGE = r"""
<!DOCTYPE html>
<html>

<head>

<title>Master Timetable</title>

<meta name="viewport"
content="width=device-width, initial-scale=1">

<style>
{{ style }}
</style>

</head>

<body>

<div class="navbar">

<div class="logo">
🎓 SGB COLLEGE
</div>

<div class="nav">

<a href="/">Home</a>
<a href="/timetable">Timetable</a>
<a href="/attendance">Attendance</a>
<a href="/reports">Reports</a>

</div>

</div>


<div class="container">

<div class="box">

<h1>
📋 Master Class Timetable
</h1>

<button onclick="window.print()">
🖨 Print All
</button>

</div>


{% for faculty in faculties %}

<div class="box">

<h2 style="
background:#172554;
color:white;
padding:15px;
border-radius:8px;
">

{{ faculty }}

</h2>


{% for year in years %}

{% if year in timetable.get(faculty,{}) %}

<h3>
{{ year }}
</h3>

{% set times = get_all_time_slots(
    timetable,
    faculty,
    year
) %}


<div class="table-wrapper">

<table>

<tr>

<th>TIME</th>

{% for day in days %}

<th>{{ day }}</th>

{% endfor %}

</tr>


{% for slot in times %}

<tr>

<td>
<strong>{{ slot }}</strong>
</td>


{% for day in days %}

<td>

{% set subjects = get_subjects(
    timetable,
    faculty,
    year,
    day,
    slot
) %}


{% if subjects %}

{% for subject in subjects %}

<div style="
background:#eff6ff;
padding:7px;
margin:3px;
border-radius:6px;
">

{{ subject }}

</div>

{% endfor %}

{% else %}

—

{% endif %}

</td>

{% endfor %}

</tr>

{% endfor %}

</table>

</div>

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
        style=BASE_STYLE,
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

<meta name="viewport"
content="width=device-width, initial-scale=1">

<style>
{{ style }}
</style>

</head>

<body>

<div class="navbar">

<div class="logo">
🎓 SGB COLLEGE
</div>

<div class="nav">

<a href="/">Home</a>
<a href="/master-timetable">Master</a>
<a href="/attendance">Attendance</a>
<a href="/reports">Reports</a>

</div>

</div>


<div class="container">

<div class="box">

<h1>
📅 Daily Timetable
</h1>

<form method="GET">

<div class="controls">

<div class="control">

<label>Faculty</label>

<select name="faculty">

{% for f in faculties %}

<option
value="{{ f }}"
{% if f == faculty %}
selected
{% endif %}
>

{{ f }}

</option>

{% endfor %}

</select>

</div>


<div class="control">

<label>Year</label>

<select name="year">

{% for y in years %}

<option
value="{{ y }}"
{% if y == year %}
selected
{% endif %}
>

{{ y }}

</option>

{% endfor %}

</select>

</div>


<div class="control">

<label>Day</label>

<select name="day">

{% for d in days %}

<option
value="{{ d }}"
{% if d == selected_day %}
selected
{% endif %}
>

{{ d }}

</option>

{% endfor %}

</select>

</div>


<div style="align-self:end">

<button>
VIEW
</button>

</div>

</div>

</form>

</div>


<div class="box">

<div class="table-wrapper">

<table>

<tr>

<th>TIME</th>

<th>{{ selected_day }}</th>

</tr>


{% for slot in slots %}

<tr>

<td>
<strong>{{ slot }}</strong>
</td>

<td>

{% for subject in data.get(slot,[]) %}

<div style="
background:#eff6ff;
padding:8px;
margin:4px;
border-radius:6px;
">

{{ subject }}

</div>

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
        datetime.now().strftime("%A")
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
        style=BASE_STYLE,
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

<meta name="viewport"
content="width=device-width, initial-scale=1">

<style>
{{ style }}

.login-box {
    max-width:400px;
    margin:80px auto;
}

.error {
    color:#dc2626;
    background:#fee2e2;
    padding:10px;
    border-radius:7px;
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

<div class="error">
{{ message }}
</div>

{% endfor %}

{% endwith %}


<form method="POST">

<label>
Username
</label>

<input
type="text"
name="username"
required
>


<label style="margin-top:10px">
Password
</label>

<input
type="password"
name="password"
required
>


<button
style="width:100%;margin-top:15px"
>

LOGIN

</button>

</form>

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
            and password == ADMIN_PASSWORD
        ):

            session["admin_logged_in"] = True
            session["admin_username"] = username

            next_url = request.args.get(
                "next",
                "/"
            )

            return redirect(next_url)

        flash(
            "Invalid username or password."
        )

    return render_template_string(
        LOGIN_PAGE,
        style=BASE_STYLE
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

<title>Attendance</title>

<meta name="viewport"
content="width=device-width, initial-scale=1">

<style>
{{ style }}

.status-cell {
    min-width:120px;
}

.action-form {
    display:flex;
    gap:5px;
    flex-wrap:wrap;
    justify-content:center;
}

</style>

</head>

<body>

<div class="navbar">

<div class="logo">
☑ SGB ATTENDANCE
</div>

<div class="nav">

<a href="/">Home</a>
<a href="/timetable">Timetable</a>
<a href="/reports">Reports</a>

{% if session.get("admin_logged_in") %}
<a href="/logout">Logout</a>
{% else %}
<a href="/login">Admin Login</a>
{% endif %}

</div>

</div>


<div class="container">


<div class="box">

<h1>
☑ Class Attendance
</h1>

<form method="GET">

<div class="controls">


<div class="control">

<label>Faculty</label>

<select name="faculty">

{% for f in faculties %}

<option
value="{{ f }}"
{% if f == faculty %}
selected
{% endif %}
>

{{ f }}

</option>

{% endfor %}

</select>

</div>


<div class="control">

<label>Year</label>

<select name="year">

{% for y in years %}

<option
value="{{ y }}"
{% if y == year %}
selected
{% endif %}
>

{{ y }}

</option>

{% endfor %}

</select>

</div>


<div class="control">

<label>Day</label>

<select name="day">

{% for d in days %}

<option
value="{{ d }}"
{% if d == selected_day %}
selected
{% endif %}
>

{{ d }}

</option>

{% endfor %}

</select>

</div>


<div style="align-self:end">

<button>
VIEW
</button>

</div>

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
Attendance Date:
<strong>
{{ today }}
</strong>
</p>


{% if not session.get("admin_logged_in") %}

<div style="
background:#fef3c7;
padding:12px;
border-radius:8px;
">

🔐 Login as admin to mark attendance.

<a href="/login?next=/attendance">
Login
</a>

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

<td>
<strong>
{{ item.time }}
</strong>
</td>


<td>

{% for subject in item.subjects %}

<div>
{{ subject }}
</div>

{% endfor %}

</td>


<td class="status-cell">

<span class="badge {{ item.status_class }}">

{{ item.status_text }}

</span>

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
class="btn-green"
>

✓ Taken

</button>


<button
name="status"
value="not_taken"
class="btn-red"
>

✗ Not Taken

</button>


<button
name="status"
value="cancelled"
class="btn-gray"
>

Cancelled

</button>

</form>

{% else %}

<a
class="btn"
href="/login?next=/attendance"
>

LOGIN

</a>

{% endif %}

</td>

</tr>

{% endfor %}

</table>

</div>

</div>


<div class="box"
style="background:#111827;color:white">

<h2>
📊 View Historical Attendance
</h2>

<p>
Use Reports to retrieve attendance from any previous date.
</p>

<a
class="btn"
href="/reports"
>

OPEN REPORTS

</a>

</div>


</div>

</body>

</html>
"""


def status_display(status):

    mapping = {

        "taken": (
            "Taken",
            "taken"
        ),

        "not_taken": (
            "Not Taken",
            "not_taken"
        ),

        "cancelled": (
            "Cancelled",
            "cancelled"
        )

    }

    return mapping.get(
        status,
        ("Not Marked", "not_marked")
    )


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
        datetime.now().strftime("%A")
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

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM attendance
        WHERE attendance_date=?
        AND faculty=?
        AND year=?
        AND day=?
    """, (
        str(date.today()),
        faculty,
        year,
        selected_day
    )).fetchall()

    conn.close()

    status_map = {
        row["time_slot"]: row
        for row in rows
    }

    lectures = []

    for slot in slots:

        subjects = data.get(
            slot,
            []
        )

        db_row = status_map.get(slot)

        if db_row:

            status = db_row["status"]

        else:

            status = "not_marked"

        status_text, status_class = status_display(
            status
        )

        lectures.append({

            "time": slot,

            "subjects": subjects,

            "subject_text": " | ".join(
                subjects
            ),

            "status_text": status_text,

            "status_class": status_class

        })

    return render_template_string(
        ATTENDANCE_PAGE,
        style=BASE_STYLE,
        faculties=FACULTIES,
        years=YEARS,
        days=DAYS,
        faculty=faculty,
        year=year,
        selected_day=selected_day,
        today=str(date.today()),
        lectures=lectures
    )


# ============================================================
# MARK ATTENDANCE
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

    allowed = [
        "taken",
        "not_taken",
        "cancelled"
    ]

    if status not in allowed:
        status = "not_taken"

    if faculty not in FACULTIES:
        return "Invalid faculty", 400

    if year not in YEARS:
        return "Invalid year", 400

    if day not in DAYS:
        return "Invalid day", 400

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    attendance_date = str(date.today())

    conn = get_db()

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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(
            attendance_date,
            faculty,
            year,
            day,
            time_slot
        )

        DO UPDATE SET

            lecture=excluded.lecture,

            status=excluded.status,

            marked_by=excluded.marked_by,

            marked_at=excluded.marked_at
    """, (
        attendance_date,
        faculty,
        year,
        day,
        time_slot,
        lecture,
        status,
        session.get(
            "admin_username",
            "admin"
        ),
        now
    ))

    conn.commit()
    conn.close()

    return redirect(
        url_for(
            "attendance",
            faculty=faculty,
            year=year,
            day=day
        )
    )


# ============================================================
# REPORTS PAGE
# ============================================================

REPORT_PAGE = r"""
<!DOCTYPE html>
<html>

<head>

<title>Attendance Reports</title>

<meta name="viewport"
content="width=device-width, initial-scale=1">

<style>
{{ style }}

.filter-grid {
    display:grid;
    grid-template-columns:
    repeat(4, 1fr);
    gap:10px;
}

@media(max-width:800px) {
    .filter-grid {
        grid-template-columns:1fr 1fr;
    }
}

@media(max-width:500px) {
    .filter-grid {
        grid-template-columns:1fr;
    }
}

</style>

</head>

<body>

<div class="navbar">

<div class="logo">
📊 SGB ATTENDANCE REPORTS
</div>

<div class="nav">

<a href="/">Home</a>
<a href="/attendance">Attendance</a>
<a href="/timetable">Timetable</a>
<a href="/logout">Logout</a>

</div>

</div>


<div class="container">


<div class="hero">

<h1>
📊 Attendance Reports
</h1>

<p>
Retrieve old attendance anytime using filters.
</p>

</div>


<!-- FILTERS -->

<div class="box">

<h2>
🔎 Search / Filter Attendance
</h2>


<form method="GET"
action="/reports">


<div class="filter-grid">


<div>

<label>
From Date
</label>

<input
type="date"
name="from_date"
value="{{ filters.from_date }}"
>

</div>


<div>

<label>
To Date
</label>

<input
type="date"
name="to_date"
value="{{ filters.to_date }}"
>

</div>


<div>

<label>
Faculty
</label>

<select name="faculty">

<option value="">
All Faculties
</option>

{% for f in faculties %}

<option
value="{{ f }}"
{% if filters.faculty == f %}
selected
{% endif %}
>

{{ f }}

</option>

{% endfor %}

</select>

</div>


<div>

<label>
Year
</label>

<select name="year">

<option value="">
All Years
</option>

{% for y in years %}

<option
value="{{ y }}"
{% if filters.year == y %}
selected
{% endif %}
>

{{ y }}

</option>

{% endfor %}

</select>

</div>


<div>

<label>
Day
</label>

<select name="day">

<option value="">
All Days
</option>

{% for d in days %}

<option
value="{{ d }}"
{% if filters.day == d %}
selected
{% endif %}
>

{{ d }}

</option>

{% endfor %}

</select>

</div>


<div>

<label>
Status
</label>

<select name="status">

<option value="">
All Status
</option>

<option value="taken"
{% if filters.status == "taken" %}
selected
{% endif %}
>
Taken
</option>

<option value="not_taken"
{% if filters.status == "not_taken" %}
selected
{% endif %}
>
Not Taken
</option>

<option value="cancelled"
{% if filters.status == "cancelled" %}
selected
{% endif %}
>
Cancelled
</option>

</select>

</div>


<div>

<label>
Search Lecture
</label>

<input
type="text"
name="lecture"
placeholder="Subject / Lecture"
value="{{ filters.lecture }}"
>

</div>


<div style="align-self:end">

<button>
🔎 SEARCH
</button>

</div>


</div>

</form>

</div>


<!-- STATISTICS -->

<div class="cards">

<div class="stat">

<div class="stat-title">
TAKEN
</div>

<div class="stat-number success">
{{ stats.taken }}
</div>

</div>


<div class="stat">

<div class="stat-title">
NOT TAKEN
</div>

<div class="stat-number danger">
{{ stats.not_taken }}
</div>

</div>


<div class="stat">

<div class="stat-title">
CANCELLED
</div>

<div class="stat-number orange">
{{ stats.cancelled }}
</div>

</div>


<div class="stat">

<div class="stat-title">
ATTENDANCE %
</div>

<div class="stat-number blue">
{{ stats.percentage }}%
</div>

</div>

</div>


<!-- SUMMARY -->

<div class="box">

<h2>
📈 Summary — Row / Column Format
</h2>


<div class="table-wrapper">

<table>

<tr>

<th>Faculty</th>
<th>Year</th>
<th>Taken</th>
<th>Not Taken</th>
<th>Cancelled</th>
<th>Total</th>
<th>Attendance %</th>

</tr>


{% for row in summary %}

<tr>

<td>
{{ row.faculty }}
</td>

<td>
{{ row.year }}
</td>

<td class="success">
<strong>
{{ row.taken }}
</strong>
</td>

<td class="danger">
<strong>
{{ row.not_taken }}
</strong>
</td>

<td class="orange">
<strong>
{{ row.cancelled }}
</strong>
</td>

<td>
{{ row.total }}
</td>

<td>

<strong>

{{ row.percentage }}%

</strong>

</td>

</tr>

{% else %}

<tr>

<td colspan="7">
No attendance data found.
</td>

</tr>

{% endfor %}

</table>

</div>

</div>


<!-- DAY SUMMARY -->

<div class="box">

<h2>
📅 Day-wise Summary
</h2>


<div class="table-wrapper">

<table>

<tr>

<th>Date</th>
<th>Day</th>
<th>Faculty</th>
<th>Year</th>
<th>Taken</th>
<th>Not Taken</th>
<th>Cancelled</th>
<th>Total</th>
<th>%</th>

</tr>


{% for row in day_summary %}

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

<td class="success">
{{ row.taken }}
</td>

<td class="danger">
{{ row.not_taken }}
</td>

<td class="orange">
{{ row.cancelled }}
</td>

<td>
{{ row.total }}
</td>

<td>
<strong>
{{ row.percentage }}%
</strong>
</td>

</tr>

{% else %}

<tr>
<td colspan="9">
No data found.
</td>
</tr>

{% endfor %}

</table>

</div>

</div>


<!-- DETAILED RECORD -->

<div class="box">

<div style="
display:flex;
justify-content:space-between;
gap:10px;
align-items:center;
flex-wrap:wrap;
">

<h2>
📋 Detailed Attendance Records
</h2>


<a
class="btn btn-green"
href="{{ csv_url }}"
>

⬇ Export CSV

</a>

</div>


<div class="table-wrapper">

<table>

<tr>

<th>ID</th>
<th>Date</th>
<th>Faculty</th>
<th>Year</th>
<th>Day</th>
<th>Time</th>
<th>Lecture</th>
<th>Status</th>
<th>Marked By</th>
<th>Marked At</th>

</tr>


{% for row in records %}

<tr>

<td>
{{ row.id }}
</td>

<td>
{{ row.attendance_date }}
</td>

<td>
{{ row.faculty }}
</td>

<td>
{{ row.year }}
</td>

<td>
{{ row.day }}
</td>

<td>
{{ row.time_slot }}
</td>

<td style="text-align:left">
{{ row.lecture }}
</td>

<td>

<span class="badge
{% if row.status == 'taken' %}
taken
{% elif row.status == 'not_taken' %}
not_taken
{% else %}
cancelled
{% endif %}
">

{{ row.status|replace("_"," ")|title }}

</span>

</td>

<td>
{{ row.marked_by }}
</td>

<td>
{{ row.marked_at }}
</td>

</tr>

{% else %}

<tr>

<td colspan="10">
No attendance records found.
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


def build_report_filters():

    return {

        "from_date": request.args.get(
            "from_date",
            ""
        ).strip(),

        "to_date": request.args.get(
            "to_date",
            ""
        ).strip(),

        "faculty": request.args.get(
            "faculty",
            ""
        ).strip(),

        "year": request.args.get(
            "year",
            ""
        ).strip(),

        "day": request.args.get(
            "day",
            ""
        ).strip(),

        "status": request.args.get(
            "status",
            ""
        ).strip(),

        "lecture": request.args.get(
            "lecture",
            ""
        ).strip()

    }


def create_where_clause(filters):

    conditions = []
    params = []

    if filters["from_date"]:

        conditions.append(
            "attendance_date >= ?"
        )

        params.append(
            filters["from_date"]
        )

    if filters["to_date"]:

        conditions.append(
            "attendance_date <= ?"
        )

        params.append(
            filters["to_date"]
        )

    if filters["faculty"]:

        conditions.append(
            "faculty = ?"
        )

        params.append(
            filters["faculty"]
        )

    if filters["year"]:

        conditions.append(
            "year = ?"
        )

        params.append(
            filters["year"]
        )

    if filters["day"]:

        conditions.append(
            "day = ?"
        )

        params.append(
            filters["day"]
        )

    if filters["status"]:

        conditions.append(
            "status = ?"
        )

        params.append(
            filters["status"]
        )

    if filters["lecture"]:

        conditions.append(
            "lecture LIKE ?"
        )

        params.append(
            "%" + filters["lecture"] + "%"
        )

    if conditions:

        where = "WHERE " + " AND ".join(
            conditions
        )

    else:

        where = ""

    return where, params


def calculate_percentage(
    taken,
    not_taken
):

    total = taken + not_taken

    if total == 0:
        return 0.0

    return round(
        (taken / total) * 100,
        2
    )


@app.route("/reports")
@admin_required
def reports():

    filters = build_report_filters()

    where, params = create_where_clause(
        filters
    )

    conn = get_db()


    # --------------------------------------------------------
    # Detailed records
    # --------------------------------------------------------

    records = conn.execute(
        f"""
        SELECT *
        FROM attendance
        {where}
        ORDER BY
            attendance_date DESC,
            faculty,
            year,
            day,
            id DESC
        LIMIT 5000
        """,
        params
    ).fetchall()


    # --------------------------------------------------------
    # Overall summary
    # --------------------------------------------------------

    summary_rows = conn.execute(
        f"""
        SELECT

            faculty,

            year,

            SUM(
                CASE
                    WHEN status='taken'
                    THEN 1
                    ELSE 0
                END
            ) AS taken,

            SUM(
                CASE
                    WHEN status='not_taken'
                    THEN 1
                    ELSE 0
                END
            ) AS not_taken,

            SUM(
                CASE
                    WHEN status='cancelled'
                    THEN 1
                    ELSE 0
                END
            ) AS cancelled,

            COUNT(*) AS total

        FROM attendance

        {where}

        GROUP BY faculty, year

        ORDER BY faculty, year
        """,
        params
    ).fetchall()


    summary = []

    for row in summary_rows:

        taken = row["taken"] or 0
        not_taken = row["not_taken"] or 0
        cancelled = row["cancelled"] or 0

        summary.append({

            "faculty": row["faculty"],

            "year": row["year"],

            "taken": taken,

            "not_taken": not_taken,

            "cancelled": cancelled,

            "total": row["total"],

            "percentage":
                calculate_percentage(
                    taken,
                    not_taken
                )

        })


    # --------------------------------------------------------
    # Day-wise summary
    # --------------------------------------------------------

    day_rows = conn.execute(
        f"""
        SELECT

            attendance_date,

            day,

            faculty,

            year,

            SUM(
                CASE
                    WHEN status='taken'
                    THEN 1
                    ELSE 0
                END
            ) AS taken,

            SUM(
                CASE
                    WHEN status='not_taken'
                    THEN 1
                    ELSE 0
                END
            ) AS not_taken,

            SUM(
                CASE
                    WHEN status='cancelled'
                    THEN 1
                    ELSE 0
                END
            ) AS cancelled,

            COUNT(*) AS total

        FROM attendance

        {where}

        GROUP BY
            attendance_date,
            day,
            faculty,
            year

        ORDER BY
            attendance_date DESC,
            faculty,
            year
        """,
        params
    ).fetchall()


    day_summary = []

    for row in day_rows:

        taken = row["taken"] or 0
        not_taken = row["not_taken"] or 0

        day_summary.append({

            "attendance_date":
                row["attendance_date"],

            "day":
                row["day"],

            "faculty":
                row["faculty"],

            "year":
                row["year"],

            "taken":
                taken,

            "not_taken":
                not_taken,

            "cancelled":
                row["cancelled"] or 0,

            "total":
                row["total"],

            "percentage":
                calculate_percentage(
                    taken,
                    not_taken
                )

        })


    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    stats_row = conn.execute(
        f"""
        SELECT

            SUM(
                CASE
                    WHEN status='taken'
                    THEN 1
                    ELSE 0
                END
            ) AS taken,

            SUM(
                CASE
                    WHEN status='not_taken'
                    THEN 1
                    ELSE 0
                END
            ) AS not_taken,

            SUM(
                CASE
                    WHEN status='cancelled'
                    THEN 1
                    ELSE 0
                END
            ) AS cancelled

        FROM attendance

        {where}
        """,
        params
    ).fetchone()


    taken = stats_row["taken"] or 0
    not_taken = stats_row["not_taken"] or 0
    cancelled = stats_row["cancelled"] or 0

    percentage = calculate_percentage(
        taken,
        not_taken
    )


    conn.close()


    # --------------------------------------------------------
    # CSV URL
    # --------------------------------------------------------

    query_string = request.query_string.decode(
        "utf-8"
    )

    csv_url = (
        "/reports/export.csv"
    )

    if query_string:
        csv_url += "?" + query_string


    return render_template_string(

        REPORT_PAGE,

        style=BASE_STYLE,

        faculties=FACULTIES,

        years=YEARS,

        days=DAYS,

        filters=filters,

        records=records,

        summary=summary,

        day_summary=day_summary,

        stats={

            "taken": taken,

            "not_taken": not_taken,

            "cancelled": cancelled,

            "percentage": percentage

        },

        csv_url=csv_url

    )


# ============================================================
# CSV EXPORT
# ============================================================

@app.route("/reports/export.csv")
@admin_required
def export_csv():

    filters = build_report_filters()

    where, params = create_where_clause(
        filters
    )

    conn = get_db()

    records = conn.execute(
        f"""
        SELECT *
        FROM attendance
        {where}
        ORDER BY
            attendance_date DESC,
            faculty,
            year,
            day,
            time_slot
        """,
        params
    ).fetchall()

    conn.close()


    output = io.StringIO()

    writer = csv.writer(
        output
    )

    writer.writerow([
        "ID",
        "Date",
        "Faculty",
        "Year",
        "Day",
        "Time Slot",
        "Lecture",
        "Status",
        "Marked By",
        "Marked At"
    ])


    for row in records:

        writer.writerow([

            row["id"],

            row["attendance_date"],

            row["faculty"],

            row["year"],

            row["day"],

            row["time_slot"],

            row["lecture"],

            row["status"],

            row["marked_by"],

            row["marked_at"]

        ])


    filename = (
        "attendance_report_"
        + datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )
        + ".csv"
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
