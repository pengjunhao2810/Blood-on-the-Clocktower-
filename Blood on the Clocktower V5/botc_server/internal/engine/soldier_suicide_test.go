package engine

import "testing"

// 士兵：恶魔可以选择士兵，但杀不死（官方规则）
func TestSoldierBlockableTarget(t *testing.T) {
	e := makePoisonGame(t)
	e.GD.Players["4"].Role = "soldier"
	e.GD.Players["4"].RoleName = "士兵"
	// 恶魔击杀：确保目标为士兵（其余玩家设为死亡，仅剩恶魔和士兵）
	for _, pid := range []string{"1", "2", "3"} {
		e.GD.Players[pid].Alive = false
	}
	action := e.DoAction("0", "imp", false)
	blocked, _ := action["blocked"].(bool)
	if !blocked {
		t.Fatalf("恶魔选中士兵应返回 blocked: %v", action)
	}
	if !e.GD.Players["4"].Alive {
		t.Fatal("士兵不应死亡")
	}
}

// 真人恶魔自杀：多名爪牙时二次挂起选择继承者
func TestImpSuicideChooseHeir(t *testing.T) {
	e := makePoisonGame(t)
	imp := e.GD.Players["0"]
	imp.IsAI = false
	imp.AIType = ""
	// 两名存活爪牙：#4、#5
	e.GD.Players["3"].Team = TeamMinion
	e.GD.Players["4"].Team = TeamMinion
	// 挂起模拟
	e.GD.PendingChoice = &NightPendingChoice{
		PlayerID: "0", Number: 1, RoleKey: "imp",
		StepIdx: 3, Total: 10, Deadline: 0,
		ValidTargets: []int{1, 2, 3, 4, 5}, MaxTargets: 1,
	}
	result, err := e.ResolveChoice("0", "imp", []int{1}, ChoiceManual)
	if err != nil {
		t.Fatalf("自杀提交失败: %v", err)
	}
	if result["waiting"] != true {
		t.Fatalf("多名爪牙自杀应二次挂起选择继承者: %v", result)
	}
	pc := e.GD.PendingChoice
	if pc == nil || pc.RoleKey != "imp_inherit" {
		t.Fatalf("应挂起传位选择: %+v", pc)
	}
	if e.GD.Players["0"].Alive {
		t.Fatal("恶魔自杀后应死亡（等待传位）")
	}
	// 提交传位选择：#4 继承
	if _, err := e.ResolveChoice("0", "imp_inherit", []int{4}, ChoiceManual); err != nil {
		t.Fatalf("传位提交失败: %v", err)
	}
	heir := e.GD.Players["3"]
	if heir.Role != "imp" {
		t.Fatalf("#4 应成为小恶魔, got %s", heir.Role)
	}
}

// AI 恶魔自杀（单爪牙直传 / 多爪牙随机传）
func TestImpSuicideAI(t *testing.T) {
	e := makePoisonGame(t)
	e.GD.Players["4"].Team = TeamMinion
	action := e.DoAction("0", "imp", false)
	for i := 0; i < 30 && action["suicide"] != true; i++ {
		e2 := makePoisonGame(t)
		e2.GD.Players["4"].Team = TeamMinion
		action = e2.DoAction("0", "imp", false)
		e = e2
	}
	_ = action
	// 若自杀，爪牙必须继承
	if e.GD.Players["0"].Alive == false {
		heirExists := false
		for _, p := range e.GD.Players {
			if p.Role == "imp" && p.Alive {
				heirExists = true
			}
		}
		if !heirExists {
			t.Fatal("自杀后应有爪牙继承恶魔")
		}
	}
}
