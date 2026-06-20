import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from flask import Flask, jsonify, request, render_template_string
from games.blood_on_clocktower.rules import BloodOnClocktowerGame
from games.blood_on_clocktower.roles import BOTC_ROLES, BOTC_TEAMS
from core.agent import SocialDeductionAgent

app = Flask(__name__)

class GameController:
    def __init__(self, num_players=7):
        self.num_players = num_players
        self.game = None
        self.agents = None
        self.finished = False
        self._init_game()

    def _init_game(self):
        self.agents = [SocialDeductionAgent(f'玩家{i+1}', '?') for i in range(self.num_players)]
        self.game = BloodOnClocktowerGame(num_players=self.num_players, script='暗流涌动')
        self.game.setup_game(self.agents)
        self.finished = False
        self.flow = ['role_assign']
        self.day_prepared = False
        if not hasattr(self, 'full_log'):
            self.full_log = []
        self.full_log.append({'num_players': self.num_players, 'log': list(self.game.storyteller_log)})
        while len(self.full_log) > 5:
            self.full_log.pop(0)

    def step(self):
        if self.finished or self.game.game_record.get('result'):
            self.finished = True
            return self.get_state()

        if not self.flow:
            self.flow = ['night', 'private_chat', 'public_chat', 'nomination']

        action = self.flow.pop(0)

        if action == 'role_assign':
            self.game.phase_role_assignment()

        elif action == 'night':
            if self.game.day_count > 0:
                self.game.end_day()
                if self.game.game_record.get('result'):
                    self.finished = True
                    return self.get_state()
            self.game.run_night()
            if self.game.game_record.get('result'):
                self.finished = True

        elif action == 'private_chat':
            if not self.day_prepared:
                self.game.start_day()
                self.day_prepared = True
                if self.game.game_record.get('result'):
                    self.finished = True
                    return self.get_state()
            self.game._private_chat_phase()

        elif action == 'public_chat':
            self.game._public_chat_phase()

        elif action == 'nomination':
            self.game._nomination_and_voting_phase()
            self.day_prepared = False

        return self.get_state()

    def get_state(self):
        g = self.game
        team_cn = {'townsfolk': '镇民', 'outsider': '外来者', 'minion': '爪牙', 'demon': '恶魔'}
        phase_icons = {
            'SETUP': '⚙️', 'ROLE_ASSIGN': '📋',
            'NIGHT': '🌙', 'DAY': '☀️',
            'PRIVATE_CHAT': '🤫', 'PUBLIC_CHAT': '💬',
            'NOMINATION': '🗳️',
        }

        raw = g.game_phase
        base = raw.split('_')[0] if '_' in raw else raw
        icon = phase_icons.get(base, '📜')

        phase_labels = {
            'SETUP': ('⚙️ 游戏设置', '准备中...'),
            'ROLE_ASSIGN': ('📋 角色分配', '各玩家已查看身份'),
        }
        if base in phase_labels:
            pn, pd = phase_labels[base]
        elif 'NIGHT' in raw:
            pn, pd = '🌙 天黑闭眼', '各角色按顺序行动中...'
        elif 'PRIVATE_CHAT' in raw:
            pn, pd = '🤫 私聊环节', '玩家私下交流信息'
        elif 'PUBLIC_CHAT' in raw:
            pn, pd = '💬 公聊环节', '玩家公开讨论'
        elif 'NOMINATION' in raw:
            pn, pd = '🗳️ 提名投票', '提名·辩护·全体表决'
        elif 'DAY' in raw:
            pn, pd = '☀️ 白天', '交流与投票'
        else:
            pn, pd = raw, ''

        alive = g.get_alive_names()
        all_agents = g.registry.all_agents()
        all_names = [a.name for a in all_agents]
        evil_agents = [a for a in all_agents if a.role in BOTC_TEAMS['demon'] + BOTC_TEAMS['minion']]

        players = []
        seat_order = g.player_order
        for a in all_agents:
            info = BOTC_ROLES.get(a.role, {})
            seat = (seat_order.index(a.name) + 1) if a.name in seat_order else 0
            players.append({
                'name': a.name, 'seat': seat, 'role': a.role, 'icon': info.get('icon', '?'),
                'team': info.get('team', ''),
                'team_cn': team_cn.get(info.get('team', ''), ''),
                'status': 'alive' if a.alive else 'dead',
                'poisoned': a.game_state.get('is_poisoned', False) if a.alive else False,
            })

        # 私聊历史整理成前端友好的格式
        chat_threads = []
        pch = g.game_record.get("private_chat_history", {})
        for thread_key, msgs in pch.items():
            # thread_key格式: D1_玩家1🔄玩家3
            parts = thread_key.split("_", 1)
            day_label = parts[0] if len(parts) > 1 else "D0"
            pair_label = parts[1] if len(parts) > 1 else thread_key
            chat_threads.append({
                "key": thread_key,
                "day": day_label,
                "pair": pair_label,
                "messages": msgs,
            })

        role_configs = {
            5: {"townsfolk": 3, "outsider": 0, "minion": 1, "demon": 1},
            6: {"townsfolk": 3, "outsider": 1, "minion": 1, "demon": 1},
            7: {"townsfolk": 5, "outsider": 0, "minion": 1, "demon": 1},
            8: {"townsfolk": 5, "outsider": 0, "minion": 2, "demon": 1},
            9: {"townsfolk": 5, "outsider": 2, "minion": 1, "demon": 1},
            10: {"townsfolk": 7, "outsider": 0, "minion": 2, "demon": 1},
            11: {"townsfolk": 7, "outsider": 1, "minion": 2, "demon": 1},
            12: {"townsfolk": 7, "outsider": 2, "minion": 2, "demon": 1},
        }

        return {
            'phase_name': pn, 'phase_desc': pd, 'raw_phase': raw,
            'day_count': g.day_count, 'night_count': g.night_count,
            'alive_count': len(alive), 'dead_count': len(all_names) - len(alive),
            'evil_count': len([a for a in evil_agents if a.alive]),
            'players': players,
            'log': g.storyteller_log[-50:] if g.storyteller_log else ['等待开始...'],
            'finished': self.finished or bool(g.game_record.get('result')),
            'result': g.game_record.get('result'),
            'chat_threads': chat_threads,
            'role_config': role_configs,
            'current_player_count': self.num_players,
        }

ctrl = GameController()

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>血染钟楼 - 私聊对话框</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Microsoft YaHei',sans-serif; background:#0a0a1a; color:#e0e0e0; min-height:100vh; overflow-x:hidden; }
.header { background:linear-gradient(135deg,#1a1a3e,#0d0d2a); padding:18px 30px; display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid #ffd70033; }
.header h1 { color:#ffd700; font-size:22px; letter-spacing:2px; }
.header .info { color:#888; font-size:13px; }
.header .info span { color:#ffd700; }
.container { max-width:1200px; margin:0 auto; padding:20px; }
.phase-bar { background:linear-gradient(135deg,#1a1a3e,#2a1a3e); border:1px solid #ffd70044; border-radius:12px; padding:14px 20px; margin-bottom:16px; display:flex; justify-content:space-between; align-items:center; }
.phase-bar .phase-name { color:#ffd700; font-size:20px; font-weight:bold; }
.phase-bar .phase-desc { color:#aaa; font-size:13px; margin-top:4px; }
.phase-bar .round { color:#888; font-size:14px; }
.phase-bar .round span { color:#4CAF50; font-weight:bold; }
.controls { display:flex; gap:10px; margin-bottom:16px; flex-wrap:wrap; }
.controls button { padding:12px 28px; border:none; border-radius:8px; font-size:15px; font-weight:bold; cursor:pointer; transition:all .2s; }
.controls button:hover { transform:translateY(-2px); box-shadow:0 4px 15px rgba(0,0,0,.4); }
.btn-step { background:linear-gradient(135deg,#4CAF50,#45a049); color:#fff; }
.btn-step:disabled { opacity:0.4; cursor:not-allowed; transform:none !important; }
.btn-auto { background:linear-gradient(135deg,#2196F3,#1a88e8); color:#fff; }
.btn-reset { background:linear-gradient(135deg,#f44336,#d32f2f); color:#fff; }
.info-row { display:flex; gap:20px; margin-bottom:16px; flex-wrap:wrap; }
.info-item { background:#111125; border-radius:8px; padding:10px 18px; color:#aaa; font-size:13px; }
.info-item span { color:#ffd700; font-weight:bold; }
.player-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(165px,1fr)); gap:12px; margin-bottom:16px; }
.player-card { background:linear-gradient(135deg,#1a1a3e,#15152e); border-radius:12px; padding:14px 10px; text-align:center; border:2px solid #333; position:relative; overflow:hidden; cursor:pointer; transition:all .2s; }
.player-card:hover { transform:translateY(-2px); border-color:#ffd70066; }
.player-card::before { content:''; position:absolute; top:0; left:0; right:0; height:3px; }
.player-card.alive::before { background:linear-gradient(90deg,#4CAF50,#8BC34A); }
.player-card.dead { opacity:.35; border-color:#555; }
.player-card.dead::before { background:#666; }
.player-card .icon { font-size:30px; margin-bottom:4px; }
.player-card .name { font-size:15px; font-weight:bold; margin-bottom:2px; }
.player-card .role { font-size:12px; padding:2px 10px; border-radius:10px; display:inline-block; margin-bottom:2px; }
.player-card .role.townsfolk { background:#4a90d944; color:#7ab8ff; }
.player-card .role.outsider { background:#7b68ee44; color:#a89bff; }
.player-card .role.minion { background:#d94a4a44; color:#ff7a7a; }
.player-card .role.demon { background:#ff444444; color:#ff8888; }
.player-card .team { font-size:11px; color:#888; }
.player-card .status { font-size:11px; padding:2px 8px; border-radius:8px; display:inline-block; margin-top:4px; }
.player-card .status.alive { background:#4CAF5022; color:#8BC34A; }
.player-card .status.dead { background:#66666622; color:#999; }
.player-card .poisoned { position:absolute; top:6px; right:6px; background:#9C27B0; color:#fff; font-size:9px; padding:2px 5px; border-radius:5px; }

/* ============ 布局: 左(主内容) + 右(聊天侧栏) ============ */
.main-layout { display:flex; gap:20px; }
.main-content { flex:1; min-width:0; }
.chat-sidebar { width:380px; flex-shrink:0; }

/* ============ 私聊线程列表 ============ */
.chat-panel { background:#111125; border:1px solid #2a2a4e; border-radius:12px; overflow:hidden; }
.chat-panel .panel-header { background:linear-gradient(135deg,#1a1a3e,#2a1a3e); padding:12px 16px; border-bottom:1px solid #2a2a4e; color:#ffd700; font-size:14px; font-weight:bold; display:flex; align-items:center; gap:8px; }
.chat-thread-list { max-height:480px; overflow-y:auto; }
.thread-item { display:flex; align-items:center; gap:10px; padding:10px 14px; cursor:pointer; transition:all .15s; border-bottom:1px solid #1a1a2e; }
.thread-item:hover { background:#1a1a3e; }
.thread-item:last-child { border-bottom:none; }
.thread-item .thread-avatars { font-size:20px; }
.thread-item .thread-info { flex:1; min-width:0; }
.thread-item .thread-pair { font-size:13px; color:#e0e0e0; font-weight:bold; }
.thread-item .thread-day { font-size:11px; color:#888; }
.thread-item .thread-preview { font-size:12px; color:#666; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:2px; }
.thread-item.active { background:#2a1a3e; border-left:3px solid #ffd700; }
.thread-item .unread-badge { background:#ffd700; color:#000; font-size:10px; padding:2px 6px; border-radius:10px; font-weight:bold; }

/* ============ 聊天对话框(气泡) ============ */
.chat-view { background:#0d0d1a; border:1px solid #2a2a4e; border-radius:12px; overflow:hidden; display:none; }
.chat-view.show { display:block; }
.chat-view .chat-header { background:linear-gradient(135deg,#1a1a3e,#2a1a3e); padding:12px 16px; border-bottom:1px solid #2a2a4e; display:flex; align-items:center; gap:8px; }
.chat-view .chat-header .back-btn { background:none; border:none; color:#888; cursor:pointer; font-size:18px; padding:0 4px; }
.chat-view .chat-header .back-btn:hover { color:#ffd700; }
.chat-view .chat-header .chat-title { color:#ffd700; font-size:14px; font-weight:bold; flex:1; }
.chat-view .chat-header .chat-day { color:#888; font-size:11px; }
.chat-bubbles { padding:16px; max-height:420px; overflow-y:auto; display:flex; flex-direction:column; gap:10px; }
.chat-bubble { max-width:85%; padding:10px 14px; border-radius:14px; font-size:13px; line-height:1.5; position:relative; word-break:break-word; }
.chat-bubble.left { align-self:flex-start; background:#1a1a4e; border-bottom-left-radius:4px; }
.chat-bubble.right { align-self:flex-end; background:#2a5a2a; border-bottom-right-radius:4px; }
.chat-bubble .bubble-speaker { font-size:11px; font-weight:bold; margin-bottom:4px; }
.chat-bubble.left .bubble-speaker { color:#7ab8ff; }
.chat-bubble.right .bubble-speaker { color:#8BC34A; }
.chat-bubble .bubble-round { font-size:10px; color:#666; margin-top:6px; text-align:right; }
.chat-empty { text-align:center; color:#555; padding:60px 20px; font-size:14px; }

/* ============ 日志 ============ */
.log-area { background:#0d0d1a; border:1px solid #222; border-radius:10px; padding:14px; max-height:240px; overflow-y:auto; margin-top:16px; }
.log-area .log-title { color:#888; font-size:12px; margin-bottom:8px; padding-bottom:6px; border-bottom:1px solid #1a1a2e; }
.log-area .log-entry { padding:3px 6px; font-size:13px; color:#ccc; line-height:1.5; border-radius:3px; }
.log-area .log-entry:nth-child(odd) { background:#0d0d1a; }

.overlay { display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,.85); z-index:1000; justify-content:center; align-items:center; }
.overlay.show { display:flex; }
.overlay .result-box { background:linear-gradient(135deg,#1a1a3e,#2a1a3e); border:2px solid #ffd700; border-radius:20px; padding:40px; text-align:center; max-width:450px; }
.overlay .result-box h2 { font-size:32px; margin-bottom:12px; }
.overlay .result-box .good { color:#4CAF50; }
.overlay .result-box .evil { color:#f44336; }
.overlay .result-box p { color:#aaa; font-size:15px; margin-bottom:20px; }
.overlay .result-box button { padding:12px 40px; border:none; border-radius:8px; background:#ffd700; color:#000; font-weight:bold; font-size:15px; cursor:pointer; }

@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.5} }
.playing .phase-name { animation:pulse 1.5s infinite; }

/* ============ 空状态提示 ============ */
.chat-sidebar-empty { text-align:center; color:#555; padding:40px 20px; font-size:13px; line-height:1.8; }
.chat-sidebar-empty .big-icon { font-size:48px; margin-bottom:12px; }

/* ============ 角色配置栏 ============ */
.role-config-bar { background:#111125; border:1px solid #2a2a4e; border-radius:8px; margin-bottom:12px; overflow:hidden; }
.role-config-bar .rc-title { padding:8px 14px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; font-size:13px; color:#aaa; user-select:none; transition:background .15s; }
.role-config-bar .rc-title:hover { background:#1a1a3e; }
.role-config-bar .rc-title span:first-child { color:#ccc; }
.role-config-bar .rc-arrow { font-size:11px; color:#666; transition:transform .2s; }
.role-config-bar .rc-arrow.open { transform:rotate(90deg); }
.role-config-bar .rc-table { display:none; padding:0 14px 10px; }
.role-config-bar .rc-table.show { display:block; }
.role-config-bar .rc-row { display:grid; grid-template-columns:70px repeat(4,1fr); gap:4px; padding:3px 0; font-size:12px; color:#888; text-align:center; }
.role-config-bar .rc-header { color:#ffd700; font-weight:bold; border-bottom:1px solid #2a2a4e; padding-bottom:5px; margin-bottom:2px; }
.role-config-bar .rc-row .tf { color:#7ab8ff; }
.role-config-bar .rc-row .os { color:#a89bff; }
.role-config-bar .rc-row .mi { color:#ff7a7a; }
.role-config-bar .rc-row .de { color:#ff8888; }
.role-config-bar .rc-row.rc-current { background:#1a1a3e; border-radius:4px; font-weight:bold; color:#e0e0e0; }

/* ============ 滚动条 ============ */
::-webkit-scrollbar { width:6px; }
::-webkit-scrollbar-track { background:transparent; }
::-webkit-scrollbar-thumb { background:#333; border-radius:3px; }
::-webkit-scrollbar-thumb:hover { background:#555; }
</style>
</head>
<body>
<div class="header">
    <h1>🕯️ 血染钟楼</h1>
    <div class="info" style="display:flex;align-items:center;gap:10px;">
        <select id="playerSelect" onchange="setPlayerCount(this.value)" style="background:#2a2a5e;color:#ffd700;border:2px solid #ffd700;border-radius:6px;padding:6px 12px;font-size:16px;font-weight:bold;cursor:pointer;">
            <option value="5">5人局</option>
            <option value="6">6人局</option>
            <option value="7" selected>7人局</option>
            <option value="8">8人局</option>
            <option value="9">9人局</option>
            <option value="10">10人局</option>
            <option value="11">11人局</option>
            <option value="12">12人局</option>
        </select>
        <span>暗流涌动</span>
    </div>
</div>
<div class="container">
    <div id="phaseBar" class="phase-bar">
        <div>
            <div id="phaseName" class="phase-name">📋 准备开始</div>
            <div id="phaseDesc" class="phase-desc">点击下方「下一步」逐帧推进游戏</div>
        </div>
        <div class="round" id="roundInfo">🌙 第 <span id="nightCount">0</span> 晚 · ☀️ 第 <span id="dayCount">0</span> 天</div>
    </div>
    <div class="role-config-bar" id="roleConfigBar">
        <div class="rc-title" onclick="toggleRoleConfig()">
            <span id="rcSummary">📋 镇民 5 · 外来者 0 · 爪牙 1 · 恶魔 1</span>
            <span class="rc-arrow" id="rcArrow">▶</span>
        </div>
        <div class="rc-table" id="rcTable">
            <div class="rc-row rc-header">
                <span>玩家数</span><span>镇民</span><span>外来者</span><span>爪牙</span><span>恶魔</span>
            </div>
        </div>
    </div>
    <div class="info-row">
        <div class="info-item">🧑‍🤝‍🧑 存活: <span id="aliveCount">7</span>人</div>
        <div class="info-item">💀 死亡: <span id="deadCount">0</span>人</div>
        <div class="info-item">👿 邪恶存活: <span id="evilCount">-</span>人</div>
    </div>
    <div class="controls">
        <button id="btnStep" class="btn-step" onclick="stepGame()">▶ 下一步</button>
        <button id="btnAuto" class="btn-auto" onclick="toggleAuto()">▶ 自动播放</button>
        <button class="btn-reset" onclick="resetGame()">↻ 新游戏</button>
    </div>

    <!-- 主体布局: 左侧玩家+日志, 右侧聊天 -->
    <div class="main-layout">
        <div class="main-content">
            <div id="playerGrid" class="player-grid"></div>
            <div id="logArea" class="log-area"><div class="log-title">📜 说书人日志</div></div>
        </div>
        <div class="chat-sidebar" id="chatSidebar">
            <div class="chat-panel">
                <div class="panel-header">💬 私聊记录</div>
                <div id="threadList" class="chat-thread-list"></div>
            </div>
            <div id="chatView" class="chat-view">
                <div class="chat-header">
                    <button class="back-btn" onclick="closeChatView()">←</button>
                    <span class="chat-title" id="chatViewTitle">对话</span>
                    <span class="chat-day" id="chatViewDay"></span>
                </div>
                <div id="chatBubbles" class="chat-bubbles"></div>
            </div>
        </div>
    </div>
</div>
<div id="overlay" class="overlay">
    <div class="result-box">
        <h2 id="resultTitle" class="good">🏆 游戏结束</h2>
        <p id="resultDetail">善良阵营获胜！</p>
        <button onclick="closeOverlay()">确定</button>
    </div>
</div>
<script>
let autoPlaying=false, autoTimer=null;
let lastThreadKeys = new Set();
let currentViewKey = null;

function updateBoard(d) {
    document.getElementById('phaseName').textContent = d.phase_name;
    document.getElementById('phaseDesc').textContent = d.phase_desc;
    document.getElementById('dayCount').textContent = d.day_count;
    document.getElementById('nightCount').textContent = d.night_count;
    document.getElementById('aliveCount').textContent = d.alive_count;
    document.getElementById('deadCount').textContent = d.dead_count;
    document.getElementById('evilCount').textContent = d.evil_count;

    let g = document.getElementById('playerGrid'), h='';
    for(let p of d.players) {
        h += '<div class="player-card '+p.status+' '+p.team+'">' +
            '<div class="icon">'+p.icon+'</div>' +
            '<div class="name">'+p.name+'</div>' +
            '<div class="role '+p.team+'">'+p.role+'</div>' +
            '<div class="team">'+p.team_cn+'</div>' +
            '<div class="status '+p.status+'">'+(p.status=='alive'?'存活':'死亡')+'</div>' +
            (p.poisoned?'<div class="poisoned">☠️</div>':'') +
            '</div>';
    }
    g.innerHTML = h;

    let l = document.getElementById('logArea'), lh='<div class="log-title">📜 说书人日志</div>';
    for(let e of d.log) {
        let hled = e.replace(/(玩家\\d+)/g, '<span style="color:#4fc3f7;font-weight:bold;">$1</span>');
        hled = hled.replace(/\\[([^\\]]+)\\]/g, '<span style="color:#ffd700;font-weight:bold;">[$1]</span>');
        lh += '<div class="log-entry">'+hled+'</div>';
    }
    l.innerHTML = lh; l.scrollTop = l.scrollHeight;

    let btn = document.getElementById('btnStep');
    btn.disabled = d.finished;
    btn.textContent = d.finished ? '✓ 游戏结束' : '▶ 下一步';

    // 更新角色配置
    updateRoleConfig(d);

    // 更新私聊线程列表
    updateChatThreads(d.chat_threads);

    if(d.result) {
        setTimeout(() => {
            document.getElementById('overlay').classList.add('show');
            let t = document.getElementById('resultTitle'), dt = document.getElementById('resultDetail');
            if(d.result=='good_win') { t.textContent='🏆 善良阵营获胜！'; t.className='good'; dt.textContent='所有恶魔已被消灭！'; }
            else { t.textContent='💀 邪恶阵营获胜！'; t.className='evil'; dt.textContent='场上只剩两名存活玩家。'; }
        }, 600);
    }
}

function updateChatThreads(threads) {
    let list = document.getElementById('threadList');
    let panel = document.querySelector('.chat-panel');
    let view = document.getElementById('chatView');

    if(!threads || threads.length === 0) {
        list.innerHTML = '<div class="chat-sidebar-empty"><div class="big-icon">💬</div>暂无私聊记录<br><span style="font-size:12px;color:#555;">点击「下一步」推进游戏<br>私聊环节结束后记录会显示在这里</span></div>';
        return;
    }

    // 检测新线程
    let currentKeys = new Set(threads.map(t => t.key));
    let newKeys = [...currentKeys].filter(k => !lastThreadKeys.has(k));
    lastThreadKeys = currentKeys;

    let h = '';
    for(let t of threads) {
        let isNew = newKeys.includes(t.key);
        let isActive = currentViewKey === t.key;
        let preview = t.messages && t.messages.length > 0 ? t.messages[t.messages.length-1].text : '';
        if(preview.length > 30) preview = preview.substring(0, 30) + '…';
        let safeKey = t.key.replace(/'/g, "\\'");
        h += '<div class="thread-item'+(isActive?' active':'')+'" data-key="'+safeKey+'" onclick="openThread(this.dataset.key)">' +
            '<div class="thread-avatars">💬</div>' +
            '<div class="thread-info">' +
            '<div class="thread-pair">'+t.pair+'</div>' +
            '<div class="thread-day">'+t.day+' · '+ (t.messages?.length||0) +' 条消息</div>' +
            '<div class="thread-preview">'+preview+'</div>' +
            '</div>' +
            (isNew?'<span class="unread-badge">新</span>':'') +
            '</div>';
    }
    list.innerHTML = h;

    // 如果有当前打开的线程, 保持内容更新
    if(currentViewKey) {
        let match = threads.find(t => t.key === currentViewKey);
        if(match) {
            renderChatBubbles(match);
        }
    }
}

function openThread(key) {
    currentViewKey = key;
    document.querySelectorAll('.thread-item').forEach(el => el.classList.remove('active'));
    let el = document.querySelector('.thread-item[data-key="'+key+'"]');
    if(el) el.classList.add('active');
    fetch('/state').then(r=>r.json()).then(d => {
        let match = d.chat_threads?.find(t => t.key === key);
        if(match) {
            renderChatBubbles(match);
            document.getElementById('chatView').classList.add('show');
            document.querySelectorAll('.thread-item').forEach(e => {
                e.classList.toggle('active', e.dataset.key === key);
            });
        }
    });
}

function closeChatView() {
    document.getElementById('chatView').classList.remove('show');
    currentViewKey = null;
}

function renderChatBubbles(thread) {
    document.getElementById('chatViewTitle').textContent = thread.pair;
    document.getElementById('chatViewDay').textContent = thread.day;

    let container = document.getElementById('chatBubbles');
    if(!thread.messages || thread.messages.length === 0) {
        container.innerHTML = '<div class="chat-empty">暂无消息</div>';
        return;
    }

    // 识别对话双方, 确定左右
    let speakers = [...new Set(thread.messages.map(m => m.speaker))];
    let leftSpeaker = speakers[0] || '';

    let h = '';
    for(let m of thread.messages) {
        let isLeft = m.speaker === leftSpeaker;
        let rndLabel = m.rnd ? '第'+m.rnd+'轮' : '';
        h += '<div class="chat-bubble '+(isLeft?'left':'right')+'">' +
            '<div class="bubble-speaker">'+m.speaker+'</div>' +
            '<div>'+m.text+'</div>' +
            (rndLabel ? '<div class="bubble-round">'+rndLabel+'</div>' : '') +
            '</div>';
    }
    container.innerHTML = h;
    container.scrollTop = container.scrollHeight;
}

function toggleRoleConfig() {
    let tbl = document.getElementById('rcTable');
    let arr = document.getElementById('rcArrow');
    tbl.classList.toggle('show');
    arr.classList.toggle('open');
}
function updateRoleConfig(d) {
    let cfg = d.role_config;
    let cur = d.current_player_count;
    if(!cfg || !cfg[cur]) return;
    let c = cfg[cur];
    let teamCn = {townsfolk:'镇民',outsider:'外来者',minion:'爪牙',demon:'恶魔'};
    let teamCls = {townsfolk:'tf',outsider:'os',minion:'mi',demon:'de'};
    document.getElementById('rcSummary').textContent =
        '\U0001F4CB 镇民 ' + c.townsfolk + ' \u00B7 外来者 ' + c.outsider + ' \u00B7 爪牙 ' + c.minion + ' \u00B7 恶魔 ' + c.demon;
    let rows = '<div class="rc-row rc-header"><span>玩家数</span><span>镇民</span><span>外来者</span><span>爪牙</span><span>恶魔</span></div>';
    let nums = Object.keys(cfg).map(Number).sort((a,b)=>a-b);
    for(let n of nums) {
        let cc = cfg[n];
        let cls = n === cur ? ' rc-row rc-current' : ' rc-row';
        rows += '<div class="' + cls + '">' +
            '<span>' + n + '人</span>' +
            '<span class="tf">' + cc.townsfolk + '</span>' +
            '<span class="os">' + cc.outsider + '</span>' +
            '<span class="mi">' + cc.minion + '</span>' +
            '<span class="de">' + cc.demon + '</span>' +
            '</div>';
    }
    document.getElementById('rcTable').innerHTML = rows;
}
function stepGame() { fetch('/step',{method:'POST'}).then(r=>r.json()).then(updateBoard); }
function toggleAuto() {
    let btn = document.getElementById('btnAuto');
    if(autoPlaying) { autoPlaying=false; clearInterval(autoTimer); btn.textContent='▶ 自动播放'; btn.style.background='linear-gradient(135deg,#2196F3,#1a88e8)'; }
    else { autoPlaying=true; btn.textContent='⏸ 暂停'; btn.style.background='linear-gradient(135deg,#ff9800,#f57c00)';
        autoTimer=setInterval(()=>{ if(document.getElementById('btnStep').disabled){toggleAuto();return;} stepGame(); },900); }
}
function resetGame() { if(autoPlaying) toggleAuto(); document.getElementById('overlay').classList.remove('show'); fetch('/reset',{method:'POST'}).then(r=>r.json()).then(updateBoard); }
function closeOverlay() { document.getElementById('overlay').classList.remove('show'); }
function setPlayerCount(n) { fetch('/set_players/'+n,{method:'POST'}).then(r=>r.json()).then(updateBoard); }
fetch('/state').then(r=>r.json()).then(updateBoard);
</script>
</body>
</html>"""

@app.route('/')
def index(): return render_template_string(HTML)

@app.route('/state')
def state(): return jsonify(ctrl.get_state())

@app.route('/step', methods=['POST'])
def step(): return jsonify(ctrl.step())

@app.route('/reset', methods=['POST'])
def reset():
    global ctrl; ctrl = GameController(ctrl.num_players)
    return jsonify(ctrl.get_state())

@app.route('/set_players/<int:n>', methods=['POST'])
def set_players(n):
    global ctrl; ctrl = GameController(n)
    return jsonify(ctrl.get_state())

if __name__ == '__main__':
    print('='*50)
    print('  血染钟楼 · 私聊对话框版')
    print('  http://127.0.0.1:5000')
    print('='*50)
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
