import os
import csv
import io
import json
import sqlite3
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

# ============================================================
# APP CONFIG
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key"
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

STATUSES = [
    "taken",
    "not_taken",
    "cancelled"
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

        print("Timetable loading error:", error)

        return {}


def get_subjects(
    timetable,
    faculty,
    year,
    day,
    time_slot
):

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


# ============================================================
# TIME FUNCTIONS
# ============================================================

def time_to_minutes(value):

    try:

        h, m = map(
            int,
            value.strip().split(":")
        )

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
# AUTHENTICATION
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
# COMMON HTML
# ============================================================

BASE_STYLE = """

* {
    box-sizing:border-box;
}

body {
    margin:0;
    font-family:Arial,sans-serif;
    background:#f1f5f9;
    color:#1e293b;
}

.navbar {
    background:#111827;
    color:white;
    padding:15px 25px;
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:20px;
    flex-wrap:wrap;
}

.logo {
    font-size:20px;
    font-weight:bold;
}

.nav {
    display:flex;
    gap:12px;
    flex-wrap:wrap;
}

.nav a {
    color:white;
    text-decoration:none;
    padding:8px 10px;
    border-radius:7px;
}

.nav a:hover {
    background:#374151;
}

.container {
    max-width:1250px;
    margin:auto;
    padding:20px;
}

.hero {
    background:linear-gradient(135deg,#2563eb,#7c3aed);
    color:white;
    padding:30px;
    border-radius:18px;
    margin-bottom:20px;
}

.box {
    background:white;
    padding:20px;
    border-radius:14px;
    margin-bottom:20px;
    box-shadow:0 3px 12px rgba(0,0,0,.05);
}

.controls {
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
    gap:12px;
}

label {
    display:block;
    font-weight:bold;
    margin-bottom:6px;
}

input,
select {
    width:100%;
    padding:11px;
    border:1px solid #cbd5e1;
    border-radius:8px;
    font-size:14px;
}

button,
.btn {
    display:inline-block;
    border:0;
    padding:11px 16px;
    border-radius:8px;
    cursor:pointer;
    color:white;
    background:#2563eb;
    text-decoration:none;
    font-weight:bold;
}

.btn-green {
    background:#16a34a;
}

.btn-dark {
    background:#111827;
}

.btn-red {
    background:#dc2626;
}

.btn-gray {
    background:#64748b;
}

.actions {
    display:flex;
    gap:8px;
    flex-wrap:wrap;
    margin-top:15px;
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
    white-space:nowrap;
}

td {
    padding:10px;
    border:1px solid #dbe3ee;
    text-align:center;
}

.badge {
    display:inline-block;
    padding:6px 10px;
    border-radius:20px;
    font-size:12px;
    font-weight:bold;
}

.taken {
    background:#dcfce7;
    color:#166534;
}

.not_taken {
    background:#fee2e2;
    color:#991b1b;
}

.cancelled {
    background:#e2e8f0;
    color:#334155;
}

.stat-grid {
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
    gap:15px;
}

.stat {
    background:white;
    padding:20px;
    border-radius:13px;
    box-shadow:0 3px 12px rgba(0,0,0,.05);
}

.stat-number {
    font-size:28px;
    font-weight:bold;
    margin-top:7px;
}

.success {
    color:#16a34a;
}

.danger {
    color:#dc2626;
}

.info {
    color:#2563eb;
}

@media(max-width:700px) {

    .navbar {
        align-items:flex-start;
        flex-direction:column;
    }

    .container {
        padding:12px;
    }

    .hero {
        padding:22px;
    }
}

@media print {

    .navbar,
    .no-print,
    .actions,
    form {
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


NAVBAR = """
<div class="navbar">

    <div class="logo">
        🎓 SGB COLLEGE
    </div>

    <div class="nav">

        <a href="/">Home</a>

        <a href="/timetable">Timetable</a>

        <a href="/master-timetable">Master</a>

        <a href="/attendance">Attendance</a>

        <a href="/reports">Reports</a>

        {% if session.get("admin_logged_in") %}
            <a href="/logout">Logout</a>
        {% else %}
            <a href="/login">Login</a>
        {% endif %}

    </div>

</div>
"""


# ============================================================
# HOME
# ============================================================

HOME_PAGE = """
<!DOCTYPE html>
<html>
<head>

<title>SGB College Management</title>

<meta name="viewport"
content="width=device-width,initial-scale=1">

<style>
{{ style }}
</style>

</head>

<body>

{{ navbar|safe }}

<div class="container">

<div class="hero">

<h1>🎓 SGB College Management System</h1>

<p>
Timetable • Attendance • Reports
</p>

</div>

<div class="box">

<form method="GET">

<div class="controls">

<div>

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

<div>

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

</div>

<div class="actions">

<button>
VIEW
</button>

</div>

</form>

</div>


<div class="stat-grid">

<div class="stat">

<div>Current Lecture</div>

<div class="stat-number success">

{% if current_lectures %}
LIVE
{% else %}
—
{% endif %}

</div>

</div>


<div class="stat">

<div>Next Lecture</div>

<div class="stat-number info">

{% if next_lecture %}
{{ next_lecture.time }}
{% else %}
—
{% endif %}

</div>

</div>


<div class="stat">

<div>Today</div>

<div class="stat-number">
{{ today }}
</div>

</div>

</div>


<div class="box">

<h2>🟢 Current Lecture</h2>

{% if current_lectures %}

{% for item in current_lectures %}

<div style="
padding:15px;
background:#dcfce7;
border-left:5px solid #16a34a;
margin:8px 0;
border-radius:8px;
">

<strong>{{ item.time }}</strong>

&nbsp;&nbsp;

{{ item.lecture }}

</div>

{% endfor %}

{% else %}

<p>No lecture is currently running.</p>

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

<tr>

<td>
<strong>{{ slot }}</strong>
</td>

<td>

{% for subject in today_data.get(slot,[]) %}

<div style="
padding:7px;
background:#eff6ff;
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

</div>

<script>

setTimeout(function(){
    location.reload();
},30000);

</script>

</body>
</html>
"""


@app.route("/")
def home():

    timetable = load_timetable()

    faculty = request.args.get(
        "faculty",
        "Science"
    )

    year = request.args.get(
        "year",
        "1st Year"
    )

    if faculty not in FACULTIES:
        faculty = "Science"

    if year not in YEARS:
        year = "1st Year"

    today = datetime.now().strftime("%A")

    today_data = (
        timetable
        .get(faculty,{})
        .get(year,{})
        .get(today,{})
    )

    today_slots = sorted(
        today_data.keys(),
        key=time_sort_key
    )

    current_lectures = []

    for slot in today_slots:

        if is_current_slot(slot):

            for subject in today_data.get(slot,[]):

                current_lectures.append({
                    "time":slot,
                    "lecture":subject
                })

    next_lecture = get_next_lecture(
        timetable,
        faculty,
        year
    )

    return render_template_string(
        HOME_PAGE,
        style=BASE_STYLE,
        navbar=NAVBAR,
        faculties=FACULTIES,
        years=YEARS,
        selected_faculty=faculty,
        selected_year=year,
        today=today,
        today_data=today_data,
        today_slots=today_slots,
        current_lectures=current_lectures,
        next_lecture=next_lecture
    )


# ============================================================
# NEXT LECTURE
# ============================================================

def get_next_lecture(
    timetable,
    faculty,
    year
):

    today = datetime.now().strftime("%A")

    now = current_time_minutes()

    day_data = (
        timetable
        .get(faculty,{})
        .get(year,{})
        .get(today,{})
    )

    possible = []

    for slot in day_data:

        start, end = parse_time_range(slot)

        if start is not None and start > now:

            possible.append(
                (start,slot)
            )

    possible.sort()

    if not possible:
        return None

    slot = possible[0][1]

    return {
        "time":slot,
        "lectures":day_data.get(slot,[])
    }


# ============================================================
# DAILY TIMETABLE
# ============================================================

TIMETABLE_PAGE = """
<!DOCTYPE html>
<html>

<head>

<title>Timetable</title>

<meta name="viewport"
content="width=device-width,initial-scale=1">

<style>
{{ style }}
</style>

</head>

<body>

{{ navbar|safe }}

<div class="container">

<div class="box">

<h1>📅 Daily Timetable</h1>

<form method="GET">

<div class="controls">

<div>

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


<div>

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


<div>

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

</div>

<div class="actions">

<button>VIEW TIMETABLE</button>

</div>

</form>

</div>


<div class="box">

<h2>
{{ faculty }} — {{ year }} — {{ selected_day }}
</h2>

<div class="table-wrapper">

<table>

<tr>

<th>TIME</th>

<th>LECTURE</th>

</tr>

{% for slot in slots %}

<tr>

<td>
<strong>{{ slot }}</strong>
</td>

<td>

{% for subject in data.get(slot,[]) %}

<div style="
padding:8px;
background:#eff6ff;
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
        .get(faculty,{})
        .get(year,{})
        .get(selected_day,{})
    )

    slots = sorted(
        data.keys(),
        key=time_sort_key
    )

    return render_template_string(
        TIMETABLE_PAGE,
        style=BASE_STYLE,
        navbar=NAVBAR,
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
# MASTER TIMETABLE
# ============================================================

MASTER_PAGE = """
<!DOCTYPE html>
<html>

<head>

<title>Master Timetable</title>

<meta name="viewport"
content="width=device-width,initial-scale=1">

<style>
{{ style }}
</style>

</head>

<body>

{{ navbar|safe }}

<div class="container">

<div class="box">

<div class="actions no-print">

<a class="btn btn-gray" href="/">
← Home
</a>

<button onclick="window.print()"
class="btn btn-green">

🖨 Print

</button>

</div>

<h1>📚 Master Class Timetable</h1>

</div>


{% for faculty in faculties %}

<div class="box">

<h2>🏫 {{ faculty }}</h2>

{% for year in years %}

{% if year in timetable.get(faculty,{}) %}

<h3>{{ year }}</h3>

{% set year_data = timetable.get(faculty,{}).get(year,{}) %}

{% set slots = [] %}

{% for day in days %}

{% for slot in year_data.get(day,{}) %}

{% if slot not in slots %}

{% set _ = slots.append(slot) %}

{% endif %}

{% endfor %}

{% endfor %}

{% set slots = slots|sort %}

<div class="table-wrapper">

<table>

<tr>

<th>TIME</th>

{% for day in days %}

<th>{{ day }}</th>

{% endfor %}

</tr>

{% for slot in slots %}

<tr>

<td>
<strong>{{ slot }}</strong>
</td>

{% for day in days %}

<td>

{% for subject in get_subjects(
    timetable,
    faculty,
    year,
    day,
    slot
) %}

<div style="
padding:7px;
background:#eff6ff;
margin:3px;
border-radius:6px;
">

{{ subject }}

</div>

{% else %}

<span style="color:#94a3b8">—</span>

{% endfor %}

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
        navbar=NAVBAR,
        timetable=timetable,
        faculties=FACULTIES,
        years=YEARS,
        days=DAYS,
        get_subjects=get_subjects
    )


# ============================================================
# LOGIN
# ============================================================

LOGIN_PAGE = """
<!DOCTYPE html>
<html>

<head>

<title>Admin Login</title>

<meta name="viewport"
content="width=device-width,initial-scale=1">

<style>

{{ style }}

.login {
    max-width:420px;
    margin:80px auto;
}

.error {
    background:#fee2e2;
    color:#991b1b;
    padding:10px;
    border-radius:8px;
}

</style>

</head>

<body>

<div class="container">

<div class="box login">

<h1>🔐 Admin Login</h1>

{% with messages = get_flashed_messages() %}

{% for message in messages %}

<div class="error">
{{ message }}
</div>

{% endfor %}

{% endwith %}

<form method="POST">

<div style="margin-top:15px">

<label>Username</label>

<input
name="username"
required
>

</div>

<div style="margin-top:15px">

<label>Password</label>

<input
type="password"
name="password"
required
>

</div>

<div class="actions">

<button>
LOGIN
</button>

</div>

</form>

</div>

</div>

</body>

</html>
"""


@app.route(
    "/login",
    methods=["GET","POST"]
)
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        )

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

        flash("Invalid username or password.")

    return render_template_string(
        LOGIN_PAGE,
        style=BASE_STYLE
    )


@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# ============================================================
# ATTENDANCE
# ============================================================

ATTENDANCE_PAGE = """
<!DOCTYPE html>
<html>

<head>

<title>Attendance</title>

<meta name="viewport"
content="width=device-width,initial-scale=1">

<style>
{{ style }}
</style>

</head>

<body>

{{ navbar|safe }}

<div class="container">

<div class="box">

<h1>☑ Attendance</h1>

<form method="GET">

<div class="controls">

<div>

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


<div>

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


<div>

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

</div>

<div class="actions">

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

{% if not session.get("admin_logged_in") %}

<p style="
background:#fff7ed;
padding:12px;
border-radius:8px;
">

🔐 Login as admin to mark attendance.

<a href="/login">Login</a>

</p>

{% endif %}


<div class="table-wrapper">

<table>

<tr>

<th>TIME</th>

<th>LECTURE</th>

<th>STATUS</th>

<th class="no-print">ACTION</th>

</tr>

{% for item in lectures %}

<tr>

<td>
<strong>{{ item.time }}</strong>
</td>

<td>

{% for subject in item.subjects %}

<div>{{ subject }}</div>

{% endfor %}

</td>

<td>

<span class="badge {{ item.status }}">

{{ item.status.replace("_"," ").upper() }}

</span>

</td>

<td class="no-print">

{% if session.get("admin_logged_in") %}

<form method="POST"
action="/attendance/mark">

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

<div class="actions">

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

</div>

</form>

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
        .get(faculty,{})
        .get(year,{})
        .get(selected_day,{})
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
        row["time_slot"]:row["status"]
        for row in rows
    }

    lectures = []

    for slot in slots:

        subjects = data.get(slot,[])

        lectures.append({

            "time":slot,

            "subjects":subjects,

            "subject_text":" | ".join(subjects),

            "status":status_map.get(
                slot,
                "not_marked"
            )

        })

    return render_template_string(
        ATTENDANCE_PAGE,
        style=BASE_STYLE,
        navbar=NAVBAR,
        faculties=FACULTIES,
        years=YEARS,
        days=DAYS,
        faculty=faculty,
        year=year,
        selected_day=selected_day,
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

    faculty = request.form.get("faculty","")
    year = request.form.get("year","")
    day = request.form.get("day","")
    time_slot = request.form.get("time_slot","")
    lecture = request.form.get("lecture","")
    status = request.form.get("status","")

    if faculty not in FACULTIES:
        return "Invalid faculty",400

    if year not in YEARS:
        return "Invalid year",400

    if day not in DAYS:
        return "Invalid day",400

    if status not in STATUSES:
        return "Invalid status",400

    today = str(date.today())

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = get_db()

    conn.execute("""
        INSERT INTO attendance (
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
        VALUES (?,?,?,?,?,?,?,?,?)

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
        today,
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
# REPORTS
# ============================================================

REPORT_PAGE = """
<!DOCTYPE html>
<html>

<head>

<title>Attendance Reports</title>

<meta name="viewport"
content="width=device-width,initial-scale=1">

<style>
{{ style }}
</style>

</head>

<body>

{{ navbar|safe }}

<div class="container">

<div class="box no-print">

<h1>📊 Attendance Reports</h1>

<form method="GET"
action="/reports">

<div class="controls">

<div>

<label>From Date</label>

<input
type="date"
name="from_date"
value="{{ from_date }}"
>

</div>


<div>

<label>To Date</label>

<input
type="date"
name="to_date"
value="{{ to_date }}"
>

</div>


<div>

<label>Faculty</label>

<select name="faculty">

<option value="">All Faculties</option>

{% for f in faculties %}

<option value="{{ f }}"
{% if f == faculty %}selected{% endif %}>

{{ f }}

</option>

{% endfor %}

</select>

</div>


<div>

<label>Year</label>

<select name="year">

<option value="">All Years</option>

{% for y in years %}

<option value="{{ y }}"
{% if y == year %}selected{% endif %}>

{{ y }}

</option>

{% endfor %}

</select>

</div>


<div>

<label>Day</label>

<select name="day">

<option value="">All Days</option>

{% for d in days %}

<option value="{{ d }}"
{% if d == day %}selected{% endif %}>

{{ d }}

</option>

{% endfor %}

</select>

</div>


<div>

<label>Status</label>

<select name="status">

<option value="">All Status</option>

<option value="taken"
{% if status == "taken" %}selected{% endif %}>
Taken
</option>

<option value="not_taken"
{% if status == "not_taken" %}selected{% endif %}>
Not Taken
</option>

<option value="cancelled"
{% if status == "cancelled" %}selected{% endif %}>
Cancelled
</option>

</select>

</div>

</div>


<div class="actions">

<button>
🔎 SEARCH REPORT
</button>

<a
class="btn btn-green"
href="{{ csv_url }}"
>
📥 CSV
</a>

<button
type="button"
class="btn btn-dark"
onclick="window.print()"
>
🖨 Print
</button>

</div>

</form>

</div>


<div class="stat-grid">

<div class="stat">

<div>Total Records</div>

<div class="stat-number info">
{{ total }}
</div>

</div>


<div class="stat">

<div>Taken</div>

<div class="stat-number success">
{{ taken }}
</div>

</div>


<div class="stat">

<div>Not Taken</div>

<div class="stat-number danger">
{{ not_taken }}
</div>

</div>


<div class="stat">

<div>Cancelled</div>

<div class="stat-number">
{{ cancelled }}
</div>

</div>


<div class="stat">

<div>Attendance %</div>

<div class="stat-number success">
{{ percentage }}%
</div>

</div>

</div>


<div class="box">

<h2>📋 Summary</h2>

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

<td>{{ row.faculty }}</td>

<td>{{ row.year }}</td>

<td class="success">
{{ row.taken }}
</td>

<td class="danger">
{{ row.not_taken }}
</td>

<td>
{{ row.cancelled }}
</td>

<td>
{{ row.total }}
</td>

<td>
<strong>{{ row.percentage }}%</strong>
</td>

</tr>

{% endfor %}

</table>

</div>

</div>


<div class="box">

<h2>
📑 Detailed Attendance Records
</h2>

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

<td>{{ row.id }}</td>

<td>{{ row.attendance_date }}</td>

<td>{{ row.faculty }}</td>

<td>{{ row.year }}</td>

<td>{{ row.day }}</td>

<td>{{ row.time_slot }}</td>

<td style="text-align:left">
{{ row.lecture }}
</td>

<td>

<span class="badge {{ row.status }}">

{{ row.status.replace("_"," ").upper() }}

</span>

</td>

<td>{{ row.marked_by }}</td>

<td>{{ row.marked_at }}</td>

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


def build_report_query():

    conditions = []
    params = []

    from_date = request.args.get(
        "from_date",
        ""
    ).strip()

    to_date = request.args.get(
        "to_date",
        ""
    ).strip()

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

    status = request.args.get(
        "status",
        ""
    ).strip()

    if from_date:

        conditions.append(
            "attendance_date >= ?"
        )

        params.append(from_date)

    if to_date:

        conditions.append(
            "attendance_date <= ?"
        )

        params.append(to_date)

    if faculty:

        conditions.append(
            "faculty = ?"
        )

        params.append(faculty)

    if year:

        conditions.append(
            "year = ?"
        )

        params.append(year)

    if day:

        conditions.append(
            "day = ?"
        )

        params.append(day)

    if status:

        conditions.append(
            "status = ?"
        )

        params.append(status)

    if conditions:

        where = "WHERE " + " AND ".join(
            conditions
        )

    else:

        where = ""

    return (
        where,
        params,
        from_date,
        to_date,
        faculty,
        year,
        day,
        status
    )


@app.route("/reports")
@admin_required
def reports():

    (
        where,
        params,
        from_date,
        to_date,
        faculty,
        year,
        day,
        status
    ) = build_report_query()

    conn = get_db()

    records = conn.execute(
        f"""
        SELECT *
        FROM attendance
        {where}
        ORDER BY attendance_date DESC, id DESC
        """,
        params
    ).fetchall()

    summary = conn.execute(
        f"""
        SELECT

            faculty,

            year,

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
            ) AS cancelled,

            COUNT(*) AS total

        FROM attendance

        {where}

        GROUP BY faculty, year

        ORDER BY faculty, year
        """,
        params
    ).fetchall()

    conn.close()

    total = len(records)

    taken = sum(
        1 for row in records
        if row["status"] == "taken"
    )

    not_taken = sum(
        1 for row in records
        if row["status"] == "not_taken"
    )

    cancelled = sum(
        1 for row in records
        if row["status"] == "cancelled"
    )

    percentage = (
        round(
            taken /
            (taken + not_taken) *
            100,
            2
        )
        if (taken + not_taken) > 0
        else 0
    )

    summary_data = []

    for row in summary:

        denominator = (
            row["taken"] +
            row["not_taken"]
        )

        row_percentage = (
            round(
                row["taken"] /
                denominator *
                100,
                2
            )
            if denominator > 0
            else 0
        )

        summary_data.append({

            "faculty":row["faculty"],

            "year":row["year"],

            "taken":row["taken"],

            "not_taken":row["not_taken"],

            "cancelled":row["cancelled"],

            "total":row["total"],

            "percentage":row_percentage

        })

    query_string = request.query_string.decode()

    csv_url = "/reports/csv"

    if query_string:

        csv_url += "?" + query_string

    return render_template_string(
        REPORT_PAGE,
        style=BASE_STYLE,
        navbar=NAVBAR,
        faculties=FACULTIES,
        years=YEARS,
        days=DAYS,
        from_date=from_date,
        to_date=to_date,
        faculty=faculty,
        year=year,
        day=day,
        status=status,
        records=records,
        summary=summary_data,
        total=total,
        taken=taken,
        not_taken=not_taken,
        cancelled=cancelled,
        percentage=percentage,
        csv_url=csv_url
    )


# ============================================================
# CSV EXPORT
# ============================================================

@app.route("/reports/csv")
@admin_required
def reports_csv():

    (
        where,
        params,
        from_date,
        to_date,
        faculty,
        year,
        day,
        status
    ) = build_report_query()

    conn = get_db()

    records = conn.execute(
        f"""
        SELECT *
        FROM attendance
        {where}
        ORDER BY attendance_date DESC, id DESC
        """,
        params
    ).fetchall()

    conn.close()

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow([
        "ID",
        "Date",
        "Faculty",
        "Year",
        "Day",
        "Time",
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
# DELETE ALL DATA - OPTIONAL ADMIN TOOL
# ============================================================

@app.route(
    "/attendance/delete/<int:record_id>",
    methods=["POST"]
)
@admin_required
def delete_attendance(record_id):

    conn = get_db()

    conn.execute(
        "DELETE FROM attendance WHERE id=?",
        (record_id,)
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("reports")
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return "OK"


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):

    return """
    <h1>404</h1>
    <p>Page not found.</p>
    <a href="/">Go Home</a>
    """,404


@app.errorhandler(500)
def server_error(error):

    return """
    <h1>500</h1>
    <p>Internal server error.</p>
    <a href="/">Go Home</a>
    """,500


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
