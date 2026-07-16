# 单人练习输出契约

调用方选择 `practice` 模式时，只返回一个 JSON 对象，不使用代码围栏，不在 JSON 前后添加说明。

固定人物目录：

```json
[
  {"id": "xiaoli", "name": "小娌"},
  {"id": "xiaoyuan", "name": "小元"}
]
```

## 通用结构

```json
{
  "version": "2.0",
  "mode": "practice",
  "status": "clarifying|in_progress|complete|paused|safety_stop",
  "reply": "当前步骤给用户看的简短指导或角色回应",
  "source_labels": [
    {
      "type": "current_event|user_statement|confirmed_success|gallup_profile|relationship_context|regulation_method|communication_method|model_hypothesis",
      "label": "给用户看的来源说明",
      "reference_id": "有关联历史记录时填写，否则留空"
    }
  ],
  "record": null,
  "practice": {
    "session_id": "调用方提供的值；没有则留空",
    "stage": "setup|narrowing_topic|expression_draft|paraphrase_confirmation|partner_response|debrief|completed|paused|safety_stop",
    "round": 1,
    "speaker": {"id": "xiaoli", "name": "小娌"},
    "ai_role": {"id": "xiaoyuan", "name": "小元"},
    "scene_type": "仪式感|危机管理|情感支持|共同活动|家庭责任|日常交流|未来规划|边界修复|其他",
    "topic_summary": "一件具体小事，不超过 80 字",
    "goal": "理解|修复|协商|设边界|改变具体行为|空字符串",
    "step_card": {
      "title": "当前步骤标题",
      "instruction": "本轮只做什么",
      "expected_input": "用户下一步应提供什么"
    },
    "attempt_feedback": null,
    "roleplay": null,
    "final_summary": null,
    "allowed_actions": ["当前状态允许的动作"],
    "uncertainty": "仍需用户确认的一点"
  }
}
```

调用方提供 `session_id`、`stage`、`round`、`speaker` 和 `ai_role` 时必须原样保留。不得自行跳转到调用方状态之外的阶段。

用户没有说明目标且调用方没有提供时，将 `goal` 留空并在 `setup` 阶段询问；不要根据抱怨内容擅自选择“理解、修复或改变行为”。`source_labels` 必须使用对象数组，不得缩写为字符串数组。

## 状态与允许动作

### setup

- `allowed_actions`: `confirm_setup`、`pause`、`abandon`
- 只补齐人物、一件小事和练习目标。

### narrowing_topic

- `allowed_actions`: `submit_topic`、`pause`、`abandon`
- `attempt_feedback` 使用：

```json
{
  "result": "pass|revise",
  "fact": {"status": "pass|revise", "evidence": "短证据"},
  "one_priority_tip": "本轮唯一修改建议",
  "suggested_version": "可选建议版本"
}
```

只有 `result=pass` 时才建议调用方进入 `expression_draft`。

### expression_draft

- `allowed_actions`: `submit_expression`、`use_suggestion`、`pause`、`abandon`
- `attempt_feedback` 使用：

```json
{
  "result": "pass|revise",
  "components": {
    "fact": {"status": "pass|revise", "evidence": "短证据"},
    "feeling": {"status": "pass|revise", "evidence": "短证据"},
    "need": {"status": "pass|revise", "evidence": "短证据"},
    "request": {"status": "pass|revise", "evidence": "短证据"}
  },
  "one_priority_tip": "本轮唯一修改建议",
  "suggested_version": "完整但简短的建议表达"
}
```

只有四项基本合格且 `result=pass` 时才建议进入 `paraphrase_confirmation`。

### paraphrase_confirmation

- AI 复述时 `allowed_actions`: `confirm_accurate`、`confirm_partial`、`confirm_inaccurate`、`pause`、`abandon`
- `roleplay` 使用：

```json
{
  "role": "listener",
  "paraphrase": "事实、感受、需要、请求的复述，并以我理解得对吗结尾",
  "captured": {
    "fact": "",
    "feeling": "",
    "need": "",
    "request": ""
  }
}
```

用户选择部分准确或不准确时，接收一句纠正并重新复述，保持本阶段。只有用户选择准确时才建议进入 `partner_response`。

### partner_response

- `allowed_actions`: `continue_to_debrief`、`practice_again`、`pause`、`abandon`
- `roleplay` 使用：

```json
{
  "role": "partner",
  "acknowledgement": "承认影响或在意的点",
  "decision": "accept|negotiate|decline",
  "action_or_alternative": "具体行动、条件或替代方案",
  "full_response": "AI 扮演另一方的完整回应"
}
```

### debrief / completed

- `debrief` 的 `allowed_actions`: `complete_practice`、`practice_again`、`abandon`
- `completed` 的 `allowed_actions`: `practice_again`、`delete_session`
- `final_summary` 使用：

```json
{
  "final_expression": "最终表达",
  "final_paraphrase": "用户确认准确的复述",
  "final_response": "AI 的回应",
  "skill_results": {
    "事实具体性": "未尝试|需调整|已做到",
    "感受准确性": "未尝试|需调整|已做到",
    "需要清楚度": "未尝试|需调整|已做到",
    "请求可执行性": "未尝试|需调整|已做到",
    "复述确认": "未尝试|需调整|已做到",
    "回应明确性": "未尝试|需调整|已做到"
  },
  "one_practice_focus": "下次只练一个重点",
  "strategy_tags": ["稳定、可统计的方法标签"],
  "real_world_outcome": "unknown"
}
```

`real_world_outcome` 在练习完成时必须是 `unknown`。只有用户之后明确确认现实中使用及结果时，应用才能改写结果；模型不得自行标记有效。

## 暂停与安全停止

`paused` 说明当前为什么不适合继续和恢复条件；可继续保存会话，但不推进普通练习步骤。

`safety_stop` 只引用明确危险信号，停止角色扮演和普通沟通优化，`allowed_actions` 仅保留应用支持的安全退出或删除动作。

## 约束

- `record` 始终为 `null`，避免练习写入真实场景复盘。
- 不返回 1–10 分数。
- 不声称已经保存数据库；只返回供调用方持久化的结构。
- 不生成第二份独立“精炼练习记录”；最终总结属于同一个 `practice` 会话。
- 不设置或返回倒计时。
- 不把 AI 的模拟回应描述为现实对方的预测。
