# 应用结构化输出契约

应用调用时只返回一个 JSON 对象，不要使用代码围栏，也不要在 JSON 前后添加说明。

## 澄清阶段

```json
{
  "status": "clarifying",
  "reply": "一次只问 1–3 个短问题",
  "record": null
}
```

信息不足时不得生成分数或长期记录。不要重复用户已经回答的问题。

## 完成阶段

```json
{
  "status": "complete",
  "reply": "给用户看的简洁中文分析",
  "record": {
    "question_summary": "不超过 80 字，只写事件与核心矛盾",
    "scene_type": "仪式感|危机管理|情感支持|共同活动|家庭责任|日常交流|未来规划|其他",
    "occurred_at": "用户明确给出时写事件时间，否则留空",
    "roles": "本次谁提出需求、谁回应，情感场景写明谁倾诉、谁支持",
    "observed_facts": "只写用户明确描述的关键言行，不写推测",
    "keywords": ["2–6 个便于检索的词"],
    "inner_expectation_me": "用户一方的内在期待",
    "inner_expectation_partner": "对方的内在期待",
    "talent_state_me": "相关才干、状态与行为证据",
    "talent_state_partner": "相关才干、状态与行为证据",
    "interaction_loop": "触发到升级或断联的短链路",
    "communication_guidance": "沟通策略",
    "recommended_wording": "一段可直接说出口的话",
    "behavior_feedback": "只评价用户本次可观察行为",
    "behavior_score": 1,
    "behavior_dimensions": {
      "期待表达": "未出现|有尝试|已做到|证据不足，并附短证据",
      "才干调节": "未出现|有尝试|已做到|证据不足，并附短证据",
      "回应对方": "未出现|有尝试|已做到|证据不足，并附短证据",
      "合作修复": "未出现|有尝试|已做到|证据不足，并附短证据"
    },
    "score_reason": "评分证据及再提高 1 分的动作",
    "progress_assessment": "进步|持平|反复|暂无基线，并说明与相似历史的关系",
    "next_action": "24–72 小时内可验证的小行动",
    "uncertainty": "仍需向双方验证的一点",
    "confidence": "高|中|低，并说明限制"
  }
}
```

`behavior_score` 只能是 1–10 的整数；证据不足时必须为 `null`。所有字符串写精炼结论，不复制整段原始聊天。`reply` 可使用短标题和项目符号，但必须与 `record` 一致。
