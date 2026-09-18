package room

import (
	"testing"

	"botc-server/internal/engine"
)

// TestNightDeathHiddenUntilDawn 夜晚死亡在快照中对外隐藏（黎明前 alive 显示 true）
func TestNightDeathHiddenUntilDawn(t *testing.T) {
	r, mgr := newNightChoiceRoom(t)
	defer mgr.Delete(r.Code)

	// 玩家 #1 夜晚被恶魔杀死
	var pid string
	for k := range r.game.Players {
		pid = k
		break
	}
	p := r.game.Players[pid]
	p.Alive = false
	r.game.Phase = "night"
	r.game.NightDeaths = map[int]bool{p.Number: true}

	snap := r.gameSnapshot()
	players, _ := snap["game"].(map[string]any)["players"].(map[string]*engine.PlayerState)
	if players[pid] == nil {
		t.Fatal("快照玩家缺失")
	}
	if !players[pid].Alive {
		t.Fatal("夜晚阶段快照应对死亡玩家隐藏死亡状态（alive 显示 true）")
	}

	// 黎明公布：ApplyDeaths 清空 NightDeaths 后快照显示真实死亡
	r.game.NightDeaths = nil
	snap2 := r.gameSnapshot()
	players2, _ := snap2["game"].(map[string]any)["players"].(map[string]*engine.PlayerState)
	if players2[pid].Alive {
		t.Fatal("黎明后快照应显示真实死亡状态")
	}
}

// TestNightDeathDisabledSkills 夜晚死亡的玩家在剩余夜晚步骤中被跳过
func TestNightDeathDisabledSkills(t *testing.T) {
	gd := &engine.GameData{
		Phase: "night", Day: 1, FirstNight: false, NightIdx: 2,
		Players: map[string]*engine.PlayerState{
			"0": {Number: 1, Role: "empath", Alive: true, IsAI: true, AIType: "local"},
			"1": {Number: 2, Role: "empath", Alive: false, IsAI: true, AIType: "local"},
		},
	}
	e := engine.NewEngine(gd, "T", func(string, any) {})
	e.GD = gd
	// StepNight 处理 empath 步骤：死亡的 #2 不应出现在行动结果中
	res := e.StepNight()
	msgs, _ := res["msgs"].([]map[string]any)
	for _, m := range msgs {
		if num, ok := m["num"].(int); ok && num == 2 {
			t.Fatal("死亡玩家不应在夜晚执行技能")
		}
	}
}
