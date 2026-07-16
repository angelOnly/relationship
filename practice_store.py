from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any


PRACTICE_SKILLS = (
    "事实具体性",
    "感受准确性",
    "需要清楚度",
    "请求可执行性",
    "复述确认",
    "回应明确性",
)

STRATEGY_LABELS = {
    "fact_feeling_need_request": "事实＋感受＋需要＋请求",
    "connection_before_solution": "先连接，再解决",
    "specific_time_request": "请求带具体时间",
    "paraphrase_before_explain": "先复述，再解释",
    "pause_with_return_time": "暂停并约定返回时间",
    "acknowledge_then_negotiate": "先承认影响，再协商",
}


def init_practice_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS practice_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            speaker_id TEXT NOT NULL CHECK(speaker_id IN ('xiaoli', 'xiaoyuan')),
            ai_role_id TEXT NOT NULL CHECK(ai_role_id IN ('xiaoli', 'xiaoyuan')),
            scene_type TEXT NOT NULL DEFAULT '其他',
            topic_summary TEXT NOT NULL DEFAULT '',
            goal TEXT NOT NULL DEFAULT '',
            source_scene_analysis_id INTEGER,
            stage TEXT NOT NULL DEFAULT 'setup',
            status TEXT NOT NULL DEFAULT 'active',
            current_round INTEGER NOT NULL DEFAULT 1,
            final_expression TEXT NOT NULL DEFAULT '',
            final_paraphrase TEXT NOT NULL DEFAULT '',
            final_response TEXT NOT NULL DEFAULT '',
            skill_result_json TEXT NOT NULL DEFAULT '{}',
            strategy_tags_json TEXT NOT NULL DEFAULT '[]',
            model_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY(source_scene_analysis_id) REFERENCES scene_analyses(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_practice_sessions_updated
            ON practice_sessions(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_practice_sessions_status
            ON practice_sessions(status, updated_at DESC);

        CREATE TABLE IF NOT EXISTS practice_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            turn_id TEXT NOT NULL,
            round_no INTEGER NOT NULL DEFAULT 1,
            sequence_no INTEGER NOT NULL,
            stage TEXT NOT NULL,
            actor TEXT NOT NULL CHECK(actor IN ('user', 'ai_partner', 'ai_coach', 'system')),
            content TEXT NOT NULL DEFAULT '',
            structured_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES practice_sessions(id) ON DELETE CASCADE,
            UNIQUE(session_id, turn_id)
        );

        CREATE INDEX IF NOT EXISTS idx_practice_turns_session
            ON practice_turns(session_id, sequence_no);

        CREATE TABLE IF NOT EXISTS practice_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            practice_session_id INTEGER NOT NULL,
            scene_analysis_id INTEGER,
            used_at TEXT NOT NULL,
            partner_reaction TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL CHECK(result IN ('helpful', 'neutral', 'worse')),
            agreement_reached INTEGER NOT NULL DEFAULT 0,
            pause_returned INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '',
            confirmed_by_user INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY(practice_session_id) REFERENCES practice_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(scene_analysis_id) REFERENCES scene_analyses(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_practice_outcomes_session
            ON practice_outcomes(practice_session_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_practice_outcomes_result
            ON practice_outcomes(confirmed_by_user, result, created_at DESC);
        """
    )


def create_practice_session(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    cursor = conn.execute(
        """
        INSERT INTO practice_sessions (
            speaker_id, ai_role_id, scene_type, topic_summary, goal,
            source_scene_analysis_id, stage, status, current_round,
            model_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'setup', 'active', 1, ?, ?, ?)
        """,
        (
            data["speaker_id"],
            data["ai_role_id"],
            data.get("scene_type", "其他"),
            data.get("topic_summary", ""),
            data.get("goal", ""),
            data.get("source_scene_analysis_id"),
            data.get("model_name", ""),
            now,
            now,
        ),
    )
    session_id = int(cursor.lastrowid)
    add_practice_turn(
        conn,
        session_id,
        f"session-{session_id}-created",
        1,
        "setup",
        "system",
        "练习已创建",
        {"event": "session_created"},
    )
    row = conn.execute("SELECT * FROM practice_sessions WHERE id = ?", (session_id,)).fetchone()
    return serialize_practice_session(row, conn=conn, include_turns=True)


def get_practice_session(
    conn: sqlite3.Connection,
    session_id: int,
    *,
    include_turns: bool = True,
) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM practice_sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    return serialize_practice_session(row, conn=conn, include_turns=include_turns)


def list_practice_sessions(
    conn: sqlite3.Connection,
    *,
    speaker_id: str = "",
    status: str = "",
    limit: int = 30,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if speaker_id:
        clauses.append("speaker_id = ?")
        params.append(speaker_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM practice_sessions {where} ORDER BY updated_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [serialize_practice_session(row, conn=conn, include_turns=False) for row in rows]


def update_practice_session(
    conn: sqlite3.Connection,
    session_id: int,
    **changes: Any,
) -> dict[str, Any] | None:
    allowed = {
        "scene_type",
        "topic_summary",
        "goal",
        "stage",
        "status",
        "current_round",
        "final_expression",
        "final_paraphrase",
        "final_response",
        "model_name",
        "completed_at",
    }
    normalized: dict[str, Any] = {}
    for key, value in changes.items():
        if key in allowed:
            normalized[key] = value
    if "skill_results" in changes:
        normalized["skill_result_json"] = _json_dump(changes["skill_results"])
    if "strategy_tags" in changes:
        normalized["strategy_tags_json"] = _json_dump(changes["strategy_tags"])
    if not normalized:
        return get_practice_session(conn, session_id)
    normalized["updated_at"] = _now()
    assignments = ", ".join(f"{key} = ?" for key in normalized)
    conn.execute(
        f"UPDATE practice_sessions SET {assignments} WHERE id = ?",
        [*normalized.values(), session_id],
    )
    return get_practice_session(conn, session_id)


def add_practice_turn(
    conn: sqlite3.Connection,
    session_id: int,
    turn_id: str,
    round_no: int,
    stage: str,
    actor: str,
    content: str,
    structured: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    existing = conn.execute(
        "SELECT * FROM practice_turns WHERE session_id = ? AND turn_id = ?",
        (session_id, turn_id),
    ).fetchone()
    if existing is not None:
        return serialize_practice_turn(existing), False
    sequence_no = conn.execute(
        "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM practice_turns WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO practice_turns (
            session_id, turn_id, round_no, sequence_no, stage, actor,
            content, structured_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            turn_id,
            round_no,
            sequence_no,
            stage,
            actor,
            content,
            _json_dump(structured or {}),
            _now(),
        ),
    )
    row = conn.execute(
        "SELECT * FROM practice_turns WHERE session_id = ? AND turn_id = ?",
        (session_id, turn_id),
    ).fetchone()
    return serialize_practice_turn(row), True


def practice_turn_exists(conn: sqlite3.Connection, session_id: int, turn_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM practice_turns WHERE session_id = ? AND turn_id = ?",
        (session_id, turn_id),
    ).fetchone() is not None


def delete_practice_session(conn: sqlite3.Connection, session_id: int) -> bool:
    cursor = conn.execute("DELETE FROM practice_sessions WHERE id = ?", (session_id,))
    return cursor.rowcount > 0


def create_practice_outcome(
    conn: sqlite3.Connection,
    session_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    now = _now()
    cursor = conn.execute(
        """
        INSERT INTO practice_outcomes (
            practice_session_id, scene_analysis_id, used_at, partner_reaction,
            result, agreement_reached, pause_returned, note,
            confirmed_by_user, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            session_id,
            data.get("scene_analysis_id"),
            data["used_at"],
            data.get("partner_reaction", ""),
            data["result"],
            int(bool(data.get("agreement_reached"))),
            int(bool(data.get("pause_returned"))),
            data.get("note", ""),
            now,
        ),
    )
    row = conn.execute("SELECT * FROM practice_outcomes WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return serialize_practice_outcome(row)


def list_practice_outcomes(
    conn: sqlite3.Connection,
    session_id: int | None = None,
) -> list[dict[str, Any]]:
    if session_id is None:
        rows = conn.execute("SELECT * FROM practice_outcomes ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM practice_outcomes WHERE practice_session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
    return [serialize_practice_outcome(row) for row in rows]


def get_practice_progress(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT skill_result_json, completed_at
        FROM practice_sessions
        WHERE status = 'completed'
        ORDER BY completed_at DESC, updated_at DESC
        """
    ).fetchall()
    skills = []
    for name in PRACTICE_SKILLS:
        counts = {"未尝试": 0, "需调整": 0, "已做到": 0}
        recent: list[dict[str, str]] = []
        for row in rows:
            result = _json_load(row["skill_result_json"], {})
            status = result.get(name, "未尝试")
            if status not in counts:
                status = "未尝试"
            counts[status] += 1
            if len(recent) < 12:
                recent.append({"status": status, "completed_at": row["completed_at"] or ""})
        skills.append({"name": name, "counts": counts, "recent": list(reversed(recent))})
    return {"completed_sessions": len(rows), "skills": skills}


def get_strategy_stats(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.id, s.strategy_tags_json, o.result, o.agreement_reached, o.pause_returned
        FROM practice_outcomes o
        JOIN practice_sessions s ON s.id = o.practice_session_id
        WHERE o.confirmed_by_user = 1
        """
    ).fetchall()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        for tag in _json_load(row["strategy_tags_json"], []):
            if tag not in STRATEGY_LABELS:
                continue
            item = grouped.setdefault(
                tag,
                {
                    "tag": tag,
                    "label": STRATEGY_LABELS[tag],
                    "total": 0,
                    "helpful": 0,
                    "neutral": 0,
                    "worse": 0,
                    "agreement_reached": 0,
                    "pause_returned": 0,
                    "session_ids": set(),
                },
            )
            item["total"] += 1
            item[row["result"]] += 1
            item["agreement_reached"] += int(row["agreement_reached"] or 0)
            item["pause_returned"] += int(row["pause_returned"] or 0)
            item["session_ids"].add(row["id"])
    result: list[dict[str, Any]] = []
    for item in grouped.values():
        total = item["total"]
        item["session_count"] = len(item.pop("session_ids"))
        item["display"] = f"{item['helpful']}/{total} 次有帮助"
        item["helpful_rate"] = round(item["helpful"] / total, 3) if total >= 5 else None
        result.append(item)
    result.sort(key=lambda item: (item["helpful"], item["total"]), reverse=True)
    return result


def find_confirmed_successes(
    conn: sqlite3.Connection,
    query: str,
    *,
    speaker_id: str = "",
    limit: int = 5,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    speaker_clause = ""
    if speaker_id:
        speaker_clause = "AND s.speaker_id = ?"
        params.append(speaker_id)
    rows = conn.execute(
        f"""
        SELECT s.*, o.id AS outcome_id, o.used_at, o.partner_reaction,
               o.agreement_reached, o.pause_returned, o.note
        FROM practice_outcomes o
        JOIN practice_sessions s ON s.id = o.practice_session_id
        WHERE o.confirmed_by_user = 1 AND o.result = 'helpful' {speaker_clause}
        ORDER BY o.created_at DESC
        LIMIT 100
        """,
        params,
    ).fetchall()
    query_tokens = _tokens(query)
    ranked: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        searchable = " ".join(
            str(row[key] or "")
            for key in ("scene_type", "topic_summary", "goal", "final_expression", "partner_reaction", "note")
        )
        tokens = _tokens(searchable)
        overlap = len(query_tokens & tokens)
        if query_tokens and overlap == 0:
            continue
        score = overlap / max(1, len(query_tokens))
        if str(row["scene_type"] or "") and str(row["scene_type"]) in query:
            score += 0.5
        ranked.append((score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "source_type": "confirmed_success",
            "reference_id": f"practice_outcome:{row['outcome_id']}",
            "practice_session_id": row["id"],
            "scene_type": row["scene_type"],
            "topic_summary": row["topic_summary"],
            "final_expression": row["final_expression"],
            "strategy_tags": _json_load(row["strategy_tags_json"], []),
            "used_at": row["used_at"],
            "partner_reaction": row["partner_reaction"],
            "agreement_reached": bool(row["agreement_reached"]),
            "pause_returned": bool(row["pause_returned"]),
            "note": row["note"],
        }
        for _, row in ranked[:limit]
    ]


def serialize_practice_session(
    row: sqlite3.Row,
    *,
    conn: sqlite3.Connection | None = None,
    include_turns: bool = False,
) -> dict[str, Any]:
    item = dict(row)
    item["skill_results"] = _json_load(item.pop("skill_result_json", "{}"), {})
    item["strategy_tags"] = _json_load(item.pop("strategy_tags_json", "[]"), [])
    if include_turns and conn is not None:
        rows = conn.execute(
            "SELECT * FROM practice_turns WHERE session_id = ? ORDER BY sequence_no",
            (item["id"],),
        ).fetchall()
        item["turns"] = [serialize_practice_turn(turn) for turn in rows]
        item["outcomes"] = list_practice_outcomes(conn, item["id"])
    return item


def serialize_practice_turn(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["structured"] = _json_load(item.pop("structured_json", "{}"), {})
    return item


def serialize_practice_outcome(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["agreement_reached"] = bool(item["agreement_reached"])
    item["pause_returned"] = bool(item["pause_returned"])
    item["confirmed_by_user"] = bool(item["confirmed_by_user"])
    return item


def _tokens(value: str) -> set[str]:
    import re

    compact = "".join(re.findall(r"[0-9a-z\u4e00-\u9fff]", str(value).lower()))
    grams = {compact[index : index + 2] for index in range(max(0, len(compact) - 1))}
    words = {item for item in re.split(r"[^0-9a-z\u4e00-\u9fff]+", str(value).lower()) if len(item) >= 2}
    return grams | words


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
