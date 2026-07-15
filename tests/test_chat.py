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


def participant_record(
    participant_id: str,
    name: str,
    expectation: str,
    talent_state: str,
    score: int,
) -> dict:
    return {
        "participant": {"id": participant_id, "name": name},
        "role_in_event": "提出连接需要" if participant_id == "xiaoli" else "回应共同活动体验",
        "inner_expectation": expectation,
        "talent_state": talent_state,
        "behavior": {
            "feedback": f"{name}已经出现可观察的调整。",
            "score": score,
            "dimensions": {
                "期待表达": "有尝试：说出了具体需要",
                "才干调节": "有尝试：没有继续争辩",
                "回应对方": "有尝试：回应了对方关注点",
                "合作修复": "有尝试：提出继续聊",
            },
            "score_reason": "已有觉察；把请求加上时间点可提高 1 分。",
        },
    }


def complete_result(summary: str = "晚餐时一方关注体验细节，另一方感到交流被忽视") -> dict:
    return {
        "status": "complete",
        "reply": "这次卡在共同活动目标不同：一方要连接，一方要体验质量。",
        "record": {
            "occurred_at": "2026-07-15",
            "scene_type": "共同活动",
            "observed_facts": "晚餐时小元多次评论菜品，小娌表达了不满。",
            "question_summary": summary,
            "keywords": ["共同活动", "晚餐", "被忽视", "专注", "完美"],
            "participants": [
                participant_record(
                    "xiaoli",
                    "小娌",
                    "希望共同活动中有专注交流",
                    "专注受压，已尝试表达连接需求",
                    6,
                ),
                participant_record(
                    "xiaoyuan",
                    "小元",
                    "希望把共同体验做到更好",
                    "完美过度，注意力投向外部体验",
                    7,
                ),
            ],
            "interaction": {
                "loop": "评审细节→感到被忽视→批评→继续防御",
                "communication_guidance": "肯定体验投入，再提出十分钟只聊天的请求",
                "recommended_wording": "我看见你很认真在照顾体验，我也想要十分钟只聊我们，可以吗？",
                "progress_assessment": "暂无基线：这是第一条共同活动记录。",
                "next_action": "下次活动前约定十分钟无手机交流",
                "uncertainty": "小元是否把评论细节当作照顾体验仍待确认",
                "confidence": "中：目前主要是单方描述",
            },
        },
    }


def period_review_result() -> dict:
    return {
        "participants": [
            {
                "participant": {"id": "xiaoli", "name": "小娌"},
                "score": 7,
                "feedback": "已经把感受翻译成需要，没有使用整体否定。",
            },
            {
                "participant": {"id": "xiaoyuan", "name": "小元"},
                "score": 6,
                "feedback": "给出了解释，但还缺少明确完成时间。",
            },
        ],
        "interaction": {
            "score": 6,
            "summary": "双方都能描述需要，但具体请求和回应仍不稳定。",
            "what_improved": "暂无历史基线；本次已经出现具体需要表达。",
            "risk_pattern": "一方催促时，另一方可能再次退回解释和延迟。",
            "adjustment_goal": "明天只练习一个带时间点的具体请求。",
            "actions": ["晚上九点前用一句事实加请求开启沟通", "收到请求后明确回复时间"],
            "conversation_example": "我想先说清需要，也想听你最担心什么，我们九点前定一个下一步。",
            "confidence": "中：双方各有一条记录，但缺少实际执行结果。",
        },
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
            "reply": "请确认本次记录者是小娌还是小元，并补充当时具体说了什么。",
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
            count = conn.execute("SELECT COUNT(*) FROM scene_analyses").fetchone()[0]
        self.assertEqual(count, 0)

    @patch("app.analyze_relationship")
    def test_complete_analysis_uses_participant_arrays_and_is_saved_once(self, mock_analyze) -> None:
        mock_analyze.return_value = complete_result()
        payload = {
            "conversation_id": "conversation01",
            "turn_id": "turn000002",
            "message": "昨晚吃饭时小元一直点评菜，小娌觉得被忽视。",
            "speaker_id": "xiaoli",
            "history": [],
            "model": "gemini-3.5-flash-high",
        }
        first = self.client.post("/api/chat", json=payload)
        second = self.client.post("/api/chat", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.get_json()["analysis_saved"])
        self.assertEqual(second.status_code, 200)
        saved = first.get_json()["record"]
        self.assertEqual([item["participant"]["name"] for item in saved["participants"]], ["小娌", "小元"])
        self.assertEqual(saved["participants"][0]["behavior"]["score"], 6)
        with closing(journal_app.get_conn()) as conn:
            rows = conn.execute("SELECT * FROM scene_analyses").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0]["participants_json"])[1]["participant"]["name"], "小元")
        self.assertEqual(rows[0]["model_name"], "gemini-3-flash-agent")
        self.assertEqual(mock_analyze.call_args.kwargs["model_name"], "gemini-3-flash-agent")
        self.assertEqual(mock_analyze.call_args.kwargs["speaker"]["name"], "小娌")

    def test_catalog_exposes_models_and_canonical_participants(self) -> None:
        catalog = self.client.get("/api/models").get_json()
        mapping = {item["key"]: item["model"] for item in catalog["models"]}
        self.assertEqual(mapping["gemini-3.5-flash-high"], "gemini-3-flash-agent")
        self.assertEqual(mapping["gemini-3.5-flash-medium"], "gemini-3.5-flash-low")
        self.assertEqual(mapping["gemini-3.1-flash-lite"], "gemini-3.1-flash-lite")
        self.assertEqual(mapping["gemini-3.5-flash-extra-low"], "gemini-3.5-flash-extra-low")
        participants = self.client.get("/api/participants").get_json()["participants"]
        self.assertEqual(participants, [{"id": "xiaoli", "name": "小娌"}, {"id": "xiaoyuan", "name": "小元"}])

        response = self.client.post(
            "/api/chat",
            json={"message": "测试未知模型", "model": "arbitrary-expensive-model"},
        )
        self.assertEqual(response.status_code, 400)

        invalid_speaker = self.client.post(
            "/api/chat",
            json={"message": "测试未知记录者", "speaker_id": "me"},
        )
        self.assertEqual(invalid_speaker.status_code, 400)
        self.assertIn("小娌或小元", invalid_speaker.get_json()["error"])

    @patch("app.analyze_relationship")
    def test_chinese_fuzzy_search_and_per_participant_progress(self, mock_analyze) -> None:
        mock_analyze.return_value = complete_result()
        self.client.post(
            "/api/chat",
            json={
                "conversation_id": "conversation02",
                "turn_id": "turn000003",
                "message": "晚餐时小娌觉得被忽视。",
                "history": [],
            },
        )
        records = self.client.get("/api/analysis-records?q=被忽视").get_json()
        self.assertEqual(len(records), 1)
        self.assertIn("晚餐", records[0]["keywords"])
        self.assertIsInstance(records[0]["participants"][0]["behavior"]["dimensions"], dict)

        progress = self.client.get("/api/progress").get_json()["participants"]
        self.assertEqual(progress[0]["participant"]["name"], "小娌")
        self.assertEqual(progress[0]["recent_average"], 6.0)
        self.assertEqual(progress[1]["recent_average"], 7.0)

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

    def test_daily_records_store_canonical_names_and_keep_revisions(self) -> None:
        payload = {
            "entry_date": "2026-07-16",
            "participant_id": "xiaoli",
            "appreciation": "小元愿意认真听完",
            "event": "讨论了周末安排",
            "feeling": "安心",
            "need": "共同参与",
            "response": "小娌提出两个选项，小元补充了时间限制",
            "repair_request": "明晚一起确认最终安排",
            "follow_up": "coordinate",
        }
        first = self.client.post("/api/entries", json=payload).get_json()
        payload["response"] = "小娌与小元各自说明限制后确定了一个方案"
        second = self.client.post("/api/entries", json=payload).get_json()
        self.assertEqual(first["participant"], {"id": "xiaoli", "name": "小娌"})
        self.assertEqual(first["schema_version"], 2)
        self.assertEqual(second["revision"], 2)

        with closing(journal_app.get_conn()) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            document = conn.execute("SELECT * FROM record_documents").fetchone()
            revision_count = conn.execute("SELECT COUNT(*) FROM record_revisions").fetchone()[0]
        self.assertNotIn("daily_entries", tables)
        self.assertNotIn("analysis_records", tables)
        self.assertNotIn("ai_period_reviews", tables)
        self.assertEqual(document["author"], "小娌")
        self.assertEqual(json.loads(document["metadata_json"])["participant"]["name"], "小娌")
        self.assertEqual(revision_count, 2)

    def test_weekly_json_has_role_neutral_field_names(self) -> None:
        response = self.client.post(
            "/api/weeks",
            json={
                "month_key": "2026-07",
                "week_no": 2,
                "observed_adjustment": "双方都能在暂停后回来",
                "participant_signals": "小娌表达更具体，小元按时回应",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIn("observed_adjustment", body)
        self.assertIn("participant_signals", body)
        self.assertNotIn("my_learning", body)
        self.assertNotIn("partner_signal", body)

    def test_action_goals_use_names_and_have_a_lifecycle(self) -> None:
        baseline = self.client.get("/api/action-items").get_json()
        self.assertTrue(all(item["owner"] == "共同" for item in baseline if item["source"] == "baseline"))
        created = self.client.post(
            "/api/action-items",
            json={
                "owner": "小娌",
                "title": "每周确认一次共同安排",
                "detail": "周日晚确定下一周唯一需要协调的事情",
            },
        )
        self.assertEqual(created.status_code, 201)
        item = created.get_json()
        self.assertEqual(item["owner"], "小娌")
        completed = self.client.patch(
            f"/api/action-items/{item['id']}",
            json={"status": "completed"},
        ).get_json()
        self.assertEqual(completed["status"], "completed")

    def test_downloads_and_backup_use_new_json_contract(self) -> None:
        self.client.post(
            "/api/entries",
            json={
                "entry_date": "2026-07-16",
                "participant_id": "xiaoli",
                "event": "测试导出",
                "follow_up": "none",
            },
        )
        csv_response = self.client.get("/api/export.csv?month=2026-07")
        backup_response = self.client.get("/api/backup.json")
        backup = backup_response.get_json()

        self.assertEqual(csv_response.status_code, 200)
        self.assertEqual(backup_response.status_code, 200)
        self.assertTrue(csv_response.data.startswith(b"\xef\xbb\xbf"))
        self.assertIn("filename*=UTF-8''", csv_response.headers["Content-Disposition"])
        self.assertEqual(backup["version"], 4)
        self.assertEqual(backup["participants"][0]["name"], "小娌")
        self.assertIn("scene_analyses", backup)
        self.assertIn("period_reviews", backup)
        self.assertNotIn("analysis_records", backup)

    @patch("app.review_journal_period")
    def test_daily_period_review_persists_two_json_objects(self, mock_review) -> None:
        mock_review.return_value = period_review_result()
        for participant_id_value, need in (("xiaoli", "被看见"), ("xiaoyuan", "有思考时间")):
            saved = self.client.post(
                "/api/entries",
                json={
                    "entry_date": "2026-07-16",
                    "participant_id": participant_id_value,
                    "appreciation": "愿意停下来听",
                    "event": "讨论时回应仍不够具体",
                    "feeling": "有点失望",
                    "need": need,
                    "response": "想约一个明确回复时间",
                    "repair_request": "明晚九点前回复",
                    "follow_up": "communicate",
                },
            )
            self.assertEqual(saved.status_code, 200)

        payload = {"period_type": "daily", "period_key": "2026-07-16"}
        first = self.client.post("/api/ai-reviews", json=payload)
        second = self.client.post("/api/ai-reviews", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["participants"][0]["score"], 7)
        self.assertEqual(first.get_json()["interaction"]["score"], 6)
        self.assertEqual(second.get_json()["revision"], 2)

        loaded = self.client.get(
            "/api/ai-reviews?period_type=daily&period_key=2026-07-16"
        ).get_json()
        self.assertEqual(len(loaded["participants"]), 2)
        self.assertEqual(len(loaded["interaction"]["actions"]), 2)
        with closing(journal_app.get_conn()) as conn:
            row = conn.execute("SELECT * FROM period_reviews").fetchone()
            ai_goal = conn.execute("SELECT * FROM action_items WHERE source = 'ai_daily'").fetchone()
        self.assertEqual(json.loads(row["participants_json"])[1]["participant"]["name"], "小元")
        self.assertEqual(json.loads(row["interaction_json"])["score"], 6)
        self.assertEqual(ai_goal["owner"], "共同")
        self.assertEqual(ai_goal["status"], "suggested")


if __name__ == "__main__":
    unittest.main()
