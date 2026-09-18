# 暗流涌动 — 线上血染钟楼（Go 重构版）

> 基于《血染钟楼·暗流涌动》的多人在线社交推理桌游
> 异构微服务架构：Go 游戏主服务 + Python AI 推理服务 + Vue3 前端

---

## 快速开始

```bash
# 1. 启动 Go 游戏主服务（端口 8741）
botc_server/start_server.bat

# 2. 启动 Python AI 推理服务（端口 8742，可选）
ai_service/start_ai.bat

# 3. 浏览器打开 http://127.0.0.1:8741
```

> 不启动 AI 服务也能玩：夜晚行动自动回退随机策略；API 型 AI 公聊静默跳过。

---

## 功能清单

- 用户注册/登录（session cookie，WS 连接认证）
- 好友系统：搜索/申请/同意/拒绝/删除，在线状态实时推送（5 秒防抖）
- 房间：创建/加入/公聊/准备/人数设置/AI 席位（本地 + 大模型）
- 房间邀请：房主邀请在线好友 → 好友接受入座（一人一房互斥校验）
- 对局：暗流涌动剧本 22 角色、官方人数表、匿名编号、昼夜阶段、提名处决、特殊规则（红唇女郎继承/小恶魔自杀传位/贞洁者/猎手/圣徒/镇长/占卜师红鲱鱼/酒鬼伪装）
- 断线重连 + 刷新恢复（sessionStorage + 快照回执）
- 对局结束归档（game_logs）

## 架构

```
浏览器 (Vue3 + Element Plus)
   │  HTTP（仅认证/建房/静态）
   │  WebSocket（全部实时交互）
   ▼
Go 游戏主服务 (Gin + gorilla/websocket)
   │  Hub：连接注册表（房间广播域 / 用户定向推送 / 上下线防抖回调）
   │  Room Actor：每房间一个 goroutine，事件 channel 串行驱动
   │  FriendService：好友业务 + 内存邀请（TTL + 懒删除 + 房间销毁清理）
   │
   ├── SQLite (GORM)     用户/房间座位镜像/好友关系/对局日志
   │
   └── HTTP ──► Python AI 服务 (Flask)      ← 仅负责大模型推理
                     └─► DeepSeek API（未配置 Key 时模板降级）
```

| 层级 | 技术 | 职责 |
|------|------|------|
| 后端 | Go 1.27 + Gin + gorilla/websocket + GORM | WS 长连接、房间 Actor、对局流程、好友、广播 |
| AI | Python Flask + requests | 大模型发言/决策，HTTP 解耦，超时回退 |
| 前端 | Vue3 + Element Plus（本地化 vendor） | 单页应用，纯 WS 通信（无轮询） |
| 视觉 | Linear/Modern 设计系统 | 深空底色、氛围光斑、多层阴影、聚光灯微交互 |
| 存储 | SQLite（GORM 自动迁移） | 用户/房间/好友/对局日志 |

## WS 协议

```jsonc
// 客户端 → 服务端（带请求 id，服务端 ack 回执）
{"event": "room.chat", "data": {"room_code": "A1B2C3", "content": "..."}, "id": 7}
{"event": "friend.request", "data": {"friend_id": 3}, "id": 8}
{"event": "room.invite_friend", "data": {"room_code": "...", "friend_id": 3}, "id": 9}
{"event": "room.invite_accept", "data": {"room_code": "..."}, "id": 10}

// 服务端 → 房间广播
room.state / room.message / game.started / game.state / game.phase / game.message
game.nominate / game.over / room.ended / room.disbanded

// 服务端 → 单人定向
game.story（说书人私密信息）
friend.request / friend.accepted / friend.removed / friend.online / room.invite
```

## 核心设计（论文亮点）

### 1. 每房间一个 goroutine（Actor 模型）

运行时状态（座位、聊天、对局）全部内存化，**DB 不参与实时路径**。
所有修改指令通过 `events chan Event` 投递，由房间 goroutine 串行执行——天然免锁，
是「不要通过共享内存通信，而要通过通信共享内存」的教科书式落地。
单个房间 panic 被 recover 隔离，不影响其他进程与服务进程。

### 2. WebSocket 全双工指令协议（无轮询）

HTTP 只保留：认证、建房入口、静态资源。聊天/指令/广播/私密信息全部走 WS。

### 3. 断线重连与会话恢复

- WS 断开后前端指数退避自动重连，重连后自动 `room.join` 拉全量快照
- 刷新页面（sessionStorage 记录所在房间）恢复房间/对局视图与历史消息
- 服务重启：等待中房间从 DB 座位镜像恢复；进行中对局回滚为等待状态

### 4. 好友系统与在线状态

- friends 表规范化存储（ID 升序 + 组合唯一索引），从存储层杜绝反向双插
- 上下线回调 + 5 秒防抖：断线延迟确认（期间重连零广播），杜绝抖动刷屏
- 房间邀请内存化（TTL 5 分钟），接受时二次校验好友关系与房间状态

### 5. 对局日志落盘

对局结束时把终局玩家状态、公聊记录、说书人信息整体归档到 `game_logs` 表，
为历史记录/回放功能打底（选做）。

## 项目结构

```
botc_server/
├── main.go                    # 入口：DB、Hub、房间恢复、好友回调注入、路由
├── internal/
│   ├── config/config.go       # 环境变量配置
│   ├── model/model.go         # GORM 模型（users/rooms/room_seats/friends/game_logs）
│   ├── ws/                    # WebSocket Hub + Client（心跳/缓冲/慢客户端断开/防抖回调）
│   ├── room/                  # 房间 Actor：manager（注册表/恢复）+ room（事件循环）
│   ├── engine/                # 游戏引擎（暗流涌动 22 角色 + 官方规则，纯内存无 IO）
│   ├── aiclient/client.go     # Python AI 服务 HTTP 客户端（AIDecider 接口）
│   └── handler/               # HTTP（认证/建房）+ WS 指令路由 + 好友服务
└── static/                    # 前端（Vue3 SPA + Linear/Modern 设计系统）
ai_service/
└── main.py                    # AI 推理服务（/api/speak /api/decide）
```

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| BOTC_ADDR | 127.0.0.1:8741 | 监听地址 |
| BOTC_DB_PATH | exe 同目录 data/botc.db | SQLite 路径 |
| BOTC_AI_URL | http://127.0.0.1:8742 | AI 服务地址 |
| BOTC_AI_CHAT_INTERVAL | 30 | AI 公聊间隔（秒） |
| BOTC_HUMAN_CHOICE | false | 真人夜晚交互选择开关：默认关闭（夜晚全自动推进，演示流畅）；开启后真人占卜师/管家挂起等待手动选择（45 秒超时兜底） |
| DEEPSEEK_API_KEY | 空 | 未配置时 AI 用模板发言降级 |

## 测试

```bash
go test ./... -race   # 引擎规则/房间事件循环/好友服务/邀请存储/Hub 防抖 全量单测
```

已通过的端到端验证：好友申请-同意-拒绝 → 邀请-接受入座（含多房间互斥）→ 真人+AI 混合对局
→ 断线重连恢复 → 对局归档 → 房间解散 → 纯 AI 老流程回归。
