from datetime import datetime, timedelta
from collections import defaultdict
from flask import Blueprint, request, jsonify
from models.quest import quests_collection


analytics_bp = Blueprint("analytics", __name__, url_prefix="/analytics")

# -------------------------
# Bucket builders
# -------------------------

def build_daily_buckets():
    today = datetime.utcnow().date()
    return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(9, -1, -1)]

def build_weekly_buckets():
    today = datetime.utcnow().date()
    start = today - timedelta(days=today.weekday())
    return [
        (start - timedelta(weeks=i)).strftime("%G-W%V")
        for i in range(9, -1, -1)
    ]

def build_monthly_buckets():
    today = datetime.utcnow().replace(day=1)
    buckets = []
    for i in range(9, -1, -1):
        d = today - timedelta(days=32 * i)
        d = d.replace(day=1)
        buckets.append(d.strftime("%Y-%m"))
    return buckets

def build_buckets(mode):
    if mode == "daily":
        return build_daily_buckets()
    if mode == "weekly":
        return build_weekly_buckets()
    if mode == "monthly":
        return build_monthly_buckets()
    raise ValueError("Invalid mode")

# -------------------------
# Bucket key resolvers
# -------------------------

def resolve_bucket_key(date_str, mode):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    if mode == "daily":
        return d.strftime("%Y-%m-%d")
    if mode == "weekly":
        return d.strftime("%G-W%V")
    if mode == "monthly":
        return d.strftime("%Y-%m")

# -------------------------
# 1) SUMMARY (TOTAL + ACHIEVEMENT)
# -------------------------

@analytics_bp.route("/summary", methods=["GET"])
def analytics_summary():
    user_id = int(request.args.get("userId"))
    mode = request.args.get("mode", "daily")

    buckets = build_buckets(mode)
    actual = defaultdict(int)
    planned = defaultdict(int)

    quests = quests_collection.find({"userId": user_id})

    for q in quests:
        # ACTUAL
        for log in q.get("spent_logs", []):
            key = resolve_bucket_key(log["spent_at"], mode)
            if key in buckets:
                actual[key] += log["spent_minutes"]

        # PLANNED
        if q.get("deadline"):
            key = resolve_bucket_key(q["deadline"], mode)
            if key in buckets:
                planned[key] += q.get("suggested_minutes", 0)

    total_actual = sum(actual.values())
    total_planned = sum(planned.values())

    return jsonify({
        "total_actual_minutes": total_actual,
        "total_planned_minutes": total_planned,
        "achievement_rate": int(total_actual / total_planned * 100) if total_planned > 0 else 0
    })
    
# PLAN VS ACTUAL (BAR CHART)
@analytics_bp.route("/plan-vs-actual", methods=["GET"])
def plan_vs_actual():
    user_id = int(request.args.get("userId"))
    mode = request.args.get("mode", "daily")

    buckets = build_buckets(mode)
    result = {b: {"actual": 0, "planned": 0} for b in buckets}

    quests = quests_collection.find({"userId": user_id})

    for q in quests:
        for log in q.get("spent_logs", []):
            key = resolve_bucket_key(log["spent_at"], mode)
            if key in result:
                result[key]["actual"] += log["spent_minutes"]

        if q.get("deadline"):
            key = resolve_bucket_key(q["deadline"], mode)
            if key in result:
                result[key]["planned"] += q.get("suggested_minutes", 0)

    response = []
    for k in buckets:
        a = result[k]["actual"]
        p = result[k]["planned"]
        response.append({
            "bucket": k,
            "actual": a,
            "planned": p,
            "achievement": int(a / p * 100) if p > 0 else 0
        })

    return jsonify(response)

# 3) TIME SPENT BY SUBJECT (DONUT)
@analytics_bp.route("/subjects", methods=["GET"])
def subject_distribution():
    user_id = int(request.args.get("userId"))
    mode = request.args.get("mode", "daily")

    buckets = build_buckets(mode)
    subject_map = defaultdict(int)

    quests = quests_collection.find({"userId": user_id})

    for q in quests:
        subject = q.get("subject", "Unknown")
        for log in q.get("spent_logs", []):
            key = resolve_bucket_key(log["spent_at"], mode)
            if key in buckets:
                subject_map[subject] += log["spent_minutes"]

    total = sum(subject_map.values())

    return jsonify([
        {
            "subject": s,
            "minutes": m,
            "share": int(m / total * 100) if total > 0 else 0
        }
        for s, m in subject_map.items()
    ])

# 4) STREAK API
@analytics_bp.route("/streak", methods=["GET"])
def streak():
    user_id = int(request.args.get("userId"))
    quests = quests_collection.find({"userId": user_id})

    active_days = set()

    for q in quests:
        for log in q.get("spent_logs", []):
            if log["spent_minutes"] > 0:
                active_days.add(log["spent_at"])

    streak = 0
    day = datetime.utcnow().date()

    while day.strftime("%Y-%m-%d") in active_days:
        streak += 1
        day -= timedelta(days=1)

    return jsonify({"streak_days": streak})

def parse_iso_date(date_str: str):
    """
    Safely parse a date from ISO string.
    Accepts 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS.sssZ' formats.
    Returns a datetime.date object or None if invalid.
    """
    if not date_str:
        return None
    try:
        # Try full ISO with timezone
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            # Fallback to just date part
            return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
        
# 5) KANBAN SNAPSHOT API
@analytics_bp.route("/kanban", methods=["GET"])
def kanban_flow():
    user_id = int(request.args.get("userId"))
    mode = request.args.get("mode", "daily")
    end_date_str = request.args.get("date")

    # ------------------
    # End date
    # ------------------
    if end_date_str:
        end_date = parse_iso_date(end_date_str)
    else:
        end_date = datetime.utcnow().date()

    # ------------------
    # Build bucket ranges
    # ------------------
    buckets = []

    if mode == "daily":
        for i in range(9, -1, -1):
            d = end_date - timedelta(days=i)
            buckets.append({"label": d.strftime("%Y-%m-%d"), "start": d, "end": d})

    elif mode == "weekly":
        week_end = end_date - timedelta(days=end_date.weekday()) + timedelta(days=6)
        for i in range(9, -1, -1):
            end = week_end - timedelta(weeks=i)
            start = end - timedelta(days=6)
            buckets.append({"label": end.strftime("%G-W%V"), "start": start, "end": end})

    elif mode == "monthly":
        month_end = end_date.replace(day=1)
        for i in range(9, -1, -1):
            d = month_end - timedelta(days=32 * i)
            start = d.replace(day=1)
            next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            end = next_month - timedelta(days=1)
            buckets.append({"label": start.strftime("%Y-%m"), "start": start, "end": end})

    else:
        return jsonify({"error": "Invalid mode"}), 400

    quests = list(quests_collection.find({"userId": user_id}))
    results = []

    # ------------------
    # Bucket evaluation
    # ------------------
    for B in buckets:
        prepare = active = done = 0

        for q in quests:
            created = parse_iso_date(q.get("created_at"))
            if not created or created > B["end"]:
                continue

            # ---- DONE ----
            updated = parse_iso_date(q.get("updated_at"))
            if q.get("status") == "done" and updated and updated <= B["end"]:
                done += 1
                continue

            # ---- ACTIVE ----
            is_active = False
            for log in q.get("spent_logs", []):
                log_date = parse_iso_date(log.get("spent_at"))
                if log_date and log.get("spent_minutes", 0) > 0 and B["start"] <= log_date <= B["end"]:
                    is_active = True
                    break

            if is_active:
                active += 1
            else:
                prepare += 1

        results.append({"bucket": B["label"], "prepare": prepare, "active": active, "done": done})

    return jsonify({"mode": mode, "buckets": results})

@analytics_bp.route("/daily-actual-308", methods=["GET"])
def actual_timeseries_308():
    try:
        user_id = int(request.args.get("userId"))
    except (TypeError, ValueError):
        return jsonify({"error": "Missing or invalid userId"}), 400

    today = datetime.utcnow().date()
    daily_actual = { (today - timedelta(days=i)).isoformat(): 0 for i in range(307, -1, -1) }

    quests = quests_collection.find({"userId": user_id})

    for q in quests:
        for log in q.get("spent_logs", []):
            spent_date = log.get("spent_at", "")[:10]
            spent_minutes = log.get("spent_minutes", 0)
            if spent_date in daily_actual:
                daily_actual[spent_date] += spent_minutes

    response = [{"date": d, "actual_minutes": daily_actual[d]} for d in sorted(daily_actual.keys())]
    return jsonify(response)
