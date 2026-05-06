from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from .db import connection_context
from .model import get_text_embedding


SEMANTIC_ENTITY_TYPES = {"event", "faq_entry", "policy_article", "department", "contact", "club_profile", "signup_rule"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_entity_semantic_text(entity: dict[str, Any]) -> str:
    lines = [
        f"type: {entity['entity_type']}",
        f"title: {entity['title']}",
        f"slug: {entity['slug']}",
    ]
    for key, value in entity["data"].items():
        if isinstance(value, list):
            value_text = " | ".join(str(item) for item in value if item)
        else:
            value_text = str(value) if value not in (None, "") else ""
        if value_text:
            lines.append(f"{key}: {value_text}")
    return "\n".join(lines)


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def get_cached_entity_embedding(entity: dict[str, Any], source_text_hash: str) -> list[float] | None:
    with connection_context() as connection:
        row = connection.execute(
            """
            SELECT embedding_json
            FROM entity_embeddings
            WHERE entity_id = ? AND entity_type = ? AND version = ? AND source_text_hash = ?
            """,
            (entity["id"], entity["entity_type"], entity["version"], source_text_hash),
        ).fetchone()
    if not row:
        return None
    return json.loads(row["embedding_json"])


def store_entity_embedding(entity: dict[str, Any], source_text_hash: str, embedding: list[float]) -> None:
    with connection_context() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO entity_embeddings (
              entity_id, entity_type, version, source_text_hash, embedding_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entity["id"],
                entity["entity_type"],
                entity["version"],
                source_text_hash,
                json.dumps(embedding),
                now_iso(),
            ),
        )
        connection.commit()


def get_or_create_entity_embedding(entity: dict[str, Any]) -> list[float] | None:
    source_text = build_entity_semantic_text(entity)
    source_text_hash = hash_text(source_text)
    cached = get_cached_entity_embedding(entity, source_text_hash)
    if cached is not None:
        return cached

    embedding = get_text_embedding(source_text)
    if not embedding:
        return None

    store_entity_embedding(entity, source_text_hash, embedding)
    return embedding


def semantic_rank_entities(question: str, entities: list[dict[str, Any]]) -> list[tuple[dict[str, Any], float]]:
    if not entities:
        return []

    query_embedding = get_text_embedding(question)
    if not query_embedding:
        return []

    ranked: list[tuple[dict[str, Any], float]] = []
    for entity in entities:
        if entity["entity_type"] not in SEMANTIC_ENTITY_TYPES:
            continue
        embedding = get_or_create_entity_embedding(entity)
        if not embedding:
            continue
        similarity = cosine_similarity(query_embedding, embedding)
        if similarity > 0:
            ranked.append((entity, similarity))

    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked
