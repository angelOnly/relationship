from __future__ import annotations

import csv
import calendar
import io
import json
import os
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request

from relationship_ai import (
    AIConfigError,
    AIServiceError,
    analyze_relationship,
    review_journal_period,
)

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

            CREATE TABLE IF NOT EXISTS analysis_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                turn_id TEXT NOT NULL UNIQUE,
                occurred_at TEXT NOT NULL DEFAULT '',
                scene_type TEXT NOT NULL DEFAULT '其他',
                roles TEXT NOT NULL DEFAULT '',
                observed_facts TEXT NOT NULL DEFAULT '',
                question_summary TEXT NOT NULL,
                keywords TEXT NOT NULL DEFAULT '[]',
                inner_expectation_me TEXT NOT NULL DEFAULT '',
                inner_expectation_partner TEXT NOT NULL DEFAULT '',
                talent_state_me TEXT NOT NULL DEFAULT '',
                talent_state_partner TEXT NOT NULL DEFAULT '',
                interaction_loop TEXT NOT NULL DEFAULT '',
                communication_guidance TEXT NOT NULL DEFAULT '',
                recommended_wording TEXT NOT NULL DEFAULT '',
                behavior_feedback TEXT NOT NULL DEFAULT '',
                behavior_score INTEGER CHECK(behavior_score IS NULL OR behavior_score BETWEEN 1 AND 10),
                behavior_dimensions TEXT NOT NULL DEFAULT '{}',
                score_reason TEXT NOT NULL DEFAULT '',
                progress_assessment TEXT NOT NULL DEFAULT '',
                next_action TEXT NOT NULL DEFAULT '',
                uncertainty TEXT NOT NULL DEFAULT '',
                confidence TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_analysis_created_at
                ON analysis_records(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_analysis_scene
                ON analysis_records(scene_type);
            CREATE INDEX IF NOT EXISTS idx_analysis_score
                ON analysis_records(behavior_score);

            CREATE TABLE IF NOT EXISTS ai_period_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period_type TEXT NOT NULL CHECK(period_type IN ('daily', 'weekly', 'monthly')),
                period_key TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                score_me INTEGER CHECK(score_me IS NULL OR score_me BETWEEN 1 AND 10),
                score_partner INTEGER CHECK(score_partner IS NULL OR score_partner BETWEEN 1 AND 10),
                relationship_score INTEGER CHECK(relationship_score IS NULL OR relationship_score BETWEEN 1 AND 10),
                feedback_me TEXT NOT NULL DEFAULT '',
                feedback_partner TEXT NOT NULL DEFAULT '',
                what_improved TEXT NOT NULL DEFAULT '',
                risk_pattern TEXT NOT NULL DEFAULT '',
                adjustment_goal TEXT NOT NULL DEFAULT '',
                actions TEXT NOT NULL DEFAULT '[]',
                conversation_example TEXT NOT NULL DEFAULT '',
                confidence TEXT NOT NULL DEFAULT '',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(period_type, period_key)
            );

            CREATE INDEX IF NOT EXISTS idx_ai_period_reviews_updated
                ON ai_period_reviews(updated_at DESC);
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


@app.get("/chat")
def chat_page():
    return render_template("chat.html")


@app.post("/api/chat")
def chat_with_coach():
    data = request.get_json(silent=True) or {}
    message = clean_text(data.get("message"))
    if not message:
        return jsonify({"error": "请先写下这次发生了什么。"}), 400
    if len(message) > 5000:
        return jsonify({"error": "单条消息请控制在 5000 字以内。"}), 400

    conversation_id = normalize_identifier(data.get("conversation_id")) or uuid.uuid4().hex
    turn_id = normalize_identifier(data.get("turn_id")) or uuid.uuid4().hex
    history = normalize_chat_history(data.get("history"))
    memories = find_similar_analyses(message, limit=5)

    try:
        result = analyze_relationship(message, history, memories)
    except AIConfigError as exc:
        return jsonify({"error": str(exc)}), 503
    except AIServiceError as exc:
        return jsonify({"error": str(exc)}), 502

    saved = None
    if result.get("status") == "complete" and isinstance(result.get("record"), dict):
        record = normalize_analysis_record(result["record"])
        if record["question_summary"]:
            saved = save_analysis_record(record, conversation_id, turn_id)

    return jsonify(
        {
            "conversation_id": conversation_id,
            "status": result.get("status", "clarifying"),
            "reply": result.get("reply", ""),
            "analysis_saved": bool(saved),
            "record": saved,
            "memory_count": len(memories),
        }
    )


@app.get("/api/analysis-records")
def list_analysis_records():
    q = clean_text(request.args.get("q"))[:200]
    scene = clean_text(request.args.get("scene"))[:30]
    try:
        limit = max(1, min(int(request.args.get("limit", 30)), 100))
    except ValueError:
        limit = 30

    clauses: list[str] = []
    params: list[Any] = []
    if q:
        like = f"%{q}%"
        searchable = [
            "question_summary",
            "keywords",
            "inner_expectation_me",
            "inner_expectation_partner",
            "talent_state_me",
            "talent_state_partner",
            "communication_guidance",
            "recommended_wording",
            "behavior_feedback",
            "progress_assessment",
        ]
        clauses.append("(" + " OR ".join(f"{column} LIKE ?" for column in searchable) + ")")
        params.extend([like] * len(searchable))
    if scene:
        clauses.append("scene_type = ?")
        params.append(scene)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    with closing(get_conn()) as conn:
        rows = conn.execute(
            f"SELECT * FROM analysis_records {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return jsonify([serialize_analysis_record(row) for row in rows])


@app.delete("/api/analysis-records/<int:record_id>")
def delete_analysis_record(record_id: int):
    with closing(get_conn()) as conn:
        cursor = conn.execute("DELETE FROM analysis_records WHERE id = ?", (record_id,))
        conn.commit()
    if cursor.rowcount == 0:
        return jsonify({"error": "记录不存在。"}), 404
    return jsonify({"ok": True})


@app.get("/api/progress")
def get_progress():
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, scene_type, question_summary, behavior_score,
                   progress_assessment
            FROM analysis_records
            WHERE behavior_score IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 20
            """
        ).fetchall()
    items = [dict(row) for row in rows]
    recent_scores = [item["behavior_score"] for item in items[:5]]
    previous_scores = [item["behavior_score"] for item in items[5:10]]
    recent_average = round(sum(recent_scores) / len(recent_scores), 1) if recent_scores else None
    previous_average = round(sum(previous_scores) / len(previous_scores), 1) if previous_scores else None
    delta = (
        round(recent_average - previous_average, 1)
        if recent_average is not None and previous_average is not None
        else None
    )
    if delta is None:
        trend = "暂无足够基线"
    elif delta >= 0.5:
        trend = "近期有进步"
    elif delta <= -0.5:
        trend = "近期有反复"
    else:
        trend = "近期基本持平"
    return jsonify(
        {
            "trend": trend,
            "recent_average": recent_average,
            "previous_average": previous_average,
            "delta": delta,
            "scored_count": len(items),
            "items": list(reversed(items)),
        }
    )


@app.get("/api/ai-reviews")
def get_ai_period_review():
    period_type = clean_text(request.args.get("period_type"))
    period_key = clean_text(request.args.get("period_key"))
    if period_type not in {"daily", "weekly", "monthly"} or not valid_period_key(period_type, period_key):
        return jsonify({"error": "复盘周期参数无效。"}), 400
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM ai_period_reviews WHERE period_type = ? AND period_key = ?",
            (period_type, period_key),
        ).fetchone()
    return jsonify(serialize_ai_period_review(row) if row else {})


@app.post("/api/ai-reviews")
def generate_ai_period_review():
    data = request.get_json(silent=True) or {}
    period_type = clean_text(data.get("period_type"))
    period_key = clean_text(data.get("period_key"))
    if period_type not in {"daily", "weekly", "monthly"} or not valid_period_key(period_type, period_key):
        return jsonify({"error": "复盘周期参数无效。"}), 400

    source = build_period_source(period_type, period_key)
    if not source.get("has_content"):
        return jsonify({"error": "这个周期还没有可复盘的记录，请先保存双方记录或小结。"}), 400
    search_text = clean_text(source.pop("search_text", ""))
    memories = find_similar_analyses(search_text, limit=5) if search_text else []
    label_map = {"daily": "每日", "weekly": "每周", "monthly": "每月"}
    try:
        result = review_journal_period(
            period_type,
            f"{label_map[period_type]} {period_key}",
            source,
            memories,
        )
    except AIConfigError as exc:
        return jsonify({"error": str(exc)}), 503
    except AIServiceError as exc:
        return jsonify({"error": str(exc)}), 502

    review = normalize_ai_period_review(result)
    saved = save_ai_period_review(period_type, period_key, review)
    return jsonify(saved)


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
        analyses = [
            serialize_analysis_record(row)
            for row in conn.execute("SELECT * FROM analysis_records ORDER BY created_at")
        ]
        ai_reviews = [
            serialize_ai_period_review(row)
            for row in conn.execute("SELECT * FROM ai_period_reviews ORDER BY period_type, period_key")
        ]
    payload = {
        "version": 2,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "daily_entries": entries,
        "weekly_summaries": weeks,
        "monthly_summaries": months,
        "analysis_records": analyses,
        "ai_period_reviews": ai_reviews,
    }
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="关系复盘备份.json"'},
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok", "database": str(DB_PATH)})


AI_REVIEW_STRING_FIELDS = (
    "summary",
    "feedback_me",
    "feedback_partner",
    "what_improved",
    "risk_pattern",
    "adjustment_goal",
    "conversation_example",
    "confidence",
)


def valid_period_key(period_type: str, period_key: str) -> bool:
    try:
        if period_type == "daily":
            datetime.strptime(period_key, "%Y-%m-%d")
            return True
        if period_type == "monthly":
            datetime.strptime(period_key, "%Y-%m")
            return True
        if period_type == "weekly":
            match = re.fullmatch(r"(\d{4}-\d{2})-W([1-6])", period_key)
            if not match:
                return False
            datetime.strptime(match.group(1), "%Y-%m")
            return True
    except ValueError:
        return False
    return False


def build_period_source(period_type: str, period_key: str) -> dict[str, Any]:
    source: dict[str, Any] = {"period_type": period_type, "period_key": period_key}
    with closing(get_conn()) as conn:
        if period_type == "daily":
            entries = conn.execute(
                "SELECT * FROM daily_entries WHERE entry_date = ? ORDER BY person",
                (period_key,),
            ).fetchall()
            source["daily_entries"] = [entry_for_ai_review(row) for row in entries]
        elif period_type == "weekly":
            match = re.fullmatch(r"(\d{4})-(\d{2})-W([1-6])", period_key)
            assert match is not None
            year, month, week_no = map(int, match.groups())
            days_in_month = calendar.monthrange(year, month)[1]
            start_day = (week_no - 1) * 7 + 1
            if start_day <= days_in_month:
                start_date = date(year, month, start_day)
                end_date = date(year, month, min(start_day + 6, days_in_month))
                entries = conn.execute(
                    "SELECT * FROM daily_entries WHERE entry_date BETWEEN ? AND ? ORDER BY entry_date, person",
                    (start_date.isoformat(), end_date.isoformat()),
                ).fetchall()
            else:
                start_date = date(year, month, days_in_month)
                end_date = start_date
                entries = []
            summary = conn.execute(
                "SELECT * FROM weekly_summaries WHERE month_key = ? AND week_no = ?",
                (f"{year:04d}-{month:02d}", week_no),
            ).fetchone()
            source.update(
                {
                    "date_range": [start_date.isoformat(), end_date.isoformat()],
                    "daily_entries": [entry_for_ai_review(row) for row in entries],
                    "weekly_summary": compact_row(summary, 900) if summary else None,
                }
            )
        else:
            entries = conn.execute(
                "SELECT * FROM daily_entries WHERE month_key = ? ORDER BY entry_date, person",
                (period_key,),
            ).fetchall()
            weeks = conn.execute(
                "SELECT * FROM weekly_summaries WHERE month_key = ? ORDER BY week_no",
                (period_key,),
            ).fetchall()
            month = conn.execute(
                "SELECT * FROM monthly_summaries WHERE month_key = ?",
                (period_key,),
            ).fetchone()
            analyses = conn.execute(
                """
                SELECT created_at, occurred_at, scene_type, question_summary,
                       behavior_score, progress_assessment, next_action
                FROM analysis_records
                WHERE occurred_at LIKE ? OR (occurred_at = '' AND created_at LIKE ?)
                ORDER BY created_at DESC
                LIMIT 30
                """,
                (f"{period_key}%", f"{period_key}%"),
            ).fetchall()
            source.update(
                {
                    "daily_entries": [entry_for_ai_review(row) for row in entries],
                    "weekly_summaries": [compact_row(row, 700) for row in weeks],
                    "monthly_summary": compact_row(month, 1200) if month else None,
                    "completed_scene_analyses": [compact_row(row, 700) for row in analyses],
                }
            )

    content_text = review_source_text(source)
    source["has_content"] = bool(content_text.strip())
    source["search_text"] = content_text[:10000]
    return source


def entry_for_ai_review(row: sqlite3.Row) -> dict[str, Any]:
    fields = (
        "entry_date",
        "person",
        "positive",
        "dissatisfaction",
        "category",
        "feeling",
        "need",
        "better_wording",
        "tomorrow_request",
    )
    return {
        field: clean_text(row[field])[:400] if field not in {"entry_date", "person", "category"} else row[field]
        for field in fields
    }


def compact_row(row: sqlite3.Row, max_length: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in row.keys():
        if key in {"id", "created_at", "updated_at", "action_scores"}:
            continue
        value = row[key]
        result[key] = clean_text(value)[:max_length] if isinstance(value, str) else value
    return result


def review_source_text(source: dict[str, Any]) -> str:
    meaningful_keys = {
        "positive",
        "dissatisfaction",
        "feeling",
        "need",
        "better_wording",
        "tomorrow_request",
        "less_harm",
        "my_progress",
        "partner_progress",
        "biggest_conflict",
        "next_focus",
        "relationship_change",
        "what_worked",
        "unresolved",
        "next_month_plan",
        "question_summary",
        "progress_assessment",
        "next_action",
    }
    texts: list[str] = []

    def collect(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                collect(child_value, child_key)
        elif isinstance(value, list):
            for child in value:
                collect(child, key)
        elif key in meaningful_keys and value:
            texts.append(clean_text(value))

    collect(source)
    return "\n".join(texts)


def normalize_ai_period_review(raw: dict[str, Any]) -> dict[str, Any]:
    review = {field: clean_text(raw.get(field))[:4000] for field in AI_REVIEW_STRING_FIELDS}
    for field in ("score_me", "score_partner", "relationship_score"):
        try:
            score = int(raw.get(field)) if raw.get(field) is not None else None
        except (TypeError, ValueError):
            score = None
        review[field] = score if score is not None and 1 <= score <= 10 else None
    raw_actions = raw.get("actions") if isinstance(raw.get("actions"), list) else []
    review["actions"] = [clean_text(item)[:700] for item in raw_actions if clean_text(item)][:3]
    return review


def save_ai_period_review(
    period_type: str,
    period_key: str,
    review: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    values = (
        period_type,
        period_key,
        review["summary"],
        review["score_me"],
        review["score_partner"],
        review["relationship_score"],
        review["feedback_me"],
        review["feedback_partner"],
        review["what_improved"],
        review["risk_pattern"],
        review["adjustment_goal"],
        json.dumps(review["actions"], ensure_ascii=False),
        review["conversation_example"],
        review["confidence"],
        now,
        now,
    )
    with closing(get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO ai_period_reviews (
                period_type, period_key, summary, score_me, score_partner,
                relationship_score, feedback_me, feedback_partner, what_improved,
                risk_pattern, adjustment_goal, actions, conversation_example,
                confidence, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(period_type, period_key) DO UPDATE SET
                summary = excluded.summary,
                score_me = excluded.score_me,
                score_partner = excluded.score_partner,
                relationship_score = excluded.relationship_score,
                feedback_me = excluded.feedback_me,
                feedback_partner = excluded.feedback_partner,
                what_improved = excluded.what_improved,
                risk_pattern = excluded.risk_pattern,
                adjustment_goal = excluded.adjustment_goal,
                actions = excluded.actions,
                conversation_example = excluded.conversation_example,
                confidence = excluded.confidence,
                revision = ai_period_reviews.revision + 1,
                updated_at = excluded.updated_at
            """,
            values,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM ai_period_reviews WHERE period_type = ? AND period_key = ?",
            (period_type, period_key),
        ).fetchone()
    return serialize_ai_period_review(row)


def serialize_ai_period_review(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    try:
        item["actions"] = json.loads(item.get("actions") or "[]")
    except json.JSONDecodeError:
        item["actions"] = []
    return item


ANALYSIS_STRING_FIELDS = (
    "occurred_at",
    "scene_type",
    "roles",
    "observed_facts",
    "question_summary",
    "inner_expectation_me",
    "inner_expectation_partner",
    "talent_state_me",
    "talent_state_partner",
    "interaction_loop",
    "communication_guidance",
    "recommended_wording",
    "behavior_feedback",
    "score_reason",
    "progress_assessment",
    "next_action",
    "uncertainty",
    "confidence",
)


def normalize_identifier(value: Any) -> str:
    text = clean_text(value)
    return text if re.fullmatch(r"[A-Za-z0-9_-]{8,80}", text) else ""


def normalize_chat_history(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    total = 0
    for item in raw[-12:]:
        if not isinstance(item, dict):
            continue
        role = clean_text(item.get("role"))
        content = clean_text(item.get("content"))[:5000]
        if role not in {"user", "assistant"} or not content:
            continue
        if total + len(content) > 24000:
            break
        result.append({"role": role, "content": content})
        total += len(content)
    return result


def normalize_analysis_record(raw: dict[str, Any]) -> dict[str, Any]:
    record = {field: clean_text(raw.get(field))[:3000] for field in ANALYSIS_STRING_FIELDS}
    record["scene_type"] = record["scene_type"] or "其他"

    raw_keywords = raw.get("keywords")
    if not isinstance(raw_keywords, list):
        raw_keywords = re.split(r"[,，、;；\s]+", clean_text(raw_keywords))
    keywords: list[str] = []
    for keyword in raw_keywords:
        keyword = clean_text(keyword)[:30]
        if keyword and keyword not in keywords:
            keywords.append(keyword)
        if len(keywords) >= 8:
            break
    record["keywords"] = keywords

    try:
        score = int(raw.get("behavior_score")) if raw.get("behavior_score") is not None else None
    except (TypeError, ValueError):
        score = None
    record["behavior_score"] = score if score is not None and 1 <= score <= 10 else None

    dimensions = raw.get("behavior_dimensions")
    record["behavior_dimensions"] = dimensions if isinstance(dimensions, dict) else {}
    return record


def save_analysis_record(
    record: dict[str, Any],
    conversation_id: str,
    turn_id: str,
) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    values = (
        conversation_id,
        turn_id,
        *(record[field] for field in ANALYSIS_STRING_FIELDS[:6]),
        json.dumps(record["keywords"], ensure_ascii=False),
        *(record[field] for field in ANALYSIS_STRING_FIELDS[6:13]),
        record["behavior_score"],
        json.dumps(record["behavior_dimensions"], ensure_ascii=False),
        *(record[field] for field in ANALYSIS_STRING_FIELDS[13:]),
        now,
        now,
    )
    with closing(get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO analysis_records (
                conversation_id, turn_id, occurred_at, scene_type, roles,
                observed_facts, question_summary, inner_expectation_me, keywords,
                inner_expectation_partner, talent_state_me, talent_state_partner,
                interaction_loop, communication_guidance, recommended_wording,
                behavior_feedback, behavior_score, behavior_dimensions, score_reason,
                progress_assessment, next_action, uncertainty, confidence,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(turn_id) DO UPDATE SET
                occurred_at = excluded.occurred_at,
                scene_type = excluded.scene_type,
                roles = excluded.roles,
                observed_facts = excluded.observed_facts,
                question_summary = excluded.question_summary,
                keywords = excluded.keywords,
                inner_expectation_me = excluded.inner_expectation_me,
                inner_expectation_partner = excluded.inner_expectation_partner,
                talent_state_me = excluded.talent_state_me,
                talent_state_partner = excluded.talent_state_partner,
                interaction_loop = excluded.interaction_loop,
                communication_guidance = excluded.communication_guidance,
                recommended_wording = excluded.recommended_wording,
                behavior_feedback = excluded.behavior_feedback,
                behavior_score = excluded.behavior_score,
                behavior_dimensions = excluded.behavior_dimensions,
                score_reason = excluded.score_reason,
                progress_assessment = excluded.progress_assessment,
                next_action = excluded.next_action,
                uncertainty = excluded.uncertainty,
                confidence = excluded.confidence,
                updated_at = excluded.updated_at
            """,
            values,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM analysis_records WHERE turn_id = ?", (turn_id,)).fetchone()
    return serialize_analysis_record(row)


def serialize_analysis_record(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    for field, default in (("keywords", []), ("behavior_dimensions", {})):
        try:
            item[field] = json.loads(item.get(field) or json.dumps(default))
        except json.JSONDecodeError:
            item[field] = default
    return item


def find_similar_analyses(query: str, limit: int = 5) -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM analysis_records ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    if not rows:
        return []

    query_text = re.sub(r"\s+", "", query.lower())
    query_terms = [
        term for term in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", query.lower())
        if len(term) >= 2
    ]
    query_grams = chinese_bigrams(query_text)
    ranked: list[tuple[float, int, sqlite3.Row]] = []
    for recency, row in enumerate(rows):
        searchable = " ".join(
            str(row[field] or "")
            for field in (
                "scene_type", "question_summary", "keywords", "inner_expectation_me",
                "inner_expectation_partner", "talent_state_me", "talent_state_partner",
                "interaction_loop", "communication_guidance", "behavior_feedback",
            )
        ).lower()
        compact = re.sub(r"\s+", "", searchable)
        score = sum(min(len(term), 12) * 2 for term in query_terms if term in searchable)
        if query_text and query_text in compact:
            score += 100
        record_grams = chinese_bigrams(compact)
        if query_grams and record_grams:
            overlap = len(query_grams & record_grams)
            score += 30 * (2 * overlap / (len(query_grams) + len(record_grams)))
        ranked.append((score, -recency, row))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = [item[2] for item in ranked if item[0] > 0][:limit]
    if not selected:
        selected = [item[2] for item in ranked[: min(3, limit)]]

    result: list[dict[str, Any]] = []
    for row in selected:
        item = serialize_analysis_record(row)
        result.append(
            {
                key: item.get(key)
                for key in (
                    "created_at", "scene_type", "question_summary", "keywords",
                    "inner_expectation_me", "inner_expectation_partner",
                    "talent_state_me", "talent_state_partner", "behavior_score",
                    "score_reason", "progress_assessment", "next_action",
                )
            }
        )
    return result


def chinese_bigrams(value: str) -> set[str]:
    chars = "".join(re.findall(r"[0-9a-z\u4e00-\u9fff]", value.lower()))
    return {chars[index : index + 2] for index in range(max(0, len(chars) - 1))}


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
