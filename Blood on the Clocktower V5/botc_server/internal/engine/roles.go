package engine

// 阵营常量
const (
	TeamTownsfolk = "townsfolk"
	TeamOutsider  = "outsider"
	TeamMinion    = "minion"
	TeamDemon     = "demon"
)

// RoleDef 角色定义
type RoleDef struct {
	Key         string
	Name        string
	Team        string // 空 = 说书人伪步骤
	Ability     string
	FirstNight  bool
	OtherNights bool
	Icon        string
	// NeedsChoice 夜晚需要玩家主动选择目标：
	// 真人 → 挂起相位 + 前端选择 UI + 超时兜底；AI → 内部直通决策
	// 当前落地：占卜师；预留：僧侣/管家/投毒者/小恶魔
	NeedsChoice bool
}

// 夜晚行动顺序（严格遵循官方钟楼百科：暗流涌动）
// 首夜：无僧侣、无小恶魔（小恶魔首夜不行动）
var NightOrderFirst = []string{
	"minion_info", "demon_info", "poisoner", "spy",
	"washerwoman", "librarian", "investigator", "chef",
	"empath", "fortune_teller", "butler",
}

// 其他夜：红唇女郎/间谍为说书人提醒步骤（被动空走）
var NightOrderOther = []string{
	"poisoner", "monk", "spy", "scarlet_woman", "imp",
	"ravenkeeper", "undertaker", "empath", "fortune_teller", "butler",
}

// Roles 全部角色表（含说书人信息步骤）
var Roles = map[string]RoleDef{
	// ——— 说书人信息步骤 (伪角色) ————————————————
	"minion_info": {Key: "minion_info", Name: "爪牙信息", Ability: "爪牙得知恶魔", FirstNight: true, Icon: "📋"},
	"demon_info":  {Key: "demon_info", Name: "恶魔信息", Ability: "恶魔得知爪牙与三个不在场镇民", FirstNight: true, Icon: "📋"},

	// ——— 镇民 (13) ————————————————
	"washerwoman": {Key: "washerwoman", Name: "洗衣妇", Team: TeamTownsfolk,
		Ability:    "在你的首个夜晚，你会得知两名玩家，其中一名是某镇民。",
		FirstNight: true, Icon: "🧺"},
	"librarian": {Key: "librarian", Name: "图书管理员", Team: TeamTownsfolk,
		Ability:    "在你的首个夜晚，你会得知两名玩家，其中一名是某外来者（或没有外来者在场）。",
		FirstNight: true, Icon: "📚"},
	"investigator": {Key: "investigator", Name: "调查员", Team: TeamTownsfolk,
		Ability:    "在你的首个夜晚，你会得知两名玩家，其中一名是爪牙。",
		FirstNight: true, Icon: "🔍"},
	"chef": {Key: "chef", Name: "厨师", Team: TeamTownsfolk,
		Ability:    "在你的首个夜晚，你会得知有多少对相邻的存活玩家是邪恶阵营。",
		FirstNight: true, Icon: "👨‍🍳"},
	"empath": {Key: "empath", Name: "共情者", Team: TeamTownsfolk,
		Ability:    "每个夜晚，你会得知与你的两名相邻存活玩家中，有几人是邪恶阵营。",
		FirstNight: true, OtherNights: true, Icon: "💗"},
	"fortune_teller": {Key: "fortune_teller", Name: "占卜师", Team: TeamTownsfolk,
		Ability:    "每个夜晚，你要选择两名玩家（其中一人可以是自己）：你会得知其中是否有恶魔。",
		FirstNight: true, OtherNights: true, Icon: "🔮", NeedsChoice: true},
	"undertaker": {Key: "undertaker", Name: "送葬者", Team: TeamTownsfolk,
		Ability:     "每个夜晚*，你会得知今天因处决而死去的玩家的角色。",
		OtherNights: true, Icon: "⚰️"},
	"monk": {Key: "monk", Name: "僧侣", Team: TeamTownsfolk,
		Ability:     "每个夜晚*，你要选择一名玩家（与上个夜晚不同）：他当晚不会因恶魔而死。",
		OtherNights: true, Icon: "🧘", NeedsChoice: true},
	"ravenkeeper": {Key: "ravenkeeper", Name: "守鸦人", Team: TeamTownsfolk,
		Ability:     "如果你在夜晚死去，你醒来后会选择一名玩家，得知他的角色。",
		OtherNights: true, Icon: "🐦‍⬛"},
	"virgin": {Key: "virgin", Name: "贞洁者", Team: TeamTownsfolk,
		Ability: "当你首次被一名镇民提名时，该镇民立即被处决。",
		Icon:    "🌸"},
	"slayer": {Key: "slayer", Name: "猎手", Team: TeamTownsfolk,
		Ability: "每局游戏限一次，在白天，你可以公开选择一名玩家：如果他是恶魔，他死亡。",
		Icon:    "🏹"},
	"soldier": {Key: "soldier", Name: "士兵", Team: TeamTownsfolk,
		Ability: "你不会因恶魔而死。",
		Icon:    "🪖"},
	"mayor": {Key: "mayor", Name: "镇长", Team: TeamTownsfolk,
		Ability: "如果只有三名玩家存活，且当天没有玩家被处决，你的阵营获胜。",
		Icon:    "🏛️"},

	// ——— 外来者 (4) ————————————————
	"butler": {Key: "butler", Name: "管家", Team: TeamOutsider,
		Ability:    "每个夜晚，你要选择你的主人。只有主人投票时，你才能投票。",
		FirstNight: true, OtherNights: true, Icon: "🫖", NeedsChoice: true},
	"drunk": {Key: "drunk", Name: "酒鬼", Team: TeamOutsider,
		Ability:    "你以为你是一个镇民，但其实你不是。",
		FirstNight: true, OtherNights: true, Icon: "🍺"},
	"recluse": {Key: "recluse", Name: "陌客", Team: TeamOutsider,
		Ability: "你可能被当作邪恶阵营或恶魔。",
		Icon:    "🕳️"},
	"saint": {Key: "saint", Name: "圣徒", Team: TeamOutsider,
		Ability: "如果你被处决，善良阵营落败。",
		Icon:    "😇"},

	// ——— 爪牙 (4) ————————————————
	"poisoner": {Key: "poisoner", Name: "投毒者", Team: TeamMinion,
		Ability:    "每个夜晚，你要选择一名玩家：他的能力失效，并可能得到错误信息，直到下个黄昏。",
		FirstNight: true, OtherNights: true, Icon: "🧪", NeedsChoice: true},
	"spy": {Key: "spy", Name: "间谍", Team: TeamMinion,
		Ability:    "每个夜晚，你会查看魔典，得知所有玩家的角色。",
		FirstNight: true, OtherNights: true, Icon: "🕶️"},
	"scarlet_woman": {Key: "scarlet_woman", Name: "红唇女郎", Team: TeamMinion,
		Ability: "如果恶魔死亡且存活玩家不少于五人，你成为恶魔。",
		Icon:    "💃"},
	"baron": {Key: "baron", Name: "男爵", Team: TeamMinion,
		Ability: "场上会多两名外来者。",
		Icon:    "🎩"},

	// ——— 恶魔 (1) ————————————————
	"imp": {Key: "imp", Name: "小恶魔", Team: TeamDemon,
		Ability:     "每个夜晚*，你要选择一名玩家：他死亡。如果你因任何原因死亡，且场上有爪牙存活，一名爪牙会成为小恶魔。",
		OtherNights: true, Icon: "😈", NeedsChoice: true},
}

// GetRolesByTeam 按阵营获取角色
func GetRolesByTeam(team string) []string {
	out := []string{}
	for k, v := range Roles {
		if v.Team == team {
			out = append(out, k)
		}
	}
	return out
}
