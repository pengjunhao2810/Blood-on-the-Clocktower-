package model

import (
	"errors"
	"strconv"
	"testing"
	"time"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func newTestDB(t *testing.T) *gorm.DB {
	dsn := "file:model_" + strconv.FormatInt(time.Now().UnixNano(), 10) + "?mode=memory&cache=shared"
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	if err := AutoMigrate(db); err != nil {
		t.Fatal(err)
	}
	return db
}

func TestFriendNormalize(t *testing.T) {
	f := NewFriend(5, 3, "pending")
	if f.UserID != 3 || f.FriendID != 5 {
		t.Fatalf("规范化失败: 期望 (3,5)，实际 (%d,%d)", f.UserID, f.FriendID)
	}
	f2 := NewFriend(2, 9, "pending")
	if f2.UserID != 2 || f2.FriendID != 9 {
		t.Fatalf("规范化失败: 期望 (2,9)，实际 (%d,%d)", f2.UserID, f2.FriendID)
	}
	f3 := NewFriend(7, 7, "pending")
	if f3.UserID != 7 || f3.FriendID != 7 {
		t.Fatalf("相同 ID 不应被改写")
	}
}

func TestFriendOtherOf(t *testing.T) {
	f := NewFriend(3, 5, "accepted")
	if f.OtherOf(3) != 5 || f.OtherOf(5) != 3 {
		t.Fatalf("OtherOf 双向取对方失败")
	}
}

func TestFriendUniquePair(t *testing.T) {
	db := newTestDB(t)

	// 正向插入
	f1 := NewFriend(1, 2, "pending")
	f1.InitiatorID = 1
	if err := db.Create(f1).Error; err != nil {
		t.Fatalf("正向插入失败: %v", err)
	}

	// 反向插入同一对：规范化后 (1,2) 与 (2,1) 等价，必须触发唯一约束
	f2 := NewFriend(2, 1, "pending")
	f2.InitiatorID = 2
	err := db.Create(f2).Error
	if err == nil {
		t.Fatalf("反向重复插入应触发唯一约束，但没有报错")
	}
	if !errors.Is(err, gorm.ErrDuplicatedKey) && !isUniqueViolation(err) {
		t.Fatalf("错误类型应为唯一约束冲突: %v", err)
	}

	// 表中只有一条记录
	var cnt int64
	db.Model(&Friend{}).Count(&cnt)
	if cnt != 1 {
		t.Fatalf("表中应有 1 条记录，实际 %d", cnt)
	}
}

func TestFriendPendingAndAccepted(t *testing.T) {
	db := newTestDB(t)

	// 模拟完整生命周期：申请 → 同意
	f := NewFriend(1, 2, "pending")
	f.InitiatorID = 1
	db.Create(f)

	var got Friend
	if err := db.Where("user_id = ? AND friend_id = ?", 1, 2).First(&got).Error; err != nil {
		t.Fatalf("pending 记录查询失败: %v", err)
	}
	if got.InitiatorID != 1 || got.Status != "pending" {
		t.Fatalf("申请方向信息错误: initiator=%d status=%s", got.InitiatorID, got.Status)
	}

	// 同意：status → accepted
	db.Model(&got).Update("status", "accepted")
	if err := db.Where("status = ? AND (user_id = ? OR friend_id = ?)", "accepted", 2, 2).First(&Friend{}).Error; err != nil {
		t.Fatalf("双向查询好友失败: %v", err)
	}
}

func isUniqueViolation(err error) bool {
	if err == nil {
		return false
	}
	// SQLite 唯一约束错误文本
	return errors.Is(err, gorm.ErrDuplicatedKey) ||
		containsString(err.Error(), "UNIQUE constraint failed")
}

func containsString(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
