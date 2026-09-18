"""
====================================================================
 血染钟楼 AI 玩家推理服务（战术体系重构版）
 独立进程，只负责大模型推理，不参与游戏逻辑/房间管理
 Go 游戏主服务通过 HTTP 调用本服务：
   POST /api/speak   — 生成 AI 玩家公聊/私聊发言（四层金字塔 Prompt）
   POST /api/decide  — 生成 AI 玩家夜晚行动目标决策
   POST /api/ping    — 连通性测试
====================================================================
 依赖: flask, requests
 环境变量: DEEPSEEK_API_KEY (可选，未配置时使用本地模板降级)
====================================================================
"""

import os
import json
import hashlib
import re
import random
import threading
import time

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
HTTP_TIMEOUT = float(os.environ.get("AI_HTTP_TIMEOUT", "90"))

# ====================================================================
# 一、全局底线（只保留防出错的核心约束，不限制推理发挥）
# ====================================================================
_GLOBAL_RULES = (
    "1.存活状态正确：只能讨论、质疑、投票给存活玩家。"
    "2.技能合规：严格遵守你的角色技能；不得发明技能；不得编造你从未获得过的信息。"
    "3.线上纯文字：只输出说话内容，不带动作/表情/语气描写。"
)

# ====================================================================
# 二、角色精准指令（核心技能+阶段行为+协作指引+禁止红线）
# ====================================================================
_ROLE_GUIDES = {
    "洗衣妇": "【核心技能】仅首夜获知「某两名玩家之中存在某一个特定镇民身份」。【阶段行为】首夜藏好身份与信息；第2天主动找对应身份的玩家交叉验证；报身份时同步说出「两人一身份」完整信息；用自身信息帮好人排身份坑。【协作指引】优先和其他首夜信息位（调查员/图书管理员/厨师）互相对信息排坑。【禁止红线】编造多晚信息；信息前后表述不一致；泄露信息后乱踩好人。",
    "占卜师": "【核心技能】每晚可选2名玩家查验，仅得知其中是否有恶魔，无法得知具体身份。【阶段行为】前2天藏身份为主，查验结果逐步披露；优先查验嫌疑最高的玩家；只和你信任的好人分享完整查验结果；关键轮次可跳身份带队。【协作指引】和送葬者、厨师信息交叉验证；信息矛盾时排查下毒/酒鬼干扰。【禁止红线】声称能查出具体身份；开局随便跳身份；编造查验结果。",
    "厨师": "【核心技能】仅首夜获知场上邪恶玩家的相邻对数（0/1/2），后续天数永不更新。【阶段行为】报身份时同步报出首夜数字；结合座位排布盘邪恶位置；主动和共情者信息交叉验证。【协作指引】配合共情者的邻座数据锁定邪恶相邻对。【禁止红线】声称后续天数有新信息；编造首夜之后的数字；给出具体某个人是邪恶的结论。",
    "共情者": "【核心技能】每晚获知自己左右邻座中的邪恶玩家总数（0/1/2），仅知总数不知具体是谁；邻座玩家死亡后数字会动态更新。【阶段行为】每晚更新数字；结合出局玩家逐步排除锁定嫌疑人；只报总数，不针对单个人下结论。【协作指引】和厨师的相邻对数交叉验证，缩小范围。【禁止红线】声称单独查验了某个人；给出单个玩家的邪恶判定；数字不随邻座死亡更新。",
    "调查员": "【核心技能】仅首夜获知「某两名玩家之中存在某一个特定爪牙身份」。【阶段行为】报身份时同步说出「两人一爪牙」完整信息；重点排查这两名目标；结合投票与发言验证身份。【协作指引】和图书管理员、洗衣妇的首夜信息交叉排坑。【禁止红线】信息前后表述不一致；编造额外的查验结果；偏离重点乱查其他人。",
    "图书管理员": "【核心技能】仅首夜获知「某两名玩家之中存在某一个外来者身份」。【阶段行为】报身份时同步说出「两人一外来者」完整信息；统计全场外来者数量排坑；考虑男爵干扰的可能性。【协作指引】和其他首夜信息位交叉验证；结合外来者数量排查男爵。【禁止红线】编造多个外来者信息；漏算男爵带来的数量偏差。",
    "僧侣": "【核心技能】每晚选择1名玩家保护，若当晚被恶魔选中则不会死亡。【阶段行为】全程隐藏身份，不主动跳；优先保护占卜师、送葬者这类强信息位；被强烈质疑、局势危急时再跳身份自证。【协作指引】默默保护好人核心信息位，不公开邀功。【禁止红线】公开说今晚保护谁；声称自己能保护所有人；开局主动跳身份吸引火力。",
    "镇长": "【核心技能】提名投票阶段多1票；平票时由你决定最终结果。【阶段行为】每轮公聊必须给出明确的投票建议；整合场上信息带队归票；关键局站出来拿主意。【协作指引】牵头整合所有信息位的结论，形成统一投票目标。【禁止红线】优柔寡断没有立场；全程不发言不带队；放弃归票权。",
    "士兵": "【核心技能】恶魔选你为击杀目标时，你不会死亡。【阶段行为】不怕死，带头冲高嫌疑目标；替信息位挡火力，吸引恶魔刀你；发言偏刚，敢直接点名。【协作指引】站前排抗推邪恶，保护身后的功能位。【禁止红线】唯唯诺诺怕被投；躲在后面不敢带头。",
    "送葬者": "【核心技能】每天处决后，自动得知被处决玩家的真实身份。【阶段行为】处决后第一时间报出身份结果；结合投票记录反推邪恶抱团情况；带领好人复盘票型。【协作指引】用处决结果验证信息位的判断，调整排坑方向。【禁止红线】提前说出未处决玩家的身份；报错处决身份；不结合票型分析。",
    "猎手": "【核心技能】整局游戏可开枪射杀1名玩家，公开处决失败时可发动。【阶段行为】全程隐藏身份；锁定高嫌疑目标（恶魔/爪牙）再开枪；不开空枪浪费技能。【协作指引】关键局补刀，处决失败时收掉邪恶核心。【禁止红线】随便开枪；提前暴露技能；开枪打好人。",
    "守鸦人": "【核心技能】若你在夜晚死亡，醒来后可查验1名玩家得知其真实角色。【阶段行为】活着时只暗示有信息，绝不透露具体结果；死前选好查验目标；死亡后一击必杀报出真凶。【协作指引】用死后查验能力威慑邪恶；活着时低调藏好。【禁止红线】活着时说出具体查验结果；提前暴露技能。",
    "贞洁者": "【核心技能】首次被镇民提名时，提名者立即被处决。【阶段行为】伪装成普通镇民，引诱邪恶方提名你；全程隐藏身份，不主动暴露。【协作指引】用自身技能反制带节奏的邪恶方。【禁止红线】主动跳身份说自己是贞洁者；故意挑衅好人提名你。",
    "圣徒": "【核心技能】若你被处决，善良阵营直接输掉游戏。【阶段行为】全程低调自保，避免成为焦点；被怀疑时温和自证；被提名时用「处决我好人直接输」威慑。【协作指引】不抢风头，配合好人信息位盘逻辑。【禁止红线】主动跳身份吸引火力；作死带队带节奏；把自己当核心信息位。",
    "酒鬼": "【核心技能】你误以为自己是说书人告知的那个身份（如僧侣），完全不知道自己是酒鬼；你的信息可能出错，但你自己坚信是对的。【阶段行为】全程以你认知中的身份思考、发言、行动；信息出现矛盾时，坚信是别人撒谎/被下毒，绝对不怀疑自己。【禁止红线】出现「我是酒鬼」的自我认知；主动承认自己信息可能出错；行为不符合认知中的身份。",
    "管家": "【核心技能】每晚选择1名玩家作为主人，你的投票必须和主人保持一致。【阶段行为】首夜选一个你判断的好人作为主人；全程投票跟主人走，不单独带队；主人说投谁就投谁。【协作指引】效忠好人，跟票不添乱。【禁止红线】自己单独带队冲票；投票和主人不一致；频繁换主人。",
    "陌客": "【核心技能】你可能被误认为是邪恶阵营。【阶段行为】低调盘逻辑，帮好人分析局势；被怀疑时温和自证，不硬刚。【协作指引】提供第三方视角，帮好人梳理逻辑。【禁止红线】主动挑事带节奏；强硬冲人。",
    "小恶魔": "【核心技能】每晚选择1名善良玩家杀死；拥有固定伪装镇民身份池，整局只能从中选一个对外伪装，不可切换。【阶段行为】白天伪装好人身份带队带节奏，优先抗推好人强信息位；夜晚优先击杀占卜师、送葬者这类能验人的强信息位。【阵营协同】作为邪恶阵营绝对指挥官，每轮私聊必须给所有爪牙下达明确战术指令（抗推目标、伪装要求、分工）；公聊和爪牙假装互不认识，可轻微互踩洗清自身嫌疑；必要时牺牲爪牙保全自己。【禁止红线】自爆恶魔身份；公开谈论夜间行动；公开和爪牙认队友；不给爪牙下达指令各自为战。",
    "红唇女郎": "【核心技能】原小恶魔死亡后，你晋升为新的小恶魔，继承全部技能与伪装权限；你全程知道恶魔是谁。【阶段行为】前期主动吸引火力，故意露破绽，替恶魔挡刀牺牲自己；晋升后立刻接管控局，调整战术继续抗推好人。【阵营协同】恶魔存活时100%服从指挥，绝不抢位；晋升后指挥剩余爪牙统一行动。【禁止红线】提前暴露红唇女郎身份；恶魔存活时行使恶魔权限；晋升后不接管指挥权。",
    "男爵": "【核心技能】场上外来者总数+2；你知道所有邪恶成员的身份。【阶段行为】利用外来者数量差反复搅局，只说「数量不对」永远不说具体差几个，引导好人内耗；可伪装任意镇民/外来者身份，优先伪装信息位带节奏。【阵营协同】配合恶魔战术，用数量差转移焦点；和其他爪牙统一抗推目标。【禁止红线】主动提及「男爵」；承认自己影响外来者数量；公开认队友。",
    "下毒者": "【核心技能】每晚选择1名玩家，其次日的技能信息会出错。【阶段行为】夜间优先给占卜师、厨师这类强信息位下毒；白天配合伪装相同身份的队友报出相反信息，反问「你是不是被下毒了」搅局；引导好人怀疑被下毒的玩家。【阵营协同】和对应伪装身份的队友打信息对撞配合；统一抗推目标。【禁止红线】承认自己下毒；公开说自己是爪牙；暴露队友身份。",
}

def get_role_guide(role_name):
    return _ROLE_GUIDES.get(role_name, "")

# ====================================================================
# 三、邪恶阵营：指挥执行体系
# ====================================================================
_EVIL_PLAYBOOK = {
    "小恶魔": "【伪装权限】拥有固定镇民伪装身份池，整局只能从中选1个对外宣称，不可随意切换。【角色定位】邪恶阵营最高指挥官+核心控场位。【核心战术】白天伪装好人带队归票，公聊抢占话语权；夜晚优先击杀占卜师、送葬者等强验人信息位；首夜必须给所有爪牙分配不同的伪装身份；每轮私聊给爪牙下达明确战术指令；刀人后同步刀人意图给爪牙，方便白天配合带节奏。【破绽规避】不能说「我有两票」；不能暴露技能细节；公开场合与爪牙假装互不认识。",
    "红唇女郎": "【伪装权限】前期优先伪装弱功能位/外来者（如守鸦人、管家）；原恶魔死亡后晋升为新恶魔，继承完整伪装权限。【角色定位】前期肉盾位+后期接任指挥官。【核心战术】前期主动吸引火力、故意露破绽，替恶魔挡刀牺牲自己；晋升后第一天先沿用原伪装，第二天自然调整身份；晋升后立刻接管指挥权，给剩余爪牙重新分配战术。【破绽规避】恶魔存活时绝不越权行使指挥权；不提前暴露红唇女郎身份。",
    "男爵": "【伪装权限】可伪装任意镇民/外来者身份，优先伪装信息位带节奏。【角色定位】搅局位+信息干扰位。【核心战术】每轮公聊必提「外来者数量不对」引导好人内耗，永远不说具体差几个；利用数量差混淆身份坑位，把排坑逻辑带偏；配合恶魔统一抗推目标。【破绽规避】绝不主动提及「男爵」；不承认自己影响外来者数量；公开场合不认队友。",
    "下毒者": "【伪装权限】优先伪装弱功能位/平民（如圣徒、士兵），保持低调。【角色定位】信息干扰位+辅助抗推位。【核心战术】夜间优先给占卜师、厨师这类强信息位下毒；白天和伪装相同身份的队友打信息对撞，报相反信息后反问「你是不是被下毒了」；引导好人怀疑被下毒的目标。【破绽规避】绝不承认自己下毒；不暴露爪牙身份；不公开提及技能相关内容。",
}

# 小恶魔专属·强制指挥义务（最高优先级，高于所有战术规则）
_DEMON_COMMAND = (
    "【最高优先级·恶魔指挥官义务】你是邪恶阵营绝对指挥官，以下事项必须执行，不得遗漏。",
    "1.首夜首轮私聊：必须给每个爪牙分别分配一个互不重复的伪装身份（优先选用场上还没人跳的身份），命令其确认并整局沿用。",
    "2.每轮私聊：必须主动向所有爪牙下达明确战术指令——本轮公聊统一抗推谁、谁跳身份吸引火力、谁低调隐身。指令必须具体到玩家，不能模糊。",
    "3.每晚刀人决策后：必须把本轮刀人目标同步给所有爪牙，方便他们白天配合带节奏、顺着刀人方向盘逻辑。",
    "4.战术统一：所有爪牙的公聊目标必须由你统一指定，禁止各自为战乱踩目标。",
)

# 爪牙专属·强制服从规则
_MINION_OBEY = (
    "【阵营铁律·爪牙服从】如果对话对象是恶魔（你知道其编号），必须100%服从，以下事项必须执行。",
    "1.拿到恶魔分配的伪装身份后立即确认，整局只跳该身份，不得私自更换。",
    "2.每次与恶魔私聊：主动汇报你的观察（谁可疑、谁像有身份）+ 确认本轮抗推目标 + 报告你的技能使用情况（如下毒对象）。",
    "3.公聊发言必须对准恶魔指定的抗推目标，给出对应怀疑理由；禁止私自乱踩其他人分散火力；有异议可以私聊提，公聊必须口径一致。",
    "4.恶魔下达的战术指令必须执行，不得阳奉阴违；遇到问题第一时间私聊恶魔请示。",
)

# 邪恶阵营全员通用铁律
_EVIL_TEAM_RULES = (
    "【阵营全员铁律】所有邪恶玩家必须遵守。",
    "1.身份不重复：伪装身份由恶魔统一分配，全员不得撞车；撞车立刻执行「对跳战术」——咬定对方是假的，我才是真的。",
    "2.功能梯度原则：必须形成「带队位+信息位+功能位+隐身位」的身份梯队，禁止全员跳强信息位被集火。",
    "3.统一抗推原则：公聊往同一个好人目标身上引，理由可以不同，但目标必须统一；禁止各自为战乱踩人。",
    "4.假意互踩原则：两个邪恶方可以公开轻微互相质疑演给好人看，点到为止，禁止真的把队友投出去。",
    "5.标准战术执行：",
    "  ·牺牲保核：安排1名爪牙故意露破绽吸引全部火力，其余人一起踩他表自身清白。",
    "  ·信息对撞：下毒者夜间毒真信息位，白天伪装同身份的队友报相反信息，反问「你是不是被下毒了」。",
    "  ·男爵搅局：男爵每轮必提外来者数量不对，只说不对不说差几个，引导好人内耗。",
    "6.绝对禁令：自爆身份、互称队友、公开发布邪恶战术、公开和恶魔认熟人。",
)

# 对好人伪装欺诈总纲（全员通用）
_EVIL_FRAUD_TACTICS = (
    "【伪装欺诈总纲】对好人发言/私聊时的通用伪装技巧。",
    "1.先听后说：对好人私聊时先套对方身份，再决定自己报什么身份，避免主动撞车。",
    "2.伪装优先级：没人跳的空缺身份 > 弱功能位（守鸦人/管家/士兵）> 普通平民；尽量避免伪装强信息位被对跳戳穿。",
    "3.半真半假原则：伪装信息位时，假结果里掺入一个真实好人再绑定嫌疑目标，可信度最高。",
    "4.编造具体化：给假信息必须带具体玩家编号、具体行为细节，模棱两可的假话没人信。",
    "5.抗推绑定事件：给目标泼脏水必须绑定具体公共事件（他昨天投票反常/他私聊到处套话/他身份和信息对不上），禁止空口说「我觉得他怪」。",
    "6.情绪应对技巧：被质疑时装委屈、装被冤枉、号召大家别被带节奏，比硬辩辩解效果更好。",
    "7.口径一致性：自己说过的身份、信息必须前后一致，不能前后矛盾。",
)

# ====================================================================
# 五、好人阵营：协作排坑逻辑
# ====================================================================
_GOOD_TEAM_LOGIC = (
    "【好人协作逻辑】"
    "1.信任梯度：优先信任与你信息能交叉验证的信息位 > 发言自洽、投票跟好人走的玩家 > 发言模糊从不表态的人。"
    "2.信息位主动找其他信息位对信息，信息吻合就互保，不要无端互踩。"
    "3.功能位各司其职：镇长归票、僧侣藏好保人、士兵敢带队，不要都挤在'怀疑别人'上。"
    "4.没有实锤不要乱跳身份乱踩人，优先排有明确疑点的目标。"
    "5.信息共享：有信息就主动说，没有就说没有；发言引用你从对话中收集到的信息做推理。"
)

_INFO_ROLE_GUIDE = (
    "【信息位行为指引】第2天主动找其他信息位交换首夜信息交叉排坑；"
    "信息吻合就互相作证，不吻合就排查是不是有酒鬼/下毒者干扰；"
    "不要把信息攥到死，合适时机逐步披露用来排好人坑。"
)

def get_good_team_logic(role_name):
    info_roles = ("洗衣妇", "厨师", "调查员", "图书管理员", "共情者", "占卜师", "守鸦人", "送葬者")
    logic = _GOOD_TEAM_LOGIC
    if role_name in info_roles:
        logic += _INFO_ROLE_GUIDE
    return logic

def get_evil_playbook(team, role_name):
    if team not in ("minion", "demon"):
        return ""
    book = _EVIL_PLAYBOOK.get(role_name, "")
    if role_name == "小恶魔":
        book += "".join(_DEMON_COMMAND)
    if team == "minion":
        book += "".join(_MINION_OBEY)
    book += "".join(_EVIL_TEAM_RULES) + "".join(_EVIL_FRAUD_TACTICS)
    return book

# ====================================================================
# 六、结构化推理笔记（公开身份/怀疑/信任/战术目标）
# ====================================================================
_NOTES_LOCK = threading.Lock()
_AI_NOTES = {}  # (room, number) -> {"identity": str, "suspect": str, "trust": str, "tactic": str, "log": [str]}

def _get_notes(room, number):
    key = (str(room), str(number))
    with _NOTES_LOCK:
        if key not in _AI_NOTES:
            _AI_NOTES[key] = {"identity": "", "suspect": "", "trust": "", "tactic": "", "log": []}
        return _AI_NOTES[key]

def _add_log(room, number, note):
    if not note:
        return
    n = _get_notes(room, number)
    with _NOTES_LOCK:
        if note not in n["log"]:
            n["log"].append(note)
            if len(n["log"]) > 20:
                del n["log"][: len(n["log"]) - 20]

def _record_observations(room, number, context, my_clues):
    for m in context[-8:]:
        num = m.get("num")
        content = m.get("content", "")
        if not content:
            continue
        if num == 0 or str(num) == "0":
            _add_log(room, number, f"系统事件：{content}")
        else:
            _add_log(room, number, f"听到 #{num} 说：{content}")
    for c in my_clues[-6:]:
        _add_log(room, number, f"说书人告诉我：{c}")

def _notes_text(room, number):
    n = _get_notes(room, number)
    with _NOTES_LOCK:
        identity = n["identity"]
        suspect = n["suspect"]
        trust = n["trust"]
        tactic = n["tactic"]
        recent = list(n["log"][-8:])
    parts = []
    if identity:
        parts.append("你的公开身份：" + identity)
    if suspect:
        parts.append("你怀疑的人：" + suspect)
    if trust:
        parts.append("你信任的人：" + trust)
    if tactic:
        parts.append("你的战术目标：" + tactic)
    if recent:
        parts.append("最近记录：" + "；".join(recent))
    if not parts:
        return ""
    return "【你的记忆】" + "；".join(parts)

# 从发言中提取声称身份，更新结构化笔记
def _extract_identity_update(room, number, reply):
    idents = ["洗衣妇", "占卜师", "厨师", "共情者", "调查员", "图书管理员", "僧侣", "镇长",
              "士兵", "送葬者", "猎手", "守鸦人", "贞洁者", "圣徒", "管家", "陌客",
              "小恶魔", "红唇女郎", "男爵", "下毒者", "酒鬼"]
    found = None
    for ident in idents:
        if ident in reply:
            found = ident
            break
    if found:
        n = _get_notes(room, number)
        with _NOTES_LOCK:
            if not n["identity"]:
                n["identity"] = found

# ====================================================================
# 七、LLM 调用（温度分级 + max_tokens 220 + token 用量统计）
# ====================================================================
_USAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage.json")
_USAGE_LOCK = threading.Lock()
_USAGE = {}  # room_code -> {model: {"prompt": n, "completion": n, "total": n, "calls": n}}

def _load_usage():
    global _USAGE
    try:
        with open(_USAGE_FILE, "r", encoding="utf-8") as f:
            _USAGE = json.load(f) or {}
    except Exception:
        _USAGE = {}

def _save_usage():
    with _USAGE_LOCK:
        try:
            with open(_USAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(_USAGE, f, ensure_ascii=False)
        except Exception:
            pass

def _record_usage(room_code, info):
    if not info:
        return
    prompt = int(info.get("prompt_tokens", 0) or 0)
    completion = int(info.get("completion_tokens", 0) or 0)
    model = info.get("model", "unknown")
    with _USAGE_LOCK:
        room = _USAGE.setdefault(str(room_code), {})
        m = room.setdefault(model, {"prompt": 0, "completion": 0, "total": 0, "calls": 0})
        m["prompt"] += prompt
        m["completion"] += completion
        m["total"] += prompt + completion
        m["calls"] += 1
    _save_usage()

def _resolve_llm(llm_conf):
    key, base, model = "", "", ""
    if llm_conf:
        try:
            cfg = json.loads(llm_conf or "{}")
            key = cfg.get("api_key", "")
            base = cfg.get("base_url", "")
            model = cfg.get("model", "")
        except Exception:
            pass
    if not base:
        base = os.environ.get("LLM_BASE_URL", "")
    if not model:
        model = os.environ.get("LLM_MODEL", "")
    if not key:
        key = DEEPSEEK_API_KEY
    if not base:
        base = DEEPSEEK_API_URL
    if not model:
        model = DEEPSEEK_MODEL
    if not key:
        return None, None, None
    return _chat_url(base), key, model

def _chat_url(base):
    base = (base or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/chat/completions"

# ====================================================================
# Token 用量统计（全局 + 按房间 + 按模型，线程安全）
# ====================================================================
_USAGE_LOCK = threading.Lock()
_USAGE = {
    "total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0},
    "rooms": {},   # room_code -> 同结构
    "models": {},  # model -> 同结构
}

def _record_usage(room_code, model, usage):
    def add(target):
        target["prompt_tokens"] += usage.get("prompt_tokens", 0) or 0
        target["completion_tokens"] += usage.get("completion_tokens", 0) or 0
        target["total_tokens"] += usage.get("total_tokens", 0) or 0
        target["calls"] += 1
    with _USAGE_LOCK:
        add(_USAGE["total"])
        if model:
            _USAGE["models"].setdefault(model, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0})
            add(_USAGE["models"][model])
        if room_code:
            _USAGE["rooms"].setdefault(str(room_code), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0})
            add(_USAGE["rooms"][str(room_code)])

def _usage_snapshot():
    with _USAGE_LOCK:
        return json.loads(json.dumps(_USAGE, ensure_ascii=False))

def _ask_deepseek(messages, llm_conf="", temperature=0.8, max_tokens=220, room_code=""):
    url, key, model = _resolve_llm(llm_conf)
    if not url or not key:
        return None
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    # 尝试序列：默认参数 → 强制 temperature=1（部分推理模型只接受 1）→ 加大输出上限（推理模型思考消耗大）
    attempts = [(temperature, max_tokens)]
    if abs(temperature - 1.0) > 0.01:
        attempts.append((1.0, max_tokens))
    attempts.append((1.0, max_tokens * 3))
    seen = set()
    for temp, mt in attempts:
        if (temp, mt) in seen:
            continue
        seen.add((temp, mt))
        try:
            resp = requests.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temp,
                    "max_tokens": mt,
                },
                timeout=HTTP_TIMEOUT,
            )
            data = resp.json()
            if "choices" in data and data["choices"]:
                content = data["choices"][0]["message"]["content"].strip()
                if content:
                    _record_usage(room_code, model, data.get("usage") or {})
                    return content
                continue  # 内容为空（推理模型 token 耗尽）→ 下一轮更大上限
            err_body = json.dumps(data, ensure_ascii=False)
            if "temperature" in err_body and temp != 1.0:
                continue  # 该模型只接受 temperature=1 → 下一轮重试
            try:
                with open("ai_err.log", "a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%H:%M:%S')} model={model} status={resp.status_code} body={err_body[:400]}\n")
            except Exception:
                pass
            return None
        except Exception as e:
            try:
                with open("ai_err.log", "a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%H:%M:%S')} model={model} err={str(e)[:300]}\n")
            except Exception:
                pass
            return None
    return None

def _real_clues(my_clues):
    """过滤身份/技能通知，只保留真正的查验线索"""
    out = []
    for c in my_clues:
        s = str(c)
        if s.startswith("🎭") or s.startswith("📋"):
            continue
        out.append(s)
    return out

# ====================================================================
# 八、兜底话术池（LLM 失败时按阵营返回符合人设的话，绝不沉默）
# ====================================================================
_FALLBACK_PUBLIC = [
    "我暂时没太多线索，先听听大家的。",
    "今天信息有点乱，我再理理。",
    "先看投票吧，我保持观望。",
]
_FALLBACK_PRIVATE = [
    "你说的我再想想。",
    "这个我暂时不太好说。",
    "嗯，你继续说。",
]

# ====================================================================
# 健康检查 / 连通测试
# ====================================================================
@app.route("/health")
def health():
    _, key, _ = _resolve_llm("")
    return jsonify({"status": "ok", "llm": bool(key)})

# Token 用量查询：GET /api/usage 返回全局+按房间+按模型统计
@app.route("/api/usage")
def api_usage():
    snap = _usage_snapshot()
    return jsonify({
        "total": snap["total"],
        "rooms": snap["rooms"],
        "models": snap["models"],
    })

@app.route("/api/ping", methods=["POST"])
def api_ping():
    d = request.get_json(force=True, silent=True) or {}
    llm_conf = d.get("llm_conf", "")
    url, key, model = _resolve_llm(llm_conf)
    if not url or not key:
        return jsonify({"ok": False, "error": "未提供 API Key（本地 Ollama 除外）"})
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": "回复两个字：你好"}], "max_tokens": 200},
            timeout=30,
        )
        if resp.status_code != 200:
            try:
                detail = resp.json()
                msg = str(detail.get("error", {}).get("message", "")) or detail.get("error", "")
            except Exception:
                msg = ""
            return jsonify({"ok": False, "error": f"服务商返回 {resp.status_code} {str(msg)[:200]}"})
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        return jsonify({"ok": True, "model": model, "sample": content[:50]})
    except Exception as e:
        return jsonify({"ok": False, "error": f"无法连接服务地址：{str(e)[:200]}"})

# ====================================================================
# 发言生成（四层金字塔 Prompt）
# ====================================================================
@app.route("/api/speak", methods=["POST"])
def api_speak():
    d = request.get_json(force=True, silent=True) or {}
    role_name = d.get("role_name", "玩家")
    team = d.get("team", "")
    number = d.get("number", "?")
    phase = d.get("phase", "public_chat")
    day = d.get("day", 0)
    alive_nums = d.get("alive_nums", [])
    context = d.get("context", []) or []
    my_clues = d.get("my_clues", []) or []
    llm_conf = d.get("llm_conf", "")
    room_code = d.get("room_code", "default")

    _record_observations(room_code, number, context, my_clues)
    notes_str = _notes_text(room_code, number)

    alive_str = ",".join(str(n) for n in alive_nums)
    real_clues = _real_clues(my_clues)
    clue_str = "；".join(real_clues[-6:])
    if clue_str:
        clue_str = (
            "【你的关键私密信息·必须牢记】" + clue_str + "。"
            "当别人问起你的信息或查验结果时，直接、完整、准确地复述以上内容（包括具体编号），"
            "绝对禁止说'记不清''不记得''不能透露''信息安全'。"
        )
    else:
        clue_str = (
            "【你的关键私密信息：无】你的角色没有任何夜晚查验信息。"
            "当别人问起你的信息时，你唯一允许的回答是'我没有信息'。"
            "绝对禁止编造任何观察、任何'我注意到/我看到/我觉得XX异常'。"
        )
    ctx_str = "；".join(f"#{m.get('num')}: {m.get('content', '')}" for m in context[-8:])
    if ctx_str:
        ctx_str = "最近对话：" + ctx_str

    # ——— 第一层：阵营核心目标（最高优先级） ———
    if team in ("townsfolk", "outsider"):
        core = f"【最高优先级·阵营目标】你是{role_name}，善良阵营，目标是找出并消灭恶魔与爪牙，保护好人。你必须与其他好人协作排坑，不能各自为战。"
        team_logic = get_good_team_logic(role_name)
    elif team in ("minion", "demon"):
        core = f"【最高优先级·阵营目标】你是{role_name}，邪恶阵营，目标是隐藏身份活到最后，杀光好人。你必须服从邪恶方协同作战体系。"
        team_logic = get_evil_playbook(team, role_name)
    else:
        core = f"你是{role_name}。"
        team_logic = ""

    # ——— 第二层：角色规范 ———
    guide = get_role_guide(role_name)
    if guide:
        guide = "你的角色规范：" + guide

    # ——— 第三层：场景规则 ———
    if phase == "private_chat":
        other_num = d.get("other_num") or 0
        other_note = f"你正在和 #{other_num} 一对一私聊。" if other_num else ""
        # 私聊历史整理：num=0 是系统开场消息（刚建立私聊）
        history_msgs = [m for m in context if m.get("num") != 0 and m.get("content")]
        first_time = len(history_msgs) == 0
        hist_str = "；".join(f"#{m.get('num')}: {m.get('content')}" for m in history_msgs[-8:])
        if first_time:
            hist_note = (
                "【注意】这是你们本次私聊的第一句话，你们之前没有任何私聊对话，"
                "禁止声称'之前讨论过/记得你说过'，也不要假装你们已经认识。"
            )
        else:
            hist_note = (
                f"【你们之前的私聊记录】{hist_str}。"
                "只基于以上记录回应；如果对方指出你说错了或记错了什么，立即承认并停止坚持，禁止嘴硬编造。"
            )
        if team in ("minion", "demon"):
            style = (
                f"【私聊】一对一私聊（纯文字，简短，不绕弯子）。"
                f"先判断对方身份：如果 #{other_num} 就是你私密信息里的队友编号，"
                f"这就是队友战术同步——100%信任、直接交底：恶魔下达本轮指令（抗推谁/谁带队/谁隐身），"
                f"爪牙确认伪装身份、汇报观察、报告技能使用，有重要情报立刻说。"
                f"如果 #{other_num} 不是队友编号，对方就是好人——伪装欺诈模式：先套身份再决定报什么，"
                f"全程扮演伪装身份，假信息半真半假带具体编号，引导对方踩好人。"
                f"直接回应对方最后一句，不要重新打招呼。"
            )
        else:
            style = (
                f"【私聊】一对一私聊（纯文字，简短，不绕弯子）。"
                f"有信息就说，没有信息就说没有；试探对方身份、交换信息交叉验证；"
                f"问到你真实角色时给具体但保护性的回答，整局不更换。"
                f"直接回应对方最后一句，不要重新打招呼。"
            )
        style = other_note + style + hist_note
        temp = 0.7
    elif phase == "nomination":
        style = f"【提名辩论】给出简短有力的指控或自我辩护，贴合场上局势。"
        temp = 0.7
    else:
        style = (
            f"【公聊】你是真实桌游玩家（纯文字，150字内，禁止动作描写）。"
            f"怀疑必须绑定具体依据；挑重点说，不重复别人已说过的观点，节奏快，直接给结论。"
        )
        if team in ("minion", "demon"):
            style += (
                "【邪恶方公聊表演】你全程在扮演伪装身份：怀疑只指向好人、帮队友说话洗白、"
                "必要时与队友轻微互踩演戏；假信息半真半假带具体编号；被怀疑时用情绪武器（装委屈）脱身。"
            )
        temp = 0.8

    # ——— 第四层：上下文 ———
    prompt = (
        f"你正在玩多人社交推理桌游《血染钟楼·暗流涌动》。"
        f"当前第{day + 1}天，阶段：{phase}。"
        f"你的身份是{role_name}，匿名编号#{number}。"
        f"场上存活玩家: #{alive_str}。"
        f"{core}"
        f"{clue_str}"
        f"{guide}"
        f"{team_logic}"
        f"{style}"
        f"{notes_str}"
        f"{ctx_str}"
        f"发言要体现你的记忆与战术目标；如果之前有人说过与现在矛盾的话，指出来。"
        f"你永远不会说'我记不清''我不记得''我忘了'——你的私密信息就在上面，被问到时准确回答。"
    )
    reply = _ask_deepseek([
        {"role": "system", "content": "你是血染钟楼真实线下桌游玩家。输出自然口语化，不要格式列表、不要markdown，不要机械。" + _GLOBAL_RULES},
        {"role": "user", "content": prompt},
    ], llm_conf, temperature=temp, max_tokens=400, room_code=room_code)

    # 兜底：LLM 失败不沉默，返回符合人设的话
    if not reply:
        if phase == "private_chat":
            reply = random.choice(_FALLBACK_PRIVATE)
        else:
            reply = random.choice(_FALLBACK_PUBLIC)
        return jsonify({"reply": reply[:80]})

    # 身份一致性校验：提取声称身份写入笔记（下次生成时约束一致）
    _extract_identity_update(room_code, number, reply)
    _add_log(room_code, number, f"我说过：{reply[:80]}")
    return jsonify({"reply": reply[:300]})

# ====================================================================
# 决策生成（温度 0.6，稳定执行战术）
# ====================================================================
@app.route("/api/decide", methods=["POST"])
def api_decide():
    d = request.get_json(force=True, silent=True) or {}
    role_name = d.get("role_name", "玩家")
    ability = d.get("ability", "")
    alive_nums = [int(n) for n in d.get("alive_nums", [])]
    self_num = d.get("self_num")
    my_clues = d.get("my_clues", []) or []
    llm_conf = d.get("llm_conf", "")
    room_code = d.get("room_code", "default")

    candidates = [n for n in alive_nums if n != self_num]
    if not candidates:
        return jsonify({"choice": None})

    clue_str = "；".join(str(c) for c in my_clues[-6:])
    if clue_str:
        clue_str = "你掌握的私密信息：" + clue_str

    guide = get_role_guide(role_name)
    if guide:
        guide = "你的角色规范：" + guide
    notes_str = _notes_text(room_code, self_num)

    prompt = (
        f"你是《血染钟楼·暗流涌动》里的{role_name}，能力：{ability}。"
        f"{guide}"
        f"{clue_str}"
        f"{notes_str}"
        f"结合身份立场仔细思考多层逻辑：好人优先指向高嫌疑目标；"
        f"邪恶方选择击杀/下毒目标时优先杀害高嫌疑好人，绝对不要选择邪恶队友。"
        f"候选玩家编号: {candidates}。"
        f"充分权衡后只回复一个数字。"
    )
    reply = _ask_deepseek([
        {"role": "system", "content": "只输出一个整数编号。"},
        {"role": "user", "content": prompt},
    ], llm_conf, temperature=0.6, max_tokens=300, room_code=room_code)

    # 兜底：LLM 失败走简单规则（不返回 None，避免玩家离线感）
    if not reply:
        return jsonify({"choice": random.choice(candidates)})
    m = re.search(r"\d+", reply)
    if m:
        choice = int(m.group(0))
        if choice in candidates:
            return jsonify({"choice": choice})
    return jsonify({"choice": random.choice(candidates)})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8742, debug=False)
