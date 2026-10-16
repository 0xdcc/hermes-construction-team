# Hermes 施工团队 · construction-team

给 [Hermes Agent](https://hermes-agent.nousresearch.com) 加一个**三级施工团队**：

```
总控（你当前的聊天窗口）
 └─ 主管 ×N（持久会话，一个模块一个，可单独指定模型）
     └─ 工人 ×M（临时子代理，干完即散）
```

适合跨多个模块、需要分别验收的大活。全部基于 Hermes 原生会话与子代理，不改官方源码，不另开端口。

## 两种用法

**1. 在聊天里直接开工（推荐）**

聊到一个复杂需求时直接说：

> 用三级施工做这个，主管用 sonnet，工人用 flash

助手会：整理任务书 → 出一张**确认卡**（总控=当前窗口模型、各级真实模型、模块、项目目录、并发）→ 你回复“开工”后才建团队派活。确认前不创建任何东西、不调用施工模型。主管的回报自动推回这个窗口，助手核验后验收或返修。

- 模型可以说口语名（`sonnet`、`flash`），会对到你 Hermes 里配置的真实模型；有歧义会列候选让你挑，不猜。也可写 `模型ID@provider`。
- 新项目会在项目区建空目录并做 git 初始提交；已有内容的目录一律不动。
- `/team` 看状态，`/team help` 看用法。

**2. 桌面面板**

侧栏「施工团队」：新建团队、选各级模型、派任务、看主管/工人状态、验收或驳回。主管会话可用**标签页**或**独立窗口**打开（只是展示方式不同，关掉不等于停工）。

## 安装

**服务端（运行 Hermes 后端的机器）**

```bash
hermes plugins install 0xdcc/hermes-construction-team
hermes plugins enable construction-team
```

**每台桌面客户端**：插件页 →「从 Git 安装」→ 填 `https://github.com/0xdcc/hermes-construction-team`，勾选**桌面**目标。
客户端连的是远程后端时，插件页会显示「不可用（远程后端）」，就是因为本机还没有桌面部分，装一次即可。

## 配置（可选）

在 `config.yaml` 的 `plugins.entries.construction-team` 下：

| 键 | 默认 | 说明 |
|---|---|---|
| `supervisor_model` / `worker_model` | 见代码 | 默认主管/工人模型 |
| `max_active_supervisors` / `max_workers` | 2 / 4 | 并发上限（1～8） |
| `projects_base` | `~/projects` | 允许自动新建项目目录的根 |
| `allow_gateway_injection` | — | 需为 `true`，主管回报才能推回聊天 |

## 边界

- 工区隔离和只读角色是**协作约束，不是安全沙箱**，只在你授权的项目里用。
- 工人沿用主管的 provider 路由。
- 插件不会自动合并、推送、部署，也不会删除脏工区。
- 已测 Hermes **v0.21.6**；其他版本请自行验证。

## License

MIT © [@0xdcc](https://github.com/0xdcc)
