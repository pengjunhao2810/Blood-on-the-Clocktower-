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

// 空置清理：全员离线标记 abandonedAt；3 分钟后复位为等待房间
func TestRoomAbandonedReset(t *testing.T) {
	r, mgr := newNightChoiceRoom(t)
	defer mgr.Delete(r.Code)

	// 模拟全员离线
	r.abandonedAt = time.Now()
	// 未到 3 分钟：不复位
	r.checkAbandoned()
	if r.Status != "playing" {
		t.Fatal("宽限期内不应复位")
	}
	// 超过 3 分钟：复位
	r.abandonedAt = time.Now().Add(-4 * time.Minute)
	r.checkAbandoned()
	if r.Status != "waiting" {
		t.Fatalf("空置超时应复位, status=%s", r.Status)
	}
	if r.game != nil || r.eng != nil {
		t.Fatal("复位后游戏状态应清空")
	}
}

// 真人回归：取消空置计时
func TestRoomJoinCancelsAbandon(t *testing.T) {
	r, mgr := newNightChoiceRoom(t)
	defer mgr.Delete(r.Code)

	r.abandonedAt = time.Now().Add(-4 * time.Minute)
	// 房主回归（模拟 join 事件路径：seatOf 存在 → 清除计时）
	done := make(chan struct{})
	r.Post(Event{Type: "join", UserID: 1, Data: map[string]any{},
		Reply: func(ok bool, msg string, d map[string]any) { close(done) }})
	<-done
	if !r.abandonedAt.IsZero() {
		t.Fatal("真人回归应取消空置计时")
	}
	r.checkAbandoned()
	if r.Status != "playing" {
		t.Fatal("有真人回归的对局不应被复位")
	}
}

// 等待房间空置：立即销毁
func TestWaitingRoomEmptyDisband(t *testing.T) {
	db, err := gorm.Open(sqlite.Open("file:wd_"+itoa(int(time.Now().UnixNano()))+"?mode=memory&cache=shared"), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	model.AutoMigrate(db)
	db.Create(&model.User{Username: "host"})
	hub := ws.NewHub()
	mgr := NewManager(hub, db, aiclient.New("http://127.0.0.1:1"))
	r := mgr.Create("WDR", 1, "host")
	if _, ok := mgr.rooms["WDR"]; !ok {
		t.Fatal("房间应存在")
	}
	// 房主离开（等待房间、无其他真人）→ 解散
	done := make(chan struct{})
	r.Post(Event{Type: "leave", UserID: 1, Data: map[string]any{},
		Reply: func(ok bool, msg string, d map[string]any) { close(done) }})
	<-done
	if _, ok := mgr.rooms["WDR"]; ok {
		t.Fatal("空置等待房间应被销毁")
	}
}
