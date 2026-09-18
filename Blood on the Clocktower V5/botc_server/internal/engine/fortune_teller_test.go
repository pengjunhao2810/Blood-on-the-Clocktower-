package engine

import "testing"

// 构造手动角色分配的 6 人局（绕过 StartGame 的随机分配）
func makeFortuneTellerGame(humanSeer bool) (*Engine, *GameData) {
	gd := &GameData{Players: map[string]*PlayerState{}}
	for i := 0; i < 6; i++ {
		gd.Players[itoa(i)] = &PlayerState{
			UserID: uint(i + 1), Username: "p" + itoa(i), Number: i + 1,
			Seat: i, IsAI: i > 0, AIType: "local", Alive: true,
			Role: "washerwoman", Team: TeamTownsfolk, RoleName: "洗衣妇",
			FlagEvil: i == 1, FlagGood: i != 1,
		}
	}
	// 0 号：占卜师（真人/AI 可切换）；1、2 号：无夜晚行动角色（避免随机毒/杀干扰占卜师）
	p0 := gd.Players["0"]
	p0.Role = "fortune_teller"
	p0.RoleName = "占卜师"
	p0.IsAI = !humanSeer
	if !humanSeer {
		p0.AIType = "local"
	} else {
		p0.AIType = ""
	}
	gd.Players["1"].Role = "minstrel"
	gd.Players["1"].RoleName = "吟游诗人"
	gd.Players["1"].Team = TeamMinion
	gd.Players["1"].FlagEvil = true
	gd.Players["1"].FlagGood = false
	gd.Players["2"].Role = "minstrel"
	gd.Players["2"].RoleName = "吟游诗人"
	gd.Players["2"].Team = TeamMinion
	gd.Players["2"].FlagEvil = true
	gd.Players["2"].FlagGood = false

	gd.Phase = "night"
	gd.FirstNight = false // 其他夜顺序：poisoner(无)→monk(无)→imp(无)→fortune_teller(0号)
	gd.NightIdx = 0
	gd.RedHerringPID = "3"
	e := NewEngine(gd, "TESTFT", func(string, any) {})
	e.HumanChoice = true // 开启真人交互（挂起测试）
	return e, gd
}

// advanceTo 推进直到返回 waiting 或到达 day
func advanceTo(e *Engine, steps int) map[string]any {
	var last map[string]any
	for i := 0; i < steps; i++ {
		last = e.AdvancePhase()
		if last["waiting"] == true {
			return last
		}
		if last["phase"] == "day" {
			return last
		}
	}
	return last
}

func TestFortuneTellerHumanAutoWhenChoiceOff(t *testing.T) {
	// 开关关闭（默认）：真人占卜师不挂起，自动执行夜晚（毕设演示模式）
	e, gd := makeFortuneTellerGame(true)
	e.HumanChoice = false
	res := advanceTo(e, 10)
	if res["waiting"] == true {
		t.Fatal("开关关闭时真人占卜师不应挂起")
	}
	if gd.PendingChoice != nil {
		t.Fatal("开关关闭时不应设置 PendingChoice")
	}
	// 占卜师行动已自动执行（有说书人消息）
	found := false
	for _, m := range gd.StorytellerMsgs {
		if m.PlayerNumber == 1 {
			found = true
		}
	}
	if !found {
		t.Fatal("真人占卜师自动模式应收到占卜结果")
	}
}

func TestFortuneTellerHumanPending(t *testing.T) {
	e, gd := makeFortuneTellerGame(true)
	// 推进：poisoner(无) → monk(无) → spy(无) → scarlet(无) → imp(无) → raven(无) → undertaker(无) → empath(无) → fortune_teller(真人挂起，第9步)
	res := advanceTo(e, 12)
	if res["waiting"] != true {
		t.Fatalf("真人占卜师应挂起等待, got %v", res)
	}
	pc := gd.PendingChoice
	if pc == nil {
		t.Fatal("NightPendingChoice 未设置")
	}
	if pc.Number != 1 || pc.RoleKey != "fortune_teller" || pc.Deadline == 0 {
		t.Fatalf("挂起信息错误: %+v", pc)
	}
	if len(pc.ValidTargets) < 2 {
		t.Fatalf("合法目标不足: %v", pc.ValidTargets)
	}
	if gd.NightIdx != 8 {
		t.Fatalf("挂起时 night_idx 应为 8（第9步）, got %d", gd.NightIdx)
	}

	// 提交选择（manual）
	result, err := e.ResolveChoice(pc.PlayerID, pc.RoleKey, []int{2, 4}, ChoiceManual)
	if err != nil {
		t.Fatalf("提交失败: %v", err)
	}
	if result["step"] != float64(9) && result["step"] != 9 {
		t.Fatalf("结算后步骤应为 9, got %v", result["step"])
	}
	if gd.PendingChoice != nil {
		t.Fatal("结算后挂起应清除")
	}
	if gd.NightIdx != 9 {
		t.Fatalf("结算后 night_idx 应为 9, got %d", gd.NightIdx)
	}
	// 说书人消息生成
	foundMsg := false
	for _, m := range gd.StorytellerMsgs {
		if m.PlayerNumber == 1 {
			foundMsg = true
			break
		}
	}
	if !foundMsg {
		t.Fatal("占卜师应收到占卜结果消息")
	}
	// 选择方式日志：manual
	if len(gd.ActionLog) != 1 || gd.ActionLog[0]["choice"] != ChoiceManual {
		t.Fatalf("ActionLog 应记录 manual, got %v", gd.ActionLog)
	}
}

func TestFortuneTellerHumanTimeoutFallback(t *testing.T) {
	e, gd := makeFortuneTellerGame(true)
	res := advanceTo(e, 12)
	if res["waiting"] != true {
		t.Fatalf("真人占卜师应挂起, got %v", res)
	}
	pc := gd.PendingChoice
	// 超时兜底：空目标 → 随机合法目标
	result, err := e.ResolveChoice(pc.PlayerID, pc.RoleKey, nil, ChoiceTimeout)
	if err != nil {
		t.Fatalf("兜底结算失败: %v", err)
	}
	if gd.PendingChoice != nil {
		t.Fatal("兜底后挂起应清除")
	}
	if result["phase"] != "night" {
		t.Fatalf("兜底后应继续夜晚: %v", result)
	}
	if gd.NightIdx != 9 {
		t.Fatalf("兜底后 night_idx 应推进, got %d", gd.NightIdx)
	}
	if gd.ActionLog[0]["choice"] != ChoiceTimeout {
		t.Fatalf("ActionLog 应记录 timeout, got %v", gd.ActionLog)
	}
}

func TestFortuneTellerAINoPending(t *testing.T) {
	e, gd := makeFortuneTellerGame(false)
	// AI 占卜师：整个夜晚不挂起
	res := advanceTo(e, 10)
	if res["waiting"] == true {
		t.Fatal("AI 占卜师不应挂起等待")
	}
	if gd.PendingChoice != nil {
		t.Fatal("AI 占卜师不应设置挂起")
	}
	// 占卜师行动已执行（有说书人消息）
	found := false
	for _, m := range gd.StorytellerMsgs {
		if m.PlayerNumber == 1 {
			found = true
		}
	}
	if !found {
		t.Fatal("AI 占卜师应收到占卜结果")
	}
	// 选择方式日志：ai
	hasAI := false
	for _, a := range gd.ActionLog {
		if a["choice"] == ChoiceAI {
			hasAI = true
		}
	}
	if !hasAI {
		t.Fatalf("ActionLog 应记录 ai, got %v", gd.ActionLog)
	}
}

func TestFortuneTellerPendingRejectAdvance(t *testing.T) {
	e, gd := makeFortuneTellerGame(true)
	advanceTo(e, 12)
	if gd.PendingChoice == nil {
		t.Fatal("应有挂起")
	}
	// 挂起期间再次推进：不应重复挂起/推进（StepNight 会重新返回 waiting）
	res := e.AdvancePhase()
	if res["waiting"] != true {
		t.Fatalf("挂起期间推进应仍返回 waiting, got %v", res)
	}
	if gd.NightIdx != 8 {
		t.Fatalf("挂起期间 night_idx 不应变化, got %d", gd.NightIdx)
	}
}

func TestOtherRolesUnaffected(t *testing.T) {
	// 非占卜师夜晚流程不受影响：完整首夜推进到 day
	e, gd := makeGame(6)
	e.StartGame()
	// 把占卜师玩家强制改为 AI，确保不挂起
	for _, p := range gd.Players {
		if p.Role == "fortune_teller" {
			p.IsAI = true
		}
	}
	for i := 0; i < len(NightOrderFirst)+2; i++ {
		res := e.AdvancePhase()
		if res["phase"] == "day" {
			break
		}
	}
	if gd.Phase != "day" {
		t.Fatalf("完整首夜应到达 day, got %s", gd.Phase)
	}
}
