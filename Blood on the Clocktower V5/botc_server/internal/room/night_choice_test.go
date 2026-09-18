package room

import (
	"testing"
	"time"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"

	"botc-server/internal/aiclient"
	"botc-server/internal/engine"
	"botc-server/internal/model"
	"botc-server/internal/ws"
)

func newNightChoiceRoom(t *testing.T) (*Room, *Manager) {
	db, err := gorm.Open(sqlite.Open("file:night_"+itoa(int(time.Now().UnixNano()))+"?mode=memory&cache=shared"), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	model.AutoMigrate(db)
	db.Create(&model.User{Username: "host"})
	hub := ws.NewHub()
	mgr := NewManager(hub, db, aiclient.New("http://127.0.0.1:1"))
	r := mgr.Create("NCH", 1, "host")
	for i := 0; i < 4; i++ {
		r.Post(Event{Type: "add_ai", UserID: 1, Data: map[string]any{"ai_type": "local"}})
	}
	done := make(chan struct{})
	r.Post(Event{Type: "start", UserID: 1, Data: map[string]any{}, Reply: func(ok bool, m string, d map[string]any) {
		close(done)
	}})
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("开局超时")
	}
	return r, mgr
}

func TestRoomNightChoiceTimeoutFallback(t *testing.T) {
	r, mgr := newNightChoiceRoom(t)
	defer mgr.Delete(r.Code)

	// 房主的真实匿名编号与 pid
	hostPID, hostNum := "", 0
	for pid, p := range r.game.Players {
		if p.UserID == 1 {
			hostPID = pid
			hostNum = p.Number
		}
	}
	// 手动注入已过期的挂起行动（占卜师）
	pa := &engine.NightPendingChoice{
		RoleKey: "fortune_teller", PlayerID: hostPID, Number: hostNum,
		StepIdx: 3, Total: 8, Deadline: time.Now().Add(-5 * time.Second).Unix(),
		ValidTargets: []int{2, 3, 4, 5},
	}
	r.game.PendingChoice = pa

	// 超时兜底：deadline 过期 → AI 自动代选 → 挂起清除、夜晚继续（防止对局卡死）
	r.checkPendingTimeout()
	if r.game.PendingChoice != nil {
		t.Fatal("超时后挂起应清除（AI 代选兜底）")
	}
	if r.game.NightIdx != pa.StepIdx+1 {
		t.Fatalf("超时后夜晚应推进, NightIdx=%d", r.game.NightIdx)
	}
}

func TestRoomNightChoiceNotExpired(t *testing.T) {
	r, mgr := newNightChoiceRoom(t)
	defer mgr.Delete(r.Code)

	pa := &engine.NightPendingChoice{
		RoleKey: "fortune_teller", PlayerID: "0", Number: 1,
		StepIdx: 3, Total: 8, Deadline: time.Now().Add(45 * time.Second).Unix(),
		ValidTargets: []int{2, 3, 4, 5},
	}
	r.game.PendingChoice = pa
	r.checkPendingTimeout()
	if r.game.PendingChoice == nil {
		t.Fatal("未过期不应触发兜底")
	}
}

func TestRoomNightChoiceSubmit(t *testing.T) {
	r, mgr := newNightChoiceRoom(t)
	defer mgr.Delete(r.Code)

	// 房主的真实匿名编号与 pid
	hostPID, hostNum := "", 0
	for pid, p := range r.game.Players {
		if p.UserID == 1 {
			hostPID = pid
			hostNum = p.Number
		}
	}
	pa := &engine.NightPendingChoice{
		RoleKey: "fortune_teller", PlayerID: hostPID, Number: hostNum,
		StepIdx: 3, Total: 8, Deadline: time.Now().Add(45 * time.Second).Unix(),
		ValidTargets: []int{2, 3, 4, 5},
	}
	r.game.PendingChoice = pa

	done := make(chan map[string]any, 1)
	r.Post(Event{
		Type: "submit_choice", UserID: 1, Data: map[string]any{"targets": []any{2.0, 4.0}},
		Reply: func(ok bool, msg string, d map[string]any) { done <- map[string]any{"ok": ok, "msg": msg} },
	})
	select {
	case res := <-done:
		if res["ok"] != true {
			t.Fatalf("提交失败: %v", res["msg"])
		}
	case <-time.After(3 * time.Second):
		t.Fatal("提交超时")
	}
	if r.game.PendingChoice != nil {
		t.Fatal("提交后挂起应清除")
	}
	if r.game.NightIdx != 4 {
		t.Fatalf("提交后 night_idx 应为 4, got %d", r.game.NightIdx)
	}
	// ActionLog 记录 manual
	if len(r.game.ActionLog) != 1 || r.game.ActionLog[0]["choice"] != engine.ChoiceManual {
		t.Fatalf("ActionLog 应记录 manual, got %v", r.game.ActionLog)
	}
	// 无效目标：不在合法列表内
	r.game.PendingChoice = &engine.NightPendingChoice{
		RoleKey: "fortune_teller", PlayerID: hostPID, Number: hostNum,
		StepIdx: 4, Total: 8, Deadline: time.Now().Add(45 * time.Second).Unix(),
		ValidTargets: []int{2, 3},
	}
	done2 := make(chan map[string]any, 1)
	r.Post(Event{
		Type: "submit_choice", UserID: 1, Data: map[string]any{"targets": []any{99.0, 100.0}},
		Reply: func(ok bool, msg string, d map[string]any) { done2 <- map[string]any{"ok": ok, "msg": msg} },
	})
	res := <-done2
	if res["ok"] == true {
		t.Fatal("非法目标应被拒绝")
	}
}
