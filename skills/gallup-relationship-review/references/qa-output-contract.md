# 一般问答输出契约

调用方选择 `qa` 模式时，只返回一个 JSON 对象，不使用代码围栏，不在 JSON 前后添加说明。

## 完整回答

```json
{
  "version": "2.0",
  "mode": "qa",
  "status": "complete",
  "reply": "给用户看的直接、简洁中文回答",
  "answer": {
    "direct_answer": "先直接回答用户的问题",
    "basis": "说明本次事实、用户明确表达或画像假设的边界",
    "possible_mechanisms": ["最多两个可能机制"],
    "one_next_step": "一个可选、具体、不强迫的动作",
    "uncertainty": "仍需确认的一点；没有则留空"
  },
  "source_labels": [
    {
      "type": "current_event|user_statement|confirmed_success|gallup_profile|relationship_context|regulation_method|communication_method|model_hypothesis",
      "label": "给用户看的来源说明",
      "reference_id": "有关联历史记录时填写，否则留空"
    }
  ],
  "record": null,
  "practice": null
}
```

## 必要澄清

只有缺失信息会实质改变答案时才澄清；最多问一个短问题：

```json
{
  "version": "2.0",
  "mode": "qa",
  "status": "clarifying",
  "reply": "一个最有区分度的短问题",
  "answer": null,
  "source_labels": [],
  "record": null,
  "practice": null
}
```

## 安全停止

```json
{
  "version": "2.0",
  "mode": "qa",
  "status": "safety_stop",
  "reply": "优先处理现实安全的简洁说明",
  "answer": {
    "direct_answer": "停止普通关系分析并说明原因",
    "basis": "只引用用户明确描述的危险信号",
    "possible_mechanisms": [],
    "one_next_step": "一个当前安全动作",
    "uncertainty": "不要猜测未提供的信息"
  },
  "source_labels": [{"type": "current_event", "label": "本次明确危险信号", "reference_id": ""}],
  "record": null,
  "practice": null
}
```

## 约束

- 一般问答不生成真实事件记录，不评分，不自动进入练习。
- `possible_mechanisms` 为 0–2 项；不要堆叠理论。
- 涉及小娌或小元时，画像只能出现在 `basis` 或来源标签中并标明是假设。
- `one_next_step` 是可选建议，不把原谅、和好或维持关系设为默认目标。
- 没有用户确认的现实结果时不得使用 `confirmed_success`。
