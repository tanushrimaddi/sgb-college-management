import os
import json
import csv
import io
import math
import uuid
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from functools import wraps

from flask import (
    Flask, render_template_string, request, redirect, url_for,
    session, flash, Response, jsonify
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

# Trial teacher accounts. Each non-admin account can mark attendance only
# for its assigned subject. Change passwords after first login.
TRIAL_TEACHERS = [
    {"name": "G.D Kurundkar", "username": "g.d.kurundkar", "password": "teacher123", "subject": "comp sci"},
    {"name": "R.S.Shaikh", "username": "r.s.shaikh", "password": "teacher123", "subject": "Physics"},
    {"name": "J.S.Pulle", "username": "j.s.pulle", "password": "teacher123", "subject": "chemistry"},
    {"name": "A.S.Kausadikar", "username": "a.s.kausadikar", "password": "teacher123", "subject": "math"},
    {"name": "R.R.Rakh", "username": "r.r.rakh", "password": "teacher123", "subject": "micro"},
]

ADMIN_DISPLAY_NAME = "A.B.Kurhe"

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

    # For teacher accounts this stores the one subject they are allowed to
    # mark. Admin accounts leave it empty and can mark every subject.
    assigned_subject = db.Column(
        db.String(300),
        nullable=True,
        index=True
    )

    # Teachers may have only one active login at a time. The session is
    # released only when that teacher explicitly logs out.
    active_session_token = db.Column(
        db.String(100),
        nullable=True,
        index=True
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


class CollegeLocation(db.Model):
    __tablename__ = "college_location"

    id = db.Column(db.Integer, primary_key=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    radius_meters = db.Column(db.Float, nullable=False, default=150.0)
    updated_at = db.Column(db.DateTime, default=now_ist_naive, nullable=False)

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

    # Number of students present in this lecture.
    # It is written once when attendance is marked and never updated.
    present_count = db.Column(
        db.Integer,
        nullable=False,
        default=0
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

    # Attendance present-student count. Existing records receive 0.
    add_column_if_missing(
        "attendance",
        "present_count",
        "INTEGER NOT NULL DEFAULT 0"
    )

    # Teacher subject permission.
    add_column_if_missing(
        "users",
        "assigned_subject",
        "VARCHAR(300)"
    )

    # One active teacher login at a time.
    add_column_if_missing(
        "users",
        "active_session_token",
        "VARCHAR(100)"
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
        if not admin.is_admin:
            admin.is_admin = True
            db.session.commit()

    # The requested administrator is A.B.Kurhe. Keep the existing primary
    # admin username so current deployments do not lose their login.
    admin.name = ADMIN_DISPLAY_NAME
    admin.is_admin = True
    db.session.commit()

    # Create/update the five trial teacher accounts. Existing passwords are
    # preserved so redeploys do not unexpectedly reset credentials.
    for teacher_data in TRIAL_TEACHERS:
        teacher = User.query.filter_by(username=teacher_data["username"]).first()
        if not teacher:
            teacher = User(
                name=teacher_data["name"],
                username=teacher_data["username"],
                password_hash=generate_password_hash(teacher_data["password"]),
                is_admin=False,
                assigned_subject=teacher_data["subject"]
            )
            db.session.add(teacher)
        else:
            teacher.name = teacher_data["name"]
            teacher.is_admin = False
            teacher.assigned_subject = teacher_data["subject"]
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

    user = db.session.get(User, user_id)
    if not user:
        session.clear()
        return None

    # Teacher sessions are tied to a server-side token. This prevents a
    # second login from being active at the same time.
    if not user.is_admin:
        session_token = session.get("active_session_token")
        if not session_token or session_token != user.active_session_token:
            session.clear()
            return None

    return user


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

    if year and str(year).strip().lower() not in {"all", "all years"}:
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



def get_college_location():
    """Return the single configured college geofence, if an admin has set it."""
    return CollegeLocation.query.first()


def distance_meters(lat1, lon1, lat2, lon2):
    """Haversine distance between two GPS coordinates in meters."""
    radius = 6371000.0
    p1 = math.radians(float(lat1))
    p2 = math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def location_allowed(latitude, longitude):
    """Check whether the supplied browser GPS point is inside the college geofence."""
    location = get_college_location()
    if not location:
        return False, "College location has not been configured by the administrator."

    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return False, "Valid device location is required."

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False, "Invalid GPS coordinates."

    distance = distance_meters(
        location.latitude, location.longitude, lat, lon
    )

    if distance > location.radius_meters:
        return False, (
            f"You are about {round(distance)} m away from the college. "
            f"Attendance can be marked only within {round(location.radius_meters)} m of the college."
        )

    return True, f"Location verified ({round(distance)} m from college)."


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


def attendance_window_open(record_date, day, slot):
    """Return True only while the lecture is actually running today (IST)."""
    now = now_ist()

    if record_date != now.date():
        return False

    if day != now.strftime("%A"):
        return False

    start, end = parse_slot(slot)

    if start is None or end is None:
        return False

    current_minutes = now.hour * 60 + now.minute
    return start <= current_minutes < end


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

    if year and str(year).strip().lower() not in {"all", "all years"}:
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

    if period == "semester1":
        return (
            today.replace(month=1, day=1),
            today.replace(month=6, day=30)
        )

    if period == "semester2":
        return (
            today.replace(month=7, day=1),
            today.replace(month=12, day=31)
        )

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
    border-radius: 10px;
    padding: 10px 8px;
    margin-bottom: 7px;
    text-align: center;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    box-shadow: 0 2px 7px rgba(15, 23, 42, 0.06);
}

.lecture-cell strong {
    display: block;
    font-size: 13px;
    line-height: 1.35;
    margin-bottom: 5px;
}

/* Consistent subject colors in the master timetable. */
.lecture-cell.subject-blue { border-top: 4px solid #2563eb; }
.lecture-cell.subject-purple { border-top: 4px solid #7c3aed; }
.lecture-cell.subject-green { border-top: 4px solid #16a34a; }
.lecture-cell.subject-orange { border-top: 4px solid #ea580c; }
.lecture-cell.subject-teal { border-top: 4px solid #0d9488; }
.lecture-cell.subject-olive { border-top: 4px solid #65a30d; }
.lecture-cell.subject-pink { border-top: 4px solid #db2777; }
.lecture-cell.subject-indigo { border-top: 4px solid #4f46e5; }
.lecture-cell.subject-slate { border-top: 4px solid #64748b; }

.lecture-cell .subject-name {
    display: inline-block;
    font-weight: 900;
    padding: 5px 9px;
    border-radius: 7px;
    background: #f1f5f9;
}

.master-table {
    border-collapse: separate;
    border-spacing: 0;
    overflow: hidden;
    border: 1px solid #dbe3ef;
    border-radius: 12px;
}

.master-table th {
    text-align: center;
    vertical-align: middle;
    background: #eaf0ff;
    color: #173b7a;
    font-size: 13px;
    font-weight: 900;
    padding: 13px 10px;
}

.master-table td {
    min-width: 155px;
    text-align: center;
    vertical-align: middle;
    padding: 9px;
}

.master-table .slot-cell {
    background: #f1f5f9;
    color: #1d4ed8;
    text-align: center;
    vertical-align: middle;
    font-size: 13px;
    white-space: nowrap;
}

.master-table .meta {
    text-align: center;
    line-height: 1.35;
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

.attendance-locked,
.attendance-disabled {
    display: inline-block;
    padding: 10px 14px;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 700;
    background: #f1f5f9;
    color: #475569;
}

.attendance-locked {
    background: #ecfdf5;
    color: #047857;
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


/* =========================
   SGB PROFESSIONAL SIDEBAR + DASHBOARD
   ========================= */
.navbar {
    position: fixed;
    left: 0;
    top: 0;
    width: 255px;
    height: 100vh;
    min-height: 100vh;
    padding: 18px 12px;
    box-sizing: border-box;
    background: linear-gradient(180deg, #071a38 0%, #0b2450 55%, #102d63 100%);
    color: white;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    justify-content: flex-start;
    gap: 14px;
    overflow-y: auto;
    overflow-x: hidden;
    z-index: 1000;
    box-shadow: 4px 0 22px rgba(15,23,42,.16);
}

.brand {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 4px 4px 16px;
    text-decoration: none;
    border-bottom: 1px solid rgba(255,255,255,.18);
}

.college-logo {
    width: 76px;
    height: 76px;
    object-fit: contain;
    background: white;
    border-radius: 50%;
    padding: 4px;
    box-shadow: 0 5px 18px rgba(0,0,0,.25);
}

.logo {
    width: 100%;
    box-sizing: border-box;
    font-weight: 900;
    font-size: 17px;
    line-height: 1.25;
    text-align: center;
    white-space: normal;
    overflow-wrap: anywhere;
    color: #fff;
}

.logo small {
    display: block;
    font-size: 9px;
    color: #cbd5e1;
    letter-spacing: 1px;
    margin-top: 5px;
}

.nav-links {
    display: flex;
    flex-direction: column;
    gap: 5px;
    width: 100%;
}

.nav-links a {
    display: flex;
    align-items: center;
    width: 100%;
    box-sizing: border-box;
    padding: 12px 13px;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 800;
    color: #e5edf9;
    text-decoration: none;
    transition: all .18s ease;
}

.nav-links a:hover {
    background: rgba(59,130,246,.30);
    color: white;
    transform: translateX(2px);
}

.nav-links a:first-child {
    background: linear-gradient(135deg, #2563eb, #3b82f6);
    color: #fff;
    box-shadow: 0 5px 14px rgba(37,99,235,.25);
}

.container {
    width: calc(100% - 255px);
    max-width: none;
    margin-left: 255px;
    margin-right: 0;
    padding: 28px 34px 55px;
    box-sizing: border-box;
    background: #f4f7fc;
    min-height: calc(100vh - 40px);
}

.footer {
    margin-left: 255px;
    background: #f4f7fc;
}

/* Dashboard hero */
.hero.dashboard-hero {
    min-height: 142px;
    padding: 18px 24px;
    border-radius: 20px;
    display: flex;
    align-items: center;
    gap: 22px;
    background: linear-gradient(120deg, #087ff5 0%, #2d55ef 52%, #7737ef 100%);
    box-shadow: 0 10px 28px rgba(37,99,235,.17);
    position: relative;
    overflow: hidden;
}

.hero.dashboard-hero::after {
    content: '';
    position: absolute;
    width: 270px;
    height: 270px;
    right: -90px;
    top: -100px;
    border-radius: 50%;
    background: rgba(255,255,255,.08);
}

.hero-logo {
    width: 112px;
    height: 112px;
    flex: 0 0 112px;
    object-fit: contain;
    border-radius: 50%;
    background: white;
    padding: 5px;
    box-sizing: border-box;
    z-index: 1;
}

.hero-copy {
    position: relative;
    z-index: 1;
}

.hero.dashboard-hero h1 {
    margin: 0 0 5px;
    font-size: clamp(25px, 3vw, 39px);
    line-height: 1.12;
    letter-spacing: .2px;
}

.hero.dashboard-hero p {
    margin: 0 0 8px;
    font-size: 16px;
}

.hero.dashboard-hero .time {
    margin: 0;
    font-weight: 800;
    font-size: 15px;
}

/* Dashboard filters */
.dashboard-filters {
    padding: 16px;
    border-radius: 16px;
    background: white;
    box-shadow: 0 5px 18px rgba(15,23,42,.06);
    margin-bottom: 18px;
}

.dashboard-filters .filter-grid {
    grid-template-columns: 1fr 1fr;
}

.dashboard-filters select {
    height: 42px;
    font-size: 14px;
    font-weight: 600;
}

/* KPI cards */
.dashboard-cards {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 12px;
    margin-bottom: 18px;
}

.dashboard-stat {
    background: #fff;
    border-radius: 16px;
    padding: 17px 16px;
    min-height: 92px;
    box-sizing: border-box;
    box-shadow: 0 5px 18px rgba(15,23,42,.06);
    border: 1px solid #edf1f7;
    position: relative;
    overflow: hidden;
}

.dashboard-stat::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 4px;
    background: #2563eb;
}

.dashboard-stat.green-card::before { background: #16a34a; }
.dashboard-stat.red-card::before { background: #dc2626; }
.dashboard-stat.orange-card::before { background: #f97316; }
.dashboard-stat.purple-card::before { background: #7c3aed; }

.dashboard-stat .stat-title {
    font-size: 10px;
    letter-spacing: .3px;
}

.dashboard-stat .stat-value {
    font-size: 25px;
    margin-top: 10px;
}

/* Live sections */
.dashboard-section {
    background: white;
    border-radius: 17px;
    padding: 18px;
    margin-bottom: 18px;
    box-shadow: 0 5px 18px rgba(15,23,42,.06);
    border: 1px solid #edf1f7;
}

.dashboard-section .report-title h2 {
    margin: 0;
    font-size: 21px;
}

.dashboard-section .lecture {
    margin-top: 13px;
    margin-bottom: 0;
    padding: 15px;
    border-radius: 13px;
}

.live-dot {
    width: 13px;
    height: 13px;
    display: inline-block;
    border-radius: 50%;
    background: #22c55e;
    box-shadow: 0 0 0 5px #dcfce7;
    margin-right: 8px;
    vertical-align: middle;
}

.quick-actions {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
}

.quick-action {
    display: block;
    text-decoration: none;
    background: #f8fafc;
    border: 1px solid #e5e7eb;
    border-radius: 13px;
    padding: 14px;
    color: #172033;
    font-weight: 900;
    transition: .18s ease;
}

.quick-action:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 18px rgba(15,23,42,.08);
}

@media (max-width: 1200px) {
    .dashboard-cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

@media (max-width: 900px) and (min-width: 701px) {
    .navbar { width: 220px; }
    .container { width: calc(100% - 220px); margin-left: 220px; padding: 22px; }
    .footer { margin-left: 220px; }
    .dashboard-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .hero-logo { width: 88px; height: 88px; flex-basis: 88px; }
}

@media (max-width: 700px) {
    .navbar {
        position: relative;
        width: 100%;
        height: auto;
        min-height: auto;
        padding: 12px;
        flex-direction: column;
        gap: 10px;
    }

    .brand { flex-direction: row; justify-content: flex-start; padding: 3px 5px 10px; }
    .college-logo { width: 55px; height: 55px; }
    .logo { text-align: left; font-size: 15px; }
    .logo small { font-size: 8px; }

    .nav-links {
        flex-direction: row;
        flex-wrap: wrap;
        overflow-x: visible;
    }

    .nav-links a { width: auto; font-size: 12px; padding: 9px 10px; }
    .container { width: 96%; margin-left: auto; margin-right: auto; padding: 15px 0 35px; }
    .footer { margin-left: 0; }

    .hero.dashboard-hero { align-items: flex-start; padding: 18px; gap: 13px; }
    .hero-logo { width: 72px; height: 72px; flex-basis: 72px; }
    .hero.dashboard-hero h1 { font-size: 23px; }
    .hero.dashboard-hero p { font-size: 13px; }
    .hero.dashboard-hero .time { font-size: 12px; }

    .dashboard-filters .filter-grid { grid-template-columns: 1fr; }
    .dashboard-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .dashboard-stat { min-height: 86px; padding: 14px; }
    .quick-actions { grid-template-columns: 1fr; }
}

/* ============================================================
   FINAL SGB STANDARD WEBSITE THEME
   ============================================================ */
body {
    background: #f3f7fc;
    color: #172b4d;
    font-family: Inter, "Segoe UI", Arial, sans-serif;
}
.navbar {
    width: 270px;
    background: linear-gradient(180deg, #061b3a 0%, #0a2b5e 55%, #103b7b 100%);
    padding: 20px 14px;
    border-right: 1px solid rgba(255,255,255,.08);
}
.brand { padding-bottom: 18px; gap: 9px; }
.college-logo {
    width: 82px; height: 82px; padding: 4px;
    box-shadow: 0 8px 22px rgba(0,0,0,.22);
}
.logo { font-size: 19px; letter-spacing: .2px; }
.logo small { font-size: 9px; letter-spacing: 1.1px; }
.nav-links { gap: 7px; margin-top: 4px; }
.nav-links a {
    min-height: 46px;
    padding: 12px 14px;
    border-radius: 11px;
    font-size: 14px;
}
.nav-links a:hover { background: rgba(59,130,246,.28); transform: translateX(3px); }
.nav-links a:first-child {
    background: linear-gradient(135deg,#2875f2,#367df0);
    box-shadow: 0 8px 18px rgba(37,99,235,.28);
}
.container {
    width: calc(100% - 270px);
    margin-left: 270px;
    padding: 22px 34px 55px;
    background: #f3f7fc;
}
.footer { margin-left: 270px; background: #f3f7fc; }

/* Top header like a modern college admin panel */
.sgb-topbar {
    position: fixed;
    left: 270px; right: 0; top: 0;
    height: 64px;
    background: rgba(255,255,255,.96);
    border-bottom: 1px solid #e6edf6;
    box-shadow: 0 3px 14px rgba(15,23,42,.05);
    z-index: 900;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 24px;
}
.sgb-topbar-left { display:flex; align-items:center; gap:12px; }
.sgb-menu {
    width:38px;height:38px;border:0;border-radius:10px;
    background:#f1f5fb;color:#234b86;font-size:21px;cursor:pointer;
}
.sgb-topbar-right { display:flex;align-items:center;gap:18px; }
.sgb-bell { font-size:21px;color:#173b7a;position:relative; }
.sgb-bell::after {
    content:''; position:absolute; width:7px;height:7px;border-radius:50%;
    background:#ef3340; right:-2px; top:-1px;
}
.sgb-user {
    display:flex;align-items:center;gap:10px;
    color:#173b7a;font-weight:800;
    border-left:1px solid #e5eaf2;padding-left:18px;
}
.sgb-avatar {
    width:40px;height:40px;border-radius:50%;
    display:grid;place-items:center;background:#edf3fb;
    border:1px solid #cbd8ec;font-size:22px;
}

/* Header/hero */
.container { padding-top: 84px; }
.hero.dashboard-hero {
    min-height: 228px;
    padding: 26px 34px;
    border-radius: 18px;
    background: linear-gradient(115deg,#096be9 0%,#2459e8 48%,#7b3ff0 100%);
    box-shadow: 0 12px 30px rgba(37,99,235,.18);
}
.hero.dashboard-hero::before {
    content:'';
    position:absolute; width:330px;height:330px; right:-90px; bottom:-190px;
    border-radius:50%; border:70px solid rgba(255,255,255,.07);
}
.hero.dashboard-hero::after {
    width:260px;height:260px;right:-80px;top:-150px;
    background:rgba(255,255,255,.09);
}
.hero-logo { width:118px;height:118px;flex-basis:118px; }
.hero-copy { padding-left:2px; }
.hero.dashboard-hero h1 {
    font-size: clamp(28px,3vw,43px);
    letter-spacing:.2px;
    margin-bottom:7px;
}
.hero-org {
    font-size:16px;font-weight:800;letter-spacing:.5px;
    margin-bottom:2px;text-transform:uppercase;
}
.hero-subtitle { font-size:17px;font-weight:600;opacity:.98; }
.hero-time {
    margin-top:12px!important;
    font-size:15px!important;font-weight:800;
}

/* Filters */
.dashboard-filters {
    padding:18px 22px;
    border:1px solid #e3ebf7;
    box-shadow:0 6px 20px rgba(15,23,42,.06);
}
.dashboard-filters label { color:#31527e;font-size:13px; }
.dashboard-filters select {
    border:1px solid #cbd8ea;border-radius:11px;
    height:46px;background:#fff;color:#19365e;
}

/* KPI cards */
.dashboard-cards { grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }
.dashboard-stat {
    min-height:116px;
    padding:18px 18px 16px 21px;
    border:1px solid #e0e8f3;
    border-radius:16px;
    box-shadow:0 7px 20px rgba(15,23,42,.06);
}
.dashboard-stat::before { width:5px; }
.dashboard-stat .stat-title { color:#637797;font-size:11px;letter-spacing:.7px; }
.dashboard-stat .stat-value { font-size:29px; color:#173b7a; }

/* Section cards */
.dashboard-section {
    border:1px solid #e3eaf5;
    border-radius:17px;
    box-shadow:0 7px 22px rgba(15,23,42,.055);
}
.dashboard-section .report-title h2 { color:#163864; }

/* Master timetable: centered, clean, subject-filled colors */
.master-table {
    width:100%;
    border:1px solid #d5e0ef;
    border-radius:14px;
    background:#fff;
}
.master-table th {
    background:linear-gradient(180deg,#eaf2ff,#dfeaff);
    color:#163d79;
    border-bottom:1px solid #cbd9ec;
    font-size:13px;
    padding:15px 10px;
}
.master-table td {
    text-align:center!important;
    vertical-align:middle!important;
    border-right:1px solid #edf2f8;
    border-bottom:1px solid #e5ebf4;
    padding:10px;
}
.master-table tr:last-child td { border-bottom:0; }
.master-table .slot-cell {
    background:#f5f8fd;
    color:#2459a8;
    font-size:13px;
    font-weight:900;
}
.lecture-cell {
    padding:11px 9px;
    border-radius:11px;
    border:1px solid rgba(148,163,184,.28);
    border-top-width:4px;
    box-shadow:0 3px 9px rgba(15,23,42,.06);
}
.lecture-cell .subject-name {
    display:block;
    margin:0 auto 7px;
    padding:7px 8px;
    border-radius:8px;
    font-size:13px;
    color:#172b4d;
}
.lecture-cell.subject-blue { background:#eef5ff;border-top-color:#2563eb; }
.lecture-cell.subject-blue .subject-name { background:#dbeafe; }
.lecture-cell.subject-purple { background:#f5efff;border-top-color:#7c3aed; }
.lecture-cell.subject-purple .subject-name { background:#ede9fe; }
.lecture-cell.subject-green { background:#edfcf3;border-top-color:#16a34a; }
.lecture-cell.subject-green .subject-name { background:#dcfce7; }
.lecture-cell.subject-orange { background:#fff5e9;border-top-color:#ea580c; }
.lecture-cell.subject-orange .subject-name { background:#ffedd5; }
.lecture-cell.subject-teal { background:#eafcf9;border-top-color:#0d9488; }
.lecture-cell.subject-teal .subject-name { background:#ccfbf1; }
.lecture-cell.subject-olive { background:#f4fbe9;border-top-color:#65a30d; }
.lecture-cell.subject-olive .subject-name { background:#ecfccb; }
.lecture-cell.subject-pink { background:#fff0f7;border-top-color:#db2777; }
.lecture-cell.subject-pink .subject-name { background:#fce7f3; }
.lecture-cell.subject-indigo { background:#eef2ff;border-top-color:#4f46e5; }
.lecture-cell.subject-indigo .subject-name { background:#e0e7ff; }
.lecture-cell.subject-slate { background:#f7f9fc;border-top-color:#64748b; }
.lecture-cell.subject-slate .subject-name { background:#e9eef5; }
.master-table .meta { text-align:center; color:#60718c; }

/* Responsive */
@media (max-width:1200px) {
    .dashboard-cards { grid-template-columns:repeat(3,minmax(0,1fr)); }
}
@media (max-width:900px) and (min-width:701px) {
    .navbar { width:220px; }
    .sgb-topbar { left:220px; }
    .container { width:calc(100% - 220px); margin-left:220px; padding:82px 22px 45px; }
    .footer { margin-left:220px; }
    .dashboard-cards { grid-template-columns:repeat(2,minmax(0,1fr)); }
}
@media (max-width:700px) {
    .navbar {
        position:relative;width:100%;height:auto;min-height:auto;
        padding:12px;display:block;
    }
    .brand { flex-direction:row;justify-content:flex-start; }
    .college-logo { width:58px;height:58px; }
    .logo { text-align:left;font-size:15px; }
    .nav-links { flex-direction:row;flex-wrap:wrap; }
    .nav-links a { width:auto;min-height:auto;font-size:12px;padding:9px 10px; }
    .sgb-topbar { position:relative;left:auto;height:54px;padding:0 12px; }
    .sgb-user { font-size:12px;padding-left:10px; }
    .sgb-avatar { width:34px;height:34px;font-size:18px; }
    .container { width:96%;margin:0 auto;padding:15px 0 35px; }
    .hero.dashboard-hero { min-height:180px;padding:20px;gap:13px; }
    .hero-logo { width:76px;height:76px;flex-basis:76px; }
    .hero-org { font-size:11px; }
    .hero.dashboard-hero h1 { font-size:24px; }
    .hero-subtitle { font-size:12px; }
    .hero-time { font-size:11px!important; }
    .dashboard-cards { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .dashboard-stat { min-height:92px;padding:13px; }
    .dashboard-stat .stat-value { font-size:23px; }
}


/* ============================================================
   FINAL SGB COLLEGE DESIGN — MATCHING THE PROVIDED DASHBOARD
   ============================================================ */

html, body {
    min-height: 100%;
}

body {
    background: #f4f7fb;
    color: #172b4d;
    font-family: Inter, "Segoe UI", Arial, sans-serif;
}

/* Left fixed navigation */
.navbar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    width: 290px;
    min-height: 100vh;
    height: 100vh;
    padding: 18px 14px 20px;
    background: linear-gradient(180deg, #071b3d 0%, #0b2d62 58%, #123e82 100%);
    color: #fff;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    align-items: stretch;
    gap: 0;
    overflow-y: auto;
    box-shadow: 5px 0 22px rgba(10, 39, 83, .10);
    border: 0;
}

.navbar .brand {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 3px 4px 20px;
    margin-bottom: 10px;
    border-bottom: 1px solid rgba(255,255,255,.16);
    text-align: center;
}

.navbar .college-logo {
    width: 92px;
    height: 92px;
    object-fit: contain;
    background: #fff;
    border-radius: 50%;
    padding: 5px;
    box-shadow: 0 4px 14px rgba(0,0,0,.18);
    margin-bottom: 12px;
}

.navbar .logo {
    color: #fff;
    font-size: 21px;
    font-weight: 900;
    letter-spacing: .2px;
}

.navbar .logo small {
    margin-top: 5px;
    color: #b8c9e5;
    font-size: 9px;
    letter-spacing: 1.1px;
    font-weight: 800;
}

.nav-links {
    display: flex;
    flex-direction: column;
    flex-wrap: nowrap;
    gap: 7px;
    width: 100%;
    align-items: stretch;
}

.nav-links a {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 47px;
    width: 100%;
    padding: 11px 15px;
    border-radius: 11px;
    color: #f5f8ff;
    font-size: 14px;
    font-weight: 800;
    letter-spacing: .05px;
    transition: .18s ease;
}

.nav-links a:hover {
    background: rgba(255,255,255,.10);
    transform: translateX(2px);
}

.nav-links a:first-child {
    background: linear-gradient(90deg, #287df0, #1677e9);
    box-shadow: 0 7px 18px rgba(25,116,235,.24);
}

.nav-links a:first-child:hover {
    background: linear-gradient(90deg, #287df0, #1677e9);
    transform: none;
}

/* Top white bar */
.sgb-topbar {
    position: fixed;
    top: 0;
    left: 290px;
    right: 0;
    height: 72px;
    z-index: 900;
    background: rgba(255,255,255,.97);
    border-bottom: 1px solid #e5ebf4;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 27px;
    box-shadow: 0 2px 12px rgba(15,43,80,.04);
}

.sgb-menu {
    width: 40px;
    height: 40px;
    padding: 0;
    border-radius: 10px;
    background: #f0f5fd;
    color: #2e4f7e;
    font-size: 23px;
    line-height: 40px;
}

.sgb-menu:hover {
    background: #e5edf9;
}

.sgb-topbar-right {
    display: flex;
    align-items: center;
    gap: 17px;
}

.sgb-bell {
    font-size: 24px;
    padding-right: 17px;
    border-right: 1px solid #dce4ef;
    line-height: 30px;
}

.sgb-user {
    display: flex;
    align-items: center;
    gap: 10px;
    color: #183764;
    font-size: 16px;
    font-weight: 900;
}

.sgb-avatar {
    width: 40px;
    height: 40px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 2px solid #c9d7ea;
    border-radius: 50%;
    background: #eef3fa;
    font-size: 21px;
}

/* Main page area */
.container {
    width: auto;
    max-width: none;
    margin: 0;
    margin-left: 290px;
    padding: 91px 22px 42px;
}

.footer {
    margin-left: 290px;
    background: transparent;
    color: #8494aa;
    border-top: 1px solid #e7edf5;
}

/* Main hero */
.hero.dashboard-hero {
    min-height: 225px;
    margin-bottom: 17px;
    padding: 25px 32px;
    border-radius: 19px;
    display: flex;
    align-items: center;
    gap: 29px;
    position: relative;
    overflow: hidden;
    background:
        linear-gradient(115deg, rgba(7,114,239,.98) 0%, rgba(36,75,232,.98) 53%, rgba(121,58,239,.97) 100%);
    box-shadow: 0 10px 28px rgba(37,99,235,.17);
}

.hero.dashboard-hero::before {
    content: "";
    position: absolute;
    width: 330px;
    height: 330px;
    right: -100px;
    top: -175px;
    border-radius: 50%;
    border: 35px solid rgba(255,255,255,.07);
}

.hero.dashboard-hero::after {
    content: "";
    position: absolute;
    width: 310px;
    height: 310px;
    right: -135px;
    bottom: -215px;
    border-radius: 50%;
    border: 38px solid rgba(255,255,255,.07);
}

.hero-logo {
    width: 126px;
    height: 126px;
    flex: 0 0 126px;
    padding: 5px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 5px 18px rgba(0,0,0,.13);
}

.hero-copy {
    position: relative;
    z-index: 3;
}

.hero.dashboard-hero .hero-org {
    margin-bottom: 4px;
    color: #fff;
    font-size: 16px;
    font-weight: 900;
    letter-spacing: .35px;
    text-transform: uppercase;
}

.hero.dashboard-hero h1 {
    margin: 0 0 3px;
    color: #fff;
    font-size: clamp(35px, 3.5vw, 51px);
    line-height: 1.03;
    font-weight: 950;
    letter-spacing: .4px;
}

.hero.dashboard-hero .hero-subtitle {
    margin: 0 0 7px;
    color: #fff;
    font-size: 20px;
    font-weight: 900;
    letter-spacing: .25px;
}

.hero.dashboard-hero p {
    color: #fff;
    font-size: 16px;
}

.hero.dashboard-hero .hero-time {
    margin-top: 11px;
    color: #fff;
    font-size: 15px;
    font-weight: 900;
}

/* Filters */
.dashboard-filters {
    padding: 17px 24px;
    margin-bottom: 18px;
    border: 1px solid #dce7f5;
    border-radius: 17px;
    background: #fff;
    box-shadow: 0 5px 18px rgba(15,23,42,.055);
}

.dashboard-filters .filter-grid {
    grid-template-columns: 1fr 1fr;
    gap: 23px;
}

.dashboard-filters label {
    margin-bottom: 8px;
    color: #294d7c;
    font-size: 13px;
    font-weight: 900;
}

.dashboard-filters select {
    height: 48px;
    padding: 0 15px;
    border: 1px solid #cad8ec;
    border-radius: 10px;
    color: #203a61;
    background: #fff;
    font-size: 14px;
    font-weight: 700;
}

/* KPI cards */
.dashboard-cards {
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 14px;
    margin-bottom: 19px;
}

.dashboard-stat {
    min-height: 114px;
    padding: 19px 17px;
    border: 1px solid #e1e9f4;
    border-radius: 16px;
    box-shadow: 0 5px 17px rgba(15,23,42,.055);
}

.dashboard-stat::before {
    width: 4px;
}

.dashboard-stat .stat-title {
    color: #617692;
    font-size: 11px;
    font-weight: 900;
    letter-spacing: .35px;
}

.dashboard-stat .stat-value {
    margin-top: 12px;
    color: #123b79;
    font-size: 29px;
    font-weight: 950;
}

.dashboard-stat.green-card .stat-value { color: #07884e; }
.dashboard-stat.red-card .stat-value { color: #d92d43; }
.dashboard-stat.orange-card .stat-value { color: #e87500; }
.dashboard-stat.purple-card .stat-value { color: #5b35cc; }

/* Dashboard content sections */
.dashboard-section {
    padding: 20px;
    margin-bottom: 18px;
    border: 1px solid #e2eaf4;
    border-radius: 17px;
    box-shadow: 0 5px 18px rgba(15,23,42,.055);
}

.dashboard-section .report-title h2 {
    color: #173968;
    font-size: 22px;
    font-weight: 900;
}

.quick-action {
    border: 1px solid #dfe8f3;
    background: #f8fbff;
}

/* Alerts */
.alert {
    border-radius: 11px;
    border: 1px solid #dce7f4;
}

/* Mobile */
@media (max-width: 900px) {
    .navbar {
        width: 240px;
    }

    .sgb-topbar {
        left: 240px;
    }

    .container {
        margin-left: 240px;
        padding-left: 16px;
        padding-right: 16px;
    }

    .footer {
        margin-left: 240px;
    }

    .dashboard-cards {
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }

    .hero.dashboard-hero {
        min-height: 190px;
    }

    .hero-logo {
        width: 100px;
        height: 100px;
        flex-basis: 100px;
    }
}

@media (max-width: 700px) {
    .navbar {
        position: relative;
        width: 100%;
        height: auto;
        min-height: auto;
        padding: 10px;
        overflow: visible;
    }

    .navbar .brand {
        flex-direction: row;
        justify-content: flex-start;
        gap: 10px;
        padding: 3px 5px 12px;
        text-align: left;
    }

    .navbar .college-logo {
        width: 55px;
        height: 55px;
        margin-bottom: 0;
    }

    .navbar .logo {
        font-size: 16px;
    }

    .nav-links {
        flex-direction: row;
        flex-wrap: wrap;
        gap: 5px;
    }

    .nav-links a {
        width: auto;
        min-height: 40px;
        font-size: 12px;
        padding: 8px 10px;
    }

    .sgb-topbar {
        position: sticky;
        left: auto;
        height: 60px;
        padding: 0 13px;
    }

    .container {
        width: 96%;
        margin-left: auto;
        margin-right: auto;
        padding: 15px 0 35px;
    }

    .footer {
        margin-left: 0;
    }

    .hero.dashboard-hero {
        min-height: auto;
        padding: 20px;
        gap: 15px;
    }

    .hero-logo {
        width: 75px;
        height: 75px;
        flex-basis: 75px;
    }

    .hero.dashboard-hero .hero-org {
        font-size: 10px;
    }

    .hero.dashboard-hero h1 {
        font-size: 30px;
    }

    .hero.dashboard-hero .hero-subtitle {
        font-size: 14px;
    }

    .hero.dashboard-hero p {
        font-size: 12px;
    }

    .dashboard-filters .filter-grid {
        grid-template-columns: 1fr;
    }

    .dashboard-cards {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}


/* ============================================================
   SGB COLLEGE — FINAL DASHBOARD VISUAL OVERRIDE
   Designed to closely match the user's supplied reference.
   ============================================================ */

:root{
    --sgb-navy:#071b3d;
    --sgb-blue:#1479ed;
    --sgb-blue2:#3158ec;
    --sgb-purple:#7b3ff0;
    --sgb-text:#17365f;
    --sgb-muted:#6d7f98;
    --sgb-bg:#f5f8fc;
}

html,body{background:var(--sgb-bg)!important;}
body{
    color:var(--sgb-text)!important;
    font-family:"Segoe UI",Inter,Arial,sans-serif!important;
}

/* LEFT SIDEBAR — reference width/spacing */
.navbar{
    position:fixed!important;
    left:0!important;
    top:0!important;
    bottom:0!important;
    width:289px!important;
    height:100vh!important;
    min-height:100vh!important;
    box-sizing:border-box!important;
    padding:18px 14px 14px!important;
    background:linear-gradient(180deg,#071a3a 0%,#0b2d62 56%,#123c7c 100%)!important;
    border:0!important;
    box-shadow:none!important;
    overflow:hidden!important;
    z-index:1000!important;
}
.navbar .brand{
    height:272px!important;
    box-sizing:border-box!important;
    margin:0!important;
    padding:2px 4px 17px!important;
    display:flex!important;
    flex-direction:column!important;
    align-items:center!important;
    justify-content:flex-start!important;
    border-bottom:1px solid rgba(255,255,255,.17)!important;
}
.navbar .college-logo{
    width:96px!important;
    height:96px!important;
    margin:2px 0 12px!important;
    padding:4px!important;
    border-radius:50%!important;
    background:#fff!important;
    object-fit:contain!important;
}
.navbar .logo{
    font-size:21px!important;
    line-height:1.15!important;
    color:#fff!important;
    font-weight:900!important;
    text-align:center!important;
}
.navbar .logo small{
    display:block!important;
    margin-top:6px!important;
    color:#b8c9e5!important;
    font-size:9px!important;
    letter-spacing:1px!important;
    font-weight:800!important;
}
.nav-links{
    margin-top:12px!important;
    display:flex!important;
    flex-direction:column!important;
    gap:5px!important;
    width:100%!important;
}
.nav-links a{
    width:100%!important;
    min-height:46px!important;
    box-sizing:border-box!important;
    display:flex!important;
    align-items:center!important;
    gap:12px!important;
    padding:10px 15px!important;
    border-radius:10px!important;
    color:#f7faff!important;
    font-size:14px!important;
    font-weight:800!important;
    text-decoration:none!important;
}
.nav-links a:hover{background:rgba(255,255,255,.09)!important;}
.nav-links a:first-child{
    background:linear-gradient(90deg,#2c7ef0,#1779ec)!important;
    box-shadow:0 5px 15px rgba(27,115,230,.24)!important;
}

/* TOP BAR */
.sgb-topbar{
    position:fixed!important;
    left:289px!important;
    right:0!important;
    top:0!important;
    height:65px!important;
    box-sizing:border-box!important;
    padding:0 18px 0 20px!important;
    display:flex!important;
    align-items:center!important;
    justify-content:space-between!important;
    background:#fff!important;
    border-bottom:1px solid #e4eaf3!important;
    box-shadow:0 2px 10px rgba(25,55,90,.04)!important;
    z-index:900!important;
}
.sgb-menu{
    width:39px!important;
    height:39px!important;
    padding:0!important;
    border:0!important;
    border-radius:10px!important;
    background:#f2f6fc!important;
    color:#456589!important;
    font-size:22px!important;
    line-height:39px!important;
}
.sgb-topbar-right{gap:16px!important;}
.sgb-bell{
    padding-right:16px!important;
    border-right:1px solid #dfe6ef!important;
    font-size:24px!important;
}
.sgb-user{
    gap:10px!important;
    color:#18365e!important;
    font-size:15px!important;
    font-weight:900!important;
}
.sgb-avatar{
    width:39px!important;
    height:39px!important;
    background:#edf2f8!important;
    border:2px solid #cad7e8!important;
    font-size:20px!important;
}

/* MAIN */
.container{
    width:auto!important;
    max-width:none!important;
    margin:0 0 0 289px!important;
    padding:79px 22px 34px!important;
    box-sizing:border-box!important;
}
.footer{
    margin-left:289px!important;
    background:transparent!important;
}

/* HERO */
.hero.dashboard-hero{
    position:relative!important;
    min-height:226px!important;
    height:226px!important;
    box-sizing:border-box!important;
    margin:0 0 17px!important;
    padding:23px 34px!important;
    display:flex!important;
    align-items:center!important;
    gap:28px!important;
    overflow:hidden!important;
    border-radius:18px!important;
    background:
        radial-gradient(circle at 91% 8%,rgba(255,255,255,.13) 0 90px,transparent 91px),
        radial-gradient(circle at 90% 90%,rgba(255,255,255,.08) 0 150px,transparent 151px),
        linear-gradient(115deg,#086fdf 0%,#2f54e9 56%,#803fee 100%)!important;
    box-shadow:0 8px 25px rgba(40,91,211,.18)!important;
}
.hero.dashboard-hero::before{
    content:""!important;
    position:absolute!important;
    right:-80px!important;
    top:-205px!important;
    width:380px!important;
    height:380px!important;
    border-radius:50%!important;
    border:42px solid rgba(255,255,255,.07)!important;
}
.hero.dashboard-hero::after{
    content:""!important;
    position:absolute!important;
    right:-125px!important;
    bottom:-255px!important;
    width:420px!important;
    height:420px!important;
    border-radius:50%!important;
    border:42px solid rgba(255,255,255,.065)!important;
}
.hero-logo{
    position:relative!important;
    z-index:4!important;
    width:128px!important;
    height:128px!important;
    flex:0 0 128px!important;
    padding:5px!important;
    border-radius:50%!important;
    background:#fff!important;
    box-shadow:0 5px 17px rgba(0,0,0,.15)!important;
}
.hero-copy{
    position:relative!important;
    z-index:5!important;
    min-width:0!important;
}
.hero.dashboard-hero .hero-org{
    position:relative!important;
    display:inline-flex!important;
    align-items:center!important;
    margin:0 0 4px!important;
    color:#fff!important;
    font-size:15px!important;
    font-weight:900!important;
    letter-spacing:.3px!important;
    white-space:nowrap!important;
}
.hero.dashboard-hero .hero-org::before,
.hero.dashboard-hero .hero-org::after{
    content:""!important;
    display:inline-block!important;
    width:45px!important;
    height:1px!important;
    margin:0 12px!important;
    background:rgba(255,255,255,.75)!important;
}
.hero.dashboard-hero h1{
    margin:0!important;
    color:#fff!important;
    font-size:49px!important;
    line-height:1.03!important;
    font-weight:950!important;
    letter-spacing:.2px!important;
}
.hero.dashboard-hero .hero-subtitle{
    margin:3px 0 7px!important;
    color:#fff!important;
    font-size:20px!important;
    line-height:1.15!important;
    font-weight:900!important;
}
.hero.dashboard-hero p{
    margin:0!important;
    color:#fff!important;
    font-size:16px!important;
    line-height:1.35!important;
}
.hero.dashboard-hero .hero-time{
    margin-top:11px!important;
    color:#fff!important;
    font-size:15px!important;
    font-weight:900!important;
}

/* FILTER PANEL */
.dashboard-filters{
    box-sizing:border-box!important;
    margin:0 0 19px!important;
    padding:16px 25px 17px!important;
    border:1px solid #dbe6f4!important;
    border-radius:17px!important;
    background:#fff!important;
    box-shadow:0 5px 18px rgba(21,55,95,.055)!important;
}
.dashboard-filters .filter-grid{
    display:grid!important;
    grid-template-columns:1fr 1fr!important;
    gap:22px!important;
}
.dashboard-filters label{
    display:block!important;
    margin:0 0 8px!important;
    color:#31517c!important;
    font-size:13px!important;
    font-weight:900!important;
}
.dashboard-filters select{
    width:100%!important;
    height:48px!important;
    box-sizing:border-box!important;
    padding:0 15px!important;
    border:1px solid #cbd9eb!important;
    border-radius:10px!important;
    background:#fff!important;
    color:#243f67!important;
    font-size:14px!important;
    font-weight:700!important;
}

/* KPI GRID — EXACTLY 5 + 2 */
.dashboard-cards{
    display:grid!important;
    grid-template-columns:repeat(5,minmax(0,1fr))!important;
    gap:15px!important;
    margin:0 0 19px!important;
}
.dashboard-stat{
    position:relative!important;
    min-height:114px!important;
    box-sizing:border-box!important;
    padding:18px 16px 15px 18px!important;
    overflow:hidden!important;
    border:1px solid #dfe8f4!important;
    border-radius:16px!important;
    background:#fff!important;
    box-shadow:0 5px 17px rgba(20,53,92,.055)!important;
}
.dashboard-stat::before{
    content:""!important;
    position:absolute!important;
    left:0!important;
    top:0!important;
    bottom:0!important;
    width:4px!important;
    border-radius:16px 0 0 16px!important;
    background:#2e75e9!important;
}
.dashboard-stat.green-card::before{background:#13a35e!important;}
.dashboard-stat.red-card::before{background:#ee334b!important;}
.dashboard-stat.orange-card::before{background:#ff820d!important;}
.dashboard-stat.purple-card::before{background:#7237e7!important;}
.dashboard-stat.blue-card::before{background:#2876ea!important;}

.dashboard-stat .stat-icon{
    position:absolute!important;
    left:17px!important;
    top:17px!important;
    width:50px!important;
    height:50px!important;
    border-radius:50%!important;
    display:flex!important;
    align-items:center!important;
    justify-content:center!important;
    color:#fff!important;
    background:#2c78eb!important;
    font-size:28px!important;
    font-weight:900!important;
}
.dashboard-stat.green-card .stat-icon{background:#14a561!important;}
.dashboard-stat.red-card .stat-icon{background:#ef334d!important;}
.dashboard-stat.orange-card .stat-icon{background:#f67d0b!important;}
.dashboard-stat.purple-card .stat-icon{background:#7138dc!important;}

.dashboard-stat .stat-title{
    margin-left:68px!important;
    margin-top:2px!important;
    color:#607590!important;
    font-size:10.5px!important;
    line-height:1.25!important;
    font-weight:900!important;
    letter-spacing:.35px!important;
    white-space:nowrap!important;
}
.dashboard-stat .stat-value{
    margin:12px 0 0 68px!important;
    color:#123d7d!important;
    font-size:27px!important;
    line-height:1!important;
    font-weight:950!important;
}
.dashboard-stat.green-card .stat-value{color:#078951!important;}
.dashboard-stat.red-card .stat-value{color:#d92843!important;}
.dashboard-stat.orange-card .stat-value{color:#e87500!important;}
.dashboard-stat.purple-card .stat-value{color:#5a32cb!important;}

/* Current lecture section */
.dashboard-section{
    margin:0 0 18px!important;
    padding:18px!important;
    border:1px solid #e0e8f3!important;
    border-radius:17px!important;
    background:#fff!important;
    box-shadow:0 5px 18px rgba(21,55,95,.055)!important;
}
.dashboard-section .report-title h2{
    color:#183963!important;
    font-size:21px!important;
    font-weight:900!important;
}
.live-dot{
    width:13px!important;
    height:13px!important;
    margin-right:8px!important;
    background:#20b968!important;
    box-shadow:0 0 0 5px #dcfce9!important;
}

/* Responsive */
@media (max-width:1100px){
    .dashboard-cards{grid-template-columns:repeat(3,minmax(0,1fr))!important;}
}
@media (max-width:900px){
    .navbar{width:235px!important;}
    .sgb-topbar{left:235px!important;}
    .container{margin-left:235px!important;}
    .footer{margin-left:235px!important;}
    .hero.dashboard-hero .hero-org{white-space:normal!important;}
    .hero.dashboard-hero h1{font-size:40px!important;}
}
@media (max-width:700px){
    .navbar{
        position:relative!important;
        width:100%!important;
        height:auto!important;
        min-height:auto!important;
        overflow:visible!important;
    }
    .navbar .brand{
        height:auto!important;
        flex-direction:row!important;
        align-items:center!important;
        justify-content:flex-start!important;
        gap:10px!important;
        text-align:left!important;
    }
    .navbar .college-logo{width:55px!important;height:55px!important;margin:0!important;}
    .nav-links{flex-direction:row!important;flex-wrap:wrap!important;}
    .nav-links a{width:auto!important;min-height:40px!important;font-size:12px!important;}
    .sgb-topbar{
        position:relative!important;
        left:auto!important;
        height:58px!important;
    }
    .container{
        width:96%!important;
        margin:0 auto!important;
        padding:15px 0 35px!important;
    }
    .footer{margin-left:0!important;}
    .hero.dashboard-hero{
        height:auto!important;
        min-height:180px!important;
        padding:18px!important;
    }
    .hero-logo{width:78px!important;height:78px!important;flex-basis:78px!important;}
    .hero.dashboard-hero .hero-org{font-size:9px!important;}
    .hero.dashboard-hero .hero-org::before,
    .hero.dashboard-hero .hero-org::after{width:20px!important;margin:0 5px!important;}
    .hero.dashboard-hero h1{font-size:29px!important;}
    .hero.dashboard-hero .hero-subtitle{font-size:14px!important;}
    .hero.dashboard-hero p{font-size:12px!important;}
    .dashboard-filters .filter-grid{grid-template-columns:1fr!important;}
    .dashboard-cards{grid-template-columns:repeat(2,minmax(0,1fr))!important;}
}


/* FINAL COLLEGE PHOTO + PROFESSIONAL SIDEBAR ICONS */
.nav-links a svg{
    width:22px!important;height:22px!important;flex:0 0 22px!important;
    fill:none!important;stroke:currentColor!important;stroke-width:1.9!important;
    stroke-linecap:round!important;stroke-linejoin:round!important;
}
.hero-campus-photo{
    position:absolute!important;right:0!important;top:0!important;bottom:0!important;
    width:39%!important;min-width:350px!important;overflow:hidden!important;z-index:1!important;
}
.hero-campus-photo img{
    width:100%!important;height:100%!important;display:block!important;
    object-fit:cover!important;object-position:center 52%!important;
    filter:saturate(.84) contrast(.97)!important;
}
.hero-campus-overlay{
    position:absolute!important;inset:0!important;
    background:linear-gradient(90deg,rgba(19,83,225,.99) 0%,rgba(42,79,229,.82) 20%,rgba(88,60,231,.38) 55%,rgba(120,57,235,.10) 100%)!important;
}
.hero-campus-photo::after{content:""!important;position:absolute!important;inset:0!important;background:linear-gradient(180deg,rgba(255,255,255,.03),rgba(0,0,0,.10))!important;}
.hero.dashboard-hero .hero-copy{max-width:62%!important;z-index:5!important;}
@media(max-width:1000px){.hero-campus-photo{width:35%!important;min-width:240px!important}.hero.dashboard-hero .hero-copy{max-width:68%!important}}
@media(max-width:700px){.hero-campus-photo{width:100%!important;min-width:0!important;opacity:.25!important}.hero.dashboard-hero .hero-copy{max-width:100%!important}.hero-campus-overlay{background:linear-gradient(90deg,rgba(15,91,226,.98),rgba(104,55,235,.88))!important}}

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

    <a href="{{ url_for('home') }}" class="brand">
        <img
            src="{{ url_for('static', filename='college-logo.png') }}"
            alt="SGB College Logo"
            class="college-logo"
        >

        <div class="logo">
            SGB COLLEGE
            <small>COLLEGE MANAGEMENT SYSTEM</small>
        </div>
    </a>

    <div class="nav-links">
        <a href="{{ url_for('home') }}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5v9a1.5 1.5 0 0 1-1.5 1.5H4.5A1.5 1.5 0 0 1 3 19.5z"/><path d="M9 21v-6h6v6"/></svg> Dashboard</a>
        <a href="{{ url_for('master_timetable') }}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v17H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 4.5v17M8 6h8M8 10h8"/></svg> All Classes</a>
        <a href="{{ url_for('timetable_page') }}"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 9h18M7 13h3M14 13h3M7 17h3"/></svg> Daily Timetable</a>

        {% if current_user_obj and current_user_obj.is_admin %}
            <a href="{{ url_for('attendance') }}"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></svg> Attendance</a>
            <a href="{{ url_for('reports') }}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg> Reports</a>
            <a href="{{ url_for('access_control') }}"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17" cy="9" r="2.5"/><path d="M15.5 15c2.8-.2 5.5 1.7 5.5 5"/></svg> Users</a>
            <a href="{{ url_for('college_location') }}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s7-6.1 7-12a7 7 0 1 0-14 0c0 5.9 7 12 7 12z"/><circle cx="12" cy="9" r="2.3"/></svg> College Location</a>
            <a href="{{ url_for('timetable_manage') }}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9.5 3 .5 2a7.5 7.5 0 0 1 4 0l.5-2 2.1.9-.8 1.9a8 8 0 0 1 2.8 2.8l1.9-.8.9 2.1-2 .5a7.5 7.5 0 0 1 0 4l2 .5-.9 2.1-1.9-.8a8 8 0 0 1-2.8 2.8l.8 1.9-2.1.9-.5-2a7.5 7.5 0 0 1-4 0l-.5 2-2.1-.9.8-1.9a8 8 0 0 1-2.8-2.8l-1.9.8-.9-2.1 2-.5a7.5 7.5 0 0 1 0-4l-2-.5.9-2.1 1.9.8A8 8 0 0 1 7.3 7.8L6.5 5.9z"/><circle cx="12" cy="12" r="3"/></svg> Manage Timetable</a>
            <a href="{{ url_for('logout') }}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5M14 8l4 4-4 4M8 12h10"/></svg> Logout</a>
        {% elif current_user_obj and current_user_obj.assigned_subject %}
            <a href="{{ url_for('attendance') }}"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></svg> Attendance</a>
            <a href="{{ url_for('logout') }}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5M14 8l4 4-4 4M8 12h10"/></svg> Logout</a>
        {% else %}
            <a href="{{ url_for('login') }}"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg> Login</a>
        {% endif %}
    </div>

</nav>

<header class="sgb-topbar">
    <div class="sgb-topbar-left">
        <button class="sgb-menu" type="button" aria-label="Menu">☰</button>
    </div>
    <div class="sgb-topbar-right">
        <span class="sgb-bell" aria-label="Notifications">🔔</span>
        <div class="sgb-user">
            <span class="sgb-avatar">👤</span>
            <span>{{ current_user_obj.name if current_user_obj else "Guest" }}</span>
        </div>
    </div>
</header>

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
    # Some pages (especially Attendance) need current_user_obj while their
    # inner template is rendered. Do not pass that same keyword twice to the
    # outer BASE_HTML template, otherwise Flask/Jinja raises a 500 error.
    page_user = context.get("current_user_obj") or current_user()

    body = render_template_string(content, **context)

    context.pop("current_user_obj", None)
    page_title = context.pop(
        "page_title",
        "SGB College Management"
    )

    return render_template_string(
        BASE_HTML,
        content=body,
        current_user_obj=page_user,
        page_title=page_title,
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
        "all"
    )
    if year not in years and year != "all":
        year = "all"

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
<div class="hero dashboard-hero">
    <img src="{{ url_for('static', filename='college-logo.png') }}"
         alt="College Logo" class="hero-logo">
    <div class="hero-copy">
        <div class="hero-org">SHRI GURU BUDDHISWAMI SHIKSHAN PRASARAK SANSTHA'S</div>
        <h1>SGB COLLEGE</h1>
        <p class="hero-subtitle">COLLEGE MANAGEMENT SYSTEM</p>
        <p style="margin-top:6px;">Timetable, live lecture and permanent attendance management</p>
        <div class="time hero-time" id="live-clock">◷ &nbsp; India Time: {{ now_time }}</div>
    </div>
    <div class="hero-campus-photo" aria-label="SGB College Campus">
        <img src="{{ url_for('static', filename='college-building.jpg') }}" alt="SGB College Campus">
        <div class="hero-campus-overlay"></div>
    </div>
</div>

<form class="dashboard-filters" method="get">
    <div class="filter-grid">
        <div>
            <label>Faculty</label>
            <select name="faculty" onchange="this.form.submit()">
                {% for f in faculties %}
                    <option value="{{ f }}" {% if f == faculty %}selected{% endif %}>{{ f }}</option>
                {% endfor %}
            </select>
        </div>
        <div>
            <label>Year</label>
            <select name="year" onchange="this.form.submit()">
                {% for y in years %}
                    <option value="{{ y }}" {% if y == year %}selected{% endif %}>{{ y }}</option>
                {% endfor %}
            </select>
        </div>
    </div>
</form>

<div id="live-data" data-faculty="{{ faculty }}" data-year="{{ year }}"></div>

<div class="dashboard-cards">
    <div class="dashboard-stat green-card">
        <div class="stat-icon">◫</div>
        <div class="stat-title">CURRENT LECTURE</div>
        <div class="stat-value green">{% if current %}LIVE{% else %}—{% endif %}</div>
    </div>
    <div class="dashboard-stat blue-card">
        <div class="stat-icon">≫</div>
        <div class="stat-title">NEXT LECTURE</div>
        <div class="stat-value blue">{% if upcoming %}{{ upcoming[0].slot }}{% else %}—{% endif %}</div>
    </div>
    <div class="dashboard-stat purple-card">
        <div class="stat-icon">▦</div>
        <div class="stat-title">TODAY'S LECTURES</div>
        <div class="stat-value purple">{{ today_rows|length }}</div>
    </div>
    <div class="dashboard-stat green-card">
        <div class="stat-icon">✓</div>
        <div class="stat-title">TAKEN TODAY</div>
        <div class="stat-value green">{{ stats.taken }}</div>
    </div>
    <div class="dashboard-stat red-card">
        <div class="stat-icon">×</div>
        <div class="stat-title">NOT TAKEN</div>
        <div class="stat-value red">{{ stats.not_taken }}</div>
    </div>
    <div class="dashboard-stat orange-card">
        <div class="stat-icon">⊘</div>
        <div class="stat-title">CANCELLED</div>
        <div class="stat-value orange">{{ stats.cancelled }}</div>
    </div>
    <div class="dashboard-stat purple-card">
        <div class="stat-icon">%</div>
        <div class="stat-title">ATTENDANCE %</div>
        <div class="stat-value blue">{{ "%.1f"|format(stats.percentage) }}%</div>
    </div>
</div>

<div class="dashboard-section">
    <div class="report-title">
        <h2><span class="live-dot"></span>Current Lecture</h2>
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

<div class="dashboard-section">
    <div class="report-title">
        <h2>⏭ Next Lecture</h2>
        <a class="btn btn-blue" href="{{ url_for('timetable_page', faculty=faculty, year=year, day=today_name) }}">View Timetable</a>
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

<div class="dashboard-section">
    <div class="report-title">
        <h2>📅 Today's Timetable</h2>
        <a class="btn btn-blue" href="{{ url_for('timetable_page', faculty=faculty, year=year, day=today_name) }}">Open Daily Timetable</a>
    </div>
    {% if today_rows %}
        {% for row in today_rows %}
            <div class="lecture {% if is_current_slot(row.slot, today_name) %}live{% endif %}">
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
                {% if is_current_slot(row.slot, today_name) %}
                    <span class="badge badge-live">LIVE NOW</span>
                {% else %}
                    <span class="badge badge-none">SCHEDULED</span>
                {% endif %}
            </div>
        {% endfor %}
    {% else %}
        <div class="empty">No timetable entries for today.</div>
    {% endif %}
</div>

<div class="dashboard-section">
    <div class="report-title"><h2>⚡ Quick Access</h2></div>
    <div class="quick-actions">
        <a class="quick-action" href="{{ url_for('master_timetable') }}">📚 All Classes</a>
        <a class="quick-action" href="{{ url_for('timetable_page', faculty=faculty, year=year, day=today_name) }}">📅 Daily Timetable</a>
        {% if current_user_obj and current_user_obj.is_admin %}
            <a class="quick-action" href="{{ url_for('attendance', faculty=faculty, year=year, day=today_name) }}">📝 Mark Attendance</a>
        {% else %}
            <a class="quick-action" href="{{ url_for('login') }}">🔐 Admin Login</a>
        {% endif %}
    </div>
</div>

<script>
async function prepareAttendanceForm(form, submitter) {
    // form.submit() does not include the clicked button's name/value.
    // Preserve the selected attendance status before submitting after GPS verification.
    if (submitter && submitter.name && submitter.value) {
        let statusInput = form.querySelector('input[data-attendance-status="1"]');
        if (!statusInput) {
            statusInput = document.createElement("input");
            statusInput.type = "hidden";
            statusInput.dataset.attendanceStatus = "1";
            statusInput.name = submitter.name;
            form.appendChild(statusInput);
        }
        statusInput.value = submitter.value;
    }

    if (form.dataset.locationReady === "1") return true;

    if (!navigator.geolocation) {
        alert("This device/browser does not support location access. Please use Chrome/Edge with Location enabled.");
        return false;
    }

    navigator.geolocation.getCurrentPosition(function(position) {
        const addHidden = (name, value) => {
            let input = form.querySelector('input[name="' + name + '"]');
            if (!input) {
                input = document.createElement("input");
                input.type = "hidden";
                input.name = name;
                form.appendChild(input);
            }
            input.value = value;
        };

        addHidden("latitude", position.coords.latitude);
        addHidden("longitude", position.coords.longitude);
        addHidden("location_accuracy", position.coords.accuracy || "");
        form.dataset.locationReady = "1";
        // Submit the original clicked button so its name/value is preserved.
        if (typeof form.requestSubmit === "function" && submitter) {
            form.requestSubmit(submitter);
        } else {
            form.submit();
        }
    }, function(error) {
        let message = "Location access is required to mark attendance.";
        if (error.code === 1) message += " Please click the lock icon near the website address and allow Location.";
        if (error.code === 2) message += " Your device could not determine its location.";
        if (error.code === 3) message += " Location request timed out. Please try again.";
        alert(message);
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 });

    return false;
}
</script>
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
# MASTER TIMETABLE DISPLAY HELPERS
# ============================================================

def short_subject_label(value):
    """Compact timetable labels while preserving the actual subject text."""
    import re
    text = str(value or "").strip()
    text = re.sub(r"^Major\s*:", "Maj:", text, flags=re.IGNORECASE)
    text = re.sub(r"^Minor\s*:", "Min:", text, flags=re.IGNORECASE)
    text = re.sub(r"^Major\s+", "Maj: ", text, flags=re.IGNORECASE)
    text = re.sub(r"^Minor\s+", "Min: ", text, flags=re.IGNORECASE)
    return text


def subject_color_class(value):
    """Stable subject color; also recognizes labels such as 'Practical: Physics'."""
    import re
    key = normalize_subject(value) if 'normalize_subject' in globals() else str(value or '').strip().lower()
    key = re.sub(r"^maj:\s*", "", key)
    key = re.sub(r"^min:\s*", "", key)
    if "physics" in key:
        return "subject-blue"
    if "chemistry" in key:
        return "subject-purple"
    if "computer science" in key or key == "comp sci" or "computer" in key:
        return "subject-green"
    if "mathematics" in key or key == "math":
        return "subject-orange"
    if "microbiology" in key or key == "micro" or "microbiology" in key:
        return "subject-teal"
    if "botany" in key:
        return "subject-olive"
    if "zoology" in key:
        return "subject-pink"
    if "english" in key:
        return "subject-indigo"
    return "subject-slate"


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
                                        <div class="lecture-cell {{ subject_color_class(row.subject) }} {% if is_current_slot(row.slot, day) %}current-cell{% endif %}">
                                            <strong class="subject-name">{{ short_subject_label(row.subject) }}</strong>

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
        short_subject_label=short_subject_label,
        subject_color_class=subject_color_class,
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
            <table class="daily-timetable-table">
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
                            <td><span class="subject-badge subject-color-{{ loop.index0 % 8 }}">{{ row.subject }}</span></td>
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
# TEACHER LOCATION VERIFICATION AT LOGIN
# ============================================================

@app.route("/teacher-location")
@login_required
def teacher_location():
    user = current_user()
    if not user or user.is_admin:
        return redirect(url_for("home"))

    # A teacher must verify their current GPS location before attendance is
    # available. Attendance POST also checks the live GPS position again.
    content = r"""
<div class="hero">
    <h1>📍 Location Verification Required</h1>
    <p>Allow your phone/browser location before you can mark attendance.</p>
</div>

<div class="section" style="border-left:5px solid #16a34a;">
    <h2>Teacher: {{ current_user_obj.name }}</h2>
    <p>Your attendance access will open only after your current location is verified inside the college area.</p>

    <div id="locationStatus" style="padding:14px;border-radius:10px;background:#f1f5f9;margin:14px 0;">
        📍 Requesting location permission...
    </div>

    <button type="button" class="btn btn-blue" id="locationButton" onclick="requestTeacherLocation()">
        📍 Allow Location & Continue
    </button>

    <p style="margin-top:14px;font-size:13px;color:#667085;">
        If no permission popup appears, open your browser site settings for this website and set
        <b>Location → Allow</b>, then reload this page. You must be physically inside the configured
        college area.
    </p>
</div>

<script>
function setStatus(text, ok=false) {
    const el = document.getElementById('locationStatus');
    el.textContent = text;
    el.style.background = ok ? '#ecfdf3' : '#f1f5f9';
    el.style.color = ok ? '#166534' : '#111827';
}

function requestTeacherLocation() {
    if (!navigator.geolocation) {
        setStatus('❌ This phone/browser does not support GPS location. Use Chrome or Safari with Location enabled.');
        return;
    }

    setStatus('📍 Please allow Location when your browser asks...');
    navigator.geolocation.getCurrentPosition(function(position) {
        setStatus('📍 Location received. Verifying with the college server...');

        fetch('{{ url_for("verify_teacher_location") }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: new URLSearchParams({
                latitude: position.coords.latitude,
                longitude: position.coords.longitude,
                location_accuracy: position.coords.accuracy || ''
            })
        }).then(r => r.json()).then(data => {
            if (data.ok) {
                setStatus('✅ ' + data.message + ' Attendance access is now enabled.', true);
                setTimeout(() => { window.location.href = '{{ url_for("attendance") }}'; }, 700);
            } else {
                setStatus('❌ ' + data.message);
            }
        }).catch(() => {
            setStatus('❌ Could not verify location with the server. Check your internet connection and try again.');
        });
    }, function(error) {
        let message = '❌ Location permission is required.';
        if (error.code === 1) message += ' Tap the browser site/lock settings and set Location to Allow, then try again.';
        if (error.code === 2) message += ' Your phone could not determine its location. Turn on phone Location/GPS.';
        if (error.code === 3) message += ' Location request timed out. Try again outdoors or near a window.';
        setStatus(message);
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
}

// Request immediately after the page loads so the browser can show its
// location permission prompt. The button remains available if the prompt
// was previously denied or the browser requires a user gesture.
window.addEventListener('load', requestTeacherLocation);
</script>
"""
    return render_page(
        content,
        current_user_obj=user,
        page_title="Teacher Location Verification"
    )


@app.route("/teacher-location/verify", methods=["POST"])
@login_required
def verify_teacher_location():
    user = current_user()
    if not user or user.is_admin:
        return jsonify(ok=False, message="Teacher location verification is not required for this account."), 403

    latitude = request.form.get("latitude", "").strip()
    longitude = request.form.get("longitude", "").strip()

    allowed, message = location_allowed(latitude, longitude)
    if not allowed:
        session["location_verified"] = False
        return jsonify(ok=False, message=message), 403

    session["location_verified"] = True
    session["location_verified_at"] = now_ist().isoformat()
    return jsonify(ok=True, message=message)


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
            # Teachers are single-session accounts. A second login is refused
            # until the existing teacher session explicitly logs out.
            if not user.is_admin and user.active_session_token:
                flash("This teacher account is already logged in on another device/browser. Please logout there first.")
                return redirect(url_for("login"))

            session.clear()
            session["user_id"] = user.id

            if not user.is_admin:
                user.active_session_token = uuid.uuid4().hex
                db.session.commit()
                session["active_session_token"] = user.active_session_token
                session["location_verified"] = False

                # Every teacher login must pass the GPS check before attendance.
                return redirect(url_for("teacher_location"))

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
    user_id = session.get("user_id")
    if user_id:
        user = db.session.get(User, user_id)
        if user and not user.is_admin:
            user.active_session_token = None
            db.session.commit()
    session.clear()
    return redirect(url_for("home"))


# ============================================================
# ATTENDANCE PERMISSION HELPERS
# ============================================================

def normalize_subject(value):
    """Normalize subject names for teacher access control.

    Teacher accounts use short subjects (comp sci, math, micro), while the
    timetable may contain labels such as Computer Science-B-13,
    Practical: Physics, SEC: Physics, Major: Computer Science-B-13,
    Chemistry-B-14, Mathematics-B-17 and Microbiology-B-7.
    """
    import re

    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)

    # Remove timetable category/paper prefixes.
    text = re.sub(
        r"^(major|minor|elective|vc|sl|practical|practicals|sec|aec|vac|ge|oe|compulsory|optional)\s*:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Also support prefixes without a colon.
    text = re.sub(
        r"^(practical|practicals|sec|aec|vac|ge|oe|major|minor)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove common class/room suffixes, e.g. -B-13 / B-13 / -B-7.
    text = re.sub(r"\s*[-/]?\s*b\s*[-/]?\s*\d+\s*$", "", text)
    text = re.sub(r"\s*[-/]?\s*dept\s*$", "", text)
    text = text.strip(" -:/")

    aliases = {
        "comp sci": "computer science",
        "computer sci": "computer science",
        "computer science": "computer science",
        "cs": "computer science",
        "physics": "physics",
        "phys": "physics",
        "chem": "chemistry",
        "chemistry": "chemistry",
        "math": "mathematics",
        "maths": "mathematics",
        "mathematics": "mathematics",
        "micro": "microbiology",
        "microbio": "microbiology",
        "microbiology": "microbiology",
    }

    if text in aliases:
        return aliases[text]

    # Handle labels that still contain extra text around the subject.
    if "computer science" in text or "comp sci" in text:
        return "computer science"
    if "microbiology" in text or "microbio" in text:
        return "microbiology"
    if "physics" in text:
        return "physics"
    if "chemistry" in text or text.startswith("chem"):
        return "chemistry"
    if "mathematics" in text or text == "math" or text.startswith("math"):
        return "mathematics"

    return text


def normalize_teacher_name(value):
    """Normalize teacher names while ignoring dots/spacing/case."""
    import re
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]", "", text)


def can_mark_subject(user, subject):
    if not user:
        return False
    if user.is_admin:
        return True
    return normalize_subject(user.assigned_subject) == normalize_subject(subject)


def can_mark_lecture(user, subject, lecture_teacher):
    """Attendance permission for the five assigned teachers.

    Admin can mark everything. A teacher must match their assigned subject.
    If the timetable has a teacher name, it must also match the logged-in
    teacher. If the timetable teacher field is blank (as in the original
    timetable data), subject matching is used so valid teacher accounts are
    not incorrectly locked out.
    """
    if not user:
        return False
    if user.is_admin:
        return True

    assigned_ok = (
        normalize_subject(user.assigned_subject) == normalize_subject(subject)
    )
    if not assigned_ok:
        return False

    timetable_teacher = str(lecture_teacher or "").strip()
    if not timetable_teacher:
        return True

    return normalize_teacher_name(user.name) == normalize_teacher_name(timetable_teacher)


def attendance_access_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()

        if not user:
            return redirect(url_for("login", next=request.full_path))

        if not user.is_admin and not user.assigned_subject:
            flash("Attendance access is not assigned to this account.")
            return redirect(url_for("home"))

        if not user.is_admin and not session.get("location_verified"):
            return redirect(url_for("teacher_location", next=request.full_path))

        return view(*args, **kwargs)
    return wrapped


# ============================================================
# ATTENDANCE PAGE
# ============================================================

@app.route("/attendance")
@attendance_access_required
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
    <p>Secure lecture attendance — teachers can mark only their own subject and timetable lecture</p>
</div>

<div class="section" style="border-left:5px solid #16a34a;">
    <h2>📍 College Location Verification</h2>
    <p style="margin:0 0 10px;">Teachers must allow browser location access and be inside the configured college area to mark attendance.</p>
    {% if college_location_configured %}
        <span class="badge badge-taken">📍 Location verification required</span>
        <span class="meta" style="margin-left:8px;">Allowed radius: {{ college_radius }} m</span>
    {% else %}
        <span class="badge badge-not">⚠ College location not configured</span>
        <div class="meta" style="margin-top:8px;">Ask the administrator to open <b>College Location</b> while physically at the college and save the location.</div>
    {% endif %}
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

            {% set lecture_active = attendance_window_open(
                record_date, row.day, row.slot
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

                    {% set existing_record = attendance_record_for(
                        record_date, row.faculty, row.year, row.day,
                        row.slot, row.subject, row.class_name or ""
                    ) %}
                    {% if existing_record %}
                        <div class="meta" style="margin-top:7px; font-weight:800;">
                            👥 Present Students: {{ existing_record.present_count }}
                        </div>
                    {% endif %}
                </div>

                <div class="action-row">
                    {% if status %}
                        <span class="attendance-locked">🔒 Attendance locked — cannot be changed</span>
                    {% elif not can_mark_lecture(current_user_obj, row.subject, row.teacher or '') %}
                        <span class="attendance-disabled">🔐 Only the assigned teacher for this subject can mark this attendance</span>
                    {% elif lecture_active %}
                        <form class="attendance-form" method="post" action="{{ url_for('mark_attendance') }}" onsubmit="return prepareAttendanceForm(this, event.submitter);">
                            <input type="hidden" name="record_date" value="{{ record_date_text }}">
                            <input type="hidden" name="faculty" value="{{ row.faculty }}">
                            <input type="hidden" name="year" value="{{ row.year }}">
                            <input type="hidden" name="day" value="{{ row.day }}">
                            <input type="hidden" name="slot" value="{{ row.slot }}">
                            <input type="hidden" name="subject" value="{{ row.subject }}">
                            <input type="hidden" name="class_name" value="{{ row.class_name or '' }}">
                            <input type="hidden" name="teacher" value="{{ row.teacher or '' }}">

                            <div style="min-width:190px; margin-bottom:8px;">
                                <label>Present Students</label>
                                <input
                                    type="number"
                                    name="present_count"
                                    min="0"
                                    step="1"
                                    placeholder="e.g. 52 (required for Taken)"
                                >
                            </div>

                            <button class="btn btn-green btn-small" name="status" value="taken">
                                ✓ Taken
                            </button>

                            <button class="btn btn-red btn-small" name="status" value="not_taken">
                                ✕ Not Taken
                            </button>

                            <button class="btn btn-orange btn-small" name="status" value="cancelled">
                                Cancelled
                            </button>
                        </form>
                    {% else %}
                        <span class="attendance-disabled">⏱️ Marking is available only during this lecture</span>
                    {% endif %}
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
        attendance_record_for=attendance_record_for,
        attendance_window_open=attendance_window_open,
        current_user_obj=current_user(),
        can_mark_subject=can_mark_subject,
        can_mark_lecture=can_mark_lecture,
        college_location_configured=(get_college_location() is not None),
        college_radius=(get_college_location().radius_meters if get_college_location() else 150),
        page_title="Attendance"
    )


# ============================================================
# MARK / EDIT ATTENDANCE
# ============================================================

@app.route("/attendance/mark", methods=["POST"])
@attendance_access_required
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
    latitude = request.form.get("latitude", "").strip()
    longitude = request.form.get("longitude", "").strip()

    present_count_raw = request.form.get("present_count", "").strip()
    status = request.form.get("status", "").strip()

    # Present student count is required only when a lecture is marked Taken.
    # Not Taken and Cancelled do not require a student count.
    if status == "taken":
        try:
            present_count = int(present_count_raw)
        except (TypeError, ValueError):
            flash("Please enter the present student number before marking Taken.")
            return redirect(url_for(
                "attendance", faculty=faculty, year=year, day=day,
                record_date=record_date.isoformat()
            ))
        if present_count < 0:
            flash("Present student number cannot be negative.")
            return redirect(url_for(
                "attendance", faculty=faculty, year=year, day=day,
                record_date=record_date.isoformat()
            ))
    else:
        present_count = 0

    if not all([faculty, year, day, slot, subject]):
        flash("Incomplete lecture information.")
        return redirect(url_for("attendance"))

    if day not in DAYS:
        flash("Invalid day.")
        return redirect(url_for("attendance"))

    user = current_user()

    # First verify that the submitted lecture actually exists in the timetable.
    # This prevents a teacher from crafting a fake slot/lecture in the browser.
    lecture = Timetable.query.filter_by(
        faculty=faculty,
        year=year,
        day=day,
        slot=slot,
        subject=subject,
        class_name=class_name or None
    ).first()

    if not lecture:
        # Some old timetable rows may have an empty class_name stored as an
        # empty string instead of NULL, so retry without class_name.
        lecture = Timetable.query.filter_by(
            faculty=faculty,
            year=year,
            day=day,
            slot=slot,
            subject=subject
        ).first()

    if not lecture:
        flash("This lecture does not exist in the timetable.")
        return redirect(url_for(
            "attendance", faculty=faculty, year=year, day=day,
            record_date=record_date.isoformat()
        ))

    if not class_name:
        class_name = lecture.class_name or ""
    if not teacher:
        teacher = lecture.teacher or ""

    # Strict server-side enforcement: non-admin teachers must match BOTH
    # the assigned subject and the teacher name on this exact timetable row.
    if not can_mark_lecture(user, lecture.subject, lecture.teacher or ""):
        flash("You can mark attendance only for your own assigned subject and lecture.")
        return redirect(url_for(
            "attendance", faculty=faculty, year=year, day=day,
            record_date=record_date.isoformat()
        ))

    # Teachers must prove they are physically inside the configured college
    # geofence. The administrator is exempt so they can manage the system.
    if not user.is_admin:
        allowed, location_message = location_allowed(latitude, longitude)
        if not allowed:
            flash("📍 " + location_message)
            return redirect(url_for(
                "attendance", faculty=faculty, year=year, day=day,
                record_date=record_date.isoformat()
            ))

    record = attendance_record_for(
        record_date,
        faculty,
        year,
        day,
        slot,
        subject,
        class_name
    )

    # Once attendance is saved, it is permanently locked.
    if record:
        flash("Attendance is already marked and cannot be changed.")

    # Attendance can only be marked while the lecture is running today.
    elif not attendance_window_open(record_date, day, slot):
        flash("Attendance can only be marked during the scheduled lecture time.")

    elif status in VALID_STATUSES:
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
            present_count=present_count,
            marked_by_user_id=user.id,
            marked_by=user.name,
            marked_at=now_ist_naive()
        )
        db.session.add(record)
        db.session.commit()

        flash(
            f"{subject} — {VALID_STATUSES[status]} "
            f"for {record_date.strftime('%d-%m-%Y')}. Attendance is now locked."
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
        "all"
    )
    if year not in years and year != "all":
        year = "all"

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
                <option value="all" {% if year == "all" %}selected{% endif %}>All Years</option>
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
                <option value="">Select Class (optional)</option>
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
                <option value="semester1" {% if period == "semester1" %}selected{% endif %}>Semester 1 (January – June)</option>
                <option value="semester2" {% if period == "semester2" %}selected{% endif %}>Semester 2 (July – December)</option>
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
        {{ faculty }} • {% if year == "all" %}All Years{% else %}{{ year }}{% endif %}
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
                        <th>Present Students</th>
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
                            <td><strong>{{ r.present_count }}</strong></td>

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
        "all"
    )
    if year not in years and year != "all":
        year = "all"

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
        "Present Students",
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
            r.present_count,
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
# COLLEGE LOCATION / GEOFENCE
# ============================================================

@app.route("/admin/college-location", methods=["GET", "POST"])
@admin_required
def college_location():
    location = get_college_location()

    if request.method == "POST":
        try:
            latitude = float(request.form.get("latitude", ""))
            longitude = float(request.form.get("longitude", ""))
            radius = float(request.form.get("radius_meters", "150"))
        except (TypeError, ValueError):
            flash("Please provide a valid GPS location and radius.")
            return redirect(url_for("college_location"))

        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            flash("Invalid GPS coordinates.")
            return redirect(url_for("college_location"))

        if not (50 <= radius <= 1000):
            flash("Radius must be between 50 and 1000 meters.")
            return redirect(url_for("college_location"))

        if not location:
            location = CollegeLocation(
                latitude=latitude,
                longitude=longitude,
                radius_meters=radius,
                updated_at=now_ist_naive()
            )
            db.session.add(location)
        else:
            location.latitude = latitude
            location.longitude = longitude
            location.radius_meters = radius
            location.updated_at = now_ist_naive()

        db.session.commit()
        flash("📍 College location saved successfully. Teachers can now mark attendance only inside this area.")
        return redirect(url_for("college_location"))

    content = r"""
<div class="hero">
    <h1>📍 College Attendance Location</h1>
    <p>Set the official college GPS point. Teachers must be inside the allowed radius to mark attendance.</p>
</div>

<div class="section">
    <h2>Set location from this device</h2>
    <p class="meta">Open this page while you are physically at the college. Then click <b>Use My Current Location</b>.</p>

    {% if location %}
        <div class="alert">
            Current location: {{ "%.6f"|format(location.latitude) }}, {{ "%.6f"|format(location.longitude) }}
            • Radius: {{ location.radius_meters|round|int }} m
        </div>
    {% endif %}

    <form method="post" id="locationForm">
        <div class="filter-grid">
            <div>
                <label>Latitude</label>
                <input id="latitude" name="latitude" required readonly value="{{ location.latitude if location else '' }}">
            </div>
            <div>
                <label>Longitude</label>
                <input id="longitude" name="longitude" required readonly value="{{ location.longitude if location else '' }}">
            </div>
            <div>
                <label>Allowed Radius (meters)</label>
                <input type="number" name="radius_meters" min="50" max="1000" step="1" value="{{ location.radius_meters|round|int if location else 150 }}" required>
            </div>
        </div>
        <br>
        <button type="button" class="btn btn-blue" onclick="captureCollegeLocation()">📍 Use My Current Location</button>
        <button type="submit" class="btn btn-green" id="saveLocation" disabled>💾 Save College Location</button>
        <p id="locationMessage" class="meta" style="margin-top:10px;"></p>
    </form>
</div>

<div class="section">
    <h2>How it works</h2>
    <ul>
        <li>Teacher opens Attendance and allows browser Location permission.</li>
        <li>The server checks the teacher's GPS coordinates against this college point.</li>
        <li>Only teachers inside the configured radius can save attendance.</li>
        <li>The normal subject + teacher + lecture-time restrictions still apply.</li>
    </ul>
</div>

<script>
function captureCollegeLocation() {
    const msg = document.getElementById("locationMessage");
    if (!navigator.geolocation) {
        msg.textContent = "This browser does not support location access.";
        return;
    }
    msg.textContent = "Requesting your current location...";
    navigator.geolocation.getCurrentPosition(function(position) {
        document.getElementById("latitude").value = position.coords.latitude.toFixed(7);
        document.getElementById("longitude").value = position.coords.longitude.toFixed(7);
        document.getElementById("saveLocation").disabled = false;
        msg.textContent = "Location captured. Verify that you are physically at the college, then save.";
    }, function(error) {
        msg.textContent = "Location access failed. Please allow Location in the browser site settings and try again.";
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
}
</script>
"""

    return render_page(
        content,
        location=location,
        page_title="College Location"
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
                    <th>Attendance Subject</th>
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
                                <span class="badge badge-none">TEACHER</span>
                            {% endif %}
                        </td>
                        <td>{{ u.assigned_subject or "All subjects" }}</td>
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
