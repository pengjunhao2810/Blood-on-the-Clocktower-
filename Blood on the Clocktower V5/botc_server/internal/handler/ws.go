package handler

import (
	"math/rand"
	"net/http"
	"sync"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"

	"botc-server/internal/model"
	"botc-server/internal/room"
	"botc-server/internal/ws"
)

func randIntn(n int) int { return rand.Intn(n) }

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	CheckOrigin:     func(r *http.Request) bool { return true },
}

// 好友服务单例（C 模块接线：延迟初始化，InviteStore 状态随进程存活）
var (
	friendOnce sync.Once
	friendSvc  *FriendService
)

func (h *Handler) getFriendSvc() *FriendService {
	friendOnce.Do(func() {
		friendSvc = NewFriendService(h.DB, h.Hub)
	})
	return friendSvc
}

// WSHandler WebSocket 升级入口：认证 → 注册到 Hub → 收发循环
func (h *Handler) WSHandler(c *gin.Context) {
	uid := CurrentUserID(c)
	if uid == 0 {
		c.JSON(http.StatusUnauthorized, gin.H{"success": false})
		return
	}
	conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		return
	}
	client := ws.NewClient(conn, uid)
	h.Hub.Register(client)

	defer func() {
		h.Hub.Unregister(client)
		var u model.User
		if err := h.DB.First(&u, uid).Error; err == nil {
			u.IsOnline = h.Hub.UserOnline(uid)
			h.DB.Save(&u)
		}
	}()

	var u model.User
	if err := h.DB.First(&u, uid).Error; err == nil {
		u.IsOnline = true
		h.DB.Save(&u)
	}

	go client.WritePump()
	client.ReadPump(h.onWSMessage)
}

// onWSMessage WS 指令入口，两层分流：
// 第 1 层：无房间上下文指令（heartbeat / friend.* / room.invite_*）
//
//	必须在房间定位之前处理（缺陷 #5 修复：这些指令不带 room_code）
//
// 第 2 层：房间/对局指令（原有逻辑，未改动）
func (h *Handler) onWSMessage(c *ws.Client, event string, data map[string]any, reqID uint64) {
	if data == nil {
		data = map[string]any{}
	}

	reply := func(ok bool, msg string, payload map[string]any) {
		out := map[string]any{"id": reqID, "ok": ok, "message": msg}
		if payload != nil {
			for k, v := range payload {
				out[k] = v
			}
		}
		h.Hub.SendToUser(c.UserID, "ack", out)
	}

	// —— 第 1 层：无房间上下文指令 ——
	switch event {
	case "heartbeat":
		reply(true, "", nil)
		return
	case "friend.search":
		h.onFriendSearch(c, data, reply)
		return
	case "friend.request":
		h.onFriendRequest(c, data, reply)
		return
	case "friend.accept":
		h.onFriendAccept(c, data, reply)
		return
	case "friend.reject":
		h.onFriendReject(c, data, reply)
		return
	case "friend.remove":
		h.onFriendRemove(c, data, reply)
		return
	case "friend.list":
		h.onFriendList(c, data, reply)
		return
	case "room.invite_friend":
		h.onInviteFriend(c, data, reply)
		return
	case "room.invite_accept":
		h.onInviteAccept(c, data, reply)
		return
	case "room.invite_reject":
		h.onInviteReject(c, data, reply)
		return
	}

	// —— 第 2 层：房间/对局指令（原有逻辑） ——
	code := ""
	if v, ok := data["room_code"].(string); ok {
		code = v
	}
	if code == "" {
		reply(false, "缺少 room_code", nil)
		return
	}

	if event == "room.join" {
		h.doRoomJoin(c, code, reply)
		return
	}

	r := h.Mgr.Get(code)
	if r == nil {
		reply(false, "房间不存在", nil)
		return
	}

	evType := ""
	switch event {
	case "room.chat":
		evType = "chat"
	case "room.ready":
		evType = "ready"
	case "room.add_ai":
		evType = "add_ai"
	case "room.remove_ai":
		evType = "remove_ai"
	case "room.set_seats":
		evType = "set_seats"
	case "room.start":
		evType = "start"
	case "room.leave":
		evType = "leave"
	case "game.chat":
		evType = "game_chat"
	case "game.next_phase":
		evType = "next_phase"
	case "game.nominate":
		evType = "nominate"
	case "game.vote":
		evType = "vote"
	case "game.end_nomination":
		evType = "end_nomination"
	case "game.private_chat":
		evType = "private_chat"
	case "game.private_invite":
		evType = "private_invite"
	case "game.private_accept":
		evType = "private_accept"
	case "game.private_decline":
		evType = "private_decline"
	case "game.skip_private":
		evType = "skip_private"
	case "game.end":
		evType = "end"
	case "game.my_info":
		evType = "my_info"
	case "game.submit_choice":
		evType = "submit_choice"
	case "game.tip_ack":
		evType = "tip_ack"
	case "room.kick":
		evType = "kick"
	case "room.fill_bots":
		evType = "fill_bots"
	default:
		reply(false, "未知指令", nil)
		return
	}

	r.Post(room.Event{
		Type: evType, UserID: c.UserID, Data: data,
		Reply: func(ok bool, msg string, payload map[string]any) { reply(ok, msg, payload) },
	})
}

// doRoomJoin 加入房间（room.join 与 room.invite_accept 共用）
func (h *Handler) doRoomJoin(c *ws.Client, code string, reply func(bool, string, map[string]any)) {
	r := h.Mgr.Get(code)
	if r == nil {
		reply(false, "房间不存在", nil)
		return
	}
	r.Post(room.Event{
		Type: "join", UserID: c.UserID, Data: map[string]any{"room_code": code},
		Reply: reply,
	})
}

func uintOf(d map[string]any, key string) uint {
	switch v := d[key].(type) {
	case float64:
		return uint(v)
	case int:
		return uint(v)
	case uint:
		return v
	case int64:
		return uint(v)
	}
	return 0
}

// ==============================
// 好友指令处理（C 模块）
// ==============================

func (h *Handler) onFriendSearch(c *ws.Client, data map[string]any, reply func(bool, string, map[string]any)) {
	username, _ := data["username"].(string)
	u, status, err := h.getFriendSvc().Search(c.UserID, username)
	if err != nil {
		reply(false, err.Error(), nil)
		return
	}
	reply(true, "", map[string]any{
		"user":              map[string]any{"id": u.ID, "username": u.Username},
		"friendship_status": status,
	})
}

func (h *Handler) onFriendRequest(c *ws.Client, data map[string]any, reply func(bool, string, map[string]any)) {
	fid := uintOf(data, "friend_id")
	if fid == 0 {
		reply(false, "参数错误", nil)
		return
	}
	if err := h.getFriendSvc().Request(c.UserID, fid); err != nil {
		reply(false, err.Error(), nil)
		return
	}
	reply(true, "", nil)
}

func (h *Handler) onFriendAccept(c *ws.Client, data map[string]any, reply func(bool, string, map[string]any)) {
	fid := uintOf(data, "friend_id")
	if err := h.getFriendSvc().Accept(c.UserID, fid); err != nil {
		reply(false, err.Error(), nil)
		return
	}
	reply(true, "", nil)
}

func (h *Handler) onFriendReject(c *ws.Client, data map[string]any, reply func(bool, string, map[string]any)) {
	fid := uintOf(data, "friend_id")
	if err := h.getFriendSvc().Reject(c.UserID, fid); err != nil {
		reply(false, err.Error(), nil)
		return
	}
	reply(true, "", nil)
}

func (h *Handler) onFriendRemove(c *ws.Client, data map[string]any, reply func(bool, string, map[string]any)) {
	fid := uintOf(data, "friend_id")
	if err := h.getFriendSvc().Remove(c.UserID, fid); err != nil {
		reply(false, err.Error(), nil)
		return
	}
	reply(true, "", nil)
}

func (h *Handler) onFriendList(c *ws.Client, data map[string]any, reply func(bool, string, map[string]any)) {
	list, err := h.getFriendSvc().List(c.UserID)
	if err != nil {
		reply(false, err.Error(), nil)
		return
	}
	reply(true, "", map[string]any{
		"friends":  list.Friends,
		"incoming": list.Incoming,
		"outgoing": list.Outgoing,
	})
}

// ==============================
// 房间邀请指令处理（C 模块，缺陷 #3 房主校验落地）
// ==============================

func (h *Handler) onInviteFriend(c *ws.Client, data map[string]any, reply func(bool, string, map[string]any)) {
	code, _ := data["room_code"].(string)
	fid := uintOf(data, "friend_id")
	if code == "" || fid == 0 {
		reply(false, "参数错误", nil)
		return
	}
	// 缺陷 #3：房主校验——仅房主可发送房间邀请
	var r model.Room
	if err := h.DB.Where("room_code = ?", code).First(&r).Error; err != nil {
		reply(false, "房间不存在", nil)
		return
	}
	if r.HostID != c.UserID {
		reply(false, "只有房主能邀请好友", nil)
		return
	}
	if err := h.getFriendSvc().InviteFriend(c.UserID, fid, code); err != nil {
		reply(false, err.Error(), nil)
		return
	}
	reply(true, "", nil)
}

func (h *Handler) onInviteAccept(c *ws.Client, data map[string]any, reply func(bool, string, map[string]any)) {
	code, _ := data["room_code"].(string)
	if code == "" {
		reply(false, "参数错误", nil)
		return
	}
	if _, err := h.getFriendSvc().AcceptInvite(c.UserID, code); err != nil {
		reply(false, err.Error(), nil)
		return
	}
	// 校验通过：复用现有 join 事件入座（座位分配/广播/DB 镜像全部走原逻辑）
	h.doRoomJoin(c, code, reply)
}

func (h *Handler) onInviteReject(c *ws.Client, data map[string]any, reply func(bool, string, map[string]any)) {
	code, _ := data["room_code"].(string)
	if code == "" {
		reply(false, "参数错误", nil)
		return
	}
	h.getFriendSvc().RejectInvite(c.UserID, code)
	reply(true, "", nil)
}
