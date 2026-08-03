"""
官方暗流涌动(Trouble Brewing)角色定义
基于钟楼百科 https://clocktower-wiki.gstonegames.com
"""

BOTC_ROLES = {
    "洗衣妇": {
        "team": "townsfolk",
        "ability": "游戏开始时会得知两名玩家中有一名特定镇民身份。",
        "first_night": True,
        "other_nights": False,
        "icon": "🧺",
    },
    "图书管理员": {
        "team": "townsfolk",
        "ability": "游戏开始时会得知两名玩家中有一名特定外来者身份，或得知本局没有外来者。",
        "first_night": True,
        "other_nights": False,
        "icon": "📚",
    },
    "调查员": {
        "team": "townsfolk",
        "ability": "游戏开始时会得知两名玩家中有一名特定爪牙身份。",
        "first_night": True,
        "other_nights": False,
        "icon": "🔍",
    },
    "厨师": {
        "team": "townsfolk",
        "ability": "游戏开始时会得知有多少对相邻的玩家是邪恶阵营。",
        "first_night": True,
        "other_nights": False,
        "icon": "👨‍🍳",
    },
    "共情者": {
        "team": "townsfolk",
        "ability": "每晚会得知与你相邻的存活玩家中有多少人是邪恶的(0-2)。",
        "first_night": True,
        "other_nights": True,
        "icon": "💕",
    },
    "占卜师": {
        "team": "townsfolk",
        "ability": "每晚会选择两名玩家，得知其中是否有恶魔(可选择一名已选过的玩家)。注意有干扰项机制。",
        "first_night": True,
        "other_nights": True,
        "icon": "🔮",
    },
    "送葬者": {
        "team": "townsfolk",
        "ability": "每晚会得知今天白天被处决的玩家的角色。",
        "first_night": False,
        "other_nights": True,
        "icon": "⚰️",
    },
    "僧侣": {
        "team": "townsfolk",
        "ability": "每晚会选择一名玩家(不能选自己)，该玩家当晚不会被恶魔杀害。",
        "first_night": False,
        "other_nights": True,
        "icon": "🙏",
    },
    "守鸦人": {
        "team": "townsfolk",
        "ability": "如果你在夜晚死亡，你可以选择一名玩家并得知其角色。",
        "first_night": False,
        "other_nights": False,
        "icon": "🐦",
    },
    "贞洁者": {
        "team": "townsfolk",
        "ability": "第一次被提名时，如果提名者是镇民则其立即被处决。",
        "first_night": False,
        "other_nights": False,
        "icon": "💎",
    },
    "猎手": {
        "team": "townsfolk",
        "ability": "白天可公开选择一名玩家，如果该玩家是恶魔则其立即死亡。能力只能用一次。",
        "first_night": False,
        "other_nights": False,
        "icon": "🏹",
    },
    "士兵": {
        "team": "townsfolk",
        "ability": "恶魔无法杀害你。",
        "first_night": False,
        "other_nights": False,
        "icon": "🛡️",
    },
    "镇长": {
        "team": "townsfolk",
        "ability": "如果白天只有3名存活玩家且无人被处决，你的阵营获胜。当恶魔攻击你时可能有一名其他玩家死亡。",
        "first_night": False,
        "other_nights": False,
        "icon": "🏛️",
    },
    "管家": {
        "team": "outsider",
        "ability": "每晚会选择一名玩家成为你的主人，你只能在主人投票后才能投票。",
        "first_night": True,
        "other_nights": True,
        "icon": "🕴️",
    },
    "酒鬼": {
        "team": "outsider",
        "ability": "你以为自己是某镇民角色，但实际不是，你得到的是错误信息。",
        "first_night": False,
        "other_nights": False,
        "icon": "🍺",
    },
    "陌客": {
        "team": "outsider",
        "ability": "你可能被判定为邪恶阵营或爪牙，即使你是善良的。",
        "first_night": False,
        "other_nights": False,
        "icon": "👤",
    },
    "圣徒": {
        "team": "outsider",
        "ability": "如果你被处决，你的阵营落败。",
        "first_night": False,
        "other_nights": False,
        "icon": "😇",
    },
    "投毒者": {
        "team": "minion",
        "ability": "每晚会选择一名玩家，该玩家今晚和明天白天中毒(获得错误信息)。",
        "first_night": True,
        "other_nights": True,
        "icon": "☠️",
    },
    "间谍": {
        "team": "minion",
        "ability": "你可以查看魔典。你可能被判定为善良阵营。",
        "first_night": True,
        "other_nights": True,
        "icon": "🕵️",
    },
    "红唇女郎": {
        "team": "minion",
        "ability": "如果恶魔死亡，你变成恶魔。",
        "first_night": False,
        "other_nights": False,
        "icon": "💋",
    },
    "男爵": {
        "team": "minion",
        "ability": "本局游戏额外增加2名外来者(减少2名镇民)。",
        "first_night": False,
        "other_nights": False,
        "icon": "👑",
    },
    "小恶魔": {
        "team": "demon",
        "ability": "每晚会选择一名玩家杀害(首夜不杀人)。如果自杀，一名爪牙变成恶魔。",
        "first_night": False,
        "other_nights": True,
        "icon": "😈",
    },
}

BOTC_TEAMS = {
    "townsfolk": ["洗衣妇", "图书管理员", "调查员", "厨师", "共情者", "占卜师", "送葬者", "僧侣", "守鸦人", "贞洁者", "猎手", "士兵", "镇长"],
    "outsider": ["管家", "酒鬼", "陌客", "圣徒"],
    "minion": ["投毒者", "间谍", "红唇女郎", "男爵"],
    "demon": ["小恶魔"],
}

BOTC_WIN_CONDITIONS = {
    "good": "所有恶魔均已死亡。",
    "evil": "场上只剩两名存活玩家(旅行者不计入)。",
}

# 官方夜晚顺序表(严格按wiki顺序)
# 首夜：间谍在洗衣妇之前查看魔典，这样间谍可以提前知道全角色信息来伪装
NIGHT_ORDER_FIRST = [
    ("黄昏", "检查所有玩家闭眼"),
    ("爪牙信息", "唤醒爪牙,指认恶魔(仅7人以上)"),
    ("恶魔信息", "唤醒恶魔,指认爪牙,展示3个不在场善良角色(仅7人以上)"),
    ("投毒者", "选择一名玩家下毒"),
    ("间谍", "查看魔典(知晓全场角色以制定伪装策略)"),
    ("洗衣妇", "得知两名玩家中一名特定镇民身份"),
    ("图书管理员", "得知两名玩家中一名特定外来者身份或告知无外来者"),
    ("调查员", "得知两名玩家中一名特定爪牙身份"),
    ("厨师", "得知相邻邪恶对数"),
    ("共情者", "得知相邻存活邪恶玩家数"),
    ("占卜师", "选择两名玩家,得知其中是否有恶魔(含干扰项)"),
    ("管家", "选择一名玩家为主人"),
    ("黎明", "所有玩家睁眼"),
]

NIGHT_ORDER_OTHER = [
    ("黄昏", "检查所有玩家闭眼"),
    ("投毒者", "选择一名玩家下毒"),
    ("僧侣", "选择一名玩家保护(不能被恶魔杀害)"),
    ("间谍", "查看魔典(知晓全场角色以制定伪装策略)"),
    ("红唇女郎", "若恶魔死亡则变成新恶魔(存活>=5人时)"),
    ("小恶魔", "选择一名玩家杀害(可自杀传位)"),
    ("守鸦人", "若今晚死亡则查看一名玩家的角色"),
    ("送葬者", "得知今天白天被处决的玩家角色"),
    ("共情者", "得知相邻存活邪恶玩家数"),
    ("占卜师", "选择两名玩家,得知其中是否有恶魔(含干扰项)"),
    ("管家", "选择一名玩家为主人"),
    ("黎明", "睁眼并宣布死亡情况"),
]
