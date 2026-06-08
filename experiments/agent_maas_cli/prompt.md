# 单条信息源活动抽取

从 `source_text` 抽取校园活动事实，只基于原文和输入字段。

输入字段：`source_name`、`source_url`、`reference_date`、`timezone`、`source_text`。

输出字段由工具 schema 约束：

```text
source_name
source_url
events[]
warnings[]

events[*].title
events[*].summary
events[*].start_time
events[*].end_time
events[*].location
events[*].campus
events[*].organizer
events[*].tags
events[*].evidence_text
```

规则：

1. 只抽取原文事实和输入字段，不得编造。
2. `source_name`、`source_url`：输入字段有值则直接使用；输入字段为空时，必须从原文头部 `author:`、`source_url:` 行提取（由 fetch_weixin.py 写入），不得跳过。原文没有 `author:` 行时，从 `#js_name` 或文末署名推断，仍无法确定才填 `null`。
3. 活动、开放日、参观、返校日线下专场、咨询、展览、演出、福利兑换等事项，只要原文给出标题或主题且有时间或地点，即可放入 `events`。
4. 不按日期、地点完整度或链接缺失过滤活动；早于 `reference_date` 的活动也要抽取。
5. 缺失标量填 `null`；缺失数组填 `[]`。
6. 时间尽量转成 ISO 8601 带时区；日期或时间不完整则填 `null`，不要用 `00:00:00` 或 `23:59:59` 补全天时间。当原文出现相对日期（如"今晚"、"明天"、"本周六"）时，以输入的 `reference_date` 为基准推算绝对日期；时区使用输入的 `timezone`（默认 Asia/Shanghai）。
7. `campus` 只能填 `邯郸`、`江湾`、`枫林`、`张江`、`其他`；原文没有明确校区时填 `邯郸`。若 `location` 或原文已能明确推断校区，`campus` 可据此填写。
8. 如果同一活动明确涉及多个校区，拆成多条 `events`，每条只填一个 `campus`，不要把多个校区写在同一个字段里。
9. `organizer` 只填原文明示的主办、承办、组织、举办、发布方或社团名。
10. `summary` 只概括活动事实，不写推荐理由。
11. `evidence_text` 填能支持该活动抽取的短原文片段。
12. `warnings` 只记录无法确定或可能有歧义的抽取问题；没有则为 `[]`。
13. 不输出 `event_id`、`source_file`；这些由批量脚本在聚合时生成。
