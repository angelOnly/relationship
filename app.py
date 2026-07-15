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
from urllib.parse import quote

from flask import Flask, Response, jsonify, render_template, request

from journal_store import (
    RECORD_SCHEMAS,
    create_action_item,
    get_record,
    get_record_schema,
    init_flexible_schema,
    list_action_items,
    list_record_revisions,
    list_records,
    serialize_record,
    soft_delete_record,
    update_action_item,
    upsert_ai_goal,
    upsert_record,
)
from relationship_ai import (
    AIConfigError,
    AIModelError,
    AIServiceError,
    analyze_relationship,
    get_model_catalog,
    resolve_model_name,
    review_journal_period,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "relationship.db"
APP_VERSION = os.getenv("APP_VERSION", "3.0.0")

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.jinja_env.globals["app_version"] = APP_VERSION

PEOPLE = {"me", "partner"}


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
                model_name TEXT NOT NULL DEFAULT '',
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
                model_name TEXT NOT NULL DEFAULT '',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(period_type, period_key)
            );

            CREATE INDEX IF NOT EXISTS idx_ai_period_reviews_updated
                ON ai_period_reviews(updated_at DESC);
            """
        )
        _ensure_column(conn, "analysis_records", "model_name", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "ai_period_reviews", "model_name", "TEXT NOT NULL DEFAULT ''")
        init_flexible_schema(conn)
        conn.commit()


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


@app.before_request
def ensure_db() -> None:
    init_db()


@app.after_request
def add_runtime_headers(response: Response) -> Response:
    response.headers["X-Relationship-Journal-Version"] = APP_VERSION
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


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


@app.get("/api/models")
def list_ai_models():
    return jsonify(get_model_catalog())


@app.get("/api/record-schemas/<record_type>")
def get_active_record_schema(record_type: str):
    with closing(get_conn()) as conn:
        schema = get_record_schema(conn, record_type)
    if schema is None:
        return jsonify({"error": "记录类型不存在。"}), 404
    return jsonify(schema)


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
        model_name = resolve_model_name(clean_text(data.get("model")) or None)
        result = analyze_relationship(
            message,
            history,
            memories,
            model_name=model_name,
        )
    except AIModelError as exc:
        return jsonify({"error": str(exc)}), 400
    except AIConfigError as exc:
        return jsonify({"error": str(exc)}), 503
    except AIServiceError as exc:
        return jsonify({"error": str(exc)}), 502

    saved = None
    if result.get("status") == "complete" and isinstance(result.get("record"), dict):
        record = normalize_analysis_record(result["record"])
        if record["question_summary"]:
            saved = save_analysis_record(
                record,
                conversation_id,
                turn_id,
                model_name,
            )

    return jsonify(
        {
            "conversation_id": conversation_id,
            "status": result.get("status", "clarifying"),
            "reply": result.get("reply", ""),
            "analysis_saved": bool(saved),
            "record": saved,
            "memory_count": len(memories),
            "model_name": model_name,
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
        model_name = resolve_model_name(clean_text(data.get("model")) or None)
        result = review_journal_period(
            period_type,
            f"{label_map[period_type]} {period_key}",
            source,
            memories,
            model_name=model_name,
        )
    except AIModelError as exc:
        return jsonify({"error": str(exc)}), 400
    except AIConfigError as exc:
        return jsonify({"error": str(exc)}), 503
    except AIServiceError as exc:
        return jsonify({"error": str(exc)}), 502

    review = normalize_ai_period_review(result)
    saved = save_ai_period_review(period_type, period_key, review, model_name)
    return jsonify(saved)


@app.get("/api/entries")
def list_entries():
    month = clean_text(request.args.get("month"))[:7]
    q = clean_text(request.args.get("q"))[:200]
    person = clean_text(request.args.get("person"))
    follow_up = clean_text(request.args.get("follow_up") or request.args.get("category"))
    with closing(get_conn()) as conn:
        records = list_records(
            conn,
            "daily",
            period_prefix=month,
            author=person if person in PEOPLE else "",
            query=q,
        )
    entries = [daily_record_to_api(record) for record in records]
    if follow_up:
        entries = [entry for entry in entries if entry["follow_up"] == follow_up]
    return jsonify(entries)


@app.get("/api/entries/<entry_date>/<person>")
def get_entry(entry_date: str, person: str):
    if person not in PEOPLE:
        return jsonify({"error": "invalid person"}), 400
    with closing(get_conn()) as conn:
        record = get_record(conn, "daily", entry_date, person)
    return jsonify(daily_record_to_api(record) if record else empty_entry(entry_date, person))


@app.post("/api/entries")
def save_entry():
    data = request.get_json(silent=True) or {}
    entry_date = clean_text(data.get("entry_date"))
    person = clean_text(data.get("person"))

    try:
        datetime.strptime(entry_date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "entry_date must be YYYY-MM-DD"}), 400
    if person not in PEOPLE:
        return jsonify({"error": "person must be me or partner"}), 400
    content = normalize_daily_content(data)
    with closing(get_conn()) as conn:
        record = upsert_record(
            conn,
            record_type="daily",
            period_key=entry_date,
            author=person,
            data=content,
            metadata={"source": "web", "format": "universal"},
        )
        conn.commit()
    return jsonify(daily_record_to_api(record)), 200


@app.delete("/api/entries/<entry_date>/<person>")
def delete_entry(entry_date: str, person: str):
    if person not in PEOPLE:
        return jsonify({"error": "invalid person"}), 400
    with closing(get_conn()) as conn:
        deleted = soft_delete_record(conn, "daily", entry_date, person)
        conn.commit()
    return jsonify({"ok": True, "deleted": deleted})


@app.get("/api/weeks")
def list_weeks():
    month = clean_text(request.args.get("month"))
    if not month:
        return jsonify([])
    with closing(get_conn()) as conn:
        records = list_records(conn, "weekly", period_prefix=f"{month}-W")
    weeks = [weekly_record_to_api(record) for record in records]
    weeks.sort(key=lambda item: item["week_no"])
    return jsonify(weeks)


@app.post("/api/weeks")
def save_week():
    data = request.get_json(silent=True) or {}
    month_key = clean_text(data.get("month_key"))
    try:
        week_no = int(data.get("week_no", 0) or 0)
    except (TypeError, ValueError):
        week_no = 0
    try:
        datetime.strptime(month_key, "%Y-%m")
    except ValueError:
        return jsonify({"error": "month_key must be YYYY-MM"}), 400
    if not 1 <= week_no <= 6:
        return jsonify({"error": "week_no must be 1-6"}), 400
    content = normalize_weekly_content(data)
    with closing(get_conn()) as conn:
        record = upsert_record(
            conn,
            record_type="weekly",
            period_key=f"{month_key}-W{week_no}",
            author="joint",
            data=content,
            metadata={"source": "web", "format": "universal"},
        )
        conn.commit()
    return jsonify(weekly_record_to_api(record))


@app.get("/api/monthly-summary")
def get_monthly_summary():
    month = clean_text(request.args.get("month"))
    with closing(get_conn()) as conn:
        record = get_record(conn, "monthly", month, "joint")
    return jsonify(monthly_record_to_api(record) if record else empty_monthly_record(month))


@app.post("/api/monthly-summary")
def save_monthly_summary():
    data = request.get_json(silent=True) or {}
    month_key = clean_text(data.get("month_key"))
    try:
        datetime.strptime(month_key, "%Y-%m")
    except ValueError:
        return jsonify({"error": "month_key must be YYYY-MM"}), 400
    content = normalize_monthly_content(data)
    with closing(get_conn()) as conn:
        record = upsert_record(
            conn,
            record_type="monthly",
            period_key=month_key,
            author="joint",
            data=content,
            metadata={"source": "web", "format": "universal"},
        )
        conn.commit()
    return jsonify(monthly_record_to_api(record))


@app.get("/api/months")
def list_months():
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT substr(period_key, 1, 7) AS month_key,
                   MAX(updated_at) AS last_updated,
                   COUNT(*) AS entry_count
            FROM record_documents
            WHERE record_type = 'daily' AND deleted_at = ''
            GROUP BY substr(period_key, 1, 7)
            ORDER BY month_key DESC
            """
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/api/action-items")
def get_action_items():
    statuses = [part for part in clean_text(request.args.get("status")).split(",") if part]
    with closing(get_conn()) as conn:
        items = list_action_items(conn, statuses=statuses or None)
    return jsonify(items)


@app.post("/api/action-items")
def add_action_item():
    data = request.get_json(silent=True) or {}
    title = clean_text(data.get("title"))[:300]
    if not title:
        return jsonify({"error": "请写下一个具体行动目标。"}), 400
    owner = clean_text(data.get("owner")) or "both"
    kind = clean_text(data.get("kind")) or "goal"
    if owner not in {"me", "partner", "both"}:
        return jsonify({"error": "行动负责人无效。"}), 400
    if kind not in {"boundary", "practice", "goal"}:
        return jsonify({"error": "行动类型无效。"}), 400
    with closing(get_conn()) as conn:
        item = create_action_item(
            conn,
            {
                "owner": owner,
                "kind": kind,
                "title": title,
                "detail": clean_text(data.get("detail"))[:1200],
                "status": "active",
                "source": "manual",
                "start_date": clean_text(data.get("start_date"))[:10],
                "due_date": clean_text(data.get("due_date"))[:10],
            },
        )
        conn.commit()
    return jsonify(item), 201


@app.patch("/api/action-items/<int:action_id>")
def patch_action_item(action_id: int):
    data = request.get_json(silent=True) or {}
    changes: dict[str, Any] = {}
    if "status" in data:
        status = clean_text(data.get("status"))
        if status not in {"suggested", "active", "paused", "completed", "archived"}:
            return jsonify({"error": "行动状态无效。"}), 400
        changes["status"] = status
    if "title" in data:
        title = clean_text(data.get("title"))[:300]
        if not title:
            return jsonify({"error": "行动标题不能为空。"}), 400
        changes["title"] = title
    if "detail" in data:
        changes["detail"] = clean_text(data.get("detail"))[:1200]
    with closing(get_conn()) as conn:
        item = update_action_item(conn, action_id, changes)
        conn.commit()
    if item is None:
        return jsonify({"error": "行动项不存在。"}), 404
    return jsonify(item)


@app.get("/api/export.csv")
def export_csv():
    month = clean_text(request.args.get("month"))
    with closing(get_conn()) as conn:
        records = list_records(conn, "daily", period_prefix=month)
    entries = [daily_record_to_api(record) for record in reversed(records)]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "日期",
            "记录人",
            "值得肯定的事",
            "关键事件",
            "感受",
            "需要",
            "双方回应",
            "修复或具体请求",
            "跟进状态",
            "记录格式",
            "修订版本",
            "更新时间",
        ]
    )
    for entry in entries:
        writer.writerow(
            [
                entry["entry_date"],
                "我" if entry["person"] == "me" else "他",
                entry["appreciation"],
                entry["event"],
                entry["feeling"],
                entry["need"],
                entry["response"],
                entry["repair_request"],
                entry["follow_up"],
                f"{entry['schema_key']}@{entry['schema_version']}",
                entry["revision"],
                entry["updated_at"],
            ]
        )

    filename = f"关系复盘-{month or '全部'}.csv"
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": download_disposition(
                filename,
                f"relationship-review-{month or 'all'}.csv",
            )
        },
    )


@app.get("/api/backup.json")
def backup_json():
    with closing(get_conn()) as conn:
        record_rows = conn.execute("SELECT * FROM record_documents ORDER BY record_type, period_key, author").fetchall()
        records = [serialize_record(row) for row in record_rows]
        entries = [daily_record_to_api(item) for item in records if item["record_type"] == "daily" and not item["deleted_at"]]
        weeks = [weekly_record_to_api(item) for item in records if item["record_type"] == "weekly" and not item["deleted_at"]]
        months = [monthly_record_to_api(item) for item in records if item["record_type"] == "monthly" and not item["deleted_at"]]
        revisions = list_record_revisions(conn)
        actions = list_action_items(conn)
        schemas = [dict(row) for row in conn.execute("SELECT * FROM record_schemas ORDER BY record_type, version")]
        analyses = [
            serialize_analysis_record(row)
            for row in conn.execute("SELECT * FROM analysis_records ORDER BY created_at")
        ]
        ai_reviews = [
            serialize_ai_period_review(row)
            for row in conn.execute("SELECT * FROM ai_period_reviews ORDER BY period_type, period_key")
        ]
    payload = {
        "version": 3,
        "app_version": APP_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "daily_entries": entries,
        "weekly_summaries": weeks,
        "monthly_summaries": months,
        "record_documents": records,
        "record_revisions": revisions,
        "record_schemas": schemas,
        "action_items": actions,
        "analysis_records": analyses,
        "ai_period_reviews": ai_reviews,
    }
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8",
        headers={
            "Content-Disposition": download_disposition(
                "关系复盘备份.json",
                "relationship-review-backup.json",
            )
        },
    )


def download_disposition(filename: str, fallback: str) -> str:
    """Return an ASCII-safe header plus an RFC 5987 UTF-8 filename."""
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


@app.get("/health")
@app.get("/api/health")
def health():
    model_catalog = get_model_catalog()
    return jsonify(
        {
            "status": "ok",
            "version": APP_VERSION,
            "database": "ok",
            "ai_configured": model_catalog["configured"],
            "features": {
                "gallup_chat": True,
                "ai_period_reviews": True,
                "model_selector": True,
                "flexible_records": True,
                "dynamic_actions": True,
            },
        }
    )


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
            entries = [
                record
                for person in ("me", "partner")
                if (record := get_record(conn, "daily", period_key, person))
            ]
            source["daily_entries"] = [
                entry_for_ai_review(daily_record_to_api(record)) for record in entries
            ]
        elif period_type == "weekly":
            match = re.fullmatch(r"(\d{4})-(\d{2})-W([1-6])", period_key)
            assert match is not None
            year, month, week_no = map(int, match.groups())
            days_in_month = calendar.monthrange(year, month)[1]
            start_day = (week_no - 1) * 7 + 1
            if start_day <= days_in_month:
                start_date = date(year, month, start_day)
                end_date = date(year, month, min(start_day + 6, days_in_month))
                entries = list_records(
                    conn,
                    "daily",
                    date_from=start_date.isoformat(),
                    date_to=end_date.isoformat(),
                )
            else:
                start_date = date(year, month, days_in_month)
                end_date = start_date
                entries = []
            summary = get_record(conn, "weekly", period_key, "joint")
            source.update(
                {
                    "date_range": [start_date.isoformat(), end_date.isoformat()],
                    "daily_entries": [
                        entry_for_ai_review(daily_record_to_api(record)) for record in reversed(entries)
                    ],
                    "weekly_summary": compact_mapping(summary["data"], 900) if summary else None,
                }
            )
        else:
            entries = list_records(conn, "daily", period_prefix=period_key)
            weeks = list_records(conn, "weekly", period_prefix=f"{period_key}-W")
            month = get_record(conn, "monthly", period_key, "joint")
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
                    "daily_entries": [
                        entry_for_ai_review(daily_record_to_api(record)) for record in reversed(entries)
                    ],
                    "weekly_summaries": [
                        compact_mapping(record["data"], 700) for record in reversed(weeks)
                    ],
                    "monthly_summary": compact_mapping(month["data"], 1200) if month else None,
                    "completed_scene_analyses": [compact_row(row, 700) for row in analyses],
                }
            )

    content_text = review_source_text(source)
    source["has_content"] = bool(content_text.strip())
    source["search_text"] = content_text[:10000]
    return source


def entry_for_ai_review(entry: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "entry_date",
        "person",
        "appreciation",
        "event",
        "feeling",
        "need",
        "response",
        "repair_request",
        "follow_up",
    )
    return {
        field: clean_text(entry.get(field))[:500]
        if field not in {"entry_date", "person", "follow_up"}
        else entry.get(field, "")
        for field in fields
    }


def compact_row(row: sqlite3.Row, max_length: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in row.keys():
        if key in {"id", "created_at", "updated_at"}:
            continue
        value = row[key]
        result[key] = clean_text(value)[:max_length] if isinstance(value, str) else value
    return result


def compact_mapping(value: dict[str, Any], max_length: int) -> dict[str, Any]:
    return {
        key: clean_text(item)[:max_length] if isinstance(item, str) else item
        for key, item in value.items()
    }


def review_source_text(source: dict[str, Any]) -> str:
    meaningful_keys = {
        "appreciation",
        "event",
        "response",
        "repair_request",
        "follow_up",
        "highlights",
        "recurring_pattern",
        "my_learning",
        "partner_signal",
        "overall_change",
        "what_helped",
        "recurring_patterns",
        "needs_attention",
        "next_focus",
        "feeling",
        "need",
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
    model_name: str = "",
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
        model_name,
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
                confidence, model_name, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                model_name = excluded.model_name,
                revision = ai_period_reviews.revision + 1,
                updated_at = excluded.updated_at
            """,
            values,
        )
        if review["adjustment_goal"]:
            upsert_ai_goal(
                conn,
                period_type,
                period_key,
                review["adjustment_goal"],
                "；".join(review["actions"][:2]),
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
    model_name: str = "",
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
        model_name,
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
                model_name, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                model_name = excluded.model_name,
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


FOLLOW_UP_VALUES = {"none", "communicate", "coordinate", "repair", "pause", "resolved"}


def normalize_daily_content(data: dict[str, Any]) -> dict[str, str]:
    follow_up = clean_text(data.get("follow_up"))
    if follow_up not in FOLLOW_UP_VALUES:
        follow_up = "none"
    return {
        "appreciation": clean_text(data.get("appreciation"))[:3000],
        "event": clean_text(data.get("event"))[:3000],
        "feeling": clean_text(data.get("feeling"))[:3000],
        "need": clean_text(data.get("need"))[:3000],
        "response": clean_text(data.get("response"))[:3000],
        "repair_request": clean_text(data.get("repair_request"))[:3000],
        "follow_up": follow_up,
    }


def daily_record_to_api(record: dict[str, Any]) -> dict[str, Any]:
    data = record.get("data", {})
    appreciation = clean_text(data.get("appreciation"))
    event = clean_text(data.get("event"))
    response = clean_text(data.get("response"))
    repair_request = clean_text(data.get("repair_request"))
    follow_up = clean_text(data.get("follow_up")) or "none"
    return {
        "id": record.get("id"),
        "entry_date": record.get("period_key", ""),
        "month_key": clean_text(record.get("period_key"))[:7],
        "person": record.get("author", ""),
        "appreciation": appreciation,
        "event": event,
        "feeling": clean_text(data.get("feeling")),
        "need": clean_text(data.get("need")),
        "response": response,
        "repair_request": repair_request,
        "follow_up": follow_up,
        "schema_key": record.get("schema_key", RECORD_SCHEMAS["daily"]["key"]),
        "schema_version": record.get("schema_version", RECORD_SCHEMAS["daily"]["version"]),
        "revision": record.get("revision", 0),
        "created_at": record.get("created_at", ""),
        "updated_at": record.get("updated_at", ""),
    }


def empty_entry(entry_date: str, person: str) -> dict[str, Any]:
    return {
        "entry_date": entry_date,
        "month_key": entry_date[:7],
        "person": person,
        "appreciation": "",
        "event": "",
        "feeling": "",
        "need": "",
        "response": "",
        "repair_request": "",
        "follow_up": "none",
        "schema_key": RECORD_SCHEMAS["daily"]["key"],
        "schema_version": RECORD_SCHEMAS["daily"]["version"],
        "revision": 0,
        "created_at": "",
        "updated_at": "",
    }


def normalize_weekly_content(data: dict[str, Any]) -> dict[str, str]:
    return {
        "highlights": clean_text(data.get("highlights"))[:4000],
        "recurring_pattern": clean_text(data.get("recurring_pattern"))[:4000],
        "my_learning": clean_text(data.get("my_learning"))[:4000],
        "partner_signal": clean_text(data.get("partner_signal"))[:4000],
        "next_focus": clean_text(data.get("next_focus"))[:4000],
    }


def weekly_record_to_api(record: dict[str, Any]) -> dict[str, Any]:
    data = record.get("data", {})
    period_key = clean_text(record.get("period_key"))
    match = re.fullmatch(r"(\d{4}-\d{2})-W([1-6])", period_key)
    month_key, week_no = (match.group(1), int(match.group(2))) if match else (period_key[:7], 0)
    result = {
        "id": record.get("id"),
        "month_key": month_key,
        "week_no": week_no,
        "highlights": clean_text(data.get("highlights")),
        "recurring_pattern": clean_text(data.get("recurring_pattern")),
        "my_learning": clean_text(data.get("my_learning")),
        "partner_signal": clean_text(data.get("partner_signal")),
        "next_focus": clean_text(data.get("next_focus")),
        "schema_key": record.get("schema_key"),
        "schema_version": record.get("schema_version"),
        "revision": record.get("revision", 0),
        "created_at": record.get("created_at", ""),
        "updated_at": record.get("updated_at", ""),
    }
    return result


def normalize_monthly_content(data: dict[str, Any]) -> dict[str, str]:
    return {
        "overall_change": clean_text(data.get("overall_change"))[:5000],
        "what_helped": clean_text(data.get("what_helped"))[:5000],
        "recurring_patterns": clean_text(data.get("recurring_patterns"))[:5000],
        "needs_attention": clean_text(data.get("needs_attention"))[:5000],
        "next_focus": clean_text(data.get("next_focus"))[:5000],
    }


def monthly_record_to_api(record: dict[str, Any]) -> dict[str, Any]:
    data = record.get("data", {})
    result = {
        "id": record.get("id"),
        "month_key": record.get("period_key", ""),
        "overall_change": clean_text(data.get("overall_change")),
        "what_helped": clean_text(data.get("what_helped")),
        "recurring_patterns": clean_text(data.get("recurring_patterns")),
        "needs_attention": clean_text(data.get("needs_attention")),
        "next_focus": clean_text(data.get("next_focus")),
        "schema_key": record.get("schema_key"),
        "schema_version": record.get("schema_version"),
        "revision": record.get("revision", 0),
        "created_at": record.get("created_at", ""),
        "updated_at": record.get("updated_at", ""),
    }
    return result


def empty_monthly_record(month_key: str) -> dict[str, Any]:
    return monthly_record_to_api(
        {
            "period_key": month_key,
            "data": {},
            "schema_key": RECORD_SCHEMAS["monthly"]["key"],
            "schema_version": RECORD_SCHEMAS["monthly"]["version"],
            "revision": 0,
        }
    )


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
