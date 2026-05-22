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
2. `source_name`、`source_url` 优先使用输入字段；没有输入时，若原文第一行或署名行是账号/社团/机构名，可填入 `source_name`，否则填 `null`。
3. 活动、开放日、参观、返校日线下专场、咨询、展览、演出、福利兑换等事项，只要原文给出标题或主题且有时间或地点，即可放入 `events`。
4. 不按日期、地点完整度或链接缺失过滤活动；早于 `reference_date` 的活动也要抽取。
5. 缺失标量填 `null`；缺失数组填 `[]`。
6. 时间尽量转成 ISO 8601 带时区；日期或时间不完整则填 `null`，不要用 `00:00:00` 或 `23:59:59` 补全天时间。
7. `campus` 只填原文明确出现的校区词或“某某校区”；不得根据建筑名、学校名推断。
8. `organizer` 只填原文明示的主办、承办、组织、举办、发布方或社团名。
9. `summary` 只概括活动事实，不写推荐理由。
10. `evidence_text` 填能支持该活动抽取的短原文片段。
11. `warnings` 只记录无法确定或可能有歧义的抽取问题；没有则为 `[]`。
12. 不输出 `event_id`、`source_file`；这些由批量脚本在聚合时生成。
