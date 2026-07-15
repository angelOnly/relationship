from __future__ import annotations

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
        self.temp_dir = tempfile.TemporaryDirectory()
        journal_app.DATA_DIR = Path(self.temp_dir.name)
        journal_app.DB_PATH = journal_app.DATA_DIR / "test.db"
        journal_app.app.config.update(TESTING=True)
        journal_app.init_db()
        self.client = journal_app.app.test_client()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

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

    @patch("app.review_journal_period")
    def test_daily_ai_review_is_scored_and_upserted(self, mock_review) -> None:
        mock_review.return_value = period_review_result()
        for person, need in (("me", "被看见"), ("partner", "有思考时间")):
            saved = self.client.post(
                "/api/entries",
                json={
                    "entry_date": "2026-07-16",
                    "person": person,
                    "positive": "对方愿意停下来听",
                    "dissatisfaction": "回应仍不够具体",
                    "category": "talk",
                    "feeling": "有点失望",
                    "need": need,
                    "better_wording": "我想约一个明确回复时间",
                    "tomorrow_request": "明晚九点前回复",
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
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
