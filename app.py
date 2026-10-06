import os
import json
import csv
import io
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from functools import wraps

from flask import (
    Flask, render_template_string, request, redirect, url_for,
    session, flash, Response
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import UniqueConstraint, inspect, text


# ============================================================
# APPLICATION CONFIGURATION
# ============================================================

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "CHANGE-ME-IN-PRODUCTION"
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(BASE_DIR, "college.db")
)

# Render/Railway may provide postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Helpful for SQLite concurrency.
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True
}

db = SQLAlchemy(app)

IST = ZoneInfo("Asia/Kolkata")

DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday"
]

FACULTY_ORDER = ["Science", "Arts", "Commerce"]
YEAR_ORDER = ["1st Year", "2nd Year", "3rd Year"]

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

TIMETABLE_FILE = os.path.join(BASE_DIR, "timetable.json")


# ============================================================
# TIME HELPERS
# ============================================================

def now_ist():
    return datetime.now(IST)


def today_ist():
    return now_ist().date()


def now_ist_naive():
    return now_ist().replace(tzinfo=None)


def parse_time(value):
    """Return minutes after midnight from HH:MM."""
    if value is None:
        return None

    try:
        text = str(value).strip()
        parts = text.split(":")
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour * 60 + minute
    except Exception:
        return None


def parse_slot(slot):
    """Parse '09:00-10:00' into (start_minutes, end_minutes)."""
    if not slot:
        return None, None

    try:
        start_text, end_text = str(slot).split("-", 1)
        return parse_time(start_text), parse_time(end_text)
    except Exception:
        return None, None


def slot_start(slot):
    start, _ = parse_slot(slot)
    return start if start is not None else 99999


def format_date(value):
    if not value:
        return ""
    return value.strftime("%d-%m-%Y")


def format_time_range(slot):
    return slot


# ============================================================
# TIMETABLE DATA NORMALISATION
# ============================================================

def load_timetable_json():
    if not os.path.exists(TIMETABLE_FILE):
        return {}

    try:
        with open(TIMETABLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print("WARNING: timetable.json could not be loaded:", exc)
        return {}


def lecture_to_dict(value):
    """
    Supports the existing timetable formats:

        "Physics"

        {"subject": "Physics", "teacher": "Dr. A"}

        {"class": "Physics"}

        {"lecture": "Physics"}

        {"name": "Physics"}

        {"subject": "Physics", "teacher": "Dr. A", "room": "101"}

        {"lectures": ["Physics", "Chemistry"]}
    """
    if isinstance(value, str):
        return [{
            "subject": value.strip(),
            "teacher": "",
            "room": "",
            "class_name": ""
        }] if value.strip() else []

    if isinstance(value, dict):
        # A dictionary containing a lecture list.
        for list_key in ("lectures", "subjects", "classes"):
            if isinstance(value.get(list_key), list):
                result = []
                parent_teacher = str(
                    value.get("teacher", value.get("faculty_teacher", ""))
                ).strip()
                parent_room = str(value.get("room", "")).strip()
                parent_class = str(
                    value.get("class_name", value.get("class", ""))
                ).strip()

                for item in value[list_key]:
                    parsed = lecture_to_dict(item)
                    for x in parsed:
                        if not x["teacher"]:
                            x["teacher"] = parent_teacher
                        if not x["room"]:
                            x["room"] = parent_room
                        if not x["class_name"]:
                            x["class_name"] = parent_class
                        result.append(x)
                return result

        subject = ""
        for key in ("subject", "lecture", "name", "class"):
            if value.get(key) is not None:
                subject = str(value.get(key)).strip()
                if subject:
                    break

        # If "class" was actually intended as a class name but there is
        # no subject, it is still shown as the lecture subject.
        if not subject:
            subject = str(value).strip()

        teacher = str(
            value.get(
                "teacher",
                value.get(
                    "faculty_teacher",
                    value.get("instructor", "")
                )
            )
        ).strip()

        room = str(value.get("room", value.get("classroom", ""))).strip()

        class_name = str(
            value.get(
                "class_name",
                value.get("section", "")
            )
        ).strip()

        return [{
            "subject": subject,
            "teacher": teacher,
            "room": room,
            "class_name": class_name
        }] if subject else []

    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            result.extend(lecture_to_dict(item))
        return result

    text = str(value).strip()
    return [{
        "subject": text,
        "teacher": "",
        "room": "",
        "class_name": ""
    }] if text else []


def ordered_faculties(values):
    values = list(dict.fromkeys(values))
    return (
        [x for x in FACULTY_ORDER if x in values]
        + [x for x in values if x not in FACULTY_ORDER]
    )


def ordered_years(values):
    values = list(dict.fromkeys(values))
    return (
        [x for x in YEAR_ORDER if x in values]
        + [x for x in values if x not in YEAR_ORDER]
    )


def normalize_year(value):
    if value is None:
        return ""

    text = str(value).strip()

    aliases = {
        "1": "1st Year",
        "1st": "1st Year",
        "1st year": "1st Year",
        "first": "1st Year",
        "first year": "1st Year",

        "2": "2nd Year",
        "2nd": "2nd Year",
        "2nd year": "2nd Year",
        "second": "2nd Year",
        "second year": "2nd Year",

        "3": "3rd Year",
        "3rd": "3rd Year",
        "3rd year": "3rd Year",
        "third": "3rd Year",
        "third year": "3rd Year",
    }

    return aliases.get(text.lower(), text)


def json_to_rows(data):
    """
    Flatten the existing nested timetable into database rows.

    Expected common structure:

    {
      "Science": {
        "1st Year": {
          "Monday": {
            "09:00-10:00": "Physics"
          }
        }
      }
    }

    Existing dictionaries/lists are also accepted.
    """
    rows = []

    if not isinstance(data, dict):
        return rows

    for faculty, faculty_data in data.items():
        if not isinstance(faculty_data, dict):
            continue

        for year, year_data in faculty_data.items():
            if not isinstance(year_data, dict):
                continue

            year_normalized = normalize_year(year)

            for day, day_data in year_data.items():
                if day not in DAYS or not isinstance(day_data, dict):
                    continue

                for slot, value in day_data.items():
                    for lecture in lecture_to_dict(value):
                        rows.append({
                            "faculty": str(faculty).strip(),
                            "year": year_normalized,
                            "day": day,
                            "slot": str(slot).strip(),
                            "subject": lecture["subject"],
                            "teacher": lecture["teacher"],
                            "class_name": lecture["class_name"],
                            "room": lecture["room"]
                        })

    return rows


# ============================================================
# DATABASE MODELS
# ============================================================

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(200), nullable=False)

    username = db.Column(
        db.String(100),
        unique=True,
        nullable=False,
        index=True
    )

    password_hash = db.Column(db.String(300), nullable=False)

    is_admin = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=now_ist_naive,
        nullable=False
    )

    attendance_records = db.relationship(
        "Attendance",
        back_populates="marked_by_user",
        foreign_keys="Attendance.marked_by_user_id"
    )


class Timetable(db.Model):
    __tablename__ = "timetable"

    id = db.Column(db.Integer, primary_key=True)

    faculty = db.Column(db.String(100), nullable=False, index=True)
    year = db.Column(db.String(100), nullable=False, index=True)
    day = db.Column(db.String(20), nullable=False, index=True)

    slot = db.Column(db.String(50), nullable=False, index=True)
    subject = db.Column(db.String(300), nullable=False, index=True)

    teacher = db.Column(db.String(200), nullable=True)
    class_name = db.Column(db.String(200), nullable=True)
    room = db.Column(db.String(100), nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=now_ist_naive,
        nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "faculty",
            "year",
            "day",
            "slot",
            "subject",
            name="uq_timetable_lecture"
        ),
    )


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)

    record_date = db.Column(
        db.Date,
        nullable=False,
        index=True
    )

    faculty = db.Column(
        db.String(100),
        nullable=False,
        index=True
    )

    year = db.Column(
        db.String(100),
        nullable=False,
        index=True
    )

    class_name = db.Column(
        db.String(200),
        nullable=True,
        index=True
    )

    day = db.Column(
        db.String(20),
        nullable=False,
        index=True
    )

    slot = db.Column(
        db.String(50),
        nullable=False,
        index=True
    )

    subject = db.Column(
        db.String(300),
        nullable=False,
        index=True
    )

    teacher = db.Column(
        db.String(200),
        nullable=True
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        index=True
    )

    marked_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True
    )

    marked_by = db.Column(
        db.String(200),
        nullable=True
    )

    marked_at = db.Column(
        db.DateTime,
        default=now_ist_naive,
        nullable=False
    )

    marked_by_user = db.relationship(
        "User",
        back_populates="attendance_records",
        foreign_keys=[marked_by_user_id]
    )

    __table_args__ = (
        UniqueConstraint(
            "record_date",
            "faculty",
            "year",
            "class_name",
            "day",
            "slot",
            "subject",
            name="uq_attendance_lecture"
        ),
    )


# ============================================================
# DATABASE INITIALISATION
# ============================================================

def migrate_legacy_schema():
    """
    Make the application compatible with the user's earlier version of
    this project. Flask-SQLAlchemy's create_all() does not add new columns
    to an already-existing table, so the small migration below preserves
    existing attendance records while adding the newer fields.
    """
    inspector = inspect(db.engine)

    tables = inspector.get_table_names()

    # Nothing to migrate on a completely new database.
    if not tables:
        return

    def add_column_if_missing(table_name, column_name, sql_type):
        if table_name not in inspect(db.engine).get_table_names():
            return

        columns = {
            col["name"]
            for col in inspect(db.engine).get_columns(table_name)
        }

        if column_name not in columns:
            db.session.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    f"ADD COLUMN {column_name} {sql_type}"
                )
            )
            db.session.commit()

    # Legacy User model used attendance_access and did not have is_admin.
    add_column_if_missing(
        "users",
        "is_admin",
        "BOOLEAN NOT NULL DEFAULT 0"
    )

    # Legacy Attendance model did not have these fields.
    add_column_if_missing(
        "attendance",
        "class_name",
        "VARCHAR(200)"
    )

    add_column_if_missing(
        "attendance",
        "teacher",
        "VARCHAR(200)"
    )

    add_column_if_missing(
        "attendance",
        "marked_by_user_id",
        "INTEGER"
    )


def initialise_database():
    db.create_all()

    migrate_legacy_schema()

    # create_all() is run again so newly-created tables and indexes are
    # visible after the lightweight legacy migration.
    db.create_all()

    admin = User.query.filter_by(username=ADMIN_USERNAME).first()

    if not admin:
        admin = User(
            name="Administrator",
            username=ADMIN_USERNAME,
            password_hash=generate_password_hash(ADMIN_PASSWORD),
            is_admin=True
        )
        db.session.add(admin)
        db.session.commit()
    else:
        # Keep the configured account an admin.
        # This also upgrades the old project's primary admin account.
        if not admin.is_admin:
            admin.is_admin = True
            db.session.commit()

    # Import timetable.json only when the timetable table is empty.
    # This preserves the user's existing timetable structure/data.
    if Timetable.query.count() == 0:
        data = load_timetable_json()
        rows = json_to_rows(data)

        for row in rows:
            db.session.add(Timetable(**row))

        if rows:
            db.session.commit()
            print(f"Imported {len(rows)} timetable lecture rows from timetable.json.")


with app.app_context():
    initialise_database()


# ============================================================
# CURRENT USER / AUTHORIZATION
# ============================================================

def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    return db.session.get(User, user_id)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(
                url_for(
                    "login",
                    next=request.full_path
                )
            )
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()

        if not user:
            return redirect(
                url_for(
                    "login",
                    next=request.full_path
                )
            )

        if not user.is_admin:
            flash("Administrator access is required.")
            return redirect(url_for("home"))

        return view(*args, **kwargs)

    return wrapped


# ============================================================
# TIMETABLE DATABASE HELPERS
# ============================================================

def all_faculties():
    values = [
        row[0]
        for row in db.session.query(Timetable.faculty)
        .distinct()
        .all()
    ]

    if not values:
        values = FACULTY_ORDER

    return ordered_faculties(values)


def years_for_faculty(faculty):
    query = db.session.query(Timetable.year).distinct()

    if faculty:
        query = query.filter(Timetable.faculty == faculty)

    values = [row[0] for row in query.all()]

    if not values:
        values = YEAR_ORDER

    return ordered_years(values)


def timetable_rows(
    faculty=None,
    year=None,
    day=None,
    slot=None,
    subject=None,
    class_name=None
):
    query = Timetable.query

    if faculty:
        query = query.filter(Timetable.faculty == faculty)

    if year:
        query = query.filter(Timetable.year == year)

    if day:
        query = query.filter(Timetable.day == day)

    if slot:
        query = query.filter(Timetable.slot == slot)

    if subject:
        query = query.filter(Timetable.subject == subject)

    if class_name:
        query = query.filter(Timetable.class_name == class_name)

    return query.order_by(
        Timetable.day.asc(),
        Timetable.slot.asc(),
        Timetable.id.asc()
    ).all()


def slots_for_filters(faculty=None, year=None, day=None):
    rows = timetable_rows(
        faculty=faculty,
        year=year,
        day=day
    )

    slots = list(dict.fromkeys(row.slot for row in rows))
    return sorted(slots, key=slot_start)


def subjects_for_filters(faculty=None, year=None):
    rows = timetable_rows(
        faculty=faculty,
        year=year
    )

    return sorted(
        set(row.subject for row in rows)
    )


def classes_for_filters(faculty=None, year=None):
    rows = timetable_rows(
        faculty=faculty,
        year=year
    )

    values = sorted(
        set(
            row.class_name
            for row in rows
            if row.class_name
        )
    )

    return values


def get_day_lectures(faculty, year, day):
    return sorted(
        timetable_rows(
            faculty=faculty,
            year=year,
            day=day
        ),
        key=lambda row: (slot_start(row.slot), row.id)
    )


# ============================================================
# LIVE LECTURE HELPERS
# ============================================================

def is_current_slot(slot, day):
    if day != now_ist().strftime("%A"):
        return False

    start, end = parse_slot(slot)

    if start is None or end is None:
        return False

    current = now_ist().hour * 60 + now_ist().minute

    return start <= current < end


def get_current_lectures(faculty, year):
    today_name = now_ist().strftime("%A")
    current = []

    for row in get_day_lectures(faculty, year, today_name):
        if is_current_slot(row.slot, today_name):
            current.append(row)

    return current


def get_next_lectures(faculty, year):
    today_name = now_ist().strftime("%A")
    current_minutes = now_ist().hour * 60 + now_ist().minute

    upcoming = []

    for row in get_day_lectures(faculty, year, today_name):
        start, end = parse_slot(row.slot)

        if start is not None and start > current_minutes:
            upcoming.append(row)

    return upcoming


def live_payload(faculty, year):
    current = get_current_lectures(faculty, year)
    upcoming = get_next_lectures(faculty, year)

    def lecture_dict(row):
        return {
            "slot": row.slot,
            "subject": row.subject,
            "teacher": row.teacher or "",
            "class_name": row.class_name or "",
            "room": row.room or "",
            "faculty": row.faculty,
            "year": row.year
        }

    return {
        "date": today_ist().isoformat(),
        "day": now_ist().strftime("%A"),
        "time": now_ist().strftime("%d-%m-%Y %I:%M:%S %p"),
        "faculty": faculty,
        "year": year,
        "current": [lecture_dict(x) for x in current],
        "next": [lecture_dict(x) for x in upcoming]
    }


# ============================================================
# ATTENDANCE HELPERS
# ============================================================

VALID_STATUSES = {
    "taken": "Taken",
    "not_taken": "Not Taken",
    "cancelled": "Cancelled"
}


def attendance_record_for(
    record_date,
    faculty,
    year,
    day,
    slot,
    subject,
    class_name=""
):
    return Attendance.query.filter_by(
        record_date=record_date,
        faculty=faculty,
        year=year,
        day=day,
        slot=slot,
        subject=subject,
        class_name=class_name or ""
    ).first()


def attendance_status_for(
    record_date,
    faculty,
    year,
    day,
    slot,
    subject,
    class_name=""
):
    record = attendance_record_for(
        record_date,
        faculty,
        year,
        day,
        slot,
        subject,
        class_name
    )

    return record.status if record else None


def attendance_query(
    faculty=None,
    year=None,
    class_name=None,
    start_date=None,
    end_date=None,
    subject=None,
    slot=None,
    status=None
):
    query = Attendance.query

    if faculty:
        query = query.filter(Attendance.faculty == faculty)

    if year:
        query = query.filter(Attendance.year == year)

    if class_name:
        query = query.filter(Attendance.class_name == class_name)

    if start_date:
        query = query.filter(Attendance.record_date >= start_date)

    if end_date:
        query = query.filter(Attendance.record_date <= end_date)

    if subject:
        query = query.filter(Attendance.subject == subject)

    if slot:
        query = query.filter(Attendance.slot == slot)

    if status:
        query = query.filter(Attendance.status == status)

    return query.order_by(
        Attendance.record_date.desc(),
        Attendance.slot.asc(),
        Attendance.faculty.asc(),
        Attendance.year.asc(),
        Attendance.subject.asc()
    )


def attendance_stats(records):
    total = len(records)
    taken = sum(1 for x in records if x.status == "taken")
    not_taken = sum(1 for x in records if x.status == "not_taken")
    cancelled = sum(1 for x in records if x.status == "cancelled")

    # Attendance percentage is based on lectures marked Taken
    # out of all non-cancelled recorded lectures.
    denominator = taken + not_taken

    percentage = (
        taken / denominator * 100
        if denominator
        else 0
    )

    return {
        "total": total,
        "taken": taken,
        "not_taken": not_taken,
        "cancelled": cancelled,
        "percentage": percentage
    }


def subject_statistics(records):
    result = {}

    for record in records:
        key = record.subject

        if key not in result:
            result[key] = {
                "total": 0,
                "taken": 0,
                "not_taken": 0,
                "cancelled": 0
            }

        result[key]["total"] += 1

        if record.status == "taken":
            result[key]["taken"] += 1
        elif record.status == "not_taken":
            result[key]["not_taken"] += 1
        elif record.status == "cancelled":
            result[key]["cancelled"] += 1

    for key, value in result.items():
        denominator = value["taken"] + value["not_taken"]

        value["percentage"] = (
            value["taken"] / denominator * 100
            if denominator
            else 0
        )

    return result


def period_dates(period, custom_start=None, custom_end=None):
    today = today_ist()

    if period == "today":
        return today, today

    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)

    if period == "month":
        start = today.replace(day=1)

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

        return start, next_month - timedelta(days=1)

    if period == "year":
        return (
            today.replace(month=1, day=1),
            today.replace(month=12, day=31)
        )

    if period == "custom":
        try:
            start = datetime.strptime(
                custom_start or "",
                "%Y-%m-%d"
            ).date()

            end = datetime.strptime(
                custom_end or "",
                "%Y-%m-%d"
            ).date()

            if end < start:
                start, end = end, start

            return start, end
        except Exception:
            pass

    return today, today


# ============================================================
# HTML / CSS
# ============================================================

BASE_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">

<title>{{ page_title or "SGB College Management" }}</title>

<style>
:root {
    --bg: #f5f7fb;
    --card: #ffffff;
    --text: #172033;
    --muted: #667085;
    --border: #e5e7eb;
    --nav: #111827;
    --primary: #2563eb;
    --green: #16a34a;
    --red: #dc2626;
    --orange: #ea580c;
    --purple: #7c3aed;
}

* { box-sizing: border-box; }

body {
    margin: 0;
    font-family: Inter, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
}

a {
    color: inherit;
    text-decoration: none;
}

.navbar {
    position: sticky;
    top: 0;
    z-index: 1000;
    min-height: 64px;
    padding: 10px 18px;
    background: var(--nav);
    color: white;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.logo {
    font-weight: 900;
    font-size: 18px;
    white-space: nowrap;
}

.logo small {
    display: block;
    font-size: 9px;
    color: #9ca3af;
    letter-spacing: 1px;
    margin-top: 2px;
}

.nav-links {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    align-items: center;
}

.nav-links a {
    padding: 9px 10px;
    border-radius: 8px;
    font-size: 13px;
}

.nav-links a:hover {
    background: #1f2937;
}

.container {
    width: min(1250px, 94%);
    margin: auto;
    padding: 20px 0 45px;
}

.hero {
    background: linear-gradient(135deg, #2563eb, #7c3aed);
    color: white;
    padding: 25px;
    border-radius: 18px;
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

.hero .time {
    color: white;
    min-width: auto;
    margin-top: 8px;
}

.card,
.section,
.filters,
.stat {
    background: var(--card);
    border-radius: 14px;
    box-shadow: 0 2px 10px rgba(15, 23, 42, .06);
}

.section {
    padding: 18px;
    margin-bottom: 18px;
}

.section h2 {
    margin-top: 0;
}

.filters {
    padding: 16px;
    margin-bottom: 18px;
}

.filter-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 12px;
}

label {
    display: block;
    font-size: 12px;
    color: var(--muted);
    font-weight: 800;
    margin-bottom: 5px;
}

select,
input {
    width: 100%;
    padding: 10px 11px;
    border: 1px solid #d1d5db;
    border-radius: 9px;
    background: white;
    font-size: 14px;
}

button,
.btn {
    display: inline-block;
    border: 0;
    border-radius: 9px;
    padding: 10px 13px;
    cursor: pointer;
    font-weight: 800;
    font-size: 13px;
}

.btn-blue { background: var(--primary); color: white; }
.btn-green { background: var(--green); color: white; }
.btn-red { background: var(--red); color: white; }
.btn-orange { background: var(--orange); color: white; }
.btn-purple { background: var(--purple); color: white; }
.btn-gray { background: #e5e7eb; color: #172033; }

.btn-small {
    padding: 7px 9px;
    font-size: 11px;
}

.cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
    gap: 11px;
    margin-bottom: 18px;
}

.stat {
    padding: 16px;
}

.stat-title {
    color: var(--muted);
    font-size: 11px;
    font-weight: 900;
    text-transform: uppercase;
}

.stat-value {
    font-size: 25px;
    font-weight: 900;
    margin-top: 7px;
}

.green { color: var(--green); }
.red { color: var(--red); }
.orange { color: var(--orange); }
.blue { color: var(--primary); }
.purple { color: var(--purple); }

.lecture {
    border: 1px solid var(--border);
    border-left: 5px solid #94a3b8;
    border-radius: 11px;
    padding: 13px;
    margin-bottom: 9px;
    display: flex;
    align-items: center;
    gap: 12px;
}

.lecture.live {
    background: #ecfdf3;
    border-left-color: var(--green);
}

.lecture.next {
    background: #eff6ff;
    border-left-color: var(--primary);
}

.time {
    min-width: 125px;
    font-weight: 900;
    color: var(--primary);
}

.subject {
    flex: 1;
    font-weight: 900;
}

.meta {
    color: var(--muted);
    font-size: 12px;
    margin-top: 4px;
}

.badge {
    display: inline-block;
    padding: 5px 9px;
    border-radius: 30px;
    color: white;
    font-size: 10px;
    font-weight: 900;
    white-space: nowrap;
}

.badge-live,
.badge-taken { background: var(--green); }
.badge-not { background: var(--red); }
.badge-cancel { background: var(--orange); }
.badge-next { background: var(--primary); }
.badge-none { background: #64748b; }

.table-wrap {
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}

table {
    width: 100%;
    border-collapse: collapse;
    min-width: 760px;
}

th, td {
    padding: 10px;
    border-bottom: 1px solid var(--border);
    text-align: left;
    vertical-align: top;
}

th {
    background: #f3f4f6;
    font-size: 12px;
    position: sticky;
    top: 0;
    z-index: 2;
}

td {
    font-size: 13px;
}

.master-table th {
    text-align: center;
}

.master-table td {
    min-width: 150px;
}

.slot-cell {
    background: #f8fafc;
    font-weight: 900;
    min-width: 125px !important;
}

.lecture-cell {
    border-radius: 8px;
    padding: 8px;
    background: #f8fafc;
    margin-bottom: 6px;
}

.lecture-cell strong {
    display: block;
}

.current-cell {
    background: #ecfdf3;
    border: 1px solid #bbf7d0;
}

.progress {
    height: 8px;
    background: #e5e7eb;
    border-radius: 10px;
    overflow: hidden;
    margin-top: 6px;
}

.progress-bar {
    height: 100%;
    background: var(--green);
}

.alert {
    padding: 11px 14px;
    border-radius: 9px;
    margin-bottom: 14px;
    background: #eff6ff;
    color: #1d4ed8;
}

.empty {
    text-align: center;
    padding: 40px 15px;
    color: var(--muted);
}

.login-box {
    max-width: 430px;
    margin: 50px auto;
    padding: 25px;
    background: white;
    border-radius: 16px;
    box-shadow: 0 3px 18px rgba(0,0,0,.08);
}

.footer {
    text-align: center;
    color: var(--muted);
    font-size: 12px;
    padding: 25px;
}

.action-row {
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
}

.inline-form {
    display: inline;
}

.print-only {
    display: none;
}

.report-title {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
}

@media print {
    .navbar,
    .filters,
    .no-print,
    .footer {
        display: none !important;
    }

    body {
        background: white;
    }

    .container {
        width: 100%;
        padding: 0;
    }

    .section,
    .stat,
    .hero {
        box-shadow: none;
        border: 1px solid #ddd;
    }

    .print-only {
        display: block;
    }

    table {
        min-width: 0;
    }
}

@media (max-width: 700px) {
    .navbar {
        align-items: flex-start;
        flex-direction: column;
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

    .action-row .btn {
        flex: 1;
    }
}
</style>

<script>
function reloadLiveLecture() {
    const box = document.getElementById("live-data");
    if (!box) return;

    const faculty = box.dataset.faculty || "";
    const year = box.dataset.year || "";

    fetch(
        "/api/live?faculty=" +
        encodeURIComponent(faculty) +
        "&year=" +
        encodeURIComponent(year),
        {cache: "no-store"}
    )
    .then(r => r.json())
    .then(data => {
        const time = document.getElementById("live-clock");
        if (time) time.textContent = "India Time: " + data.time;

        const current = document.getElementById("current-live-list");
        const next = document.getElementById("next-live-list");

        if (current) {
            if (!data.current.length) {
                current.innerHTML =
                    '<div class="empty">No lecture running right now.</div>';
            } else {
                current.innerHTML = data.current.map(x => `
                    <div class="lecture live">
                        <div class="time">${escapeHtml(x.slot)}</div>
                        <div class="subject">
                            ${escapeHtml(x.subject)}
                            <div class="meta">
                                ${escapeHtml(x.faculty)} •
                                ${escapeHtml(x.year)}
                                ${x.class_name ? " • " + escapeHtml(x.class_name) : ""}
                                ${x.teacher ? " • " + escapeHtml(x.teacher) : ""}
                                ${x.room ? " • Room " + escapeHtml(x.room) : ""}
                            </div>
                        </div>
                        <span class="badge badge-live">LIVE NOW</span>
                    </div>
                `).join("");
            }
        }

        if (next) {
            if (!data.next.length) {
                next.innerHTML =
                    '<div class="empty">No more lectures today.</div>';
            } else {
                next.innerHTML = data.next.slice(0, 3).map(x => `
                    <div class="lecture next">
                        <div class="time">${escapeHtml(x.slot)}</div>
                        <div class="subject">
                            ${escapeHtml(x.subject)}
                            <div class="meta">
                                ${escapeHtml(x.faculty)} •
                                ${escapeHtml(x.year)}
                                ${x.class_name ? " • " + escapeHtml(x.class_name) : ""}
                                ${x.teacher ? " • " + escapeHtml(x.teacher) : ""}
                            </div>
                        </div>
                        <span class="badge badge-next">NEXT</span>
                    </div>
                `).join("");
            }
        }
    })
    .catch(() => {});
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

setInterval(reloadLiveLecture, 15000);
</script>
</head>

<body>

<nav class="navbar">
    <a href="{{ url_for('home') }}">
        <div class="logo">
            🎓 SGB COLLEGE
            <small>COLLEGE MANAGEMENT SYSTEM</small>
        </div>
    </a>

    <div class="nav-links">
        <a href="{{ url_for('home') }}">🏠 Dashboard</a>
        <a href="{{ url_for('master_timetable') }}">📚 All Classes</a>
        <a href="{{ url_for('timetable_page') }}">📅 Daily Timetable</a>

        {% if current_user_obj and current_user_obj.is_admin %}
            <a href="{{ url_for('attendance') }}">📝 Attendance</a>
            <a href="{{ url_for('reports') }}">📊 Reports</a>
            <a href="{{ url_for('access_control') }}">👥 Users</a>
            <a href="{{ url_for('timetable_manage') }}">⚙ Manage Timetable</a>
            <a href="{{ url_for('logout') }}">Logout</a>
        {% else %}
            <a href="{{ url_for('login') }}">🔐 Admin Login</a>
        {% endif %}
    </div>
</nav>

<div class="container">

{% with messages = get_flashed_messages() %}
    {% if messages %}
        {% for message in messages %}
            <div class="alert">{{ message }}</div>
        {% endfor %}
    {% endif %}
{% endwith %}

{{ content|safe }}

</div>

<div class="footer">
    SGB College Management System
    <br>
    Timetable • Current Lecture • Attendance • Reports
</div>

</body>
</html>
"""


def render_page(content, **context):
    body = render_template_string(content, **context)

    return render_template_string(
        BASE_HTML,
        content=body,
        current_user_obj=current_user(),
        page_title=context.pop(
            "page_title",
            "SGB College Management"
        ),
        **context
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/")
def home():
    faculties = all_faculties()

    faculty = request.args.get(
        "faculty",
        faculties[0] if faculties else ""
    )

    years = years_for_faculty(faculty)

    year = request.args.get(
        "year",
        years[0] if years else ""
    )

    today_name = now_ist().strftime("%A")

    today_rows = get_day_lectures(
        faculty,
        year,
        today_name
    )

    current = get_current_lectures(
        faculty,
        year
    )

    upcoming = get_next_lectures(
        faculty,
        year
    )

    records_today = attendance_query(
        faculty=faculty,
        year=year,
        start_date=today_ist(),
        end_date=today_ist()
    ).all()

    stats = attendance_stats(records_today)

    content = r"""
<div class="hero">
    <h1>🎓 SGB College Dashboard</h1>
    <p>Timetable, live lecture and permanent attendance management</p>
    <div class="time" id="live-clock">
        India Time: {{ now_time }}
    </div>
</div>

<form class="filters" method="get">
    <div class="filter-grid">
        <div>
            <label>Faculty</label>
            <select name="faculty" onchange="this.form.submit()">
                {% for f in faculties %}
                    <option value="{{ f }}" {% if f == faculty %}selected{% endif %}>
                        {{ f }}
                    </option>
                {% endfor %}
            </select>
        </div>

        <div>
            <label>Year</label>
            <select name="year" onchange="this.form.submit()">
                {% for y in years %}
                    <option value="{{ y }}" {% if y == year %}selected{% endif %}>
                        {{ y }}
                    </option>
                {% endfor %}
            </select>
        </div>
    </div>
</form>

<div
    id="live-data"
    data-faculty="{{ faculty }}"
    data-year="{{ year }}"
>
</div>

<div class="cards">
    <div class="stat">
        <div class="stat-title">Current Lecture</div>
        <div class="stat-value green">
            {% if current %}LIVE{% else %}—{% endif %}
        </div>
    </div>

    <div class="stat">
        <div class="stat-title">Next Lecture</div>
        <div class="stat-value blue">
            {% if upcoming %}{{ upcoming[0].slot }}{% else %}—{% endif %}
        </div>
    </div>

    <div class="stat">
        <div class="stat-title">Today's Lectures</div>
        <div class="stat-value purple">{{ today_rows|length }}</div>
    </div>

    <div class="stat">
        <div class="stat-title">Taken Today</div>
        <div class="stat-value green">{{ stats.taken }}</div>
    </div>

    <div class="stat">
        <div class="stat-title">Not Taken</div>
        <div class="stat-value red">{{ stats.not_taken }}</div>
    </div>

    <div class="stat">
        <div class="stat-title">Cancelled</div>
        <div class="stat-value orange">{{ stats.cancelled }}</div>
    </div>

    <div class="stat">
        <div class="stat-title">Attendance %</div>
        <div class="stat-value blue">
            {{ "%.1f"|format(stats.percentage) }}%
        </div>
    </div>
</div>

<div class="section">
    <div class="report-title">
        <h2>🟢 Current Lecture</h2>
        <span class="badge badge-live">AUTO UPDATE</span>
    </div>

    <div id="current-live-list">
        {% if current %}
            {% for row in current %}
                <div class="lecture live">
                    <div class="time">{{ row.slot }}</div>

                    <div class="subject">
                        {{ row.subject }}

                        <div class="meta">
                            {{ row.faculty }} • {{ row.year }}
                            {% if row.class_name %} • {{ row.class_name }}{% endif %}
                            {% if row.teacher %} • {{ row.teacher }}{% endif %}
                            {% if row.room %} • Room {{ row.room }}{% endif %}
                        </div>
                    </div>

                    <span class="badge badge-live">LIVE NOW</span>
                </div>
            {% endfor %}
        {% else %}
            <div class="empty">No lecture running right now.</div>
        {% endif %}
    </div>
</div>

<div class="section">
    <div class="report-title">
        <h2>⏭ Next Lecture</h2>
    </div>

    <div id="next-live-list">
        {% if upcoming %}
            {% for row in upcoming[:3] %}
                <div class="lecture next">
                    <div class="time">{{ row.slot }}</div>

                    <div class="subject">
                        {{ row.subject }}

                        <div class="meta">
                            {{ row.faculty }} • {{ row.year }}
                            {% if row.class_name %} • {{ row.class_name }}{% endif %}
                            {% if row.teacher %} • {{ row.teacher }}{% endif %}
                        </div>
                    </div>

                    <span class="badge badge-next">NEXT</span>
                </div>
            {% endfor %}
        {% else %}
            <div class="empty">No more lectures today.</div>
        {% endif %}
    </div>
</div>

<div class="section">
    <div class="report-title">
        <h2>📅 Today's Timetable</h2>
        <a class="btn btn-blue" href="{{ url_for('timetable_page', faculty=faculty, year=year, day=today_name) }}">
            Open Daily Timetable
        </a>
    </div>

    {% if today_rows %}
        {% for row in today_rows %}
            <div class="lecture {% if is_current_slot(row.slot, today_name) %}live{% endif %}">
                <div class="time">{{ row.slot }}</div>

                <div class="subject">
                    {{ row.subject }}
                    <div class="meta">
                        {% if row.teacher %}Teacher: {{ row.teacher }}{% endif %}
                        {% if row.class_name %} • Class: {{ row.class_name }}{% endif %}
                        {% if row.room %} • Room: {{ row.room }}{% endif %}
                    </div>
                </div>

                {% if is_current_slot(row.slot, today_name) %}
                    <span class="badge badge-live">LIVE</span>
                {% endif %}
            </div>
        {% endfor %}
    {% else %}
        <div class="empty">No timetable available for today.</div>
    {% endif %}
</div>
"""

    return render_page(
        content,
        faculties=faculties,
        faculty=faculty,
        years=years,
        year=year,
        today_name=today_name,
        current=current,
        upcoming=upcoming,
        today_rows=today_rows,
        stats=stats,
        is_current_slot=is_current_slot,
        now_time=now_ist().strftime("%d-%m-%Y %I:%M:%S %p"),
        page_title="Dashboard"
    )


# ============================================================
# LIVE API
# ============================================================

@app.route("/api/live")
def api_live():
    faculties = all_faculties()

    faculty = request.args.get(
        "faculty",
        faculties[0] if faculties else ""
    )

    years = years_for_faculty(faculty)

    year = request.args.get(
        "year",
        years[0] if years else ""
    )

    return live_payload(faculty, year)


# ============================================================
# MASTER TIMETABLE
# ============================================================

@app.route("/master")
def master_timetable():
    faculties = all_faculties()

    faculty = request.args.get(
        "faculty",
        ""
    )

    year = request.args.get(
        "year",
        ""
    )

    if faculty:
        years = years_for_faculty(faculty)
    else:
        years = ordered_years(
            [
                row[0]
                for row in db.session.query(Timetable.year)
                .distinct()
                .all()
            ]
        )

    # Build row/column matrix:
    # rows = time slots
    # columns = Monday-Saturday
    query = Timetable.query

    if faculty:
        query = query.filter(Timetable.faculty == faculty)

    if year:
        query = query.filter(Timetable.year == year)

    rows = query.all()

    slots = sorted(
        set(row.slot for row in rows),
        key=slot_start
    )

    matrix = {}

    for slot in slots:
        matrix[slot] = {}

        for day in DAYS:
            matrix[slot][day] = [
                row for row in rows
                if row.slot == slot and row.day == day
            ]

    content = r"""
<div class="hero">
    <h1>📚 ALL CLASS / MASTER TIMETABLE</h1>
    <p>Rows = time slots • Columns = Monday to Saturday</p>
</div>

<form class="filters" method="get">
    <div class="filter-grid">

        <div>
            <label>Faculty</label>
            <select name="faculty" onchange="this.form.submit()">
                <option value="">All Faculties</option>
                {% for f in faculties %}
                    <option value="{{ f }}" {% if f == faculty %}selected{% endif %}>
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
                    <option value="{{ y }}" {% if y == year %}selected{% endif %}>
                        {{ y }}
                    </option>
                {% endfor %}
            </select>
        </div>

        <div>
            <label>&nbsp;</label>
            <button class="btn btn-blue" type="submit">
                Filter Timetable
            </button>
        </div>

        <div>
            <label>&nbsp;</label>
            <a class="btn btn-gray" href="{{ url_for('master_timetable') }}">
                Show All
            </a>
        </div>
    </div>
</form>

<div class="section">
    <div class="report-title">
        <h2>
            Master Timetable
            {% if faculty %} • {{ faculty }}{% endif %}
            {% if year %} • {{ year }}{% endif %}
        </h2>

        <a class="btn btn-purple" href="{{ url_for('timetable_page', faculty=faculty, year=year) }}">
            Daily View
        </a>
    </div>

    {% if slots %}
        <div class="table-wrap">
            <table class="master-table">
                <thead>
                    <tr>
                        <th>Time</th>
                        {% for day in days %}
                            <th>{{ day }}</th>
                        {% endfor %}
                    </tr>
                </thead>

                <tbody>
                    {% for slot in slots %}
                        <tr>
                            <td class="slot-cell">
                                {{ slot }}
                            </td>

                            {% for day in days %}
                                <td>
                                    {% for row in matrix[slot][day] %}
                                        <div class="lecture-cell {% if is_current_slot(row.slot, day) %}current-cell{% endif %}">
                                            <strong>{{ row.subject }}</strong>

                                            <div class="meta">
                                                {{ row.faculty }} • {{ row.year }}
                                            </div>

                                            {% if row.class_name %}
                                                <div class="meta">
                                                    Class: {{ row.class_name }}
                                                </div>
                                            {% endif %}

                                            {% if row.teacher %}
                                                <div class="meta">
                                                    Teacher: {{ row.teacher }}
                                                </div>
                                            {% endif %}

                                            {% if row.room %}
                                                <div class="meta">
                                                    Room: {{ row.room }}
                                                </div>
                                            {% endif %}

                                            {% if is_current_slot(row.slot, day) %}
                                                <br>
                                                <span class="badge badge-live">LIVE</span>
                                            {% endif %}
                                        </div>
                                    {% else %}
                                        <span style="color:#94a3b8;">—</span>
                                    {% endfor %}
                                </td>
                            {% endfor %}
                        </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    {% else %}
        <div class="empty">
            No timetable records found.
        </div>
    {% endif %}
</div>
"""

    return render_page(
        content,
        faculties=faculties,
        years=years,
        faculty=faculty,
        year=year,
        days=DAYS,
        slots=slots,
        matrix=matrix,
        is_current_slot=is_current_slot,
        page_title="Master Timetable"
    )


# Alias requested wording.
app.add_url_rule(
    "/all-classes",
    endpoint="all_classes",
    view_func=master_timetable
)


# ============================================================
# DAILY TIMETABLE
# ============================================================

@app.route("/timetable")
def timetable_page():
    faculties = all_faculties()

    faculty = request.args.get(
        "faculty",
        faculties[0] if faculties else ""
    )

    years = years_for_faculty(faculty)

    year = request.args.get(
        "year",
        years[0] if years else ""
    )

    day = request.args.get(
        "day",
        now_ist().strftime("%A")
    )

    if day not in DAYS:
        day = "Monday"

    rows = get_day_lectures(
        faculty,
        year,
        day
    )

    content = r"""
<div class="hero">
    <h1>📅 Daily Timetable</h1>
    <p>{{ faculty }} • {{ year }} • {{ day }}</p>
</div>

<form class="filters" method="get">
    <div class="filter-grid">

        <div>
            <label>Faculty</label>
            <select name="faculty" onchange="this.form.submit()">
                {% for f in faculties %}
                    <option value="{{ f }}" {% if f == faculty %}selected{% endif %}>
                        {{ f }}
                    </option>
                {% endfor %}
            </select>
        </div>

        <div>
            <label>Year</label>
            <select name="year" onchange="this.form.submit()">
                {% for y in years %}
                    <option value="{{ y }}" {% if y == year %}selected{% endif %}>
                        {{ y }}
                    </option>
                {% endfor %}
            </select>
        </div>

        <div>
            <label>Day</label>
            <select name="day" onchange="this.form.submit()">
                {% for d in days %}
                    <option value="{{ d }}" {% if d == day %}selected{% endif %}>
                        {{ d }}
                    </option>
                {% endfor %}
            </select>
        </div>
    </div>
</form>

<div class="section">
    <div class="report-title">
        <h2>{{ day }} Schedule</h2>
        <a class="btn btn-purple" href="{{ url_for('master_timetable', faculty=faculty, year=year) }}">
            Master Timetable
        </a>
    </div>

    {% if rows %}
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Faculty</th>
                        <th>Year</th>
                        <th>Class</th>
                        <th>Subject</th>
                        <th>Teacher</th>
                        <th>Room</th>
                        <th>Live</th>
                    </tr>
                </thead>

                <tbody>
                    {% for row in rows %}
                        <tr>
                            <td><strong>{{ row.slot }}</strong></td>
                            <td>{{ row.faculty }}</td>
                            <td>{{ row.year }}</td>
                            <td>{{ row.class_name or "—" }}</td>
                            <td><strong>{{ row.subject }}</strong></td>
                            <td>{{ row.teacher or "—" }}</td>
                            <td>{{ row.room or "—" }}</td>
                            <td>
                                {% if is_current_slot(row.slot, day) %}
                                    <span class="badge badge-live">LIVE</span>
                                {% else %}
                                    —
                                {% endif %}
                            </td>
                        </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    {% else %}
        <div class="empty">
            No timetable available.
        </div>
    {% endif %}
</div>
"""

    return render_page(
        content,
        faculties=faculties,
        years=years,
        faculty=faculty,
        year=year,
        day=day,
        days=DAYS,
        rows=rows,
        is_current_slot=is_current_slot,
        page_title="Daily Timetable"
    )


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(
            user.password_hash,
            password
        ):
            session.clear()
            session["user_id"] = user.id

            next_url = request.args.get("next")

            if next_url and next_url.startswith("/"):
                return redirect(next_url)

            return redirect(url_for("home"))

        flash("Invalid username or password.")

    content = r"""
<div class="login-box">
    <h1>🔐 Admin Login</h1>

    <p>
        Login is required for attendance, reports and timetable management.
    </p>

    <form method="post">
        <label>Username</label>
        <input name="username" required autocomplete="username">

        <br><br>

        <label>Password</label>
        <input type="password" name="password" required autocomplete="current-password">

        <br><br>

        <button class="btn btn-blue" type="submit">
            Login
        </button>
    </form>

    <br>

    <p style="font-size:12px;color:#667085;">
        Students and visitors can view the timetable and live lecture
        without administrative access.
    </p>
</div>
"""

    return render_page(
        content,
        page_title="Admin Login"
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ============================================================
# ATTENDANCE PAGE
# ============================================================

@app.route("/attendance")
@admin_required
def attendance():
    faculties = all_faculties()

    faculty = request.args.get(
        "faculty",
        faculties[0] if faculties else ""
    )

    years = years_for_faculty(faculty)

    year = request.args.get(
        "year",
        years[0] if years else ""
    )

    day = request.args.get(
        "day",
        now_ist().strftime("%A")
    )

    record_date_text = request.args.get(
        "record_date",
        today_ist().isoformat()
    )

    try:
        record_date = datetime.strptime(
            record_date_text,
            "%Y-%m-%d"
        ).date()
    except Exception:
        record_date = today_ist()
        record_date_text = record_date.isoformat()

    if day not in DAYS:
        day = "Monday"

    rows = get_day_lectures(
        faculty,
        year,
        day
    )

    content = r"""
<div class="hero">
    <h1>📝 Attendance Management</h1>
    <p>Administrator-only lecture attendance</p>
</div>

<form class="filters" method="get">
    <div class="filter-grid">

        <div>
            <label>Faculty</label>
            <select name="faculty" onchange="this.form.submit()">
                {% for f in faculties %}
                    <option value="{{ f }}" {% if f == faculty %}selected{% endif %}>
                        {{ f }}
                    </option>
                {% endfor %}
            </select>
        </div>

        <div>
            <label>Year</label>
            <select name="year" onchange="this.form.submit()">
                {% for y in years %}
                    <option value="{{ y }}" {% if y == year %}selected{% endif %}>
                        {{ y }}
                    </option>
                {% endfor %}
            </select>
        </div>

        <div>
            <label>Day</label>
            <select name="day" onchange="this.form.submit()">
                {% for d in days %}
                    <option value="{{ d }}" {% if d == day %}selected{% endif %}>
                        {{ d }}
                    </option>
                {% endfor %}
            </select>
        </div>

        <div>
            <label>Attendance Date</label>
            <input
                type="date"
                name="record_date"
                value="{{ record_date_text }}"
                onchange="this.form.submit()"
            >
        </div>
    </div>
</form>

<div class="section">
    <div class="report-title">
        <h2>
            {{ day }} • {{ record_date_text }}
        </h2>

        <a class="btn btn-blue" href="{{ url_for('reports', faculty=faculty, year=year) }}">
            View Reports
        </a>
    </div>

    {% if rows %}
        {% for row in rows %}
            {% set status = attendance_status_for(
                record_date,
                row.faculty,
                row.year,
                row.day,
                row.slot,
                row.subject,
                row.class_name or ""
            ) %}

            <div class="lecture">
                <div class="time">
                    {{ row.slot }}
                </div>

                <div class="subject">
                    {{ row.subject }}

                    <div class="meta">
                        {{ row.faculty }} • {{ row.year }}
                        {% if row.class_name %} • {{ row.class_name }}{% endif %}
                        {% if row.teacher %} • {{ row.teacher }}{% endif %}
                    </div>

                    <div style="margin-top:7px;">
                        {% if status == "taken" %}
                            <span class="badge badge-taken">✓ TAKEN</span>
                        {% elif status == "not_taken" %}
                            <span class="badge badge-not">✕ NOT TAKEN</span>
                        {% elif status == "cancelled" %}
                            <span class="badge badge-cancel">CANCELLED</span>
                        {% else %}
                            <span class="badge badge-none">NOT MARKED</span>
                        {% endif %}
                    </div>
                </div>

                <div class="action-row">
                    <form method="post" action="{{ url_for('mark_attendance') }}">
                        <input type="hidden" name="record_date" value="{{ record_date_text }}">
                        <input type="hidden" name="faculty" value="{{ row.faculty }}">
                        <input type="hidden" name="year" value="{{ row.year }}">
                        <input type="hidden" name="day" value="{{ row.day }}">
                        <input type="hidden" name="slot" value="{{ row.slot }}">
                        <input type="hidden" name="subject" value="{{ row.subject }}">
                        <input type="hidden" name="class_name" value="{{ row.class_name or '' }}">
                        <input type="hidden" name="teacher" value="{{ row.teacher or '' }}">

                        <button class="btn btn-green btn-small" name="status" value="taken">
                            ✓ Taken
                        </button>

                        <button class="btn btn-red btn-small" name="status" value="not_taken">
                            ✕ Not Taken
                        </button>

                        <button class="btn btn-orange btn-small" name="status" value="cancelled">
                            Cancelled
                        </button>

                        <button
                            class="btn btn-gray btn-small"
                            name="status"
                            value="clear"
                            onclick="return confirm('Remove this saved attendance record?')"
                        >
                            Undo
                        </button>
                    </form>
                </div>
            </div>
        {% endfor %}
    {% else %}
        <div class="empty">No lectures scheduled.</div>
    {% endif %}
</div>
"""

    return render_page(
        content,
        faculties=faculties,
        years=years,
        faculty=faculty,
        year=year,
        day=day,
        days=DAYS,
        rows=rows,
        record_date=record_date,
        record_date_text=record_date_text,
        attendance_status_for=attendance_status_for,
        page_title="Attendance"
    )


# ============================================================
# MARK / EDIT ATTENDANCE
# ============================================================

@app.route("/attendance/mark", methods=["POST"])
@admin_required
def mark_attendance():
    try:
        record_date = datetime.strptime(
            request.form.get("record_date", ""),
            "%Y-%m-%d"
        ).date()
    except Exception:
        flash("Invalid attendance date.")
        return redirect(url_for("attendance"))

    faculty = request.form.get("faculty", "").strip()
    year = request.form.get("year", "").strip()
    day = request.form.get("day", "").strip()
    slot = request.form.get("slot", "").strip()
    subject = request.form.get("subject", "").strip()
    class_name = request.form.get("class_name", "").strip()
    teacher = request.form.get("teacher", "").strip()
    status = request.form.get("status", "").strip()

    if not all([faculty, year, day, slot, subject]):
        flash("Incomplete lecture information.")
        return redirect(url_for("attendance"))

    if day not in DAYS:
        flash("Invalid day.")
        return redirect(url_for("attendance"))

    user = current_user()

    record = attendance_record_for(
        record_date,
        faculty,
        year,
        day,
        slot,
        subject,
        class_name
    )

    if status == "clear":
        if record:
            db.session.delete(record)
            db.session.commit()
            flash("Attendance record removed.")
        else:
            flash("No saved attendance record to remove.")

    elif status in VALID_STATUSES:
        if record:
            record.status = status
            record.teacher = teacher
            record.marked_by_user_id = user.id
            record.marked_by = user.name
            record.marked_at = now_ist_naive()
        else:
            record = Attendance(
                record_date=record_date,
                faculty=faculty,
                year=year,
                class_name=class_name,
                day=day,
                slot=slot,
                subject=subject,
                teacher=teacher,
                status=status,
                marked_by_user_id=user.id,
                marked_by=user.name,
                marked_at=now_ist_naive()
            )
            db.session.add(record)

        db.session.commit()

        flash(
            f"{subject} — {VALID_STATUSES[status]} "
            f"for {record_date.strftime('%d-%m-%Y')}."
        )

    else:
        flash("Invalid attendance status.")

    return redirect(
        url_for(
            "attendance",
            faculty=faculty,
            year=year,
            day=day,
            record_date=record_date.isoformat()
        )
    )


# ============================================================
# REPORTS
# ============================================================

@app.route("/reports")
@admin_required
def reports():
    faculties = all_faculties()

    faculty = request.args.get(
        "faculty",
        faculties[0] if faculties else ""
    )

    years = years_for_faculty(faculty)

    year = request.args.get(
        "year",
        years[0] if years else ""
    )

    class_name = request.args.get(
        "class_name",
        ""
    ).strip()

    period = request.args.get(
        "period",
        "month"
    )

    subject = request.args.get(
        "subject",
        ""
    ).strip()

    slot = request.args.get(
        "slot",
        ""
    ).strip()

    status = request.args.get(
        "status",
        ""
    ).strip()

    custom_start = request.args.get(
        "start_date",
        ""
    )

    custom_end = request.args.get(
        "end_date",
        ""
    )

    start_date, end_date = period_dates(
        period,
        custom_start,
        custom_end
    )

    records = attendance_query(
        faculty=faculty,
        year=year,
        class_name=class_name,
        start_date=start_date,
        end_date=end_date,
        subject=subject,
        slot=slot,
        status=status
    ).all()

    stats = attendance_stats(records)
    subject_stats = subject_statistics(records)

    classes = classes_for_filters(
        faculty,
        year
    )

    subjects = subjects_for_filters(
        faculty,
        year
    )

    slots = slots_for_filters(
        faculty,
        year
    )

    content = r"""
<div class="hero">
    <h1>📊 Attendance Reports</h1>
    <p>Retrieve permanently saved attendance records at any time</p>
</div>

<form class="filters" method="get">
    <div class="filter-grid">

        <div>
            <label>Faculty</label>
            <select name="faculty">
                {% for f in faculties %}
                    <option value="{{ f }}" {% if f == faculty %}selected{% endif %}>
                        {{ f }}
                    </option>
                {% endfor %}
            </select>
        </div>

        <div>
            <label>Year</label>
            <select name="year">
                {% for y in years %}
                    <option value="{{ y }}" {% if y == year %}selected{% endif %}>
                        {{ y }}
                    </option>
                {% endfor %}
            </select>
        </div>

        <div>
            <label>Class</label>
            <select name="class_name">
                <option value="">All Classes</option>
                {% for c in classes %}
                    <option value="{{ c }}" {% if c == class_name %}selected{% endif %}>
                        {{ c }}
                    </option>
                {% endfor %}
            </select>
        </div>

        <div>
            <label>Period</label>
            <select name="period">
                <option value="today" {% if period == "today" %}selected{% endif %}>Today</option>
                <option value="week" {% if period == "week" %}selected{% endif %}>This Week</option>
                <option value="month" {% if period == "month" %}selected{% endif %}>This Month</option>
                <option value="year" {% if period == "year" %}selected{% endif %}>This Year</option>
                <option value="custom" {% if period == "custom" %}selected{% endif %}>Custom Date Range</option>
            </select>
        </div>

        <div>
            <label>Subject</label>
            <select name="subject">
                <option value="">All Subjects</option>
                {% for s in subjects %}
                    <option value="{{ s }}" {% if s == subject %}selected{% endif %}>
                        {{ s }}
                    </option>
                {% endfor %}
            </select>
        </div>

        <div>
            <label>Lecture / Time</label>
            <select name="slot">
                <option value="">All Lectures</option>
                {% for s in slots %}
                    <option value="{{ s }}" {% if s == slot %}selected{% endif %}>
                        {{ s }}
                    </option>
                {% endfor %}
            </select>
        </div>

        <div>
            <label>Status</label>
            <select name="status">
                <option value="">All Statuses</option>
                <option value="taken" {% if status == "taken" %}selected{% endif %}>Taken</option>
                <option value="not_taken" {% if status == "not_taken" %}selected{% endif %}>Not Taken</option>
                <option value="cancelled" {% if status == "cancelled" %}selected{% endif %}>Cancelled</option>
            </select>
        </div>

        <div>
            <label>Start Date</label>
            <input type="date" name="start_date" value="{{ custom_start }}">
        </div>

        <div>
            <label>End Date</label>
            <input type="date" name="end_date" value="{{ custom_end }}">
        </div>

        <div>
            <label>&nbsp;</label>
            <button class="btn btn-blue" type="submit">
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
                    class_name=class_name,
                    period=period,
                    subject=subject,
                    slot=slot,
                    status=status,
                    start_date=custom_start,
                    end_date=custom_end
                ) }}"
            >
                ⬇ Export CSV
            </a>
        </div>

        <div>
            <label>&nbsp;</label>
            <button
                class="btn btn-purple"
                type="button"
                onclick="window.print()"
            >
                🖨 Print
            </button>
        </div>
    </div>
</form>

<div class="section print-only">
    <h2>SGB College Attendance Report</h2>
    <p>
        {{ faculty }} • {{ year }}
        {% if class_name %} • {{ class_name }}{% endif %}
    </p>
    <p>
        Date Range: {{ start_date }} to {{ end_date }}
    </p>
</div>

<div class="cards">
    <div class="stat">
        <div class="stat-title">Total Records</div>
        <div class="stat-value blue">{{ stats.total }}</div>
    </div>

    <div class="stat">
        <div class="stat-title">Taken</div>
        <div class="stat-value green">{{ stats.taken }}</div>
    </div>

    <div class="stat">
        <div class="stat-title">Not Taken</div>
        <div class="stat-value red">{{ stats.not_taken }}</div>
    </div>

    <div class="stat">
        <div class="stat-title">Cancelled</div>
        <div class="stat-value orange">{{ stats.cancelled }}</div>
    </div>

    <div class="stat">
        <div class="stat-title">Attendance %</div>
        <div class="stat-value purple">
            {{ "%.1f"|format(stats.percentage) }}%
        </div>
    </div>
</div>

<div class="section">
    <div class="report-title">
        <h2>📚 Subject Summary</h2>
        <span class="meta">
            {{ start_date }} → {{ end_date }}
        </span>
    </div>

    {% if subject_stats %}
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Subject</th>
                        <th>Total Lectures</th>
                        <th>Taken</th>
                        <th>Not Taken</th>
                        <th>Cancelled</th>
                        <th>Attendance %</th>
                    </tr>
                </thead>

                <tbody>
                    {% for name, data in subject_stats.items() %}
                        <tr>
                            <td><strong>{{ name }}</strong></td>
                            <td>{{ data.total }}</td>
                            <td class="green">{{ data.taken }}</td>
                            <td class="red">{{ data.not_taken }}</td>
                            <td class="orange">{{ data.cancelled }}</td>
                            <td>
                                {{ "%.1f"|format(data.percentage) }}%

                                <div class="progress">
                                    <div
                                        class="progress-bar"
                                        style="width:{{ [data.percentage, 100]|min }}%;"
                                    ></div>
                                </div>
                            </td>
                        </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    {% else %}
        <div class="empty">No attendance records found.</div>
    {% endif %}
</div>

<div class="section">
    <div class="report-title">
        <h2>📝 Detailed Attendance Records</h2>
        <span class="meta">
            {{ records|length }} record(s)
        </span>
    </div>

    {% if records %}
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Day</th>
                        <th>Time / Lecture</th>
                        <th>Faculty</th>
                        <th>Year</th>
                        <th>Class</th>
                        <th>Subject</th>
                        <th>Teacher</th>
                        <th>Status</th>
                        <th>Marked By</th>
                        <th>Marked At</th>
                    </tr>
                </thead>

                <tbody>
                    {% for r in records %}
                        <tr>
                            <td>{{ r.record_date.strftime("%d-%m-%Y") }}</td>
                            <td>{{ r.day }}</td>
                            <td>{{ r.slot }}</td>
                            <td>{{ r.faculty }}</td>
                            <td>{{ r.year }}</td>
                            <td>{{ r.class_name or "—" }}</td>
                            <td><strong>{{ r.subject }}</strong></td>
                            <td>{{ r.teacher or "—" }}</td>

                            <td>
                                {% if r.status == "taken" %}
                                    <span class="badge badge-taken">TAKEN</span>
                                {% elif r.status == "not_taken" %}
                                    <span class="badge badge-not">NOT TAKEN</span>
                                {% else %}
                                    <span class="badge badge-cancel">CANCELLED</span>
                                {% endif %}
                            </td>

                            <td>{{ r.marked_by or "—" }}</td>

                            <td>
                                {{ r.marked_at.strftime("%d-%m-%Y %I:%M:%S %p") if r.marked_at else "—" }}
                            </td>
                        </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    {% else %}
        <div class="empty">
            No saved attendance records match the selected filters.
        </div>
    {% endif %}
</div>
"""

    return render_page(
        content,
        faculties=faculties,
        years=years,
        faculty=faculty,
        year=year,
        class_name=class_name,
        period=period,
        subject=subject,
        slot=slot,
        status=status,
        custom_start=custom_start,
        custom_end=custom_end,
        start_date=start_date,
        end_date=end_date,
        records=records,
        stats=stats,
        subject_stats=subject_stats,
        classes=classes,
        subjects=subjects,
        slots=slots,
        page_title="Attendance Reports"
    )


# ============================================================
# CSV EXPORT
# ============================================================

@app.route("/reports/export.csv")
@admin_required
def export_csv():
    faculties = all_faculties()

    faculty = request.args.get(
        "faculty",
        faculties[0] if faculties else ""
    )

    years = years_for_faculty(faculty)

    year = request.args.get(
        "year",
        years[0] if years else ""
    )

    class_name = request.args.get(
        "class_name",
        ""
    ).strip()

    period = request.args.get(
        "period",
        "month"
    )

    subject = request.args.get(
        "subject",
        ""
    ).strip()

    slot = request.args.get(
        "slot",
        ""
    ).strip()

    status = request.args.get(
        "status",
        ""
    ).strip()

    custom_start = request.args.get(
        "start_date",
        ""
    )

    custom_end = request.args.get(
        "end_date",
        ""
    )

    start_date, end_date = period_dates(
        period,
        custom_start,
        custom_end
    )

    records = attendance_query(
        faculty=faculty,
        year=year,
        class_name=class_name,
        start_date=start_date,
        end_date=end_date,
        subject=subject,
        slot=slot,
        status=status
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Date",
        "Day",
        "Time / Lecture",
        "Faculty",
        "Year",
        "Class",
        "Subject",
        "Teacher",
        "Status",
        "Marked By",
        "Marked At"
    ])

    for r in records:
        writer.writerow([
            r.record_date.isoformat(),
            r.day,
            r.slot,
            r.faculty,
            r.year,
            r.class_name or "",
            r.subject,
            r.teacher or "",
            VALID_STATUSES.get(r.status, r.status),
            r.marked_by or "",
            r.marked_at.strftime("%Y-%m-%d %H:%M:%S")
            if r.marked_at else ""
        ])

    filename = (
        f"SGB_Attendance_{start_date}_{end_date}.csv"
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
# ADMIN USER / ACCESS CONTROL
# ============================================================

@app.route("/access", methods=["GET", "POST"])
@admin_required
def access_control():
    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "create":
            name = request.form.get("name", "").strip()
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            if not name or not username or not password:
                flash("Name, username and password are required.")
            elif User.query.filter_by(username=username).first():
                flash("Username already exists.")
            else:
                user = User(
                    name=name,
                    username=username,
                    password_hash=generate_password_hash(password),
                    is_admin=False
                )

                db.session.add(user)
                db.session.commit()

                flash("User created successfully.")

        elif action == "make_admin":
            try:
                user_id = int(request.form.get("user_id", "0"))
            except Exception:
                user_id = 0

            user = db.session.get(User, user_id)

            if user:
                user.is_admin = True
                db.session.commit()
                flash("User promoted to administrator.")

        elif action == "remove_admin":
            try:
                user_id = int(request.form.get("user_id", "0"))
            except Exception:
                user_id = 0

            user = db.session.get(User, user_id)

            if user and user.username != ADMIN_USERNAME:
                user.is_admin = False
                db.session.commit()
                flash("Administrator permission removed.")

        elif action == "delete":
            try:
                user_id = int(request.form.get("user_id", "0"))
            except Exception:
                user_id = 0

            user = db.session.get(User, user_id)

            if user and user.username != ADMIN_USERNAME:
                db.session.delete(user)
                db.session.commit()
                flash("User deleted.")

    users = User.query.order_by(User.id.asc()).all()

    content = r"""
<div class="hero">
    <h1>👥 User Management</h1>
    <p>Manage administrator accounts and permissions</p>
</div>

<div class="section">
    <h2>➕ Add User</h2>

    <form method="post">
        <input type="hidden" name="action" value="create">

        <div class="filter-grid">
            <div>
                <label>Name</label>
                <input name="name" required>
            </div>

            <div>
                <label>Username</label>
                <input name="username" required>
            </div>

            <div>
                <label>Password</label>
                <input type="password" name="password" required>
            </div>
        </div>

        <br>

        <button class="btn btn-blue" type="submit">
            Create User
        </button>
    </form>
</div>

<div class="section">
    <h2>👤 Users</h2>

    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Username</th>
                    <th>Administrator</th>
                    <th>Action</th>
                </tr>
            </thead>

            <tbody>
                {% for u in users %}
                    <tr>
                        <td>{{ u.name }}</td>
                        <td>{{ u.username }}</td>
                        <td>
                            {% if u.is_admin %}
                                <span class="badge badge-taken">ADMIN</span>
                            {% else %}
                                <span class="badge badge-none">USER</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if u.username != admin_username %}
                                <div class="action-row">

                                    {% if u.is_admin %}
                                        <form method="post">
                                            <input type="hidden" name="action" value="remove_admin">
                                            <input type="hidden" name="user_id" value="{{ u.id }}">
                                            <button class="btn btn-orange btn-small">
                                                Remove Admin
                                            </button>
                                        </form>
                                    {% else %}
                                        <form method="post">
                                            <input type="hidden" name="action" value="make_admin">
                                            <input type="hidden" name="user_id" value="{{ u.id }}">
                                            <button class="btn btn-green btn-small">
                                                Make Admin
                                            </button>
                                        </form>
                                    {% endif %}

                                    <form
                                        method="post"
                                        onsubmit="return confirm('Delete this user?')"
                                    >
                                        <input type="hidden" name="action" value="delete">
                                        <input type="hidden" name="user_id" value="{{ u.id }}">
                                        <button class="btn btn-red btn-small">
                                            Delete
                                        </button>
                                    </form>
                                </div>
                            {% else %}
                                <span class="badge badge-live">PRIMARY ADMIN</span>
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
        admin_username=ADMIN_USERNAME,
        page_title="User Management"
    )


# ============================================================
# TIMETABLE MANAGEMENT
# ============================================================

@app.route("/admin/timetable", methods=["GET", "POST"])
@admin_required
def timetable_manage():
    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "add":
            faculty = request.form.get("faculty", "").strip()
            year = normalize_year(request.form.get("year", "").strip())
            day = request.form.get("day", "").strip()
            slot = request.form.get("slot", "").strip()
            subject = request.form.get("subject", "").strip()
            teacher = request.form.get("teacher", "").strip()
            class_name = request.form.get("class_name", "").strip()
            room = request.form.get("room", "").strip()

            if not all([faculty, year, day, slot, subject]):
                flash("Faculty, year, day, time and subject are required.")
            elif day not in DAYS:
                flash("Invalid day.")
            else:
                duplicate = Timetable.query.filter_by(
                    faculty=faculty,
                    year=year,
                    day=day,
                    slot=slot,
                    subject=subject
                ).first()

                if duplicate:
                    flash("That timetable lecture already exists.")
                else:
                    db.session.add(
                        Timetable(
                            faculty=faculty,
                            year=year,
                            day=day,
                            slot=slot,
                            subject=subject,
                            teacher=teacher,
                            class_name=class_name,
                            room=room
                        )
                    )
                    db.session.commit()
                    flash("Timetable lecture added.")

        elif action == "delete":
            try:
                row_id = int(request.form.get("row_id", "0"))
            except Exception:
                row_id = 0

            row = db.session.get(Timetable, row_id)

            if row:
                db.session.delete(row)
                db.session.commit()
                flash("Timetable lecture deleted.")

    rows = Timetable.query.order_by(
        Timetable.faculty.asc(),
        Timetable.year.asc(),
        Timetable.day.asc(),
        Timetable.slot.asc(),
        Timetable.id.asc()
    ).all()

    content = r"""
<div class="hero">
    <h1>⚙ Timetable Management</h1>
    <p>Optional administrator tools for adding/removing timetable entries</p>
</div>

<div class="section">
    <h2>➕ Add Lecture</h2>

    <form method="post">
        <input type="hidden" name="action" value="add">

        <div class="filter-grid">
            <div>
                <label>Faculty</label>
                <select name="faculty" required>
                    {% for f in faculty_options %}
                        <option value="{{ f }}">{{ f }}</option>
                    {% endfor %}
                </select>
            </div>

            <div>
                <label>Year</label>
                <select name="year" required>
                    {% for y in year_options %}
                        <option value="{{ y }}">{{ y }}</option>
                    {% endfor %}
                </select>
            </div>

            <div>
                <label>Day</label>
                <select name="day" required>
                    {% for d in days %}
                        <option value="{{ d }}">{{ d }}</option>
                    {% endfor %}
                </select>
            </div>

            <div>
                <label>Time Slot</label>
                <input
                    name="slot"
                    placeholder="09:00-10:00"
                    required
                >
            </div>

            <div>
                <label>Subject</label>
                <input name="subject" required>
            </div>

            <div>
                <label>Teacher</label>
                <input name="teacher">
            </div>

            <div>
                <label>Class / Section</label>
                <input name="class_name">
            </div>

            <div>
                <label>Room</label>
                <input name="room">
            </div>
        </div>

        <br>

        <button class="btn btn-blue" type="submit">
            Add Lecture
        </button>
    </form>
</div>

<div class="section">
    <h2>Current Timetable Records</h2>

    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th>Faculty</th>
                    <th>Year</th>
                    <th>Day</th>
                    <th>Time</th>
                    <th>Subject</th>
                    <th>Teacher</th>
                    <th>Class</th>
                    <th>Room</th>
                    <th>Action</th>
                </tr>
            </thead>

            <tbody>
                {% for row in rows %}
                    <tr>
                        <td>{{ row.faculty }}</td>
                        <td>{{ row.year }}</td>
                        <td>{{ row.day }}</td>
                        <td>{{ row.slot }}</td>
                        <td><strong>{{ row.subject }}</strong></td>
                        <td>{{ row.teacher or "—" }}</td>
                        <td>{{ row.class_name or "—" }}</td>
                        <td>{{ row.room or "—" }}</td>
                        <td>
                            <form
                                method="post"
                                onsubmit="return confirm('Delete this timetable entry?')"
                            >
                                <input type="hidden" name="action" value="delete">
                                <input type="hidden" name="row_id" value="{{ row.id }}">
                                <button class="btn btn-red btn-small">
                                    Delete
                                </button>
                            </form>
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
        rows=rows,
        faculty_options=FACULTY_ORDER,
        year_options=YEAR_ORDER,
        days=DAYS,
        page_title="Timetable Management"
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():
    return {
        "status": "ok",
        "application": "SGB College Management System",
        "timezone": "Asia/Kolkata",
        "current_time": now_ist().isoformat(),
        "timetable_lectures": Timetable.query.count(),
        "attendance_records": Attendance.query.count()
    }


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):
    content = """
<div class="empty">
    <h1>404</h1>
    <p>Page not found.</p>
    <a class="btn btn-blue" href="{{ url_for('home') }}">Go Home</a>
</div>
"""
    return render_page(
        content,
        page_title="404"
    ), 404


@app.errorhandler(500)
def server_error(error):
    db.session.rollback()

    content = """
<div class="empty">
    <h1>500</h1>
    <p>Something went wrong on the server.</p>
    <a class="btn btn-blue" href="{{ url_for('home') }}">Go Home</a>
</div>
"""
    return render_page(
        content,
        page_title="500"
    ), 500


# ============================================================
# APPLICATION START
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))

    print("=" * 65)
    print("SGB COLLEGE MANAGEMENT SYSTEM")
    print("=" * 65)
    print("Timezone:", "Asia/Kolkata")
    print(
        "Current India Time:",
        now_ist().strftime("%d-%m-%Y %I:%M:%S %p")
    )
    print("Local URL:", f"http://127.0.0.1:{port}")
    print("Admin username:", ADMIN_USERNAME)
    print(
        "Admin password:",
        "(set via ADMIN_PASSWORD environment variable)"
    )
    print("=" * 65)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
