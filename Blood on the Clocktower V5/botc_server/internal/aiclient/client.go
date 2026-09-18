package aiclient

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// Client Python AI 推理服务客户端（Go 主服务通过 HTTP 调用，解耦）
type Client struct {
	BaseURL string
	HTTP    *http.Client
}

// New 创建 AI 客户端
// HTTP 超时 10 秒：AI 调用全部在独立 goroutine 异步回投，不阻塞房间事件循环；
// 智谱/通义等模型响应常需 3-8 秒，3 秒会静默丢弃导致 AI "不鸟人"，10 秒覆盖主流服务商
func New(baseURL string) *Client {
	return &Client{
		BaseURL: baseURL,
		HTTP:    &http.Client{Timeout: 10 * time.Second},
	}
}

// SpeakReq AI 发言请求：携带对局上下文（轮次/阶段/存活玩家/最近发言）+ 座位级 LLM 配置 + 私密线索 + 阵营
type SpeakReq struct {
	RoomCode  string // 房间码（Python 侧 AI 推理笔记隔离键）
	RoleName  string
	Team      string // 阵营：townsfolk/outsider=善良，minion/demon=邪恶（发言立场约束）
	Number    int
	Phase     string
	Day       int
	AliveNums []int
	Context   []map[string]any
	MyClues   []string // 该 AI 的说书人私密信息（查验结果等），供推理/分享
	LLMConf   string   // 座位级大模型配置 JSON（api_key/base_url/model）
	OtherNum  int      // 私聊场景：对话对方编号（0=非私聊）
}

// Speak 生成 AI 玩家公聊发言（POST Python AI 服务）
func (c *Client) Speak(req SpeakReq) (string, bool) {
	payload := map[string]any{
		"room_code":  req.RoomCode,
		"role_name":  req.RoleName,
		"team":       req.Team,
		"number":     req.Number,
		"phase":      req.Phase,
		"day":        req.Day,
		"alive_nums": req.AliveNums,
		"context":    req.Context,
		"my_clues":   req.MyClues,
		"llm_conf":   req.LLMConf,
		"other_num":  req.OtherNum,
	}
	var resp struct {
		Reply string `json:"reply"`
	}
	if err := c.post("/api/speak", payload, &resp); err != nil {
		return "", false
	}
	return resp.Reply, resp.Reply != ""
}

// Decide 生成 AI 夜晚行动目标决策，返回目标编号
func (c *Client) Decide(roleName, ability string, aliveNums []int, selfNum int) (int, bool) {
	return c.DecideWithConf(roleName, ability, aliveNums, selfNum, "")
}

// DecideWithConf 携带座位级 LLM 配置与私密线索的目标决策
func (c *Client) DecideWithConf(roleName, ability string, aliveNums []int, selfNum int, llmConf string) (int, bool) {
	return c.decide("", roleName, ability, aliveNums, selfNum, llmConf, nil)
}

// DecideWithClues 携带私密线索（说书人查验结果）的目标决策——AI 基于真实信息推理
func (c *Client) DecideWithClues(roleName, ability string, aliveNums []int, selfNum int, llmConf string, clues []string) (int, bool) {
	return c.decide("", roleName, ability, aliveNums, selfNum, llmConf, clues)
}

// DecideWithCluesRoom 携带房间码（Python 侧推理笔记隔离键）+ 私密线索的目标决策
func (c *Client) DecideWithCluesRoom(roomCode, roleName, ability string, aliveNums []int, selfNum int, llmConf string, clues []string) (int, bool) {
	return c.decide(roomCode, roleName, ability, aliveNums, selfNum, llmConf, clues)
}

func (c *Client) decide(roomCode, roleName, ability string, aliveNums []int, selfNum int, llmConf string, clues []string) (int, bool) {
	payload := map[string]any{
		"room_code":  roomCode,
		"role_name":  roleName,
		"ability":    ability,
		"alive_nums": aliveNums,
		"self_num":   selfNum,
		"my_clues":   clues,
		"llm_conf":   llmConf,
	}
	var resp struct {
		Choice *int `json:"choice"`
	}
	if err := c.post("/api/decide", payload, &resp); err != nil {
		return 0, false
	}
	if resp.Choice == nil {
		return 0, false
	}
	return *resp.Choice, true
}

// Ping 连通性测试：用给定 LLM 配置调一次模型，返回结果详情（添加 AI 前校验 Key）
func (c *Client) Ping(llmConf string) (map[string]any, bool) {
	payload := map[string]any{"llm_conf": llmConf}
	var resp struct {
		OK    bool   `json:"ok"`
		Error string `json:"error"`
		Model string `json:"model"`
	}
	if err := c.post("/api/ping", payload, &resp); err != nil {
		return map[string]any{"ok": false, "error": "AI 服务不可用"}, false
	}
	return map[string]any{"ok": resp.OK, "error": resp.Error, "model": resp.Model}, resp.OK
}

// Usage 查询大模型 Token 用量统计（全局+按房间+按模型）
func (c *Client) Usage() map[string]any {
	req, err := http.NewRequest(http.MethodGet, c.BaseURL+"/api/usage", nil)
	if err != nil {
		return nil
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil
	}
	return out
}

func (c *Client) post(path string, payload any, out any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequest(http.MethodPost, c.BaseURL+path, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("ai service status %d", resp.StatusCode)
	}
	return json.NewDecoder(resp.Body).Decode(out)
}
