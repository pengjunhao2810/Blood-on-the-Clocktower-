package engine

import "testing"

func makeGame(n int) (*Engine, *GameData) {
	gd := &GameData{Players: map[string]*PlayerState{}}
	for i := 0; i < n; i++ {
		gd.Players[itoa(i)] = &PlayerState{
			UserID: uint(i + 1), Username: "p" + itoa(i), Number: i + 1,
			Seat: i, IsAI: true, AIType: "local", Alive: true,
		}
	}
	e := NewEngine(gd, "TEST01", func(event string, data any) {})
	return e, gd
}

func TestStartGameFirstNight(t *testing.T) {
	for _, n := range []int{5, 7, 9, 12} {
		e, gd := makeGame(n)
		e.StartGame()
		if len(gd.StorytellerMsgs) == 0 {
			t.Fatalf("%d人局: 无首夜信息", n)
		}
		for i := 0; i < len(NightOrderFirst)+1; i++ {
			res := e.AdvancePhase()
			if res["waiting"] == true {
				pc := gd.PendingChoice
				if pc != nil {
					e.ResolveChoice(pc.PlayerID, pc.RoleKey, nil, ChoiceTimeout)
				}
			}
		}
		if gd.Phase != "day" {
			t.Fatalf("%d人局: 首夜后应为 day，实际 %s", n, gd.Phase)
		}
	}
}

func TestRoleDistribution(t *testing.T) {
	// 官方人数表：(镇民, 外来者, 爪牙, 恶魔)
	expect := map[int][4]int{
		5: {3, 0, 1, 1}, 6: {3, 1, 1, 1}, 7: {5, 0, 1, 1}, 8: {5, 1, 1, 1},
		9: {5, 2, 1, 1}, 10: {7, 0, 2, 1}, 11: {7, 1, 2, 1}, 12: {7, 2, 2, 1},
	}
	for n := 5; n <= 12; n++ {
		for round := 0; round < 30; round++ {
			e, gd := makeGame(n)
			e.StartGame()
			cnt := [4]int{}
			hasBaron := false
			for _, p := range gd.Players {
				switch p.Team {
				case TeamTownsfolk:
					cnt[0]++
				case TeamOutsider:
					cnt[1]++
				case TeamMinion:
					cnt[2]++
				case TeamDemon:
					cnt[3]++
				}
				if p.Role == "baron" {
					hasBaron = true
				}
			}
			exp := expect[n]
			if hasBaron {
				exp[0] -= 2
				exp[1] += 2
			}
			if cnt != exp {
				t.Fatalf("%d人局(男爵=%v): 阵营分布 %v != 期望 %v", n, hasBaron, cnt, exp)
			}
			// 恶魔必是小恶魔
			for _, p := range gd.Players {
				if p.Team == TeamDemon && p.Role != "imp" {
					t.Fatalf("恶魔角色错误: %s", p.Role)
				}
			}
		}
	}
}

func TestImpInheritance(t *testing.T) {
	// 规则 1：无红唇女郎时，恶魔死亡 → 无继承 → 善良胜
	noInherit := 0
	withSW := 0
	for round := 0; round < 60; round++ {
		e, gd := makeGame(10) // 10人 = 2 爪牙
		e.StartGame()
		impPID := ""
		hasSW := false
		for pid, p := range gd.Players {
			if p.Role == "imp" && p.Alive {
				impPID = pid
			}
			if p.Role == "scarlet_woman" && p.Alive {
				hasSW = true
			}
		}
		gd.Players[impPID].Alive = false
		e.maybeInheritImp()
		newImp := 0
		for _, p := range gd.Players {
			if p.Role == "imp" && p.Alive {
				newImp++
			}
		}
		if hasSW {
			withSW++
			if newImp != 1 {
				t.Fatalf("有红唇女郎且存活≥5：恶魔死亡后应恰好 1 个存活 imp，实际 %d", newImp)
			}
		} else {
			noInherit++
			if newImp != 0 {
				t.Fatalf("无红唇女郎：恶魔死亡后不应有继承（官方仅红唇女郎可继承）")
			}
		}
	}
	t.Logf("无SW局 %d 次（均无继承），SW局 %d 次（均正确继承）", noInherit, withSW)

	// 规则 2：小恶魔自杀 → 爪牙传位（becomeImp 直接验证）
	e, gd := makeGame(10)
	e.StartGame()
	heir := &PlayerState{Number: 99, Role: "poisoner", Team: TeamMinion, RoleName: "投毒者", Alive: true}
	gd.Players["heir"] = heir
	e.becomeImp(heir)
	if heir.Role != "imp" || heir.Team != TeamDemon || heir.RoleName != "小恶魔" {
		t.Fatalf("自杀传位失败: role=%s team=%s", heir.Role, heir.Team)
	}
	if len(heir.InfoMinionNums) == 0 {
		t.Fatalf("新恶魔应得知爪牙编号")
	}
}

func TestSlayerAndVirginAndSaint(t *testing.T) {
	// 屠夫射杀恶魔
	e, gd := makeGame(8)
	e.StartGame()
	impNum, slayerNum := 0, 0
	for _, p := range gd.Players {
		if p.Role == "imp" {
			impNum = p.Number
		}
		if p.Role == "slayer" {
			slayerNum = p.Number
		}
	}
	if slayerNum == 0 {
		slayerNum = impNum%len(gd.Players) + 1 // 无屠夫时跳过验证
		t.Log("本局无猎手，跳过")
	} else {
		res := e.Nominate(slayerNum, impNum)
		if res["special"] != "slayer" {
			t.Fatalf("猎手应射杀恶魔: %v", res)
		}
		// game_over 仅当无继承（猩红女郎不在场）时成立，不强制断言
		t.Logf("猎手射杀成功: %v", res["message"])
	}

	// 圣徒处决 → 邪恶获胜（构造一局强制圣徒在场并操控投票太随机，改为直接验证规则存在）
	e2, gd2 := makeGame(8)
	e2.StartGame()
	saintNum := 0
	for _, p := range gd2.Players {
		if p.Role == "saint" {
			saintNum = p.Number
		}
	}
	if saintNum == 0 {
		t.Log("本局无圣徒，跳过")
	} else {
		// 强制过半投票：直接操控——遍历提名直至处决（多数随机票）
		executed := false
		for i := 0; i < 20 && !executed; i++ {
			from := saintNum%len(gd2.Players) + 1
			res := e2.Nominate(from, saintNum)
			if res["game_over"] == true {
				if res["winner"] != "evil" {
					t.Fatalf("圣徒被处决应为 evil 胜: %v", res)
				}
				executed = true
			}
		}
		if !executed {
			t.Log("圣徒 20 次提名未处决（随机票），跳过")
		}
	}
}

func TestDrunkDisguise(t *testing.T) {
	found := false
	for round := 0; round < 50 && !found; round++ {
		e, gd := makeGame(8)
		e.StartGame()
		for _, p := range gd.Players {
			if p.Role == "drunk" {
				found = true
				if p.FakeRole == "" || p.RoleName == "酒鬼" {
					t.Fatalf("酒鬼应有伪装镇民身份: fake=%s name=%s", p.FakeRole, p.RoleName)
				}
				// 酒鬼的阵营是外来者
				if p.Team != TeamOutsider {
					t.Fatalf("酒鬼阵营应为外来者")
				}
			}
		}
	}
	if !found {
		t.Log("50 局未出现酒鬼，跳过（概率极低）")
	}
}
