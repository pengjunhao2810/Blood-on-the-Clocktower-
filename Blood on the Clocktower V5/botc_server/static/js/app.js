/* 暗流涌动 — Vue3 应用逻辑
 * 通信架构：WebSocket 全双工指令 + 服务器事件广播（无轮询）
 * 协议：客户端 {event, data, id} → 服务端 {event, data} 广播 + {event:"ack", data:{id, ok, message, ...}} 回执
 */
(function () {
    const { createApp, ref, reactive, computed } = Vue;
    const { ElMessage } = ElementPlus;

    // ——— WebSocket 客户端 ———
    const WS = {
        conn: null,
        seq: 0,
        pending: new Map(),
        handlers: {},
        retryDelay: 1000,
        heartbeatTimer: null,

        connect() {
            const proto = location.protocol === 'https:' ? 'wss' : 'ws';
            this.conn = new WebSocket(proto + '://' + location.host + '/ws');
            this.conn.onopen = () => {
                this.retryDelay = 1000;
                if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
                this.heartbeatTimer = setInterval(() => {
                    this.send('heartbeat', {}).catch(() => {});
                }, 30000);
                this.emit('_open', {});
            };
            this.conn.onmessage = (ev) => {
                let msg;
                try { msg = JSON.parse(ev.data); } catch (e) { return; }
                if (msg.event === 'ack') {
                    const p = this.pending.get(msg.data && msg.data.id);
                    if (p) {
                        this.pending.delete(msg.data.id);
                        clearTimeout(p.timer);
                        if (msg.data.ok) p.resolve(msg.data);
                        else p.reject(new Error(msg.data.message || '指令失败'));
                    }
                    return;
                }
                this.emit(msg.event, msg.data);
            };
            this.conn.onclose = () => {
                if (this.heartbeatTimer) { clearInterval(this.heartbeatTimer); this.heartbeatTimer = null; }
                // 未完成的请求全部失败
                this.pending.forEach(p => { clearTimeout(p.timer); p.reject(new Error('连接已断开')); });
                this.pending.clear();
                this.emit('_close', {});
                setTimeout(() => this.connect(), this.retryDelay);
                this.retryDelay = Math.min(this.retryDelay * 2, 8000);
            };
            this.conn.onerror = () => { try { this.conn.close(); } catch (e) {} };
        },

        on(event, fn) {
            (this.handlers[event] = this.handlers[event] || []).push(fn);
            return () => {
                const list = this.handlers[event] || [];
                const i = list.indexOf(fn);
                if (i >= 0) list.splice(i, 1);
            };
        },
        emit(event, data) {
            (this.handlers[event] || []).forEach(fn => { try { fn(data); } catch (e) {} });
        },

        send(event, data) {
            return new Promise((resolve, reject) => {
                const doSend = () => {
                    if (!this.conn || this.conn.readyState !== WebSocket.OPEN) {
                        reject(new Error('连接未就绪'));
                        return;
                    }
                    const id = ++this.seq;
                    const timer = setTimeout(() => {
                        this.pending.delete(id);
                        reject(new Error('指令超时'));
                    }, 8000);
                    this.pending.set(id, { resolve, reject, timer });
                    this.conn.send(JSON.stringify({ event, data: data || {}, id }));
                };
                if (!this.conn || this.conn.readyState !== WebSocket.OPEN) {
                    // 连接未建立：最多等待 5 秒（断线重连窗口内不发错误）
                    let waited = 0;
                    const t = setInterval(() => {
                        waited += 400;
                        if (this.conn && this.conn.readyState === WebSocket.OPEN) {
                            clearInterval(t);
                            doSend();
                        } else if (waited >= 5000) {
                            clearInterval(t);
                            reject(new Error('连接未就绪'));
                        }
                    }, 400);
                    return;
                }
                doSend();
            });
        },
    };

    const api = {
        async post(url, body) {
            const resp = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body || {}),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.message || ('HTTP ' + resp.status));
            return data;
        },
        async get(url) {
            const resp = await fetch(url);
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.message || ('HTTP ' + resp.status));
            return data;
        },
    };

    createApp({
        setup() {
            // ——— 全局状态 ———
            const view = ref('login');
            const user = ref(null);
            const busy = ref(false);
            const loginForm = reactive({ username: '', password: '' });
            const isRegister = ref(false);
            const joinCode = ref('');
            const wsReady = ref(false);

            // 房间
            const roomCode = ref('');
            const room = ref(null);
            const roomMessages = ref([]);
            const chatText = ref('');
            const seatCount = ref(8);

            // 游戏
            const game = ref(null);
            const myNumber = ref(0);
            const pubMsgs = ref([]);
            const gameChatText = ref('');
            const myInfo = ref({ infos: [], my_role: '?', my_team: '?' });
            const stories = ref([]);
            const nightInfo = ref(null);
            const infoDialog = ref(false);
            const overDialog = ref(false);
            const winner = ref('');
            // 战绩与回放
            const statsDialog = ref(false);
            const stats = reactive({ total: 0, wins: 0, win_rate: 0 });
            const myGames = ref([]);
            const replayDialog = ref(false);
            const replay = ref(null);
            async function openStatsPanel() {
                statsDialog.value = true;
                try {
                    const [s, g] = await Promise.all([
                        api.get('/api/stats'),
                        api.get('/api/games'),
                    ]);
                    stats.total = s.data.total || 0;
                    stats.wins = s.data.wins || 0;
                    stats.win_rate = s.data.win_rate || 0;
                    myGames.value = g.data.games || [];
                } catch (e) { toast(e.message, 'error'); }
            }
            async function openReplay(id) {
                try {
                    const d = await api.get('/api/games/' + id + '/replay');
                    replay.value = d.data;
                    replayDialog.value = true;
                } catch (e) { toast(e.message, 'error'); }
            }

            // 好友系统
            const friendDialog = ref(false);
            const friendList = reactive({ friends: [], incoming: [], outgoing: [] });
            const friendSearch = ref('');
            const searchResult = ref(null);
            const inviteDialog = ref(false);
            const inviteIncoming = ref(null);
            const inviteIncomingVisible = computed({
                get: () => inviteIncoming.value !== null,
                set: (v) => { if (!v) inviteIncoming.value = null; },
            });

            // 夜晚行动选择已迁移至公聊定向提示（night_tip 消息），弹窗相关状态全部移除
            let tipCountdownTimer = null;

            // 提名投票状态
            const voteInfo = ref(null); // {from, target, waiting, deadline, debate, debateDeadline}
            const voteCountdown = ref(0);
            const debateCountdown = ref(0);

            // 私聊状态
            const privatePhase = ref(false); // 是否处于私聊阶段
            const privatePanelVisible = ref(false); // 私聊面板是否展开（收起后仍处于阶段中）
            const privateChats = reactive({}); // 对象编号 -> 消息数组
            const privateTarget = ref(null);   // 当前私聊对象编号
            const activePrivateTarget = ref(null); // 私聊模式：非空时聊天面板整体切换为与该玩家的私聊对话
            // 模板用 computed（Vue 3 编译器不支持 v-for 表达式内嵌三元/括号）
            const roomPlayers = computed(() => {
                return (room.value && room.value.players) || [];
            });
            const activePrivateChats = computed(() => {
                if (!activePrivateTarget.value) return [];
                return privateChats[activePrivateTarget.value] || [];
            });
            const privateText = ref('');
            const privatePartners = ref([]);   // 已建立会话的对象编号列表
            const privateInviteWaiting = ref(null); // 我发出的邀请等待中的对象
            const privateIncoming = ref(null); // 我收到的邀请 {from_number}

            const isHost = computed(() => room.value && user.value && room.value.host_id === user.value.id);
            const myReady = computed(() => {
                if (!room.value || !user.value) return false;
                const me = room.value.players.find(p => p.user_id === user.value.id);
                return me ? me.is_ready : false;
            });
            const sortedPlayers = computed(() => {
                if (!game.value || !game.value.players) return [];
                const list = Object.values(game.value.players);
                list.sort((a, b) => a.number - b.number);
                return list;
            });
            function nameOf(n) {
                if (!game.value || !game.value.players) return '';
                for (const pid in game.value.players) {
                    const p = game.value.players[pid];
                    if (p.number === n) return p.is_ai ? (p.ai_model || 'AI 玩家') : p.username;
                }
                return '';
            }
            const phaseLabel = computed(() => {
                const ph = game.value ? game.value.phase : 'waiting';
                const map = {
                    waiting: '等待', night: '🌙 夜晚', day: '🌅 黎明',
                    public_chat: '💬 公聊', private_chat: '🤫 私聊', nomination: '⚖️ 提名',
                };
                return map[ph] || ph;
            });
            const phaseTagClass = computed(() => {
                const ph = game.value ? game.value.phase : '';
                if (ph === 'night') return 'tag';
                if (ph === 'nomination') return 'tag tag-red';
                return 'tag tag-yellow';
            });
            const aliveCount = computed(() => {
                if (!game.value || !game.value.players) return 0;
                return Object.values(game.value.players).filter(p => p.alive).length;
            });
            // 公聊发言权：黑夜禁言；辩论期仅提名双方可发言；其余时间可发言
            const canSpeakNow = computed(() => {
                if (!game.value) return true;
                if (game.value.phase === 'night') return false;
                const av = game.value.active_vote;
                if (game.value.phase === 'nomination' && av && !av.vote_deadline) {
                    return myNumber.value === av.from || myNumber.value === av.target;
                }
                return true;
            });
            // 黑夜消息过滤：黑夜只渲染夜间行动系统卡片，屏蔽普通聊天（消息上下文隔离）
            const visibleMsgs = computed(() => {
                if (game.value && game.value.phase === 'night') {
                    return pubMsgs.value.filter(m => m.nightTip);
                }
                return pubMsgs.value;
            });
            const teamName = computed(() => {
                const t = myInfo.value.my_team;
                return { townsfolk: '镇民·善良', outsider: '外来者·善良', minion: '爪牙·邪恶', demon: '恶魔·邪恶' }[t] || '?';
            });

            function toast(msg, type) {
                ElMessage({ message: msg, type: type || 'info', duration: 2500 });
            }
            function scrollMsgs() {
                requestAnimationFrame(() => {
                    const el = document.getElementById('game-msgs');
                    if (el) el.scrollTop = el.scrollHeight;
                });
            }

            // ——— 认证（HTTP） ———
            async function doLogin() {
                if (busy.value) return;
                busy.value = true;
                try {
                    const url = isRegister.value ? '/api/auth/register' : '/api/auth/login';
                    const d = await api.post(url, { username: loginForm.username.trim(), password: loginForm.password });
                    user.value = d.data.user;
                    view.value = 'lobby';
                    WS.connect();
                    toast(isRegister.value ? '注册成功' : '欢迎回来', 'success');
                } catch (e) {
                    toast(e.message, 'error');
                } finally {
                    busy.value = false;
                }
            }
            async function doLogout() {
                await api.post('/api/auth/logout').catch(() => {});
                view.value = 'login';
                user.value = null;
            }

            // ——— 大厅（HTTP 建房 + WS 加入） ———
            async function createRoom() {
                if (busy.value) return;
                busy.value = true;
                try {
                    const d = await api.post('/api/room/create');
                    enterRoom(d.data.room.room_code);
                } catch (e) { toast(e.message, 'error'); } finally { busy.value = false; }
            }
            async function joinRoomByCode() {
                if (!joinCode.value || busy.value) return;
                busy.value = true;
                const code = joinCode.value.toUpperCase();
                try {
                    await enterRoom(code);
                } catch (e) {
                    roomCode.value = '';
                    view.value = 'lobby';
                } finally { busy.value = false; }
            }

            // ——— 房间（WS 指令 + 事件） ———
            function ensureWS() {
                return new Promise((resolve, reject) => {
                    if (WS.conn && WS.conn.readyState === WebSocket.OPEN) { resolve(); return; }
                    const timer = setTimeout(() => { off(); reject(new Error('连接服务器超时')); }, 8000);
                    const off = WS.on('_open', () => { clearTimeout(timer); off(); resolve(); });
                });
            }
            async function enterRoom(code) {
                roomCode.value = code;
                room.value = null;
                roomMessages.value = [];
                view.value = 'room';
                try {
                    await ensureWS();
                    const ack = await joinRoomWS();
                    applyRoomState(ack.state);
                    sessionStorage.setItem('botc_room', code);
                } catch (e) {
                    toast(e.message, 'error');
                    throw e;
                }
            }
            async function joinRoomWS() {
                const ack = await WS.send('room.join', { room_code: roomCode.value });
                applyRoomState(ack.state);
                return ack;
            }
            function applyRoomState(snap) {
                if (!snap) return;
                room.value = snap.room;
                roomMessages.value = snap.messages || [];
                seatCount.value = snap.room.max_players;
            }
            async function sendRoomMsg() {
                const txt = chatText.value.trim();
                if (!txt) return;
                chatText.value = '';
                try {
                    await WS.send('room.chat', { room_code: roomCode.value, content: txt });
                } catch (e) { toast(e.message, 'error'); }
            }
            async function toggleReady() {
                try {
                    await WS.send('room.ready', { room_code: roomCode.value });
                } catch (e) { toast(e.message, 'error'); }
            }
            async function addAI(type) {
                try {
                    await WS.send('room.add_ai', { room_code: roomCode.value, ai_type: type });
                } catch (e) { toast(e.message, 'error'); }
            }
            // 一键假人凑人数：填充到设定人数（至少 5 人）直接开局
            async function fillBots() {
                try {
                    const ack = await WS.send('room.fill_bots', { room_code: roomCode.value });
                    toast('已添加 ' + (ack.added || 0) + ' 个假人，可以直接开始对局', 'success');
                } catch (e) { toast(e.message, 'error'); }
            }
            // 一键补满假人（本地 AI）到最少 5 人并直接开局
            async function fillAndStart() {
                try {
                    const total = room.value ? room.value.player_count : 0;
                    const need = Math.max(0, 5 - total);
                    for (let i = 0; i < need; i++) {
                        await WS.send('room.add_ai', { room_code: roomCode.value, ai_type: 'local' });
                    }
                    toast('已补齐 ' + need + ' 个假人，正在开局…', 'success');
                    await startGame();
                } catch (e) { toast(e.message, 'error'); }
            }
            // 大模型 AI 弹窗：手动输入 API 配置（服务商预设 + 自定义）
            const llmDialog = ref(false);
            const llmPresets = [
                { key: 'deepseek', label: 'DeepSeek（官方）', base_url: 'https://api.deepseek.com', model: 'deepseek-chat', needKey: true },
                { key: 'siliconflow', label: '硅基流动（有免费额度）', base_url: 'https://api.siliconflow.cn/v1', model: 'Qwen/Qwen2.5-7B-Instruct', needKey: true },
                { key: 'zhipu', label: '智谱 GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash', needKey: true },
                { key: 'moonshot', label: '月之暗面 Kimi', base_url: 'https://api.moonshot.cn/v1', model: 'kimi-k2.6', needKey: true },
                { key: 'dashscope', label: '阿里通义（百炼）', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-turbo', needKey: true },
                { key: 'hunyuan', label: '腾讯混元', base_url: 'https://api.hunyuan.cloud.tencent.com/v1', model: 'hunyuan-lite', needKey: true },
                { key: 'groq', label: 'Groq（高速免费额度）', base_url: 'https://api.groq.com/openai/v1', model: 'llama-3.3-70b-versatile', needKey: true },
                { key: 'openrouter', label: 'OpenRouter（有免费模型）', base_url: 'https://openrouter.ai/api/v1', model: 'deepseek/deepseek-chat-v3-0324:free', needKey: true },
                { key: 'ollama', label: 'Ollama 本地（免费离线）', base_url: 'http://127.0.0.1:11434/v1', model: 'qwen2.5:7b', needKey: false },
            ];
            const llmForm = reactive({ provider: 'deepseek', api_key: '', base_url: '', model: '' });
            const usage = ref(null);
            const roomUsage = computed(() => {
                if (!usage.value || !usage.value.rooms) return null;
                return usage.value.rooms[roomCode.value] || null;
            });
            function fmtTokens(n) {
                n = Number(n) || 0;
                if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
                if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
                return String(n);
            }
            async function fetchUsage() {
                try {
                    const r = await api.get('/api/ai_usage');
                    usage.value = r.data;
                } catch (e) { usage.value = null; }
            }
            function openLlmDialog() {
                pickLlmPreset('deepseek');
                llmDialog.value = true;
                fetchUsage();
            }
            function pickLlmPreset(key) {
                const pr = llmPresets.find(p => p.key === key);
                if (!pr) return;
                llmForm.provider = key;
                llmForm.base_url = pr.base_url;
                llmForm.model = pr.model;
                if (!pr.needKey) llmForm.api_key = '';
            }
            async function confirmAddLlmAI() {
                if (!llmForm.api_key && llmForm.provider !== 'ollama') {
                    toast('请填写 API Key（或选择 Ollama 本地模型）', 'error');
                    return;
                }
                // 先测试连通性：Key/端点不可用立即提示，避免添加后 AI 一直沉默
                try {
                    const ping = await api.post('/api/llm_ping', {
                        llm_conf: JSON.stringify({
                            api_key: llmForm.api_key,
                            base_url: llmForm.base_url,
                            model: llmForm.model,
                        }),
                    });
                    if (!ping.data.ok) {
                        toast('API 测试失败：' + (ping.data.error || '未知错误'), 'error');
                        return;
                    }
                    toast('✅ API 连通正常（' + (ping.data.model || '') + '）', 'success');
                } catch (e) {
                    toast('AI 服务不可用：' + e.message, 'error');
                    return;
                }
                try {
                    await WS.send('room.add_ai', {
                        room_code: roomCode.value,
                        ai_type: 'api',
                        api_key: llmForm.api_key,
                        base_url: llmForm.base_url,
                        model: llmForm.model,
                    });
                    llmDialog.value = false;
                    toast('已添加大模型 AI 玩家', 'success');
                } catch (e) { toast(e.message, 'error'); }
            }
            async function removeAI(seat) {
                try {
                    await WS.send('room.remove_ai', { room_code: roomCode.value, seat });
                } catch (e) { toast(e.message, 'error'); }
            }
            // 房主踢出真人玩家（仅等待房间）
            async function kickPlayer(userId) {
                try {
                    await WS.send('room.kick', { room_code: roomCode.value, user_id: userId });
                    toast('已将该玩家移出房间', 'success');
                } catch (e) { toast(e.message, 'error'); }
            }
            async function setSeats() {
                try {
                    await WS.send('room.set_seats', { room_code: roomCode.value, max_players: seatCount.value });
                } catch (e) { toast(e.message, 'error'); }
            }
            async function startGame() {
                if (busy.value) return;
                busy.value = true;
                try {
                    await WS.send('room.start', { room_code: roomCode.value });
                } catch (e) { toast(e.message, 'error'); } finally { busy.value = false; }
            }
            async function leaveRoom() {
                leaveGameView();
                try {
                    await WS.send('room.leave', { room_code: roomCode.value });
                } catch (e) { /* 忽略 */ }
                sessionStorage.removeItem('botc_room');
                view.value = 'lobby';
                room.value = null;
            }
            // 复制房间邀请链接（房码直链，好友打开后自动填入房码）
            async function copyRoomLink() {
                const url = location.origin + location.pathname + '#join=' + roomCode.value;
                try {
                    await navigator.clipboard.writeText(url);
                    toast('邀请链接已复制：' + url, 'success');
                } catch (e) {
                    toast('房间码 ' + roomCode.value + '（请手动告知好友）', 'info');
                }
            }

            // ——— 游戏（WS 指令 + 事件） ———
            function enterGame() {
                game.value = null;
                pubMsgs.value = [];
                stories.value = [];
                myInfo.value = { infos: [], my_role: '?', my_team: '?' };
                overDialog.value = false;
                nightInfo.value = null;
                enterGameState();
            }
            function enterGameState() {
                view.value = 'game';
                loadMyInfo();
                startChoicePoll();
            }
            function leaveGameView() {
                stopChoicePoll();
            }
            // 轮询兜底（双通道）：3 秒查一次挂起选择，WS 事件/WS 查询/HTTP 查询任一可用都能弹面板
            let choicePollTimer = null;
            function startChoicePoll() {
                stopChoicePoll();
                const check = async () => {
                    if (view.value !== 'game' || !roomCode.value) return;
                    let pc = null;
                    let myN = myNumber.value;
                    // 通道 1：WS 查询
                    try {
                        const ack = await WS.send('game.my_info', { room_code: roomCode.value });
                        pc = ack.pending_choice;
                        if (ack.my_number) myN = ack.my_number;
                    } catch (e) { /* WS 不可用，走 HTTP */ }
                    // 通道 2：HTTP 查询（与 WS 完全独立）
                    if (!pc) {
                        try {
                            const d = await api.get('/api/game/' + roomCode.value + '/pending');
                            pc = d.data.pending_choice;
                            if (d.data.my_number) myN = d.data.my_number;
                        } catch (e) { /* 忽略 */ }
                    }
                    if (pc && myN && pc.number === myN) {
                        addNightTip({
                            number: pc.number, role: pc.role, role_name: pc.role_name,
                            valid_targets: pc.valid_targets || [],
                            max_targets: pc.max_targets || 2,
                            deadline: pc.deadline,
                            tip_id: pc.tip_id,
                        });
                    }
                };
                check();
                choicePollTimer = setInterval(check, 3000);
            }
            function stopChoicePoll() {
                if (choicePollTimer) { clearInterval(choicePollTimer); choicePollTimer = null; }
            }
            async function loadMyInfo() {
                try {
                    const ack = await WS.send('game.my_info', { room_code: roomCode.value });
                    myInfo.value = {
                        infos: ack.infos || [],
                        my_role: ack.my_role || '?',
                        my_team: ack.my_team || '?',
                        my_number: ack.my_number || myNumber.value,
                    };
                    if (ack.my_number) myNumber.value = ack.my_number;
                } catch (e) { /* 忽略 */ }
            }
            function applyGameState(snap) {
                if (!snap || !snap.game) return;
                game.value = snap.game;
                // 性能优化：消息增量合并（只追加新增消息，避免全量替换触发整列重渲染）
                const old = pubMsgs.value;
                // 保留本地卡片（夜间行动/投票/投票结果仅本端存在，快照覆盖时不得丢失）
                const cards = old.filter(m => m.nightTip || m.voteCard || m.voteResultCard || m.nominateCard || m.nominateResultCard);
                const incoming = snap.messages || [];
                if (cards.length) {
                    pubMsgs.value = [...cards, ...incoming];
                } else {
                    const exist = new Set(old.map(m => m.id));
                    const fresh = incoming.filter(m => !exist.has(m.id));
                    if (fresh.length) {
                        pubMsgs.value = [...old, ...fresh].slice(-500);
                    } else if (incoming.length < old.length) {
                        pubMsgs.value = incoming;
                    }
                }
                const me = Object.values(snap.game.players).find(p => p.user_id === user.value.id);
                if (me) myNumber.value = me.number;
                // 断线重连恢复：按相位恢复聊天状态
                const ph = snap.game.phase;
                if (ph === 'private_chat' && !privatePhase.value) {
                    enterPrivatePhase();
                } else if (ph !== 'private_chat' && privatePhase.value) {
                    leavePrivatePhase();
                }
                // 断线重连恢复：挂起的真人行动 → 公聊消息流恢复定向提示（不弹面板）
                const pc = snap.game.pending_choice;
                if (pc && myNumber.value && pc.number === myNumber.value) {
                    addNightTip({
                        number: pc.number, role: pc.role, role_name: pc.role_name,
                        valid_targets: pc.valid_targets || [],
                        max_targets: pc.max_targets || 2,
                        deadline: pc.deadline,
                        tip_id: pc.tip_id,
                    });
                }
                // 注意：不再在前端自行判定"挂起已解除→置过期"；
                // 卡片状态只由服务端事件驱动（提交 ack / 超时 phase 事件带 tip_id → markTipDone）
            }
            async function sendGameMsg() {
                // 私聊模式：消息走一对一私聊通道，不进公聊
                if (activePrivateTarget.value) {
                    const txt = gameChatText.value.trim();
                    if (!txt) return;
                    gameChatText.value = '';
                    try {
                        await WS.send('game.private_chat', { room_code: roomCode.value, to_number: activePrivateTarget.value, content: txt });
                    } catch (e) { toast(e.message, 'error'); }
                    return;
                }
                const txt = gameChatText.value.trim();
                if (!txt) return;
                // 挂起中：纯数字序列（如"2 5"）→ 解析为夜晚行动选择提交
                const activeTip = pubMsgs.value.find(m => m.nightTip && m.nightTip.active);
                if (activeTip) {
                    const nums = tryParseChoiceInput(txt);
                    if (nums) {
                        gameChatText.value = '';
                        activeTip.nightTip.selected = [...nums];
                        await submitTipChoice(activeTip);
                        return;
                    }
                }
                gameChatText.value = '';
                try {
                    await WS.send('game.chat', { room_code: roomCode.value, content: txt });
                } catch (e) { toast(e.message, 'error'); }
            }
            async function nextPhase() {
                try {
                    const ack = await WS.send('game.next_phase', { room_code: roomCode.value });
                    applyPhaseResult(ack);
                } catch (e) { toast(e.message, 'error'); }
            }
            function applyPhaseResult(d) {
                // 面板只由「提交成功」和「倒计时归零」关闭，中间广播一律不得关闭
                // （超时兜底广播 phase=night 时倒计时 tick 会自行关闭面板）
                if (d.game_over) {
                    winner.value = d.winner;
                    overDialog.value = true;
                }
                if (d.role_name) {
                    nightInfo.value = { role_name: d.role_name, step: d.step, total: d.total };
                } else if (d.phase !== 'night') {
                    nightInfo.value = null;
                }
                // 私聊阶段：进入/退出控制
                if (d.phase === 'private_chat') {
                    enterPrivatePhase();
                } else if (d.phase !== 'private_chat' && privatePhase.value) {
                    leavePrivatePhase();
                }
                // 夜晚行动提交/超时事件：更新对应卡片状态（不新增消息）
                if (d.tip_id) {
                    markTipDone(d);
                }
            }
            // 夜间行动定向提示（仅自己可见）：在公聊消息流内渲染选择按钮，不再弹独立面板
            let tipSeq = 0;
            function addNightTip(d) {
                // 后端必须下发唯一 tip_id（取自 pending_choice 唯一标识）；缺失则报错并放弃渲染
                if (!d.tip_id) {
                    console.error('[night_tip] 缺少 tip_id，放弃渲染卡片:', d);
                    return;
                }
                // 幂等去重：消息根层级 tip_id 相同 → 只渲染一次（提交/超时后永久拦截）
                if (pubMsgs.value.some(m => m.tip_id === d.tip_id)) return;
                // 超时以"卡片送达时刻"为起点：deadline 已过期时重新给 45 秒操作窗口（秒级整数时间戳）
                const now = Math.floor(Date.now() / 1000);
                const rawDeadline = Math.floor(d.deadline || 0);
                const deadline = rawDeadline > now ? rawDeadline : now + 45;
                pubMsgs.value.push({
                    id: 'tip' + (++tipSeq),
                    tip_id: d.tip_id, // 去重标识挂在消息根层级
                    number: 0, system: true,
                    content: '🔮 夜晚行动：' + (d.role_name || '角色') + ' 请选择 ' + (d.max_targets || 2) + ' 名目标',
                    nightTip: {
                        role: d.role, role_name: d.role_name,
                        targets: d.valid_targets || d.targets || [],
                        max_targets: d.max_targets || 2,
                        deadline,
                        selected: [], done: false, expired: false, active: true,
                        left: Math.max(0, deadline - now),
                    },
                });
                // TODO(并行行动): 当前夜晚角色串行执行，全局 tipCountdownTimer 暂时可用；
                // 未来支持并行角色行动时，必须改为每个 tip 卡片持有独立定时器，禁止共用全局 tipCountdownTimer。
                console.log('[tip-debug] addNightTip push tip_id=' + d.tip_id + ' deadline=' + deadline + ' now=' + now + ' left=' + Math.max(0, deadline - now));
                // 倒计时仅用于展示：归零不置 expired（与投票卡片一致，状态只由服务端事件驱动）
                if (tipCountdownTimer) clearInterval(tipCountdownTimer);
                const tick = () => {
                    let anyActive = false;
                    for (const m of pubMsgs.value) {
                        const t = m.nightTip;
                        if (!t || !t.active) continue;
                        anyActive = true;
                        t.left = Math.max(0, Math.floor(t.deadline - Date.now() / 1000));
                    }
                    if (!anyActive) clearInterval(tipCountdownTimer);
                };
                tick();
                tipCountdownTimer = setInterval(tick, 500);
            }
            // 收到后端 tip_id 对应的提交/超时事件 → 更新已有卡片状态（不新增消息）
            function markTipDone(d) {
                if (!d.tip_id) return;
                for (const m of pubMsgs.value) {
                    if (m.tip_id === d.tip_id && m.nightTip) {
                        console.log('[tip-debug] markTipDone tip_id=' + d.tip_id + ' timeout=' + (d.timeout || false));
                        m.nightTip.active = false;
                        if (d.timeout) m.nightTip.expired = true;
                        else m.nightTip.done = true;
                    }
                }
            }
            function toggleTipTarget(m, n) {
                const t = m.nightTip;
                const idx = t.selected.indexOf(n);
                if (idx >= 0) { t.selected.splice(idx, 1); return; }
                if (t.selected.length >= t.max_targets) {
                    toast('最多选择 ' + t.max_targets + ' 名玩家', 'info');
                    return;
                }
                t.selected.push(n);
            }
            async function submitTipChoice(m) {
                const t = m.nightTip;
                if (t.done || t.expired || t.selected.length !== t.max_targets) {
                    toast('还需选择 ' + (t.max_targets - t.selected.length) + ' 名目标才能确认', 'info');
                    return;
                }
                try {
                    await WS.send('game.submit_choice', { room_code: roomCode.value, targets: [...t.selected] });
                    t.done = true;
                    t.active = false;
                    toast('已提交选择，等待夜晚继续…', 'success');
                } catch (e) {
                    // 挂起已解除（超时代选/重复提交）
                    t.expired = true;
                    t.active = false;
                    toast(e.message, 'error');
                }
            }
            // 输入框数字提交：挂起中发送纯数字序列（如"2 5"）→ 解析为目标提交
            function tryParseChoiceInput(txt) {
                const parts = txt.trim().split(/\s+/).map(s => parseInt(s, 10));
                if (parts.length && parts.every(n => !isNaN(n) && n > 0)) return parts;
                return null;
            }
            // 左侧玩家列表点击：私聊阶段 → 邀请/进入私聊；提名阶段 → 提名
            function clickPlayer(p) {
                if (!p.alive) { toast('死亡玩家无法操作', 'info'); return; }
                if (p.number === myNumber.value) return;
                const ph = game.value && game.value.phase;
                if (ph === 'private_chat') {
                    // 已建立会话 → 直接进入私聊模式；否则发起邀请
                    if (privatePartners.value.includes(p.number)) {
                        activePrivateTarget.value = p.number;
                        if (!privateChats[p.number]) privateChats[p.number] = [];
                    } else {
                        invitePrivate(p.number);
                    }
                    return;
                }
                if (ph === 'nomination') { nominate(p.number); return; }
                toast('当前阶段不可操作', 'info');
            }
            async function nominate(num) {
                try {
                    await WS.send('game.nominate', { room_code: roomCode.value, target_number: num });
                } catch (e) { toast(e.message, 'error'); }
            }
            async function endGame() {
                try {
                    await WS.send('game.end', { room_code: roomCode.value });
                } catch (e) { toast(e.message, 'error'); }
            }
            // ——— 提名投票 ———
            async function castVote(choice) {
                const card = pubMsgs.value.find(m => m.voteCard && !m.voteCard.done);
                if (!card) { toast('当前没有进行中的投票', 'info'); return; }
                try {
                    const ack = await WS.send('game.vote', { room_code: roomCode.value, choice });
                    // 倒计时内可反复切换意向：更新本地卡片的投票状态
                    card.voteCard.mine = ack.choice === 'yes';
                    if (ack.choice === 'yes') toast('已投票，倒计时结束前可取消', 'success');
                    else toast('已取消投票', 'info');
                } catch (e) { toast(e.message, 'error'); }
            }
            async function endNomination() {
                try {
                    await WS.send('game.end_nomination', { room_code: roomCode.value });
                } catch (e) { toast(e.message, 'error'); }
            }
            // ——— 私聊 ———
            function enterPrivatePhase() {
                privatePhase.value = true;
                privatePanelVisible.value = true;
                for (const k in privateChats) delete privateChats[k];
                privateTarget.value = null;
                privateText.value = '';
                privatePartners.value = [];
                privateInviteWaiting.value = null;
                privateIncoming.value = null;
            }
            function leavePrivatePhase() {
                // 完全离开私聊阶段（相位切换时由 applyPhaseResult 调用）
                privatePhase.value = false;
                privatePanelVisible.value = false;
                privateIncoming.value = null;
                privateInviteWaiting.value = null;
                activePrivateTarget.value = null;
            }
            // 收起私聊面板：阶段计时继续，顶部标签可重新打开
            function collapsePrivatePanel() {
                privatePanelVisible.value = false;
            }
            function openPrivatePanel() {
                privatePanelVisible.value = true;
            }
            function pickPrivateTarget(n) {
                privateTarget.value = n;
                if (!privateChats[n]) privateChats[n] = [];
            }
            // 找人私聊：发起邀请
            async function invitePrivate(n) {
                try {
                    const ack = await WS.send('game.private_invite', { room_code: roomCode.value, to_number: n });
                    if (ack.auto_accept) {
                        // AI 自动接受
                        privatePartners.value = [...new Set([...privatePartners.value, ack.partner])];
                        privateTarget.value = ack.partner;
                        if (!privateChats[ack.partner]) privateChats[ack.partner] = [];
                        toast('# ' + ack.partner + ' 接受了你的私聊邀请', 'success');
                    } else {
                        privateInviteWaiting.value = ack.partner;
                        toast('已向 #' + ack.partner + ' 发出私聊邀请，等待接受…', 'info');
                    }
                } catch (e) { toast(e.message, 'error'); }
            }
            // 被邀请私聊：接受 → 直接进入私聊模式
            async function acceptPrivate() {
                if (!privateIncoming.value) return;
                const from = privateIncoming.value.from_number;
                try {
                    await WS.send('game.private_accept', { room_code: roomCode.value });
                    privateIncoming.value = null;
                    privatePartners.value = [...new Set([...privatePartners.value, from])];
                    privateTarget.value = from;
                    if (!privateChats[from]) privateChats[from] = [];
                    activePrivateTarget.value = from; // 聊天面板切换为私聊对话
                    toast('你已接受 #' + from + ' 的私聊，聊天区已切换为私聊', 'success');
                } catch (e) { toast(e.message, 'error'); }
            }
            // 退出私聊模式：返回公聊视图（会话保留）
            function exitPrivateChat() {
                activePrivateTarget.value = null;
                toast('已返回公聊', 'info');
            }
            // 被邀请私聊：拒绝
            async function declinePrivate() {
                if (!privateIncoming.value) return;
                try {
                    await WS.send('game.private_decline', { room_code: roomCode.value });
                    privateIncoming.value = null;
                    toast('已拒绝私聊邀请', 'info');
                } catch (e) { toast(e.message, 'error'); }
            }
            async function sendPrivateMsg() {
                const txt = privateText.value.trim();
                if (!txt || !privateTarget.value) return;
                const to = privateTarget.value;
                try {
                    // 只发送 WS：消息渲染统一由 game.private_message 事件处理（避免本地 push + 事件推送重复）
                    await WS.send('game.private_chat', { room_code: roomCode.value, to_number: to, content: txt });
                    privateText.value = '';
                } catch (e) { toast(e.message, 'error'); }
            }
            async function skipPrivate() {
                try {
                    await WS.send('game.skip_private', { room_code: roomCode.value });
                } catch (e) { toast(e.message, 'error'); }
            }
            function backToRoom() {
                overDialog.value = false;
                leaveGameView();
                view.value = 'room';
            }

            // ——— 好友系统（E 模块） ———
            async function openFriendPanel() {
                friendDialog.value = true;
                searchResult.value = null;
                friendSearch.value = '';
                await refreshFriendList();
            }
            async function refreshFriendList() {
                try {
                    const ack = await WS.send('friend.list', {});
                    friendList.friends = ack.friends || [];
                    friendList.incoming = ack.incoming || [];
                    friendList.outgoing = ack.outgoing || [];
                } catch (e) { /* 忽略 */ }
            }
            async function doFriendSearch() {
                const kw = friendSearch.value.trim();
                if (!kw) return;
                try {
                    const ack = await WS.send('friend.search', { username: kw });
                    searchResult.value = { user: ack.user, friendship_status: ack.friendship_status };
                } catch (e) { searchResult.value = null; toast(e.message, 'error'); }
            }
            async function sendFriendRequest(uid) {
                try {
                    await WS.send('friend.request', { friend_id: uid });
                    toast('好友申请已发送', 'success');
                    await doFriendSearch();
                    await refreshFriendList();
                } catch (e) { toast(e.message, 'error'); }
            }
            async function acceptFriend(uid) {
                try {
                    await WS.send('friend.accept', { friend_id: uid });
                    toast('已添加为好友', 'success');
                    await refreshFriendList();
                } catch (e) { toast(e.message, 'error'); }
            }
            async function rejectFriend(uid) {
                try {
                    await WS.send('friend.reject', { friend_id: uid });
                    await refreshFriendList();
                } catch (e) { toast(e.message, 'error'); }
            }
            async function removeFriend(uid) {
                try {
                    await WS.send('friend.remove', { friend_id: uid });
                    toast('已删除好友', 'info');
                    await refreshFriendList();
                } catch (e) { toast(e.message, 'error'); }
            }
            async function openInviteDialog() {
                await refreshFriendList();
                inviteDialog.value = true;
            }
            async function sendInvite(uid) {
                try {
                    await WS.send('room.invite_friend', { room_code: roomCode.value, friend_id: uid });
                    toast('邀请已发送', 'success');
                } catch (e) { toast(e.message, 'error'); }
            }
            async function acceptInvite() {
                if (!inviteIncoming.value) return;
                const code = inviteIncoming.value.room_code;
                try {
                    const ack = await WS.send('room.invite_accept', { room_code: code });
                    inviteIncoming.value = null;
                    roomCode.value = code;
                    applyRoomState(ack.state);
                    sessionStorage.setItem('botc_room', code);
                    view.value = 'room';
                    toast('已加入房间', 'success');
                } catch (e) {
                    inviteIncoming.value = null;
                    toast(e.message, 'error');
                }
            }
            async function rejectInvite() {
                if (!inviteIncoming.value) return;
                const code = inviteIncoming.value.room_code;
                inviteIncoming.value = null;
                try { await WS.send('room.invite_reject', { room_code: code }); } catch (e) { /* 忽略 */ }
            }

            // ——— WS 事件订阅 ———
            WS.on('_open', () => {
                wsReady.value = true;
                // 断线重连后自动恢复当前房间状态
                if ((view.value === 'room' || view.value === 'game') && roomCode.value) {
                    joinRoomWS().then(ack => {
                        if (ack.state) applyRoomState(ack.state);
                        if (ack.game && ack.game.game && view.value === 'game') applyGameState(ack.game);
                    }).catch(() => {});
                }
            });
            WS.on('_close', () => { wsReady.value = false; });

            WS.on('room.state', (d) => {
                if (view.value === 'room') applyRoomState(d);
            });
            WS.on('room.message', (d) => {
                if (view.value === 'room') roomMessages.value.push(d);
            });
            WS.on('room.disbanded', () => {
                if (view.value === 'room') {
                    sessionStorage.removeItem('botc_room');
                    view.value = 'lobby';
                    room.value = null;
                    toast('房间已解散', 'info');
                }
            });
            WS.on('room.kicked', () => {
                sessionStorage.removeItem('botc_room');
                room.value = null;
                roomCode.value = '';
                view.value = 'lobby';
                toast('你已被房主移出房间', 'warning');
            });
            WS.on('game.started', () => {
                if (roomCode.value) enterGame();
            });
            WS.on('game.state', (d) => {
                if (view.value === 'game') applyGameState(d);
            });
            WS.on('game.state_update', (d) => {
                if (view.value === 'game' && game.value) {
                    game.value.phase = d.phase;
                    game.value.day = d.day;
                    if (d.players) game.value.players = d.players;
                }
            });
            WS.on('game.phase', (d) => {
                if (view.value === 'game') applyPhaseResult(d);
            });
            WS.on('game.message', (d) => {
                if (view.value === 'game') {
                    pubMsgs.value.push(d);
                    scrollMsgs();
                }
            });
            WS.on('game.nominate', (d) => {
                if (view.value !== 'game') return;
                if (d.special) {
                    toast(d.message, 'info');
                    return;
                }
                // 提名/辩论信息由系统消息与投票条展示，不再弹窗
            });
            WS.on('game.story', (d) => {
                stories.value.push(d.content);
                if (stories.value.length > 100) stories.value = stories.value.slice(-100);
            });
            WS.on('game.over', (d) => {
                winner.value = d.winner;
                overDialog.value = true;
            });
            WS.on('room.ended', (d) => {
                if (view.value === 'game') {
                    view.value = 'room';
                    toast('对局已结束', 'info');
                }
            });

            // ——— 好友系统事件（E 模块） ———
            WS.on('friend.request', (d) => {
                toast(d.username + ' 申请加你为好友，去好友面板处理', 'info');
                if (friendDialog.value) refreshFriendList();
            });
            WS.on('friend.accepted', (d) => {
                toast('你和 ' + d.username + ' 已成为好友', 'success');
                if (friendDialog.value) refreshFriendList();
            });
            WS.on('friend.removed', (d) => {
                toast(d.username + ' 删除了你们的好友关系', 'info');
                if (friendDialog.value) refreshFriendList();
            });
            WS.on('friend.online', (d) => {
                const target = friendList.friends.find(f => f.user_id === d.user_id);
                if (target) target.is_online = d.is_online;
            });
            WS.on('room.invite', (d) => {
                inviteIncoming.value = { room_code: d.room_code, from: d.from };
            });
            WS.on('game.night_tip', (d) => {
                if (view.value !== 'game') return;
                addNightTip(d);
                // 确认收到卡片：服务端从此刻重新计时，并同步更新本地卡片倒计时
                WS.send('game.tip_ack', { room_code: roomCode.value }).then(ack => {
                    if (ack && ack.deadline) {
                        for (const m of pubMsgs.value) {
                            if (m.tip_id === d.tip_id && m.nightTip) {
                                m.nightTip.deadline = ack.deadline;
                                m.nightTip.left = Math.max(0, Math.floor(ack.deadline - Date.now() / 1000));
                            }
                        }
                    }
                }).catch(() => {});
            });
            // ——— 提名投票事件 ———
            let voteCountdownTimer = null;
            let cooldownTimer = null;
            function startVoteCountdown() {
                if (voteCountdownTimer) clearInterval(voteCountdownTimer);
                const tick = () => {
                    let any = false;
                    for (const m of pubMsgs.value) {
                        if (m.voteCard && !m.voteCard.done) {
                            any = true;
                            m.voteCard.left = Math.max(0, Math.floor(m.voteCard.deadline - Date.now() / 1000));
                        }
                    }
                    if (!any) clearInterval(voteCountdownTimer);
                };
                tick();
                voteCountdownTimer = setInterval(tick, 400);
            }
            WS.on('game.nominate', (d) => {
                if (view.value !== 'game') return;
                if (d.special) {
                    toast(d.message, 'info');
                    return;
                }
                if (d.nominated && d.debate) {
                    // 提名系统卡片：进入辩论阶段（仅双方可发言，20 秒后自动投票）
                    pubMsgs.value.push({
                        id: 'nm' + (++tipSeq),
                        number: 0, system: true,
                        content: '⚖️ 辩论开始：# ' + d.from + ' 提名了 #' + d.target,
                        nominateCard: {
                            from: d.from, target: d.target,
                            deadline: d.debate_deadline,
                            isParty: myNumber.value === d.from || myNumber.value === d.target,
                            left: Math.max(0, Math.floor(((d.debate_deadline || Date.now() / 1000) - Date.now() / 1000))),
                        },
                    });
                    voteInfo.value = {
                        from: d.from, target: d.target, waiting: false,
                        debate: true, debateDeadline: d.debate_deadline,
                    };
                    startDebateCountdown();
                }
            });
            let debateCountdownTimer = null;
            function startDebateCountdown() {
                if (debateCountdownTimer) clearInterval(debateCountdownTimer);
                const tick = () => {
                    if (!voteInfo.value || !voteInfo.value.debate || voteInfo.value.waiting) {
                        clearInterval(debateCountdownTimer);
                        return;
                    }
                    const left = voteInfo.value.debateDeadline - Math.floor(Date.now() / 1000);
                    debateCountdown.value = Math.max(0, left);
                    // 同步提名卡片倒计时
                    for (const m of pubMsgs.value) {
                        if (m.nominateCard) {
                            m.nominateCard.left = Math.max(0, Math.floor(m.nominateCard.deadline - Date.now() / 1000));
                        }
                    }
                    if (left <= 0) {
                        clearInterval(debateCountdownTimer);
                    }
                };
                tick();
                debateCountdownTimer = setInterval(tick, 400);
            }
            WS.on('game.vote_start', (d) => {
                if (view.value !== 'game') return;
                // 说书人投票系统卡片（公聊消息流内展示，仅非辩论双方可操作）
                pubMsgs.value.push({
                    id: 'vc' + (++tipSeq),
                    number: 0, system: true,
                    content: '⚖️ 投票开始：#' + d.from + ' 提名 #' + d.target,
                    voteCard: {
                        from: d.from, target: d.target,
                        deadline: d.deadline,
                        mine: false, done: false,
                        isParty: myNumber.value === d.from || myNumber.value === d.target,
                        left: Math.max(0, Math.floor(((d.deadline || Date.now() / 1000) - Date.now() / 1000))),
                    },
                });
                startVoteCountdown();
            });
            WS.on('game.vote_result', (d) => {
                // 标记投票卡片完成 + 说书人结果卡片（同意票数/参与人数/各玩家投票情况）
                for (const m of pubMsgs.value) {
                    if (m.voteCard && !m.voteCard.done) m.voteCard.done = true;
                }
                if (voteCountdownTimer) clearInterval(voteCountdownTimer);
                pubMsgs.value.push({
                    id: 'vr' + (++tipSeq),
                    number: 0, system: true,
                    content: '📢 投票结束：#' + d.target + ' 同意 ' + d.yes + ' 票',
                    voteResultCard: {
                        target: d.target,
                        yes: d.yes,
                        abstain: d.abstain || 0,
                        voted: d.voted || 0,
                        unvoted: d.unvoted || 0,
                        yes_nums: d.yes_nums || [],
                        unvoted_nums: d.unvoted_nums || [],
                        votes: d.votes || {},
                        message: d.message || '',
                        cooldownLeft: d.cooldown || 30,
                    },
                });
                // 提名窗口倒计时（卡片内展示）
                if (cooldownTimer) clearInterval(cooldownTimer);
                const cdTick = () => {
                    let any = false;
                    for (const m of pubMsgs.value) {
                        if (m.voteResultCard && m.voteResultCard.cooldownLeft > 0) {
                            any = true;
                            m.voteResultCard.cooldownLeft--;
                        }
                    }
                    if (!any) clearInterval(cooldownTimer);
                };
                cdTick();
                cooldownTimer = setInterval(cdTick, 1000);
            });
            WS.on('game.nominate_result', (d) => {
                voteInfo.value = null;
                // 处决判定系统卡片（周期结束统一比对结果）
                pubMsgs.value.push({
                    id: 'nrr' + (++tipSeq),
                    number: 0, system: true,
                    content: d.executed ? '⚖️ 处决：' + d.message : '⚖️ 提名结束：' + (d.message || ''),
                    nominateResultCard: {
                        executed: d.executed,
                        message: d.message || '',
                    },
                });
            });
            // ——— 私聊事件 ———
            WS.on('game.private_message', (d) => {
                if (view.value !== 'game') return;
                const other = d.from_number === myNumber.value ? d.to_number : d.from_number;
                if (!privateChats[other]) privateChats[other] = [];
                privateChats[other].push({
                    from_number: d.from_number,
                    to_number: d.to_number,
                    content: d.content,
                    mine: d.from_number === myNumber.value,
                });
                // 内存保护：每个私聊会话最多保留 100 条
                if (privateChats[other].length > 100) {
                    privateChats[other] = privateChats[other].slice(-100);
                }
                if (!privateTarget.value) privateTarget.value = other;
                // 私聊模式中收到非当前对象的私聊 → 提示（不打断当前对话）
                if (activePrivateTarget.value && other !== activePrivateTarget.value && !(d.from_number === myNumber.value)) {
                    toast('#' + d.from_number + ' 私聊了你：' + d.content.slice(0, 30), 'info');
                }
                // 不在私聊模式且收到对方消息 → 提示可点击玩家条目进入
                if (!activePrivateTarget.value && !(d.from_number === myNumber.value)) {
                    toast('#' + d.from_number + ' 私聊了你，点击左侧玩家条目进入私聊', 'info');
                }
            });
            WS.on('game.private_invite', (d) => {
                if (view.value !== 'game') return;
                privateIncoming.value = { from_number: d.from_number };
                toast('#' + d.from_number + ' 邀请你私聊', 'info');
            });
            WS.on('game.private_accepted', (d) => {
                privateInviteWaiting.value = null;
                privatePartners.value = [...new Set([...privatePartners.value, d.partner])];
                if (!privateChats[d.partner]) privateChats[d.partner] = [];
                if (!privateTarget.value) privateTarget.value = d.partner;
                // 对方接受邀请：直接进入私聊模式（聊天面板切换）
                activePrivateTarget.value = d.partner;
                toast('#' + d.partner + ' 接受了你的私聊邀请，聊天区已切换为私聊', 'success');
            });
            WS.on('game.private_declined', (d) => {
                privateInviteWaiting.value = null;
                toast('#' + d.by_number + ' 拒绝了你的私聊邀请', 'info');
            });

            // ——— 初始化 ———
            (async function init() {
                // 邀请链接：#join=ROOMCODE 自动填入房码
                const h = location.hash || '';
                const jm = h.match(/join=([A-Z0-9]{6})/i);
                if (jm) {
                    joinCode.value = jm[1].toUpperCase();
                    history.replaceState(null, '', location.pathname);
                    toast('检测到邀请链接，已填入房间码 ' + jm[1].toUpperCase(), 'info');
                }
                try {
                    const d = await api.get('/api/me');
                    if (d.data && d.data.user) {
                        user.value = d.data.user;
                        WS.connect();
                        const savedRoom = sessionStorage.getItem('botc_room');
                        if (savedRoom) {
                            // 刷新恢复：回到之前所在的房间/对局
                            try {
                                roomCode.value = savedRoom;
                                await ensureWS();
                                const ack = await joinRoomWS();
                                applyRoomState(ack.state);
                                if (ack.game && ack.game.game) {
                                    applyGameState(ack.game);
                                    enterGameState();
                                } else {
                                    view.value = 'room';
                                }
                            } catch (e) {
                                sessionStorage.removeItem('botc_room');
                                view.value = 'lobby';
                            }
                        } else {
                            view.value = 'lobby';
                        }
                    }
                } catch (e) { /* 未登录 */ }
            })();

            // ——— 鼠标追踪聚光灯（spotlight 卡片） ———
            document.addEventListener('mousemove', (e) => {
                const target = e.target && e.target.closest ? e.target.closest('.spotlight') : null;
                if (!target) return;
                const rect = target.getBoundingClientRect();
                target.style.setProperty('--mx', (e.clientX - rect.left) + 'px');
                target.style.setProperty('--my', (e.clientY - rect.top) + 'px');
            }, { passive: true });

            return {
                view, user, busy, loginForm, isRegister, joinCode, wsReady,
                roomCode, room, roomMessages, chatText, seatCount,
                game, myNumber, pubMsgs, gameChatText, myInfo, stories, nightInfo,
                infoDialog, overDialog, winner,
                statsDialog, stats, myGames, replayDialog, replay, openStatsPanel, openReplay,
                friendDialog, friendList, friendSearch, searchResult,
                inviteDialog, inviteIncoming, inviteIncomingVisible,
                voteInfo, voteCountdown, debateCountdown, castVote, endNomination,
                privatePhase, privatePanelVisible, privateChats, privateTarget, privateText,
                activePrivateTarget, exitPrivateChat, roomPlayers, activePrivateChats,
                privatePartners, privateInviteWaiting, privateIncoming,
                pickPrivateTarget, invitePrivate, acceptPrivate, declinePrivate, sendPrivateMsg, skipPrivate, leavePrivatePhase,
                collapsePrivatePanel, openPrivatePanel,
                isHost, myReady, sortedPlayers, phaseLabel, phaseTagClass, teamName, aliveCount, canSpeakNow, visibleMsgs, nameOf,
                doLogin, doLogout, createRoom, joinRoom: joinRoomByCode,
                sendRoomMsg, toggleReady, addAI, removeAI, kickPlayer, fillBots, setSeats, startGame, leaveRoom,
                fillAndStart,
                llmDialog, llmPresets, llmForm, openLlmDialog, pickLlmPreset, confirmAddLlmAI, usage, roomUsage, fetchUsage, fmtTokens,
                aiCount: (r) => r.players.filter(p => p.is_ai).length,
                sendGameMsg, nextPhase, nominate, endGame, backToRoom,
                clickPlayer, copyRoomLink,
                openFriendPanel, refreshFriendList, doFriendSearch, sendFriendRequest,
                acceptFriend, rejectFriend, removeFriend,
                openInviteDialog, sendInvite, acceptInvite, rejectInvite,
                toggleTipTarget, submitTipChoice,
            };
        },
    }).use(ElementPlus).mount('#app');
})();
