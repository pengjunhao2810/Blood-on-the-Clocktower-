package ws

import (
	"encoding/json"
	"sync"
	"time"
)

// Event 服务器推送消息格式
type Event struct {
	Event string `json:"event"`
	Data  any    `json:"data"`
}

// presenceState 用户在线状态通知状态（防抖用）
type presenceState struct {
	lastNotify   time.Time   // 最近一次在线状态广播时间
	lastStatus   bool        // 最近一次广播的状态（true=online）
	offlineTimer *time.Timer // offline 延迟推送定时器（重连期内取消）
}

// Hub 管理所有 WebSocket 连接：房间广播 + 用户定向推送 + 在线状态回调
type Hub struct {
	mu    sync.RWMutex
	rooms map[string]map[*Client]struct{} // room_code -> 客户端集合
	users map[uint]*Client                // user_id -> 当前在线连接

	// 上下线回调（由上层注入，Hub 保持对 DB 无依赖）
	OnUserOnline  func(uid uint)
	OnUserOffline func(uid uint)

	// 在线状态广播防抖（默认 5 秒，避免重连抖动刷屏）
	PresenceDebounce time.Duration

	pmu      sync.Mutex
	presence map[uint]*presenceState
}

func NewHub() *Hub {
	return &Hub{
		rooms:            make(map[string]map[*Client]struct{}),
		users:            make(map[uint]*Client),
		PresenceDebounce: 5 * time.Second,
		presence:         make(map[uint]*presenceState),
	}
}

// Register 客户端认证后注册（跨设备登录踢旧连接）
func (h *Hub) Register(c *Client) {
	h.mu.Lock()
	if old, ok := h.users[c.UserID]; ok && old != c {
		old.Close() // 踢旧连接：其 Unregister 因 cur != c 不触发 offline
	}
	h.users[c.UserID] = c
	h.mu.Unlock()

	h.notifyOnline(c.UserID)
}

// Unregister 移除客户端
func (h *Hub) Unregister(c *Client) {
	h.mu.Lock()
	for _, code := range c.Rooms() {
		if set, ok := h.rooms[code]; ok {
			delete(set, c)
			if len(set) == 0 {
				delete(h.rooms, code)
			}
		}
	}
	isCurrent := false
	if cur, ok := h.users[c.UserID]; ok && cur == c {
		delete(h.users, c.UserID)
		isCurrent = true
	}
	h.mu.Unlock()

	if isCurrent {
		h.notifyOffline(c.UserID)
	}
}

// JoinRoom 客户端加入房间广播域
func (h *Hub) JoinRoom(c *Client, roomCode string) {
	if c == nil {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	c.join(roomCode)
	if h.rooms[roomCode] == nil {
		h.rooms[roomCode] = make(map[*Client]struct{})
	}
	h.rooms[roomCode][c] = struct{}{}
}

// LeaveRoom 客户端离开房间广播域
func (h *Hub) LeaveRoom(c *Client, roomCode string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	c.leave(roomCode)
	if set, ok := h.rooms[roomCode]; ok {
		delete(set, c)
		if len(set) == 0 {
			delete(h.rooms, roomCode)
		}
	}
}

// BroadcastToRoom 向房间内所有连接广播事件
func (h *Hub) BroadcastToRoom(roomCode, event string, data any) {
	payload, err := json.Marshal(Event{Event: event, Data: data})
	if err != nil {
		return
	}
	h.mu.RLock()
	set := h.rooms[roomCode]
	clients := make([]*Client, 0, len(set))
	for c := range set {
		clients = append(clients, c)
	}
	h.mu.RUnlock()
	for _, c := range clients {
		c.sendBytes(payload)
	}
}

// SendToUser 向指定用户推送事件
func (h *Hub) SendToUser(userID uint, event string, data any) {
	payload, err := json.Marshal(Event{Event: event, Data: data})
	if err != nil {
		return
	}
	h.mu.RLock()
	c := h.users[userID]
	h.mu.RUnlock()
	if c != nil {
		c.sendBytes(payload)
	}
}

// UserOnline 判断用户是否有活跃连接
func (h *Hub) UserOnline(userID uint) bool {
	h.mu.RLock()
	defer h.mu.RUnlock()
	_, ok := h.users[userID]
	return ok
}

// ClientOf 获取用户当前连接（可能为 nil）
func (h *Hub) ClientOf(userID uint) *Client {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return h.users[userID]
}

// ==============================
// 在线状态回调（5 秒防抖）
// ==============================

// notifyOnline 上线通知：立即触发；防抖期内重复上线不重发
func (h *Hub) notifyOnline(uid uint) {
	h.pmu.Lock()
	ps := h.presence[uid]
	if ps == nil {
		ps = &presenceState{}
		h.presence[uid] = ps
	}
	// 取消挂起的 offline 延迟推送（断线重连场景）
	if ps.offlineTimer != nil {
		ps.offlineTimer.Stop()
		ps.offlineTimer = nil
	}
	need := true
	if ps.lastStatus && time.Since(ps.lastNotify) < h.PresenceDebounce {
		need = false // 防抖：刚广播过 online，跳过
	}
	if !need {
		h.pmu.Unlock()
		return
	}
	ps.lastStatus = true
	ps.lastNotify = time.Now()
	cb := h.OnUserOnline
	h.pmu.Unlock()
	if cb != nil {
		cb(uid)
	}
}

// notifyOffline 下线通知：延迟 5 秒确认（期间重连则取消），避免抖动刷屏
func (h *Hub) notifyOffline(uid uint) {
	h.pmu.Lock()
	ps := h.presence[uid]
	if ps == nil {
		ps = &presenceState{}
		h.presence[uid] = ps
	}
	if ps.offlineTimer != nil {
		ps.offlineTimer.Stop()
	}
	ps.offlineTimer = time.AfterFunc(h.PresenceDebounce, func() {
		h.pmu.Lock()
		if h.UserOnline(uid) {
			// 防抖期内已重连：视为在线，不广播 offline
			ps.lastStatus = true
			ps.lastNotify = time.Now()
			ps.offlineTimer = nil
			h.pmu.Unlock()
			return
		}
		ps.lastStatus = false
		ps.lastNotify = time.Now()
		ps.offlineTimer = nil
		cb := h.OnUserOffline
		delete(h.presence, uid)
		h.pmu.Unlock()
		if cb != nil {
			cb(uid)
		}
	})
	h.pmu.Unlock()
}
