package room

import (
	"testing"

	"botc-server/internal/engine"
)

// 单真人管家局：首夜推进到管家步骤应挂起等待真人选择
func TestButlerHumanPending(t *testing.T) {
	r, mgr := newNightChoiceRoom(t)
	defer mgr.Delete(r.Code)
	// 房主（真人）设为管家
	var pid string
	for k, p := range r.game.Players {
		if !p.IsAI {
			pid = k
			p.Role = "butler"
			p.RoleName = "管家"
		}
	}
	r.eng.HumanChoice = true
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
		t.Fatal("真人管家应挂起等待选择")
	}
	if pc.RoleKey != "butler" || pc.PlayerID != pid {
		t.Fatalf("挂起信息错误: role=%s pid=%s want butler/%s", pc.RoleKey, pc.PlayerID, pid)
	}
}
