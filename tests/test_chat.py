from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as journal_app
from relationship_ai import AIConfigError


def complete_result(summary: str = "晚餐时一方关注体验细节，另一方感到交流被忽视") -> dict:
    return {
        "status": "complete",
        "reply": "这次卡在共同活动目标不同：一方要连接，一方要体验质量。",
        "record": {
            "occurred_at": "2026-07-15",
            "scene_type": "共同活动",
            "roles": "用户提出连接需求，对方持续评审餐厅体验",
            "observed_facts": "晚餐时对方多次评论菜品，用户表达了不满。",
            "question_summary": summary,
            "keywords": ["共同活动", "晚餐", "被忽视", "专注", "完美"],
            "inner_expectation_me": "希望共同活动中有专注交流",
            "inner_expectation_partner": "希望把共同体验做到更好",
            "talent_state_me": "专注受压，已尝试表达连接需求",
            "talent_state_partner": "完美过度，注意力投向外部体验",
            "interaction_loop": "评审细节→感到被忽视→批评→继续防御",
            "communication_guidance": "肯定体验投入，再提出十分钟只聊天的请求",
            "recommended_wording": "我看见你很认真在照顾体验，我也想要十分钟只聊我们，可以吗？",
            "behavior_feedback": "用户能说出不满，但请求仍不够具体。",
            "behavior_score": 6,
            "behavior_dimensions": {
                "期待表达": "有尝试：说出了想交流",
                "才干调节": "有尝试：没有继续争辩",
                "回应对方": "未出现：没有先肯定对方投入",
                "合作修复": "有尝试：提出继续聊",
            },
            "score_reason": "有觉察但仍带批评；具体提出十分钟请求可提高 1 分。",
            "progress_assessment": "暂无基线：这是第一条共同活动记录。",
            "next_action": "下次活动前约定十分钟无手机交流",
            "uncertainty": "对方是否把评论细节当作照顾体验仍待确认",
            "confidence": "中：只有用户单方描述",
        },
    }


def period_review_result() -> dict:
    return {
        "summary": "双方都能描述需要，但具体请求和回应仍不稳定。",
        "score_me": 7,
        "score_partner": 6,
        "relationship_score": 6,
        "feedback_me": "已经把感受翻译成需要，没有使用整体否定。",
        "feedback_partner": "给出了解释，但还缺少明确完成时间。",
        "what_improved": "暂无历史基线；本次已经出现具体需要表达。",
        "risk_pattern": "一方催促时，另一方可能再次退回解释和延迟。",
        "adjustment_goal": "明天只练习一个带时间点的具体请求。",
        "actions": ["晚上九点前用一句事实加请求开启沟通", "收到请求后明确回复时间"],
        "conversation_example": "我想先说清需要，也想听你最担心什么，我们九点前定一个下一步。",
        "confidence": "中：双方各有一条记录，但缺少实际执行结果。",
    }


class ChatApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key-not-a-real-secret",
                "OPENAI_MODEL_NAME": "gemini-3.1-pro-high",
            },
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

    @patch("app.analyze_relationship")
    def test_clarification_turn_is_not_persisted(self, mock_analyze) -> None:
        mock_analyze.return_value = {
            "status": "clarifying",
            "reply": "你当时具体说了什么？对方怎么回应？",
            "record": None,
        }
        response = self.client.post(
            "/api/chat",
            json={
                "conversation_id": "conversation01",
                "turn_id": "turn000001",
                "message": "我们吵架了。",
                "history": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["analysis_saved"])
        with closing(journal_app.get_conn()) as conn:
            count = conn.execute("SELECT COUNT(*) FROM analysis_records").fetchone()[0]
        self.assertEqual(count, 0)

    @patch("app.analyze_relationship")
    def test_complete_analysis_is_saved_once(self, mock_analyze) -> None:
        mock_analyze.return_value = complete_result()
        payload = {
            "conversation_id": "conversation01",
            "turn_id": "turn000002",
            "message": "昨晚吃饭时他一直点评菜，我觉得被忽视。",
            "history": [],
            "model": "gemini-3.5-flash-high",
        }
        first = self.client.post("/api/chat", json=payload)
        second = self.client.post("/api/chat", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.get_json()["analysis_saved"])
        self.assertEqual(second.status_code, 200)
        with closing(journal_app.get_conn()) as conn:
            rows = conn.execute("SELECT * FROM analysis_records").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["behavior_score"], 6)
        self.assertEqual(rows[0]["model_name"], "gemini-3-flash-agent")
        self.assertEqual(mock_analyze.call_args.kwargs["model_name"], "gemini-3-flash-agent")

    def test_model_catalog_exposes_requested_aliases_and_rejects_unknown(self) -> None:
        catalog = self.client.get("/api/models").get_json()
        mapping = {item["key"]: item["model"] for item in catalog["models"]}
        self.assertEqual(mapping["gemini-3.5-flash-high"], "gemini-3-flash-agent")
        self.assertEqual(mapping["gemini-3.5-flash-medium"], "gemini-3.5-flash-low")
        self.assertEqual(mapping["gemini-3.1-flash-lite"], "gemini-3.1-flash-lite")
        self.assertEqual(mapping["gemini-3.5-flash-extra-low"], "gemini-3.5-flash-extra-low")

        response = self.client.post(
            "/api/chat",
            json={"message": "测试未知模型", "model": "arbitrary-expensive-model"},
        )
        self.assertEqual(response.status_code, 400)

    @patch("app.analyze_relationship")
    def test_chinese_fuzzy_search_and_progress(self, mock_analyze) -> None:
        mock_analyze.return_value = complete_result()
        self.client.post(
            "/api/chat",
            json={
                "conversation_id": "conversation02",
                "turn_id": "turn000003",
                "message": "晚餐时我觉得被忽视。",
                "history": [],
            },
        )
        search = self.client.get("/api/analysis-records?q=被忽视")
        records = search.get_json()
        self.assertEqual(search.status_code, 200)
        self.assertEqual(len(records), 1)
        self.assertIn("晚餐", records[0]["keywords"])
        self.assertIsInstance(records[0]["behavior_dimensions"], dict)

        progress = self.client.get("/api/progress").get_json()
        self.assertEqual(progress["recent_average"], 6.0)
        self.assertEqual(progress["trend"], "暂无足够基线")

    @patch("app.analyze_relationship", side_effect=AIConfigError("服务端缺少模型配置"))
    def test_missing_provider_config_is_safe(self, _mock_analyze) -> None:
        response = self.client.post(
            "/api/chat",
            json={"message": "测试消息", "conversation_id": "conversation03"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "服务端缺少模型配置")

    def test_daily_review_requires_saved_content(self) -> None:
        response = self.client.post(
            "/api/ai-reviews",
            json={"period_type": "daily", "period_key": "2026-07-16"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("还没有", response.get_json()["error"])

    def test_daily_records_use_versioned_documents_and_keep_revisions(self) -> None:
        payload = {
            "entry_date": "2026-07-16",
            "person": "me",
            "appreciation": "他愿意认真听完",
            "event": "我们讨论了周末安排",
            "feeling": "安心",
            "need": "共同参与",
            "response": "我提出两个选项，他补充了时间限制",
            "repair_request": "明晚一起确认最终安排",
            "follow_up": "coordinate",
        }
        first = self.client.post("/api/entries", json=payload).get_json()
        payload["response"] = "我们各自说明限制后确定了一个方案"
        second = self.client.post("/api/entries", json=payload).get_json()
        self.assertEqual(first["schema_key"], "universal-daily")
        self.assertEqual(second["revision"], 2)

        with closing(journal_app.get_conn()) as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            document = conn.execute("SELECT * FROM record_documents").fetchone()
            revision_count = conn.execute("SELECT COUNT(*) FROM record_revisions").fetchone()[0]
        self.assertNotIn("daily_entries", tables)
        self.assertEqual(document["record_type"], "daily")
        self.assertEqual(json.loads(document["data_json"])["follow_up"], "coordinate")
        self.assertEqual(revision_count, 2)

    def test_action_goals_have_a_lifecycle(self) -> None:
        baseline = self.client.get("/api/action-items").get_json()
        self.assertGreaterEqual(len([item for item in baseline if item["source"] == "baseline"]), 6)
        created = self.client.post(
            "/api/action-items",
            json={
                "owner": "both",
                "title": "每周确认一次共同安排",
                "detail": "周日晚确定下一周唯一需要协调的事情",
            },
        )
        self.assertEqual(created.status_code, 201)
        item = created.get_json()
        completed = self.client.patch(
            f"/api/action-items/{item['id']}",
            json={"status": "completed"},
        ).get_json()
        self.assertEqual(completed["status"], "completed")

    def test_download_headers_support_chinese_filenames(self) -> None:
        self.client.post(
            "/api/entries",
            json={
                "entry_date": "2026-07-16",
                "person": "me",
                "event": "测试导出",
                "follow_up": "none",
            },
        )
        csv_response = self.client.get("/api/export.csv?month=2026-07")
        backup_response = self.client.get("/api/backup.json")

        self.assertEqual(csv_response.status_code, 200)
        self.assertEqual(backup_response.status_code, 200)
        self.assertTrue(csv_response.data.startswith(b"\xef\xbb\xbf"))
        self.assertIn("filename*=UTF-8''", csv_response.headers["Content-Disposition"])
        self.assertIn("filename*=UTF-8''", backup_response.headers["Content-Disposition"])
        csv_response.headers["Content-Disposition"].encode("latin-1")
        backup_response.headers["Content-Disposition"].encode("latin-1")

    @patch("app.review_journal_period")
    def test_daily_ai_review_is_scored_and_upserted(self, mock_review) -> None:
        mock_review.return_value = period_review_result()
        for person, need in (("me", "被看见"), ("partner", "有思考时间")):
            saved = self.client.post(
                "/api/entries",
                json={
                    "entry_date": "2026-07-16",
                    "person": person,
                    "appreciation": "对方愿意停下来听",
                    "event": "讨论时回应仍不够具体",
                    "feeling": "有点失望",
                    "need": need,
                    "response": "我想约一个明确回复时间",
                    "repair_request": "明晚九点前回复",
                    "follow_up": "communicate",
                },
            )
            self.assertEqual(saved.status_code, 200)

        payload = {"period_type": "daily", "period_key": "2026-07-16"}
        first = self.client.post("/api/ai-reviews", json=payload)
        second = self.client.post("/api/ai-reviews", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["score_me"], 7)
        self.assertEqual(second.get_json()["revision"], 2)

        loaded = self.client.get(
            "/api/ai-reviews?period_type=daily&period_key=2026-07-16"
        ).get_json()
        self.assertEqual(loaded["relationship_score"], 6)
        self.assertEqual(len(loaded["actions"]), 2)
        with closing(journal_app.get_conn()) as conn:
            count = conn.execute("SELECT COUNT(*) FROM ai_period_reviews").fetchone()[0]
            ai_goal = conn.execute(
                "SELECT * FROM action_items WHERE source = 'ai_daily'"
            ).fetchone()
        self.assertEqual(count, 1)
        self.assertIsNotNone(ai_goal)
        self.assertEqual(ai_goal["status"], "suggested")


if __name__ == "__main__":
    unittest.main()
