package engine

import "testing"

// 构造提名测试局：全 AI 玩家（投票自动），验证多提名统计逻辑
func makeNominateGame(n int) (*Engine, *GameData) {
	gd := &GameData{Players: map[string]*PlayerState{}, Phase: "nomination"}
	for i := 0; i < n; i++ {
		gd.Players[itoa(i)] = &PlayerState{
			UserID: uint(i + 1), Username: "p" + itoa(i), Number: i + 1,
			Seat: i, IsAI: true, AIType: "local", Alive: true,
			Role: "washerwoman", Team: TeamTownsfolk, RoleName: "洗衣妇",
		}
	}
	return NewEngine(gd, "TESTNOM", func(string, any) {}), gd
}

func TestNominationMultiHighestExecuted(t *testing.T) {
	e, gd := makeNominateGame(6)

	// 手动构造提名记录（模拟多轮投票后的结果）
	// 目标 #2 得 4 票（过半），目标 #3 得 5 票（过半且最高）→ #3 应被处决
	gd.Nominations = []*NominationRecord{
		{FromNumber: 1, TargetNumber: 2, Yes: 4, No: 2, Abstain: 0},
		{FromNumber: 4, TargetNumber: 3, Yes: 5, No: 1, Abstain: 0},
	}
	result := e.EndNomination()
	if result["executed"] != true {
		t.Fatalf("应有处决: %v", result)
	}
	if result["target"] != 3 {
		t.Fatalf("应处决得票最高的 #3，实际 %v", result["target"])
	}
	if gd.Players["2"].Alive {
		t.Fatal("#3 应被处决死亡")
	}
	if !gd.Players["1"].Alive {
		t.Fatal("#2 不应被处决")
	}
}

func TestNominationNoMajority(t *testing.T) {
	e, gd := makeNominateGame(6)
	// 所有提名都未过半 → 平安日
	gd.Nominations = []*NominationRecord{
		{FromNumber: 1, TargetNumber: 2, Yes: 2, No: 4, Abstain: 0},
		{FromNumber: 4, TargetNumber: 3, Yes: 3, No: 3, Abstain: 0},
	}
	result := e.EndNomination()
	if result["executed"] == true {
		t.Fatalf("未过半不应处决: %v", result)
	}
	for _, p := range gd.Players {
		if !p.Alive {
			t.Fatal("平安日不应有人死亡")
		}
	}
}

func TestNominateVoteFlow(t *testing.T) {
	e, gd := makeNominateGame(6)
	// 发起提名：进入辩论期，辩论结束后全 AI 自动投票，倒计时结束统计
	result := e.Nominate(1, 2)
	if result["nominated"] != true {
		t.Fatalf("提名失败: %v", result)
	}
	if result["debate"] != true {
		t.Fatalf("提名后应先进入辩论: %v", result)
	}
	if gd.ActiveVote == nil {
		t.Fatal("辩论期投票状态应存在")
	}
	res, done := e.StartVoting()
	if done {
		t.Fatal("StartVoting 不应立即完成")
	}
	if res["vote_start"] != true || gd.ActiveVote.VoteDeadline == 0 {
		t.Fatalf("投票倒计时应启动: %v", res)
	}
	// AI 已自动投票
	if len(gd.ActiveVote.Votes) == 0 {
		t.Fatal("AI 玩家应在投票开始时自动投票")
	}
	// 倒计时结束统计
	finish := e.FinishVote()
	if finish == nil {
		t.Fatal("FinishVote 失败")
	}
	if gd.ActiveVote != nil {
		t.Fatal("统计后投票状态应清除")
	}
	if len(gd.Nominations) != 1 {
		t.Fatalf("应有 1 条提名记录, got %d", len(gd.Nominations))
	}
	rec := gd.Nominations[0]
	if rec.TargetNumber != 2 || rec.FromNumber != 1 {
		t.Fatalf("提名记录错误: %+v", rec)
	}
	// 未处决 → 提名冷却开启
	if gd.NomCooldownUntil == 0 {
		t.Fatal("未处决应开启提名冷却窗口")
	}
}

func TestNominateVoteWithHuman(t *testing.T) {
	e, gd := makeNominateGame(6)
	// 玩家 0 设为真人
	gd.Players["0"].IsAI = false
	gd.Players["0"].AIType = ""

	// 发起提名：进入辩论期，辩论结束后开始同时投票
	result := e.Nominate(1, 2)
	if result["debate"] != true {
		t.Fatalf("提名后应先进入辩论: %v", result)
	}
	e.StartVoting()
	if gd.ActiveVote == nil || gd.ActiveVote.VoteDeadline == 0 {
		t.Fatal("投票状态应存在")
	}
	// 真人投票（#3 非辩论双方）→ 成功（倒计时内）
	_, _, err := e.CastVote(3, "yes")
	if err != nil {
		t.Fatalf("投票失败: %v", err)
	}
	if gd.ActiveVote.Votes[3] != "yes" {
		t.Fatal("真人投票应记录")
	}
	// 辩论双方不能投票（提名者 #1）
	_, _, err = e.CastVote(1, "yes")
	if err == nil {
		t.Fatal("提名双方不应能投票")
	}
	// 取消投票（反复切换意向）
	_, _, err = e.CastVote(3, "abstain")
	if err != nil {
		t.Fatalf("取消投票失败: %v", err)
	}
	if _, exists := gd.ActiveVote.Votes[3]; exists {
		t.Fatal("取消投票后应移除票")
	}
	// 再次投票（可反复切换）
	_, _, err = e.CastVote(3, "yes")
	if err != nil {
		t.Fatalf("再次投票失败: %v", err)
	}
	// 辩论期不能投票（新提名后未 StartVoting）
	e.FinishVote()
	e.Nominate(2, 3)
	if gd.ActiveVote != nil && gd.ActiveVote.VoteDeadline == 0 {
		_, _, err = e.CastVote(1, "yes")
		if err == nil {
			t.Fatal("辩论期投票应被拒绝")
		}
	}
}

func TestNominateCooldownWindow(t *testing.T) {
	e, gd := makeNominateGame(6)
	e.Nominate(1, 2)
	e.StartVoting()
	finish := e.FinishVote()
	if finish["cooldown"] == nil {
		t.Fatalf("未处决应开启冷却: %v", finish)
	}
	// 冷却期内新提名被拒绝
	res := e.Nominate(3, 4)
	if res["success"] == false {
		if msg, _ := res["message"].(string); msg != "提名冷却中，请 30 秒后再提名" && !containsStr(msg, "冷却") {
			t.Fatalf("冷却拒绝消息错误: %v", res)
		}
	} else {
		t.Fatal("冷却期内应拒绝新提名")
	}
	// 冷却过期后可提名
	gd.NomCooldownUntil = 0
	res2 := e.Nominate(3, 4)
	if res2["nominated"] != true {
		t.Fatalf("冷却结束后应可提名: %v", res2)
	}
}

func containsStr(s, sub string) bool {
	return len(s) >= len(sub) && (s == sub || containsStrIndex(s, sub) >= 0)
}
func containsStrIndex(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}

func TestNominateDeadAllowedButNoRepeat(t *testing.T) {
	e, gd := makeNominateGame(6)
	// 玩家 #2 死亡
	gd.Players["1"].Alive = false
	// 允许提名死人
	result := e.Nominate(1, 2)
	if result["nominated"] != true {
		t.Fatalf("应允许提名死人: %v", result)
	}
	e.StartVoting() // 辩论结束，AI 投票
	e.FinishVote()  // 倒计时结束统计（未处决 → 30 秒冷却）
	gd.NomCooldownUntil = 0
	// 投票完成后（同一天）再提名同一人 → 拒绝
	result2 := e.Nominate(3, 2)
	if result2["success"] == false && result2["message"] == "该玩家已被提名过，不能再提名" {
		// 预期拒绝
	} else {
		t.Fatalf("被提名过的玩家应拒绝再次提名: %v", result2)
	}
	// 处决死人：EndNomination 无论投票是否过半，死人都不应复活
	res := e.EndNomination()
	_ = res["executed"]
	if gd.Players["1"].Alive {
		t.Fatal("死人不应复活")
	}
}
