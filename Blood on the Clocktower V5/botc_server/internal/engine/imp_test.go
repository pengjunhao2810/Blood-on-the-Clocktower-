package engine

import "testing"

// 构造小恶魔 AI 局：0 号小恶魔，其余普通镇民
func makeImpGame() (*Engine, *GameData) {
	gd := &GameData{Players: map[string]*PlayerState{}}
	for i := 0; i < 6; i++ {
		gd.Players[itoa(i)] = &PlayerState{
			UserID: uint(i + 1), Username: "p" + itoa(i), Number: i + 1,
			Seat: i, IsAI: true, AIType: "local", Alive: true,
			Role: "washerwoman", Team: TeamTownsfolk, RoleName: "洗衣妇",
			FlagEvil: i == 0, FlagGood: i != 0,
		}
	}
	p0 := gd.Players["0"]
	p0.Role = "imp"
	p0.RoleName = "小恶魔"
	p0.Team = TeamDemon
	gd.Phase = "night"
	gd.FirstNight = true
	gd.NightIdx = 0
	return NewEngine(gd, "TESTIMP", func(string, any) {}), gd
}

func TestImpNoKillFirstNight(t *testing.T) {
	e, gd := makeImpGame()
	// 推进完整首夜（首夜顺序 13 步 + 1 步到 day）
	for i := 0; i < len(NightOrderFirst)+1; i++ {
		e.AdvancePhase()
	}
	if gd.Phase != "day" {
		t.Fatalf("首夜后应为 day, got %s", gd.Phase)
	}
	// 首夜禁刀：无任何人死亡
	for _, p := range gd.Players {
		if !p.Alive {
			t.Fatalf("首夜恶魔不应杀人，玩家 #%d 死亡", p.Number)
		}
	}

	// 第二夜：小恶魔应正常杀人
	e.AdvancePhase() // day → public_chat
	e.AdvancePhase() // → private_chat
	e.AdvancePhase() // → nomination
	res := e.AdvancePhase()
	if res["phase"] != "night" {
		t.Fatalf("应进入第二夜, got %v", res["phase"])
	}
	if gd.FirstNight {
		t.Fatal("第二夜 first_night 应为 false")
	}
	// 推进第二夜：poisoner(无) → monk(无) → spy(无) → scarlet(无) → imp(杀人，第5步)
	e.AdvancePhase() // step 1
	e.AdvancePhase() // step 2
	e.AdvancePhase() // step 3
	e.AdvancePhase() // step 4
	e.AdvancePhase() // step 5 imp 行动
	died := 0
	for _, p := range gd.Players {
		if !p.Alive {
			died++
		}
	}
	if died == 0 {
		t.Fatal("第二夜恶魔应正常杀人")
	}
	// 士兵不会死：若被杀者含士兵则不成立，但本局无士兵
	t.Logf("第二夜死亡 %d 人 ✓", died)
}
