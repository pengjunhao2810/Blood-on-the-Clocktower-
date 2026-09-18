package handler

import (
	"testing"
	"time"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"

	"botc-server/internal/model"
	"botc-server/internal/ws"
)

func newFriendTest(t *testing.T) (*FriendService, *gorm.DB) {
	dsn := "file:friend_" + itoaI(int(time.Now().UnixNano())) + "?mode=memory&cache=shared"
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	if err := model.AutoMigrate(db); err != nil {
		t.Fatal(err)
	}
	for i := 1; i <= 5; i++ {
		db.Create(&model.User{Username: "u" + itoaI(i)})
	}
	return NewFriendService(db, ws.NewHub()), db
}

func itoaI(n int) string {
	if n == 0 {
		return "0"
	}
	var buf [20]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	return string(buf[i:])
}

// ==============================
// InviteStore 单元测试
// ==============================

func TestInviteStoreBasic(t *testing.T) {
	s := NewInviteStore(time.Minute)
	s.Add(&Invite{FromUserID: 1, ToUserID: 2, RoomCode: "AAA111"})

	if inv, ok := s.Find(2, "AAA111"); !ok || inv.FromUserID != 1 {
		t.Fatalf("邀请查找失败")
	}
	if _, ok := s.Find(2, "BBB222"); ok {
		t.Fatalf("不存在的邀请不应命中")
	}
	// 幂等覆盖：同 (to, room) 重复添加应只剩一条
	s.Add(&Invite{FromUserID: 1, ToUserID: 2, RoomCode: "AAA111"})
	if _, ok := s.Find(2, "AAA111"); !ok {
		t.Fatalf("覆盖后邀请仍应存在")
	}
	s.Remove(2, "AAA111")
	if _, ok := s.Find(2, "AAA111"); ok {
		t.Fatalf("删除后邀请不应存在")
	}
}

func TestInviteStoreExpire(t *testing.T) {
	s := NewInviteStore(40 * time.Millisecond)
	s.Add(&Invite{FromUserID: 1, ToUserID: 2, RoomCode: "AAA111"})
	time.Sleep(70 * time.Millisecond)
	if _, ok := s.Find(2, "AAA111"); ok {
		t.Fatalf("过期邀请应被懒删除")
	}
}

func TestInviteStoreDeleteByRoom(t *testing.T) {
	s := NewInviteStore(time.Minute)
	s.Add(&Invite{FromUserID: 1, ToUserID: 2, RoomCode: "AAA111"})
	s.Add(&Invite{FromUserID: 1, ToUserID: 3, RoomCode: "AAA111"})
	s.Add(&Invite{FromUserID: 1, ToUserID: 4, RoomCode: "ZZZ999"})
	s.DeleteByRoom("AAA111")
	if _, ok := s.Find(2, "AAA111"); ok {
		t.Fatalf("房间销毁后邀请应被清理")
	}
	if _, ok := s.Find(4, "ZZZ999"); !ok {
		t.Fatalf("其他房间邀请不应被误删")
	}
}

func TestInviteStoreConcurrent(t *testing.T) {
	// 并发读写验证 mutex 保护（-race 模式下运行）
	s := NewInviteStore(time.Minute)
	done := make(chan struct{})
	for i := 0; i < 4; i++ {
		go func(n int) {
			defer func() { done <- struct{}{} }()
			for j := 0; j < 200; j++ {
				s.Add(&Invite{FromUserID: uint(n + 1), ToUserID: 9, RoomCode: "R" + itoaI(j%10)})
				s.Find(9, "R"+itoaI(j%10))
				s.Remove(9, "R"+itoaI(j%10))
				s.DeleteByRoom("R" + itoaI(j%10))
			}
		}(i)
	}
	for i := 0; i < 4; i++ {
		<-done
	}
}

// ==============================
// FriendService 好友业务测试
// ==============================

func TestFriendRequestFlow(t *testing.T) {
	s, _ := newFriendTest(t)

	// 1 → 2 申请
	if err := s.Request(1, 2); err != nil {
		t.Fatalf("申请失败: %v", err)
	}
	// 重复申请
	if err := s.Request(1, 2); err != ErrAlreadyRequested {
		t.Fatalf("重复申请应报 ErrAlreadyRequested，实际 %v", err)
	}
	// 2 的列表：incoming 含 1
	list, _ := s.List(2)
	if len(list.Incoming) != 1 || list.Incoming[0].UserID != 1 {
		t.Fatalf("incoming 列表错误: %+v", list.Incoming)
	}
	// 1 的列表：outgoing 含 2
	list, _ = s.List(1)
	if len(list.Outgoing) != 1 || list.Outgoing[0].UserID != 2 {
		t.Fatalf("outgoing 列表错误: %+v", list.Outgoing)
	}
	// 2 同意
	if err := s.Accept(2, 1); err != nil {
		t.Fatalf("同意失败: %v", err)
	}
	list, _ = s.List(1)
	if len(list.Friends) != 1 || list.Friends[0].UserID != 2 {
		t.Fatalf("好友列表错误: %+v", list.Friends)
	}
	// 已是好友再申请
	if err := s.Request(2, 1); err != ErrAlreadyFriends {
		t.Fatalf("已是好友应报 ErrAlreadyFriends，实际 %v", err)
	}
}

func TestFriendBidirectionalRequest(t *testing.T) {
	s, _ := newFriendTest(t)
	// 1 申请 2；2 反向申请 1 → 自动成为好友（缺陷 #1 修复后的预期行为）
	if err := s.Request(1, 2); err != nil {
		t.Fatal(err)
	}
	if err := s.Request(2, 1); err != nil {
		t.Fatalf("反向申请应自动成为好友: %v", err)
	}
	list, _ := s.List(1)
	if len(list.Friends) != 1 {
		t.Fatalf("双向申请后应成为好友")
	}
}

func TestFriendRejectAndRemove(t *testing.T) {
	s, _ := newFriendTest(t)
	s.Request(1, 2)
	if err := s.Reject(2, 1); err != nil {
		t.Fatalf("拒绝失败: %v", err)
	}
	list, _ := s.List(1)
	if len(list.Outgoing)+len(list.Incoming) != 0 {
		t.Fatalf("拒绝后申请记录应清除")
	}
	// 非接收方处理
	s.Request(1, 2)
	if err := s.Accept(1, 2); err != ErrNotYourRequest {
		t.Fatalf("发起方不能同意自己的申请")
	}
	s.Accept(2, 1)
	// 删除好友
	if err := s.Remove(1, 2); err != nil {
		t.Fatalf("删除失败: %v", err)
	}
	list, _ = s.List(2)
	if len(list.Friends) != 0 {
		t.Fatalf("删除后好友列表应为空")
	}
	// 删除后再删 → ErrNotFriends
	if err := s.Remove(1, 2); err != ErrNotFriends {
		t.Fatalf("重复删除应报 ErrNotFriends")
	}
}

func TestFriendSearch(t *testing.T) {
	s, _ := newFriendTest(t)
	u, status, err := s.Search(1, "u3")
	if err != nil || u.ID != 3 || status != "none" {
		t.Fatalf("搜索失败: %v %s", err, status)
	}
	if _, _, err := s.Search(1, "nobody"); err != ErrUserNotFound {
		t.Fatalf("不存在用户应报 ErrUserNotFound")
	}
	if _, _, err := s.Search(1, "u1"); err != ErrSelfRequest {
		t.Fatalf("搜索自己应报 ErrSelfRequest")
	}
	s.Request(1, 3)
	if _, status, _ := s.Search(1, "u3"); status != "pending_out" {
		t.Fatalf("状态应为 pending_out，实际 %s", status)
	}
	if _, status, _ := s.Search(3, "u1"); status != "pending_in" {
		t.Fatalf("状态应为 pending_in，实际 %s", status)
	}
}

func TestInviteFriendAndAccept(t *testing.T) {
	s, db := newFriendTest(t)
	// 建好友关系 + 房间
	s.Request(1, 2)
	s.Accept(2, 1)
	room := model.Room{RoomCode: "TEST01", HostID: 1, Status: "waiting", MaxPlayers: 8}
	db.Create(&room)

	// 非好友邀请
	if err := s.InviteFriend(1, 3, "TEST01"); err != ErrNotFriends {
		t.Fatalf("非好友邀请应被拒")
	}
	// 离线好友邀请（hub 无连接 → 离线）
	if err := s.InviteFriend(1, 2, "TEST01"); err != ErrFriendOffline {
		t.Fatalf("离线邀请应报 ErrFriendOffline，实际 %v", err)
	}
	// 模拟好友上线（注册假连接）—— 用真实 Hub 注册一个客户端
	hub := ws.NewHub()
	s.Hub = hub
	c := ws.NewClient(nil, 2)
	hub.Register(c)
	defer hub.Unregister(c)
	if err := s.InviteFriend(1, 2, "TEST01"); err != nil {
		t.Fatalf("在线邀请失败: %v", err)
	}
	// 接受：好友关系仍在 + 房间 waiting → 成功
	if inv, err := s.AcceptInvite(2, "TEST01"); err != nil || inv.FromUserID != 1 {
		t.Fatalf("接受邀请失败: %v", err)
	}
	// 二次接受：邀请已删除
	if _, err := s.AcceptInvite(2, "TEST01"); err == nil {
		t.Fatalf("重复接受应失败")
	}
}

func TestInviteEdgeCases(t *testing.T) {
	s, db := newFriendTest(t)
	s.Request(1, 2)
	s.Accept(2, 1)
	hub := ws.NewHub()
	s.Hub = hub
	c := ws.NewClient(nil, 2)
	hub.Register(c)
	defer hub.Unregister(c)

	// 房间已开局 → 邀请被拒
	room := model.Room{RoomCode: "PLAY01", HostID: 1, Status: "playing", MaxPlayers: 8}
	db.Create(&room)
	if err := s.InviteFriend(1, 2, "PLAY01"); err != ErrRoomStarted {
		t.Fatalf("开局后邀请应被拒，实际 %v", err)
	}

	// 邀请后房间被销毁 → 接受失败且记录被清理
	room2 := model.Room{RoomCode: "WAIT01", HostID: 1, Status: "waiting", MaxPlayers: 8}
	db.Create(&room2)
	s.InviteFriend(1, 2, "WAIT01")
	db.Delete(&room2) // 模拟房间解散
	if _, err := s.AcceptInvite(2, "WAIT01"); err != ErrRoomGone {
		t.Fatalf("房间解散后接受应报 ErrRoomGone，实际 %v", err)
	}
	// 失败后记录已清理（再次接受报"过期或不存在"而非 ErrRoomGone）
	if _, err := s.AcceptInvite(2, "WAIT01"); err == nil {
		t.Fatalf("清理后不应再有邀请")
	}

	// 删除好友后接受邀请 → 失效
	room3 := model.Room{RoomCode: "WAIT02", HostID: 1, Status: "waiting", MaxPlayers: 8}
	db.Create(&room3)
	s.InviteFriend(1, 2, "WAIT02")
	s.Remove(1, 2)
	if _, err := s.AcceptInvite(2, "WAIT02"); err != ErrNotFriends {
		t.Fatalf("删除好友后接受应报 ErrNotFriends，实际 %v", err)
	}

	// 房间解散清理：CleanupInvitesByRoom
	room4 := model.Room{RoomCode: "WAIT03", HostID: 1, Status: "waiting", MaxPlayers: 8}
	db.Create(&room4)
	s.Request(1, 2)
	s.Accept(2, 1)
	s.InviteFriend(1, 2, "WAIT03")
	s.CleanupInvitesByRoom("WAIT03")
	if _, err := s.AcceptInvite(2, "WAIT03"); err == nil {
		t.Fatalf("DeleteByRoom 后邀请不应存在")
	}
}
