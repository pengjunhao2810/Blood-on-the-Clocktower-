package handler

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-contrib/sessions"
	"github.com/gin-gonic/gin"
	"golang.org/x/crypto/bcrypt"
	"gorm.io/gorm"

	"botc-server/internal/model"
	"botc-server/internal/room"
	"botc-server/internal/ws"
)

func itoa(n int) string { return strconv.Itoa(n) }

// Handler 聚合依赖：HTTP 层只做认证与建房，实时交互全部走 WS → 房间 Actor
type Handler struct {
	DB  *gorm.DB
	Hub *ws.Hub
	Mgr *room.Manager
}

// OK 成功响应
func OK(c *gin.Context, data any) {
	c.JSON(http.StatusOK, gin.H{"success": true, "data": data})
}

// Fail 失败响应
func Fail(c *gin.Context, code int, msg string) {
	c.JSON(code, gin.H{"success": false, "message": msg})
}

// CurrentUserID 从 session 取当前用户 ID，未登录返回 0
func CurrentUserID(c *gin.Context) uint {
	s := sessions.Default(c)
	switch v := s.Get("user_id").(type) {
	case uint:
		return v
	case uint64:
		return uint(v)
	case int:
		return uint(v)
	case int64:
		return uint(v)
	}
	return 0
}

func setLogin(c *gin.Context, uid uint) {
	s := sessions.Default(c)
	s.Set("user_id", uid)
	s.Options(sessions.Options{MaxAge: 7 * 24 * 3600, HttpOnly: true, Path: "/"})
	_ = s.Save()
}

// AuthRequired 登录校验中间件
func AuthRequired() gin.HandlerFunc {
	return func(c *gin.Context) {
		if CurrentUserID(c) == 0 {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"success": false, "message": "未登录"})
			return
		}
		c.Next()
	}
}

// CurrentUser 获取当前用户模型
func CurrentUser(c *gin.Context, db *gorm.DB) *model.User {
	uid := CurrentUserID(c)
	if uid == 0 {
		return nil
	}
	var u model.User
	if err := db.First(&u, uid).Error; err != nil {
		return nil
	}
	return &u
}

// Register 注册
func (h *Handler) Register(c *gin.Context) {
	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		Fail(c, 400, "参数错误")
		return
	}
	if len(req.Username) < 2 || len(req.Username) > 20 {
		Fail(c, 400, "用户名长度 2-20")
		return
	}
	if len(req.Password) < 6 {
		Fail(c, 400, "密码至少 6 位")
		return
	}
	var cnt int64
	h.DB.Model(&model.User{}).Where("username = ?", req.Username).Count(&cnt)
	if cnt > 0 {
		Fail(c, 400, "用户名已注册")
		return
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		Fail(c, 500, "服务器错误")
		return
	}
	u := model.User{Username: req.Username, PasswordHash: string(hash), IsOnline: true, LastActive: time.Now()}
	if err := h.DB.Create(&u).Error; err != nil {
		Fail(c, 500, "服务器错误")
		return
	}
	setLogin(c, u.ID)
	OK(c, gin.H{"user": gin.H{"id": u.ID, "username": u.Username}})
}

// Login 登录
func (h *Handler) Login(c *gin.Context) {
	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		Fail(c, 400, "参数错误")
		return
	}
	var u model.User
	if err := h.DB.Where("username = ?", req.Username).First(&u).Error; err != nil {
		Fail(c, 401, "用户名或密码错误")
		return
	}
	if bcrypt.CompareHashAndPassword([]byte(u.PasswordHash), []byte(req.Password)) != nil {
		Fail(c, 401, "用户名或密码错误")
		return
	}
	u.IsOnline = true
	u.LastActive = time.Now()
	h.DB.Save(&u)
	setLogin(c, u.ID)
	OK(c, gin.H{"user": gin.H{"id": u.ID, "username": u.Username}})
}

// Logout 登出
func (h *Handler) Logout(c *gin.Context) {
	if u := CurrentUser(c, h.DB); u != nil {
		u.IsOnline = false
		h.DB.Save(u)
	}
	OK(c, nil)
}

// Me 当前用户信息（前端 WS 连接前的会话检查）
func (h *Handler) Me(c *gin.Context) {
	u := CurrentUser(c, h.DB)
	if u == nil {
		Fail(c, 401, "未登录")
		return
	}
	OK(c, gin.H{"user": gin.H{"id": u.ID, "username": u.Username}})
}

// LLMPing 大模型连通性测试（添加 AI 前校验 Key/端点可用性）
func (h *Handler) LLMPing(c *gin.Context) {
	u := CurrentUser(c, h.DB)
	if u == nil {
		Fail(c, 401, "未登录")
		return
	}
	var req struct {
		LLMConf string `json:"llm_conf"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		Fail(c, 400, "参数错误")
		return
	}
	result, ok := h.Mgr.AI.Ping(req.LLMConf)
	_ = ok
	OK(c, result)
}

// AIUsage 查询大模型 Token 用量统计（转发 Python AI 服务）
func (h *Handler) AIUsage(c *gin.Context) {
	u := CurrentUser(c, h.DB)
	if u == nil {
		Fail(c, 401, "未登录")
		return
	}
	result := h.Mgr.AI.Usage()
	if result == nil {
		Fail(c, 502, "AI 服务不可用")
		return
	}
	OK(c, result)
}

// MyStats 个人战绩统计（总场次/胜场/胜率/善良邪恶场次）
func (h *Handler) MyStats(c *gin.Context) {
	u := CurrentUser(c, h.DB)
	if u == nil {
		Fail(c, 401, "未登录")
		return
	}
	var total int64
	h.DB.Model(&model.GameLog{}).Where("user_ids LIKE ?", "%,"+itoa(int(u.ID))+",%").Count(&total)
	var wins int64
	h.DB.Model(&model.GameLog{}).Where("user_ids LIKE ? AND winner = 'good'", "%,"+itoa(int(u.ID))+",%").Count(&wins)
	winRate := 0.0
	if total > 0 {
		winRate = float64(wins) / float64(total)
	}
	OK(c, gin.H{
		"total":    total,
		"wins":     wins,
		"win_rate": winRate,
	})
}

// MyGames 我的历史对局列表（倒序，最多 50 条）
func (h *Handler) MyGames(c *gin.Context) {
	u := CurrentUser(c, h.DB)
	if u == nil {
		Fail(c, 401, "未登录")
		return
	}
	var logs []model.GameLog
	h.DB.Where("user_ids LIKE ?", "%,"+itoa(int(u.ID))+",%").
		Order("id DESC").Limit(50).Find(&logs)
	items := []gin.H{}
	for _, l := range logs {
		items = append(items, gin.H{
			"id":         l.ID,
			"room_code":  l.RoomCode,
			"started_at": l.StartedAt,
			"ended_at":   l.EndedAt,
			"winner":     l.Winner,
			"day":        l.Day,
		})
	}
	OK(c, gin.H{"games": items})
}

// GameReplay 对局回放详情（读归档日志，不影响运行时状态）
func (h *Handler) GameReplay(c *gin.Context) {
	u := CurrentUser(c, h.DB)
	if u == nil {
		Fail(c, 401, "未登录")
		return
	}
	var log model.GameLog
	if err := h.DB.First(&log, c.Param("id")).Error; err != nil {
		Fail(c, 404, "对局不存在")
		return
	}
	if !strings.Contains(log.UserIDs, ","+itoa(int(u.ID))+",") {
		Fail(c, 403, "你不是该对局的参与者")
		return
	}
	OK(c, gin.H{
		"id":           log.ID,
		"room_code":    log.RoomCode,
		"started_at":   log.StartedAt,
		"ended_at":     log.EndedAt,
		"winner":       log.Winner,
		"day":          log.Day,
		"players":      json.RawMessage(log.Players),
		"messages":     json.RawMessage(log.Messages),
		"actions":      json.RawMessage(log.Actions),
		"private_msgs": json.RawMessage(log.PrivateMsgs),
	})
}

// CreateRoom 创建房间（HTTP 仅做入口，状态全在房间 Actor）
func (h *Handler) CreateRoom(c *gin.Context) {
	u := CurrentUser(c, h.DB)
	if u == nil {
		Fail(c, 401, "未登录")
		return
	}
	code := genRoomCode(h.DB)
	r := h.Mgr.Create(code, u.ID, u.Username)
	OK(c, gin.H{"room": gin.H{
		"room_code": r.Code, "host_id": r.HostID, "max_players": r.MaxPlayers,
	}})
}

// PendingChoice HTTP 兜底端点：WS 完全不可用时前端仍可轮询获取挂起状态
// 通过房间事件循环串行查询；返回 pending_choice + 请求者的匿名编号（前端零状态依赖）
func (h *Handler) PendingChoice(c *gin.Context) {
	u := CurrentUser(c, h.DB)
	if u == nil {
		Fail(c, 401, "未登录")
		return
	}
	code := c.Param("code")
	r := h.Mgr.Get(code)
	if r == nil {
		OK(c, gin.H{"pending_choice": nil, "my_number": 0})
		return
	}
	ch := make(chan map[string]any, 1)
	r.Post(room.Event{
		Type:   "query_pending",
		UserID: u.ID,
		Data:   map[string]any{},
		Reply: func(ok bool, msg string, payload map[string]any) {
			ch <- payload
		},
	})
	select {
	case payload := <-ch:
		OK(c, gin.H{"pending_choice": payload["pending_choice"], "my_number": payload["my_number"]})
	case <-time.After(3 * time.Second):
		OK(c, gin.H{"pending_choice": nil, "my_number": 0})
	}
}

func genRoomCode(db *gorm.DB) string {
	const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
	for {
		b := make([]byte, 6)
		for i := range b {
			b[i] = chars[randIntn(len(chars))]
		}
		code := string(b)
		var cnt int64
		db.Model(&model.Room{}).Where("room_code = ?", code).Count(&cnt)
		if cnt == 0 {
			return code
		}
	}
}
