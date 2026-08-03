# 血染钟楼 AI 项目 (Blood on the Clocktower AI)

## 项目概述

基于 Flask 的血染钟楼·暗流涌动 12 人对局模拟系统。AI 玩家由模板系统驱动，支持完整游戏流程：夜晚行动、私聊、公聊、提名投票。

## 版本

| 版本 | 目录 | 说明 |
|---|---|---|
| V1 | `Blood on the Clocktower V1/` | 初始版本，基础游戏引擎 |
| V2 | `Blood on the Clocktower V2/` | 对话系统优化，私聊记录导出 |
| V3 | `Blood on the Clocktower V3/` | 人类化思考系统、角色专属模板、间谍全知 |
| **V4** | **`Blood on the Clocktower V4/`** | **精简版，清理垃圾文件，稳定对局** |

## V4 快速开始

```bash
cd "Blood on the Clocktower V4"
pip install -r requirements.txt
python app.py
```

打开 http://127.0.0.1:5000

## V4 主要改进

- 死人名字过滤：私聊发言自动替换已死亡玩家名
- 身份不明替换：自动查 claim_map 填实际声称
- 自引用防止："X和X互动"自动修正
- 间谍全知：SPY_KNOWLEDGE_TALK / SPY_PRECISE_ACCUSE 专属话术
- 死人去重：夜间死亡列表消除重复
- 精简代码：删除测试/训练脚本，只保留运行必需文件

## 目录结构

```
Blood on the Clocktower V4/
  app.py              ← Flask 网站主程序
  start_server.bat    ← 一键启动
  games/              ← 游戏引擎
    blood_on_clocktower/
      rules.py            ← 主引擎（日夜流程、投票处决）
      dialogue_dataset.py ← 对话模板（48+类模板）
      roles.py            ← 22角色定义
      personality.py      ← 4种人格系统
      dialogue_generator.py ← 对话生成器
      template_generator.py ← 模板碎片组合
      llm_filler.py       ← LLM接口（备用）
  core/               ← AI 代理
  engine/             ← 引擎辅助

## 游戏规则

22个角色 · 暗流涌动剧本。详细规则见 `games/blood_on_clocktower/rules.py`。

## 导出功能

- `/export` — 导出完整对局 Word 文档
- `/export_chat` — 导出纯私聊记录
- `/private_chat` — 在线查看私聊记录
