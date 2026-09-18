package main

import (
	"io"
	"log"
	"net/http"
	_ "net/http/pprof"
	"os"
	"path/filepath"

	"github.com/gin-contrib/sessions"
	"github.com/gin-contrib/sessions/cookie"
	"github.com/gin-gonic/gin"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	gormlogger "gorm.io/gorm/logger"

	"botc-server/internal/aiclient"
	"botc-server/internal/config"
	"botc-server/internal/handler"
	"botc-server/internal/model"
	"botc-server/internal/room"
	"botc-server/internal/ws"
)

func main() {
	if err := config.EnsureDir(config.C.DBPath); err != nil {
		log.Fatalf("创建数据目录失败: %v", err)
	}
	// 日志文件防膨胀：超过 10MB 截断保留尾部 1MB（须在打开日志句柄之前，避免句柄偏移错乱）
	for _, name := range []string{"botc.log", "gin.log"} {
		if fi, err := os.Stat(name); err == nil && fi.Size() > 10<<20 {
			if b, _ := os.ReadFile(name); len(b) > 1<<20 {
				_ = os.WriteFile(name, b[len(b)-(1<<20):], 0o644)
			}
		}
	}
	// 服务日志：同时输出到控制台与文件（cmd 前台运行可见，WMI 后台运行落盘可查）
	// 注：WMI 无人消费 stdout 时仅少量 boot 日志，管道缓冲足够不阻塞
	if lf, err := os.OpenFile(filepath.Join(filepath.Dir(config.C.DBPath), "botc.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644); err == nil {
		log.SetOutput(io.MultiWriter(os.Stdout, lf))
	}
	log.Printf("数据库位置: %s", config.C.DBPath)

	db, err := gorm.Open(sqlite.Open(config.C.DBPath), &gorm.Config{
		Logger: gormlogger.Default.LogMode(gormlogger.Silent),
	})
	if err != nil {
		log.Fatalf("数据库初始化失败: %v", err)
	}
	// 关键稳定性修复：
	// 1) SQLite 单写者，连接池限制为 1，彻底消除并发写锁竞争（此前会堆积等待→资源耗尽）
	// 2) busy_timeout 兜底：写锁等待 5 秒后报错而非无限阻塞
	if sqlDB, err := db.DB(); err == nil {
		sqlDB.SetMaxOpenConns(1)
		sqlDB.SetMaxIdleConns(1)
		sqlDB.SetConnMaxLifetime(0)
	}
	log.Println("[boot] db opened")
	if err := model.AutoMigrate(db); err != nil {
		log.Fatalf("数据库迁移失败: %v", err)
	}
	log.Println("[boot] migrate done")

	hub := ws.NewHub()
	// 好友在线状态广播（D 模块）：上下线回调 + 5 秒防抖在 Hub 内处理
	ai := aiclient.New(config.C.AIServiceURL)
	mgr := room.NewManager(hub, db, ai)
	hub.OnUserOnline = func(uid uint) { broadcastPresence(db, hub, uid, true) }
	hub.OnUserOffline = func(uid uint) {
		broadcastPresence(db, hub, uid, false)
		mgr.MarkUserOffline(uid) // 座位标记离线（断连即释放房间占用，允许加入其他房间）
	}
	log.Println("[boot] restoring rooms...")
	mgr.Restore() // 服务重启后恢复等待中的房间
	log.Println("[boot] restore done, rooms:", len(mgr.List()))

	h := &handler.Handler{DB: db, Hub: hub, Mgr: mgr}

	go func() { _ = http.ListenAndServe("127.0.0.1:8790", nil) }()
	gin.SetMode(gin.ReleaseMode)
	// 稳定性修复：gin 日志写入文件（后台启动时写无人消费的管道会阻塞 HTTP）
	if f, err := os.OpenFile("gin.log", os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644); err == nil {
		gin.DefaultWriter = f
	} else {
		gin.DefaultWriter = io.Discard
	}
	r := gin.Default()
	r.Use(corsMiddleware())
	r.Use(cacheControlMiddleware())

	store := cookie.NewStore([]byte(config.C.SessionSecret))
	r.Use(sessions.Sessions("botc_session", store))

	// HTTP 只承担：认证 + 建房入口 + 静态资源
	api := r.Group("/api")
	{
		api.POST("/auth/register", h.Register)
		api.POST("/auth/login", h.Login)
		api.POST("/auth/logout", h.Logout)
		api.GET("/me", handler.AuthRequired(), h.Me)
		api.POST("/room/create", handler.AuthRequired(), h.CreateRoom)
		api.GET("/game/:code/pending", handler.AuthRequired(), h.PendingChoice)
		api.GET("/stats", handler.AuthRequired(), h.MyStats)
		api.GET("/games", handler.AuthRequired(), h.MyGames)
		api.GET("/games/:id/replay", handler.AuthRequired(), h.GameReplay)
		api.POST("/llm_ping", handler.AuthRequired(), h.LLMPing)
		api.GET("/ai_usage", handler.AuthRequired(), h.AIUsage)
	}

	r.GET("/ws", h.WSHandler)
	r.Static("/static", "./static")
	r.GET("/", func(c *gin.Context) {
		c.File("./static/index.html")
	})
	r.NoRoute(func(c *gin.Context) {
		if len(c.Request.URL.Path) >= 4 && c.Request.URL.Path[:4] == "/api" {
			c.JSON(404, gin.H{"success": false, "message": "接口不存在"})
			return
		}
		c.File("./static/index.html")
	})

	log.Printf("血染钟楼 Go 游戏服务启动: http://%s", config.C.Addr)
	if err := r.Run(config.C.Addr); err != nil {
		log.Fatalf("服务启动失败: %v", err)
	}
}

func corsMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("Access-Control-Allow-Origin", c.GetHeader("Origin"))
		c.Header("Access-Control-Allow-Credentials", "true")
		c.Header("Access-Control-Allow-Headers", "Content-Type, Authorization")
		c.Header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(204)
			return
		}
		c.Next()
	}
}

// broadcastPresence 好友在线状态广播：通知 uid 的所有好友 + 同步 DB 在线标记
func broadcastPresence(db *gorm.DB, hub *ws.Hub, uid uint, online bool) {
	db.Model(&model.User{}).Where("id = ?", uid).Update("is_online", online)
	var friends []model.Friend
	db.Where("(user_id = ? OR friend_id = ?) AND status = ?", uid, uid, "accepted").Find(&friends)
	for i := range friends {
		hub.SendToUser(friends[i].OtherOf(uid), "friend.online", map[string]any{
			"user_id": uid, "is_online": online,
		})
	}
}

// cacheControlMiddleware 静态资源禁用缓存（前端更新后浏览器强制拉取新版本）
func cacheControlMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		p := c.Request.URL.Path
		if p == "/" || len(p) >= 8 && p[:8] == "/static/" {
			c.Header("Cache-Control", "no-cache, no-store, must-revalidate")
		}
		c.Next()
	}
}
