package ws

import (
	"encoding/json"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

const (
	writeWait      = 10 * time.Second
	pongWait       = 60 * time.Second
	pingPeriod     = 50 * time.Second
	maxMessageSize = 8192
	sendBuffer     = 256
)

// Client 单个 WebSocket 连接
type Client struct {
	Conn   *websocket.Conn
	UserID uint

	send  chan []byte
	mu    sync.RWMutex
	rooms map[string]bool
	once  sync.Once
}

func NewClient(conn *websocket.Conn, userID uint) *Client {
	return &Client{
		Conn:   conn,
		UserID: userID,
		send:   make(chan []byte, sendBuffer),
		rooms:  make(map[string]bool),
	}
}

func (c *Client) join(code string)  { c.rooms[code] = true }
func (c *Client) leave(code string) { delete(c.rooms, code) }

// Rooms 返回客户端加入的广播域
func (c *Client) Rooms() []string {
	c.mu.RLock()
	defer c.mu.RUnlock()
	out := make([]string, 0, len(c.rooms))
	for k := range c.rooms {
		out = append(out, k)
	}
	return out
}

// sendBytes 非阻塞投递消息（缓冲区满视为慢客户端，断开）
func (c *Client) sendBytes(payload []byte) {
	select {
	case c.send <- payload:
	default:
		c.Close()
	}
}

// Close 安全关闭连接
func (c *Client) Close() {
	c.once.Do(func() {
		close(c.send)
		c.Conn.Close()
	})
}

// WritePump 写协程：发送队列 + 心跳
func (c *Client) WritePump() {
	ticker := time.NewTicker(pingPeriod)
	defer func() {
		ticker.Stop()
		c.Close()
	}()
	for {
		select {
		case msg, ok := <-c.send:
			c.Conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				c.Conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}
			if err := c.Conn.WriteMessage(websocket.TextMessage, msg); err != nil {
				return
			}
		case <-ticker.C:
			c.Conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := c.Conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

// ReadPump 读协程：接收客户端指令并分发
func (c *Client) ReadPump(onMessage func(c *Client, event string, data map[string]any, reqID uint64)) {
	defer c.Close()
	c.Conn.SetReadLimit(maxMessageSize)
	c.Conn.SetReadDeadline(time.Now().Add(pongWait))
	c.Conn.SetPongHandler(func(string) error {
		c.Conn.SetReadDeadline(time.Now().Add(pongWait))
		return nil
	})
	for {
		_, raw, err := c.Conn.ReadMessage()
		if err != nil {
			return
		}
		var msg struct {
			Event string         `json:"event"`
			Data  map[string]any `json:"data"`
			ID    uint64         `json:"id"`
		}
		if err := json.Unmarshal(raw, &msg); err != nil {
			continue
		}
		if msg.Event != "" && onMessage != nil {
			onMessage(c, msg.Event, msg.Data, msg.ID)
		}
	}
}
