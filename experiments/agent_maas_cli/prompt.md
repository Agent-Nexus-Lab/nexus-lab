# 单条信息源活动抽取

从 `source_text` 抽取校园活动事实，只基于原文和输入字段。

输入字段：`source_name`、`source_url`、`source_platform`、`title`、`publish_time`、`reference_date`、`timezone`、`source_text`。

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

1. 只抽取原文事实和输入字段，不得编造。原文可能来自网页抓取（cn8n），可能包含导航栏、广告、页脚、HTML 实体残留等干扰文本，这些不应被当作活动事实。
2. `source_name`、`source_url`：**必保字段**，输入字段提供时必须原样回传，不可为空、不可编造、不可替换。输入为空时尝试从原文推断；原文无来源信息则在 `warnings` 中记录 "source_url missing" 或 "source_name missing"。
3. 活动、开放日、参观、返校日线下专场、咨询、展览、演出、福利兑换等事项，只要原文给出标题或主题且有时间或地点，即可放入 `events`。
4. 不按日期、地点完整度或链接缺失过滤活动；早于 `reference_date` 的活动也要抽取。
5. 缺失标量填 `null`；缺失数组填 `[]`。
6. 时间尽量转成 ISO 8601 带时区；日期或时间不完整则填 `null`，**严禁用 `00:00:00` 或 `23:59:59` 补全天时间**。当原文出现相对日期（如"今晚"、"明天"、"本周六"）时，以输入的 `reference_date` 为基准推算绝对日期；时区使用输入的 `timezone`（默认 Asia/Shanghai）。**时间字段只能使用原文明示的信息，不得推算、猜测或补全。**
7. `campus` 只能填 `邯郸`、`江湾`、`枫林`、`张江`、`其他`；原文没有明确校区时填 `邯郸`。若 `location` 或原文已能明确推断校区，`campus` 可据此填写。
8. 如果同一活动明确涉及多个校区，拆成多条 `events`，每条只填一个 `campus`，不要把多个校区写在同一个字段里。
9. `organizer` 只填原文明示的主办、承办、组织、举办、发布方或社团名。
10. `summary` 只概括活动事实，不写推荐理由。
11. `evidence_text` **必须直接从原文引用**，禁止自行概括或编造。用于后续复核和回溯，应逐字引用原文中支持该活动抽取的片段。
12. `warnings` 只记录无法确定或可能有歧义的抽取问题；没有则为 `[]`。**如果 `source_url` 缺失或为空，必须记录 "source_url missing"；如果 `source_name` 缺失或为空，必须记录 "source_name missing"。**
13. 不输出 `event_id`、`source_file`；这些由批量脚本在聚合时生成。
14. `source_platform` 填写平台标识（`wechat` / `website` / `other`），输入未提供时不填。`title` 和 `publish_time` 来自输入的 `title` 和 `publish_time` 字段，不另从原文提取。
