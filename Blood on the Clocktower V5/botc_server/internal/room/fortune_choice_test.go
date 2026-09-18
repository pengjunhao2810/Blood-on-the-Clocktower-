package room

import (
	"testing"
	"time"

	"botc-server/internal/engine"
)

// 构造：真人占卜师（HumanChoice 开启）+ 若干 AI 玩家，夜晚推进到占卜师步骤挂起
func makeFortunePendingRoom(t *testing.T) (*Room, *Manager, *engine.NightPendingChoice) {
	r, mgr := newNightChoiceRoom(t)
	// 指定一位真人玩家为占卜师
	var pid string
	for k, p := range r.game.Players {
		if !p.IsAI {
			pid = k
			break
		}
	}
	p := r.game.Players[pid]
	p.Role = "fortune_teller"
	r.eng.HumanChoice = true

	// 夜晚推进直到挂起（占卜师在首夜顺序中）
	var pc *engine.NightPendingChoice
	for i := 0; i < len(engine.NightOrderFirst); i++ {
		res := r.eng.AdvancePhase()
		if res["waiting"] == true {
			pc = r.game.PendingChoice
			break
		}
		if res["phase"] != "night" {
			break
		}
	}
	if pc == nil {
		t.Fatal("未到达占卜师挂起")
	}
	if pc.RoleKey != "fortune_teller" {
		t.Fatalf("挂起角色应为 fortune_teller, got %s", pc.RoleKey)
	}
	return r, mgr, pc
}

// 用例 1：真人占卜师选择 2 名目标提交 → 挂起解除 → 夜晚完整走完 → day（之后才允许私聊）
func TestFortuneTellerSubmitChoiceFlow(t *testing.T) {
	r, mgr, pc := makeFortunePendingRoom(t)
	defer mgr.Delete(r.Code)

	// 选择 2 个合法目标提交
	targets := []int{pc.ValidTargets[0], pc.ValidTargets[1]}
	result, err := r.eng.ResolveChoice(pc.PlayerID, pc.RoleKey, targets, engine.ChoiceManual)
	if err != nil {
		t.Fatalf("提交失败: %v", err)
	}
	if result["phase"] != "night" {
		t.Fatalf("提交后应继续夜晚, got %v", result["phase"])
	}
	if r.game.PendingChoice != nil {
		t.Fatal("提交后挂起应清除")
	}

	// 夜晚继续走完全部步骤 → day（走完前 Phase 不得为 private_chat/day）
	for r.game.Phase == "night" {
		res := r.eng.AdvancePhase()
		if res["waiting"] == true {
			// 真人占卜师已行动过，不应再挂起
			t.Fatal("占卜师行动后不应再次挂起")
		}
	}
	if r.game.Phase != "day" {
		t.Fatalf("夜晚走完应进入 day, got %s", r.game.Phase)
	}
	// 挂起中/夜晚中 enterPrivateChat 必须被守卫拒绝
	r.game.Phase = "night"
	r.game.PendingChoice = &engine.NightPendingChoice{Number: 1, Deadline: time.Now().Add(60).Unix()}
	r.enterPrivateChat()
	if r.game.Phase == "private_chat" {
		t.Fatal("夜晚挂起中禁止进入私聊（守卫失效）")
	}
	r.game.PendingChoice = nil
	r.game.Phase = "day"
}

// 用例 2：真人占卜师不操作 → 45 秒超时兜底 → AI 代选 → 夜晚完整走完进入 day，中途不弹私聊
func TestFortuneTellerTimeoutFallback(t *testing.T) {
	r, mgr, pc := makeFortunePendingRoom(t)
	defer mgr.Delete(r.Code)

	// 超时兜底：deadline 过期 → AI 自动代选 → 挂起清除、夜晚继续
	r.game.PendingChoice.Deadline = time.Now().Add(-1 * time.Second).Unix()
	r.checkPendingTimeout()
	if r.game.PendingChoice != nil {
		t.Fatal("超时后挂起应清除（AI 代选兜底）")
	}
	if r.game.NightIdx != pc.StepIdx+1 {
		t.Fatalf("超时后夜晚应推进, NightIdx=%d", r.game.NightIdx)
	}
	// 挂起解除后夜晚阶段禁止进入私聊（守卫）
	r.enterPrivateChat()
	if r.game.Phase == "private_chat" {
		t.Fatal("夜晚阶段禁止进入私聊")
	}
	// 夜晚走完 → day
	for r.game.Phase == "night" {
		r.eng.AdvancePhase()
	}
	if r.game.Phase != "day" {
		t.Fatalf("应进入 day, got %s", r.game.Phase)
	}
	// day → private_chat 正常路径（此时允许）
	r.eng.AdvancePhase()
	if r.game.Phase != "private_chat" {
		t.Fatalf("day 后应进入 private_chat, got %s", r.game.Phase)
	}
}
