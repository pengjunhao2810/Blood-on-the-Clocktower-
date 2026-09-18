package engine

import "testing"

// 用例 5：票数超过存活半数且最高 → 处决死亡（冷却到期统一比对）
func TestVoteMajorityExecuted(t *testing.T) {
	e, gd := makeNominateGame(6) // 6 人存活，半数=3，需 >3 票
	// 全部 AI 设为投赞成
	aiVoteYes := func(p *PlayerState) string { return "yes" }
	_ = aiVoteYes
	// 直接控制投票：StartVoting 后手动让所有 AI 投 yes
	e.Nominate(1, 2)
	e.StartVoting()
	// AI 已投（aiVoteChoice 随机）；手动补投全部存活玩家 yes
	for _, p := range gd.Players {
		if p.Alive {
			gd.ActiveVote.Votes[p.Number] = "yes"
		}
	}
	finish := e.FinishVote()
	if finish["cooldown"] == nil {
		t.Fatalf("投票结束应开启提名冷却: %v", finish)
	}
	if gd.NomCooldownUntil == 0 {
		t.Fatal("应开启 30 秒提名冷却窗口")
	}
	// 冷却到期：统一比对处决
	result := e.ResolveNominationPeriod()
	if result == nil || result["executed"] != true {
		t.Fatalf("过半票数应处决: %v", result)
	}
	if gd.Players["1"].Alive {
		t.Fatal("#2 应被处决死亡")
	}
	// 处决后提名记录清空、冷却清除
	if len(gd.Nominations) != 0 {
		t.Fatal("处决后提名记录应清空")
	}
	if gd.NomCooldownUntil != 0 {
		t.Fatal("处决后冷却应清除（直接入夜）")
	}
}

// 用例 6：未过半票数（2 票）→ 最高票处决（不再判断是否过半）+ 30 秒冷却
func TestVoteNoMajorityCooldown(t *testing.T) {
	e, gd := makeNominateGame(6)
	e.Nominate(1, 2)
	e.StartVoting()
	// 仅 2 票赞成（#3/#4 非辩论双方，2 票 < 半数 3）
	gd.ActiveVote.Votes = map[int]string{3: "yes", 4: "yes"}
	finish := e.FinishVote()
	if finish["cooldown"] == nil || gd.NomCooldownUntil == 0 {
		t.Fatal("投票结束应开启 30 秒提名冷却")
	}
	// 冷却期内拒绝新提名
	if res := e.Nominate(3, 4); res["success"] == false {
		msg, _ := res["message"].(string)
		if !containsStr(msg, "冷却") {
			t.Fatalf("冷却拒绝消息错误: %v", res)
		}
	} else {
		t.Fatal("冷却期内应拒绝新提名")
	}
	// 冷却到期：最高票处决（不再判断是否过半）
	res := e.ResolveNominationPeriod()
	if res == nil || res["executed"] != true {
		t.Fatalf("最高票应处决（无需过半）: %v", res)
	}
	if gd.Players["1"].Alive {
		t.Fatal("#2（最高票 2 票）应被处决死亡")
	}
}

// 用例：0 票场景 → 无人处决
func TestVoteZeroYesNoExecuted(t *testing.T) {
	e, gd := makeNominateGame(6)
	e.Nominate(1, 2)
	e.StartVoting()
	gd.ActiveVote.Votes = map[int]string{} // 无人投赞成
	e.FinishVote()
	res := e.ResolveNominationPeriod()
	if res == nil || res["executed"] == true {
		t.Fatalf("0 票应无人处决: %v", res)
	}
	for _, p := range gd.Players {
		if !p.Alive {
			t.Fatal("无人死亡")
		}
	}
}

// 用例 4：多提名比对——1提3得7票，4提6得5票 → 3 票数最高 → 处决（不做过半判断）
func TestMultiNominationHighestExecuted(t *testing.T) {
	e, gd := makeNominateGame(12)
	// 手动构造两次提名记录
	gd.Nominations = []*NominationRecord{
		{FromNumber: 1, TargetNumber: 3, Yes: 7, Abstain: 5},
		{FromNumber: 4, TargetNumber: 6, Yes: 5, Abstain: 7},
	}
	gd.NomCooldownUntil = 1 // 模拟冷却已到期
	result := e.ResolveNominationPeriod()
	if result["executed"] != true {
		t.Fatalf("#3 票数最高应处决: %v", result)
	}
	if result["target"] != 3 {
		t.Fatalf("应处决 #3, got %v", result["target"])
	}
	if gd.Players["2"].Alive {
		t.Fatal("#3 应死亡")
	}
	if !gd.Players["5"].Alive {
		t.Fatal("#6 不应死亡")
	}
}

// 用例 5：多提名票数并列最高 → 无人处决
func TestMultiNominationTieNoExecuted(t *testing.T) {
	e, gd := makeNominateGame(12)
	gd.Nominations = []*NominationRecord{
		{FromNumber: 1, TargetNumber: 3, Yes: 6, Abstain: 6},
		{FromNumber: 4, TargetNumber: 6, Yes: 6, Abstain: 6},
	}
	gd.NomCooldownUntil = 1
	result := e.ResolveNominationPeriod()
	if result["executed"] == true {
		t.Fatalf("并列最高不应处决: %v", result)
	}
	for _, p := range gd.Players {
		if !p.Alive {
			t.Fatal("无人处决")
		}
	}
	// 周期结束：提名记录清空
	if len(gd.Nominations) != 0 {
		t.Fatal("周期结束后提名记录应清空")
	}
}
