from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .db import connection_context


VALID_STATUSES = {"draft", "pending", "published"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_effective_now(effective_at: str | None) -> bool:
    if not effective_at:
        return True
    try:
        effective_dt = datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if effective_dt.tzinfo is None:
        effective_dt = effective_dt.replace(tzinfo=timezone.utc)
    return effective_dt <= datetime.now(timezone.utc)


def parse_entity(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "entity_type": row["entity_type"],
        "slug": row["slug"],
        "title": row["title"],
        "status": row["status"],
        "data": json.loads(row["data_json"]),
        "version": row["version"],
        "effective_at": row["effective_at"],
        "published_at": row["published_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
    }


def parse_chat_log_row(row: Any) -> dict[str, Any]:
    payload = dict(row)
    source_records_json = payload.get("source_records_json") or "[]"
    debug_trace_json = payload.get("debug_trace_json") or "{}"
    return {
        **payload,
        "needs_verification": bool(payload.get("needs_verification")),
        "source_records": json.loads(source_records_json),
        "debug_trace": json.loads(debug_trace_json),
    }


def get_table_columns(table_name: str) -> set[str]:
    with connection_context() as connection:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def validate_entity_input(payload: dict[str, Any]) -> None:
    required = ["entity_type", "slug", "title", "status", "data", "updated_by"]
    for key in required:
        if payload.get(key) in (None, ""):
            raise ValueError(f"Missing required field: {key}")
    if payload["status"] not in VALID_STATUSES:
        raise ValueError("Invalid status")
    if not isinstance(payload["data"], dict):
        raise ValueError("Field data must be an object")


def get_next_version(entity_type: str, slug: str) -> int:
    with connection_context() as connection:
        row = connection.execute(
            """
            SELECT COALESCE(MAX(version), 0) AS max_version
            FROM entities
            WHERE entity_type = ? AND slug = ?
            """,
            (entity_type, slug),
        ).fetchone()
    return int(row["max_version"]) + 1


def list_entities(entity_type: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if entity_type:
        clauses.append("entity_type = ?")
        params.append(entity_type)
    if status:
        clauses.append("status = ?")
        params.append(status)

    sql = "SELECT * FROM entities"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY updated_at DESC, id DESC"

    with connection_context() as connection:
        rows = connection.execute(sql, params).fetchall()
    return [parse_entity(row) for row in rows]


def get_entity(entity_id: int) -> dict[str, Any] | None:
    with connection_context() as connection:
        row = connection.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return parse_entity(row) if row else None


def create_entity(payload: dict[str, Any]) -> dict[str, Any]:
    validate_entity_input(payload)
    timestamp = now_iso()
    version = get_next_version(payload["entity_type"], payload["slug"])

    with connection_context() as connection:
        cursor = connection.execute(
            """
            INSERT INTO entities (
              entity_type, slug, title, status, data_json, version, effective_at,
              published_at, created_at, updated_at, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["entity_type"],
                payload["slug"],
                payload["title"],
                payload["status"],
                json.dumps(payload["data"], ensure_ascii=False),
                version,
                payload.get("effective_at"),
                timestamp if payload["status"] == "published" else None,
                timestamp,
                timestamp,
                payload["updated_by"],
            ),
        )
        entity_id = cursor.lastrowid
        connection.commit()

    entity = get_entity(int(entity_id))
    if entity is None:
        raise ValueError("Failed to create entity")
    return entity


def update_entity(entity_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    current = get_entity(entity_id)
    if current is None:
        raise ValueError("Entity not found")

    next_payload = {
        "entity_type": patch.get("entity_type", current["entity_type"]),
        "slug": patch.get("slug", current["slug"]),
        "title": patch.get("title", current["title"]),
        "status": patch.get("status", current["status"]),
        "data": patch.get("data", current["data"]),
        "effective_at": patch.get("effective_at", current["effective_at"]),
        "updated_by": patch.get("updated_by", current["updated_by"]),
    }
    return create_entity(next_payload)


def delete_entity(entity_id: int) -> bool:
    with connection_context() as connection:
        cursor = connection.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        connection.commit()
    return cursor.rowcount > 0


def publish_entity(entity_id: int, updated_by: str = "admin") -> dict[str, Any]:
    entity = get_entity(entity_id)
    if entity is None:
        raise ValueError("Entity not found")

    timestamp = now_iso()
    with connection_context() as connection:
        connection.execute(
            """
            UPDATE entities
            SET status = 'pending', updated_at = ?, updated_by = ?
            WHERE entity_type = ? AND slug = ? AND status = 'published' AND id != ?
            """,
            (timestamp, updated_by, entity["entity_type"], entity["slug"], entity_id),
        )
        connection.execute(
            """
            UPDATE entities
            SET status = 'published', published_at = ?, updated_at = ?, updated_by = ?
            WHERE id = ?
            """,
            (timestamp, timestamp, updated_by, entity_id),
        )
        connection.commit()
    published = get_entity(entity_id)
    if published is None:
        raise ValueError("Entity not found after publish")
    return published


def get_published_entities(entity_type: str | None = None) -> list[dict[str, Any]]:
    inner_filter = "AND entity_type = ?" if entity_type else ""
    sql = f"""
        SELECT e.*
        FROM entities e
        INNER JOIN (
          SELECT entity_type, slug, MAX(version) AS max_version
          FROM entities
          WHERE status = 'published'
          {inner_filter}
          GROUP BY entity_type, slug
        ) latest
          ON latest.entity_type = e.entity_type
         AND latest.slug = e.slug
         AND latest.max_version = e.version
        WHERE e.status = 'published'
        ORDER BY e.updated_at DESC
    """
    params = (entity_type,) if entity_type else ()
    with connection_context() as connection:
        rows = connection.execute(sql, params).fetchall()
    return [entity for row in rows if is_effective_now((entity := parse_entity(row))["effective_at"])]


def list_published_faq_entries(limit: int = 10) -> list[dict[str, Any]]:
    items = get_published_entities("faq_entry")[:limit]
    return [
        {
            "id": item["id"],
            "question": item["data"].get("question"),
            "aliases": item["data"].get("aliases", []),
            "answer": item["data"].get("answer"),
        }
        for item in items
    ]


def insert_chat_log(log: dict[str, Any]) -> None:
    chat_log_columns = get_table_columns("chat_logs")
    has_debug_trace = "debug_trace_json" in chat_log_columns

    with connection_context() as connection:
        if has_debug_trace:
            connection.execute(
                """
                INSERT INTO chat_logs (
                  session_id, question, answer_text, answer_mode, matched_entity_type,
                  matched_entity_id, confidence_level, source_records_json, debug_trace_json,
                  needs_verification, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log["session_id"],
                    log["question"],
                    log["answer_text"],
                    log["answer_mode"],
                    log.get("matched_entity_type"),
                    log.get("matched_entity_id"),
                    log["confidence_level"],
                    json.dumps(log.get("source_records", []), ensure_ascii=False),
                    json.dumps(log.get("debug_trace", {}), ensure_ascii=False),
                    1 if log.get("needs_verification") else 0,
                    now_iso(),
                ),
            )
        else:
            connection.execute(
                """
                INSERT INTO chat_logs (
                  session_id, question, answer_text, answer_mode, matched_entity_type,
                  matched_entity_id, confidence_level, source_records_json,
                  needs_verification, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log["session_id"],
                    log["question"],
                    log["answer_text"],
                    log["answer_mode"],
                    log.get("matched_entity_type"),
                    log.get("matched_entity_id"),
                    log["confidence_level"],
                    json.dumps(log.get("source_records", []), ensure_ascii=False),
                    1 if log.get("needs_verification") else 0,
                    now_iso(),
                ),
            )
        connection.commit()


def insert_unmatched_question(item: dict[str, Any]) -> None:
    with connection_context() as connection:
        connection.execute(
            """
            INSERT INTO unmatched_questions (session_id, question, reason, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (item["session_id"], item["question"], item["reason"], now_iso()),
        )
        connection.commit()


def get_session_state(session_id: str) -> dict[str, Any] | None:
    with connection_context() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM session_state
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    if not row:
        return None
    return {
        **dict(row),
        "source_records": json.loads(row["focus_source_records_json"] or "[]"),
    }


def upsert_session_state(
    session_id: str,
    focused_entity_type: str | None,
    focused_entity_id: int | None,
    source_records: list[dict[str, Any]] | None,
    conversation_mode: str | None,
) -> None:
    with connection_context() as connection:
        connection.execute(
            """
            INSERT INTO session_state (
              session_id, focused_entity_type, focused_entity_id, focus_source_records_json, conversation_mode, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
              focused_entity_type = excluded.focused_entity_type,
              focused_entity_id = excluded.focused_entity_id,
              focus_source_records_json = excluded.focus_source_records_json,
              conversation_mode = excluded.conversation_mode,
              updated_at = excluded.updated_at
            """,
            (
                session_id,
                focused_entity_type,
                focused_entity_id,
                json.dumps(source_records or [], ensure_ascii=False),
                conversation_mode,
                now_iso(),
            ),
        )
        connection.commit()


def list_chat_logs(limit: int = 100) -> list[dict[str, Any]]:
    with connection_context() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM chat_logs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [parse_chat_log_row(row) for row in rows]


def list_chat_logs_for_session(session_id: str, limit: int = 10) -> list[dict[str, Any]]:
    with connection_context() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM chat_logs
            WHERE session_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    return [parse_chat_log_row(row) for row in rows]


def list_unmatched_questions(limit: int = 100) -> list[dict[str, Any]]:
    with connection_context() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM unmatched_questions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def seed_demo_data() -> None:
    with connection_context() as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM entities").fetchone()
    if row["count"] > 0:
        return

    seed_rows = [
        {
            "entity_type": "club_profile",
            "slug": "main",
            "title": "星火 AI 社团",
            "status": "published",
            "updated_by": "system",
            "data": {
                "club_name": "星火 AI 社团",
                "mission": "帮助同学们用 AI 做项目、打比赛、做作品集。",
                "intro": "我们长期组织 AI 入门分享、项目实战和跨专业合作活动。",
                "base_location": "大学生活动中心 302",
                "contact_hint": "如需加入咨询，可先在小程序内查看报名规则和联系人信息。",
            },
        },
        {
            "entity_type": "department",
            "slug": "product-team",
            "title": "产品策划部",
            "status": "published",
            "updated_by": "system",
            "data": {
                "department_name": "产品策划部",
                "responsibilities": ["活动策划", "招新流程设计", "跨部门协作"],
                "manager": "王学姐",
                "intro": "主要负责社团活动策划、项目推进和跨部门沟通。",
            },
        },
        {
            "entity_type": "event",
            "slug": "2026-spring-recruitment",
            "title": "2026 春季招新宣讲会",
            "status": "published",
            "updated_by": "system",
            "effective_at": "2026-04-10T19:00:00.000Z",
            "data": {
                "event_name": "2026 春季招新宣讲会",
                "time": "2026-04-20 19:00",
                "location": "图书馆报告厅 B201",
                "signup_method": "在小程序首页点击“报名招新”填写表单",
                "audience": "全校对 AI、产品、设计、开发感兴趣的同学",
                "fee": "免费",
                "owner": "李同学",
                "status_label": "报名中",
                "intro_text": "活动会介绍社团方向、部门分工和本学期项目机会。",
            },
        },
        {
            "entity_type": "signup_rule",
            "slug": "2026-spring-general",
            "title": "2026 春季招新报名规则",
            "status": "published",
            "updated_by": "system",
            "data": {
                "target_event_slug": "2026-spring-recruitment",
                "eligibility": "全日制在校学生均可报名",
                "deadline": "2026-04-18 23:59",
                "process": "报名表提交后，24 小时内会收到面试时间通知。",
                "reminder": "请认真填写项目经历和兴趣方向，便于部门匹配。",
            },
        },
        {
            "entity_type": "contact",
            "slug": "recruitment-contact",
            "title": "招新联系人",
            "status": "published",
            "updated_by": "system",
            "data": {
                "contact_name": "李同学",
                "role": "招新负责人",
                "channel": "微信",
                "contact_value": "spark-ai-2026",
                "available_time": "工作日 18:00-22:00",
            },
        },
        {
            "entity_type": "faq_entry",
            "slug": "how-to-join",
            "title": "怎么报名加入社团",
            "status": "published",
            "updated_by": "system",
            "data": {
                "question": "怎么报名加入社团？",
                "aliases": ["怎么加入社团", "报名入口在哪", "如何报名"],
                "answer": "进入小程序首页后点击“报名招新”，填写表单即可完成报名。",
                "related_entity_type": "signup_rule",
                "related_entity_slug": "2026-spring-general",
            },
        },
        {
            "entity_type": "policy_article",
            "slug": "attendance-policy",
            "title": "活动签到说明",
            "status": "published",
            "updated_by": "system",
            "data": {
                "summary": "活动开始前 15 分钟开放签到，迟到超过 20 分钟需要补充说明。",
                "details": "如因课程冲突无法准时到场，请提前联系活动负责人报备。",
            },
        },
    ]

    for row in seed_rows:
        create_entity(row)


def reset_all_data() -> None:
    with connection_context() as connection:
        connection.executescript(
            """
            DELETE FROM chat_logs;
            DELETE FROM unmatched_questions;
            DELETE FROM session_state;
            DELETE FROM entity_embeddings;
            DELETE FROM entities;
            DELETE FROM sqlite_sequence WHERE name IN ('entities', 'chat_logs', 'unmatched_questions');
            """
        )
        connection.commit()
