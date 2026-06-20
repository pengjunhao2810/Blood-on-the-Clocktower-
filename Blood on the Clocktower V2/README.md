# Blood on the Clocktower V2

血染钟楼 Web 服务器 + AI 训练系统。混合模板 + ML 策略驱动的人机对话版血染钟楼。

## 目录结构

```
Blood on the Clocktower V2/
├── app.py                    # 主游戏服务器 (端口 5000)
├── rules.py                  # 游戏规则引擎
├── roles.py                  # 角色定义 (22个基础角色)
├── dialogue_dataset.py       # 对话模板 (49类)
├── personality.py            # 人格系统 (4种性格)
├── strategies.py             # AI 策略
├── ml_policy.py              # ML 策略网络
├── data/                     # 游戏记录存档
├── training/
│   ├── train_server.py       # AI 训练服务器 (端口 5001)
│   ├── auto_learn.py         # 自动迭代训练
│   ├── train_ml_evil.py      # 邪恶方策略梯度训练
│   ├── training_data.jsonl   # 对话训练数据集 (13MB)
│   ├── config.json           # 训练配置
│   └── requirements.txt      # Python 依赖
├── engine/                   # 共享游戏引擎模块
│   ├── role_mind_engine.py   # 角色思维引擎 (10个角色模型)
│   ├── voting_mixin.py       # 投票逻辑
│   ├── chat_mixin.py         # 对话逻辑
│   ├── ...                   # 其他引擎组件
└── ml_checkpoints/           # ML 模型检查点
```

## 启动方式

### 主游戏服务器
```bash
cd Blood on the Clocktower V2
python app.py
# 访问 http://127.0.0.1:5000
```

### AI 训练服务器
```bash
python training/train_server.py
# 访问 http://127.0.0.1:5001
```

### ML 训练
```bash
python training/train_ml_evil.py
```

## 功能

- 22 个血染钟楼基础角色 (TB 版本)
- 多轮私聊 (3轮 evil/good 分支)
- 角色思维引擎 (10个角色模型)
- 人格系统 (冲动/冷静/话痨/新手)
- 邪恶方 ML 策略 (REINFORCE)
- 5 标签页私聊界面
