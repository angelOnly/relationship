from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "relationship.db"

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

PEOPLE = {"me", "partner"}
CATEGORY_VALUES = {"talk", "let_go", "triggered"}

MY_ACTION_KEYS = [
    "no_mockery",
    "no_personal_attack",
    "no_old_score_dump",
    "no_voice_escalation",
    "pause_when_triggered",
]

PARTNER_ACTION_KEYS = [
    "reason_plus_action",
    "no_silent_avoidance",
    "no_personality_as_excuse",
    "ask_before_changing",
    "give_specific_feedback",
]


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    with closing(get_conn()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_date TEXT NOT NULL,
                month_key TEXT NOT NULL,
                person TEXT NOT NULL CHECK(person IN ('me', 'partner')),
                positive TEXT NOT NULL DEFAULT '',
                dissatisfaction TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'talk' CHECK(category IN ('talk', 'let_go', 'triggered')),
                feeling TEXT NOT NULL DEFAULT '',
                need TEXT NOT NULL DEFAULT '',
                better_wording TEXT NOT NULL DEFAULT '',
                tomorrow_request TEXT NOT NULL DEFAULT '',
                action_scores TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(entry_date, person)
            );

            CREATE TABLE IF NOT EXISTS weekly_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                month_key TEXT NOT NULL,
                week_no INTEGER NOT NULL CHECK(week_no BETWEEN 1 AND 6),
                less_harm TEXT NOT NULL DEFAULT '',
                my_progress TEXT NOT NULL DEFAULT '',
                partner_progress TEXT NOT NULL DEFAULT '',
                biggest_conflict TEXT NOT NULL DEFAULT '',
                next_focus TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(month_key, week_no)
            );

            CREATE TABLE IF NOT EXISTS monthly_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                month_key TEXT NOT NULL UNIQUE,
                relationship_change TEXT NOT NULL DEFAULT '',
                what_worked TEXT NOT NULL DEFAULT '',
                unresolved TEXT NOT NULL DEFAULT '',
                next_month_plan TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()


@app.before_request
def ensure_db() -> None:
    init_db()


@app.get("/")
def home():
    return render_template("journal.html", today=date.today().isoformat())


@app.get("/actions")
def actions_page():
    return render_template("actions.html")


@app.get("/journal")
def journal_page():
    return render_template("journal.html", today=date.today().isoformat())


@app.get("/api/entries")
def list_entries():
    month = request.args.get("month", "").strip()
    q = request.args.get("q", "").strip()
    person = request.args.get("person", "").strip()
    category = request.args.get("category", "").strip()

    clauses: list[str] = []
    params: list[Any] = []
    if month:
        clauses.append("month_key = ?")
        params.append(month)
    if person in PEOPLE:
        clauses.append("person = ?")
        params.append(person)
    if category in CATEGORY_VALUES:
        clauses.append("category = ?")
        params.append(category)
    if q:
        clauses.append(
            "(positive LIKE ? OR dissatisfaction LIKE ? OR feeling LIKE ? OR need LIKE ? OR better_wording LIKE ? OR tomorrow_request LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like] * 6)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM daily_entries {where} ORDER BY entry_date DESC, person ASC"

    with closing(get_conn()) as conn:
        rows = conn.execute(sql, params).fetchall()

    return jsonify([serialize_entry(row) for row in rows])


@app.get("/api/entries/<entry_date>/<person>")
def get_entry(entry_date: str, person: str):
    if person not in PEOPLE:
        return jsonify({"error": "invalid person"}), 400
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM daily_entries WHERE entry_date = ? AND person = ?",
            (entry_date, person),
        ).fetchone()
    if row is None:
        return jsonify(empty_entry(entry_date, person))
    return jsonify(serialize_entry(row))


@app.post("/api/entries")
def save_entry():
    data = request.get_json(silent=True) or {}
    entry_date = str(data.get("entry_date", "")).strip()
    person = str(data.get("person", "")).strip()
    category = str(data.get("category", "talk")).strip()

    try:
        datetime.strptime(entry_date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "entry_date must be YYYY-MM-DD"}), 400
    if person not in PEOPLE:
        return jsonify({"error": "person must be me or partner"}), 400
    if category not in CATEGORY_VALUES:
        category = "talk"

    action_scores = normalize_action_scores(data.get("action_scores"), person)
    now = datetime.now().isoformat(timespec="seconds")
    month_key = entry_date[:7]

    values = (
        entry_date,
        month_key,
        person,
        clean_text(data.get("positive")),
        clean_text(data.get("dissatisfaction")),
        category,
        clean_text(data.get("feeling")),
        clean_text(data.get("need")),
        clean_text(data.get("better_wording")),
        clean_text(data.get("tomorrow_request")),
        json.dumps(action_scores, ensure_ascii=False),
        now,
        now,
    )

    with closing(get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO daily_entries (
                entry_date, month_key, person, positive, dissatisfaction, category,
                feeling, need, better_wording, tomorrow_request, action_scores,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entry_date, person) DO UPDATE SET
                month_key = excluded.month_key,
                positive = excluded.positive,
                dissatisfaction = excluded.dissatisfaction,
                category = excluded.category,
                feeling = excluded.feeling,
                need = excluded.need,
                better_wording = excluded.better_wording,
                tomorrow_request = excluded.tomorrow_request,
                action_scores = excluded.action_scores,
                updated_at = excluded.updated_at
            """,
            values,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM daily_entries WHERE entry_date = ? AND person = ?",
            (entry_date, person),
        ).fetchone()

    return jsonify(serialize_entry(row)), 200


@app.delete("/api/entries/<entry_date>/<person>")
def delete_entry(entry_date: str, person: str):
    if person not in PEOPLE:
        return jsonify({"error": "invalid person"}), 400
    with closing(get_conn()) as conn:
        conn.execute(
            "DELETE FROM daily_entries WHERE entry_date = ? AND person = ?",
            (entry_date, person),
        )
        conn.commit()
    return jsonify({"ok": True})


@app.get("/api/weeks")
def list_weeks():
    month = request.args.get("month", "").strip()
    if not month:
        return jsonify([])
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM weekly_summaries WHERE month_key = ? ORDER BY week_no ASC",
            (month,),
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/weeks")
def save_week():
    data = request.get_json(silent=True) or {}
    month_key = str(data.get("month_key", "")).strip()
    week_no = int(data.get("week_no", 0) or 0)
    try:
        datetime.strptime(month_key, "%Y-%m")
    except ValueError:
        return jsonify({"error": "month_key must be YYYY-MM"}), 400
    if not 1 <= week_no <= 6:
        return jsonify({"error": "week_no must be 1-6"}), 400

    now = datetime.now().isoformat(timespec="seconds")
    values = (
        month_key,
        week_no,
        clean_text(data.get("less_harm")),
        clean_text(data.get("my_progress")),
        clean_text(data.get("partner_progress")),
        clean_text(data.get("biggest_conflict")),
        clean_text(data.get("next_focus")),
        now,
        now,
    )

    with closing(get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO weekly_summaries (
                month_key, week_no, less_harm, my_progress, partner_progress,
                biggest_conflict, next_focus, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(month_key, week_no) DO UPDATE SET
                less_harm = excluded.less_harm,
                my_progress = excluded.my_progress,
                partner_progress = excluded.partner_progress,
                biggest_conflict = excluded.biggest_conflict,
                next_focus = excluded.next_focus,
                updated_at = excluded.updated_at
            """,
            values,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM weekly_summaries WHERE month_key = ? AND week_no = ?",
            (month_key, week_no),
        ).fetchone()
    return jsonify(dict(row))


@app.get("/api/monthly-summary")
def get_monthly_summary():
    month = request.args.get("month", "").strip()
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM monthly_summaries WHERE month_key = ?",
            (month,),
        ).fetchone()
    if row is None:
        return jsonify(
            {
                "month_key": month,
                "relationship_change": "",
                "what_worked": "",
                "unresolved": "",
                "next_month_plan": "",
            }
        )
    return jsonify(dict(row))


@app.post("/api/monthly-summary")
def save_monthly_summary():
    data = request.get_json(silent=True) or {}
    month_key = str(data.get("month_key", "")).strip()
    try:
        datetime.strptime(month_key, "%Y-%m")
    except ValueError:
        return jsonify({"error": "month_key must be YYYY-MM"}), 400
    now = datetime.now().isoformat(timespec="seconds")
    values = (
        month_key,
        clean_text(data.get("relationship_change")),
        clean_text(data.get("what_worked")),
        clean_text(data.get("unresolved")),
        clean_text(data.get("next_month_plan")),
        now,
        now,
    )
    with closing(get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO monthly_summaries (
                month_key, relationship_change, what_worked, unresolved,
                next_month_plan, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(month_key) DO UPDATE SET
                relationship_change = excluded.relationship_change,
                what_worked = excluded.what_worked,
                unresolved = excluded.unresolved,
                next_month_plan = excluded.next_month_plan,
                updated_at = excluded.updated_at
            """,
            values,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM monthly_summaries WHERE month_key = ?",
            (month_key,),
        ).fetchone()
    return jsonify(dict(row))


@app.get("/api/months")
def list_months():
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT month_key, MAX(updated_at) AS last_updated, COUNT(*) AS entry_count
            FROM daily_entries
            GROUP BY month_key
            ORDER BY month_key DESC
            """
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/api/export.csv")
def export_csv():
    month = request.args.get("month", "").strip()
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM daily_entries WHERE month_key = ? ORDER BY entry_date, person",
            (month,),
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "日期",
            "记录人",
            "对方做得好的事",
            "不满的事",
            "处理分类",
            "真实感受",
            "真正需求",
            "更好的表达",
            "明日请求",
            "行动评分",
            "更新时间",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["entry_date"],
                "我" if row["person"] == "me" else "他",
                row["positive"],
                row["dissatisfaction"],
                row["category"],
                row["feeling"],
                row["need"],
                row["better_wording"],
                row["tomorrow_request"],
                row["action_scores"],
                row["updated_at"],
            ]
        )

    filename = f"关系复盘-{month or '全部'}.csv"
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/backup.json")
def backup_json():
    with closing(get_conn()) as conn:
        entries = [serialize_entry(row) for row in conn.execute("SELECT * FROM daily_entries ORDER BY entry_date, person")]
        weeks = [dict(row) for row in conn.execute("SELECT * FROM weekly_summaries ORDER BY month_key, week_no")]
        months = [dict(row) for row in conn.execute("SELECT * FROM monthly_summaries ORDER BY month_key")]
    payload = {
        "version": 1,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "daily_entries": entries,
        "weekly_summaries": weeks,
        "monthly_summaries": months,
    }
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="关系复盘备份.json"'},
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok", "database": str(DB_PATH)})


def serialize_entry(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    try:
        item["action_scores"] = json.loads(item.get("action_scores") or "{}")
    except json.JSONDecodeError:
        item["action_scores"] = {}
    return item


def empty_entry(entry_date: str, person: str) -> dict[str, Any]:
    keys = MY_ACTION_KEYS if person == "me" else PARTNER_ACTION_KEYS
    return {
        "entry_date": entry_date,
        "month_key": entry_date[:7],
        "person": person,
        "positive": "",
        "dissatisfaction": "",
        "category": "talk",
        "feeling": "",
        "need": "",
        "better_wording": "",
        "tomorrow_request": "",
        "action_scores": {key: 3 for key in keys},
    }


def normalize_action_scores(raw: Any, person: str) -> dict[str, int]:
    keys = MY_ACTION_KEYS if person == "me" else PARTNER_ACTION_KEYS
    raw = raw if isinstance(raw, dict) else {}
    result: dict[str, int] = {}
    for key in keys:
        try:
            score = int(raw.get(key, 3))
        except (TypeError, ValueError):
            score = 3
        result[key] = max(0, min(3, score))
    return result


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
