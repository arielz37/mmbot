from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections import OrderedDict
from typing import Any

from .config import (
    embedding_configured,
    get_embedding_api_key,
    get_embedding_base_url,
    get_embedding_model,
    get_model_api_key,
    get_model_base_url,
    get_model_name,
    get_model_timeout_ms,
    model_configured,
)


PLAN_CACHE: OrderedDict[str, dict[str, Any] | None] = OrderedDict()
PLAN_CACHE_SIZE = 128
JUDGE_CACHE: OrderedDict[str, dict[str, Any] | None] = OrderedDict()
JUDGE_CACHE_SIZE = 128
CHAT_CACHE: OrderedDict[str, str | None] = OrderedDict()
CHAT_CACHE_SIZE = 128
GROUNDED_CACHE: OrderedDict[str, str | None] = OrderedDict()
GROUNDED_CACHE_SIZE = 128

ALLOWED_ENTITY_TYPES = {"event", "signup_rule", "department", "contact", "faq_entry", "policy_article", "club_profile"}


def _post_chat_completion(messages: list[dict[str, str]], temperature: float = 0.2) -> dict[str, Any] | None:
    if not model_configured():
        return None

    payload = {
        "model": get_model_name(),
        "temperature": temperature,
        "messages": messages,
    }

    request = urllib.request.Request(
        url=f"{get_model_base_url().rstrip('/')}/chat/completions",
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {get_model_api_key()}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=get_model_timeout_ms() / 1000) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def _extract_content(response: dict[str, Any] | None) -> str | None:
    if not response:
        return None
    return response.get("choices", [{}])[0].get("message", {}).get("content", "").strip() or None


def _extract_json_object(content: str | None) -> dict[str, Any] | None:
    if not content:
        return None
    try:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1:
            return None
        return json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None


def get_text_embedding(text: str) -> list[float] | None:
    if not embedding_configured():
        return None

    payload = {
        "model": get_embedding_model(),
        "input": text,
    }

    request = urllib.request.Request(
        url=f"{get_embedding_base_url().rstrip('/')}/embeddings",
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {get_embedding_api_key()}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=get_model_timeout_ms() / 1000) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    embedding = body.get("data", [{}])[0].get("embedding")
    if not isinstance(embedding, list):
        return None
    try:
        return [float(item) for item in embedding]
    except (TypeError, ValueError):
        return None


def build_plan_turn_prompt() -> str:
    return (
        "你是社团 AI 助手的回合规划器。"
        "你不直接回答用户，而是先决定这一轮应该走“知识检索”还是“日常聊天”。"
        "请充分使用上下文理解用户意图，但只能输出 JSON，不能输出解释。"
        "如果用户是在寒暄、闲聊、表达情绪、寻求泛建议、开放式讨论，就设 mode=chat。"
        "如果用户是在问社团事实、活动、联系人、报名、规则、部门、地点、时间、制度、社团介绍等可验证信息，就设 mode=retrieve。"
        "当 mode=retrieve 时，你需要给出 target_entity_types 和一个更适合语义检索的 query_rewrite。"
        "当 mode=chat 时，可以直接给出 direct_reply。"
        "允许的 target_entity_types 只有：event, signup_rule, department, contact, faq_entry, policy_article, club_profile。"
        "JSON 结构固定为："
        '{"mode":"retrieve","target_entity_types":["event"],"query_rewrite":"最近的活动有哪些","need_list":true,"need_detail":false,"response_style":"normal","confidence":"high","direct_reply":""}'
    )


def build_candidate_judge_prompt() -> str:
    return (
        "你是社团 AI 助手的候选证据裁决器。"
        "你会收到用户问题、最近上下文和一组已经通过语义检索召回的候选记录。"
        "你的任务不是编造事实，而是在候选证据里判断：应该返回单条、返回列表、转为聊天回复，还是明确表示证据不足。"
        "请尽量依赖上下文和用户真实意图，不要机械地只看第一名。"
        "如果用户问的是多个活动/多个事项的概览，decision=list。"
        "如果用户问的是某一条具体信息，decision=single。"
        "如果这些候选都不够支持回答，decision=no_answer。"
        "如果问题其实更像闲聊或建议，decision=chat，并给 direct_reply。"
        "只能输出 JSON，不能输出解释。"
        "JSON 结构固定为："
        '{"decision":"single","selected_entity_ids":[12],"confidence":"high","reason":"用户在追问一条活动详情","direct_reply":""}'
    )


def build_general_chat_prompt() -> str:
    return (
        "你是社团里的学长学姐型 AI 助手，语气亲切、自然、可靠。"
        "当前问题不需要检索知识库，而是更像日常聊天、鼓励、建议或陪伴。"
        "请直接回复用户，尽量简洁真诚，不要说教，不要过度输出。"
        "不要假装知道数据库里没有提供的社团事实，不要编造活动、负责人、时间地点或内部安排。"
        "如果问题需要精确信息才能答准，可以自然地建议用户再具体问一下。"
    )


def build_grounded_answer_prompt() -> str:
    return (
        "你是社团 AI 助手的受证据约束回答器。"
        "你会收到用户问题和已经选定的知识记录。"
        "你只能基于提供的记录回答，不能编造任何未提供的事实。"
        "时间、地点、费用、负责人、报名方式、联系方式、制度内容等关键信息只能来自记录本身。"
        "如果是列表回答，请自然整理成清晰列表。"
        "如果是单条回答，请优先直接回答用户问的点，再补充必要背景。"
        "只输出最终给用户的话，不要输出分析，不要引用 JSON 字段名。"
    )


def plan_turn(question: str, conversation_context: str | None = None) -> dict[str, Any] | None:
    cache_key = f"{question.strip()}||{(conversation_context or '').strip()}"
    if cache_key in PLAN_CACHE:
        cached = PLAN_CACHE.pop(cache_key)
        PLAN_CACHE[cache_key] = cached
        return cached

    user_parts = []
    if conversation_context:
        user_parts.append(f"最近几轮对话上下文：\n{conversation_context}")
    user_parts.append(f"用户问题：{question}")
    user_parts.append("请输出这一轮的规划 JSON。")

    response = _post_chat_completion(
        [
            {"role": "system", "content": build_plan_turn_prompt()},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ],
        temperature=0,
    )
    payload = _extract_json_object(_extract_content(response))
    if not payload:
        _store_cache(PLAN_CACHE, PLAN_CACHE_SIZE, cache_key, None)
        return None

    mode = payload.get("mode")
    if mode not in {"retrieve", "chat"}:
        mode = "chat"

    target_entity_types = payload.get("target_entity_types") or []
    if not isinstance(target_entity_types, list):
        target_entity_types = []
    target_entity_types = [entity_type for entity_type in (str(item).strip() for item in target_entity_types) if entity_type in ALLOWED_ENTITY_TYPES]

    query_rewrite = str(payload.get("query_rewrite") or "").strip() or question.strip()
    response_style = str(payload.get("response_style") or "normal").strip()
    if response_style not in {"brief", "normal"}:
        response_style = "normal"
    confidence = str(payload.get("confidence") or "low").strip()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    direct_reply = str(payload.get("direct_reply") or "").strip()
    if mode == "retrieve":
        direct_reply = ""

    parsed = {
        "mode": mode,
        "target_entity_types": target_entity_types,
        "query_rewrite": query_rewrite,
        "need_list": bool(payload.get("need_list")),
        "need_detail": bool(payload.get("need_detail")),
        "response_style": response_style,
        "confidence": confidence,
        "direct_reply": direct_reply,
    }
    _store_cache(PLAN_CACHE, PLAN_CACHE_SIZE, cache_key, parsed)
    return parsed


def judge_candidates(
    question: str,
    conversation_context: str | None,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_lines = []
    for item in candidates:
        candidate_lines.append(
            json.dumps(
                {
                    "entity_id": item["entity_id"],
                    "entity_type": item["entity_type"],
                    "title": item["title"],
                    "semantic_score": round(float(item.get("semantic_score", 0.0)), 4),
                    "evidence": item.get("evidence", ""),
                },
                ensure_ascii=False,
            )
        )

    cache_key = f"{question.strip()}||{(conversation_context or '').strip()}||{'||'.join(candidate_lines)}"
    if cache_key in JUDGE_CACHE:
        cached = JUDGE_CACHE.pop(cache_key)
        JUDGE_CACHE[cache_key] = cached
        return cached

    user_parts = []
    if conversation_context:
        user_parts.append(f"最近几轮对话上下文：\n{conversation_context}")
    user_parts.append(f"用户问题：{question}")
    user_parts.append("候选记录如下，每行一条 JSON：")
    user_parts.extend(candidate_lines)
    user_parts.append("请输出裁决 JSON。")

    base_messages = [
        {"role": "system", "content": build_candidate_judge_prompt()},
        {"role": "user", "content": "\n".join(user_parts)},
    ]
    response = _post_chat_completion(base_messages, temperature=0)
    raw_content = _extract_content(response)
    payload = _extract_json_object(raw_content)
    retry_raw_content = None

    if not payload:
        retry_messages = [
            {"role": "system", "content": build_candidate_judge_prompt()},
            {
                "role": "user",
                "content": "\n".join(
                    user_parts
                    + [
                        "",
                        "你刚才的输出不是合法 JSON。请严格只输出一个合法 JSON 对象，不要带代码块、解释或额外文字。",
                    ]
                ),
            },
        ]
        retry_response = _post_chat_completion(retry_messages, temperature=0)
        retry_raw_content = _extract_content(retry_response)
        payload = _extract_json_object(retry_raw_content)

    if not payload:
        return {
            "status": "failed",
            "decision": "no_answer",
            "selected_entity_ids": [],
            "confidence": "low",
            "reason": "judge_output_invalid",
            "direct_reply": "",
            "raw_content": raw_content,
            "retry_raw_content": retry_raw_content,
        }

    decision = payload.get("decision")
    if decision not in {"single", "list", "chat", "no_answer"}:
        decision = "no_answer"

    raw_ids = payload.get("selected_entity_ids") or []
    if not isinstance(raw_ids, list):
        raw_ids = []
    selected_entity_ids: list[int] = []
    for item in raw_ids:
        try:
            selected_entity_ids.append(int(item))
        except (TypeError, ValueError):
            continue

    confidence = str(payload.get("confidence") or "low").strip()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"

    parsed = {
        "status": "ok",
        "decision": decision,
        "selected_entity_ids": selected_entity_ids,
        "confidence": confidence,
        "reason": str(payload.get("reason") or "").strip(),
        "direct_reply": str(payload.get("direct_reply") or "").strip(),
        "raw_content": raw_content,
        "retry_raw_content": retry_raw_content,
    }
    _store_cache(JUDGE_CACHE, JUDGE_CACHE_SIZE, cache_key, parsed)
    return parsed


def generate_general_reply(question: str, conversation_context: str | None = None) -> str | None:
    cache_key = f"{question.strip()}||{(conversation_context or '').strip()}"
    if cache_key in CHAT_CACHE:
        cached = CHAT_CACHE.pop(cache_key)
        CHAT_CACHE[cache_key] = cached
        return cached

    user_parts = []
    if conversation_context:
        user_parts.append(f"最近几轮对话上下文：\n{conversation_context}")
    user_parts.append(f"用户问题：{question}")
    user_parts.append("请直接回复用户。")

    response = _post_chat_completion(
        [
            {"role": "system", "content": build_general_chat_prompt()},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ],
        temperature=0.5,
    )
    content = _extract_content(response)
    _store_cache(CHAT_CACHE, CHAT_CACHE_SIZE, cache_key, content)
    return content


def generate_grounded_answer(
    question: str,
    decision: str,
    selected_records: list[dict[str, Any]],
    conversation_context: str | None = None,
) -> str | None:
    payload = {
        "decision": decision,
        "records": selected_records,
    }
    cache_key = f"{question.strip()}||{(conversation_context or '').strip()}||{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    if cache_key in GROUNDED_CACHE:
        cached = GROUNDED_CACHE.pop(cache_key)
        GROUNDED_CACHE[cache_key] = cached
        return cached

    user_parts = []
    if conversation_context:
        user_parts.append(f"最近几轮对话上下文：\n{conversation_context}")
    user_parts.append(f"用户问题：{question}")
    user_parts.append("已选定记录：")
    user_parts.append(json.dumps(payload, ensure_ascii=False, indent=2))
    user_parts.append("请基于这些记录给出最终回答。")

    response = _post_chat_completion(
        [
            {"role": "system", "content": build_grounded_answer_prompt()},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ],
        temperature=0.2,
    )
    content = _extract_content(response)
    _store_cache(GROUNDED_CACHE, GROUNDED_CACHE_SIZE, cache_key, content)
    return content


def _store_cache(cache: OrderedDict[str, Any], limit: int, key: str, value: Any) -> None:
    cache[key] = value
    while len(cache) > limit:
        cache.popitem(last=False)
