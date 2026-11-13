# Submission Log Format

推荐字段：

```markdown
## <timestamp> - <title>

- source_branch: `main`
- target_branch: `judge`
- commit_sha: `<40-character-full-sha>`
- timestamp: `<ISO-8601 timestamp>`
- status: `submitted`
- score:
- score_source:
- score_updated_at:
- score_notes:
- validation: `<commands and result>`
- change_summary: <one paragraph>
- logic_details:
  - <module or behavior changed>
  - <reason for the change>
  - <important implementation detail>
- notes: <follow-up or evaluation context>
```

`score`、`score_source`、`score_updated_at` 和 `score_notes` 首次允许留空。judge 返回后使用 `update-score` 回填。

`change_summary` 要说明用户可见或评测相关变化；`logic_details` 要说明具体模块、控制流、状态转换、验证规则或预算变化。

