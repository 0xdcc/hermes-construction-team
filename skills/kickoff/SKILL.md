---
name: kickoff
description: "Use when 用户在聊天中要求三级施工/施工团队/开工复杂项目. 当前窗口作总控、确认卡后开工."
version: 0.2.0
author: "@0xdcc"
license: MIT
---

# 对话内开启三级施工

用户在当前窗口说“用三级施工/施工团队做这个”时使用。**当前对话就是总控**，前面聊过的内容就是任务书底稿。工具：`construction_team`（旧会话看不到时先 `tool_search` 加载）。

## 1. 先判断值不值得上三级

- 只有 1 个模块、或几分钟能完成：建议用普通子代理，说明理由，用户坚持再继续。
- 3 个以上需分别验收的模块、跨多文件/多天的大活才是三级的主场。

## 2. 整理任务书（不调用工具）

从对话中提炼，缺的才问，一次问完：
- 目标与可见成果；非目标；禁止动作（生产、发布、付费、凭据等）。
- 模块拆分：每个模块 = 一个主管，写 `name`、`goal`、`acceptance`（可验证）、`depends_on`。
- 项目目录：已有仓库给绝对路径；新项目给 `category` + `project`（落在项目区 `<projects_base>/<分类>/<项目>/`，默认 `~/projects`，可在插件配置 `projects_base` 改）。
- 模型：用户口语说的主管/工人/顾问模型原样传；没说就用插件默认值。总控模型就是本窗口模型，不能另指定，要换让用户先 `/model`。

## 3. 出确认卡

调用 `construction_team` `action=plan`，payload 含 `name`、`root` 或 `category/project`、`models`（`{supervisor, worker, advisor?}` 口语名）、`modules`、可选 `max_active_supervisors`/`max_workers`（1～8）。

按返回值给用户一张简短卡片：

| 项 | 内容 |
|---|---|
| 总控 | 当前窗口 · `coordinator.model` |
| 主管 / 工人 / 顾问 | 解析出的真实模型ID（标明 provider 或“继承”） |
| 模块 | 名称 · 目标一句话 · 依赖 |
| 目录 | 路径 · 是否需要新建 |
| 并发 | 主管 N · 工人 M |

- `blockers` 非空：逐条讲清并给选项（模型 `ambiguous` 列候选让用户挑，不猜）。改完重新 `plan`。
- 有 `advice`、`worker_note` 时一句话带上。
- 结尾明确问：“回复**开工**就建团队并派活”。**确认前不调用 `prepare_root`/`create`/`add_supervisor`/`dispatch`。**

## 4. 用户确认后开工

1. 目录需新建：`prepare_root` 带 `confirmed:true`（只会在项目区建空目录 + git 基线；已有内容不动，报错就停下问用户）。
2. `create`：`name`、`root`、`settings`（`supervisor_model`/`worker_model`/可选 provider、并发、advisor）。**不传 `coordinator_key`、`coordinator_model`、`coordinator_provider`**，宿主会自动绑定本窗口。`request_key` 用稳定值如 `kickoff-<项目>-create`。
3. 每个模块 `add_supervisor`（模块单独指定模型时传 `model`），再 `dispatch` 任务（`member_id`、`title`、`goal`、`acceptance`、`forbidden`、`depends_on` 用真实 task id）。
4. 回报一行：团队ID、几个主管已派活、在桌面“施工团队”页或 `/team` 看进度。

## 5. 施工中

- 主管回报会自动推回本窗口（`[施工团队回报:...]`）。自己核验产物/命令/测试后再 `review`：`accept` 必须带真实证据；不行就 `reject` 写清返修点（三轮仍不过会自动阻断，转为与用户复盘）。
- 给用户的汇报保持短：通过/返修/卡住各几项，需要用户拍板的单列。
- 用户说暂停/继续/停止：对应 `pause`/`resume`/`stop`。关闭主管窗口或标签页不等于停工。
- 不扩大目标、不自动发布或改生产；需要额外授权的动作先问用户。
