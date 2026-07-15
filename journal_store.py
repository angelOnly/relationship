from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Iterable


DAILY_SCHEMA_KEY = "universal-daily"
WEEKLY_SCHEMA_KEY = "universal-weekly"
MONTHLY_SCHEMA_KEY = "universal-monthly"
SCHEMA_VERSION = 1

RECORD_SCHEMAS: dict[str, dict[str, Any]] = {
    "daily": {
        "key": DAILY_SCHEMA_KEY,
        "version": SCHEMA_VERSION,
        "title": "长期通用每日记录",
        "description": "记录事实、体验、需要、互动与下一步；评分交给 AI。",
        "fields": [
            {"name": "appreciation", "label": "值得肯定的一件具体事", "type": "text"},
            {"name": "event", "label": "今天最值得记录的一件具体事", "type": "text"},
            {"name": "feeling", "label": "我当时的感受", "type": "text"},
            {"name": "need", "label": "我真正重视或需要什么", "type": "text"},
            {"name": "response", "label": "我怎么表达，对方怎么回应", "type": "text"},
            {"name": "repair_request", "label": "接下来是否需要修复，以及一个具体请求", "type": "text"},
            {
                "name": "follow_up",
                "label": "这件事目前处于什么状态",
                "type": "select",
                "options": [
                    {"value": "none", "label": "只记录，不需要处理"},
                    {"value": "communicate", "label": "需要表达或倾听"},
                    {"value": "coordinate", "label": "需要共同协商"},
                    {"value": "repair", "label": "需要修复连接"},
                    {"value": "pause", "label": "先暂停，约定再谈"},
                    {"value": "resolved", "label": "已经处理"},
                ],
            },
        ],
    },
    "weekly": {
        "key": WEEKLY_SCHEMA_KEY,
        "version": SCHEMA_VERSION,
        "title": "长期通用每周小结",
        "description": "看见本周模式与有效做法，只保留一个下周重点。",
        "fields": [
            {"name": "highlights", "label": "本周值得保留的时刻", "type": "text"},
            {"name": "recurring_pattern", "label": "重复出现的互动模式", "type": "text"},
            {"name": "my_learning", "label": "我这一周的觉察或调整", "type": "text"},
            {"name": "partner_signal", "label": "我看见对方的努力或需要", "type": "text"},
            {"name": "next_focus", "label": "下周唯一关注点", "type": "text"},
        ],
    },
    "monthly": {
        "key": MONTHLY_SCHEMA_KEY,
        "version": SCHEMA_VERSION,
        "title": "长期通用月度复盘",
        "description": "比较趋势，而不是用单次冲突定义整段关系。",
        "fields": [
            {"name": "overall_change", "label": "这个月关系整体有什么变化", "type": "text"},
            {"name": "what_helped", "label": "哪些做法确实有帮助", "type": "text"},
            {"name": "recurring_patterns", "label": "反复出现了哪些模式", "type": "text"},
            {"name": "needs_attention", "label": "接下来最需要照顾什么", "type": "text"},
            {"name": "next_focus", "label": "下个月唯一优先目标", "type": "text"},
        ],
    },
}

BASELINE_ACTIONS = (
    ("boundary-no-humiliation", "共同底线", "不羞辱、不威胁、不做人身评价", "可以表达愤怒和失望，但不攻击人格、价值或关系安全。", 10),
    ("boundary-safe-pause", "共同底线", "暂停时说明何时回来", "任何一方都可以暂停；同时给出可执行的恢复沟通时间，不用消失惩罚对方。", 20),
    ("boundary-no-verdict", "共同底线", "情绪高峰不做关系判决", "疲惫、激动或深夜时先记录，不仓促决定关系走向。", 30),
    ("practice-one-event", "长期练习", "一次只谈一件具体事", "把当前事件与旧账分开，先完成眼前这一轮沟通。", 40),
    ("practice-four-steps", "长期练习", "事实、感受、需要、请求", "描述可观察事实，再说体验和需要，最后提出一个可以回答的具体请求。", 50),
    ("practice-understand-first", "长期练习", "确认理解后再解释", "先复述对方最在意的点，确认无误后再补充自己的原因和立场。", 60),
    ("practice-one-goal", "长期练习", "每个周期只练一个重点", "目标越少越容易形成新习惯；完成或失效后再替换。", 70),
)


def init_flexible_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS record_schemas (
            schema_key TEXT NOT NULL,
            version INTEGER NOT NULL,
            record_type TEXT NOT NULL,
            title TEXT NOT NULL,
            definition_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(schema_key, version)
        );

        CREATE TABLE IF NOT EXISTS record_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_type TEXT NOT NULL,
            period_key TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT 'joint',
            schema_key TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            data_json TEXT NOT NULL DEFAULT '{}',
            searchable_text TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT NOT NULL DEFAULT '',
            UNIQUE(record_type, period_key, author)
        );

        CREATE TABLE IF NOT EXISTS record_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            schema_key TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            data_json TEXT NOT NULL,
            searchable_text TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(record_id, revision),
            FOREIGN KEY(record_id) REFERENCES record_documents(id)
        );

        CREATE INDEX IF NOT EXISTS idx_record_documents_period
            ON record_documents(record_type, period_key, author);
        CREATE INDEX IF NOT EXISTS idx_record_documents_updated
            ON record_documents(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_record_revisions_record
            ON record_revisions(record_id, revision DESC);

        CREATE TABLE IF NOT EXISTS action_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL DEFAULT 'both',
            kind TEXT NOT NULL DEFAULT 'goal',
            title TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            source TEXT NOT NULL DEFAULT 'manual',
            source_ref TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 100,
            start_date TEXT NOT NULL DEFAULT '',
            due_date TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source, source_ref)
        );

        CREATE INDEX IF NOT EXISTS idx_action_items_status
            ON action_items(status, priority, updated_at DESC);

        """
    )
    _seed_record_schemas(conn)
    _seed_baseline_actions(conn)


def get_record_schema(conn: sqlite3.Connection, record_type: str) -> dict[str, Any] | None:
    schema = RECORD_SCHEMAS.get(record_type)
    if not schema:
        return None
    row = conn.execute(
        "SELECT definition_json FROM record_schemas WHERE schema_key = ? AND version = ?",
        (schema["key"], schema["version"]),
    ).fetchone()
    return _json_load(row["definition_json"], schema) if row else dict(schema)


def upsert_record(
    conn: sqlite3.Connection,
    *,
    record_type: str,
    period_key: str,
    author: str,
    data: dict[str, Any],
    schema_key: str | None = None,
    schema_version: int | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    schema = RECORD_SCHEMAS[record_type]
    schema_key = schema_key or schema["key"]
    schema_version = int(schema_version or schema["version"])
    now = datetime.now().isoformat(timespec="seconds")
    updated_at = updated_at or now
    searchable = build_searchable_text(data)
    data_json = _json_dump(data)
    metadata_json = _json_dump(metadata or {})
    existing = conn.execute(
        "SELECT * FROM record_documents WHERE record_type = ? AND period_key = ? AND author = ?",
        (record_type, period_key, author),
    ).fetchone()
    if existing:
        record_id = existing["id"]
        revision = int(existing["revision"] or 0) + 1
        conn.execute(
            """
            UPDATE record_documents
            SET schema_key = ?, schema_version = ?, data_json = ?, searchable_text = ?,
                metadata_json = ?, revision = ?, updated_at = ?, deleted_at = ''
            WHERE id = ?
            """,
            (
                schema_key,
                schema_version,
                data_json,
                searchable,
                metadata_json,
                revision,
                updated_at,
                record_id,
            ),
        )
    else:
        revision = 1
        cursor = conn.execute(
            """
            INSERT INTO record_documents (
                record_type, period_key, author, schema_key, schema_version,
                data_json, searchable_text, metadata_json, revision,
                created_at, updated_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
            """,
            (
                record_type,
                period_key,
                author,
                schema_key,
                schema_version,
                data_json,
                searchable,
                metadata_json,
                revision,
                created_at or updated_at,
                updated_at,
            ),
        )
        record_id = int(cursor.lastrowid)

    conn.execute(
        """
        INSERT INTO record_revisions (
            record_id, revision, schema_key, schema_version, data_json,
            searchable_text, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record_id,
            revision,
            schema_key,
            schema_version,
            data_json,
            searchable,
            metadata_json,
            updated_at,
        ),
    )
    row = conn.execute("SELECT * FROM record_documents WHERE id = ?", (record_id,)).fetchone()
    return serialize_record(row)


def get_record(
    conn: sqlite3.Connection,
    record_type: str,
    period_key: str,
    author: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM record_documents
        WHERE record_type = ? AND period_key = ? AND author = ? AND deleted_at = ''
        """,
        (record_type, period_key, author),
    ).fetchone()
    return serialize_record(row) if row else None


def list_records(
    conn: sqlite3.Connection,
    record_type: str,
    *,
    period_prefix: str = "",
    author: str = "",
    query: str = "",
    date_from: str = "",
    date_to: str = "",
) -> list[dict[str, Any]]:
    clauses = ["record_type = ?", "deleted_at = ''"]
    params: list[Any] = [record_type]
    if period_prefix:
        clauses.append("period_key LIKE ?")
        params.append(f"{period_prefix}%")
    if author:
        clauses.append("author = ?")
        params.append(author)
    if query:
        clauses.append("searchable_text LIKE ?")
        params.append(f"%{query}%")
    if date_from:
        clauses.append("period_key >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("period_key <= ?")
        params.append(date_to)
    rows = conn.execute(
        f"SELECT * FROM record_documents WHERE {' AND '.join(clauses)} ORDER BY period_key DESC, author ASC",
        params,
    ).fetchall()
    return [serialize_record(row) for row in rows]


def soft_delete_record(
    conn: sqlite3.Connection,
    record_type: str,
    period_key: str,
    author: str,
) -> bool:
    now = datetime.now().isoformat(timespec="seconds")
    cursor = conn.execute(
        """
        UPDATE record_documents SET deleted_at = ?, updated_at = ?
        WHERE record_type = ? AND period_key = ? AND author = ? AND deleted_at = ''
        """,
        (now, now, record_type, period_key, author),
    )
    return cursor.rowcount > 0


def serialize_record(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["data"] = _json_load(item.pop("data_json", "{}"), {})
    item["metadata"] = _json_load(item.pop("metadata_json", "{}"), {})
    return item


def list_record_revisions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM record_revisions ORDER BY record_id, revision").fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["data"] = _json_load(item.pop("data_json", "{}"), {})
        item["metadata"] = _json_load(item.pop("metadata_json", "{}"), {})
        result.append(item)
    return result


def list_action_items(
    conn: sqlite3.Connection,
    *,
    statuses: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    status_list = [status for status in (statuses or []) if status]
    if status_list:
        where = f"WHERE status IN ({','.join('?' for _ in status_list)})"
        params.extend(status_list)
    rows = conn.execute(
        f"""
        SELECT * FROM action_items {where}
        ORDER BY CASE status
            WHEN 'suggested' THEN 0 WHEN 'active' THEN 1 WHEN 'paused' THEN 2
            WHEN 'completed' THEN 3 ELSE 4 END,
            CASE kind WHEN 'boundary' THEN 0 WHEN 'practice' THEN 1 ELSE 2 END,
            priority, updated_at DESC
        """,
        params,
    ).fetchall()
    return [serialize_action_item(row) for row in rows]


def create_action_item(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    source = str(data.get("source") or "manual")
    source_ref = str(data.get("source_ref") or uuid.uuid4().hex)
    cursor = conn.execute(
        """
        INSERT INTO action_items (
            owner, kind, title, detail, status, source, source_ref, priority,
            start_date, due_date, tags_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.get("owner", "both"),
            data.get("kind", "goal"),
            str(data.get("title", "")).strip(),
            str(data.get("detail", "")).strip(),
            data.get("status", "active"),
            source,
            source_ref,
            int(data.get("priority", 100)),
            str(data.get("start_date", "")),
            str(data.get("due_date", "")),
            _json_dump(data.get("tags", [])),
            now,
            now,
        ),
    )
    row = conn.execute("SELECT * FROM action_items WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return serialize_action_item(row)


def update_action_item(
    conn: sqlite3.Connection,
    action_id: int,
    changes: dict[str, Any],
) -> dict[str, Any] | None:
    allowed = {"owner", "kind", "title", "detail", "status", "priority", "start_date", "due_date"}
    updates: list[str] = []
    params: list[Any] = []
    for key in allowed:
        if key in changes:
            updates.append(f"{key} = ?")
            params.append(changes[key])
    if "tags" in changes:
        updates.append("tags_json = ?")
        params.append(_json_dump(changes["tags"]))
    if not updates:
        row = conn.execute("SELECT * FROM action_items WHERE id = ?", (action_id,)).fetchone()
        return serialize_action_item(row) if row else None
    updates.append("updated_at = ?")
    params.append(datetime.now().isoformat(timespec="seconds"))
    params.append(action_id)
    conn.execute(f"UPDATE action_items SET {', '.join(updates)} WHERE id = ?", params)
    row = conn.execute("SELECT * FROM action_items WHERE id = ?", (action_id,)).fetchone()
    return serialize_action_item(row) if row else None


def upsert_ai_goal(
    conn: sqlite3.Connection,
    period_type: str,
    period_key: str,
    title: str,
    detail: str = "",
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    source = f"ai_{period_type}"
    source_ref = f"{period_type}:{period_key}"
    conn.execute(
        """
        INSERT INTO action_items (
            owner, kind, title, detail, status, source, source_ref,
            priority, created_at, updated_at
        ) VALUES ('both', 'goal', ?, ?, 'suggested', ?, ?, 80, ?, ?)
        ON CONFLICT(source, source_ref) DO UPDATE SET
            title = excluded.title,
            detail = excluded.detail,
            updated_at = excluded.updated_at
        """,
        (title, detail, source, source_ref, now, now),
    )


def serialize_action_item(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["tags"] = _json_load(item.pop("tags_json", "[]"), [])
    return item


def build_searchable_text(value: Any) -> str:
    parts: list[str] = []

    def collect(item: Any) -> None:
        if isinstance(item, dict):
            for child in item.values():
                collect(child)
        elif isinstance(item, list):
            for child in item:
                collect(child)
        elif item is not None:
            parts.append(str(item).strip())

    collect(value)
    return "\n".join(part for part in parts if part)[:30000]


def _seed_record_schemas(conn: sqlite3.Connection) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    for record_type, schema in RECORD_SCHEMAS.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO record_schemas (
                schema_key, version, record_type, title, definition_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                schema["key"],
                schema["version"],
                record_type,
                schema["title"],
                _json_dump(schema),
                now,
            ),
        )


def _seed_baseline_actions(conn: sqlite3.Connection) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    for source_ref, kind_label, title, detail, priority in BASELINE_ACTIONS:
        kind = "boundary" if kind_label == "共同底线" else "practice"
        conn.execute(
            """
            INSERT OR IGNORE INTO action_items (
                owner, kind, title, detail, status, source, source_ref,
                priority, created_at, updated_at
            ) VALUES ('both', ?, ?, ?, 'active', 'baseline', ?, ?, ?, ?)
            """,
            (kind, title, detail, source_ref, priority, now, now),
        )


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: Any, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return default
