package engine

import "testing"

// 验证：真人玩家优先拿到主动选择型角色（占卜师/管家）
func TestHumanPrefersChoiceRoles(t *testing.T) {
	// 10 人局：1 真人 + 9 AI，跑 200 局统计
	humanChoice := 0
	humanTotal := 0
	seerInPlay := 0
	butlerInPlay := 0
	for round := 0; round < 200; round++ {
		gd := &GameData{Players: map[string]*PlayerState{}}
		for i := 0; i < 10; i++ {
			gd.Players[itoa(i)] = &PlayerState{
				UserID: uint(i + 1), Username: "p" + itoa(i), Number: i + 1,
				Seat: i, IsAI: i > 0, AIType: "local", Alive: true,
			}
		}
		e := NewEngine(gd, "TESTPREF", func(string, any) {})
		e.AssignRoles()
		// 统计在场角色
		choiceInPlay := map[string]bool{}
		for _, p := range gd.Players {
			if Roles[p.Role].NeedsChoice {
				choiceInPlay[p.Role] = true
				if p.Role == "fortune_teller" {
					seerInPlay++
				}
				if p.Role == "butler" {
					butlerInPlay++
				}
				if !p.IsAI {
					humanChoice++
				}
			}
			if !p.IsAI {
				humanTotal++
			}
		}
		_ = choiceInPlay
	}
	// 期望：占卜师或管家在场时，真人优先拿到
	// 无男爵时 10 人局 7 镇民：占卜师在场率 7/13、管家在场率 7/13
	// 优化后：真人拿 choice 的次数应 ≈ 占卜师在场数 + 管家在场数（扣除同局双在场竞争）
	ratio := float64(humanChoice) / float64(humanTotal)
	t.Logf("真人拿主动角色次数: %d/%d (%.1f%%)，占卜师在场 %d 局，管家在场 %d 局",
		humanChoice, humanTotal, ratio*100, seerInPlay, butlerInPlay)
	if ratio < 0.5 {
		t.Fatalf("真人优先拿主动角色应显著生效（>=50%%），实际 %.1f%%", ratio*100)
	}
}

// 验证：全 AI 局角色分配依然正常（无真人时逻辑不变）
func TestAllAIChoiceRoles(t *testing.T) {
	for round := 0; round < 50; round++ {
		gd := &GameData{Players: map[string]*PlayerState{}}
		for i := 0; i < 8; i++ {
			gd.Players[itoa(i)] = &PlayerState{
				UserID: uint(i + 1), Username: "p" + itoa(i), Number: i + 1,
				Seat: i, IsAI: true, AIType: "local", Alive: true,
			}
		}
		e := NewEngine(gd, "TESTAI", func(string, any) {})
		e.AssignRoles()
		cnt := map[string]int{}
		for _, p := range gd.Players {
			cnt[p.Team]++
		}
		if cnt[TeamTownsfolk]+cnt[TeamOutsider]+cnt[TeamMinion]+cnt[TeamDemon] != 8 {
			t.Fatalf("全 AI 局角色分配异常: %v", cnt)
		}
	}
}
