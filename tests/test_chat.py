from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ChatFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.TemporaryDirectory()
        os.environ["APP_DB_PATH"] = str(Path(cls.tmpdir.name) / "test.sqlite")

        from app.db import initialize_db
        from app.repository import reset_all_data, seed_demo_data

        initialize_db()
        reset_all_data()
        seed_demo_data()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmpdir.cleanup()
        os.environ.pop("APP_DB_PATH", None)

    def setUp(self) -> None:
        from app.repository import reset_all_data, seed_demo_data

        reset_all_data()
        seed_demo_data()

    def test_chat_mode_skips_semantic_retrieval(self) -> None:
        from app.chat import answer_question

        with patch(
            "app.chat.plan_turn",
            return_value={
                "mode": "chat",
                "target_entity_types": [],
                "query_rewrite": "你好呀",
                "need_list": False,
                "need_detail": False,
                "response_style": "normal",
                "confidence": "high",
                "direct_reply": "你好呀！今天想聊点什么？",
            },
        ), patch("app.chat.semantic_rank_entities") as semantic_mock:
            result = answer_question("你好呀", "test-general-chat")

        self.assertEqual(result["answer_mode"], "general")
        self.assertIn("你好呀", result["answer_text"])
        semantic_mock.assert_not_called()

    def test_planned_type_limits_semantic_recall_scope(self) -> None:
        from app.chat import answer_question
        from app.repository import create_entity

        event = create_entity(
            {
                "entity_type": "event",
                "slug": "recruitment",
                "title": "春季招新",
                "status": "published",
                "updated_by": "tester",
                "data": {
                    "event_name": "春季招新宣讲会",
                    "time": "2026-05-01 19:00",
                    "location": "图书馆 B201",
                    "signup_method": "小程序报名",
                    "audience": "全校同学",
                    "fee": "免费",
                    "owner": "李同学",
                },
            }
        )

        def fake_rank(_query: str, entities: list[dict]) -> list[tuple[dict, float]]:
            for entity in entities:
                self.assertEqual(entity["entity_type"], "event")
            return [(event, 0.91)]

        with patch(
            "app.chat.plan_turn",
            return_value={
                "mode": "retrieve",
                "target_entity_types": ["event"],
                "query_rewrite": "最近的招新活动",
                "need_list": False,
                "need_detail": True,
                "response_style": "normal",
                "confidence": "high",
                "direct_reply": "",
            },
        ), patch("app.chat.semantic_rank_entities", side_effect=fake_rank), patch(
            "app.chat.judge_candidates",
            return_value={"status": "ok", "decision": "single", "selected_entity_ids": [event["id"]], "confidence": "high", "reason": "命中活动", "direct_reply": ""},
        ), patch("app.chat.generate_grounded_answer", return_value=None):
            result = answer_question("最近那个招新活动在哪，负责人是谁？", "test-event")

        self.assertEqual(result["matched_entity_type"], "event")
        self.assertIn("图书馆 B201", result["answer_text"])
        self.assertIn("李同学", result["answer_text"])

    def test_judge_candidates_can_override_top_semantic_hit(self) -> None:
        from app.chat import answer_question
        from app.repository import create_entity

        rehearsal = create_entity(
            {
                "entity_type": "event",
                "slug": "rehearsal",
                "title": "模拟彩排",
                "status": "published",
                "updated_by": "tester",
                "data": {"event_name": "模拟彩排", "time": "2026-04-20", "location": "music room", "owner": "Kai"},
            }
        )
        performance = create_entity(
            {
                "entity_type": "event",
                "slug": "live-show",
                "title": "Livehouse演出",
                "status": "published",
                "updated_by": "tester",
                "data": {"event_name": "Livehouse演出", "time": "2026-05-01", "location": "Babylon", "owner": "James"},
            }
        )

        with patch(
            "app.chat.plan_turn",
            return_value={
                "mode": "retrieve",
                "target_entity_types": ["event"],
                "query_rewrite": "演出的细节",
                "need_list": False,
                "need_detail": True,
                "response_style": "normal",
                "confidence": "high",
                "direct_reply": "",
            },
        ), patch(
            "app.chat.semantic_rank_entities",
            return_value=[(rehearsal, 0.91), (performance, 0.88)],
        ), patch(
            "app.chat.judge_candidates",
            return_value={"status": "ok", "decision": "single", "selected_entity_ids": [performance["id"]], "confidence": "high", "reason": "用户在问演出不是彩排", "direct_reply": ""},
        ), patch("app.chat.generate_grounded_answer", return_value=None):
            result = answer_question("演出是什么时候", "test-rerank")

        self.assertEqual(result["matched_entity_id"], performance["id"])
        self.assertIn("Babylon", result["answer_text"])
        self.assertNotIn("music room", result["answer_text"])

    def test_list_decision_returns_multiple_events(self) -> None:
        from app.chat import answer_question
        from app.repository import create_entity

        event_one = create_entity(
            {
                "entity_type": "event",
                "slug": "live-show",
                "title": "Live 演出",
                "status": "published",
                "updated_by": "tester",
                "data": {"event_name": "Live 演出", "time": "2026-05-01", "location": "Babylon", "owner": "James"},
            }
        )
        event_two = create_entity(
            {
                "entity_type": "event",
                "slug": "rehearsal",
                "title": "模拟彩排",
                "status": "published",
                "updated_by": "tester",
                "data": {"event_name": "模拟彩排", "time": "2026-04-20", "location": "music room", "owner": "Kai"},
            }
        )

        with patch(
            "app.chat.plan_turn",
            return_value={
                "mode": "retrieve",
                "target_entity_types": ["event"],
                "query_rewrite": "最近有什么活动",
                "need_list": True,
                "need_detail": False,
                "response_style": "normal",
                "confidence": "high",
                "direct_reply": "",
            },
        ), patch(
            "app.chat.semantic_rank_entities",
            return_value=[(event_one, 0.83), (event_two, 0.79)],
        ), patch(
            "app.chat.judge_candidates",
            return_value={
                "status": "ok",
                "decision": "list",
                "selected_entity_ids": [event_one["id"], event_two["id"]],
                "confidence": "high",
                "reason": "用户在问活动列表",
                "direct_reply": "",
            },
        ), patch("app.chat.generate_grounded_answer", return_value=None):
            result = answer_question("最近有什么活动", "test-event-list")

        self.assertEqual(result["matched_entity_type"], "event")
        self.assertIsNone(result["matched_entity_id"])
        self.assertIn("Live 演出", result["answer_text"])
        self.assertIn("模拟彩排", result["answer_text"])

    def test_judge_no_answer_returns_fallback(self) -> None:
        from app.chat import answer_question
        from app.repository import create_entity

        contact = create_entity(
            {
                "entity_type": "contact",
                "slug": "president",
                "title": "社长",
                "status": "published",
                "updated_by": "tester",
                "data": {"contact_name": "James", "role": "社长", "channel": "微信", "contact_value": "james-wechat"},
            }
        )

        with patch(
            "app.chat.plan_turn",
            return_value={
                "mode": "retrieve",
                "target_entity_types": ["contact"],
                "query_rewrite": "上上届社长最喜欢什么颜色",
                "need_list": False,
                "need_detail": False,
                "response_style": "normal",
                "confidence": "medium",
                "direct_reply": "",
            },
        ), patch("app.chat.semantic_rank_entities", return_value=[(contact, 0.66)]), patch(
            "app.chat.judge_candidates",
            return_value={"status": "ok", "decision": "no_answer", "selected_entity_ids": [], "confidence": "high", "reason": "候选无法支持该问题", "direct_reply": ""},
        ):
            result = answer_question("你们上上届社长最喜欢什么颜色？", "test-miss")

        self.assertEqual(result["confidence_level"], "low")
        self.assertTrue(result["needs_verification"])

    def test_chat_log_contains_plan_and_judge_trace(self) -> None:
        from app.chat import answer_question
        from app.repository import create_entity, list_chat_logs

        faq = create_entity(
            {
                "entity_type": "faq_entry",
                "slug": "join-faq",
                "title": "怎么报名加入社团",
                "status": "published",
                "updated_by": "tester",
                "data": {"question": "怎么报名加入社团？", "aliases": ["报名入口在哪"], "answer": "进入小程序首页填写报名表即可。"},
            }
        )

        with patch(
            "app.chat.plan_turn",
            return_value={
                "mode": "retrieve",
                "target_entity_types": ["faq_entry"],
                "query_rewrite": "报名入口在哪",
                "need_list": False,
                "need_detail": True,
                "response_style": "brief",
                "confidence": "high",
                "direct_reply": "",
            },
        ), patch("app.chat.semantic_rank_entities", return_value=[(faq, 0.88)]), patch(
            "app.chat.judge_candidates",
            return_value={"status": "ok", "decision": "single", "selected_entity_ids": [faq["id"]], "confidence": "high", "reason": "FAQ 直接命中", "direct_reply": ""},
        ), patch("app.chat.generate_grounded_answer", return_value=None):
            answer_question("报名入口在哪？", "test-debug")

        latest = list_chat_logs(limit=1)[0]
        self.assertEqual(latest["debug_trace"]["selected_path"], "judge_single")
        self.assertEqual(latest["debug_trace"]["plan"]["mode"], "retrieve")
        self.assertEqual(latest["debug_trace"]["judge"]["decision"], "single")
        self.assertTrue(latest["debug_trace"]["semantic_candidates"])

    def test_judge_failed_falls_back_to_same_type_list(self) -> None:
        from app.chat import answer_question
        from app.repository import create_entity

        event_one = create_entity(
            {
                "entity_type": "event",
                "slug": "show-a",
                "title": "演出 A",
                "status": "published",
                "updated_by": "tester",
                "data": {"event_name": "演出 A", "time": "2026-05-01", "location": "Hall A", "owner": "James"},
            }
        )
        event_two = create_entity(
            {
                "entity_type": "event",
                "slug": "show-b",
                "title": "演出 B",
                "status": "published",
                "updated_by": "tester",
                "data": {"event_name": "演出 B", "time": "2026-05-02", "location": "Hall B", "owner": "Kai"},
            }
        )

        with patch(
            "app.chat.plan_turn",
            return_value={
                "mode": "retrieve",
                "target_entity_types": ["event"],
                "query_rewrite": "最近有什么活动",
                "need_list": True,
                "need_detail": False,
                "response_style": "normal",
                "confidence": "high",
                "direct_reply": "",
            },
        ), patch(
            "app.chat.semantic_rank_entities",
            return_value=[(event_one, 0.83), (event_two, 0.79)],
        ), patch(
            "app.chat.judge_candidates",
            return_value={
                "status": "failed",
                "decision": "no_answer",
                "selected_entity_ids": [],
                "confidence": "low",
                "reason": "judge_output_invalid",
                "direct_reply": "",
                "raw_content": "not json",
                "retry_raw_content": None,
            },
        ), patch("app.chat.generate_grounded_answer", return_value=None):
            result = answer_question("最近有什么活动", "test-judge-fallback-list")

        self.assertEqual(result["matched_entity_type"], "event")
        self.assertIn("演出 A", result["answer_text"])
        self.assertIn("演出 B", result["answer_text"])


if __name__ == "__main__":
    unittest.main()
