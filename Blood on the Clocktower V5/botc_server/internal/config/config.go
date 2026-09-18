package config

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// Config 全局配置
type Config struct {
	Addr               string
	DBPath             string
	SessionSecret      string
	AIServiceURL       string
	MinPlayersPerRoom  int
	MaxPlayersPerRoom  int
	RoomCodeLength     int
	AIChateIntervalSec int
	HumanChoiceEnabled bool
}

// C 全局配置实例
var C = &Config{
	Addr:               env("BOTC_ADDR", "127.0.0.1:8741"),
	DBPath:             env("BOTC_DB_PATH", defaultDBPath()),
	SessionSecret:      env("BOTC_SESSION_SECRET", "botc-dark-moon-secret-change-in-production"),
	AIServiceURL:       env("BOTC_AI_URL", "http://127.0.0.1:8742"),
	MinPlayersPerRoom:  5,
	MaxPlayersPerRoom:  12, // 暗流涌动剧本官方上限（13-15 人需旅行者，不实现）
	RoomCodeLength:     6,
	AIChateIntervalSec: envInt("BOTC_AI_CHAT_INTERVAL", 12),
	// 真人夜晚交互选择开关：默认开启（真人拿到占卜师/管家等主动角色时挂起等待手动选择）
	// 关闭后：夜晚全自动推进，真人角色也自动执行（演示兜底）
	HumanChoiceEnabled: envBool("BOTC_HUMAN_CHOICE", true),
}

func envBool(key string, def bool) bool {
	if v := os.Getenv(key); v != "" {
		switch strings.ToLower(v) {
		case "1", "true", "on", "yes":
			return true
		case "0", "false", "off", "no":
			return false
		}
	}
	return def
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

// defaultDBPath 数据库默认路径：锚定到可执行文件所在目录，
// 避免相对路径随启动工作目录漂移导致"数据消失"。
// go run 场景（exe 在系统临时目录）回退到当前工作目录，保持开发体验。
func defaultDBPath() string {
	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		if !strings.HasPrefix(dir, os.TempDir()) {
			return filepath.Join(dir, "data", "botc.db")
		}
	}
	cwd, _ := os.Getwd()
	return filepath.Join(cwd, "data", "botc.db")
}

// EnsureDir 确保目录存在
func EnsureDir(path string) error {
	return os.MkdirAll(filepath.Dir(path), 0o755)
}
