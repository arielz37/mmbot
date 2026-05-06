from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .model import generate_general_reply, generate_grounded_answer, judge_candidates, plan_turn
from .repository import (
    get_published_entities,
    insert_chat_log,
    insert_unmatched_question,
    list_chat_logs_for_session,
)
from .semantic import semantic_rank_entities


ALLOWED_ENTITY_TYPES = ("event", "signup_rule", "contact", "department", "faq_entry", "policy_article", "club_profile")


def source_record(entity: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {
        "entity_type": entity["entity_type"],
        "entity_id": entity["id"],
        "title": entity["title"],
        "fields": fields,
    }


def build_event_answer(event: dict[str, Any], signup_rule: dict[str, Any] | None) -> dict[str, Any]:
    data = event["data"]
    parts = [
        f"MMbot这边查到的最新活动信息是：{data.get('event_name', event['title'])}。",
        f"时间：{data.get('time', '待更新')}",
        f"地点：{data.get('location', '待更新')}",
        f"报名方式：{data.get('signup_method', '待更新')}",
        f"面向对象：{data.get('audience', '待更新')}",
        f"费用：{data.get('fee', '待更新')}",
        f"负责人：{data.get('owner', '待更新')}",
    ]
    sources = [source_record(event, ["event_name", "time", "location", "signup_method", "audience", "fee", "owner"])]

    if signup_rule:
        parts.append(f"报名截止：{signup_rule['data'].get('deadline', '待更新')}")
        parts.append(
            f"补充说明：{signup_rule['data'].get('process') or signup_rule['data'].get('reminder') or '请留意后续通知'}"
        )
        sources.append(source_record(signup_rule, ["deadline", "process", "reminder"]))

    return {
        "answer_text": "\n".join(parts),
        "answer_mode": "template",
        "matched_entity_type": "event",
        "matched_entity_id": event["id"],
        "confidence_level": "high",
        "source_records": sources,
        "needs_verification": False,
    }


def build_event_list_answer(events: list[dict[str, Any]]) -> dict[str, Any]:
    lines = ["我先帮你整理几条相关活动，按匹配度从高到低排好了："]
    sources = []

    for index, event in enumerate(events, start=1):
        data = event["data"]
        lines.append(
            f"{index}. {data.get('event_name', event['title'])} | 时间：{data.get('time', '待更新')} | 地点：{data.get('location', '待更新')} | 负责人：{data.get('owner', '待更新')}"
        )
        sources.append(source_record(event, ["event_name", "time", "location", "owner", "intro_text"]))

    lines.append("如果你想继续缩小范围，可以继续问我“哪个最适合新手”或者“哪一个在最近举办”。")
    return {
        "answer_text": "\n".join(lines),
        "answer_mode": "template",
        "matched_entity_type": "event",
        "matched_entity_id": None,
        "confidence_level": "high",
        "source_records": sources,
        "needs_verification": False,
    }


def build_ranked_event_list_answer(ranked_events: list[tuple[dict[str, Any], int]]) -> dict[str, Any]:
    lines = ["我先把当前可用的活动按相关度整理给你："]
    sources = []

    for index, (event, _score) in enumerate(ranked_events[:5], start=1):
        data = event["data"]
        lines.append(
            f"{index}. {data.get('event_name', event['title'])} | 时间：{data.get('time', '待更新')} | 地点：{data.get('location', '待更新')} | 负责人：{data.get('owner', '待更新')}"
        )
        sources.append(source_record(event, ["event_name", "time", "location", "owner", "intro_text"]))

    lines.append("如果你想继续缩小范围，可以继续问我“最近的活动有哪些”或者“哪一个最好玩”。")
    return {
        "answer_text": "\n".join(lines),
        "answer_mode": "template",
        "matched_entity_type": "event",
        "matched_entity_id": None,
        "confidence_level": "high",
        "source_records": sources,
        "needs_verification": False,
    }


def build_contact_answer(contact: dict[str, Any]) -> dict[str, Any]:
    data = contact["data"]
    return {
        "answer_text": "\n".join(
            [
                f"目前可联系的负责人是：{data.get('contact_name', '待更新')}。",
                f"身份：{data.get('role', '待更新')}",
                f"联系方式：{data.get('channel', '待更新')} {data.get('contact_value', '')}".strip(),
                f"可联系时段：{data.get('available_time', '待更新')}",
            ]
        ),
        "answer_mode": "template",
        "matched_entity_type": "contact",
        "matched_entity_id": contact["id"],
        "confidence_level": "high",
        "source_records": [source_record(contact, ["contact_name", "role", "channel", "contact_value", "available_time"])],
        "needs_verification": False,
    }


def build_department_answer(department: dict[str, Any]) -> dict[str, Any]:
    data = department["data"]
    lines = [
        f"这个部门是：{data.get('department_name', department['title'])}。",
        f"负责人：{data.get('manager', '待更新')}",
        f"主要职责：{'、'.join(data.get('responsibilities', [])) or '待更新'}",
    ]
    if data.get("intro"):
        lines.append(f"补充介绍：{data['intro']}")
    return {
        "answer_text": "\n".join(lines),
        "answer_mode": "template",
        "matched_entity_type": "department",
        "matched_entity_id": department["id"],
        "confidence_level": "medium",
        "source_records": [source_record(department, ["department_name", "manager", "responsibilities", "intro"])],
        "needs_verification": False,
    }


def build_faq_answer(faq: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer_text": faq["data"].get("answer", ""),
        "answer_mode": "template",
        "matched_entity_type": "faq_entry",
        "matched_entity_id": faq["id"],
        "confidence_level": "high",
        "source_records": [source_record(faq, ["question", "aliases", "answer"])],
        "needs_verification": False,
    }


def build_policy_answer(policy: dict[str, Any]) -> dict[str, Any]:
    data = policy["data"]
    lines = [
        f"我先根据已发布制度给你一个保守答复：{data.get('summary', '当前暂无更多制度说明。')}",
    ]
    if data.get("details"):
        lines.append(f"补充说明：{data['details']}")
    lines.append("如果你遇到的是特殊情况，建议再联系管理员确认。")
    return {
        "answer_text": "\n".join(lines),
        "answer_mode": "hybrid",
        "matched_entity_type": "policy_article",
        "matched_entity_id": policy["id"],
        "confidence_level": "medium",
        "source_records": [source_record(policy, ["summary", "details"])],
        "needs_verification": True,
    }


def build_fallback(reason: str) -> dict[str, Any]:
    return {
        "answer_text": "我暂时没在已发布的社团资料里查到足够明确的信息。为了避免误答，建议你联系管理员再确认一下最新安排。",
        "answer_mode": "template",
        "matched_entity_type": None,
        "matched_entity_id": None,
        "confidence_level": "low",
        "source_records": [],
        "needs_verification": True,
        "unmatched_reason": reason,
    }


def build_general_answer(answer_text: str, confidence_level: str = "high") -> dict[str, Any]:
    return {
        "answer_text": answer_text,
        "answer_mode": "general",
        "matched_entity_type": None,
        "matched_entity_id": None,
        "confidence_level": confidence_level,
        "source_records": [],
        "needs_verification": False,
    }


def answer_for_entity_type(entity_type: str, entity: dict[str, Any], signup_rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    if entity_type == "faq_entry":
        return build_faq_answer(entity)
    if entity_type == "contact":
        return build_contact_answer(entity)
    if entity_type == "department":
        return build_department_answer(entity)
    if entity_type == "policy_article":
        return build_policy_answer(entity)
    if entity_type == "event":
        signup_rule = next((item for item in signup_rules if item["data"].get("target_event_slug") == entity["slug"]), None)
        signup_rule = signup_rule or (signup_rules[0] if signup_rules else None)
        return build_event_answer(entity, signup_rule)
    if entity_type == "club_profile":
        return {
            "answer_text": "\n".join(
                [
                    f"社团名称：{entity['data'].get('club_name', entity['title'])}",
                    f"社团使命：{entity['data'].get('mission', '待更新')}",
                    f"社团介绍：{entity['data'].get('intro', '待更新')}",
                    f"常驻地点：{entity['data'].get('base_location', '待更新')}",
                ]
            ),
            "answer_mode": "template",
            "matched_entity_type": "club_profile",
            "matched_entity_id": entity["id"],
            "confidence_level": "high",
            "source_records": [source_record(entity, ["club_name", "mission", "intro", "base_location"])],
            "needs_verification": False,
        }
    return None


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def includes_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def asks_multi_entity_result(question: str) -> bool:
    normalized = normalize_text(question)
    return includes_any(
        normalized,
        ["有什么", "有哪些", "哪些", "推荐", "好玩的", "活动推荐", "列一下", "都有哪些", "有什么活动"],
    )


def asks_broad_event_overview(question: str, intent: dict[str, Any] | None = None) -> bool:
    normalized = normalize_text(question)
    if intent and intent.get("entity_type") == "event" and intent.get("intent") == "lookup_overview":
        return True
    return includes_any(normalized, ["有什么活动", "有哪些活动", "最近有什么活动", "都有什么活动", "活动有哪些"])


def rank_entities_from_context(question: str, entities: list[dict[str, Any]]) -> list[tuple[dict[str, Any], float]]:
    if not entities:
        return []
    return rank_entities(question, entities)


def entity_evidence(entity: dict[str, Any]) -> str:
    values: list[str] = [entity["title"]]
    for value in entity["data"].values():
        if isinstance(value, list):
            values.extend(str(item) for item in value if item)
        elif value not in (None, ""):
            values.append(str(value))
    return " | ".join(values)


def lexical_score(query: str, entity: dict[str, Any]) -> float:
    normalized_query = normalize_text(query)
    evidence = normalize_text(entity_evidence(entity))
    if not normalized_query or not evidence:
        return 0.0

    score = 0.0
    if normalized_query in evidence:
        score += 0.65

    terms = [term for term in re.split(r"[，。？！、\s,.;:!?]+", query) if term]
    for chinese_text in re.findall(r"[\u4e00-\u9fff]{2,}", query):
        terms.append(chinese_text)
        for size in (2, 3, 4):
            terms.extend(chinese_text[index : index + size] for index in range(0, max(len(chinese_text) - size + 1, 0)))
    unique_terms = {normalize_text(term) for term in terms if normalize_text(term)}
    if unique_terms:
        hits = sum(1 for term in unique_terms if term in evidence)
        score += min(0.55, hits / max(len(unique_terms), 1))

    return min(score, 1.0)


def rank_entities(question: str, entities: list[dict[str, Any]]) -> list[tuple[dict[str, Any], float]]:
    ranked = semantic_rank_entities(question, entities)
    if ranked:
        return ranked

    lexical_ranked = [(entity, lexical_score(question, entity)) for entity in entities]
    lexical_ranked = [(entity, score) for entity, score in lexical_ranked if score > 0]
    lexical_ranked.sort(key=lambda item: item[1], reverse=True)
    return lexical_ranked


def retrieve_ranked_entities(
    entity_type: str,
    question: str,
    filters: dict[str, Any],
    entities_by_type: dict[str, list[dict[str, Any]]],
) -> list[tuple[dict[str, Any], float]]:
    filter_text = " ".join(str(value) for value in filters.values() if value)
    query = " ".join(part for part in [question, filter_text] if part).strip()
    return rank_entities(query, entities_by_type.get(entity_type, []))


def parse_event_datetime(event: dict[str, Any]) -> datetime | None:
    raw_time = str(event["data"].get("time") or "")
    match = re.search(r"(\d{4})[-./年](\d{1,2})[-./月](\d{1,2})", raw_time)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def sort_events_for_overview(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    def sort_key(event: dict[str, Any]) -> tuple[int, int, str]:
        event_dt = parse_event_datetime(event)
        if not event_dt:
            return (2, 0, event["title"])
        delta_days = (event_dt - today).days
        if delta_days >= 0:
            return (0, delta_days, event["title"])
        return (1, -delta_days, event["title"])

    return sorted(events, key=sort_key)


def build_conversation_context(session_id: str) -> str | None:
    recent_logs = list_chat_logs_for_session(session_id, limit=5)
    if not recent_logs:
        return None

    lines = []
    for log in reversed(recent_logs):
        lines.append(f"用户：{log['question']}")
        lines.append(f"助手：{log['answer_text']}")
    return "\n".join(lines)


def candidate_record(entity: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "entity_id": entity["id"],
        "entity_type": entity["entity_type"],
        "title": entity["title"],
        "semantic_score": float(score),
        "evidence": entity_evidence(entity),
    }


def selected_entities_from_judge(
    judge: dict[str, Any],
    ranked_entities: list[tuple[dict[str, Any], float]],
) -> list[dict[str, Any]]:
    selected_ids = []
    for item in judge.get("selected_entity_ids", []):
        try:
            selected_ids.append(int(item))
        except (TypeError, ValueError):
            continue

    entities_by_id = {entity["id"]: entity for entity, _score in ranked_entities}
    return [entities_by_id[entity_id] for entity_id in selected_ids if entity_id in entities_by_id]


def build_answer_from_selected(
    decision: str,
    selected_entities: list[dict[str, Any]],
    signup_rules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not selected_entities:
        return None

    if decision == "list":
        if all(entity["entity_type"] == "event" for entity in selected_entities):
            return build_event_list_answer(selected_entities)

        lines = ["我先把相关信息整理给你："]
        sources = []
        for index, entity in enumerate(selected_entities, start=1):
            lines.append(f"{index}. {entity['title']}")
            sources.append(source_record(entity, list(entity["data"].keys())))
        return {
            "answer_text": "\n".join(lines),
            "answer_mode": "template",
            "matched_entity_type": selected_entities[0]["entity_type"],
            "matched_entity_id": None,
            "confidence_level": "high",
            "source_records": sources,
            "needs_verification": False,
        }

    return answer_for_entity_type(selected_entities[0]["entity_type"], selected_entities[0], signup_rules)


def maybe_apply_grounded_answer(
    question: str,
    answer: dict[str, Any],
    decision: str,
    selected_entities: list[dict[str, Any]],
    conversation_context: str | None,
) -> dict[str, Any]:
    if not selected_entities or answer["answer_mode"] != "hybrid":
        return answer

    selected_records = [
        {
            "entity_id": entity["id"],
            "entity_type": entity["entity_type"],
            "title": entity["title"],
            "data": entity["data"],
        }
        for entity in selected_entities
    ]
    grounded_text = generate_grounded_answer(question, decision, selected_records, conversation_context)
    if grounded_text:
        answer["answer_text"] = grounded_text
        answer["answer_mode"] = "grounded"
    return answer


def maybe_answer_from_session_context(
    question: str,
    session_id: str,
    entities_by_type: dict[str, list[dict[str, Any]]],
    signup_rules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    recent_logs = list_chat_logs_for_session(session_id, limit=5)
    if not recent_logs:
        return None

    for log in recent_logs:
        source_records = log.get("source_records") or []
        if not source_records:
            continue

        grouped_ids: dict[str, set[int]] = {}
        for source in source_records:
            entity_type = source.get("entity_type")
            entity_id = source.get("entity_id")
            if not entity_type or entity_id is None:
                continue
            grouped_ids.setdefault(str(entity_type), set()).add(int(entity_id))

        for entity_type, entity_ids in grouped_ids.items():
            candidates = [entity for entity in entities_by_type.get(entity_type, []) if entity["id"] in entity_ids]
            ranked = rank_entities_from_context(question, candidates)
            if not ranked:
                continue

            top_entity, top_score = ranked[0]
            if top_score < 0.42:
                continue

            second_score = ranked[1][1] if len(ranked) > 1 else 0.0
            if len(ranked) > 1 and top_score - second_score < 0.08:
                continue

            if entity_type == "event" and asks_broad_event_overview(question):
                return build_ranked_event_list_answer(ranked)

            answer = answer_for_entity_type(entity_type, top_entity, signup_rules)
            if not answer:
                continue

            if top_score < 0.55:
                answer["confidence_level"] = "medium" if answer["confidence_level"] == "high" else answer["confidence_level"]
                answer["needs_verification"] = True
            return answer

    return None


def find_by_llm_intent(
    question: str,
    intent: dict[str, Any],
    entities_by_type: dict[str, list[dict[str, Any]]],
    signup_rules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    query_terms = intent["query_terms"] or [question]
    filters = intent["filters"] or {}
    query_text = " ".join([question, *query_terms, *filters.values()]).strip()
    ranked = retrieve_ranked_entities(intent["entity_type"], query_text, filters, entities_by_type)
    if not ranked:
        return None

    if intent["entity_type"] == "event" and asks_broad_event_overview(question, intent):
        return build_ranked_event_list_answer(ranked)

    threshold = max(0.38, ranked[0][1] * 0.78)
    above_threshold = [entity for entity, score in ranked if score >= threshold][:5]
    best, best_score = ranked[0]
    if not best or best_score <= 0:
        return None

    if (
        intent["entity_type"] == "event"
        and len(above_threshold) > 1
        and (intent.get("intent") in {"lookup_overview", "lookup_general"} or asks_multi_entity_result(question))
    ):
        return build_event_list_answer(above_threshold)

    answer = answer_for_entity_type(intent["entity_type"], best, signup_rules)
    if not answer:
        return None

    if intent["confidence"] == "low":
        answer["confidence_level"] = "medium" if answer["confidence_level"] == "high" else answer["confidence_level"]
        answer["needs_verification"] = True

    return answer


def find_by_generic_fallback(
    question: str,
    entities_by_type: dict[str, list[dict[str, Any]]],
    signup_rules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    scored_candidates: dict[str, list[tuple[dict[str, Any], float]]] = {}

    for entity_type, candidates in entities_by_type.items():
        if not candidates:
            continue
        ranked = retrieve_ranked_entities(entity_type, question, {}, entities_by_type)
        scored_candidates[entity_type] = ranked

    if asks_broad_event_overview(question):
        event_ranked = scored_candidates.get("event", [])
        if event_ranked:
            return build_ranked_event_list_answer(event_ranked)

    best_entity = None
    best_entity_type = None
    best_score = 0.0
    for entity_type, ranked in scored_candidates.items():
        if not ranked:
            continue
        entity, score = ranked[0]
        if score > best_score:
            best_entity = entity
            best_entity_type = entity_type
            best_score = score

    if not best_entity or not best_entity_type or best_score < 0.32:
        return None

    answer = answer_for_entity_type(best_entity_type, best_entity, signup_rules)
    if answer:
        if best_score >= 0.55:
            answer["confidence_level"] = "high"
            answer["needs_verification"] = False
        else:
            answer["confidence_level"] = "medium" if answer["confidence_level"] == "high" else answer["confidence_level"]
            answer["needs_verification"] = True
    return answer


def maybe_enhance_with_model(question: str, answer: dict[str, Any]) -> dict[str, Any]:
    return answer


def answer_question(question: str, session_id: str) -> dict[str, Any]:
    events = get_published_entities("event")
    signup_rules = get_published_entities("signup_rule")
    contacts = get_published_entities("contact")
    departments = get_published_entities("department")
    faqs = get_published_entities("faq_entry")
    policies = get_published_entities("policy_article")
    club_profiles = get_published_entities("club_profile")

    entities_by_type = {
        "event": events,
        "signup_rule": signup_rules,
        "contact": contacts,
        "department": departments,
        "faq_entry": faqs,
        "policy_article": policies,
        "club_profile": club_profiles,
    }

    conversation_context = build_conversation_context(session_id)
    plan = plan_turn(question, conversation_context) or {
        "mode": "retrieve",
        "target_entity_types": list(ALLOWED_ENTITY_TYPES),
        "query_rewrite": question,
        "need_list": asks_multi_entity_result(question),
        "need_detail": False,
        "response_style": "normal",
        "confidence": "low",
        "direct_reply": "",
    }
    debug_trace: dict[str, Any] = {"plan": plan, "semantic_candidates": []}

    if plan.get("mode") == "chat":
        reply = plan.get("direct_reply") or generate_general_reply(question, conversation_context)
        answer = build_general_answer(reply or "我在。你可以继续说具体一点，我再接着帮你。")
        debug_trace["selected_path"] = "chat"
        answer["debug_trace"] = debug_trace
        insert_chat_log({"session_id": session_id, "question": question, **answer})
        return answer

    target_entity_types = [
        entity_type
        for entity_type in (plan.get("target_entity_types") or ALLOWED_ENTITY_TYPES)
        if entity_type in entities_by_type
    ] or list(ALLOWED_ENTITY_TYPES)

    ranked_entities: list[tuple[dict[str, Any], float]] = []
    for entity_type in target_entity_types:
        ranked = rank_entities(plan.get("query_rewrite") or question, entities_by_type.get(entity_type, []))
        if entity_type == "event" and asks_broad_event_overview(question):
            scores_by_id = {entity["id"]: score for entity, score in ranked}
            ranked = [(event, scores_by_id.get(event["id"], 0.2)) for event in sort_events_for_overview(entities_by_type.get("event", []))]
        ranked_entities.extend(ranked[:5])
    if not asks_broad_event_overview(question):
        ranked_entities.sort(key=lambda item: item[1], reverse=True)
    ranked_entities = ranked_entities[:8]

    candidates = [candidate_record(entity, score) for entity, score in ranked_entities]
    debug_trace["semantic_candidates"] = candidates

    judge = (
        judge_candidates(question, conversation_context, candidates)
        if candidates
        else {
            "status": "ok",
            "decision": "no_answer",
            "selected_entity_ids": [],
            "confidence": "low",
            "reason": "no_candidates",
            "direct_reply": "",
        }
    )
    debug_trace["judge"] = judge

    answer: dict[str, Any] | None = None
    selected_entities: list[dict[str, Any]] = []
    decision = judge.get("decision", "no_answer")

    if judge.get("status") == "failed" and candidates and (plan.get("need_list") or asks_broad_event_overview(question)):
        top_entity_type = ranked_entities[0][0]["entity_type"]
        same_type_entities = [entity for entity, _score in ranked_entities if entity["entity_type"] == top_entity_type]
        selected_entities = same_type_entities[:5]
        answer = build_answer_from_selected("list", selected_entities, signup_rules)
        debug_trace["selected_path"] = "judge_failed_list"
    elif judge.get("status") == "failed" and ranked_entities:
        selected_entities = [ranked_entities[0][0]]
        answer = build_answer_from_selected("single", selected_entities, signup_rules)
        debug_trace["selected_path"] = "judge_failed_single"
    elif decision == "chat":
        reply = judge.get("direct_reply") or generate_general_reply(question, conversation_context)
        answer = build_general_answer(reply or "这个问题我可以陪你聊，但不能假装它来自社团资料。")
        debug_trace["selected_path"] = "judge_chat"
    elif decision in {"single", "list"}:
        selected_entities = selected_entities_from_judge(judge, ranked_entities)
        if not selected_entities and ranked_entities and decision == "single":
            selected_entities = [ranked_entities[0][0]]
        answer = build_answer_from_selected(decision, selected_entities, signup_rules)
        debug_trace["selected_path"] = f"judge_{decision}" if answer else "judge_no_selected"

    if not answer:
        answer = build_fallback("no_clear_match")
        insert_unmatched_question({"session_id": session_id, "question": question, "reason": answer["unmatched_reason"]})
        debug_trace["selected_path"] = debug_trace.get("selected_path") or "fallback"

    final_answer = maybe_apply_grounded_answer(question, answer, decision, selected_entities, conversation_context)
    final_answer = maybe_enhance_with_model(question, final_answer)
    final_answer["debug_trace"] = debug_trace
    insert_chat_log({"session_id": session_id, "question": question, **final_answer})
    return final_answer
