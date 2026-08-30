import os
import json
from datetime import datetime

from flask import Flask, render_template_string, request, redirect, url_for, flash


# ============================================================
# APP CONFIGURATION
# ============================================================

app = Flask(__name__)
app.secret_key = "sgbm-college-secret-key"

TIMETABLE_FILE = "timetable.json"

DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday"
]

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


# ============================================================
# LOAD TIMETABLE
# ============================================================

def load_timetable():
    if not os.path.exists(TIMETABLE_FILE):
        return {}

    try:
        with open(TIMETABLE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as e:
        print("Error loading timetable.json:", e)
        return {}


timetable = load_timetable()


# ============================================================
# TIME HELPERS
# ============================================================

def time_to_minutes(time_string):
    """
    Convert HH:MM into minutes.
    """
    try:
        hour, minute = map(int, time_string.strip().split(":"))
        return hour * 60 + minute
    except Exception:
        return 9999


def time_sort_key(time_range):
    """
    Sort time ranges using starting time.

    Example:
    09:00-10:00
    10:00-11:00
    11:00-12:00
    """
    try:
        start = time_range.split("-")[0].strip()
        return time_to_minutes(start)
    except Exception:
        return 9999


def format_time(time_range):
    """
    Display time more nicely.
    """
    return time_range


# ============================================================
# GET ALL TIME SLOTS
# ============================================================

def get_time_slots(faculty, year):
    """
    Collect every time slot used during Monday-Saturday.
    """

    slots = set()

    faculty_data = timetable.get(faculty, {})
    year_data = faculty_data.get(year, {})

    for day in DAYS:
        day_data = year_data.get(day, {})

        for time_range in day_data.keys():
            slots.add(time_range)

    return sorted(slots, key=time_sort_key)


# ============================================================
# GET SUBJECTS
# ============================================================

def get_subjects(faculty, year, day, time_range):
    """
    Return subjects for a particular day/time.
    """

    faculty_data = timetable.get(faculty, {})
    year_data = faculty_data.get(year, {})
    day_data = year_data.get(day, {})

    subjects = day_data.get(time_range, [])

    if subjects is None:
        return []

    if isinstance(subjects, str):
        return [subjects]

    return subjects


# ============================================================
# HOME PAGE
# ============================================================

HOME_PAGE = """
<!DOCTYPE html>
<html>
<head>

    <title>SGBM College - Timetable</title>

    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <style>

        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            font-family: Arial, Helvetica, sans-serif;
            background: #f3f6fb;
            color: #1f2937;
        }

        .header {
            background: linear-gradient(
                135deg,
                #172554,
                #1e40af
            );

            color: white;
            padding: 35px 20px;
            text-align: center;
        }

        .header h1 {
            margin: 0;
            font-size: 34px;
        }

        .header p {
            margin-top: 10px;
            font-size: 17px;
        }

        .container {
            max-width: 1100px;
            margin: 40px auto;
            padding: 20px;
        }

        .main-card {
            background: white;
            padding: 35px;
            border-radius: 18px;
            box-shadow:
                0 8px 30px rgba(0,0,0,0.08);

            text-align: center;
        }

        .main-card h2 {
            margin-top: 0;
            font-size: 28px;
        }

        .main-card p {
            color: #64748b;
            font-size: 16px;
        }

        .master-button {
            display: inline-block;
            margin-top: 25px;
            padding: 16px 30px;
            border-radius: 12px;

            background: #2563eb;
            color: white;

            text-decoration: none;
            font-size: 18px;
            font-weight: bold;

            transition: 0.2s;
        }

        .master-button:hover {
            background: #1d4ed8;
            transform: translateY(-2px);
        }

        .faculty-grid {
            margin-top: 35px;

            display: grid;
            grid-template-columns:
                repeat(auto-fit, minmax(220px, 1fr));

            gap: 20px;
        }

        .faculty-card {
            background: #f8fafc;
            padding: 25px;
            border-radius: 14px;
            border: 1px solid #e2e8f0;
        }

        .faculty-card h3 {
            margin-top: 0;
        }

        .year-list {
            color: #475569;
            line-height: 1.8;
        }

        @media(max-width: 600px) {

            .header h1 {
                font-size: 26px;
            }

            .main-card {
                padding: 25px 18px;
            }

        }

    </style>

</head>

<body>

    <div class="header">

        <h1>SGBM COLLEGE</h1>

        <p>
            Smart Class Timetable Management
        </p>

    </div>


    <div class="container">

        <div class="main-card">

            <h2>
                MASTER CLASS TIMETABLE
            </h2>

            <p>
                View Science, Arts and Commerce
                class timetables in table format.
            </p>

            <a
                href="{{ url_for('master_timetable') }}"
                class="master-button"
            >
                📋 OPEN MASTER CLASS TIMETABLE
            </a>


            <div class="faculty-grid">

                {% for faculty in faculties %}

                <div class="faculty-card">

                    <h3>
                        {{ faculty }}
                    </h3>

                    <div class="year-list">

                        1st Year<br>
                        2nd Year<br>
                        3rd Year

                    </div>

                </div>

                {% endfor %}

            </div>

        </div>

    </div>

</body>
</html>
"""


# ============================================================
# MASTER TIMETABLE PAGE
# ============================================================

MASTER_PAGE = """
<!DOCTYPE html>
<html>

<head>

    <title>
        Master Class Timetable - SGBM College
    </title>

    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <style>

        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            font-family: Arial, Helvetica, sans-serif;

            background:
                #eef2f7;

            color: #1e293b;
        }


        /* ==================================================
           HEADER
        ================================================== */

        .header {

            background:
                linear-gradient(
                    135deg,
                    #172554,
                    #2563eb
                );

            color: white;

            padding: 25px 20px;

            text-align: center;

            position: sticky;
            top: 0;

            z-index: 100;
        }

        .header h1 {

            margin: 0;

            font-size: 30px;

        }

        .header p {

            margin: 7px 0 0;

            opacity: 0.9;

        }


        /* ==================================================
           CONTROL PANEL
        ================================================== */

        .controls {

            background: white;

            margin: 25px auto;

            padding: 20px;

            max-width: 1400px;

            border-radius: 15px;

            box-shadow:
                0 5px 20px rgba(0,0,0,0.07);

        }

        .control-row {

            display: flex;

            flex-wrap: wrap;

            gap: 15px;

            align-items: end;

        }

        .control-group {

            flex: 1;

            min-width: 200px;

        }

        .control-group label {

            display: block;

            font-weight: bold;

            margin-bottom: 7px;

            color: #334155;

        }

        select {

            width: 100%;

            padding: 12px;

            border-radius: 9px;

            border:
                1px solid #cbd5e1;

            background: white;

            font-size: 15px;

        }

        .view-button {

            padding: 12px 22px;

            border: none;

            border-radius: 9px;

            background: #2563eb;

            color: white;

            font-size: 15px;

            font-weight: bold;

            cursor: pointer;

        }

        .view-button:hover {

            background: #1d4ed8;

        }

        .home-button {

            display: inline-block;

            margin-top: 15px;

            padding: 10px 18px;

            background: #64748b;

            color: white;

            text-decoration: none;

            border-radius: 8px;

        }


        /* ==================================================
           TITLE
        ================================================== */

        .table-container {

            max-width: 1400px;

            margin:
                0 auto 40px;

            padding: 0 20px;

        }

        .table-title {

            background: white;

            padding: 20px;

            border-radius: 15px 15px 0 0;

            border-bottom:
                3px solid #2563eb;

        }

        .table-title h2 {

            margin: 0;

            font-size: 24px;

        }

        .table-title p {

            margin:
                7px 0 0;

            color: #64748b;

        }


        /* ==================================================
           TABLE
        ================================================== */

        .table-wrapper {

            background: white;

            overflow-x: auto;

            border-radius:
                0 0 15px 15px;

            box-shadow:
                0 5px 25px rgba(0,0,0,0.08);

        }

        table {

            width: 100%;

            min-width: 1050px;

            border-collapse: collapse;

        }

        th {

            background: #1e3a8a;

            color: white;

            padding: 15px 10px;

            border:
                1px solid #cbd5e1;

            text-align: center;

            font-size: 15px;

        }

        th.time-header {

            background: #172554;

            min-width: 130px;

        }

        td {

            border:
                1px solid #dbe3ee;

            padding: 10px;

            vertical-align: top;

            text-align: center;

            min-width: 145px;

            height: 80px;

        }

        td.time-cell {

            background: #f1f5f9;

            font-weight: bold;

            color: #334155;

            min-width: 130px;

        }

        .subject {

            display: block;

            background: #eff6ff;

            border-left:
                4px solid #2563eb;

            padding: 7px 8px;

            margin: 4px 0;

            border-radius: 6px;

            font-size: 13px;

            text-align: left;

            color: #1e3a8a;

            font-weight: 600;

        }

        .empty {

            color: #94a3b8;

            font-size: 13px;

        }


        /* ==================================================
           PRINT
        ================================================== */

        .print-button {

            margin-top: 15px;

            padding: 11px 20px;

            border: none;

            border-radius: 8px;

            background: #16a34a;

            color: white;

            font-weight: bold;

            cursor: pointer;

        }


        @media(max-width: 700px) {

            .header h1 {

                font-size: 24px;

            }

            .controls {

                margin: 15px;

            }

            .table-container {

                padding: 0 10px;

            }

        }


        @media print {

            .header {

                position: static;

            }

            .controls,

            .home-button,

            .print-button {

                display: none;

            }

            .table-container {

                max-width: none;

                padding: 0;

            }

            table {

                min-width: 0;

                font-size: 10px;

            }

            th,

            td {

                padding: 5px;

            }

        }

    </style>

</head>


<body>


    <!-- ==================================================
         HEADER
    ================================================== -->

    <div class="header">

        <h1>
            SGBM COLLEGE
        </h1>

        <p>
            MASTER CLASS TIMETABLE
        </p>

    </div>


    <!-- ==================================================
         CONTROLS
    ================================================== -->

    <div class="controls">

        <form method="GET"
              action="{{ url_for('master_timetable') }}">

            <div class="control-row">


                <div class="control-group">

                    <label>
                        Faculty
                    </label>

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


                <div class="control-group">

                    <label>
                        Year
                    </label>

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


                <button
                    type="submit"
                    class="view-button"
                >

                    VIEW TIMETABLE

                </button>

            </div>

        </form>


        <a
            href="{{ url_for('home') }}"
            class="home-button"
        >

            ← Back to Home

        </a>


        <button
            onclick="window.print()"
            class="print-button"
        >

            🖨 Print Timetable

        </button>

    </div>


    <!-- ==================================================
         TIMETABLE
    ================================================== -->

    <div class="table-container">


        <div class="table-title">

            <h2>

                {{ selected_faculty }}
                -
                {{ selected_year }}

            </h2>

            <p>

                Weekly Class Timetable
                | Monday to Saturday

            </p>

        </div>


        <div class="table-wrapper">

            <table>

                <thead>

                    <tr>

                        <th class="time-header">
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


                    {% for time_slot in time_slots %}

                    <tr>


                        <td class="time-cell">

                            {{ time_slot }}

                        </td>


                        {% for day in days %}

                        <td>


                            {% set subjects =
                            get_subjects(
                                selected_faculty,
                                selected_year,
                                day,
                                time_slot
                            ) %}


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


</body>

</html>
"""


# ============================================================
# HOME ROUTE
# ============================================================

@app.route("/")
def home():

    return render_template_string(
        HOME_PAGE,
        faculties=FACULTIES
    )


# ============================================================
# MASTER TIMETABLE ROUTE
# ============================================================

@app.route("/master-timetable")
def master_timetable():

    selected_faculty = request.args.get(
        "faculty",
        "Science"
    )

    selected_year = request.args.get(
        "year",
        "1st Year"
    )


    # Validate faculty

    if selected_faculty not in FACULTIES:

        selected_faculty = "Science"


    # Validate year

    if selected_year not in YEARS:

        selected_year = "1st Year"


    # Get time slots

    time_slots = get_time_slots(
        selected_faculty,
        selected_year
    )


    return render_template_string(

        MASTER_PAGE,

        faculties=FACULTIES,

        years=YEARS,

        days=DAYS,

        selected_faculty=selected_faculty,

        selected_year=selected_year,

        time_slots=time_slots,

        get_subjects=get_subjects

    )


# ============================================================
# RUN APPLICATION
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
