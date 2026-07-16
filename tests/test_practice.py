from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as journal_app
from relationship_ai import AIServiceError


def practice_ai_result(session, action, content, **_kwargs):
    if action == "submit_topic":
        return {
            "status": "in_progress",
            "reply": "这件事已经足够具体。",
            "attempt_feedback": {
                "result": "pass",
                "fact": {"status": "pass", "evidence": "有具体动作"},
                "one_priority_tip": "继续只谈这件事",
                "suggested_version": content,
            },
            "source_labels": [],
        }
    if action in {"submit_expression", "use_suggestion"}:
        return {
            "status": "in_progress",
            "reply": "四个部分已经基本清楚。",
            "attempt_feedback": {
                "result": "pass",
                "components": {
                    name: {"status": "pass", "evidence": "已出现"}
                    for name in ("fact", "feeling", "need", "request")
                },
                "one_priority_tip": "保持请求具体",
                "suggested_version": content,
            },
            "roleplay": {
                "role": "listener",
                "paraphrase": "我听到你希望说重要事情时我先放下手机两分钟，我理解得对吗？",
                "captured": {"fact": "看手机", "feeling": "失落", "need": "被听见", "request": "放下手机两分钟"},
            },
            "strategy_tags": ["fact_feeling_need_request", "specific_time_request"],
            "source_labels": [],
        }
    if action == "confirm_accurate":
        return {
            "status": "in_progress",
            "reply": "我明白这会让你失落。可以，之后你说重要事情时我先放下手机两分钟。",
            "roleplay": {
                "role": "partner",
                "acknowledgement": "承认失落",
                "decision": "accept",
                "action_or_alternative": "先放下手机两分钟",
                "full_response": "我明白这会让你失落。可以，之后你说重要事情时我先放下手机两分钟。",
            },
            "source_labels": [],
        }
    if action == "continue_to_debrief":
        return {
            "status": "in_progress",
            "reply": "本轮已经完成表达、复述和回应。",
            "final_summary": {
                "final_expression": session["final_expression"],
                "final_paraphrase": session["final_paraphrase"],
                "final_response": session["final_response"],
                "skill_results": {
                    "事实具体性": "已做到",
                    "感受准确性": "已做到",
                    "需要清楚度": "已做到",
                    "请求可执行性": "已做到",
                    "复述确认": "已做到",
                    "回应明确性": "已做到",
                },
                "one_practice_focus": "保持一次只提一个请求",
                "strategy_tags": ["fact_feeling_need_request", "specific_time_request"],
                "real_world_outcome": "unknown",
            },
            "source_labels": [],
        }
    raise AssertionError(action)


class PracticeApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL_NAME": "gemini-3.1-pro-high"},
        )
        self.env_patcher.start()
        self.temp_dir = tempfile.TemporaryDirectory()
        journal_app.DATA_DIR = Path(self.temp_dir.name)
        journal_app.DB_PATH = journal_app.DATA_DIR / "test.db"
        journal_app.app.config.update(TESTING=True)
        journal_app.init_db()
        self.client = journal_app.app.test_client()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        self.env_patcher.stop()

    def create_session(self) -> dict:
        response = self.client.post(
            "/api/practice-sessions",
            json={
                "speaker_id": "xiaoli",
                "scene_type": "日常交流",
                "topic_summary": "刚才我说工作时，小元连续看了几次手机。",
                "goal": "改变具体行为",
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.get_json()

    def advance(self, session_id: int, stage: str, action: str, turn_id: str, **extra):
        response = self.client.post(
            f"/api/practice-sessions/{session_id}/advance/stream",
            json={"expected_stage": stage, "action": action, "turn_id": turn_id, **extra},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        events = [json.loads(line) for line in response.get_data(as_text=True).splitlines() if line]
        error = next((item for item in events if item["type"] == "error"), None)
        self.assertIsNone(error, error)
        return next(item for item in events if item["type"] == "final")

    @patch("app.run_practice_turn", side_effect=practice_ai_result)
    def test_full_practice_state_machine_persists_and_resumes(self, _mock_ai) -> None:
        session = self.create_session()
        self.assertEqual(session["stage"], "setup")
        self.assertTrue(session["saved"])
        self.assertNotIn("timer", session)

        final = self.advance(
            session["id"], "setup", "confirm_setup", "turnsetup01",
            topic_summary=session["topic_summary"], goal=session["goal"], scene_type=session["scene_type"],
        )
        session = final["session"]
        self.assertEqual(session["stage"], "narrowing_topic")

        duplicate = self.advance(session["id"], "narrowing_topic", "submit_topic", "turnsetup01", content="不会使用")
        self.assertTrue(duplicate["idempotent"])
        self.assertEqual(duplicate["session"]["stage"], "narrowing_topic")

        final = self.advance(session["id"], "narrowing_topic", "submit_topic", "turntopic01", content=session["topic_summary"])
        session = final["session"]
        self.assertEqual(session["stage"], "expression_draft")

        expression = "刚才我说工作时你连续看了几次手机，我有点失落。我需要被认真听见。以后我说重要事情时，你能先放下手机两分钟吗？"
        final = self.advance(session["id"], "expression_draft", "submit_expression", "turnexpr001", content=expression)
        session = final["session"]
        self.assertEqual(session["stage"], "paraphrase_confirmation")
        self.assertEqual(session["final_expression"], expression)

        final = self.advance(session["id"], "paraphrase_confirmation", "confirm_accurate", "turnpara001")
        session = final["session"]
        self.assertEqual(session["stage"], "partner_response")
        self.assertIn("放下手机", session["final_response"])

        final = self.advance(session["id"], "partner_response", "continue_to_debrief", "turndebrief1")
        session = final["session"]
        self.assertEqual(session["stage"], "debrief")
        self.assertEqual(session["skill_results"]["复述确认"], "已做到")

        final = self.advance(session["id"], "debrief", "complete_practice", "turncomplete1")
        session = final["session"]
        self.assertEqual(session["status"], "completed")
        self.assertEqual(session["stage"], "completed")

        restored = self.client.get(f"/api/practice-sessions/{session['id']}").get_json()
        self.assertEqual(restored["final_expression"], expression)
        self.assertGreaterEqual(len(restored["turns"]), 10)
        self.assertEqual(self.client.get("/api/progress").get_json()["participants"][0]["scored_count"], 0)
        practice_progress = self.client.get("/api/practice-progress").get_json()
        self.assertEqual(practice_progress["completed_sessions"], 1)
        self.assertEqual(practice_progress["skills"][0]["counts"]["已做到"], 1)

    def test_stage_conflict_returns_409(self) -> None:
        session = self.create_session()
        response = self.client.post(
            f"/api/practice-sessions/{session['id']}/advance/stream",
            json={"expected_stage": "expression_draft", "action": "submit_expression", "turn_id": "conflict01", "content": "测试"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["session"]["stage"], "setup")

    @patch("app.run_practice_turn", side_effect=AIServiceError("模型暂时不可用"))
    def test_model_failure_does_not_advance_or_consume_turn_id(self, _mock_ai) -> None:
        session = self.create_session()
        session = self.advance(
            session["id"], "setup", "confirm_setup", "failsetup1",
            topic_summary=session["topic_summary"], goal=session["goal"],
        )["session"]
        response = self.client.post(
            f"/api/practice-sessions/{session['id']}/advance/stream",
            json={
                "expected_stage": "narrowing_topic",
                "action": "submit_topic",
                "turn_id": "retryturn1",
                "content": session["topic_summary"],
            },
        )
        events = [json.loads(line) for line in response.get_data(as_text=True).splitlines() if line]
        self.assertEqual(next(item for item in events if item["type"] == "error")["error"], "模型暂时不可用")
        restored = self.client.get(f"/api/practice-sessions/{session['id']}").get_json()
        self.assertEqual(restored["stage"], "narrowing_topic")
        self.assertFalse(any(turn["turn_id"] == "retryturn1" for turn in restored["turns"]))

    @patch("app.run_practice_turn", side_effect=practice_ai_result)
    def test_user_confirmed_outcomes_drive_strategy_stats(self, _mock_ai) -> None:
        session = self.create_session()
        session = self.advance(session["id"], "setup", "confirm_setup", "outsetup01", topic_summary=session["topic_summary"], goal=session["goal"])["session"]
        session = self.advance(session["id"], "narrowing_topic", "submit_topic", "outtopic01", content=session["topic_summary"])["session"]
        session = self.advance(session["id"], "expression_draft", "submit_expression", "outexpr001", content="刚才你看手机，我失落，需要被听见。你能先放下手机两分钟吗？")["session"]

        outcome = self.client.post(
            f"/api/practice-sessions/{session['id']}/outcomes",
            json={
                "used_at": "2026-07-16",
                "result": "helpful",
                "partner_reaction": "小元放下手机并听完了",
                "agreement_reached": True,
            },
        )
        self.assertEqual(outcome.status_code, 201)
        self.assertTrue(outcome.get_json()["confirmed_by_user"])
        stats = self.client.get("/api/practice-strategy-stats").get_json()["strategies"]
        self.assertEqual(stats[0]["display"], "1/1 次有帮助")
        self.assertIsNone(stats[0]["helpful_rate"])

    @patch("app.analyze_relationship")
    def test_qa_mode_never_persists_real_review(self, mock_analyze) -> None:
        mock_analyze.return_value = {
            "mode": "qa",
            "status": "complete",
            "reply": "先回应感受，再询问是否需要方案。",
            "answer": {"direct_answer": "先回应感受"},
            "source_labels": [{"type": "communication_method", "label": "沟通方法", "reference_id": ""}],
            "record": None,
        }
        response = self.client.post("/api/chat", json={"mode": "qa", "message": "倾诉时怎么回应？"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["mode"], "qa")
        self.assertFalse(response.get_json()["analysis_saved"])
        self.assertEqual(mock_analyze.call_args.kwargs["mode"], "qa")
        with closing(journal_app.get_conn()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM scene_analyses").fetchone()[0], 0)

    def test_unrelated_real_reviews_are_not_used_as_fallback(self) -> None:
        with closing(journal_app.get_conn()) as conn:
            now = "2026-07-16T12:00:00"
            conn.execute(
                """
                INSERT INTO scene_analyses (
                    conversation_id, turn_id, scene_type, question_summary,
                    searchable_text, created_at, updated_at
                ) VALUES ('conversation01', 'reviewturn01', '共同活动', '晚餐时讨论菜品', '晚餐 菜品 共同活动', ?, ?)
                """,
                (now, now),
            )
            conn.commit()
        self.assertEqual(journal_app.find_similar_analyses("是否应该换一份工作", limit=5), [])

    def test_health_and_backup_expose_practice_capabilities(self) -> None:
        session = self.create_session()
        health = self.client.get("/api/health").get_json()
        self.assertEqual(health["features"]["coach_modes"], ["qa", "review", "practice"])
        self.assertTrue(health["features"]["practice_persistence"])
        backup = self.client.get("/api/backup.json").get_json()
        self.assertEqual(backup["practice_sessions"][0]["id"], session["id"])
        self.assertIn("practice_turns", backup)
        self.assertIn("practice_outcomes", backup)


if __name__ == "__main__":
    unittest.main()
