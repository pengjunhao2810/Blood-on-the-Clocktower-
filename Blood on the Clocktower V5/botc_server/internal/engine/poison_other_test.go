package engine

import (
	"encoding/json"
	"strings"
	"testing"
)

// 用例 A：共情者中毒——照常行动，返回虚假数字（不等于真实值）
func TestPoisonedEmpathFakeCount(t *testing.T) {
	e := makePoisonGame(t)
	emp := e.GD.Players["2"]
	emp.Role = "empath"
	emp.RoleName = "共情者"
	emp.Poisoned = true
	// 邻居：确保 #3 的相邻（#1 imp 与 #5 chef）有 1 名邪恶（imp 是邪恶）
	action := e.DoAction("2", "empath", false)
	evil, _ := action["evil"].(int)
	// 真实值应为 0（#3 的邻居 #2 僧侣、#4 洗衣妇均为善良）
	if evil == 0 {
		t.Fatalf("中毒共情者应返回虚假数字, got 真实值 %d", evil)
	}
	if evil < 0 || evil > 2 {
		t.Fatalf("共情者数字非法: %d", evil)
	}
}

// 用例 B：送葬者中毒——返回虚假角色名
func TestPoisonedUndertakerFakeRole(t *testing.T) {
	e := makePoisonGame(t)
	ut := e.GD.Players["2"]
	ut.Role = "undertaker"
	ut.RoleName = "送葬者"
	ut.Poisoned = true
	e.GD.LastExecutedPID = "3" // #4 洗衣妇
	e.GD.Players["3"].RoleName = "洗衣妇"
	action := e.DoAction("2", "undertaker", false)
	info, _ := action["info"].(string)
	if !strings.Contains(info, "昨天被处决的是") {
		t.Fatalf("送葬者应有消息, got %v", action)
	}
	if strings.Contains(info, "洗衣妇") {
		t.Fatalf("中毒送葬者应返回虚假角色名, got %q", info)
	}
}

// 用例 C：首夜信息位线索延迟发放 + 中毒厨师收到假线索
func TestPoisonedChefFakeClueDelayed(t *testing.T) {
	e := makePoisonGame(t)
	chef := e.GD.Players["4"]
	chef.Role = "chef"
	chef.RoleName = "厨师"
	chef.Poisoned = true
	chef.InfoClues = []string{"👨‍🍳 你得知有 2 对相邻的玩家是邪恶阵营"}
	action := e.DoAction("4", "chef", true)
	if len(action) != 0 {
		t.Fatalf("infoClueNotify 应返回空 action, got %v", action)
	}
	// 中毒：不应发放真实线索（InfoClues 中的 2 对），而是假线索
	// 通过 InfoClues 未被通知验证：这里直接验证 fakeClue 格式
	clue := e.fakeClue("chef")
	if !strings.HasPrefix(clue, "👨‍🍳 你得知有") {
		t.Fatalf("假线索格式错误: %q", clue)
	}
}

// 用例 D：投毒者中毒——毒不生效
func TestPoisonedPoisonerIneffective(t *testing.T) {
	e := makePoisonGame(t)
	psn := e.GD.Players["4"]
	psn.Role = "poisoner"
	psn.RoleName = "投毒者"
	psn.Poisoned = true
	// 让投毒者只能选 #3（占卜师）：其他候选排除
	for _, pid := range []string{"0", "1", "2"} {
		e.GD.Players[pid].Alive = false
	}
	e.DoAction("4", "poisoner", false)
	if e.GD.Players["2"].Poisoned {
		t.Fatal("中毒投毒者的毒不应生效")
	}
}

// 用例 E：恶魔免疫投毒
func TestImpImmuneToPoison(t *testing.T) {
	e := makePoisonGame(t)
	psn := e.GD.Players["4"]
	psn.Role = "poisoner"
	psn.RoleName = "投毒者"
	// 投毒者毒恶魔 #1：其他候选排除
	for _, pid := range []string{"1", "2", "3"} {
		e.GD.Players[pid].Alive = false
	}
	e.DoAction("4", "poisoner", false)
	if e.GD.Players["0"].Poisoned {
		t.Fatal("恶魔应免疫投毒")
	}
}

// 用例 F：首夜信息位线索不在开局发放（延迟到夜晚步骤），酒鬼线索照常开局发放
func TestFirstNightInfoClueDelayed(t *testing.T) {
	e := makePoisonGame(t)
	chef := e.GD.Players["4"]
	chef.Role = "chef"
	chef.RoleName = "厨师"
	chef.InfoClues = []string{"👨‍🍳 你得知有 1 对相邻的玩家是邪恶阵营"}
	e.GD.StorytellerMsgs = nil
	e.GenFirstNightInfo()
	for _, m := range e.GD.StorytellerMsgs {
		if m.Content == chef.InfoClues[0] {
			t.Fatal("首夜信息位线索不应在开局发放（延迟到夜晚步骤）")
		}
	}
	// 夜晚步骤发放线索（DoAction 内部 Notify）
	e.GD.StorytellerMsgs = nil
	e.DoAction("4", "chef", true)
	found := false
	for _, m := range e.GD.StorytellerMsgs {
		if m.Content == chef.InfoClues[0] {
			found = true
		}
	}
	if !found {
		t.Fatal("首夜线索应在夜晚 chef 步骤发放")
	}
	// 序列化不泄露中毒
	chef.Poisoned = true
	b, _ := json.Marshal(e.GD)
	if strings.Contains(string(b), "poisoned") {
		t.Fatal("序列化不应包含 poisoned")
	}
}
