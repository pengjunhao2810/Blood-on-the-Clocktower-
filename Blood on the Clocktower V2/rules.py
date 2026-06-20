"""
血染钟楼 TROUBLE BREWING 官方流程引擎
流程: 选板子→分角色→天黑闭眼→各角色行动→天亮睁眼→私聊→公聊→提名投票→平安日/处决→天黑...
"""
import random
from core.game_manager import GameManager
from .roles import BOTC_ROLES, BOTC_TEAMS, NIGHT_ORDER_FIRST, NIGHT_ORDER_OTHER
from .dialogue_dataset import DialogueDataset as DD
from .dialogue_generator import (gen_good_private_discuss, gen_evil_private_plan,
                                 gen_good_public_reasoning, gen_good_bluff,
                                 gen_evil_public_reasoning)
from .personality import Personality, assign_personality, set_current_personality, apply_personality
from .ml_policy import (
    encode_observation, get_policy, get_trainer,
    is_enabled, is_recording, set_record, set_epsilon
)

# LLM 填充支持（懒加载，失败时自动降级）
try:
    from .llm_filler import generate_text as _llm_gen
except ImportError:
    try:
        from llm_filler import generate_text as _llm_gen
    except ImportError:
        _llm_gen = None
_LLM_PRIV_PROB = 0.0   # LLM暂禁用（模型加载太慢导致服务器崩溃）
_LLM_PUB_PROB = 0.0    # LLM暂禁用


class BloodOnClocktowerGame(GameManager):
    def __init__(self, registry=None, num_players=7, script="暗流涌动"):
        super().__init__("血染钟楼", registry)
        self.script = script
        self.num_players = num_players
        self.role_list = []
        self.dead_players = []
        self.poisoned_players = set()
        self.protected_player = None
        self.last_executed = None
        self.nominees = []
        self.executed_today = False
        self.peaceful_night = False
        self.peaceful_day = False
        self.day_count = 0
        self.night_count = 0
        self.setup_complete = False
        self.player_order = []
        self.game_phase = "SETUP"
        self.storyteller_log = []
        self.ghost_vote_used = set()
        self.public_claims = {}  # 公聊中玩家声明的身份 {玩家名: 声称的角色}
        self.nomination_count = {}  # 每个玩家被提名的次数 {玩家名: 次数}
        self.hunter_used = set()  # 已使用技能的猎手
        self.chat_history = []  # 公聊历史记录，供AI推理引用

    def select_script(self, script_name):
        self.script = script_name
        self.log(f"[设置] 选定剧本: {script_name}")

    def _generate_roles(self, num):
        configs = {
            5: {"townsfolk": 3, "outsider": 0, "minion": 1, "demon": 1},
            6: {"townsfolk": 3, "outsider": 1, "minion": 1, "demon": 1},
            7: {"townsfolk": 5, "outsider": 0, "minion": 1, "demon": 1},
            8: {"townsfolk": 5, "outsider": 0, "minion": 2, "demon": 1},
            9: {"townsfolk": 5, "outsider": 2, "minion": 1, "demon": 1},
            10: {"townsfolk": 7, "outsider": 0, "minion": 2, "demon": 1},
            11: {"townsfolk": 7, "outsider": 1, "minion": 2, "demon": 1},
            12: {"townsfolk": 7, "outsider": 2, "minion": 2, "demon": 1},
        }
        config = dict(configs.get(num, configs[7]))
        # 先抽爪牙，检查是否有男爵(增加2外来者)
        minion_pool = list(BOTC_TEAMS["minion"])
        random.shuffle(minion_pool)
        chosen_minions = minion_pool[:config["minion"]]
        has_baron = "男爵" in chosen_minions
        if has_baron:
            config["outsider"] = min(config["outsider"] + 2, config["townsfolk"])
            config["townsfolk"] = num - config["demon"] - config["minion"] - config["outsider"]
        roles = list(chosen_minions)
        for group, count in config.items():
            if group == "minion":
                continue
            pool = list(BOTC_TEAMS[group])
            random.shuffle(pool)
            roles.extend(pool[:min(count, len(pool))])
        # 酒鬼官方规则：酒鬼标记不放进袋中，替换为一个镇民标记
        self._drunk_public_role = None
        if "酒鬼" in roles:
            available = [r for r in BOTC_TEAMS["townsfolk"] if r not in roles]
            extra = random.choice(available) if available else random.choice(BOTC_TEAMS["townsfolk"])
            idx = roles.index("酒鬼")
            roles[idx] = extra
            self._drunk_public_role = extra
        random.shuffle(roles)
        return roles

    def setup_game(self, agents: list):
        self.role_list = self._generate_roles(len(agents))
        if len(agents) != len(self.role_list):
            raise ValueError(f"需要{len(self.role_list)}名玩家，当前{len(agents)}名")
        # 先设置所有玩家的game_state
        for agent, role in zip(agents, self.role_list):
            agent.role = role
            agent.alive = True
            agent.game_state = {
                "role": role,
                "role_info": BOTC_ROLES.get(role, {}),
                "observations": [],
                "known_info": {},
                "private_info": "",
                "is_poisoned": False,
                "is_drunk": False,
                "chat_memory": [],        # 听到的所有对话
                "suspicion": {},           # {玩家名: 怀疑分数(0-100)}
                "trust": {},              # {玩家名: 信任分数(0-100)}
                "my_claims": [],          # 自己公开声明过的身份
                "notes": "",              # 私人笔记（上次更新后的新发现）
                "diary": {},              # {day: [笔记条目列表]}
                "accusations": {},        # {day: {accuser: [targets]}}
                "vote_patterns": {},      # {player: [voted_for]}
            }
            self.add_player(agent)
        self.player_order = [a.name for a in self.registry.all_agents()]

        # 酒鬼官方规则：酒鬼标记不放进袋中，拿到替换镇民标记的玩家秘密是酒鬼
        if self._drunk_public_role:
            for agent in agents:
                if agent.role == self._drunk_public_role:
                    agent.game_state["is_drunk"] = True
                    agent.game_state["fake_role"] = agent.role
                    agent.role = "酒鬼"
                    self.log(f"  {agent.name}是酒鬼(以为自己是{agent.game_state['fake_role']})")
                    break

        # 占卜师干扰项：随机选一名非恶魔玩家，他始终被占卜师当作恶魔
        fortune_tellers = [a for a in agents if a.role == "占卜师"]
        if fortune_tellers:
            non_demon = [a for a in agents if a.role not in BOTC_TEAMS["demon"]]
            if non_demon:
                red_herring = random.choice(non_demon)
                for ft in fortune_tellers:
                    ft.game_state["red_herring"] = red_herring.name
                    self.log(f"  {ft.name}(占卜师)的干扰项是{red_herring.name}({red_herring.role})")
        self.setup_complete = True
        self.game_phase = "ROLE_ASSIGN"
        self.log(f"[设置] {len(agents)}人局, 角色已分配")

    def log(self, msg):
        self.storyteller_log.append(msg)
        try:
            print(msg)
        except UnicodeEncodeError:
            safe = msg.encode('gbk', errors='replace').decode('gbk', errors='replace')
            print(safe)

    def get_player_by_name(self, name):
        return self.registry.get(name)

    def get_alive_names(self):
        return [a.name for a in self.registry.all_alive()]

    def get_alive_agents(self):
        return self.registry.all_alive()

    # ==================== 第一阶段: 角色分配与信息 ====================
    def phase_role_assignment(self):
        """发放角色并告知初始信息"""
        self.log(f"\n========== 剧本: {self.script} ==========")
        self.log(f"玩家人数: {self.num_players}")
        self.log("\n--- 角色分配 ---")
        for a in self.registry.all_agents():
            team_names = {"townsfolk": "镇民", "outsider": "外来者", "minion": "爪牙", "demon": "恶魔"}
            t = team_names.get(BOTC_ROLES[a.role].get("team", ""), "未知")
            self.log(f"  {a.name}: {a.role} ({t})")
        self.game_phase = "NIGHT"

    # ==================== 第二阶段: 夜晚 ====================
    def run_night(self):
        self.night_count += 1
        self.peaceful_night = True
        self.protected_player = None
        is_first = (self.night_count == 1)
        order = NIGHT_ORDER_FIRST if is_first else NIGHT_ORDER_OTHER

        self.log(f"\n========== 第{self.night_count}晚(天黑请闭眼) ==========")
        self.game_phase = f"NIGHT_{self.night_count}"
        self.game_record["rounds"].append({
            "round_num": self.night_count,
            "phase": f"night_{self.night_count}",
            "actions": []
        })

        if is_first:
            self._first_night_information()

        for step_name, desc in order:
            self._execute_night_step(step_name, is_first)

        died = [name for name in self.get_alive_names() if name in self.dead_players and name not in self.get_alive_names()]
        new_deaths = [p for p in self.dead_players if self.get_player_by_name(p) and not self.get_player_by_name(p).alive]
        new_deaths = list(set(new_deaths))

        self.log(f"\n========== 天亮了 ==========")
        if new_deaths:
            self.log(f"昨晚死亡: {', '.join(new_deaths)}")
            self.peaceful_night = False
        elif not is_first:
            self.log(f"昨晚是个平安夜, 无人死亡。")
            self.peaceful_night = True
        else:
            self.peaceful_night = True

        self._record_night_info()
        self._check_game_end()

    def _first_night_information(self):
        """首夜信息分发"""
        self.log("\n--- [说书人] 首夜信息分发 ---")

        demon_agents = self.registry.get_by_role("小恶魔")
        minion_agents = self.registry.get_by_role("投毒者") + self.registry.get_by_role("间谍") + \
                        self.registry.get_by_role("红唇女郎") + self.registry.get_by_role("男爵")

        if self.num_players >= 7:
            self.log(f"[爪牙信息] 唤醒爪牙, 向他们指认恶魔...")
            for m in minion_agents:
                if demon_agents:
                    m.game_state["known_info"]["demon"] = demon_agents[0].name
                    self.log(f"  {m.name}(爪牙)得知恶魔是{demon_agents[0].name}")

            self.log(f"[恶魔信息] 唤醒恶魔, 指认爪牙并展示伪装角色...")
            for d in demon_agents:
                # 仅展示不在场上的角色（排除已分配给玩家的所有角色）
                in_play_roles = set(a.role for a in self.registry.all_agents())
                all_good_roles = BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"]
                off_script = [r for r in all_good_roles if r not in in_play_roles]
                # 排除酒鬼的假角色（酒鬼占了一个镇民位，该角色视为在场）
                for agent in self.registry.all_agents():
                    if agent.game_state.get("is_drunk"):
                        drunk_fake = agent.game_state.get("fake_role")
                        if drunk_fake in off_script:
                            off_script.remove(drunk_fake)
                min_count = min(3, len(off_script))
                if min_count >= 3:
                    fake_roles = random.sample(off_script, 3)
                else:
                    fake_roles = off_script[:]
                    missing = 3 - len(fake_roles)
                    extra_pool = [r for r in all_good_roles if r not in fake_roles and r not in in_play_roles]
                    fake_roles.extend(random.sample(extra_pool, min(missing, len(extra_pool))))
                d.game_state["known_info"]["minions"] = [m.name for m in minion_agents]
                d.game_state["known_info"]["fake_roles"] = fake_roles
                self.log(f"  {d.name}(恶魔)得知爪牙: {[m.name for m in minion_agents]}")
                self.log(f"  {d.name}(恶魔)可伪装角色: {fake_roles}")

        self.log("[首夜信息] 各信息角色已获取初始信息。")

    def _ml_pick_kill_target(self, player, candidates):
        """ML策略选择击杀目标"""
        if not is_enabled() or not candidates:
            return None
        obs, n2i, i2n = encode_observation(self, player)
        valid = [n2i[t] for t in candidates if t in n2i]
        if not valid:
            return None
        kill_idx, log_prob = get_policy().act_kill(obs, valid_kill=valid, eps=0.2)
        target = i2n[kill_idx]
        if log_prob is not None and is_recording():
            get_trainer().record_step(log_prob)
        return target

    def _imp_kill(self, player):
        """小恶魔杀人逻辑，含自杀传位机制（官方：红唇女郎优先，存活>=5人才可传位）"""
        alive_names = [a.name for a in self.registry.all_alive() if a.name != player.name]
        alive_count = len(alive_names) + 1  # 含恶魔自己
        minions = [m for m in self.registry.all_agents()
                   if m.role in BOTC_TEAMS["minion"] and m.alive]
        can_suicide = bool(minions) and alive_count >= 5

        target_pool = alive_names[:]
        if can_suicide:
            target_pool = alive_names + [player.name]

        if not target_pool:
            return

        soldiers = self.registry.get_by_role("士兵")
        soldier_names = [s.name for s in soldiers if s.alive]
        valid_targets = [t for t in target_pool
                         if not any(s == t for s in soldier_names)
                         and t != self.protected_player]
        if not valid_targets:
            valid_targets = target_pool
        if not valid_targets:
            return

        # 优先击杀信息位（声明占卜师、共情者等的高威胁目标）
        info_roles = ["占卜师", "共情者", "调查员", "送葬者", "守鸦人"]
        _, _, claim_map = self._build_chat_summary(player)
        info_claimants = [p for p in valid_targets if p in claim_map and claim_map[p] in info_roles]
        if info_claimants and random.random() < 0.6:
            target = random.choice(info_claimants)
            self.log(f"  [邪恶战略] {player.name}优先击杀信息位{target}")
        else:
            target = self._ml_pick_kill_target(player, valid_targets)
            if not target:
                target = random.choice(valid_targets)
        target_agent = self.get_player_by_name(target)

        if target == player.name:
            # 小恶魔自杀 → 红唇女郎优先变恶魔，否则随机爪牙
            red_lip = [m for m in minions if m.role == "红唇女郎"]
            new_demon = None
            if red_lip:
                new_demon = red_lip[0]
                self.log(f"  [小恶魔] {player.name}自杀了! 红唇女郎{new_demon.name}变成了新恶魔!")
            elif minions:
                new_demon = random.choice(minions)
                self.log(f"  [小恶魔] {player.name}自杀了! {new_demon.name}变成了新恶魔!")
            if new_demon:
                new_demon.role = "小恶魔"
                new_demon.game_state["role"] = "小恶魔"
                new_minions = [m.name for m in minions if m.name != new_demon.name]
                new_demon.game_state["known_info"]["minions"] = new_minions
                self.log(f"  [小恶魔] 新恶魔{new_demon.name}今晚不能行动，从下一晚开始杀人")
            # 自杀计入死亡
            target_agent.alive = False
            self.dead_players.append(target)
            self.peaceful_night = False
            self.record_action(player.name, "恶魔自杀", f"自杀传位给{new_demon.name if new_demon else '无爪牙(邪恶落败)'}", "night_action")
            if not new_demon:
                self.log(f"  [小恶魔] {player.name}自杀了! 存活不足5人, 邪恶阵营落败!")
        else:
            # 镇长被动保护：恶魔攻击镇长时，说书人可选择另一名玩家替死
            if target_agent.role == "镇长" and random.random() < 0.5:
                substitutes = [a.name for a in self.registry.all_alive()
                               if a.name != target and a.name != player.name
                               and a.role != "士兵" and a.name != self.protected_player]
                if substitutes:
                    real_target = random.choice(substitutes)
                    real_target_agent = self.get_player_by_name(real_target)
                    real_target_agent.alive = False
                    self.dead_players.append(real_target)
                    self.peaceful_night = False
                    self.record_action(player.name, "恶魔杀人", f"攻击镇长{target},但{real_target}代为死亡", "night_action")
                    self.log(f"  [镇长] 恶魔攻击{target}, {real_target}代为死亡!")
                    return
            target_agent.alive = False
            self.dead_players.append(target)
            self.peaceful_night = False
            self.record_action(player.name, "恶魔杀人", f"杀害{target}", "night_action")
            self.log(f"  [小恶魔] {player.name}杀害了{target}!")

    def _get_registered_team(self, player):
        """获取玩家在信息技能中注册的阵营
        官方：间谍可被当作镇民/外来者; 陌客可被当作任何阵营"""
        if player.role == "间谍":
            # 间谍可被洗衣妇、贞洁者、送葬者当作镇民或外来者
            return random.choice(["townsfolk", "outsider", "townsfolk", "minion"])
        if player.role == "陌客":
            # 陌客可被占卜师、送葬者、猎手当作恶魔或爪牙
            return random.choice(["townsfolk", "outsider", "minion", "demon"])
        return BOTC_ROLES.get(player.role, {}).get("team", "")

    def _get_registered_role(self, player):
        """获取玩家在信息技能中注册的具体角色"""
        team = self._get_registered_team(player)
        if player.role == "间谍" and team != "minion":
            return random.choice(BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"])
        if player.role == "陌客":
            if team == "townsfolk":
                return random.choice(BOTC_TEAMS["townsfolk"])
            if team == "minion":
                return random.choice(BOTC_TEAMS["minion"])
            if team == "demon":
                return "小恶魔"
        return player.role

    def _execute_night_step(self, step_name, is_first):
        """执行夜晚单步行动"""
        name_map = {
            "投毒者": "投毒者", "间谍": "间谍", "洗衣妇": "洗衣妇",
            "图书管理员": "图书管理员", "调查员": "调查员", "厨师": "厨师",
            "共情者": "共情者", "占卜师": "占卜师", "僧侣": "僧侣",
            "管家": "管家", "小恶魔": "小恶魔", "送葬者": "送葬者",
            "守鸦人": "守鸦人", "红唇女郎": "红唇女郎",
        }

        role_name = name_map.get(step_name, "")
        if not role_name or step_name in ["黄昏", "黎明", "爪牙信息", "恶魔信息"]:
            if step_name == "黄昏":
                self.poisoned_players.clear()
            if step_name == "黎明":
                pass
            return

        players = self.registry.get_by_role(role_name)
        alive_players = [p for p in players if p.alive]

        # 酒鬼玩家（认为自己有这个角色，但实际是酒鬼）
        drunk_players = [p for p in self.registry.all_alive()
                         if p.game_state.get("is_drunk")
                         and p.game_state.get("fake_role") == role_name
                         and p not in alive_players]

        # 守鸦人特殊处理：当晚死亡也可行动（包括酒鬼守鸦人）
        if role_name == "守鸦人" and not is_first:
            dead_this_night = [p for p in self.dead_players if any(
                a.name == p and not a.alive for a in self.registry.all_agents()
            )]
            rk_dead = [a for a in players if a.name in dead_this_night]
            rk_drunk_dead = [a for a in self.registry.all_agents() if a.name in dead_this_night
                             and a.game_state.get("is_drunk")
                             and a.game_state.get("fake_role") == "守鸦人"]
            for rk in rk_dead + rk_drunk_dead:
                is_drunk_rk = rk in rk_drunk_dead
                targets = [a for a in self.registry.all_alive() if a.name != rk.name]
                if targets:
                    target = random.choice(targets)
                    if is_drunk_rk:
                        fake_role = random.choice(BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"] + BOTC_TEAMS["minion"])
                        rk.game_state["known_info"]["ravenkeeper"] = (target.name, fake_role)
                        self.log(f"  [守鸦人·酒鬼] {rk.name}查验{target.name}: {fake_role}（假信息）")
                    else:
                        rk.game_state["known_info"]["ravenkeeper"] = (target.name, target.role)
                        self.log(f"  [守鸦人] {rk.name}死亡后查验了{target.name}的身份: {target.role}")

        all_actors = alive_players + drunk_players
        for player in all_actors:
            is_drunk_actor = player in drunk_players

            if role_name == "投毒者":
                targets = [a.name for a in self.registry.all_alive() if a.name != player.name]
                if targets:
                    target = random.choice(targets)
                    self.poisoned_players.add(target)
                    target_agent = self.get_player_by_name(target)
                    if target_agent:
                        target_agent.game_state["is_poisoned"] = True
                    context = f"投毒者选择目标"
                    self.record_action(player.name, context, f"对{target}下毒", "night_action")
                    self.log(f"  [投毒者] {player.name}对{target}下毒(将获得错误信息)")

            elif role_name == "小恶魔" and not is_first:
                self._imp_kill(player)

            elif role_name == "僧侣" and not is_first:
                others = [a.name for a in self.registry.all_alive() if a.name != player.name]
                if others:
                    protect = random.choice(others)
                    if not is_drunk_actor:
                        self.protected_player = protect
                    player.game_state["protected"] = protect
                    self.log(f"  [{'僧侣·酒鬼' if is_drunk_actor else '僧侣'}] {player.name}保护了{protect}")

            elif role_name == "共情者":
                if is_drunk_actor:
                    evil_count = random.randint(0, 2)
                else:
                    idx = self.player_order.index(player.name)
                    neighbors = []
                    for offset in [-1, 1]:
                        ni = (idx + offset) % len(self.player_order)
                        n_name = self.player_order[ni]
                        n_agent = self.get_player_by_name(n_name)
                        if n_agent and n_agent.alive:
                            neighbors.append(n_agent)
                    evil_count = sum(1 for n in neighbors
                                     if self._get_registered_team(n) in ["minion", "demon"])
                    if player.name in self.poisoned_players:
                        evil_count = max(0, evil_count + random.choice([-1, 1]))
                player.game_state["known_info"]["empathy"] = evil_count
                self.log(f"  [共情者{'·酒鬼' if is_drunk_actor else ''}] {player.name}得知相邻邪恶数: {evil_count}")

            elif role_name == "占卜师":
                all_names = [a.name for a in self.registry.all_agents() if a.name != player.name]
                others = [n for n in all_names]
                if len(others) >= 2:
                    chosen = random.sample(others, 2)
                elif len(others) == 1:
                    chosen = [others[0], others[0]]
                else:
                    continue
                if is_drunk_actor:
                    has_demon = random.choice([True, False])
                else:
                    red_herring_name = player.game_state.get("red_herring")
                    has_demon = False
                    for n in chosen:
                        target = self.get_player_by_name(n)
                        if not target:
                            continue
                        if target.role in BOTC_TEAMS["demon"]:
                            has_demon = True
                        elif red_herring_name and n == red_herring_name:
                            has_demon = True
                    if player.name in self.poisoned_players:
                        has_demon = not has_demon
                player.game_state["known_info"]["seer"] = (chosen, has_demon)
                result_text = "有恶魔" if has_demon else "无恶魔"
                self.log(f"  [占卜师{'·酒鬼' if is_drunk_actor else ''}] {player.name}查验{chosen}: {result_text}")

            elif role_name == "送葬者" and not is_first:
                if self.last_executed:
                    exec_agent = self.get_player_by_name(self.last_executed)
                    if exec_agent:
                        if is_drunk_actor:
                            fake_role = random.choice(BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"] + BOTC_TEAMS["minion"] + BOTC_TEAMS["demon"])
                            player.game_state["known_info"]["undertaker"] = fake_role
                            self.log(f"  [送葬者·酒鬼] {player.name}得知{self.last_executed}的身份是{fake_role}（假信息）")
                        else:
                            player.game_state["known_info"]["undertaker"] = exec_agent.role
                            self.log(f"  [送葬者] {player.name}得知{self.last_executed}的身份是{exec_agent.role}")

            elif role_name == "间谍":
                all_roles_info = {a.name: a.role for a in self.registry.all_agents()}
                player.game_state["known_info"]["spy_info"] = all_roles_info
                self.log(f"  [间谍] {player.name}查看了全角色 ({len(all_roles_info)}人)")

            elif role_name == "管家":
                others = [a.name for a in self.registry.all_alive() if a.name != player.name]
                if others:
                    master = random.choice(others)
                    player.game_state["known_info"]["master"] = master
                    self.log(f"  [管家] {player.name}选择{master}为主人")

            elif role_name == "洗衣妇" and is_first:
                if is_drunk_actor:
                    alive = [a for a in self.registry.all_agents() if a.alive and a.name != player.name]
                    if len(alive) >= 2:
                        candidates = random.sample(alive, 2)
                        fake_role = random.choice(BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"])
                        player.game_state["known_info"]["washerwoman"] = (candidates[0].name, candidates[1].name, fake_role)
                        self.log(f"  [洗衣妇·酒鬼] {player.name}得知{candidates[0].name}或{candidates[1].name}是{fake_role}（假信息）")
                else:
                    alive = [a for a in self.registry.all_agents() if a.alive and a.name != player.name]
                    if len(alive) >= 2:
                        chosen = random.sample(alive, 2)
                        registered_townsfolk = [c for c in chosen if self._get_registered_team(c) == "townsfolk"]
                        target = registered_townsfolk[0] if registered_townsfolk else chosen[0]
                        shown_role = self._get_registered_role(target)
                        player.game_state["known_info"]["washerwoman"] = (chosen[0].name, chosen[1].name, shown_role)
                        self.log(f"  [洗衣妇] {player.name}得知{chosen[0].name}或{chosen[1].name}是{shown_role}")

            elif role_name == "图书管理员" and is_first:
                if is_drunk_actor:
                    alive = [a for a in self.registry.all_agents() if a.alive and a.name != player.name]
                    if len(alive) >= 2:
                        candidates = random.sample(alive, 2)
                        fake_role = random.choice(BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"])
                        player.game_state["known_info"]["librarian"] = (candidates[0].name, candidates[1].name, fake_role)
                        self.log(f"  [图书管理员·酒鬼] {player.name}得知{candidates[0].name}或{candidates[1].name}是{fake_role}（假信息）")
                else:
                    all_agents = self.registry.all_agents()
                    alive_outsiders = [o for o in all_agents if o.alive and o.name != player.name
                                       and self._get_registered_team(o) == "outsider"]
                    alive_others = [o for o in all_agents if o.alive and o.name != player.name
                                    and self._get_registered_team(o) != "outsider"]
                    if alive_outsiders and len(alive_others) >= 1:
                        chosen = [random.choice(alive_outsiders), random.choice(alive_others)]
                        shown_role = self._get_registered_role(chosen[0])
                        player.game_state["known_info"]["librarian"] = (chosen[0].name, chosen[1].name, shown_role)
                        self.log(f"  [图书管理员] {player.name}得知{chosen[0].name}或{chosen[1].name}是外来者({shown_role})")
                    else:
                        player.game_state["known_info"]["librarian"] = ("无", "无", "本局没有外来者")
                        self.log(f"  [图书管理员] {player.name}得知本局没有外来者")

            elif role_name == "调查员" and is_first:
                if is_drunk_actor:
                    alive = [a for a in self.registry.all_agents() if a.alive and a.name != player.name]
                    if len(alive) >= 2:
                        candidates = random.sample(alive, 2)
                        fake_role = random.choice(BOTC_TEAMS["minion"])
                        player.game_state["known_info"]["investigator"] = (candidates[0].name, candidates[1].name, fake_role)
                        self.log(f"  [调查员·酒鬼] {player.name}得知{candidates[0].name}或{candidates[1].name}是爪牙({fake_role})（假信息）")
                else:
                    all_agents = self.registry.all_agents()
                    alive_minions = [m for m in all_agents if m.alive and m.name != player.name
                                     and self._get_registered_team(m) == "minion"]
                    alive_others = [o for o in all_agents if o.alive and o.name != player.name
                                    and self._get_registered_team(o) != "minion"]
                    if alive_minions and len(alive_others) >= 1:
                        chosen = [random.choice(alive_minions), random.choice(alive_others)]
                        shown_role = self._get_registered_role(chosen[0])
                        player.game_state["known_info"]["investigator"] = (chosen[0].name, chosen[1].name, shown_role)
                        self.log(f"  [调查员] {player.name}得知{chosen[0].name}或{chosen[1].name}是爪牙({shown_role})")

            elif role_name == "厨师" and is_first:
                if is_drunk_actor:
                    evil_pairs = random.randint(0, 2)
                else:
                    evil_pairs = 0
                    for i in range(len(self.player_order)):
                        current = self.get_player_by_name(self.player_order[i])
                        next_p = self.get_player_by_name(self.player_order[(i + 1) % len(self.player_order)])
                        if current and next_p:
                            c_evil = self._get_registered_team(current) in ["minion", "demon"]
                            n_evil = self._get_registered_team(next_p) in ["minion", "demon"]
                            if c_evil and n_evil:
                                evil_pairs += 1
                    if player.name in self.poisoned_players:
                        evil_pairs = max(0, evil_pairs + random.choice([-1, 1]))
                player.game_state["known_info"]["chef"] = evil_pairs
                self.log(f"  [厨师{'·酒鬼' if is_drunk_actor else ''}] {player.name}得知相邻邪恶对数为: {evil_pairs}")

    # ==================== 第三阶段: 白天(私聊+公聊+提名) ====================
    def run_day(self):
        """完整的白天流程（兼容旧调用）"""
        self.start_day()
        if self.game_record.get('result'):
            return
        self._private_chat_phase()
        self._check_game_end()
        if self.game_record.get('result'):
            return
        self._public_chat_phase()
        self._check_game_end()
        if self.game_record.get('result'):
            return
        self._nomination_and_voting_phase()
        self.end_day()

    def start_day(self):
        """初始化白天"""
        self.day_count += 1
        self.executed_today = False
        self.nominees = []
        self.peaceful_day = True

        self.log(f"\n========== 第{self.day_count}天(白天) ==========")
        self.game_phase = f"DAY_{self.day_count}"
        self.game_record["rounds"].append({
            "round_num": self.day_count,
            "phase": f"day_{self.day_count}",
            "actions": []
        })

        self._check_game_end()

    def end_day(self):
        """结束白天，宣布处决情况"""
        if self.executed_today:
            self.log(f"\n[处决] 今天有玩家被处决。")
            self.peaceful_day = False
        else:
            self.log(f"\n[平安日] 今天无人被处决, 是个平安日。")
        self._check_game_end(check_mayor=True)

    def _store_chat(self, speaker, listener, speech, phase):
        """将对话存入玩家记忆"""
        entry = {"speaker": speaker, "listener": listener, "text": speech, "phase": phase, "day": self.day_count}
        sp = self.get_player_by_name(speaker)
        if sp:
            sp.game_state["chat_memory"].append(entry)
            for rn in BOTC_ROLES:
                if f"我是{rn}" in speech:
                    already = any(c["role"] == rn and c["day"] == self.day_count for c in sp.game_state["my_claims"])
                    if not already:
                        sp.game_state["my_claims"].append({"role": rn, "day": self.day_count, "target": speech})
                        self.public_claims[speaker] = rn
                    break
        if listener != "all":
            lp = self.get_player_by_name(listener)
            if lp:
                lp.game_state["chat_memory"].append(entry)
        else:
            for p in self.registry.all_agents():
                if p.name != speaker:
                    p.game_state["chat_memory"].append(entry)

    def _get_claim_history(self):
        """构建全局身份声明历史: {player: [(day, role), ...]}"""
        history = {}
        for p in self.registry.all_agents():
            claims = p.game_state.get("my_claims", [])
            if claims:
                history[p.name] = [(c["day"], c["role"]) for c in claims]
        return history

    def _update_suspicion_from_chat(self, player):
        """根据聊天记录更新怀疑/信任分数"""
        gs = player.game_state
        memory = gs.get("chat_memory", [])
        claim_history = self._get_claim_history()

        for entry in memory[-30:]:
            sp_name = entry["speaker"]
            text = entry["text"]
            if sp_name not in gs["suspicion"]:
                gs["suspicion"][sp_name] = 50
            if sp_name not in gs["trust"]:
                gs["trust"][sp_name] = 50
            if sp_name == player.name:
                continue

            # 1. 角色矛盾检测: 同人不同天声称不同角色
            if sp_name in claim_history:
                roles_on_days = claim_history[sp_name]
                unique_roles = set(r for d, r in roles_on_days)
                if len(unique_roles) > 1:
                    gs["suspicion"][sp_name] = min(100, gs["suspicion"][sp_name] + 25)
                    gs["trust"][sp_name] = max(0, gs["trust"][sp_name] - 15)

            # 2. 角色冲突检测: 两人声称同一镇民/外来者角色
            claimed_now = None
            for rn in BOTC_ROLES:
                if f"我是{rn}" in text:
                    claimed_now = rn
                    break
            if claimed_now:
                role_team = BOTC_ROLES.get(claimed_now, {}).get("team", "")
                if role_team in ("townsfolk", "outsider"):
                    for other_p in self.registry.all_agents():
                        if other_p.name != sp_name and other_p.name != player.name:
                            for oc in other_p.game_state.get("my_claims", []):
                                if oc["role"] == claimed_now:
                                    gs["suspicion"][sp_name] = min(100, gs["suspicion"][sp_name] + 10)
                                    if other_p.name not in gs["suspicion"]:
                                        gs["suspicion"][other_p.name] = 50
                                    if other_p.name not in gs["trust"]:
                                        gs["trust"][other_p.name] = 50
                                    gs["suspicion"][other_p.name] = min(100, gs["suspicion"][other_p.name] + 5)
                                    if sp_name not in gs["trust"]:
                                        gs["trust"][sp_name] = 50
                                    gs["trust"][sp_name] = max(0, gs["trust"][sp_name] - 5)

            # 3. 投票模式分析
            vote_info = self.game_record.get("vote_history", {})
            for day_str, votes in vote_info.items():
                for vote_entry in votes:
                    if vote_entry.get("voter") == sp_name:
                        target = vote_entry.get("target")
                        if target == player.name:
                            gs["suspicion"][sp_name] = min(100, gs["suspicion"][sp_name] + 10)
                        target_agent = self.get_player_by_name(target)
                        if target_agent and target_agent.role in BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"]:
                            if target in claim_history:
                                gs["suspicion"][sp_name] = min(100, gs["suspicion"][sp_name] + 8)

            # 4. 指控回旋镖: 被提名者反过来指控提名者
            if "提名" in text or "处决" in text:
                for other_name in self.public_claims:
                    if other_name != sp_name and other_name in text:
                        if other_name not in gs["suspicion"]:
                            gs["suspicion"][other_name] = 50
                        if other_name not in gs["trust"]:
                            gs["trust"][other_name] = 50
                        gs["suspicion"][other_name] = min(100, gs["suspicion"][other_name] + 3)

    def _get_last_exchange(self, name_a, name_b, n=3):
        """获取两人之间最近n次私聊记录"""
        exchanges = []
        for p in self.registry.all_agents():
            mem = p.game_state.get("chat_memory", [])
            for entry in reversed(mem):
                sp = entry.get("speaker", "")
                txt = entry.get("text", "")
                phase = entry.get("phase", "")
                if phase == "private_chat" and sp in (name_a, name_b) and txt:
                    other = name_b if sp == name_a else name_a
                    if other in txt or True:  # 属于这次对话
                        exchanges.append((sp, txt))
                        if len(exchanges) >= n:
                            return list(reversed(exchanges))
        return exchanges

    def _private_chat_phase(self):
        """多人私聊环节 - 每个玩家可与多人对话，按线程记录"""
        self.log(f"\n--- [私聊环节] 玩家可以私下交流 ---")
        self.game_phase = f"PRIVATE_CHAT_D{self.day_count}"

        if "private_chat_history" not in self.game_record:
            self.game_record["private_chat_history"] = {}

        alive = [a for a in self.registry.all_agents() if a.alive]
        random.shuffle(alive)

        used_pairs = set()
        chat_pairs = []
        total_players = len(alive)
        max_chats_per_player = 2 if total_players >= 10 else 3
        counts = {a.name: 0 for a in alive}

        for a in alive:
            partners = [p for p in alive if p.name != a.name and counts[p.name] < max_chats_per_player]
            random.shuffle(partners)
            for p in partners:
                pk = tuple(sorted([a.name, p.name]))
                if pk not in used_pairs and counts[a.name] < max_chats_per_player:
                    used_pairs.add(pk)
                    chat_pairs.append((a.name, p.name))
                    counts[a.name] += 1
                    counts[p.name] += 1

        chat_rounds = 2 if total_players >= 10 else 3

        for name_a, name_b in chat_pairs:
            a = self.get_player_by_name(name_a)
            b = self.get_player_by_name(name_b)
            if not a or not b:
                continue

            # 跨天统一线程key（不含天）
            names = sorted([name_a, name_b])
            thread_key = f"{names[0]}🔄{names[1]}"
            if thread_key in self.game_record["private_chat_history"]:
                thread_msgs = list(self.game_record["private_chat_history"][thread_key])
            else:
                thread_msgs = []
            seq = len(thread_msgs)

            for rnd in range(1, chat_rounds + 1):
                self._update_suspicion_from_chat(a)
                self._update_suspicion_from_chat(b)

                s_a = self._gen_speech(a, b.name)
                name_prefix = f"{a.name}: "
                if s_a.startswith(name_prefix):
                    s_a = s_a[len(name_prefix):]
                s_a = apply_personality(a, s_a)
                seq += 1
                self.log(f"  [{seq}] {a.name} 对 {b.name} 说: {s_a}")
                self.record_action(a.name, f"私聊{b.name}", s_a, "private_chat")
                self._store_chat(a.name, b.name, s_a, "private_chat")
                thread_msgs.append({"speaker": a.name, "text": s_a, "seq": seq})

                s_b = self._gen_speech(b, a.name)
                name_prefix = f"{b.name}: "
                if s_b.startswith(name_prefix):
                    s_b = s_b[len(name_prefix):]
                s_b = apply_personality(b, s_b)
                seq += 1
                self.log(f"  [{seq}] {b.name} 对 {a.name} 说: {s_b}")
                self.record_action(b.name, f"私聊{a.name}", s_b, "private_chat")
                self._store_chat(b.name, a.name, s_b, "private_chat")
                thread_msgs.append({"speaker": b.name, "text": s_b, "seq": seq})

            self.game_record["private_chat_history"][thread_key] = thread_msgs

        if not chat_pairs:
            self.log(f"  (玩家较少, 私聊环节跳过)")

    def _pick_target_suspicion(self, player):
        """基于怀疑分数选目标"""
        gs = player.game_state
        if gs.get("suspicion"):
            sorted_suspects = sorted(gs["suspicion"].items(), key=lambda x: -x[1])
            for name, score in sorted_suspects:
                if score >= 60 and name != player.name:
                    return name
        # 随机兜底
        alive = [a for a in self.registry.all_agents() if a.alive and a.name != player.name]
        return alive[0].name if alive else None

    def _build_chat_summary(self, player):
        """长上下文：构建聊天总结，帮助AI审阅更多对话"""
        gs = player.game_state
        memory = gs.get("chat_memory", [])
        if not memory:
            return "", [], {}
        
        recent = memory[-40:]
        claim_map = {}
        event_list = []
        name = player.name

        for entry in recent:
            sp = entry.get("speaker", "")
            txt = entry.get("text", "")
            for rn in BOTC_ROLES:
                if f"我是{rn}" in txt and sp not in claim_map:
                    claim_map[sp] = rn
            if any(kw in txt for kw in ("开枪","射杀","猎人")):
                event_list.append(f"{sp}开过枪")
            if "提名" in txt:
                event_list.append(f"{sp}发起过提名")
            if "处决" in txt and "我" in txt:
                event_list.append(f"{sp}被处决")

        # 找身份矛盾
        clash = []
        roles_seen = {}
        for sp, rn in claim_map.items():
            if rn in roles_seen and roles_seen[rn] != sp:
                clash.append(f"{sp}和{roles_seen[rn]}都自称{rn}")
            roles_seen[rn] = sp

        summary_parts = []
        if event_list:
            summary_parts.append("关键事件：" + "，".join(event_list[:5]))
        if clash:
            summary_parts.append("身份矛盾：" + "，".join(clash[:3]))
        summary = "；".join(summary_parts)
        return summary, event_list, claim_map

    def _calc_emotion(self, player, listener, exchanged, suspect):
        """根据游戏状态计算玩家的情绪，返回(情绪词, 情绪原因)"""
        name = player.name
        gs = player.game_state
        team = BOTC_ROLES.get(player.role, {}).get("team", "")
        is_evil = team in ("demon", "minion")
        listener_name = listener.name if hasattr(listener, 'name') else (listener or name)
        sus_on_me = gs.get("suspicion", {}).get(listener_name, 50)
        trust_in_me = gs.get("trust", {}).get(listener_name, 50)

        if is_evil:
            if sus_on_me > 60:
                return "紧张", f"{listener_name}在怀疑你，需要小心应对"
            if exchanged >= 3:
                return "自信", "和队友协调顺利，局势在掌控中"
            if self.day_count >= 3:
                return "谨慎", "游戏进入后期，每一步都要小心"
            return "冷静", "计划进行得很顺利"
        else:
            if suspect and exchanged >= 2:
                return "坚定", "锁定了可疑目标，准备说服对方"
            if exchanged >= 4:
                return "急切", "想尽快达成共识，推动处决"
            if sus_on_me > 50:
                return "委屈", "被怀疑了，需要解释清楚"
            if self.day_count >= 3:
                return "焦虑", "好人局势不明朗，时间紧迫"
            return "好奇", "在试探对方的信息和立场"

    def _try_llm_private(self, player, listener, exchanged):
        """45%概率用LLM生成拟人化私聊发言（含情绪+性格+游戏上下文），失败返回None"""
        if not _llm_gen or random.random() >= _LLM_PRIV_PROB:
            return None
        # 多人局降低LLM用量避免超时
        n_players = len(self.get_alive_names())
        if n_players >= 10 and random.random() >= 0.15:
            return None
        if n_players >= 8 and random.random() >= 0.30:
            return None
        name = player.name
        role = player.role
        gs = player.game_state
        effective_role = gs.get("fake_role", role) if gs.get("is_drunk") else role
        team = BOTC_ROLES.get(role, {}).get("team", "")
        suspect = self._pick_target_suspicion(player)
        listener_name = listener.name if hasattr(listener, 'name') else (listener or "某人")

        # 构建上下文
        _, _, claim_map = self._build_chat_summary(player)
        claim_str = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:5]]) if claim_map else "暂无身份声明"
        vote_info = self.game_record.get("vote_history", {})
        vote_parts = []
        if vote_info:
            for d, votes in vote_info.items():
                for v in votes:
                    vote_parts.append(f"{v.get('voter')}投了{v.get('target')}")
        vote_str = "，".join(vote_parts[:4]) if vote_parts else "暂无投票"
        suspect_str = suspect or "某人"

        # 存活/死亡
        all_names = [a.name for a in self.registry.all_agents()]
        alive_str = "、".join(a.name for a in self.registry.all_agents() if a.alive)
        dead_str = "、".join(a.name for a in self.registry.all_agents() if not a.alive) or "无"

        # 情绪
        emotion, emotion_reason = self._calc_emotion(player, listener, exchanged, suspect)

        # 性格
        ptype = getattr(getattr(player, '_personality', None), 'type_name', '中立')
        style_notes = {
            "冲动型": "直率大胆、语气强烈、不喜欢绕弯子",
            "冷静型": "理性客观、喜欢分析证据、有条理",
            "话痨型": "热情话多、喜欢讲故事、思维发散",
            "新手型": "谦虚不确定、会问别人意见、语气委婉",
        }
        style_note = style_notes.get(ptype, "自然交流")

        # 对话轮次上下文
        round_hint = ""
        if exchanged == 0:
            round_hint = "这是你们第一次私聊，先打招呼再聊正事。"
        elif exchanged <= 3:
            round_hint = "你们已经聊了几轮，继续深入讨论。"
        elif exchanged <= 6:
            round_hint = "对话已经比较深入了，可以直接谈结论。"
        else:
            round_hint = "聊了很久了，可以做总结性发言。"

        evil_hint = ""
        if team in ("demon", "minion"):
            evil_hint = "你是邪恶方，需要伪装成好人。不要暴露自己。"

        prompt = (
            f"你是{name}（角色是{effective_role}），正在玩血染钟楼桌游。"
            f"第{self.day_count}天。存活：{alive_str}。死亡：{dead_str}。"
            f"身份声明：{claim_str}。投票记录：{vote_str}。"
            f"你在和{listener_name}私聊。你最怀疑{suspect_str}。"
            f"你的性格：{style_note}。"
            f"当前情绪：{emotion}（{emotion_reason}）。"
            f"你的私人笔记：{gs.get('notes', '暂无')}。"
            f"之前发生的事：{gs.get('_summary', '无')}。"
            f"{round_hint}"
            f"{evil_hint}"
            f"请自然地聊一两句话，符合你的性格和当前情绪。不要用'首先其次'这类结构。"
        )
        system = (
            "你是血染钟楼桌游的玩家，正在用中文私聊。"
            "说话要像真人玩桌游：有情绪变化、有个性特点、会根据局势调整语气。"
            "你的私人笔记是你之前观察到的重要信息，在聊天中可以自然地引用笔记中的内容。"
            "不要机械分析，要像真实对话一样自然。"
        )
        result = _llm_gen(system, prompt, max_tokens=120, temperature=0.9)
        if result and len(result) > 8:
            return result
        return None

    def _try_llm_public(self, player):
        """30%概率用LLM生成拟人化公聊发言（无信息/分析类），失败返回None"""
        if not _llm_gen or random.random() >= _LLM_PUB_PROB:
            return None
        # 多人局降低LLM用量
        n_players = len(self.get_alive_names())
        if n_players >= 10 and random.random() >= 0.15:
            return None
            return None
        name = player.name
        role = player.role
        gs = player.game_state
        effective_role = gs.get("fake_role", role) if gs.get("is_drunk") else role
        team = BOTC_ROLES.get(role, {}).get("team", "")
        suspect = self._pick_target_suspicion(player)
        self._update_notes(player)

        # 构建上下文
        _, _, claim_map = self._build_chat_summary(player)
        claim_str = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:5]]) if claim_map else "暂无身份声明"
        vote_info = self.game_record.get("vote_history", {})
        vote_parts = []
        if vote_info:
            for d, votes in vote_info.items():
                for v in votes:
                    vote_parts.append(f"{v.get('voter')}投了{v.get('target')}")
        vote_str = "，".join(vote_parts[:4]) if vote_parts else "暂无投票"
        suspect_str = suspect or "某人"

        # 存活/死亡
        alive_str = "、".join(a.name for a in self.registry.all_agents() if a.alive)
        dead_str = "、".join(a.name for a in self.registry.all_agents() if not a.alive) or "无"

        # 情绪（公聊用 listener=None）
        emotion, emotion_reason = self._calc_emotion(player, None, 0, suspect)

        # 性格
        ptype = getattr(getattr(player, '_personality', None), 'type_name', '中立')
        style_notes = {
            "冲动型": "直率大胆、语气强烈、不喜欢绕弯子",
            "冷静型": "理性客观、喜欢分析证据、有条理",
            "话痨型": "热情话多、喜欢讲故事、思维发散",
            "新手型": "谦虚不确定、会问别人意见、语气委婉",
        }
        style_note = style_notes.get(ptype, "自然交流")

        # 身份声明矛盾
        contradict = []
        seen = {}
        for sp, rn in claim_map.items():
            if rn in seen and seen[rn] != sp:
                contradict.append(f"{sp}和{seen[rn]}都自称{rn}")
            seen[rn] = sp
        clash_str = "，".join(contradict[:2]) if contradict else ""

        # 信息角色特殊指引
        info = gs.get("known_info", {})
        day = self.day_count
        info_hint = ""
        if "empathy" in info:
            info_hint = f"你是共情者，得知相邻邪恶数={info['empathy']}"
        elif "seer" in info:
            chosen, has_demon = info["seer"]
            info_hint = f"你是占卜师，查验了{chosen[0]}和{chosen[1]}：" + ("有恶魔" if has_demon else "都不是恶魔")
        elif "investigator" in info:
            inv = info["investigator"]
            if len(inv) == 3:
                info_hint = f"你是调查员，得知{inv[0]}或{inv[1]}之中有{inv[2]}"
            else:
                info_hint = f"你是调查员，得知{inv[0]}是{inv[1]}"
        elif "chef" in info:
            info_hint = f"你是厨师，得知相邻邪恶对数={info['chef']}"
        elif "washerwoman" in info:
            ww = info["washerwoman"]
            if len(ww) == 3:
                info_hint = f"你是洗衣妇，得知{ww[0]}或{ww[1]}之中有{ww[2]}"
            else:
                info_hint = f"你是洗衣妇，得知{ww[0]}是{ww[1]}"
        elif "librarian" in info:
            lib = info["librarian"]
            if len(lib) == 3:
                if lib[0] == "无":
                    info_hint = "你是图书管理员，本局无外来者"
                else:
                    info_hint = f"你是图书管理员，得知{lib[0]}或{lib[1]}之中有外来者(可能是{lib[2]})"
            else:
                t, r = lib
                info_hint = f"你是图书管理员，得知{t}是{r}" if t != "无" else "你是图书管理员，本局无外来者"
        elif "undertaker" in info:
            info_hint = f"你是送葬者，得知被处决者是{info['undertaker']}"
        elif "ravenkeeper" in info:
            t, r = info["ravenkeeper"]
            info_hint = f"你是守鸦人，查了{t}是{r}"

        evil_hint = ""
        if team in ("demon", "minion"):
            bluff = gs.get("known_info", {}).get("current_bluff", "镇民")
            evil_hint = f"你是邪恶方，伪装的身份是{bluff}。不要在公聊中暴露自己是邪恶方。"

        prompt = (
            f"你是{name}（角色是{effective_role}），正在和大家公聊。"
            f"第{day}天。存活：{alive_str}。死亡：{dead_str}。"
            f"身份声明：{claim_str}。投票记录：{vote_str}。"
            f"{'身份矛盾：' + clash_str + '。' if clash_str else ''}"
            f"你最怀疑{suspect_str}。"
            f"你的性格：{style_note}。"
            f"当前情绪：{emotion}（{emotion_reason}）。"
            f"你的私人笔记：{gs.get('notes', '暂无')}。"
            f"{info_hint + '。' if info_hint else ''}"
            f"{evil_hint}"
            f"请自然地公聊一两句话，表达你的观点或分享信息。不要用'首先其次'这类结构。."
        )
        system = (
            "你是血染钟楼桌游的玩家，正在公开讨论阶段发言。"
            "说话要像真人玩桌游：有情绪变化、有个性特点、会根据局势调整语气。"
            "你的私人笔记是你之前观察到的重要信息，可以在发言中自然地引用。"
            "如果你有信息角色的能力结果，可以适当透露。不要机械分析，要像真实对话一样自然。"
        )
        result = _llm_gen(system, prompt, max_tokens=150, temperature=0.9)
        if result and len(result) > 8:
            return result
        return None

    def _gen_private_chat(self, player, listener):
        """基于数据集的私聊生成"""
        name = player.name
        role = player.role
        gs = player.game_state
        effective_role = gs.get("fake_role", role) if gs.get("is_drunk") else role
        team = BOTC_ROLES.get(role, {}).get("team", "")
        info = gs.get("known_info", {})
        trust = gs.get("trust", {}).get(listener, 50)
        sus = gs.get("suspicion", {}).get(listener, 50)
        suspect = self._pick_target_suspicion(player)

        exchanged = sum(1 for m in gs.get("chat_memory", [])
                      if m.get("phase") == "private_chat"
                      and ((m.get("speaker") == name and m.get("listener") == listener)
                           or (m.get("speaker") == listener and m.get("listener") == name)))

        partner_last_msg = ""
        for m in reversed(gs.get("chat_memory", [])):
            if m.get("speaker") == listener and m.get("phase") == "private_chat" and m.get("listener") == name:
                partner_last_msg = m.get("text", "")
                break

        _, _, claim_map = self._build_chat_summary(player)
        listener_claim = claim_map.get(listener, "")
        my_claim = claim_map.get(name, "")
        alive_others = [p for p in self.get_alive_names() if p not in (name, listener)]

        def _has_info_role(r):
            return r in ("占卜师","共情者","调查员","洗衣妇","图书管理员","厨师","送葬者","守鸦人")
        has_info = _has_info_role(effective_role)

        # === 构建目的驱动上下文 ===
        claim_str = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:6]])
        votes_from_game = self.game_record.get("vote_history", {})
        listener_votes = []
        speaker_votes = []
        for _, vday in votes_from_game.items():
            for v in vday:
                if v.get("voter") == listener: listener_votes.append(v.get("target"))
                if v.get("voter") == name: speaker_votes.append(v.get("target"))
        vote_str = "，".join(
            [f"{p}投了{t}" for p, t in
             ([(listener, t) for t in listener_votes] + [(name, t) for t in speaker_votes])][:4]
        ) or "暂无投票"
        # 找矛盾
        contradict = []
        seen_roles = {}
        for sp, rn in claim_map.items():
            if rn in seen_roles and seen_roles[rn] != sp:
                contradict.append(f"{sp}和{seen_roles[rn]}都自称{rn}")
            seen_roles[rn] = sp
        contradict_str = "，".join(contradict[:2])

        kwargs = dict(
            name=name, listener=listener.name if hasattr(listener, 'name') else str(listener),
            target=suspect or (alive_others[0] if alive_others else "某人"),
            suspect=suspect or "某人", role=effective_role, my_fake=effective_role,
            my_claim=my_claim or "未声明", claim=listener_claim or "身份不明",
            claim_str=claim_str, vote_str=vote_str, contradict_str=contradict_str or "暂无矛盾",
            info_share="暂无特殊信息",
            other=random.choice(alive_others) if len(alive_others) > 1 else (alive_others[0] if alive_others else "某人"),
            other_target=random.choice(alive_others) if alive_others else "某人",
            ref=partner_last_msg[partner_last_msg.find(": ")+2:][:50] if partner_last_msg and ": " in partner_last_msg else (partner_last_msg[:50] if partner_last_msg else "你的发言"),
            listener_fake=listener_claim or "镇民",
            my_note=gs.get("notes", "暂无特别记录"),
        )

        # 最近使用的模板 — 防重复
        used_key = f"_used_priv_{self.day_count}"
        used = gs.setdefault(used_key, set())

        # ----- 邪恶私聊 -----
        if team in {"demon", "minion"}:
            self._init_evil_strategy()
            evil_plan = self._evil_plan.get(name, {})
            fake_role = evil_plan.get("fake_role", "镇民")
            kwargs["my_fake"] = fake_role
            listener_fake = self._evil_plan.get(listener, {}).get("fake_role", "镇民")
            kwargs["listener_fake"] = listener_fake
            minions = info.get("minions", [])
            demon_name = info.get("demon", "")
            spy_info_dict = gs.get("known_info", {}).get("spy_info", {})

            # 邪恶私聊 LLM 尝试（35%概率，与好人私聊时更适用）
            if listener not in (minions + [demon_name] if team == "demon" else [demon_name]):
                llm_text = self._try_llm_private(player, listener, exchanged)
                if llm_text:
                    return f"{name}: {llm_text}"

            # 恶魔对爪牙
            if team == "demon" and listener in minions:
                kwargs["target"] = suspect or (alive_others[0] if alive_others else "目标")
                # Bluff讨论：恶魔首次向爪牙说明伪装分配
                if not getattr(self, '_bluff_discussed', False) and exchanged == 0:
                    self._bluff_discussed = True
                    kwargs["fake_role_pool"] = "、".join(getattr(self, '_bluff_pool', [])) or "无"
                    kwargs["demon_fake"] = self._evil_plan.get(name, {}).get("fake_role", "镇民")
                    kwargs["minion_fake"] = listener_fake
                    assigned = set(self._evil_plan[n]["fake_role"] for n in self._evil_plan)
                    spare = [r for r in getattr(self, '_bluff_pool', []) if r not in assigned]
                    kwargs["spare_suffix"] = f"剩下{spare[0]}留着备用。" if spare else "都用上了，没有多余的。"
                    t = DD.get_filled("EVIL_BLUFF_PROPOSE", used=used, **kwargs)
                    t = DD.naturalize(t)
                    return f"{name}: {t}"
                tactic = evil_plan.get("tactic", "normal")
                if tactic == "claim_battle":
                    battle_target = evil_plan.get("claim_battle_target") or suspect
                    _, _, claim_map = self._build_chat_summary(self.get_player_by_name(name))
                    battle_role = claim_map.get(battle_target, "镇民")
                    kwargs["battle_target"] = battle_target or "某人"
                    kwargs["battle_role"] = battle_role
                    kwargs["real_target"] = suspect or "某人"
                # 5阶段对话周期
                if exchanged >= 13:
                    cat = "EVIL_FINALIZE"
                elif exchanged >= 8:
                    cat = "EVIL_REHEARSE"
                elif exchanged >= 4:
                    cat = "EVIL_TARGET_COORD"
                elif exchanged >= 2 and tactic in ("sacrifice", "double_claim", "fake_solve", "info_chain", "claim_battle"):
                    cat = {"sacrifice": "EVIL_SACRIFICE", "double_claim": "EVIL_DOUBLE_CLAIM",
                           "fake_solve": "EVIL_FAKE_SOLVE", "info_chain": "EVIL_INFO_CHAIN",
                           "claim_battle": "EVIL_CLAIM_BATTLE_BRIEF"}.get(tactic, "EVIL_DEEP_PLAN")
                elif exchanged >= 1:
                    cat = "EVIL_DEEP_PLAN"
                else:
                    cat = "EVIL_FIRST_CONTACT"
                t = DD.get_filled(cat, used=used, **kwargs)
                t = DD.naturalize(t)
                return f"{name}: {t}"

            # 爪牙对恶魔（含间谍信息）
            if team == "minion" and demon_name == listener:
                kwargs["demon_name"] = demon_name
                if spy_info_dict:
                    good_players = [(n, r) for n, r in spy_info_dict.items()
                                   if BOTC_ROLES.get(r, {}).get("team") in ("townsfolk", "outsider")][:3]
                    kwargs["spy_info"] = "，".join([f"{n}是{r}" for n, r in good_players]) if good_players else "信息杂乱"
                    kwargs["target"] = good_players[0][0] if good_players else suspect
                else:
                    kwargs.setdefault("spy_info", "暂无间谍信息")
                    kwargs.setdefault("target", suspect or (alive_others[0] if alive_others else "某人"))
                # Bluff反馈：爪牙首次回应恶魔的分配
                if not getattr(self, '_bluff_discussed', False) and exchanged == 0:
                    self._bluff_discussed = True
                    kwargs["fake_role_pool"] = "、".join(getattr(self, '_bluff_pool', [])) or "无"
                    kwargs["demon_fake"] = listener_fake
                    kwargs["minion_fake"] = self._evil_plan.get(name, {}).get("fake_role", "镇民")
                    assigned = set(self._evil_plan[n]["fake_role"] for n in self._evil_plan)
                    spare = [r for r in getattr(self, '_bluff_pool', []) if r not in assigned]
                    kwargs["spare_suffix"] = f"剩下{spare[0]}留着备用。" if spare else "都用上了，没有多余的。"
                    t = DD.get_filled("MINION_BLUFF_FEEDBACK", used=used, **kwargs)
                    t = DD.naturalize(t)
                    return f"{name}: {t}"
                tactic = evil_plan.get("tactic", "normal")
                if tactic == "claim_battle":
                    battle_target = evil_plan.get("claim_battle_target") or suspect
                    _, _, claim_map = self._build_chat_summary(self.get_player_by_name(name))
                    battle_role = claim_map.get(battle_target, "镇民")
                    kwargs["battle_target"] = battle_target or "某人"
                    kwargs["battle_role"] = battle_role
                    kwargs["real_target"] = suspect or "某人"
                # 5阶段对话周期
                if exchanged >= 13:
                    cat = "EVIL_FINALIZE"
                elif exchanged >= 8:
                    cat = "EVIL_REHEARSE"
                elif exchanged >= 4:
                    cat = "EVIL_TARGET_COORD"
                elif exchanged >= 2 and tactic in ("sacrifice", "double_claim", "fake_solve", "info_chain", "claim_battle"):
                    cat = {"sacrifice": "EVIL_SACRIFICE", "double_claim": "EVIL_DOUBLE_CLAIM",
                           "fake_solve": "EVIL_FAKE_SOLVE", "info_chain": "EVIL_INFO_CHAIN",
                           "claim_battle": "EVIL_CLAIM_BATTLE_BRIEF"}.get(tactic, "EVIL_DEEP_PLAN")
                elif exchanged >= 1:
                    cat = "EVIL_DEEP_PLAN"
                else:
                    cat = "EVIL_FIRST_CONTACT"
                t = DD.get_filled(cat, used=used, **kwargs)
                t = DD.naturalize(t)
                return f"{name}: {t}"

            # 邪恶被高怀疑
            if sus > 60:
                kwargs["target"] = suspect or (alive_others[0] if alive_others else "某人")
                t = DD.get_filled("EVIL_COUNTER_ATTACK", used=used, **kwargs)
                t = DD.naturalize(t)
                return f"{name}: {t}"

            # 邪恶普通接触 — 对好人伪装式套话
            tactic = evil_plan.get("tactic", "normal")
            pocket_target = evil_plan.get("pocket_target", "")
            if exchanged >= 11:
                cat = "EVIL_GOOD_CLOSE"
            elif exchanged >= 6:
                cat = "EVIL_GOOD_PROBE"
            elif exchanged >= 2:
                if tactic == "pocket" and pocket_target and listener == pocket_target:
                    cat = "EVIL_POCKET"
                elif tactic in ("fake_solve", "info_chain"):
                    kwargs["other"] = random.choice(
                        [a for a in alive_others if a != listener]) if len(alive_others) > 1 else (alive_others[0] if alive_others else "某人")
                    cat = "EVIL_FAKE_SOLVE"
                else:
                    cat = "EVIL_GOOD_DISINFO"
            elif exchanged >= 1:
                cat = "EVIL_GOOD_DISINFO"
            else:
                cat = "EVIL_GOOD_FAKE_OPEN"
            t = DD.get_filled(cat, used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        # ----- 善良私聊（5阶段对话制）-----
        def _good_phase():
            if exchanged >= 16: return 4
            if exchanged >= 11: return 3
            if exchanged >= 6: return 2
            if exchanged >= 1: return 1
            return 0
        cp = _good_phase()
        good_phases = ["GOOD_PRIVATE_OPEN", "GOOD_PRIVATE_DISCUSS", "GOOD_PRIVATE_PERSUADE",
                       "GOOD_PRIVATE_COORDINATE", "GOOD_PRIVATE_CLOSING"]

        def _build_info_share():
            if "seer" in info:
                chosen, has = info["seer"]
                s = f"我查了{chosen[0]}和{chosen[1]}，{'有恶魔' if has else '都是好的'}"
                if has: s += f"。建议今天推{chosen[0]}"
                return s
            if "empathy" in info:
                e = info["empathy"]
                s = f"我旁边邪恶数{e}"
                if e > 0:
                    idx = self.player_order.index(name)
                    ns = [self.player_order[(idx - 1) % len(self.player_order)],
                          self.player_order[(idx + 1) % len(self.player_order)]]
                    s += f"，邻居{'、'.join(ns)}中有坏人"
                return s
            if "investigator" in info:
                return f"查到{info['investigator'][0]}是{info['investigator'][1]}"
            if "washerwoman" in info:
                ww = info["washerwoman"]
                if len(ww) == 3:
                    return f"知道{ww[0]}或{ww[1]}之中有{ww[2]}"
                return f"知道{ww[0]}是{ww[1]}"
            if "chef" in info:
                return f"相邻邪恶对数{info['chef']}"
            return f"我是{effective_role}，暂无信息"

        # 高信任渠道
        if trust > 70:
            kwargs["info_share"] = _build_info_share()
            kwargs["target"] = suspect or (alive_others[0] if alive_others else "某人")
            t = DD.get_filled(good_phases[cp], used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        # 高怀疑渠道
        if sus > 60:
            kwargs["claim"] = listener_claim or "身份不明"
            if cp >= 3:
                cat = "GOOD_PRIVATE_CLOSING"
            elif cp >= 2:
                cat = "GOOD_CONFRONT"
            elif cp >= 1:
                cat = "GOOD_PRIVATE_DISCUSS"
            else:
                cat = "GOOD_INTERROGATE"
            t = DD.get_filled(cat, used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        # ----- 洗衣妇专属策略链 -----
        if effective_role == "洗衣妇" and "washerwoman" in info:
            ww = info["washerwoman"]
            if len(ww) == 3:
                target1, target2, ww_role = ww
            else:
                target1, ww_role = ww
                target2 = ""
            kwargs["target1"] = target1
            kwargs["target2"] = target2
            kwargs["ww_role"] = ww_role

            # 首次接触目标：确认身份
            if listener in (target1, target2) and exchanged < 2:
                kwargs["target"] = listener
                t = DD.get_filled("GOOD_WASHERWOMAN_CONFIRM", used=used, **kwargs)
                t = DD.naturalize(t)
                return f"{name}: {t}"

            # 已与两个目标都聊过且都不认 → 信息矛盾分支
            partner_claims = set()
            for m in gs.get("chat_memory", []):
                sp = m.get("speaker", "")
                txt = m.get("text", "")
                if sp in (target1, target2) and "认" in txt and "洗衣妇" in txt:
                    partner_claims.add(sp)
            both_deny = len(partner_claims) == 0 and exchanged >= 4

            if both_deny:
                # 发给调查员：排查投毒者
                if listener_claim == "调查员" or BOTC_ROLES.get(self.get_player_by_name(listener).role if self.get_player_by_name(listener) else "", {}).get("team") == "townsfolk":
                    if "investigator" in info.get("investigator_listener", "") or random.random() < 0.5:
                        t = DD.get_filled("GOOD_WASHERWOMAN_POISON_SUSPECT", used=used, **kwargs)
                        t = DD.naturalize(t)
                        return f"{name}: {t}"
                # 发给图书管理员：排查男爵/酒鬼
                if listener_claim == "图书管理员" or (self.get_player_by_name(listener) and self.get_player_by_name(listener).role == "图书管理员"):
                    t = DD.get_filled("GOOD_WASHERWOMAN_BARON_SUSPECT", used=used, **kwargs)
                    t = DD.naturalize(t)
                    return f"{name}: {t}"

            # 信息清晰 → 发给调查员/占卜师共享金水
            one_confirmed = len(partner_claims) >= 1
            if one_confirmed:
                confirmed = list(partner_claims)[0]
                kwargs["target"] = confirmed
                if listener_claim == "调查员" or (self.get_player_by_name(listener) and self.get_player_by_name(listener).role == "调查员"):
                    t = DD.get_filled("GOOD_WASHERWOMAN_GOLDWATER_INV", used=used, **kwargs)
                    t = DD.naturalize(t)
                    return f"{name}: {t}"
                if listener_claim == "占卜师" or (self.get_player_by_name(listener) and self.get_player_by_name(listener).role == "占卜师"):
                    t = DD.get_filled("GOOD_WASHERWOMAN_GOLDWATER_SEER", used=used, **kwargs)
                    t = DD.naturalize(t)
                    return f"{name}: {t}"

            # 提名贞洁者自证计划（信息混乱时发给其他信息位）
            if both_deny and exchanged >= 6 and (listener_claim in ("调查员", "图书管理员") or (self.get_player_by_name(listener) and self.get_player_by_name(listener).role in ("调查员", "图书管理员"))):
                t = DD.get_filled("GOOD_WASHERWOMAN_VIRGIN_PLAN", used=used, **kwargs)
                t = DD.naturalize(t)
                return f"{name}: {t}"

        # 信息角色（首夜即获知信息，可以直接公开）
        if has_info:
            kwargs["target"] = suspect or (alive_others[0] if alive_others else "某人")
            # 信息角色也可以尝试 LLM 增强
            llm_text = self._try_llm_private(player, listener, exchanged)
            if llm_text:
                t = llm_text
            elif cp == 0:
                kwargs["info_share"] = _build_info_share()
                t = DD.get_filled("GOOD_PRIVATE_OPEN", used=used, **kwargs)
            elif cp == 1:
                kwargs["info_share"] = _build_info_share()
                t = DD.get_filled("GOOD_PRIVATE_DISCUSS", used=used, **kwargs)
            elif cp >= 2:
                kwargs["info_share"] = _build_info_share()
                t = DD.get_filled(good_phases[cp], used=used, **kwargs)
            else:
                t = DD.get_filled("GOOD_INFO_PROBE", used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        # 无信息角色 — 尝试 LLM 增强
        kwargs["target"] = suspect or (alive_others[0] if alive_others else "某人")
        noninfo_phases = ["GOOD_PRIVATE_OPEN", "GOOD_NOINFO_PROBE", "GOOD_PRIVATE_PERSUADE",
                          "GOOD_PRIVATE_COORDINATE", "GOOD_PRIVATE_CLOSING"]
        llm_text = self._try_llm_private(player, listener, exchanged)
        t = llm_text if llm_text else DD.get_filled(noninfo_phases[cp], used=used, **kwargs)
        t = DD.naturalize(t)
        return f"{name}: {t}"

    def _gen_dead_speech(self, player):
        """基于数据集的死者发言"""
        name = player.name
        gs = player.game_state
        info = gs.get("known_info", {})
        _, _, claim_map = self._build_chat_summary(player)
        suspect = self._pick_target_suspicion(player)
        alive_names = self.get_alive_names()
        kwargs = dict(name=name, target=suspect or "某人",
                      other=random.choice([p for p in alive_names if p != name]) if alive_names else "某人")

        # 构建上下文
        claim_str = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:5]])
        vote_info = self.game_record.get("vote_history", {})
        vote_str = "，".join(
            [f"{p}投了{t}" for day in vote_info.values() for v in day
             for p, t in [(v.get("voter"), v.get("target"))]][:4]
        ) or ""
        contradict = []
        seen = {}
        for sp, rn in claim_map.items():
            if rn in seen and seen[rn] != sp:
                contradict.append(f"{sp}和{seen[rn]}都自称{rn}")
            seen[rn] = sp
        cstr = "，".join(contradict[:2])
        kwargs.update(claim_str=claim_str, vote_str=vote_str, contradict_str=cstr,
                      claims_summary=claim_str, clash_info=cstr, summary=claim_str + ("；" + cstr if cstr else ""))

        used_key = f"_used_dead_{self.day_count}"
        used = gs.setdefault(used_key, set())

        if "undertaker" in info:
            exec_role = info["undertaker"]
            verdict = "处决对了！" if exec_role in BOTC_TEAMS['demon'] + BOTC_TEAMS['minion'] else "处决错了……"
            kwargs.update(exec_role=exec_role, verdict=verdict)
            text = DD.get_filled("DEAD_UNDERTAKER", used=used, **kwargs)
            text = DD.naturalize(text)
            return f"{name}(已死亡): {text}"

        if "ravenkeeper" in info:
            rk_target, rk_role = info["ravenkeeper"]
            team_label = "邪恶阵营" if rk_role in BOTC_TEAMS['demon'] + BOTC_TEAMS['minion'] else "善良阵营"
            kwargs.update(rk_target=rk_target, rk_role=rk_role, team=team_label)
            text = DD.get_filled("DEAD_RAVENKEEPER", used=used, **kwargs)
            text = DD.naturalize(text)
            return f"{name}(已死亡): {text}"

        kwargs["target"] = suspect or random.choice(list(claim_map.keys())) if claim_map else "某人"
        kwargs["other"] = random.choice([p for p in claim_map if p != kwargs["target"]]) if len(claim_map) > 1 else "某人"
        text = DD.get_filled("DEAD_ANALYSIS", used=used, **kwargs)
        text = DD.naturalize(text)
        return f"{name}(已死亡): {text}"

    def _gen_public_chat(self, player):
        """基于数据集和角色信息的公聊发言"""
        name = player.name
        role = player.role
        gs = player.game_state
        effective_role = gs.get("fake_role", role) if gs.get("is_drunk") else role
        team = BOTC_ROLES.get(role, {}).get("team", "")
        info = gs.get("known_info", {})
        suspect = self._pick_target_suspicion(player)
        day = self.day_count
        _, _, claim_map = self._build_chat_summary(player)

        def _claim_of(p):
            return claim_map.get(p, "?")

        # ----- 邪恶公聊 -----
        if team in {"minion", "demon"}:
            self._init_evil_strategy()
            evil_plan = self._evil_plan.get(name, {})
            target_for_accusation = suspect
            if not target_for_accusation and claim_map:
                candidates = [p for p in claim_map if p != name]
                if candidates:
                    target_for_accusation = random.choice(candidates)

            if team == "demon" and "fake_roles" in info:
                bluff = info.get("current_bluff")
                if not bluff:
                    bluff = random.choice(info["fake_roles"])
                    info["current_bluff"] = bluff
            else:
                bluff = evil_plan.get("fake_role", "镇民")

            accusation = ""
            if day > 1 and target_for_accusation:
                tc = _claim_of(target_for_accusation)
                if tc:
                    vote_info = self.game_record.get("vote_history", {})
                    tv = []
                    for _, votes in vote_info.items():
                        for v in votes:
                            if v.get("voter") == target_for_accusation:
                                tv.append(v.get("target"))
                    if tv:
                        accusation = f"{target_for_accusation}自称{tc}，但投票处决过{'/'.join(tv[:2])}，行为对不上！"
                    else:
                        accusation = f"{target_for_accusation}自称{tc}，但发言和这个身份不符。"
                elif team == "demon" and "fake_roles" in info:
                    for sp, rn in claim_map.items():
                        if sp != name and rn == bluff:
                            accusation = f"{sp}也自称{bluff}——他在冒充我！"
                            break
                if not accusation:
                    silent = [p for p in self.get_alive_names() if p != name and p not in claim_map]
                    if silent and random.random() < 0.4:
                        accusation = f"{random.choice(silent)}一直不报身份，很可疑。"

            # 构建公聊上下文（排除自己的声明）
            others_claim = {p: r for p, r in claim_map.items() if p != name}
            claim_str = "，".join([f"{p}自称{r}" for p, r in list(others_claim.items())[:6]]) if others_claim else ""
            vote_info = self.game_record.get("vote_history", {})
            vote_str = "，".join(
                [f"{p}投了{t}" for day_ in vote_info.values() for v in day_
                 for p, t in [(v.get("voter"), v.get("target"))]][:4]
            ) or ""
            contradict = []
            seen = {}
            for sp, rn in others_claim.items():
                if rn in seen and seen[rn] != sp:
                    contradict.append(f"{sp}和{seen[rn]}都自称{rn}")
                seen[rn] = sp
            cstr = "，".join(contradict[:2])

            kwargs = dict(name=name, target=target_for_accusation or "某人", accusation=accusation,
                         bluff=bluff, fake_info=self._gen_consistent_fake_info(name, bluff),
                         claim_str=claim_str, vote_str=vote_str, contradict_str=cstr, claim="?",
                         other=random.choice(list(claim_map.keys())) if claim_map else "某人",
                         other_target=random.choice(list(claim_map.keys())) if claim_map else "某人")

            # ----- 身份对跳检测 -----
            claim_battle_msg = self._detect_claim_battle(name, evil_plan, claim_map, claim_str, vote_str)
            if claim_battle_msg:
                return f"{name}: {claim_battle_msg}"

            # 邪恶公聊 LLM 尝试（30%概率）
            llm_text = self._try_llm_public(player)
            if llm_text:
                return f"{name}: {llm_text}"

            used_pub = self.game_record.setdefault(f"_used_pub_{self.day_count}", set())

            if team == "demon":
                t = DD.get_filled("DEMON_PUBLIC_ATTACK" if accusation else "DEMON_PUBLIC_SOFT", used=used_pub, **kwargs)
                t = DD.naturalize(t)
                return f"{name}: {t}"

            if team == "minion":
                minion_bluff = evil_plan.get("fake_role", "")
                if minion_bluff and minion_bluff in ("洗衣妇", "图书管理员", "厨师", "调查员", "共情者", "占卜师"):
                    t = DD.get_filled("MINION_PUBLIC_ATTACK", used=used_pub, **kwargs)
                elif accusation:
                    t = f"{accusation}"
                else:
                    t = DD.get_filled("MINION_PUBLIC_ATTACK", used=used_pub, **kwargs)
                t = DD.naturalize(t)
                return f"{name}: {t}"

        # ----- 善良公聊 -----
        # 构建公聊上下文（排除自己的声明）
        others_claim = {p: r for p, r in claim_map.items() if p != name}
        claim_str = "，".join([f"{p}自称{r}" for p, r in list(others_claim.items())[:6]]) if others_claim else ""
        vote_info = self.game_record.get("vote_history", {})
        vote_str = "，".join(
            [f"{p}投了{t}" for day_ in vote_info.values() for v in day_
             for p, t in [(v.get("voter"), v.get("target"))]][:4]
        ) or ""
        contradict = []
        seen = {}
        for sp, rn in others_claim.items():
            if rn in seen and seen[rn] != sp:
                contradict.append(f"{sp}和{seen[rn]}都自称{rn}")
            seen[rn] = sp
        cstr = "，".join(contradict[:2])

        def _claim_of(p):
            return claim_map.get(p, "?")

        used_key = f"_used_pub_{self.day_count}"
        used = self.game_record.setdefault(used_key, set())

        kwargs = dict(name=name, role=effective_role, target=suspect or "某人", suspect=suspect or "某人",
                     claim_str=claim_str, vote_str=vote_str, contradict_str=cstr,
                     claim=_claim_of(suspect) if suspect else "?", voted="某人",
                     other=random.choice(list(claim_map.keys())) if claim_map else "某人",
                     other_target=random.choice(list(claim_map.keys())) if claim_map else "某人",
                     my_note=gs.get("notes", "暂无特别记录"))

        if "empathy" in info:
            e = info["empathy"]
            idx = self.player_order.index(name)
            ns = [self.player_order[(idx - 1) % len(self.player_order)],
                  self.player_order[(idx + 1) % len(self.player_order)]]
            kwargs.update(e=e, neighbor_info="，".join([f"{n}(自称{_claim_of(n)})" for n in ns]))
            t = DD.get_filled("GOOD_PUBLIC_EMPATHY", used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        if "seer" in info:
            chosen, has_demon = info["seer"]
            kwargs.update(chosen0=chosen[0], chosen1=chosen[1],
                         result="有恶魔！这两人必须处决一个" if has_demon else "都不是恶魔",
                         demon_verdict="有恶魔嫌疑" if has_demon else "排除了两个好人",
                         suggestion=f"我建议从{chosen[0]}开始处决" if has_demon else "")
            t = DD.get_filled("GOOD_PUBLIC_SEER", used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        if "investigator" in info:
            inv = info["investigator"]
            if len(inv) == 3:
                t1, t2, t_role = inv
                target_str = f"{t1}/{t2}"
            else:
                t1, t_role = inv
                target_str = t1
            kwargs.update(target=target_str, role=t_role)
            t = DD.get_filled("GOOD_PUBLIC_INVESTIGATOR", used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        # ----- 洗衣妇公聊 -----
        if "washerwoman" in info:
            ww = info["washerwoman"]
            if len(ww) == 3:
                t1, t2, shown = ww
            else:
                t1, shown = ww
                t2 = ""
            kwargs["target1"] = t1
            kwargs["target2"] = t2
            kwargs["ww_role"] = shown

            # 检查两个目标是否有人认领
            partner_claims = []
            for m in gs.get("chat_memory", []):
                sp = m.get("speaker", "")
                txt = m.get("text", "")
                if sp in (t1, t2):
                    partner_claims.append(sp)
                    if "是" + shown in txt or "认" in txt:
                        partner_claims.append("CONFIRMED_" + sp)
            confirmed = [c.replace("CONFIRMED_", "") for c in partner_claims if c.startswith("CONFIRMED_")]
            both_deny = not confirmed and len(partner_claims) >= 2

            if confirmed:
                kwargs["target"] = confirmed[0]
                t = DD.get_filled("GOOD_PUBLIC_WASHERWOMAN_CLEAR", used=used, **kwargs)
            elif both_deny:
                # 检查是否已有贞洁者提名计划
                has_virgin_plan = False
                for m in gs.get("chat_memory", []):
                    if "贞洁者" in m.get("text", "") and "提名" in m.get("text", ""):
                        has_virgin_plan = True
                        break
                if has_virgin_plan:
                    t = DD.get_filled("GOOD_PUBLIC_WASHERWOMAN_VIRGIN", used=used, **kwargs)
                else:
                    t = DD.get_filled("GOOD_PUBLIC_WASHERWOMAN_CONFUSED", used=used, **kwargs)
            else:
                kwargs["target"] = t1
                t = DD.get_filled("GOOD_PUBLIC_WASHERWOMAN_CLEAR", used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        # 其他信息角色
        info_or_opinion = ""
        if "chef" in info:
            info_or_opinion = f"厨师结果：相邻邪恶对数{info['chef']}"
        elif "washerwoman" in info:
            ww = info["washerwoman"]
            if len(ww) == 3:
                t1, t2, shown = ww
                info_or_opinion = f"洗衣妇信息：{t1}或{t2}之中有{shown}"
            else:
                info_or_opinion = f"洗衣妇信息：{ww[0]}是{ww[1]}"
        elif "librarian" in info:
            lib = info["librarian"]
            if len(lib) == 3:
                t1, t2, msg = lib
                if t1 == "无":
                    info_or_opinion = "图书管理员信息：本局没有外来者"
                else:
                    info_or_opinion = f"图书管理员：{t1}或{t2}之中有外来者(可能是{msg})"
            else:
                t, r = lib
                info_or_opinion = f"图书管理员：{t}是{r}" if t != "无" else "本局无外来者"
        elif "undertaker" in info:
            info_or_opinion = f"送葬者：被处决的是{info['undertaker']}"
        elif "ravenkeeper" in info:
            t, r = info["ravenkeeper"]
            info_or_opinion = f"守鸦人查了{t}是{r}"
        elif "chef" in info:
            info_or_opinion = f"厨师结果：{info['chef']}"
        else:
            info_or_opinion = "暂无特殊信息"

        if info_or_opinion:
            kwargs["info_or_opinion"] = info_or_opinion
            kwargs["opinion"] = f"基于以上，我怀疑{suspect or '某人'}"

        # LLM 公聊尝试（用于非结构化公聊场景）
        llm_text = self._try_llm_public(player)
        if llm_text:
            return f"{name}: {llm_text}"

        # 无信息角色——第二天后做分析
        if day > 1 and claim_map:
            kwargs["claims_summary"] = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:6]])
            clash = []
            roles_seen = {}
            for sp, rn in claim_map.items():
                if rn in roles_seen and roles_seen[rn] != sp:
                    clash.append(f"{sp}和{roles_seen[rn]}都自称{rn}")
                roles_seen[rn] = sp
            kwargs["clash_info"] = "，".join(clash[:2]) if clash else ""
            voted = self.game_record.get("vote_history", {})
            target_votes = []
            if suspect:
                for _, votes in voted.items():
                    for v in votes:
                        if v.get("voter") == suspect:
                            target_votes.append(v.get("target"))
            kwargs["voted"] = "/".join(target_votes[:2]) if target_votes else "某人"
            kwargs["claim"] = _claim_of(suspect) if suspect else "?"
            text = DD.get_filled("GOOD_PUBLIC_ANALYSIS", used=used, **kwargs)
            text = DD.naturalize(text)
            return f"{name}: {text}"

        # 无信息角色第一天
        kwargs["info_or_opinion"] = "暂时没有关键信息"
        kwargs["opinion"] = f"我会重点观察{suspect or '大家的发言'}"
        text = DD.get_filled("GOOD_PUBLIC_ANALYSIS", used=used, **kwargs)
        text = DD.naturalize(text)
        return f"{name}: {text}"

    def _update_notes(self, player):
        """从 chat_memory 提取关键信息更新私人笔记"""
        gs = player.game_state
        day = self.day_count
        diary = gs.setdefault("diary", {})
        if day not in diary:
            diary[day] = []
        today_notes = diary[day]
        memory = gs.get("chat_memory", [])
        ptype = getattr(player, "_personality", None)
        pname = ptype.type_name if ptype else ""
        is_talkative = pname == "话痨型"
        max_notes = 4 if is_talkative else 3

        import re
        for m in memory:
            if m.get("day") != day:
                continue
            text = m.get("text", "")
            speaker = m.get("speaker", "")
            if not text or not speaker:
                continue
            claims = re.findall(r'我是([\u4e00-\u9fa5]{2,4})', text)
            for c in claims:
                if c in (BOTC_TEAMS.get("townsfolk", []) + BOTC_TEAMS.get("outsider", []) + BOTC_TEAMS.get("minion", [])):
                    note = f"{speaker}自称{c}"
                    if note not in today_notes:
                        today_notes.append(note)
            if any(w in text for w in ["怀疑", "可疑", "说我是", "投了", "处决"]):
                for t in re.findall(r'([\u4e00-\u9fa5]{2,3})[是个]*(?:可疑|有问题|不是好人|在撒谎)', text):
                    pass

        suspect = self._pick_target_suspicion(player)
        if suspect and not any(suspect in n for n in today_notes):
            today_notes.append(f"我最怀疑{suspect}")

        today_notes[:] = today_notes[-max_notes:]

        # 跨天记忆：引用前一天的重要笔记
        prev_day_notes = diary.get(day - 1, [])
        cross_ref = ""
        if prev_day_notes and day > 1:
            important_prev = [n for n in prev_day_notes if any(w in n for w in ["怀疑", "自称", "处决", "翻出"])]
            if important_prev:
                cross_ref = "（昨天记的：" + "；".join(important_prev[-2:]) + "）"

        gs["notes"] = "；".join(today_notes) if today_notes else "暂无特别记录"
        if cross_ref:
            gs["notes"] += cross_ref

    def _gen_speech(self, player, listener=None):
        """数据驱动发言生成 V3 - 人格化 + 长推理链 + 笔记增强"""
        name = player.name
        gs = player.game_state
        team = BOTC_ROLES.get(gs.get("role", player.role), {}).get("team", "")
        dead = not player.alive
        assign_personality(player)
        set_current_personality(player._personality)
        p = player._personality
        self._update_notes(player)
        summary, events, claim_map = self._build_chat_summary(player)
        gs["_summary"] = summary
        gs["_events"] = events

        if listener:
            text = self._gen_private_chat(player, listener)
        elif dead:
            text = self._gen_dead_speech(player)
        else:
            bluff_text = self._detect_good_bluff(player, claim_map)
            if bluff_text:
                text = f"{name}: {bluff_text}"
            else:
                text = self._gen_public_chat(player)
        return text

    def _detect_good_bluff(self, player, claim_map):
        """善良方诈身份：好人也敢假跳信息位钓鱼"""
        name = player.name
        role = player.role
        gs = player.game_state
        effective_role = gs.get("fake_role", role) if gs.get("is_drunk") else role
        team = BOTC_ROLES.get(role, {}).get("team", "")
        if team not in ("townsfolk", "outsider"):
            return None
        info = gs.get("known_info", {})
        # 信息角色不诈（已经有真信息了）
        if any(k in info for k in ("seer", "empathy", "investigator", "washerwoman", "chef", "ravenkeeper")):
            return None
        # 公聊第2天后且有可疑目标时才诈
        suspect = self._pick_target_suspicion(player)
        if not suspect or self.day_count < 2:
            return None
        # 30%概率诈身份
        if random.random() > 0.30:
            return None
        # 已诈过的不重复诈
        if gs.get("_bluffed_already"):
            return None
        gs["_bluffed_already"] = True
        _, _, claim_map_live = self._build_chat_summary(player)
        text = gen_good_bluff(name, effective_role, info, suspect, claim_map_live,
                              self.game_record.get("vote_history", {}))
        text = DD.naturalize(text)
        return text

    def _detect_claim_battle(self, name, evil_plan, claim_map, claim_str="", vote_str=""):
        """检测身份对跳机会：好人声称了高价值角色，邪恶方冒名顶替制造混乱"""
        tactic = evil_plan.get("tactic", "")
        if tactic != "claim_battle":
            return None
        alive_names = [a for a in self.get_alive_names() if a != name]
        battle_roles = {"猎手": "CLAIM_BATTLE_HUNTSMAN", "士兵": "CLAIM_BATTLE_SOLDIER",
                        "僧侣": "CLAIM_BATTLE_MONK", "镇长": "CLAIM_BATTLE_MAYOR",
                        "占卜师": "CLAIM_BATTLE_SEER",
                        "镇民": None}  # none = use generic, 镇民匹配所有非特定角色
        # 扫描所有存活好人的声称，优先对跳高价值角色，任意角色均可触发
        candidates = [(sp, rn) for sp, rn in claim_map.items()
                      if sp != name and sp in alive_names]
        if not candidates:
            return None
        # 按优先级排序: 猎手=0, 占卜师=1, 僧侣=2, 士兵=3, 镇长=4, 其他=5
        priority = {"猎手": 0, "占卜师": 1, "僧侣": 2, "士兵": 3, "镇长": 4}
        candidates.sort(key=lambda x: priority.get(x[1], 5))
        battle_target, claimed_role = candidates[0]
        cat = battle_roles.get(claimed_role)
        if cat is None:
            cat = "CLAIM_BATTLE_GENERIC"
        if not cat:
            return None
        used = evil_plan.get("_battle_used", set())
        extra = dict(battle_target=battle_target, battle_role=claimed_role,
                     claim_str=claim_str, vote_str=vote_str)
        if claimed_role == "猎手":
            extra["battle_victim"] = random.choice(alive_names) if alive_names else "某人"
        elif claimed_role == "僧侣":
            extra["defend_target"] = random.choice(alive_names) if alive_names else "某人"
        elif claimed_role == "占卜师":
            pool = alive_names[:]
            if battle_target in pool:
                pool.remove(battle_target)
            random.shuffle(pool)
            extra["checked1"] = pool[0] if pool else "某人"
            extra["checked2"] = pool[1] if len(pool) > 1 else pool[0] if pool else "某人"
            has_demon = random.random() < 0.5
            extra["result"] = "有恶魔反应！这两人必须盘" if has_demon else "都是好人，排除了两个选项"
        t = DD.get_filled(cat, used=used, **extra)
        t = DD.naturalize(t)
        evil_plan.setdefault("_battle_used", set()).update(used)
        return t

    def _gen_fake_info(self, name, bluff_role):
        """生成伪装角色的假信息——邪恶方直接捏造指向好人的伪证据"""
        alive_names = [a for a in self.get_alive_names() if a != name]
        others_pool = alive_names[:]
        random.shuffle(others_pool)
        if not others_pool:
            return ""
        v1 = others_pool[0]
        v2 = others_pool[1] if len(others_pool) > 1 else v1
        v3 = others_pool[2] if len(others_pool) > 2 else v1

        # 使用邪恶计划中的协调目标
        evil_plan = self._evil_plan.get(name, {})
        common_target = evil_plan.get("common_target")
        if common_target and common_target in alive_names:
            v1 = common_target
            others_pool = [a for a in others_pool if a != common_target]
            v2 = others_pool[0] if others_pool else v1
            v3 = others_pool[1] if len(others_pool) > 1 else v1

        exec_ref = ""
        if self.day_count >= 2 and self.last_executed:
            exec_ref = f"昨天被处决的{self.last_executed}大家还记得吧？"

        # 检查历史宣称，保持一致性
        fake_log = self._evil_fake_log.get(name, {})
        prev_day = fake_log.get(self.day_count - 1, {}) if self.day_count > 1 else {}

        fakes = {
            "共情者": random.choice([
                f"昨晚我旁边的邪恶数是{random.randint(1,2)}！{v1}和{v2}里至少有一个是坏人，大家盯紧他们。",
                f"{exec_ref}昨晚共情感应告诉我左右两边有{random.randint(1,2)}个邪恶——我建议先从{v1}开始查。",
                f"我的共情者技能明确显示{v1}有问题——他旁边的人邪恶值很高，数据不会骗人。",
                f"共情者再报数：{v1}让我很不舒服——我的技能告诉我他周围的邪恶浓度很高。",
            ]),
            "占卜师": random.choice([
                f"昨晚我查验了{v1}和{v2}——有恶魔反应！这两人必须处决一个，我建议先动{v1}。",
                f"{exec_ref}我的占卜结果出来了：{v1}是邪恶的！昨晚我清清楚楚查到了恶魔的气息。",
                f"占卜结果：{v1}有恶魔嫌疑，{v2}也不干净。我拿命担保{v1}绝对有问题。",
                f"占卜师又查了一夜：{v1}身上有邪恶痕迹，{v2}也逃不了干系。今天必须出{v1}。",
            ]),
            "厨师": random.choice([
                f"厨师结果显示有{random.randint(1,2)}对相邻邪恶——{v1}和{v2}坐在一起不是巧合，他们很可能是搭档。",
                f"{exec_ref}邪恶分布告诉我{v1}和{v2}有问题——相邻邪恶对数指向这对组合。",
                f"昨晚我算出有{random.randint(1,2)}对邪恶相邻，排除一下位置就知道{v1}逃不掉。",
            ]),
            "洗衣妇": random.choice([
                f"我是洗衣妇，昨晚确认了{v1}的真实身份——他不是他声称的那个人！他在撒谎。",
                f"{exec_ref}洗衣妇的信息链是完整的，我查到的结果明确指向{v1}身份造假。",
                f"洗衣妇手里有{v1}的实锤信息——他说自己是好人，但我的技能告诉我他在编。",
            ]),
            "调查员": random.choice([
                f"调查员有重要发现！{v1}是{random.choice(['男爵', '投毒者', '红唇女郎', '间谍'])}——他就是爪牙！证据确凿，今天必须处决他！",
                f"{exec_ref}调查结果确认{v1}是邪恶阵营，我查到了铁证。大家不要被他的辩解迷惑。",
                f"我查了{v1}的身份——爪牙！这还有什么好说的？投票处决！",
            ]),
            "图书管理员": random.choice([
                f"图书管理员确认{v1}是外来者——但他自己声称是镇民！他在隐瞒身份，这本身就是最大的疑点。",
                f"{exec_ref}我的信息显示{v1}的身份声明对不上——他要么是邪恶在编，要么在隐藏什么。",
                f"图书管理员查到了：{v1}根本不是他说的那个身份。他为什么撒谎？因为他是邪恶！",
            ]),
            "僧侣": random.choice([
                f"昨晚我保护了{v1}但他还是被杀了？不，等等，我保护的是{v2}——这说明恶魔昨晚想刀{v2}，被我挡住了。",
                f"{exec_ref}僧侣的技能让我知道恶魔的目标是{v1}附近的人——这说明{v1}大概率是好人被盯上了，那他的对立面{v2}就非常可疑。",
            ]),
            "士兵": "我是士兵，昨晚恶魔刀了我但我没死！说明我确实是士兵。有我活着在，邪恶就永远少一刀。",
            "送葬者": random.choice([
                f"送葬者技能揭示：昨天被处决的人是好人！投票处决他的人里面，{v1}和{v2}跟票最快——他们急着灭口。",
                f"{exec_ref}作为送葬者我查到了关键信息：被处决者的真实身份是好人——那些带头投他的人里一定有邪恶在推波助澜。",
                f"送葬者报信：白天被处决的是好人！处决错了……那{v1}和{v2}的投票就有大问题。",
            ]),
        }
        default_msgs = [
            f"我严重怀疑{v1}——他的发言逻辑前后矛盾，明显在编故事。",
            f"大家注意{v1}，他的投票轨迹不对——好人不这样投票。",
            f"我觉得{v1}和{v2}有勾结——他们的投票高度一致，不是巧合。",
            f"我从{v1}的发言中嗅到了谎言的味道——他太急于证明自己了，真正的好人不需要反复强调。",
        ]

        msg = fakes.get(bluff_role, random.choice(default_msgs))

        # 记录到假信息日志
        self._evil_fake_log.setdefault(name, {})[self.day_count] = {
            "claimed_role": bluff_role,
            "target": v1,
            "target2": v2,
            "message": msg[:60],
        }

        return msg

    def _gen_consistent_fake_info(self, name, bluff_role):
        """生成一致的假信息——引用历史宣称，前後连贯"""
        msg = self._gen_fake_info(name, bluff_role)

        # 如果有前一天的信息，引用作为「连续验证」
        fake_log = self._evil_fake_log.get(name, {})
        prev = fake_log.get(self.day_count - 1) if self.day_count > 1 else None
        if prev and prev.get("target") and self.day_count >= 2:
            prev_target = prev["target"]
            alive = self.get_alive_names()
            if prev_target in alive:
                prefix = random.choice([
                    f"我昨天就说了{prev_target}有问题，今天我的{bluff_role}技能再次确认了这一点——",
                    f"跟昨天一样，我的{bluff_role}查到的结果还是指向{prev_target}——这不是巧合，而是铁证！",
                    f"连续两天了，我的{bluff_role}信息都指向{prev_target}——一个人可以被冤枉一次，但不会被连续误判两次！",
                ])
                msg = prefix + msg
        return msg

    def _gen_hunter_decision(self, hunter):
        """猎手推理决策：基于聊天记忆和已知信息判断最佳目标"""
        gs = hunter.game_state
        memory = gs.get("chat_memory", [])
        known = gs.get("known_info", {})

        # 优先打自己怀疑分数最高的人
        if gs.get("suspicion"):
            sorted_suspects = sorted(gs["suspicion"].items(), key=lambda x: -x[1])
            if sorted_suspects:
                top = sorted_suspects[0]
                if top[1] >= 70:  # 怀疑度>=70才开枪
                    return top[0]

        # 有已知信息的用信息决策
        if "seer" in known:
            chosen, has = known["seer"]
            if has and chosen:
                return chosen[0]

        # 第一天随机射杀（排除法）
        if self.day_count <= 1:
            alive = [a.name for a in self.registry.all_alive() if a.name != hunter.name]
            if alive:
                return random.choice(alive)

        # 第二天起：找声称身份有矛盾的
        for entry in reversed(memory):
            for rn in BOTC_ROLES:
                if f"我是{rn}" in entry.get("text", ""):
                    speaker = entry["speaker"]
                    if speaker != hunter.name:
                        return speaker

        # 默认最可疑
        alive = [a.name for a in self.registry.all_alive() if a.name != hunter.name]
        return alive[0] if alive else None

    def _public_chat_phase(self):
        """公聊环节 - 所有人(含死人)均可发言"""
        self.log(f"\n--- [公聊环节] 玩家公开讨论 ---")
        self.game_phase = f"PUBLIC_CHAT_D{self.day_count}"

        alive_names = self.get_alive_names()

        # 猎手技能：基于推理决定是否开枪（每局一次，包括酒鬼猎手也能"开枪"但不生效）
        hunters = [a for a in self.registry.all_alive() if a.role == "猎手" and a.name not in self.hunter_used]
        drunk_hunters = [a for a in self.registry.all_alive() if a.game_state.get("is_drunk")
                         and a.game_state.get("fake_role") == "猎手" and a.name not in self.hunter_used]
        for hunter in hunters + drunk_hunters:
            is_drunk_hunter = hunter in drunk_hunters
            self._update_suspicion_from_chat(hunter)
            target = self._gen_hunter_decision(hunter)
            if target:
                self.hunter_used.add(hunter.name)
                target_agent = self.get_player_by_name(target)
                sus_score = hunter.game_state.get("suspicion", {}).get(target, 50)
                if sus_score >= 80:
                    shot_speech = f"我开枪射杀{target}！他是我最怀疑的人，必须解决！"
                elif sus_score >= 60:
                    shot_speech = f"我开枪射杀{target}！他的言行非常可疑，我赌他是恶魔！"
                else:
                    shot_speech = f"我开枪射杀{target}！虽然不确定，但概率上他最值得一试！"
                if is_drunk_hunter:
                    self.log(f"  [猎手·酒鬼] {hunter.name}: {shot_speech} 但酒鬼的枪是空的，没人受伤。")
                elif target_agent and target_agent.role in BOTC_TEAMS["demon"]:
                    target_agent.alive = False
                    self.dead_players.append(target)
                    self.log(f"  [猎手] {hunter.name}: {shot_speech} {target}是恶魔，一枪毙命！")
                    self._check_game_end()
                    if self.game_record.get('result'):
                        return
                else:
                    self.log(f"  [猎手] {hunter.name}: {shot_speech} 但{target}不是恶魔，能力已消耗。")

        if self.game_record.get('result'):
            return

        # 公聊发言前更新每个玩家的怀疑度 + 存入所有人记忆
        all_names = [a.name for a in self.registry.all_agents()]
        for player in self.registry.all_agents():
            self._update_suspicion_from_chat(player)
            speech = self._gen_speech(player)
            context = f"公聊环节, 存活: {self.get_alive_names()}"
            self.record_action(player.name, context, speech, "speech")
            self.log(f"  {speech}")
            # 存入所有玩家的聊天记忆
            self._store_chat(player.name, "all", speech, "public_chat")
            # 记录身份声明
            for role_name in BOTC_ROLES:
                if f"我是{role_name}" in speech:
                    self.public_claims[player.name] = role_name
                    break

    def _init_evil_strategy(self):
        """初始化邪恶阵营高级战术"""
        if hasattr(self, '_evil_inited'):
            self._reevaluate_evil_tactics()
            return
        self._evil_inited = True
        self._evil_plan = {}
        self._evil_vote_target = {}      # 每轮邪恶统一投票目标
        self._evil_fake_log = {}         # {evil_name: {day: {claimed_role, claimed_info, target}}}

        demons = [a for a in self.registry.all_agents() if a.role in BOTC_TEAMS["demon"]]
        minions = [a for a in self.registry.all_agents() if a.role in BOTC_TEAMS["minion"]]

        # 更丰富的战术池
        tactics_pool = [
            "normal", "normal", "sacrifice", "double_claim",
            "fake_solve", "pocket", "info_chain", "claim_battle",
            "bus", "deep_cover", "role_swap", "info_chain"
        ]
        random.shuffle(tactics_pool)

        for demon in demons:
            gs = demon.game_state
            fake_roles = list(gs.get("known_info", {}).get("fake_roles", []))
            self._bluff_pool = list(fake_roles)
            random.shuffle(fake_roles)
            chosen_bluff = fake_roles.pop(0) if fake_roles else "镇民"
            tactic = tactics_pool.pop()
            self._evil_plan[demon.name] = {
                "fake_role": chosen_bluff,
                "strategy": "lead",
                "tactic": tactic,
                "pocket_target": None,
                "sacrifice_partner": None,
                "claim_pair": None,
                "claim_battle_target": None,
                "fake_data": {},
                "vote_with": [],           # 和谁统一投票
                "vote_against": [],        # 假装投队友骗信任
                "claimed_info_history": [], # 每日声称的假信息列表
                "current_kill_target": None,
            }

        for minion in minions:
            if fake_roles:
                chosen = fake_roles.pop(0)
            else:
                chosen = random.choice(["洗衣妇", "图书管理员", "厨师", "士兵", "僧侣", "管家"])
            tactic = tactics_pool.pop()
            self._evil_plan[minion.name] = {
                "fake_role": chosen,
                "strategy": "support",
                "tactic": tactic,
                "pocket_target": None,
                "sacrifice_partner": None,
                "claim_pair": None,
                "claim_battle_target": None,
                "fake_data": {},
                "vote_with": [],
                "vote_against": [],
                "claimed_info_history": [],
                "current_kill_target": None,
            }

        self._setup_evil_tactics()

    def _setup_evil_tactics(self):
        """高级战术参数配置"""
        evil_names = list(self._evil_plan.keys())
        if len(evil_names) < 2:
            return

        alive_good = [a for a in self.registry.all_agents()
                      if a.alive and a.role not in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]]
        common_target = random.choice(alive_good).name if alive_good else None

        double_claim_players = [n for n, p in self._evil_plan.items() if p["tactic"] == "double_claim"]
        sacrifice_players = [n for n, p in self._evil_plan.items() if p["tactic"] == "sacrifice"]
        pocket_players = [n for n, p in self._evil_plan.items() if p["tactic"] == "pocket"]
        bus_players = [n for n, p in self._evil_plan.items() if p["tactic"] == "bus"]
        deep_cover_players = [n for n, p in self._evil_plan.items() if p["tactic"] == "deep_cover"]
        role_swap_players = [n for n, p in self._evil_plan.items() if p["tactic"] == "role_swap"]

        # 双簧：配对共享假身份
        if len(double_claim_players) >= 2:
            shared_role = random.choice(["士兵", "僧侣", "管家"])
            for n in double_claim_players:
                self._evil_plan[n]["claim_pair"] = shared_role
                self._evil_plan[n]["fake_role"] = shared_role
        elif len(double_claim_players) == 1:
            self._evil_plan[double_claim_players[0]]["tactic"] = "normal"

        # 苦肉计：牺牲者(爪牙)-受益者(恶魔)
        if len(sacrifice_players) >= 2:
            sacrifice_order = sorted(sacrifice_players,
                                     key=lambda n: 0 if n in self._evil_plan and
                                     self.get_player_by_name(n) and
                                     self.get_player_by_name(n).role in BOTC_TEAMS["minion"] else 1)
            victim = sacrifice_order[0]
            beneficiary = sacrifice_order[1]
            self._evil_plan[victim]["sacrifice_partner"] = beneficiary
            self._evil_plan[victim]["tactic_role"] = "victim"
            self._evil_plan[beneficiary]["sacrifice_partner"] = victim
            self._evil_plan[beneficiary]["tactic_role"] = "beneficiary"

        # 卖队友战术：一个邪恶故意假装质疑另一个邪恶（建立好人人设）
        if len(bus_players) >= 2:
            for i in range(0, len(bus_players) - 1, 2):
                a, b = bus_players[i], bus_players[i + 1]
                self._evil_plan[a]["vote_against"].append(b)
                self._evil_plan[b]["vote_against"].append(a)
                self._evil_plan[a]["tactic_role"] = "bus_driver"
                self._evil_plan[b]["tactic_role"] = "bus_target"

        # 潜伏战术：deep_cover玩家伪装成对邪恶有怀疑的好人
        for n in deep_cover_players:
            self._evil_plan[n]["tactic_role"] = "deep_cover"
            self._evil_plan[n]["fake_role"] = random.choice(
                ["占卜师", "共情者", "调查员", "洗衣妇"]
            )

        # 角色交换战术：恶魔和爪牙互换伪装身份
        if len(role_swap_players) >= 2:
            roles = [self._evil_plan[n]["fake_role"] for n in role_swap_players]
            random.shuffle(roles)
            for n, r in zip(role_swap_players, roles):
                self._evil_plan[n]["fake_role"] = r
                self._evil_plan[n]["claim_pair"] = r

        # 拉拢目标
        if pocket_players and common_target:
            for n in pocket_players:
                self._evil_plan[n]["pocket_target"] = common_target

        # 身份对跳目标
        claim_battle_players = [n for n, p in self._evil_plan.items() if p["tactic"] == "claim_battle"]
        for n in claim_battle_players:
            self._evil_plan[n]["claim_battle_target"] = common_target

        # 统一投票目标 & 公共攻击目标
        for n in self._evil_plan:
            if common_target:
                self._evil_plan[n]["common_target"] = common_target
            # vote_with = 所有存活邪恶队友
            partners = [e for e in evil_names if e != n and
                        self.get_player_by_name(e) and self.get_player_by_name(e).alive]
            self._evil_plan[n]["vote_with"] = partners

        # 初始化假信息日志
        for n in self._evil_plan:
            self._evil_fake_log.setdefault(n, {})

    def _reevaluate_evil_tactics(self):
        """每日战术重评估：更新目标、调整战术、协调投票"""
        if not hasattr(self, '_evil_plan'):
            return

        # 更新存活状态和死亡信息
        alive_evil = []
        for name, plan in list(self._evil_plan.items()):
            agent = self.get_player_by_name(name)
            if not agent or not agent.alive:
                continue
            alive_evil.append(name)

            # 牺牲伙伴已死则转普通
            partner = plan.get("sacrifice_partner")
            if partner:
                partner_agent = self.get_player_by_name(partner)
                if not partner_agent or not partner_agent.alive:
                    plan["tactic"] = "normal"
                    plan["sacrifice_partner"] = None

        if not alive_evil:
            return

        # 重新选择公共攻击目标（优先打有信息位声明的人）
        alive_good = [a for a in self.registry.all_agents()
                      if a.alive and a.role not in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]]

        if alive_good:
            _, _, claim_map = self._build_chat_summary(list(self.registry.all_agents())[0])
            # 优先攻击声明了信息位（威胁大）的好人
            info_claimants = [p for p in alive_good for rn in
                              ["占卜师", "共情者", "调查员", "送葬者", "守鸦人"]
                              if claim_map.get(p.name) == rn]
            if info_claimants:
                new_target = random.choice(info_claimants).name
            else:
                new_target = random.choice(alive_good).name

            for name in alive_evil:
                self._evil_plan[name]["common_target"] = new_target

        # 更新vote_with
        for name in alive_evil:
            partners = [e for e in alive_evil if e != name]
            self._evil_plan[name]["vote_with"] = partners

            # 更新 kill target
            if alive_good:
                _, _, claim_map = self._build_chat_summary(
                    self.get_player_by_name(name) or list(self.registry.all_agents())[0])
                info_roles = ["占卜师", "共情者", "调查员", "送葬者", "守鸦人", "士兵"]
                # 优先杀宣称信息位的
                for p in alive_good:
                    if claim_map.get(p.name) in info_roles:
                        self._evil_plan[name]["current_kill_target"] = p.name
                        break
                else:
                    self._evil_plan[name]["current_kill_target"] = new_target if alive_good else None

    def _gen_nomination_speech(self, nominator_name, target_name):
        """基于证据链和数据集模板的提名发言"""
        nominator = self.get_player_by_name(nominator_name)
        target = self.get_player_by_name(target_name)
        if not nominator or not target:
            return f"我提名{target_name}，他非常可疑。"
        gs = nominator.game_state
        known = gs.get("known_info", {})
        memory = gs.get("chat_memory", [])
        suspicion = gs.get("suspicion", {}).get(target_name, 50)
        nom_team = BOTC_ROLES.get(nominator.role, {}).get("team", "")
        self._init_evil_strategy()
        _, _, claim_map = self._build_chat_summary(nominator)

        # 收集目标身份声明
        target_claims = set()
        for entry in memory:
            if entry.get("speaker") == target_name:
                txt = entry.get("text", "")
                for rn in BOTC_ROLES:
                    if f"我是{rn}" in txt:
                        target_claims.add(rn)

        # 构建证据链
        reason_parts = []
        if known.get("investigator") and known["investigator"][0] == target_name:
            reason_parts.append(f"我是调查员，直接查出{target_name}是{known['investigator'][1]}——这是实锤级的证据")
        if known.get("empathy", 0) > 0:
            e = known["empathy"]
            reason_parts.append(f"共情者显示我旁边有{e}个邪恶，{target_name}恰好是我邻居之一，嫌疑直线上升")
        if known.get("seer") and target_name in known["seer"][0] and known["seer"][1]:
            chosen = known["seer"][0]
            reason_parts.append(f"占卜师昨晚查了{chosen[0]}和{chosen[1]}，{target_name}有恶魔嫌疑")
        if len(target_claims) > 1:
            reason_parts.append(f"{target_name}先后声称是{'/'.join(target_claims)}，身份反复变化——真正的好人不会这样")
        elif target_claims:
            tc = list(target_claims)[0]
            reason_parts.append(f"{target_name}自称{tc}但{claim_map.get(target_name,'?')}这个声明和其他人提供的信息对不上")

        vote_info = self.game_record.get("vote_history", {})
        target_votes = []
        for day_str, votes in vote_info.items():
            for v in votes:
                if v.get("voter") == target_name:
                    target_votes.append(v.get("target"))
        if target_votes:
            reason_parts.append(f"他的投票记录{'/'.join(target_votes[:3])}非常反常——好人不该这样投票")

        if suspicion > 75 and not reason_parts:
            reason_parts.append(f"综合他的发言风格和投票模式，可疑度极高")

        # claim_str / vote_str / contradict_str 用于模板上下文
        claim_str = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:5]])
        vote_str = "，".join(
            [f"{p}投了{t}" for day_ in vote_info.values() for v in day_
             for p, t in [(v.get("voter"), v.get("target"))]][:4]
        ) or "暂无记录"
        contradict = []
        seen = {}
        for sp, rn in claim_map.items():
            if rn in seen and seen[rn] != sp:
                contradict.append(f"{sp}和{seen[rn]}都自称{rn}")
            seen[rn] = sp
        cstr = "，".join(contradict[:2])

        reasons = "；".join(reason_parts[:4]) if reason_parts else f"综合判断，{target_name}的嫌疑非常突出"
        kwargs = dict(target=target_name, reasons=reasons,
                      claim_str=claim_str, vote_str=vote_str, contradict_str=cstr)
        used = gs.setdefault(f"_used_nom_{self.day_count}", set())

        # 邪恶提名策略（增强版：引用队友假信息做协同指控）
        if nom_team in {"demon", "minion"}:
            target_team = BOTC_ROLES.get(target.role, {}).get("team", "")
            if target_team in {"demon", "minion"} and target_name != nominator_name:
                if random.random() < 0.3:
                    t = f"我提名{target_name}！我一直觉得{target_name}有问题，今天处决他获取关键信息！"
                    return DD.naturalize(t)

            # 构造更强的指控：引用队友的假信息作为佐证
            team_fake_info = ""
            evil_plan = self._evil_plan.get(nominator_name, {})
            for partner_name, partner_plan in self._evil_plan.items():
                if partner_name == nominator_name:
                    continue
                partner_fake_log = self._evil_fake_log.get(partner_name, {})
                for day, log in partner_fake_log.items():
                    if log.get("target") == target_name:
                        team_fake_info = (
                            f"而且我的队友{partner_name}（{partner_plan.get('fake_role','镇民')}）"
                            f"也查到了{target_name}有问题——两个人交叉验证，这还不是铁证？"
                        )
                        break
                if team_fake_info:
                    break

            if team_fake_info and reason_parts:
                reason_parts.append(team_fake_info)
            elif team_fake_info:
                # 只用队友信息作为主要理由
                reason_parts.append(team_fake_info)

            if reason_parts:
                t = DD.get_filled("NOMINATION_EVIL", used=used, **kwargs)
            else:
                kwargs["reasons"] = random.choice([
                    f"{target_name}的发言和投票处处都是破绽，{vote_str}说明他有问题",
                    f"{target_name}一直在转移焦点不敢正面回答质疑",
                    f"根据我的观察{claim_str}，{target_name}的信息和别人对不上",
                ])
                t = DD.get_filled("NOMINATION_EVIL", used=used, **kwargs)
            return DD.naturalize(t)

        if reason_parts:
            t = DD.get_filled("NOMINATION", used=used, **kwargs)
        else:
            kwargs["reasons"] = f"根据我的观察，{target_name}的发言存在多处疑点，建议今天处决"
            t = DD.get_filled("NOMINATION", used=used, **kwargs)
        return DD.naturalize(t)

    def _gen_defense_speech(self, target_name, nominator_name):
        """基于角色和数据集模板的辩护发言"""
        target = self.get_player_by_name(target_name)
        if not target:
            return f"我是清白的！{nominator_name}在乱提名！"
        role = target.role
        team = BOTC_ROLES.get(role, {}).get("team", "")
        gs = target.game_state
        known = gs.get("known_info", {})
        _, _, claim_map = self._build_chat_summary(target)

        # 构建上下文
        claim_str = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:5]])
        vote_info = self.game_record.get("vote_history", {})
        vote_str = "，".join(
            [f"{p}投了{t}" for day_ in vote_info.values() for v in day_
             for p, t in [(v.get("voter"), v.get("target"))]][:4]
        ) or ""
        reason = self._pick_target_suspicion(target)
        reason_str = f"我怀疑{reason}才是真正的邪恶——{claim_str}"
        if known:
            info_items = []
            for k, v in list(known.items())[:2]:
                info_items.append(f"{k}:{v}")
            if info_items:
                reason_str = "；".join(info_items)

        kwargs = dict(role=role, nominator=nominator_name, target=target_name,
                      reason=reason_str, claim_str=claim_str, vote_str=vote_str)
        used = gs.setdefault(f"_used_def_{self.day_count}", set())

        # 信息位优先用技能数据辩护
        if "seer" in known:
            chosen, has = known["seer"]
            demon_found = "查出了恶魔！这就是为什么我敢肯定{nominator}在胡说！" if has else "正在缩小范围，我还有用！"
            return DD.naturalize(f"大家冷静！我是占卜师，我查了{chosen[0]}和{chosen[1]}，{demon_found}")
        if "empathy" in known:
            e = known["empathy"]
            return DD.naturalize(f"我是共情者，我旁边邪恶数为{e}！处决我的话好人就失去了每晚的邪恶探测——这正中邪恶下怀！")
        if "investigator" in known:
            inv = known["investigator"]
            if len(inv) == 3:
                inv_names = f"{inv[0]}或{inv[1]}"
                inv_role = inv[2]
            else:
                inv_names = inv[0]
                inv_role = inv[1]
            return DD.naturalize(f"我是调查员！我查出{inv_names}之中有{inv_role}——这才是真正的爪牙！{nominator_name}急着处决我，"
                                 f"就是因为怕我继续查出他的同伙！")
        if "washerwoman" in known:
            return DD.naturalize(f"我是洗衣妇！{reason_str}处决我这条信息链就断了。{nominator_name}的目的就是销毁证据！")
        if "chef" in known:
            return DD.naturalize(f"我是厨师！{reason_str}nominator急着处决一个信息位，这不合逻辑！")

        # 特殊身份辩护
        if role == "圣徒":
            t = random.choice([
                f"我！是！圣！徒！处决我会导致好人阵营直接落败——想清楚！{nominator_name}在故意害好人，你们别上当了！",
                f"等一下！我是圣徒，我死了好人就输了。{nominator_name}要是真好人，应该先确认身份再提名——他这么急一定有鬼！",
            ])
            return DD.naturalize(t)
        if role == "镇长":
            return DD.naturalize(f"我是镇长！镇长活着才有用——只有3人存活时我能直接带来胜利。处决我是最差的选择！")
        if role == "士兵":
            return DD.naturalize(f"我是士兵，恶魔杀不了我！我可以一直活到决赛圈帮好人投票——{nominator_name}急着除掉我，恰恰证明他在帮邪恶做事！")
        if role == "僧侣":
            return DD.naturalize(f"我是僧侣，每晚能保护一个人不被恶魔杀。{nominator_name}要处决我，等于帮恶魔开了一条血路！")
        if role == "管家":
            return DD.naturalize(f"我是管家，虽然能力有限但我始终站在好人这边。{nominator_name}的信息和推理明显有漏洞——"
                                 f"大家仔细想想，他说的那些真的站得住脚吗？")

        # 通用辩护
        if team in {"demon", "minion"}:
            kwargs["nominator"] = nominator_name
            t = DD.get_filled("DEFENSE_EVIL", used=used, **kwargs)
            return DD.naturalize(t)

        t = DD.get_filled("DEFENSE_GOOD", used=used, **kwargs)
        return DD.naturalize(t)

    def _nomination_and_voting_phase(self):
        """提名与投票环节"""
        self.log(f"\n--- [提名投票环节] ---")
        self.game_phase = f"NOMINATION_D{self.day_count}"
        alive = self.get_alive_names()

        if len(alive) <= 1:
            self.log(f"[说书人] 人数不足, 跳过提名阶段。")
            return

        self.log(f"[说书人] 现在进入提名环节, 大家可以发起提名了。")

        nominations = {}
        nominators_used = set()

        for _ in range(min(5, len(alive))):
            nominator = random.choice([n for n in alive if n not in nominators_used])
            if not nominator:
                break
            nom_agent = self.get_player_by_name(nominator)
            self._update_suspicion_from_chat(nom_agent) if nom_agent else None
            # 选怀疑分数最高的玩家提名
            targets = [n for n in alive if n != nominator and n not in nominations]
            if not targets:
                break
            # ML策略提名（邪恶玩家专用）
            if nom_agent and nom_agent.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"] and is_enabled():
                try:
                    obs, n2i, i2n = encode_observation(self, nom_agent)
                    valid = [n2i[t] for t in targets if t in n2i]
                    if valid:
                        nom_idx, log_prob = get_policy().act_nominate(obs, valid_nom=valid, eps=0.2)
                        target = i2n[nom_idx]
                        if log_prob is not None and is_recording():
                            get_trainer().record_step(log_prob)
                    else:
                        target = random.choice(targets)
                except Exception:
                    target = random.choice(targets)
            elif nom_agent and nom_agent.game_state.get("suspicion"):
                sorted_targets = sorted(targets, key=lambda t: nom_agent.game_state["suspicion"].get(t, 50), reverse=True)
                target = sorted_targets[0]
            else:
                target = random.choice(targets)

            # 贞洁者能力：第一次被提名时，若提名者是镇民则提名者被处决
            target_agent = self.get_player_by_name(target)
            is_real_virgin = target_agent and target_agent.role == "贞洁者"
            is_drunk_virgin = target_agent and target_agent.game_state.get("is_drunk") and target_agent.game_state.get("fake_role") == "贞洁者"
            if is_real_virgin or is_drunk_virgin:
                self.nomination_count[target] = self.nomination_count.get(target, 0) + 1
                if self.nomination_count[target] == 1:
                    nominator_agent = self.get_player_by_name(nominator)
                    if is_drunk_virgin:
                        self.log(f"  [贞洁者·酒鬼] {target}是酒鬼(以为自己是贞洁者)，提名{nominator}无效。")
                    elif nominator_agent and self._get_registered_team(nominator_agent) == "townsfolk":
                        nominator_agent.alive = False
                        self.dead_players.append(nominator)
                        self.executed_today = True
                        self.log(f"  [贞洁者] {target}是贞洁者! 提名者{nominator}被当作镇民, 被立即处决!")
        self._record_night_info()
        self._check_game_end()
                        if self.game_record.get('result'):
                            return
                        continue
                    else:
                        self.log(f"  [贞洁者] {target}被首次提名,但{nominator}不是镇民,提名继续。")

            nominators_used.add(nominator)
            nominations[target] = nominator
            self.log(f"  {nominator}提名了{target}!")

            # 提名者发表提名理由
            nom_speech = self._gen_nomination_speech(nominator, target)
            self.log(f"  [提名发言] {nominator}: {nom_speech}")
            self.record_action(nominator, f"提名{target}", nom_speech, "nomination")

            # 被提名者辩护发言
            def_speech = self._gen_defense_speech(target, nominator)
            self.log(f"  [辩护发言] {target}: {def_speech}")
            self.record_action(target, f"被{nominator}提名", def_speech, "defense")

            result = self._run_vote(target, nominator)
            if result == "executed":
                self.executed_today = True
                self.log(f"  {target}被处决!")
                self._check_game_end()
                break
            elif result == "failed":
                self.log(f"  {target}未被处决。")
            elif result == "nomore":
                break

        if not self.executed_today:
            self.log(f"[说书人] 最后一次提名机会...3...2...1...无人发起提名。")

    def _get_vote_probability(self, voter, nominee):
        """基于推理的投票决策"""
        gs = voter.game_state
        suspicion = gs.get("suspicion", {}).get(nominee, 50)
        trust = gs.get("trust", {}).get(nominee, 50)
        known_info = gs.get("known_info", {})

        # 邪恶阵营：战略性投票（含ML策略调节 + 卖队友策略）
        if voter.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
            nom_agent = self.get_player_by_name(nominee)
            # ML 策略调节基础投票倾向
            ml_aggression = 0.5
            if is_enabled():
                try:
                    obs, _, _ = encode_observation(self, voter)
                    ml_aggression = get_policy().get_vote_prob(obs)
                except Exception:
                    ml_aggression = 0.5
            if nom_agent and nom_agent.role in BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"]:
                return 0.5 + 0.45 * ml_aggression  # 0.5~0.95
            # 卖队友策略
            if nom_agent and nom_agent.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
                if nom_agent.name == voter.name:
                    return 0.0
                alive_count = len(self.get_alive_names())
                if alive_count <= 4:
                    return 0.0
                if ml_aggression > 0.6 and random.random() < 0.3:
                    return 0.85
            return 0.1 + 0.2 * (1 - ml_aggression)  # 0.1~0.3

        # 善良阵营：基于怀疑/信任评分
        base = (suspicion - 50) / 50  # -1 ~ +1
        if "seer" in known_info:
            chosen, has = known_info["seer"]
            if nominee in chosen and has:
                return 0.95
            if nominee in chosen and not has:
                return 0.15
        if "investigator" in known_info:
            inv = known_info["investigator"]
            inv_names = [inv[0], inv[1]] if len(inv) == 3 else [inv[0]]
            if nominee in inv_names:
                return 0.9
        if "empathy" in known_info:
            if known_info["empathy"] > 0:
                return 0.5 + base * 0.4

        return max(0.05, min(0.95, 0.5 + base * 0.4))

    def _run_vote(self, nominee, nominator):
        """执行投票 - 基于推理的投票"""
        self.log(f"  [投票] 所有玩家请表决: 处决不处决{nominee}?")
        alive_names = self.get_alive_names()

        votes_for = 0
        voter_details = []

        vote_records = []
        voted_players = set()  # 记录已投票玩家（用于管家限制）
        for voter_name in alive_names:
            if voter_name == nominee:
                continue
            voter = self.get_player_by_name(voter_name)
            if not voter or not voter.alive:
                continue
            # 管家限制：只能在主人投票后才能投票
            if voter.role == "管家":
                master = voter.game_state.get("known_info", {}).get("master")
                if master and master not in voted_players and master != voter_name:
                    self.log(f"  [管家限制] {voter_name}(管家)的主人{master}尚未投票,跳过投票")
                    continue
            self._update_suspicion_from_chat(voter)
            vote_prob = self._get_vote_probability(voter, nominee)
            cast_vote = random.random() < vote_prob
            # 记录邪恶方的投票 log_prob 用于 ML 训练
            if is_recording() and is_enabled() and voter.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
                try:
                    from .ml_policy import get_trainer
                    import math
                    lp_val = math.log(vote_prob if cast_vote else 1.0 - vote_prob + 1e-10)
                    import torch
                    get_trainer().record_step(torch.tensor(lp_val))
                except Exception:
                    pass
            if cast_vote:
                voted_players.add(voter_name)
                vote_records.append({"voter": voter_name, "target": nominee, "day": self.day_count})
                votes_for += 1
                voter_details.append(f"{voter_name}({BOTC_ROLES[voter.role].get('team', '')})")

        # 死者幽灵投票
        dead_names = [a.name for a in self.registry.all_agents()
                      if not a.alive and a.name not in self.ghost_vote_used]
        for dname in dead_names:
            voter = self.get_player_by_name(dname)
            vote_prob = 0.3
            if voter:
                self._update_suspicion_from_chat(voter)
                s = voter.game_state.get("suspicion", {}).get(nominee, 50)
                vote_prob = max(0.1, min(0.8, (s - 50) / 50 * 0.4 + 0.4))
            if random.random() < vote_prob:
                votes_for += 1
                self.ghost_vote_used.add(dname)
                voter_details.append(f"{dname}(幽灵)")

        # 记录投票历史
        if vote_records:
            day_key = f"day_{self.day_count}"
            if "vote_history" not in self.game_record:
                self.game_record["vote_history"] = {}
            if day_key not in self.game_record["vote_history"]:
                self.game_record["vote_history"][day_key] = []
            self.game_record["vote_history"][day_key].extend(vote_records)

        total_voters = len(alive_names)
        threshold = total_voters // 2 + 1
        self.log(f"  [计票] {votes_for}/{total_voters} 票赞同 (需{threshold}票, 含{len([v for v in voter_details if '幽灵' in v])}幽灵票)")
        self.log(f"  投票详情: {', '.join(voter_details)}")

        if votes_for >= threshold:
            target_agent = self.get_player_by_name(nominee)
            if target_agent:
                if target_agent.role == "小丑":
                    self.log(f"[小丑] {nominee}是小丑, 处决无效!")
                    return "failed"
                elif target_agent.role == "圣徒":
                    self.log(f"[圣徒] {nominee}是圣徒! 被处决导致善良阵营落败!")
                    target_agent.alive = False
                    self.dead_players.append(nominee)
                    self.last_executed = nominee
                    self.end_game("evil_win")
                    return "executed"
                else:
                    target_agent.alive = False
                    self.dead_players.append(nominee)
                    self.last_executed = nominee
                    context = f"{nominee}被处决"
                    self.record_action(nominator, context, f"处决{nominee}", "execution")
                    self.log(f"  处决者: {nominator}, 被处决: {nominee}({target_agent.role})")
                    return "executed"
        return "failed"

    # ==================== 结束条件 ====================
    def _check_scarlet_woman_conversion(self):
        """红唇女郎转换：恶魔死亡时若存活>=5人，红唇女郎变成新恶魔"""
        alive_agents = self.registry.all_alive()
        alive_count = len([a for a in alive_agents])
        if alive_count < 5:
            return False
        scarlets = [a for a in self.registry.all_agents()
                    if a.role == "红唇女郎" and a.alive]
        if not scarlets:
            return False
        sw = scarlets[0]
        sw.role = "小恶魔"
        sw.game_state["role"] = "小恶魔"
        remaining_minions = [m.name for m in self.registry.all_agents()
                             if m.role in BOTC_TEAMS["minion"] and m.alive and m.name != sw.name]
        sw.game_state["known_info"]["minions"] = remaining_minions
        self.log(f"\n  [红唇女郎] 恶魔死亡! {sw.name}变成新恶魔!(存活{alive_count}人>=5)")
        return True

    def _record_night_info(self):
        """每夜结束后记录所有玩家获得的夜间信息到night_info_history"""
        if "night_info_history" not in self.game_record:
            self.game_record["night_info_history"] = {}
        day_key = f"day_{self.day_count}"
        if day_key not in self.game_record["night_info_history"]:
            self.game_record["night_info_history"][day_key] = {}
        info_map = {
            'seer': lambda v: f"查验 {v[0]}，{'发现恶魔' if v[1] else '无恶魔'}",
            'washerwoman': lambda v: f"{v[0]} 和 {v[1]} 中有一人是 {v[2]}",
            'librarian': lambda v: f"{v[0]} 和 {v[1]} 中有一人是 {v[2]}" if v[0] != '无' else "无外来者",
            'investigator': lambda v: f"{v[0]} 和 {v[1]} 中有一人是 {v[2]}",
            'empathy': lambda v: f"左右邻居中有 {v} 个邪恶玩家",
            'chef': lambda v: f"有 {v} 对相邻的邪恶玩家",
            'undertaker': lambda v: f"被处决者身份是 {v}",
            'ravenkeeper': lambda v: f"查看了 {v[0]}，身份是 {v[1]}",
        }
        for a in self.registry.all_agents():
            known = a.game_state.get('known_info', {})
            all_keys = list(info_map.keys())
            for k in all_keys:
                if k in known:
                    text = info_map.get(k, lambda v: str(v))(known[k])
                    if a.name not in self.game_record["night_info_history"][day_key]:
                        self.game_record["night_info_history"][day_key][a.name] = []
                    # 避免重复记录（同一个key同一天）
                    existing = [e for e in self.game_record["night_info_history"][day_key][a.name] if e['key'] == k]
                    if not existing:
                        self.game_record["night_info_history"][day_key][a.name].append({
                            'key': k, 'text': text, 'day': self.day_count
                        })

    def _check_game_end(self, check_mayor=False):
        """官方胜利条件判定
        check_mayor: 在白天结束时设为True，触发镇长特殊胜利判定
        """
        demon_alive = any(
            a.alive for a in self.registry.all_agents()
            if a.role in BOTC_TEAMS["demon"]
        )
        alive_count = len(self.get_alive_names())

        # 0) 恶魔死亡时的红唇女郎转换（处决或夜晚死亡后触发）
        if not demon_alive:
            if self._check_scarlet_woman_conversion():
                return False  # 转换成功，游戏继续

        # 1) 镇长特殊胜利: 仅3人存活且白天无人被处决（仅在白天结束时判定）
        if check_mayor and alive_count <= 3 and not self.executed_today:
            mayor_players = [a for a in self.registry.all_agents()
                             if a.role == "镇长" and a.alive]
            if mayor_players:
                self.end_game("good_win")
                self.log(f"\n========== 游戏结束: 善良阵营获胜! ==========")
                self.log("镇长能力触发: 仅3人存活且无人被处决。")
                return True

        # 2) 同时满足条件时，善良阵营优先获胜
        good_wins = not demon_alive
        evil_wins = alive_count <= 2

        if good_wins and evil_wins:
            self.end_game("good_win")
            self.log(f"\n========== 游戏结束: 善良阵营获胜! ==========")
            self.log("恶魔被处决，同时场上不足3人，善良阵营优先获胜。")
            return True

        # 3) 恶魔全部死亡 → 善良阵营获胜
        if not demon_alive:
            self.end_game("good_win")
            self.log(f"\n========== 游戏结束: 善良阵营获胜! ==========")
            self.log("所有恶魔均已死亡。")
            return True

        # 4) 存活≤2人（不含旅行者）→ 邪恶阵营获胜
        if alive_count <= 2:
            self.end_game("evil_win")
            self.log(f"\n========== 游戏结束: 邪恶阵营获胜! ==========")
            self.log("场上只剩两名存活玩家。")
            return True

        return False

    # ==================== 启动游戏 ====================
    def start_game(self, show_detail=True):
        if not self.setup_complete:
            raise RuntimeError("请先调用setup_game()")

        self.logger_enabled = show_detail
        self.phase_role_assignment()

        max_rounds = 20
        round_count = 0
        while not self.game_record["result"] and round_count < max_rounds:
            round_count += 1
            self.run_night()
            if self.game_record["result"]:
                break
            self.run_day()

        self.game_record["storyteller_log"] = self.storyteller_log
        self.game_record["total_rounds"] = round_count

        # ML训练：对局结束后更新策略
        if is_recording():
            win = "evil" in self.game_record.get("result", "")
            loss_val = get_trainer().finish_episode(win)
            if show_detail:
                self.log(f"[ML训练] 邪恶{'胜利' if win else '失败'}，loss={loss_val:.4f}")

        return self.game_record
