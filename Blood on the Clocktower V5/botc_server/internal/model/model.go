package model

import (
	"time"

	"gorm.io/gorm"
)

// User 用户账号（持久层）
type User struct {
	ID           uint      `gorm:"primaryKey" json:"id"`
	Username     string    `gorm:"size:50;uniqueIndex;not null" json:"username"`
	PasswordHash string    `gorm:"size:200;not null" json:"-"`
	CreatedAt    time.Time `json:"created_at"`
	IsOnline     bool      `json:"is_online"`
	LastActive   time.Time `json:"last_active"`
}

// Room 房间记录（持久层：房间元信息与座位，用于断线恢复）
// 运行时状态（聊天/对局）在内存，由房间 Actor 管理；
// 对局状态定期落盘到 GameData 字段，服务重启后可恢复进行中的对局
type Room struct {
	ID         uint       `gorm:"primaryKey" json:"id"`
	RoomCode   string     `gorm:"size:10;uniqueIndex;not null" json:"room_code"`
	HostID     uint       `gorm:"not null" json:"host_id"`
	Status     string     `gorm:"size:20;default:waiting" json:"status"` // waiting/playing/ended
	MaxPlayers int        `gorm:"default:8" json:"max_players"`
	CreatedAt  time.Time  `json:"created_at"`
	GameData   string     `gorm:"type:text" json:"-"` // 对局快照 JSON（重启恢复）
	Host       User       `gorm:"foreignKey:HostID" json:"-"`
	Seats      []RoomSeat `gorm:"foreignKey:RoomID" json:"-"`
}

// RoomSeat 房间座位（持久层：真人/AI 占位，断线恢复用）
type RoomSeat struct {
	ID         uint      `gorm:"primaryKey" json:"id"`
	RoomID     uint      `gorm:"not null;index" json:"room_id"`
	UserID     *uint     `gorm:"index" json:"user_id"` // nil = AI
	SeatNumber int       `gorm:"not null" json:"seat_number"`
	IsAI       bool      `json:"is_ai"`
	AIType     string    `gorm:"size:20;default:local" json:"ai_type"`
	JoinedAt   time.Time `json:"joined_at"`
	User       *User     `gorm:"foreignKey:UserID" json:"-"`
}

// Friend 好友关系（持久层）
// 存储不变式：UserID/FriendID 按 ID 升序规范化（小 ID 在前），
// 配合组合唯一索引，从存储层杜绝 (A,B)/(B,A) 反向双插。
// 申请方向由 InitiatorID 表达（pending 时有意义：谁发起的申请）。
type Friend struct {
	ID          uint      `gorm:"primaryKey" json:"id"`
	UserID      uint      `gorm:"not null;uniqueIndex:idx_friend_pair" json:"user_id"`   // 规范化：小 ID
	FriendID    uint      `gorm:"not null;uniqueIndex:idx_friend_pair" json:"friend_id"` // 规范化：大 ID
	InitiatorID uint      `gorm:"not null" json:"initiator_id"`                          // 申请发起方
	Status      string    `gorm:"size:20;default:pending" json:"status"`                 // pending/accepted
	CreatedAt   time.Time `json:"created_at"`
}

// NewFriend 创建好友关系记录：自动按 ID 升序规范化存储
func NewFriend(a, b uint, status string) *Friend {
	if a > b {
		a, b = b, a
	}
	return &Friend{UserID: a, FriendID: b, InitiatorID: 0, Status: status}
}

// OtherOf 返回相对于 uid 的另一方用户 ID
func (f *Friend) OtherOf(uid uint) uint {
	if f.UserID == uid {
		return f.FriendID
	}
	return f.UserID
}

// GameLog 对局日志（对局结束后整体落盘，支持历史记录/回放）
type GameLog struct {
	ID          uint      `gorm:"primaryKey" json:"id"`
	RoomCode    string    `gorm:"size:10;index;not null" json:"room_code"`
	StartedAt   time.Time `json:"started_at"`
	EndedAt     time.Time `json:"ended_at"`
	Winner      string    `gorm:"size:10" json:"winner"` // good/evil
	Day         int       `json:"day"`
	UserIDs     string    `gorm:"size:500" json:"-"` // 参与玩家 uid 列表（,1,2, 格式，战绩统计用）
	Players     string    `json:"-"`                 // 终局玩家状态 JSON
	Messages    string    `json:"-"`                 // 公聊消息 JSON
	Stories     string    `json:"-"`                 // 说书人信息 JSON
	Actions     string    `json:"-"`                 // 夜晚选择方式日志 JSON（manual/timeout/ai）
	PrivateMsgs string    `json:"-"`                 // 私聊日志 JSON（仅归档，不对玩家广播）
}

// AutoMigrate 建表
func AutoMigrate(db *gorm.DB) error {
	return db.AutoMigrate(&User{}, &Room{}, &RoomSeat{}, &GameLog{}, &Friend{})
}
