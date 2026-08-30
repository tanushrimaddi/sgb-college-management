# ============================================================
# MASTER TIMETABLE
# ============================================================

@app.route("/master-timetable")
def master_timetable():

    faculties = get_faculties()

    # Default faculties if timetable.json is empty
    if not faculties:
        faculties = [
            "Arts",
            "Commerce",
            "Science"
        ]

    faculty = request.args.get(
        "faculty",
        "Arts"
    )

    if faculty not in faculties:
        faculty = faculties[0]

    years = get_years(faculty)

    # Make sure all 3 years are available
    if not years:
        years = [
            "1st Year",
            "2nd Year",
            "3rd Year"
        ]

    year = request.args.get(
        "year",
        "1st Year"
    )

    if year not in years:
        year = years[0]

    # --------------------------------------------------------
    # COLLECT ALL TIME SLOTS
    # --------------------------------------------------------

    all_slots = set()

    for day in DAYS:

        day_data = get_day_data(
            faculty,
            year,
            day
        )

        for slot in day_data.keys():

            all_slots.add(slot)

    # Sort time slots
    def slot_sort_key(slot):

        start, end = parse_slot(slot)

        if start is None:
            return 9999

        return start

    slots = sorted(
        all_slots,
        key=slot_sort_key
    )

    # --------------------------------------------------------
    # BUILD MASTER TABLE
    # --------------------------------------------------------

    master_data = {}

    for slot in slots:

        master_data[slot] = {}

        for day in DAYS:

            value = get_day_data(
                faculty,
                year,
                day
            ).get(slot, "")

            lectures = get_lecture_list(
                value
            )

            if lectures:

                master_data[slot][day] = " / ".join(
                    lectures
                )

            else:

                master_data[slot][day] = ""

    # --------------------------------------------------------
    # HTML
    # --------------------------------------------------------

    content = """

<style>

.master-table {
    min-width: 950px;
}

.master-table th {
    text-align: center;
    color: white;
    background: #1e293b;
    position: sticky;
    top: 0;
    z-index: 5;
}

.master-table th.time-head {
    background: #2563eb;
    width: 130px;
}

.master-table td {
    vertical-align: middle;
    min-height: 65px;
}

.master-time {
    font-weight: 800;
    color: #2563eb;
    white-space: nowrap;
    background: #eff6ff;
}

.master-class {
    min-height: 45px;
    padding: 10px;
    border-radius: 8px;
    background: #f8fafc;
    font-weight: 600;
    text-align: center;
}

.master-class.live {
    background: #dcfce7;
    color: #166534;
    border: 1px solid #86efac;
}

.master-empty {
    color: #cbd5e1;
    text-align: center;
    font-size: 20px;
}

.master-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 15px;
}

.master-title {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}

@media print {

    .navbar,
    .filters,
    .footer,
    .master-actions {
        display: none !important;
    }

    body {
        background: white;
    }

    .container {
        width: 100%;
        padding: 0;
    }

    .hero {
        color: black;
        background: white;
        padding: 10px 0;
    }

    .section {
        box-shadow: none;
        padding: 0;
    }

    .master-table {
        min-width: 100%;
    }

}

</style>


<div class="hero">

<div class="master-title">

<div>

<h1>
📚 Master Timetable
</h1>

<p>
{{ faculty }} • {{ year }}
</p>

</div>

<div>

<button
type="button"
class="btn btn-green"
onclick="window.print()"
>
🖨 Print
</button>

</div>

</div>

</div>


<form
class="filters"
method="get"
>

<div class="filter-grid">


<div>

<label>
Faculty
</label>

<select
name="faculty"
onchange="this.form.submit()"
>

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


<div>

<label>
Year
</label>

<select
name="year"
onchange="this.form.submit()"
>

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


</div>

</form>


<div class="section">

<h2>
{{ faculty }} — {{ year }} Master Timetable
</h2>


{% if master_data %}

<div class="table-wrap">

<table class="master-table">

<thead>

<tr>

<th class="time-head">
⏰ Time
</th>

{% for day in days %}

<th>
{{ day }}
</th>

{% endfor %}

</tr>

</thead>


<tbody>

{% for slot in slots %}

<tr>

<td class="master-time">

{{ slot }}

</td>


{% for day in days %}

<td>

{% set subject = master_data[slot][day] %}

{% if subject %}

<div
class="master-class
{% if is_current_slot(slot, day) %}
live
{% endif %}
">

{{ subject }}

{% if is_current_slot(slot, day) %}

<br>

<span class="badge badge-live">
LIVE NOW
</span>

{% endif %}

</div>

{% else %}

<div class="master-empty">
—
</div>

{% endif %}

</td>

{% endfor %}

</tr>

{% endfor %}

</tbody>

</table>

</div>


<div class="master-actions">

<a
class="btn btn-blue"
href="{{ url_for(
'timetable_page',
faculty=faculty,
year=year,
day='Monday'
) }}"
>
📅 Daily Timetable
</a>


<a
class="btn btn-gray"
href="{{ url_for('home') }}"
>
🏠 Home
</a>

</div>


{% else %}

<div class="empty">

📚

<br><br>

No timetable available for

<strong>
{{ faculty }} — {{ year }}
</strong>

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

        days=DAYS,

        slots=slots,

        master_data=master_data,

        is_current_slot=is_current_slot

    )
