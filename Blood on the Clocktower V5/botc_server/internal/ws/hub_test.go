package ws

import (
	"sync"
	"testing"
	"time"
)

// 快速防抖测试：50ms 防抖窗口
func newTestHub(t *testing.T) (*Hub, *sync.Mutex, *[]string) {
	h := NewHub()
	h.PresenceDebounce = 50 * time.Millisecond
	var mu sync.Mutex
	log := []string{}
	h.OnUserOnline = func(uid uint) {
		mu.Lock()
		log = append(log, "online")
		mu.Unlock()
	}
	h.OnUserOffline = func(uid uint) {
		mu.Lock()
		log = append(log, "offline")
		mu.Unlock()
	}
	return h, &mu, &log
}

func waitFor(t *testing.T, cond func() bool, timeout time.Duration, msg string) {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("等待超时: %s", msg)
}

func TestHubPresenceOnline(t *testing.T) {
	h, _, log := newTestHub(t)
	c := NewClient(nil, 1)
	h.Register(c)
	waitFor(t, func() bool { return len(*log) >= 1 }, time.Second, "online 回调")
	if (*log)[0] != "online" {
		t.Fatalf("期望 online，实际 %v", *log)
	}
	h.Unregister(c)
}

func TestHubPresenceOfflineAfterDebounce(t *testing.T) {
	h, mu, log := newTestHub(t)
	c := NewClient(nil, 1)
	h.Register(c)
	time.Sleep(100 * time.Millisecond) // 等 online 落定
	h.Unregister(c)

	// 防抖期内不应立即触发 offline
	time.Sleep(20 * time.Millisecond)
	mu.Lock()
	n := len(*log)
	mu.Unlock()
	if n > 1 {
		t.Fatalf("防抖期内不应广播 offline: %v", *log)
	}
	// 到期后触发 offline
	waitFor(t, func() bool {
		mu.Lock()
		defer mu.Unlock()
		return len(*log) >= 2 && (*log)[1] == "offline"
	}, time.Second, "offline 延迟广播")
}

func TestHubPresenceReconnectCancelsOffline(t *testing.T) {
	h, mu, log := newTestHub(t)
	c := NewClient(nil, 1)
	h.Register(c)
	time.Sleep(100 * time.Millisecond)
	h.Unregister(c)

	// 20ms 内重连（防抖 50ms 窗口内）
	time.Sleep(20 * time.Millisecond)
	c2 := NewClient(nil, 1)
	h.Register(c2)

	// 等待远超防抖窗口，确认从未广播 offline
	time.Sleep(200 * time.Millisecond)
	mu.Lock()
	defer mu.Unlock()
	for _, ev := range *log {
		if ev == "offline" {
			t.Fatalf("重连场景不应广播 offline: %v", *log)
		}
	}
	h.Unregister(c2)
}

func TestHubPresenceDebounceOnline(t *testing.T) {
	h, mu, log := newTestHub(t)
	// 防抖验证：快速两次上线通知只广播一次（模拟踢线+重连的重复 online）
	h.notifyOnline(1)
	h.notifyOnline(1)

	time.Sleep(120 * time.Millisecond)
	mu.Lock()
	defer mu.Unlock()
	onlineCount := 0
	for _, ev := range *log {
		if ev == "online" {
			onlineCount++
		}
	}
	if onlineCount != 1 {
		t.Fatalf("防抖期内应只广播一次 online，实际 %d 次: %v", onlineCount, *log)
	}
}

func TestHubPresenceKickedConnNoOffline(t *testing.T) {
	h, mu, log := newTestHub(t)
	c1 := NewClient(nil, 1)
	h.Register(c1)
	time.Sleep(100 * time.Millisecond)

	// 模拟跨设备踢线后的状态：users[1] 已换为新连接 c2，
	// 此时旧连接 c1 的 Unregister 因 cur != c1 不应触发 offline
	c2 := NewClient(nil, 1)
	h.mu.Lock()
	h.users[1] = c2
	h.mu.Unlock()
	h.Unregister(c1)

	time.Sleep(200 * time.Millisecond)
	mu.Lock()
	defer mu.Unlock()
	for _, ev := range *log {
		if ev == "offline" {
			t.Fatalf("被踢连接不应触发 offline: %v", *log)
		}
	}
	// 清理：移除 c2（绕过踢线，直接清状态）
	h.mu.Lock()
	delete(h.users, 1)
	h.mu.Unlock()
}
