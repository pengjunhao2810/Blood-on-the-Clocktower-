package room

import (
	"encoding/json"
	"log"
	"sync"
	"time"

	"gorm.io/gorm"

	"botc-server/internal/aiclient"
	"botc-server/internal/config"
	"botc-server/internal/engine"
	"botc-server/internal/model"
	"botc-server/internal/ws"
)

// Manager 房间注册表：内存房间集合 + DB 镜像 + 生命周期管理
type Manager struct {
	mu    sync.RWMutex
	rooms map[string]*Room
	Hub   *ws.Hub
	DB    *gorm.DB
	AI    *aiclient.Client
}

func NewManager(hub *ws.Hub, db *gorm.DB, ai *aiclient.Client) *Manager {
	return &Manager{
		rooms: make(map[string]*Room),
		Hub:   hub,
		DB:    db,
		AI:    ai,
	}
}

// Get 获取房间（未加载到内存时从 DB 恢复）
func (m *Manager) Get(code string) *Room {
	m.mu.RLock()
	r, ok := m.rooms[code]
	m.mu.RUnlock()
	if ok {
		return r
	}
	// 服务重启后的恢复路径：从 DB 加载等待中的房间
	var rec model.Room
	if err := m.DB.Where("room_code = ? AND status = ?", code, "waiting").Preload("Seats").Preload("Seats.User").First(&rec).Error; err != nil {
		return nil
	}
	m.mu.Lock()
	if r, ok = m.rooms[code]; ok {
		m.mu.Unlock()
		return r
	}
	r = restoreFromDB(m, &rec)
	m.rooms[code] = r
	m.mu.Unlock()
	go r.Run()
	return r
}

// Create 创建房间：内存 + DB + 启动 goroutine
func (m *Manager) Create(code string, hostID uint, hostName string) *Room {
	rec := model.Room{RoomCode: code, HostID: hostID, Status: "waiting", MaxPlayers: 8}
	m.DB.Create(&rec)
	m.DB.Create(&model.RoomSeat{RoomID: rec.ID, UserID: &hostID, SeatNumber: 0})

	r := &Room{
		Code:       code,
		HostID:     hostID,
		MaxPlayers: 8,
		Status:     "waiting",
		seats: map[int]*Seat{
			0: {Number: 0, UserID: hostID, Username: hostName},
		},
		events:  make(chan Event, 64),
		quit:    make(chan struct{}),
		mgr:     m,
		msgSeq:  0,
		stories: make(map[int][]string),
	}
	m.mu.Lock()
	m.rooms[code] = r
	m.mu.Unlock()
	go r.Run()
	r.addSystemMsg("房间 " + code + " 已创建，等待玩家加入…")
	return r
}

// Delete 移除房间（解散）
func (m *Manager) Delete(code string) {
	m.mu.Lock()
	r, ok := m.rooms[code]
	if ok {
		delete(m.rooms, code)
	}
	m.mu.Unlock()
	if ok {
		close(r.quit)
		// 房间销毁 = 房间记录 + 座位记录一起删（此前只删房间留下孤儿座位）
		var rec model.Room
		m.DB.Where("room_code = ?", code).First(&rec)
		m.DB.Exec("DELETE FROM room_seats WHERE room_id = ?", rec.ID)
		m.DB.Where("room_code = ?", code).Delete(&model.Room{})
	}
}

// List 所有内存房间
func (m *Manager) List() []string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]string, 0, len(m.rooms))
	for k := range m.rooms {
		out = append(out, k)
	}
	return out
}

// MarkUserOffline WS 断连时标记该用户在所有房间的座位为离线（空置则开始清理计时）
// 通过房间事件投递保证线程安全
func (m *Manager) MarkUserOffline(uid uint) {
	m.mu.RLock()
	rooms := make([]*Room, 0, len(m.rooms))
	for _, r := range m.rooms {
		rooms = append(rooms, r)
	}
	m.mu.RUnlock()
	for _, r := range rooms {
		r.Post(Event{Type: "user_offline", UserID: uid})
	}
}

// Restore 服务启动时恢复所有房间（含进行中的对局）
func (m *Manager) Restore() {
	// 清理孤儿座位（房间已销毁但座位残留的历史脏数据）
	m.DB.Exec("DELETE FROM room_seats WHERE room_id NOT IN (SELECT id FROM rooms)")
	var recs []model.Room
	m.DB.Preload("Seats").Preload("Seats.User").Find(&recs)
	restoredPlaying := 0
	for i := range recs {
		switch recs[i].Status {
		case "waiting":
			r := restoreFromDB(m, &recs[i])
			m.rooms[recs[i].RoomCode] = r
			// 恢复的等待房间所有座位均离线 → 立即销毁（防止历史房间堆积）
			r.markAbandonedIfEmpty()
			if _, still := m.rooms[recs[i].RoomCode]; still {
				go r.Run()
			}
		case "playing":
			// 恢复进行中的对局：重建引擎与对局状态（角色/存活/相位）
			r := restorePlayingFromDB(m, &recs[i])
			if r != nil {
				m.rooms[recs[i].RoomCode] = r
				go r.Run()
				restoredPlaying++
			}
		}
	}
	log.Printf("[restore] 恢复 %d 个等待房间，%d 个进行中对局", len(recs)-restoredPlaying, restoredPlaying)
}

// restorePlayingFromDB 恢复进行中的对局（重建 GameData 与引擎）
func restorePlayingFromDB(m *Manager, rec *model.Room) *Room {
	r := restoreFromDB(m, rec)
	r.Status = "playing"
	if rec.GameData != "" {
		gd := &engine.GameData{}
		if err := json.Unmarshal([]byte(rec.GameData), gd); err == nil {
			r.game = gd
			r.eng = engine.NewEngine(gd, rec.RoomCode, func(event string, data any) {
				m.Hub.BroadcastToRoom(rec.RoomCode, event, data)
			})
			r.eng.AI = m.AI
			r.eng.HumanChoice = config.C.HumanChoiceEnabled
			r.startedAt = time.Now()
		}
	}
	if r.game == nil {
		return nil
	}
	// 私聊状态初始化（恢复 private_chat 阶段的存档时防 nil map panic）
	r.privateInvites = map[int]int{}
	r.privateSessions = map[int]map[int]bool{}
	// 恢复即视为空置起点：3 分钟内无真人加入 → 自动复位（防止对局垃圾堆积）
	r.abandonedAt = time.Now()
	return r
}

func restoreFromDB(m *Manager, rec *model.Room) *Room {
	r := &Room{
		Code:       rec.RoomCode,
		HostID:     rec.HostID,
		MaxPlayers: rec.MaxPlayers,
		Status:     "waiting",
		seats:      make(map[int]*Seat),
		events:     make(chan Event, 64),
		quit:       make(chan struct{}),
		mgr:        m,
		stories:    make(map[int][]string),
	}
	for _, s := range rec.Seats {
		name := ""
		if s.IsAI {
			name = "AI-" + itoa(s.SeatNumber)
		} else if s.User != nil {
			name = s.User.Username
		}
		var uid uint
		if s.UserID != nil {
			uid = *s.UserID
		}
		r.seats[s.SeatNumber] = &Seat{Number: s.SeatNumber, UserID: uid, Username: name, IsAI: s.IsAI, AIType: s.AIType, IsReady: s.IsAI}
	}
	return r
}

// Seat 内存座位
type Seat struct {
	Number    int    `json:"seat_number"`
	UserID    uint   `json:"user_id"`
	Username  string `json:"username"`
	IsAI      bool   `json:"is_ai"`
	AIType    string `json:"ai_type"` // local/api
	LLMConfig string `json:"-"`       // 大模型配置 JSON（api_key/base_url/model，仅 api 类型）
	IsReady   bool   `json:"is_ready"`
	IsOnline  bool   `json:"is_online"`
}

// Event 房间事件：WS 指令被包装后投递到房间 goroutine 串行处理
type Event struct {
	Type   string
	UserID uint
	Data   map[string]any
	Reply  func(ok bool, message string, data map[string]any)
}

// ChatMsg 房间公聊消息（内存）
type ChatMsg struct {
	ID       uint64    `json:"id"`
	Username string    `json:"username"`
	Content  string    `json:"content"`
	System   bool      `json:"system"`
	At       time.Time `json:"created_at"`
}

// GameMsg 对局公聊消息（内存，匿名编号）；Number=0 表示系统消息（提名/投票统计等）
type GameMsg struct {
	ID       uint64    `json:"id"`
	Number   int       `json:"number"`
	Username string    `json:"username,omitempty"` // 发言人显示名（真人=账号名，AI=模型名）
	Content  string    `json:"content"`
	System   bool      `json:"system"`
	AIModel  string    `json:"ai_model,omitempty"` // AI 发言时显示所调大模型名
	At       time.Time `json:"created_at"`
}

// ModelFromLLMConfig 从座位级大模型配置 JSON 提取模型名（展示用）
func ModelFromLLMConfig(llmJSON string) string {
	if llmJSON == "" {
		return ""
	}
	var cfg struct {
		Model string `json:"model"`
	}
	if err := json.Unmarshal([]byte(llmJSON), &cfg); err != nil || cfg.Model == "" {
		return ""
	}
	return cfg.Model
}

func itoa(n int) string {
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

// pidOfNum 按匿名编号查找玩家 pid
func pidOfNum(gd *engine.GameData, num int) string {
	for pid, p := range gd.Players {
		if p.Number == num {
			return pid
		}
	}
	return ""
}
