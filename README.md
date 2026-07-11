 # Blood on the Clocktower

血染钟楼 AI 社交推理游戏 — "暗流涌动" (Trouble Brewing) 规则引擎。

## 版本

| 版本 | 目录 | 说明 |
|------|------|------|
| V2 | Blood on the Clocktower V2 | 增强版 — 角色思维引擎、人格系统、5标签私聊、ML策略训练 |
| V3 | Blood on the Clocktower V3 | 最新独立版 — 下载即玩，无需外部依赖路径 |

## V3 快速启动

```
pip install flask python-docx torch
cd "Blood on the Clocktower V3"
python app.py
# 浏览器打开 http://127.0.0.1:5000
```

## V3 核心改进（相比 V2）

- **规则硬约束**: 圣徒提名拦截、SW 继承限制(仅红唇女郎)、恶魔禁止刀队友
- **信息交叉投票**: 多信息位指向同一人自动叠加投票权重
- **过程奖励训练**: 提名对跳+0.15、刀信息位+0.3、反推好人-0.4
- **导出增强**: 公/私聊分色、人名高亮、恶魔继承标注
- **19视频 → 28战术模式**: 训练 Schema 覆盖好人/邪恶/干扰全场景
