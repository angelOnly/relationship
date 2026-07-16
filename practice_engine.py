from __future__ import annotations

from typing import Any


STAGES = (
    "setup",
    "narrowing_topic",
    "expression_draft",
    "paraphrase_confirmation",
    "partner_response",
    "debrief",
    "completed",
)

STEP_CARDS = {
    "setup": {"number": 1, "title": "练习设置", "instruction": "确认谁来表达、只谈哪一件小事，以及这轮想达成什么。", "expected_input": "确认人物、具体小事和目标"},
    "narrowing_topic": {"number": 1, "title": "把事情说小", "instruction": "只写摄像头能拍到的动作或原话，不评价人格、不翻旧账。", "expected_input": "一件有时间、动作或原话的小事"},
    "expression_draft": {"number": 2, "title": "20 秒表达", "instruction": "按事实＋感受＋需要＋具体请求写一小段话。这里只是结构名称，不计时。", "expected_input": "一段包含四个部分的简短表达"},
    "paraphrase_confirmation": {"number": 3, "title": "AI 复述", "instruction": "核对 AI 是否准确听见事实、感受、需要和请求。", "expected_input": "选择准确、部分准确或不准确；必要时补一句纠正"},
    "partner_response": {"number": 4, "title": "AI 回应", "instruction": "AI 扮演另一方，承认影响并对请求作出明确回应。", "expected_input": "继续总结，或再练一轮表达"},
    "debrief": {"number": 5, "title": "本轮总结", "instruction": "查看最终表达、复述、回应和一个下次练习重点。", "expected_input": "完成练习，或再练一轮"},
    "completed": {"number": 5, "title": "练习已完成", "instruction": "这只是练习结果；现实是否有效需要你之后亲自记录。", "expected_input": "记录现实使用结果，或再练一轮"},
}

ALLOWED_ACTIONS = {
    "setup": ["confirm_setup", "pause", "abandon"],
    "narrowing_topic": ["submit_topic", "pause", "abandon"],
    "expression_draft": ["submit_expression", "use_suggestion", "pause", "abandon"],
    "paraphrase_confirmation": ["confirm_accurate", "confirm_partial", "confirm_inaccurate", "pause", "abandon"],
    "partner_response": ["continue_to_debrief", "practice_again", "pause", "abandon"],
    "debrief": ["complete_practice", "practice_again", "abandon"],
    "completed": ["practice_again", "delete_session"],
}


class PracticeConflictError(ValueError):
    pass


class PracticeValidationError(ValueError):
    pass


def allowed_actions(session: dict[str, Any]) -> list[str]:
    status = session.get("status")
    if status == "paused":
        return ["resume", "abandon"]
    if status == "safety_stop":
        return ["delete_session"]
    if status == "abandoned":
        return ["delete_session"]
    actions = list(ALLOWED_ACTIONS.get(str(session.get("stage")), []))
    if session.get("goal") == "练习表达" and session.get("stage") == "expression_draft":
        actions.insert(0, "submit_action_attempt")
    return actions


def step_card(stage: str) -> dict[str, Any]:
    return dict(STEP_CARDS.get(stage, STEP_CARDS["setup"]))


def validate_advance(session: dict[str, Any], expected_stage: str, action: str) -> None:
    actual_stage = str(session.get("stage", ""))
    if expected_stage != actual_stage:
        raise PracticeConflictError(f"练习已在“{step_card(actual_stage)['title']}”，请刷新当前状态后继续。")
    if session.get("status") == "paused":
        raise PracticeConflictError("练习已暂停，请先恢复。")
    if action not in allowed_actions(session):
        raise PracticeValidationError("当前步骤不允许这个操作。")


def require_text(value: Any, label: str, max_length: int = 3000) -> str:
    text = str(value or "").strip()
    if not text:
        raise PracticeValidationError(f"请先填写{label}。")
    if len(text) > max_length:
        raise PracticeValidationError(f"{label}请控制在 {max_length} 字以内。")
    return text


def public_practice_state(session: dict[str, Any]) -> dict[str, Any]:
    stage = str(session.get("stage", "setup"))
    result = dict(session)
    result["step_card"] = step_card(stage)
    result["allowed_actions"] = allowed_actions(session)
    result["saved"] = True
    return result
