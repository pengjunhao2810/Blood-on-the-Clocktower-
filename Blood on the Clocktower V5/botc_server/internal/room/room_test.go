package room

import (
	"testing"
	"time"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"

	"botc-server/internal/aiclient"
	"botc-server/internal/model"
	"botc-server/internal/ws"
)

func TestRoomStartGame(t *testing.T) {
	db, err := gorm.Open(sqlite.Open("file::memory:?cache=shared"), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	if err := model.AutoMigrate(db); err != nil {
		t.Fatal(err)
	}
	db.Create(&model.User{Username: "host"})

	hub := ws.NewHub()
	mgr := NewManager(hub, db, aiclient.New("http://127.0.0.1:1")) // 不存在的 AI 服务
	r := mgr.Create("TEST01", 1, "host")

	done := make(chan map[string]any, 1)
	r.Post(Event{Type: "add_ai", UserID: 1, Data: map[string]any{"ai_type": "local"}, Reply: nil})
	r.Post(Event{Type: "add_ai", UserID: 1, Data: map[string]any{"ai_type": "local"}, Reply: nil})
	r.Post(Event{Type: "add_ai", UserID: 1, Data: map[string]any{"ai_type": "local"}, Reply: nil})
	r.Post(Event{Type: "add_ai", UserID: 1, Data: map[string]any{"ai_type": "local"}, Reply: nil})

	r.Post(Event{
		Type: "start", UserID: 1, Data: map[string]any{},
		Reply: func(ok bool, msg string, data map[string]any) {
			done <- map[string]any{"ok": ok, "msg": msg}
		},
	})

	select {
	case res := <-done:
		if !res["ok"].(bool) {
			t.Fatalf("start failed: %v", res["msg"])
		}
		t.Logf("start ok")
	case <-time.After(5 * time.Second):
		t.Fatal("start timeout: 房间事件循环可能卡死")
	}

	if r.Status != "playing" || r.game == nil {
		t.Fatalf("room not playing after start: status=%s", r.Status)
	}
	t.Logf("game phase=%s players=%d", r.game.Phase, len(r.game.Players))

	// 推进夜晚
	r.Post(Event{Type: "next_phase", UserID: 1, Data: map[string]any{}, Reply: func(ok bool, msg string, d map[string]any) {}})
	time.Sleep(100 * time.Millisecond)
	t.Logf("after next_phase: phase=%s", r.game.Phase)
}
