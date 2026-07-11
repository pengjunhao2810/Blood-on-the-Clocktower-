# Blood on the Clocktower V2

**血染钟楼 · 混合模板 + 角色思维引擎版**

基于 Trouble Brewing (暗流涌动) 剧本的 AI 驱动社交推理游戏。V2 在 V1 规则引擎基础上，新增了**角色思维引擎 (RoleMind)**、**人格系统**、**5 标签页私聊界面**、**邪恶方 ML 策略训练**等核心功能。

---

## 功能特色

- **22 个血染钟楼基础角色** — 完整实现 Trouble Brewing 剧本，含士兵/僧侣/小恶魔/占卜师等
- **多轮私聊系统** — 每人每天与 2 名玩家私聊，各 2 轮，evil/good 各有不同对话分支
- **角色思维引擎 (RoleMind)** — 10 个角色专属思维模型，含目标/关注点/自然疑问/怀疑触发
- **人格系统 V2** — 4 种鲜明性格 (冲动型/冷静型/话痨型/新手型)，影响句子长度、语气、确定性
- **5 标签页私聊界面** — 💬 私聊记录 / 📜 说书人信息 / 🌙 夜晚顺序 / 📋 角色能力 / 🗳️ 提名记录
- **邪恶方 AI 策略** — 优先杀信息位、优先提名权、投票策略、恶魔-爪牙协调
- **ML 策略训练** — 基于 REINFORCE 的策略梯度训练，模型保存为 PyTorch 检查点
- **13MB 对话数据集** — 49 类对话模板 + 训练对话记录

---

## 目录结构

```
Blood on the Clocktower V2/
├── app.py                        # 主游戏服务器 (Flask, 端口 5000)
├── rules.py                      # 游戏规则引擎 (153KB, 核心)
├── roles.py                      # 角色定义 (22个基础角色)
├── dialogue_dataset.py           # 对话模板 (49类)
├── personality.py                # 人格系统 V2 (4种性格)
├── strategies.py                 # AI 策略
├── ml_policy.py                  # ML 策略网络
├── data/                         # 游戏记录存档 (JSON)
├── training/
│   ├── train_server.py           # AI 训练服务器 (Flask, 端口 5001)
│   ├── auto_learn.py             # 自动迭代训练脚本
│   ├── train_ml_evil.py          # 邪恶方策略梯度训练
│   ├── training_data.jsonl       # 对话训练数据集 (13MB, 16000+条)
│   ├── config.json               # 训练配置
│   └── requirements.txt          # Python 依赖
├── engine/                       # 共享游戏引擎模块
│   ├── role_mind_engine.py       # 角色思维引擎 (10个角色模型)
│   ├── voting_mixin.py           # 投票/提名逻辑
│   ├── chat_mixin.py             # 对话逻辑
│   ├── evil_mixin.py             # 邪恶方 AI 策略
│   ├── night_mixin.py            # 夜晚行动逻辑
│   ├── private_chat_mixin.py     # 私聊逻辑
│   ├── game.py                   # 游戏管理器
│   └── ...                       # 其他辅助模块
└── ml_checkpoints/               # ML 模型检查点
    ├── policy_step200.pt
    ├── policy_step400.pt
    └── policy_stepfinal.pt
```

---

## 快速开始

### 环境要求

- Python 3.10+
- Flask 3.x

```bash
pip install flask
```

### 启动主游戏服务器

```bash
cd "Blood on the Clocktower V2"
python app.py
```

打开 http://127.0.0.1:5000

### 启动 AI 训练服务器

```bash
python training/train_server.py
```

打开 http://127.0.0.1:5001

### 运行 ML 训练

```bash
python training/train_ml_evil.py
```

训练 4000 局，模型保存至 `ml_checkpoints/`

---

## 界面说明

主服务器 (端口 5000) 提供两个页面：

| 页面 | 路径 | 说明 |
|------|------|------|
| 游戏主界面 | `/` | 玩家卡片、游戏日志、角色配置、操作按钮 |
| 私聊记录 | `/private_chat` | 5 标签页：私聊气泡 / 说书人信息 / 夜晚顺序 / 角色能力 / 提名记录 |

### API 端点

| 路径 | 返回 |
|------|------|
| `/state` | 完整游戏状态 (玩家、日志、私聊线程、投票、提名) |
| `/storyteller_info` | 每位玩家的首夜信息 |
| `/role_data` | 角色列表、阵营、夜晚顺序 |

---

## 技术架构

### 角色思维引擎 (RoleMind)

`engine/role_mind_engine.py` 包含 10 个角色专属思维模型：

| 角色 | 目标 | 核心关注点 |
|------|------|-----------|
| 占卜师 | 验出恶魔 | 昨夜结果、伪装者矛盾 |
| 洗衣妇 | 验证身份 | 角色声称可信度 |
| 厨师 | 获取邻座信息 | 邪恶阵营相邻数 |
| 共情者 | 感知邪恶 | 座位邻居的可疑度 |
| 士兵 | 存活 | 夜间被杀风险 |
| 僧侣 | 保护他人 | 守护目标的选择 |
| 调查员 | 找出爪牙 | 角色声称的验证 |
| 送葬者 | 确认死者身份 | 死者角色信息 |
| 猎手 | 找到恶魔 | 技能目标的选择 |
| 小恶魔 | 生存+误导 | 暴露风险、爪牙协调 |

### 人格系统

4 种性格影响发言风格：

- **冲动型** — 短句、高感叹号频率 (40%)、高确定性 (0.85)
- **冷静型** — 中等长度、低感叹号 (5%)、高确定性 (0.75)
- **话痨型** — 长句延伸、中等感叹号 (15%)、中等确定性 (0.65)
- **新手型** — 短句、低确定性 (0.35)、更多疑问表达

### 私聊流程

1. 每轮选择对话对方
2. `_extract_chat_context()` 提取对方上条信息的关键词 (问题/指控/角色声称/立场)
3. 模板填充 + 35% 概率追加角色思维引擎生成的自然疑问
4. 通过 `apply_personality()` 应用性格风格
5. 3 轮对话后自动结束

---

## 已知限制

- 仅支持 Trouble Brewing (暗流涌动) 剧本
- 所有 AI 对话为规则驱动 (无 LLM 调用)
- 界面标签和聊天内容为中文
- 开发用 Flask 服务器，不适用于生产环境
- Qwen2-VL-2B 因 4GB 显存限制已禁用

---

## License

MIT
