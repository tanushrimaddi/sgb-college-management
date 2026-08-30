import os
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
    flash
)


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
# LOAD TIMETABLE
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

            marked_at TEXT
        )
    """)

    conn.commit()

    conn.close()


init_db()


# ============================================================
# LOGIN DECORATOR
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

        h, m = map(
            int,
            value.strip().split(":")
        )

        return h * 60 + m

    except:

        return 9999


def time_sort_key(value):

    try:

        start = value.split("-")[0].strip()

        return time_to_minutes(start)

    except:

        return 9999


def parse_time_range(value):

    try:

        start, end = value.split("-")

        return (
            time_to_minutes(start),
            time_to_minutes(end)
        )

    except:

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

    except:

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
# CURRENT LECTURE
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

    subjects = day_data.get(
        slot,
        []
    )

    return {
        "time": slot,
        "lectures": subjects
    }


# ============================================================
# HOME PAGE
# ============================================================

HOME_PAGE = r"""
<!DOCTYPE html>
<html>

<head>

<title>SGB College Management</title>

<meta
name="viewport"
content="width=device-width, initial-scale=1.0"
>

<style>

* {
    box-sizing:border-box;
}

body {
    margin:0;
    font-family:Arial, sans-serif;
    background:#f4f6fb;
    color:#1e293b;
}


/* NAVBAR */

.navbar {

    background:#111827;

    color:white;

    padding:15px 30px;

    display:flex;

    align-items:center;

    justify-content:space-between;

    gap:20px;

}

.logo {

    font-size:21px;

    font-weight:bold;

}

.logo small {

    display:block;

    font-size:10px;

    opacity:.7;

    margin-top:3px;

}

.nav {

    display:flex;

    gap:25px;

    flex-wrap:wrap;

}

.nav a {

    color:white;

    text-decoration:none;

    font-size:14px;

}


/* HERO */

.container {

    max-width:1200px;

    margin:auto;

    padding:25px 18px;

}

.hero {

    background:
    linear-gradient(
        135deg,
        #2563eb,
        #7c3aed
    );

    color:white;

    padding:30px;

    border-radius:20px;

    margin-bottom:22px;

}

.hero h1 {

    margin:0;

    font-size:31px;

}

.hero p {

    margin-bottom:0;

    opacity:.9;

}


/* SELECT */

.select-box {

    background:white;

    padding:20px;

    border-radius:15px;

    box-shadow:
    0 4px 15px rgba(0,0,0,.06);

    display:flex;

    gap:15px;

    flex-wrap:wrap;

}

.select-group {

    flex:1;

    min-width:220px;

}

label {

    display:block;

    font-weight:bold;

    margin-bottom:7px;

}

select {

    width:100%;

    padding:12px;

    border:
    1px solid #d1d5db;

    border-radius:9px;

    font-size:15px;

}


/* CARDS */

.cards {

    display:grid;

    grid-template-columns:
    repeat(
        3,
        1fr
    );

    gap:18px;

    margin-top:20px;

}

.card {

    background:white;

    padding:20px;

    border-radius:15px;

    box-shadow:
    0 4px 15px rgba(0,0,0,.06);

}

.card-title {

    font-size:13px;

    color:#64748b;

    text-transform:uppercase;

}

.live {

    font-size:27px;

    font-weight:bold;

    color:#16a34a;

    margin-top:8px;

}

.next {

    font-size:24px;

    font-weight:bold;

    color:#2563eb;

    margin-top:8px;

}

.today {

    font-size:24px;

    font-weight:bold;

    margin-top:8px;

}


/* CURRENT */

.section {

    background:white;

    margin-top:20px;

    padding:22px;

    border-radius:15px;

    box-shadow:
    0 4px 15px rgba(0,0,0,.06);

}

.section h2 {

    margin-top:0;

}

.lecture {

    display:flex;

    justify-content:space-between;

    align-items:center;

    gap:10px;

    padding:14px;

    margin:8px 0;

    background:#ecfdf5;

    border-left:
    4px solid #16a34a;

    border-radius:8px;

}

.live-badge {

    background:#16a34a;

    color:white;

    padding:6px 10px;

    border-radius:20px;

    font-size:11px;

    font-weight:bold;

}


/* BUTTON */

.master-btn {

    display:block;

    text-align:center;

    margin-top:20px;

    padding:17px;

    border-radius:12px;

    background:
    linear-gradient(
        135deg,
        #2563eb,
        #7c3aed
    );

    color:white;

    text-decoration:none;

    font-size:18px;

    font-weight:bold;

}


/* TABLE */

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

    padding:12px;

    border:1px solid #cbd5e1;

}

td {

    padding:10px;

    border:1px solid #dbe3ee;

    text-align:center;

    vertical-align:top;

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

.current-cell {

    background:#dcfce7;

}


/* MASTER BUTTON */

.all-class {

    margin-top:25px;

    background:#111827;

    color:white;

    padding:18px;

    border-radius:14px;

    text-align:center;

}

.all-class a {

    display:inline-block;

    margin-top:10px;

    background:#2563eb;

    color:white;

    padding:13px 25px;

    border-radius:9px;

    text-decoration:none;

    font-weight:bold;

}


/* MOBILE */

@media(max-width:700px) {

    .navbar {

        padding:13px;

        flex-direction:column;

        align-items:flex-start;

    }

    .nav {

        gap:12px;

    }

    .cards {

        grid-template-columns:1fr;

    }

    .hero h1 {

        font-size:24px;

    }

}

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
        <a href="/login">🔐 Access</a>
        {% endif %}

    </div>

</div>


<div class="container">


<div class="hero">

    <h1>
        🎓 SGB College Management
    </h1>

    <p>
        Smart timetable, attendance and reports
    </p>

</div>


<form
method="GET"
action="/"
>

<div class="select-box">


<div class="select-group">

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


<div class="select-group">

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


</div>

</form>


<div class="cards">


<div class="card">

<div class="card-title">
Current Lecture
</div>

<div class="live">

{% if current_lectures %}
1 LIVE
{% else %}
NO LIVE
{% endif %}

</div>

</div>


<div class="card">

<div class="card-title">
Next Lecture
</div>

<div class="next">

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

<div class="today">

{{ today }}

</div>

</div>


</div>


<div class="section">

<h2>
🟢 Current Lecture
</h2>


{% if current_lectures %}

{% for item in current_lectures %}

<div class="lecture">

<div>

<strong>
{{ item.time }}
</strong>

&nbsp;&nbsp;

{{ item.lecture }}

</div>

<div class="live-badge">
LIVE NOW
</div>

</div>

{% endfor %}

{% else %}

<p>
No lecture is currently running.
</p>

{% endif %}

</div>


<!-- MASTER BUTTON -->

<div class="all-class">

<h2>
📚 All Class Timetable
</h2>

<p>
Science + Arts + Commerce
<br>
1st Year + 2nd Year + 3rd Year
</p>

<a href="/master-timetable">

OPEN ALL CLASS TIMETABLE

</a>

</div>


<!-- TODAY TABLE -->

<div class="section">

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

<tr
{% if slot in current_slots %}
class="current-cell"
{% endif %}
>

<td class="time">
{{ slot }}
</td>

<td>

{% for subject in today_data.get(slot, []) %}

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


<script>

/*
Automatically refresh the page every 30 seconds
so Current Lecture changes automatically.
*/

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


# ============================================================
# HOME ROUTE
# ============================================================

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

        faculties=FACULTIES,

        years=YEARS,

        selected_faculty=selected_faculty,

        selected_year=selected_year,

        current_lectures=current_lectures,

        current_slots=current_slots,

        next_lecture=next_lecture,

        today=today,

        today_data=today_data,

        today_slots=today_slots
    )


# ============================================================
# MASTER TIMETABLE PAGE
# ============================================================

MASTER_PAGE = r"""
<!DOCTYPE html>
<html>

<head>

<title>All Class Timetable</title>

<meta
name="viewport"
content="width=device-width, initial-scale=1.0"
>

<style>

* {
    box-sizing:border-box;
}

body {

    margin:0;

    font-family:Arial,sans-serif;

    background:#eef2f7;

    color:#1e293b;

}


/* HEADER */

.header {

    background:
    linear-gradient(
        135deg,
        #172554,
        #2563eb
    );

    color:white;

    padding:28px 20px;

    text-align:center;

}

.header h1 {

    margin:0;

    font-size:30px;

}

.header p {

    margin:8px 0 0;

}


/* CONTAINER */

.container {

    max-width:1500px;

    margin:auto;

    padding:20px;

}


/* BUTTONS */

.top-buttons {

    display:flex;

    gap:10px;

    flex-wrap:wrap;

    margin-bottom:20px;

}

.btn {

    display:inline-block;

    padding:11px 18px;

    border-radius:9px;

    color:white;

    text-decoration:none;

    font-weight:bold;

}

.back {

    background:#475569;

}

.print {

    background:#16a34a;

    border:none;

    cursor:pointer;

}


/* FACULTY */

.faculty {

    margin-bottom:45px;

}

.faculty-header {

    background:
    linear-gradient(
        135deg,
        #1e3a8a,
        #4f46e5
    );

    color:white;

    padding:18px;

    border-radius:
    14px 14px 0 0;

}

.faculty-header h2 {

    margin:0;

}


/* YEAR */

.year {

    background:white;

    margin-top:15px;

    border-radius:10px 10px 0 0;

}

.year-header {

    padding:15px;

    border-left:
    5px solid #2563eb;

    font-size:20px;

    font-weight:bold;

}


/* TABLE */

.table-wrapper {

    overflow-x:auto;

}

table {

    width:100%;

    min-width:1050px;

    border-collapse:collapse;

}

th {

    background:#172554;

    color:white;

    padding:13px 8px;

    border:1px solid #cbd5e1;

    text-align:center;

}

th.time {

    min-width:125px;

}

td {

    border:1px solid #dbe3ee;

    padding:9px;

    min-width:145px;

    vertical-align:top;

    text-align:center;

}

td.time {

    background:#f1f5f9;

    font-weight:bold;

}


/* SUBJECT */

.subject {

    display:block;

    background:#eff6ff;

    color:#1e3a8a;

    border-left:
    4px solid #2563eb;

    padding:7px;

    margin:4px 0;

    border-radius:6px;

    text-align:left;

    font-size:13px;

    font-weight:600;

}


/* EMPTY */

.empty {

    color:#94a3b8;

}


/* PRINT */

@media print {

    .top-buttons {

        display:none;

    }

    .faculty {

        page-break-after:always;

    }

    body {

        background:white;

    }

}

</style>

</head>


<body>


<div class="header">

<h1>
📚 SGB COLLEGE
</h1>

<p>
MASTER CLASS TIMETABLE
</p>

</div>


<div class="container">


<div class="top-buttons">

<a
href="/"
class="btn back"
>
← Back to Home
</a>


<button
onclick="window.print()"
class="btn print"
>
🖨 Print All
</button>

</div>


{% for faculty in faculties %}


<div class="faculty">


<div class="faculty-header">

<h2>
{{ faculty }}
</h2>

</div>


{% for year in years %}


{% if year in timetable.get(faculty,{}) %}


<div class="year">


<div class="year-header">

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

<th class="time">
TIME
</th>


{% for day in days %}

<th>
{{ day }}
</th>

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

<span class="empty">
—
</span>

{% endif %}


</td>


{% endfor %}


</tr>


{% endfor %}


</tbody>

</table>

</div>


</div>


{% endif %}


{% endfor %}


</div>


{% endfor %}


</div>


</body>

</html>
"""


# ============================================================
# MASTER ROUTE
# ============================================================

@app.route("/master-timetable")
def master_timetable():

    timetable = load_timetable()

    return render_template_string(

        MASTER_PAGE,

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

<meta
name="viewport"
content="width=device-width,initial-scale=1"
>

<style>

body {

    margin:0;

    font-family:Arial;

    background:#f1f5f9;

}

.header {

    background:#172554;

    color:white;

    padding:25px;

    text-align:center;

}

.container {

    max-width:1200px;

    margin:auto;

    padding:20px;

}

.controls {

    background:white;

    padding:20px;

    border-radius:12px;

    margin-bottom:20px;

}

select {

    padding:12px;

    width:100%;

    margin-bottom:10px;

}

button {

    padding:12px 20px;

    background:#2563eb;

    color:white;

    border:0;

    border-radius:8px;

}

.wrapper {

    overflow-x:auto;

}

table {

    width:100%;

    min-width:800px;

    border-collapse:collapse;

    background:white;

}

th {

    background:#1e3a8a;

    color:white;

    padding:13px;

}

td {

    border:1px solid #ddd;

    padding:10px;

    text-align:center;

}

.time {

    background:#f1f5f9;

    font-weight:bold;

}

.subject {

    display:block;

    padding:7px;

    background:#eff6ff;

    margin:3px;

    border-radius:5px;

}

</style>

</head>


<body>


<div class="header">

<h1>
📅 Daily Timetable
</h1>

</div>


<div class="container">


<div class="controls">

<form method="GET">

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


<button>
VIEW TIMETABLE
</button>

</form>

</div>


<div class="wrapper">

<table>

<tr>

<th>TIME</th>

<th>
{{ selected_day }}
</th>

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

<meta
name="viewport"
content="width=device-width,initial-scale=1"
>

<style>

body {

    margin:0;

    background:#eef2ff;

    font-family:Arial;

}

.box {

    max-width:400px;

    margin:80px auto;

    background:white;

    padding:30px;

    border-radius:15px;

    box-shadow:
    0 5px 25px rgba(0,0,0,.1);

}

h1 {

    text-align:center;

}

input {

    width:100%;

    padding:13px;

    margin:8px 0;

    border:1px solid #ccc;

    border-radius:8px;

    box-sizing:border-box;

}

button {

    width:100%;

    padding:13px;

    margin-top:10px;

    background:#2563eb;

    color:white;

    border:0;

    border-radius:8px;

    font-weight:bold;

}

.error {

    color:#dc2626;

    text-align:center;

}

</style>

</head>


<body>


<div class="box">

<h1>
🔐 Admin Access
</h1>


{% with messages =
    get_flashed_messages()
%}

{% for message in messages %}

<p class="error">
{{ message }}
</p>

{% endfor %}

{% endwith %}


<form method="POST">

<input
type="text"
name="username"
placeholder="Username"
required
>


<input
type="password"
name="password"
placeholder="Password"
required
>


<button>
LOGIN
</button>

</form>


</div>

</body>

</html>
"""


@app.route("/login", methods=["GET","POST"])
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
            and
            password == ADMIN_PASSWORD
        ):

            session["admin_logged_in"] = True

            session["admin_username"] = username

            return redirect(
                request.args.get(
                    "next",
                    "/"
                )
            )


        flash("Invalid username or password.")


    return render_template_string(
        LOGIN_PAGE
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

<meta
name="viewport"
content="width=device-width,initial-scale=1"
>

<style>

body {

    margin:0;

    font-family:Arial;

    background:#f1f5f9;

}

.header {

    background:#111827;

    color:white;

    padding:20px;

    text-align:center;

}

.container {

    max-width:1100px;

    margin:auto;

    padding:20px;

}

.box {

    background:white;

    padding:20px;

    border-radius:14px;

    margin-bottom:20px;

}

select {

    padding:11px;

    margin:5px;

}

table {

    width:100%;

    border-collapse:collapse;

}

th {

    background:#172554;

    color:white;

    padding:12px;

}

td {

    border:1px solid #ddd;

    padding:10px;

    text-align:center;

}

.status {

    font-weight:bold;

}

button {

    padding:9px 14px;

    border:0;

    border-radius:7px;

    cursor:pointer;

}

.taken {

    background:#16a34a;

    color:white;

}

.not {

    background:#dc2626;

    color:white;

}

.cancel {

    background:#64748b;

    color:white;

}

</style>

</head>


<body>


<div class="header">

<h1>
☑ Class Attendance
</h1>

</div>


<div class="container">


<div class="box">

<form method="GET">

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


<button>
VIEW
</button>

</form>

</div>


<div class="box">

<h2>
{{ selected_day }} - {{ faculty }} - {{ year }}
</h2>


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
{{ item.time }}
</td>

<td>

{% for subject in item.subjects %}

<div>
{{ subject }}
</div>

{% endfor %}

</td>


<td class="status">

{{ item.status }}

</td>


<td>


<form
method="POST"
action="/attendance/mark"
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
class="taken"
>
✓ Taken
</button>


<button
name="status"
value="not_taken"
class="not"
>
✗ Not Taken
</button>


<button
name="status"
value="cancelled"
class="cancel"
>
Cancelled
</button>


</form>


</td>

</tr>

{% endfor %}


</table>

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

        lectures.append({

            "time":slot,

            "subjects":subjects,

            "subject_text":" | ".join(
                subjects
            ),

            "status":
                status_map.get(
                    slot,
                    "Not Marked"
                )

        })


    return render_template_string(

        ATTENDANCE_PAGE,

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

    faculty = request.form.get(
        "faculty"
    )

    year = request.form.get(
        "year"
    )

    day = request.form.get(
        "day"
    )

    time_slot = request.form.get(
        "time_slot"
    )

    lecture = request.form.get(
        "lecture"
    )

    status = request.form.get(
        "status"
    )


    allowed = [
        "taken",
        "not_taken",
        "cancelled"
    ]

    if status not in allowed:

        status = "not_taken"


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
        str(date.today()),
        faculty,
        year,
        day,
        time_slot
    )).fetchone()


    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


    if existing:

        conn.execute("""
            UPDATE attendance
            SET status=?,
                lecture=?,
                marked_by=?,
                marked_at=?
            WHERE id=?
        """, (
            status,
            lecture,
            session.get(
                "admin_username",
                "admin"
            ),
            now,
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
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            str(date.today()),
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

REPORT_PAGE = r"""
<!DOCTYPE html>
<html>

<head>

<title>Attendance Reports</title>

<meta
name="viewport"
content="width=device-width,initial-scale=1"
>

<style>

body {

    margin:0;

    font-family:Arial;

    background:#f1f5f9;

}

.header {

    background:#172554;

    color:white;

    padding:25px;

    text-align:center;

}

.container {

    max-width:1200px;

    margin:auto;

    padding:20px;

}

.box {

    background:white;

    padding:20px;

    border-radius:14px;

    margin-bottom:20px;

}

table {

    width:100%;

    border-collapse:collapse;

}

th {

    background:#1e3a8a;

    color:white;

    padding:12px;

}

td {

    border:1px solid #ddd;

    padding:10px;

    text-align:center;

}

</style>

</head>


<body>


<div class="header">

<h1>
📊 Attendance Reports
</h1>

</div>


<div class="container">


<div class="box">

<h2>
Attendance Summary
</h2>


<table>

<tr>

<th>Faculty</th>

<th>Year</th>

<th>Taken</th>

<th>Not Taken</th>

<th>Cancelled</th>

<th>Total</th>

</tr>


{% for row in summary %}

<tr>

<td>
{{ row.faculty }}
</td>

<td>
{{ row.year }}
</td>

<td>
{{ row.taken }}
</td>

<td>
{{ row.not_taken }}
</td>

<td>
{{ row.cancelled }}
</td>

<td>
{{ row.total }}
</td>

</tr>

{% endfor %}


</table>

</div>


<div class="box">

<h2>
Recent Attendance Data
</h2>


<table>

<tr>

<th>Date</th>

<th>Faculty</th>

<th>Year</th>

<th>Day</th>

<th>Time</th>

<th>Lecture</th>

<th>Status</th>

<th>Marked By</th>

</tr>


{% for row in recent %}

<tr>

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

<td>
{{ row.lecture }}
</td>

<td>
{{ row.status }}
</td>

<td>
{{ row.marked_by }}
</td>

</tr>

{% endfor %}


</table>

</div>


</div>

</body>

</html>
"""


@app.route("/reports")
@admin_required
def reports():

    conn = get_db()


    summary = conn.execute("""
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

        GROUP BY faculty, year

        ORDER BY faculty, year
    """).fetchall()


    recent = conn.execute("""
        SELECT *
        FROM attendance
        ORDER BY id DESC
        LIMIT 100
    """).fetchall()


    conn.close()


    return render_template_string(

        REPORT_PAGE,

        summary=summary,

        recent=recent

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
