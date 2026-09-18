# 暗流涌动 · 血染钟楼线上桌游（毕业设计）

一个支持真人+AI 混玩的多人线上社交推理游戏网站，完整实现《血染钟楼·暗流涌动》官方规则。

## 技术栈

| 层 | 技术 |
|---|---|
| 游戏主服务 | Go + Gin + gorilla/websocket + GORM + SQLite（端口 8741） |
| AI 推理服务 | Python + Flask（端口 8742，DEEPSEEK 降级为本地模板） |
| 前端 | Vue3 + Element Plus（本地 vendor，无构建） |

## 启动

```bash
# 1. 主服务（一键）
cd botc_server
go build -o botc-server.exe .
botc-server.exe
# 或双击 启动服务器.bat

# 2. AI 服务（可选，未启动时 AI 用本地模板降级）
cd ai_service
python main.py
```

访问 http://127.0.0.1:8741

## 功能清单

- 注册/登录（bcrypt）、好友系统、房间邀请链接
- 房间：真人座位 + AI 玩家（本地/大模型）、6-12 人官方人数表
- 完整 22 角色《暗流涌动》规则引擎：官方夜晚顺序、首夜禁刀、中毒机制（信息类假情报/效果类失效/恶魔免疫）、猎手/贞洁者/圣徒/镇长特殊规则
- 夜晚自动推进 + 真人夜间行动（聊天卡片交互、45 秒超时兜底）
- 聊天卡片式交互：夜间技能选择（定向）、私聊（点击玩家条目邀请、面板切换、一对一）、提名（点击条目发起）、投票（面板横幅、可反复切换）
- 提名流程：提名系统消息 → 20 秒辩论（仅双方发言）→ 20 秒投票倒计时 → 统计文案 → 30 秒提名冷却 → 汇总最高票过半处决 → 入夜
- 对局持久化：5 秒落盘、服务重启热恢复、空置 3 分钟自动清理
- 战绩统计 + 历史对局回放（仅参与者可见）
- 观战模式（对局中可旁观）
- 移动端响应式适配

## 目录结构

```
botc_server/
├── main.go                 入口：路由/日志/SQLite
├── internal/
│   ├── engine/             游戏引擎（22 角色、夜晚、提名投票、处决）
│   ├── room/               房间 Actor（相位流转、定时器、私聊、持久化）
│   ├── handler/            HTTP 接口 + WS 事件映射
│   ├── model/              GORM 模型（users/rooms/seats/friends/game_logs）
│   ├── ws/                 WebSocket Hub（房间广播/定向推送）
│   ├── aiclient/           AI 服务 HTTP 客户端
│   └── config/             环境变量配置
└── static/                 前端（Vue3 单文件应用）
ai_service/main.py          AI 推理服务（speak/decide）
```

## 关键环境变量

| 变量 | 说明 |
|---|---|
| BOTC_HUMAN_CHOICE | 真人夜间交互开关（默认 true） |
| DEEPSEEK_API_KEY | 大模型 AI（未配置则模板降级） |

## 测试

```bash
go test -race ./...           # 全量单元测试（引擎/房间/HTTP/WS）
node ui_e2e/*.cjs             # 端到端流程测试（需服务运行中）
```

详见 docs/测试报告.md。
