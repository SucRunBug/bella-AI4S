# 项目状态与证据契约

## 最小持续项目

适配现有目录，不强制搬动。新项目需要续接时运行 `scripts/init_project.py`，创建 `research_state.md`、`evidence.json`、`experiments.jsonl`。代码、数据、图、稿按需再建。小任务不用初始化。
状态记录问题、研究类型、预算、决定及原因、完成产物、未解问题、下一步，以及正在使用的记忆存储路径。场景习惯与可复用经验见 [记忆规则](memory.md)，项目状态不重复搬进全局记忆。废弃结论标被替代，不删除反例；输入变化或产物失效时依赖 claim 改回待核验。

## 证据结构

顶层：`schema_version: 1`、`sources: []`、`claims: []`。
以下仅为字段说明，非真实研究证据。

来源对象：

```json
{"id":"S001","kind":"literature","title":"真实来源标题","url":"https://来源稳定页面","identifier":"真实标识，无则省略","identity_status":"unverified","access":"abstract_only"}
```

- `kind`：`literature`／`experiment`／`dataset`／`other`。
- `identity_status`：`verified`／`unverified`／`conflict`。verified 必须补 `identity_checked_at`（YYYY-MM-DD）和 `identity_basis`（实际比对依据）。
- `access`：`metadata_only`／`abstract_only`／`full_text`／`local_artifact`。
- 本地材料用 `artifact` 指向账本所在目录内的相对文件；实验必须使用 local_artifact 和真实非空结果，不能拿计划当结果。外部材料用 http(s) URL。
- 身份核对包括题名、作者、年份、标识、版本；不一致记 conflict。verified 是登记状态，仍可能误填。

论断对象：

```json
{"id":"C001","text":"一条具体论断","status":"needs_evidence","use_in_output":true,"evidence":[{"source_id":"S001","locator":"页/节/图表/结果字段","relation":"supports","note":"支持什么，不能支持什么"}]}
```

- `status`：`supported`／`needs_evidence`／`contradicted`。
- `relation`：`supports`／`contradicts`／`context`。保留冲突，不能投票覆盖；有冲突先缩小结论或处理冲突。
- `use_in_output`：是否拟作为事实放入下游产物。研究假设置 false 并注明假设身份。
- 每个 claim 单独核验；不能来源身份通过就接受其所有引用。

## 本地检查

`python3 <skill目录>/scripts/audit_evidence.py <项目>/evidence.json`

退出码 0：登记和依赖完整；1：证据缺口或不一致；2：输入格式／读取错误。空账本为 incomplete。
检查重复／悬空 ID、本地文件、supported 来源身份与定位、摘要／元数据限制，以及拟用于产物但未支持的论断。
这是保守的机械检查，不联网、不读文件语义、不验证 DOI 真伪、统计或科研质量。摘要可以支持的小范围论断仍需人工核对访问限制；禁止为通过检查虚报 full_text。

## 归档

归档输入／代码／环境版本、真实运行命令、图表数据、引用、局限、未解问题与访问限制。公开包和私密数据分开，不自动公开。复现包应有新目录实际重跑记录或明确未运行说明。
