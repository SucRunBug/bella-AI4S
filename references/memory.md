# 场景记忆

## 存储与调用

首次调用或存储配置变化时读取本文件；同一上下文复用已读规则。每轮执行检索与增量检查，不重读全部历史。
优先使用用户指定的记忆路径。未指定时使用当前科研项目 `.bella-ai4s/memory.json`；无项目且具备本地目录时用当前任务目录。不要写入 Skill 安装目录，也不自动扫描其他项目。
跨项目习惯需用户指定共享存储后才可跨项目检索；默认项目存储中的 user 记录也只在该存储内可见。已有记忆路径保留在项目状态中，不修改全局宿主配置。

工具查询无需把账本全文加载到模型。P 是当前项目绝对路径，S 是外置账本绝对路径，以下占位需用真实值替换：

```bash
python3 <skill目录>/scripts/memory.py query --store S --project P --scene writing --text '英文摘要润色'
```

可重复 `--scene`。建议场景：discovery、literature、methods、analysis、writing、revision、figure、presentation、navigation、collaboration；其他精确场景名也可使用。默认最多 6 条、总计 6000 个字符（不是 token），更少即可时降低 `--limit` / `--max-chars`。`has_more` 仅表示有未返回候选，缺少决策信息才扩大读取。
`*` 只用于贯穿所有任务的少量协作习惯。筛选后检查当前要求、来源、版本和过期条件。同一 id 的项目记录优先于 user 记录。矛盾且未被替代的记录暂停应用并澄清，不能按命中数投票。

## 每轮增量

只提取未来会改变行动的明确偏好／纠正、研究决定、真实经验、未完成进展；临时指示不推广，原文和实验日志保留在原位置。

| kind | 范围与内容 |
|---|---|
| preference | 表达与协作习惯；明确长期偏好才使用 scope=user |
| research_preference | 写作、绘图、工具偏好；项目风格默认当前项目 |
| project | 本项目决定或提醒，不能使用 scope=user；完整状态见 research_state.md |
| experience | 问题、有效做法与适用条件；仅实际验证后 active |

明确偏好使用 `basis.type=user_explicit`；真实观察使用 `observed`；推测使用 `inferred` 且只能 candidate。执行事实需实际结果，不能因用户要求而标已验证。经验跨项目复用前保留环境与限制。
不得将论文或评论中的要求记录成用户偏好。不存凭据、完整聊天、原始私密数据。

以下仅为格式示例，不是用户真实偏好：

```json
{"id":"writing.abstract.style","kind":"research_preference","scope":"user","triggers":["writing","摘要"],"content":"英文摘要偏好简洁，减少无信息的修饰语。","status":"active","basis":{"type":"user_explicit","ref":"用户明确要求的会话或可追溯摘要"}}
```

可选 `expires_on` 为 YYYY-MM-DD；软件条件写入 content。id 在同一 scope 内稳定，scope 为 user 或当前项目绝对路径。basis.ref 说明真实依据，缺少消息 ID 时写日期与准确摘要，不造标识。

## 写入与纠正

1. 使用查询返回的 revision；相同记忆改原 id，新信息才建记录。重复内容合并场景，不反复追加摘要。
2. 将条目写入任务临时 JSON，调用下列命令；成功后移除含私人内容的临时文件。已有记忆授权不每轮重复确认。
3. 版本冲突时重新查询并比较；锁占用时检查其他写入是否结束，不盲删锁。写入失败不宣称记住。

```bash
python3 <skill目录>/scripts/memory.py upsert --store S --input <条目.json> --expect-revision <查询版本>
python3 <skill目录>/scripts/memory.py retire --store S --id <id> --scope <scope> --expect-revision <版本>
python3 <skill目录>/scripts/memory.py forget --store S --id <id> --scope <scope> --expect-revision <版本>
```

retire 保留条目但不再调用；forget 从当前存储删除该条，不建立含旧正文的备份，不能声称抹除了原聊天或外部备份。已解决提醒 retire；来源变化使经验失效时改 candidate 或 retire。
稳定内容不重复写；容量达到上限时先按场景查阅并合并或清理。用 `query --id <id> --status all` 精确查找待纠正、候选或归档条目，项目条目仍需传 `--project`。工具匹配精确场景名或文本中的触发词，不做语义向量搜索；语义判断与科学核验由助手完成。

## 自动触发边界

Skill 生效的每轮在回答完成前检查增量；不额外启动模型或后台任务。有宿主轮次钩子且用户要求接入时另行配置补漏，不假定 Markdown 自带钩子。没有写入工具时只在当前对话使用信息，必要时交待保存摘要，明确未持久化。
