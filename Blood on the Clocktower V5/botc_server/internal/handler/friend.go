package handler

import (
	"errors"
	"sync"
	"time"

	"gorm.io/gorm"

	"botc-server/internal/model"
	"botc-server/internal/ws"
)

// ============================================================================
// 好友系统 + 房间邀请（B 模块）
// 设计要点：
//   - 好友关系落库 friends 表（model.NewFriend 规范化存储，杜绝反向双插）
//   - 房间邀请为内存结构（好友必须在线才能收到，离线邀请无意义）
//   - 邀请接受时二次校验：邀请未过期 + 好友关系仍存在 + 房间仍在等待中
// ============================================================================

const inviteTTL = 5 * time.Minute

// Invite 房间邀请（内存，瞬时性数据不落库）
type Invite struct {
	FromUserID uint
	ToUserID   uint
	RoomCode   string
	At         time.Time
}

// InviteStore 邀请存储：mutex 保护 + TTL 过期懒删除 + 按房间批量清理
type InviteStore struct {
	mu     sync.Mutex
	ttl    time.Duration
	byUser map[uint][]*Invite // 被邀请者 → 邀请列表
}

func NewInviteStore(ttl time.Duration) *InviteStore {
	if ttl <= 0 {
		ttl = inviteTTL
	}
	return &InviteStore{ttl: ttl, byUser: make(map[uint][]*Invite)}
}

// Add 记录邀请：同 (被邀请者, 房间) 重复邀请幂等覆盖
func (s *InviteStore) Add(inv *Invite) {
	s.mu.Lock()
	defer s.mu.Unlock()
	list := s.byUser[inv.ToUserID]
	kept := list[:0]
	for _, x := range list {
		if x.RoomCode == inv.RoomCode {
			continue // 覆盖旧邀请
		}
		kept = append(kept, x)
	}
	inv.At = time.Now()
	s.byUser[inv.ToUserID] = append(kept, inv)
}

// Find 查找有效邀请（过期懒删除，找到即返回）
func (s *InviteStore) Find(toUID uint, roomCode string) (*Invite, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now()
	list := s.byUser[toUID]
	kept := list[:0]
	var found *Invite
	for _, x := range list {
		if now.Sub(x.At) > s.ttl {
			continue // 过期：懒删除（缺陷 #4）
		}
		kept = append(kept, x)
		if x.RoomCode == roomCode && found == nil {
			found = x
		}
	}
	s.byUser[toUID] = kept
	return found, found != nil
}

// Remove 删除指定邀请（接受/拒绝后调用）
func (s *InviteStore) Remove(toUID uint, roomCode string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	list := s.byUser[toUID]
	kept := list[:0]
	for _, x := range list {
		if x.RoomCode != roomCode {
			kept = append(kept, x)
		}
	}
	if len(kept) == 0 {
		delete(s.byUser, toUID)
	} else {
		s.byUser[toUID] = kept
	}
}

// DeleteByRoom 房间销毁后清理该房间全部邀请（缺陷 #4）
func (s *InviteStore) DeleteByRoom(roomCode string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for uid, list := range s.byUser {
		kept := list[:0]
		for _, x := range list {
			if x.RoomCode != roomCode {
				kept = append(kept, x)
			}
		}
		if len(kept) == 0 {
			delete(s.byUser, uid)
		} else {
			s.byUser[uid] = kept
		}
	}
}

// ============================================================================
// FriendService 好友业务服务
// ============================================================================

// FriendInfo 好友/申请者信息（含在线状态）
type FriendInfo struct {
	UserID   uint   `json:"user_id"`
	Username string `json:"username"`
	IsOnline bool   `json:"is_online"`
}

// FriendListResult 好友列表聚合：好友 / 待我处理的申请 / 我发出的申请
type FriendListResult struct {
	Friends  []FriendInfo `json:"friends"`
	Incoming []FriendInfo `json:"incoming"`
	Outgoing []FriendInfo `json:"outgoing"`
}

// FriendService 好友业务：申请/同意/拒绝/删除/列表 + 房间邀请
// 由 WS 指令层（C 模块）调用；本模块不触碰房间 Actor 与游戏引擎
type FriendService struct {
	DB      *gorm.DB
	Hub     *ws.Hub
	Invites *InviteStore
}

func NewFriendService(db *gorm.DB, hub *ws.Hub) *FriendService {
	return &FriendService{
		DB:      db,
		Hub:     hub,
		Invites: NewInviteStore(inviteTTL),
	}
}

// findPair 规范化查询好友关系（与 model.NewFriend 同一规范化规则）
func (s *FriendService) findPair(a, b uint) (*model.Friend, error) {
	var f model.Friend
	err := s.DB.Where("user_id = ? AND friend_id = ?", minUint(a, b), maxUint(a, b)).First(&f).Error
	if err != nil {
		return nil, err
	}
	return &f, nil
}

func minUint(a, b uint) uint {
	if a < b {
		return a
	}
	return b
}

func maxUint(a, b uint) uint {
	if a > b {
		return a
	}
	return b
}

func (s *FriendService) userInfo(uid uint) FriendInfo {
	info := FriendInfo{UserID: uid}
	var u model.User
	if s.DB.First(&u, uid).Error == nil {
		info.Username = u.Username
	}
	info.IsOnline = s.Hub.UserOnline(uid)
	return info
}

var (
	ErrAlreadyFriends   = errors.New("你们已经是好友")
	ErrAlreadyRequested = errors.New("已发送过申请，请等待对方处理")
	ErrNotFriends       = errors.New("对方不是你的好友")
	ErrNotYourRequest   = errors.New("只有接收方才能处理该申请")
	ErrUserNotFound     = errors.New("用户不存在")
	ErrSelfRequest      = errors.New("不能添加自己为好友")
)

// Search 按用户名精确查找用户（排除自己），返回好友关系状态
func (s *FriendService) Search(meID uint, username string) (*model.User, string, error) {
	var u model.User
	if err := s.DB.Where("username = ?", username).First(&u).Error; err != nil {
		return nil, "", ErrUserNotFound
	}
	if u.ID == meID {
		return nil, "", ErrSelfRequest
	}
	f, err := s.findPair(meID, u.ID)
	if err != nil {
		return &u, "none", nil
	}
	if f.Status == "accepted" {
		return &u, "accepted", nil
	}
	if f.InitiatorID == meID {
		return &u, "pending_out", nil
	}
	return &u, "pending_in", nil
}

// Request 发送好友申请：
//   - 无关系 → 创建 pending
//   - 对方已申请过我 → 直接成为好友（双向申请自动同意）
//   - 已是好友/已申请 → 返回对应错误
func (s *FriendService) Request(meID, targetID uint) error {
	if meID == targetID {
		return ErrSelfRequest
	}
	var target model.User
	if s.DB.First(&target, targetID).Error != nil {
		return ErrUserNotFound
	}
	if f, err := s.findPair(meID, targetID); err == nil {
		switch {
		case f.Status == "accepted":
			return ErrAlreadyFriends
		case f.InitiatorID == meID:
			return ErrAlreadyRequested
		default:
			// 对方已申请过我：双向申请 → 直接成为好友
			f.Status = "accepted"
			if err := s.DB.Save(f).Error; err != nil {
				return err
			}
			s.Hub.SendToUser(targetID, "friend.accepted", ginFriendInfo(s.userInfo(meID)))
			s.Hub.SendToUser(meID, "friend.accepted", ginFriendInfo(s.userInfo(targetID)))
			return nil
		}
	}

	// 新申请：规范化插入；并发窗口下唯一约束冲突则回查（重试一次）
	rec := model.NewFriend(meID, targetID, "pending")
	rec.InitiatorID = meID
	if err := s.DB.Create(rec).Error; err != nil {
		if f, e2 := s.findPair(meID, targetID); e2 == nil && f.InitiatorID != meID && f.Status == "pending" {
			f.Status = "accepted"
			if err := s.DB.Save(f).Error; err != nil {
				return err
			}
			s.Hub.SendToUser(targetID, "friend.accepted", ginFriendInfo(s.userInfo(meID)))
			s.Hub.SendToUser(meID, "friend.accepted", ginFriendInfo(s.userInfo(targetID)))
			return nil
		}
		if _, e2 := s.findPair(meID, targetID); e2 == nil {
			return ErrAlreadyRequested
		}
		return err
	}
	s.Hub.SendToUser(targetID, "friend.request", ginFriendInfo(s.userInfo(meID)))
	return nil
}

func ginFriendInfo(f FriendInfo) map[string]any {
	return map[string]any{
		"user_id": f.UserID, "username": f.Username, "is_online": f.IsOnline,
	}
}

// Accept 同意好友申请（仅接收方可处理）
func (s *FriendService) Accept(meID, targetID uint) error {
	f, err := s.findPair(meID, targetID)
	if err != nil {
		return ErrNotYourRequest
	}
	if f.Status != "pending" || f.InitiatorID == meID {
		return ErrNotYourRequest
	}
	f.Status = "accepted"
	if err := s.DB.Save(f).Error; err != nil {
		return err
	}
	s.Hub.SendToUser(targetID, "friend.accepted", ginFriendInfo(s.userInfo(meID)))
	s.Hub.SendToUser(meID, "friend.accepted", ginFriendInfo(s.userInfo(targetID)))
	return nil
}

// Reject 拒绝好友申请（仅接收方可处理）
func (s *FriendService) Reject(meID, targetID uint) error {
	f, err := s.findPair(meID, targetID)
	if err != nil {
		return ErrNotYourRequest
	}
	if f.Status != "pending" || f.InitiatorID == meID {
		return ErrNotYourRequest
	}
	return s.DB.Delete(f).Error
}

// Remove 删除好友（任意一方可发起）
func (s *FriendService) Remove(meID, targetID uint) error {
	f, err := s.findPair(meID, targetID)
	if err != nil {
		return ErrNotFriends
	}
	if f.Status != "accepted" {
		return ErrNotFriends
	}
	if err := s.DB.Delete(f).Error; err != nil {
		return err
	}
	s.Hub.SendToUser(targetID, "friend.removed", ginFriendInfo(s.userInfo(meID)))
	s.Hub.SendToUser(meID, "friend.removed", ginFriendInfo(s.userInfo(targetID)))
	return nil
}

// List 好友列表 + 待处理申请（双向查询：user_id=me OR friend_id=me）
func (s *FriendService) List(meID uint) (*FriendListResult, error) {
	var recs []model.Friend
	if err := s.DB.Where("(user_id = ? OR friend_id = ?)", meID, meID).Find(&recs).Error; err != nil {
		return nil, err
	}
	out := &FriendListResult{Friends: []FriendInfo{}, Incoming: []FriendInfo{}, Outgoing: []FriendInfo{}}
	for i := range recs {
		f := &recs[i]
		other := f.OtherOf(meID)
		if f.Status == "accepted" {
			out.Friends = append(out.Friends, s.userInfo(other))
		} else if f.InitiatorID == meID {
			out.Outgoing = append(out.Outgoing, s.userInfo(other))
		} else {
			out.Incoming = append(out.Incoming, s.userInfo(other))
		}
	}
	return out, nil
}

// ============================================================================
// 房间邀请
// ============================================================================

var (
	ErrRoomGone      = errors.New("房间不存在或已解散")
	ErrRoomStarted   = errors.New("游戏已开始，无法邀请")
	ErrFriendOffline = errors.New("对方不在线，无法收到邀请")
)

// InviteFriend 房主邀请好友入房：
// 校验 ①好友关系 ②对方在线 ③房间 waiting
// TODO(#3): 房主校验——C 模块 WS 指令层补上"请求者必须是 host_id"校验后再调用本方法
func (s *FriendService) InviteFriend(fromUID, toUID uint, roomCode string) error {
	f, err := s.findPair(fromUID, toUID)
	if err != nil || f.Status != "accepted" {
		return ErrNotFriends
	}
	if !s.Hub.UserOnline(toUID) {
		return ErrFriendOffline
	}
	var room model.Room
	if err := s.DB.Where("room_code = ?", roomCode).First(&room).Error; err != nil {
		return ErrRoomGone
	}
	if room.Status != "waiting" {
		return ErrRoomStarted
	}
	s.Invites.Add(&Invite{FromUserID: fromUID, ToUserID: toUID, RoomCode: roomCode})
	s.Hub.SendToUser(toUID, "room.invite", map[string]any{
		"room_code": roomCode,
		"from":      ginFriendInfo(s.userInfo(fromUID)),
	})
	return nil
}

// AcceptInvite 接受邀请：校验邀请未过期 + 好友关系仍在 + 房间仍在等待
// 返回邀请信息（C 模块据此投递房间 join 事件）
// 两类失败处理：
//   - 致命失败（过期/好友删除/房间销毁）→ 删除邀请记录
//   - 可重试失败（已在其他房间）→ 保留邀请，用户离开后可重新接受
func (s *FriendService) AcceptInvite(toUID uint, roomCode string) (*Invite, error) {
	inv, ok := s.Invites.Find(toUID, roomCode)
	if !ok {
		return nil, errors.New("邀请已过期或不存在")
	}
	// 缺陷 #2：已在其他房间 → 可重试，不删除邀请
	var occupied int64
	s.DB.Model(&model.RoomSeat{}).
		Joins("JOIN rooms ON rooms.id = room_seats.room_id").
		Where("room_seats.user_id = ? AND rooms.room_code != ?", toUID, roomCode).
		Count(&occupied)
	if occupied > 0 {
		return nil, errors.New("你已在其他房间中，请先离开")
	}
	fail := func(err error) (*Invite, error) {
		s.Invites.Remove(toUID, roomCode) // 缺陷 #4：致命失败即清理，不残留
		return nil, err
	}
	if f, err := s.findPair(inv.FromUserID, toUID); err != nil || f.Status != "accepted" {
		return fail(ErrNotFriends)
	}
	var room model.Room
	if err := s.DB.Where("room_code = ?", roomCode).First(&room).Error; err != nil {
		return fail(ErrRoomGone)
	}
	if room.Status != "waiting" {
		return fail(ErrRoomStarted)
	}
	s.Invites.Remove(toUID, roomCode)
	return inv, nil
}

// RejectInvite 拒绝邀请
func (s *FriendService) RejectInvite(toUID uint, roomCode string) {
	s.Invites.Remove(toUID, roomCode)
}

// CleanupInvitesByRoom 房间销毁时清理邀请（缺陷 #4，房间解散处调用）
func (s *FriendService) CleanupInvitesByRoom(roomCode string) {
	s.Invites.DeleteByRoom(roomCode)
}
