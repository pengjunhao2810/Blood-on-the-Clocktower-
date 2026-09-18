package engine

import (
	"encoding/json"
	"strings"
	"testing"
)

// 基础局：imp(恶魔) + monk + fortune_teller + 若干镇民，全部 AI/真人可控
func makePoisonGame(t *testing.T) *Engine {
	gd := &GameData{
		Phase: "night", Day: 1, FirstNight: false, NightIdx: 0,
		Players: map[string]*PlayerState{
			"0": {Number: 1, Role: "imp", Alive: true, IsAI: true, AIType: "local"},
			"1": {Number: 2, Role: "monk", Alive: true, IsAI: true, AIType: "local"},
			"2": {Number: 3, Role: "fortune_teller", Alive: true, IsAI: true, AIType: "local"},
			"3": {Number: 4, Role: "washerwoman", Alive: true, IsAI: true, AIType: "local"},
			"4": {Number: 5, Role: "chef", Alive: true, IsAI: true, AIType: "local"},
		},
	}
	for _, p := range gd.Players {
		ri := Roles[p.Role]
		p.RoleName = ri.Name
		p.Team = ri.Team
		p.FlagEvil = ri.Team == TeamMinion || ri.Team == TeamDemon
		p.FlagGood = !p.FlagEvil
	}
	e := NewEngine(gd, "P", func(string, any) {})
	return e
}

// 用例 1：占卜师中毒——正常挂起/提交选择，收到虚假查验结果，序列化不泄露中毒状态
func TestPoisonedFortuneTellerFakeResult(t *testing.T) {
	e := makePoisonGame(t)
	ft := e.GD.Players["2"]
	ft.Poisoned = true

	// 挂起照常创建（中毒不拦截操作）
	e.GD.PendingChoice = &NightPendingChoice{
		PlayerID: "2", Number: 3, RoleKey: "fortune_teller",
		StepIdx: 8, Total: 10, Deadline: 0,
		ValidTargets: []int{1, 2, 3, 4, 5}, MaxTargets: 2,
	}
	// 玩家提交：查验 [imp(1), 厨师(5)]——真实结果应 found=true（含恶魔）
	result, err := e.ResolveChoice("2", "fortune_teller", []int{1, 5}, ChoiceManual)
	if err != nil {
		t.Fatalf("中毒占卜师提交应成功（不拦截操作）: %v", err)
	}
	if result["phase"] != "night" {
		t.Fatalf("提交后应继续夜晚, got %v", result["phase"])
	}
	msgs, _ := result["msgs"].([]map[string]any)
	foundMsg := ""
	if len(msgs) > 0 {
		foundMsg, _ = msgs[0]["msg"].(string)
	}
	// 中毒：返回虚假结果（反转）——真实含恶魔，应显示"没有恶魔"
	if !strings.Contains(foundMsg, "没有恶魔") {
		t.Fatalf("中毒占卜师应收到虚假结果（没有恶魔）, got %q", foundMsg)
	}
	// 序列化不泄露中毒状态
	b, _ := json.Marshal(e.GD)
	if strings.Contains(string(b), "poisoned") {
		t.Fatal("序列化不应包含 poisoned 字段")
	}
}

// 用例 2：僧侣中毒（真人提交路径）——保护选择正常提交，但保护效果不写入；恶魔击杀目标 → 目标死亡
func TestPoisonedMonkProtectionIneffectiveSubmit(t *testing.T) {
	e := makePoisonGame(t)
	monk := e.GD.Players["1"]
	monk.Poisoned = true

	e.GD.PendingChoice = &NightPendingChoice{
		PlayerID: "1", Number: 2, RoleKey: "monk",
		StepIdx: 3, Total: 10, Deadline: 0,
		ValidTargets: []int{3, 4, 5}, MaxTargets: 1,
	}
	// 保护 #4（washerwoman）
	if _, err := e.ResolveChoice("1", "monk", []int{4}, ChoiceManual); err != nil {
		t.Fatalf("中毒僧侣提交应成功: %v", err)
	}
	if e.GD.Players["3"].Protected {
		t.Fatal("中毒僧侣的保护效果不应写入对局状态")
	}
	// 恶魔击杀 #4（引擎击杀效果：Alive=false + 记录今晚死亡）→ 黎明结算
	e.GD.Players["3"].Alive = false
	e.markNightDeath(4)
	target := e.GD.Players["3"]
	if target.Alive {
		t.Fatal("恶魔攻击应使目标进入死亡（待黎明结算）")
	}
	e.ApplyDeaths()
	if target.Alive {
		t.Fatal("中毒僧侣保护无效：目标应死亡")
	}
}

// 用例 3：僧侣中毒（AI/超时兜底路径）——恶魔攻击被"保护"目标（弹刀场景），目标依旧死亡
func TestPoisonedMonkProtectionIneffectiveDoAction(t *testing.T) {
	e := makePoisonGame(t)
	monk := e.GD.Players["1"]
	monk.Poisoned = true
	// 只保留 imp/monk/#4 存活，僧侣候选 = {#1(imp), #4}
	for _, pid := range []string{"2", "4"} {
		e.GD.Players[pid].Alive = false
	}
	// DoAction 随机选择：MonkLast 排除机制保证第二轮必选 #4（若第一轮选了 #1）
	var action map[string]any
	for i := 0; i < 3; i++ {
		action = e.DoAction("1", "monk", false)
		if t, _ := action["target"].(int); t == 4 {
			break
		}
	}
	tgt, _ := action["target"].(int)
	if tgt != 4 {
		t.Fatalf("僧侣应选择 #4, got %v", action)
	}
	if e.GD.Players["3"].Protected {
		t.Fatal("中毒僧侣保护不生效：Protected 不应被写入")
	}
	// 恶魔击杀 #4（弹刀场景：正常僧侣保护时攻击被弹开，中毒时无效）→ 黎明结算 → 死亡
	e.GD.Players["3"].Alive = false
	e.markNightDeath(4)
	e.ApplyDeaths()
	if e.GD.Players["3"].Alive {
		t.Fatal("中毒僧侣保护无效（弹刀场景）：目标应死亡")
	}
}

// 用例 4：死亡 + 中毒——死亡优先，直接禁用技能（不挂起、不行动）
func TestDeadPoisonedSkipSkill(t *testing.T) {
	e := makePoisonGame(t)
	ft := e.GD.Players["2"]
	ft.Alive = false
	ft.Poisoned = true
	ft.IsAI = false // 真人死亡占卜师：若逻辑错误会挂起

	// 夜晚推进到 fortune_teller 步骤（NightOrderOther 中位置）
	e.GD.NightIdx = 8
	res := e.StepNight()
	if res["waiting"] == true {
		t.Fatal("死亡占卜师不应触发挂起（死亡 > 中毒）")
	}
	if e.GD.PendingChoice != nil {
		t.Fatal("死亡占卜师不应创建挂起")
	}
	msgs, _ := res["msgs"].([]map[string]any)
	for _, m := range msgs {
		if num, ok := m["num"].(int); ok && num == 3 {
			t.Fatal("死亡占卜师不应在夜晚执行技能")
		}
	}
}

// 用例 5：未中毒占卜师/僧侣技能完全正常
func TestNormalRolesUnaffected(t *testing.T) {
	e := makePoisonGame(t)
	// 占卜师正常查验：含恶魔 → found=true
	e.GD.PendingChoice = &NightPendingChoice{
		PlayerID: "2", Number: 3, RoleKey: "fortune_teller",
		StepIdx: 8, Total: 10, Deadline: 0,
		ValidTargets: []int{1, 2, 3, 4, 5}, MaxTargets: 2,
	}
	result, err := e.ResolveChoice("2", "fortune_teller", []int{1, 5}, ChoiceManual)
	if err != nil {
		t.Fatalf("正常占卜师提交失败: %v", err)
	}
	msgs, _ := result["msgs"].([]map[string]any)
	if len(msgs) == 0 {
		t.Fatal("正常占卜师应有查验消息")
	}
	msg, _ := msgs[0]["msg"].(string)
	if !strings.Contains(msg, "有恶魔") {
		t.Fatalf("正常占卜师查验含恶魔应返回真实结果, got %q", msg)
	}
	// 僧侣正常：保护 #4 → Protected 写入 → 恶魔击杀 → 黎明复活
	e.GD.PendingChoice = &NightPendingChoice{
		PlayerID: "1", Number: 2, RoleKey: "monk",
		StepIdx: 3, Total: 10, Deadline: 0,
		ValidTargets: []int{3, 4, 5}, MaxTargets: 1,
	}
	if _, err := e.ResolveChoice("1", "monk", []int{4}, ChoiceManual); err != nil {
		t.Fatalf("正常僧侣提交失败: %v", err)
	}
	if !e.GD.Players["3"].Protected {
		t.Fatal("正常僧侣保护应生效")
	}
	// 恶魔击杀 #4 → 黎明结算 → 被保护复活
	e.GD.Players["3"].Alive = false
	e.markNightDeath(4)
	e.ApplyDeaths()
	if !e.GD.Players["3"].Alive {
		t.Fatal("正常僧侣保护应使目标存活")
	}
}
