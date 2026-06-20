"""
血染钟楼 TROUBLE BREWING 官方流程引擎
流程: 选板子→分角色→天黑闭眼→各角色行动→天亮睁眼→私聊→公聊→提名投票→平安日/处决→天黑...
"""
import random
from core.game_manager import GameManager
from .roles import BOTC_ROLES, BOTC_TEAMS, NIGHT_ORDER_FIRST, NIGHT_ORDER_OTHER


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
            }
            self.add_player(agent)
        self.player_order = [a.name for a in self.registry.all_agents()]

        # 酒鬼：替换一个镇民角色，以为自己就是该镇民
        drunk_agents = [a for a in agents if a.role == "酒鬼"]
        for drunk in drunk_agents:
            # 选一个不在场的镇民角色作为酒鬼的"假认知"
            existing_roles = {a.role for a in agents}
            available_townsfolk = [r for r in BOTC_TEAMS["townsfolk"] if r not in existing_roles]
            if available_townsfolk:
                fake_role = random.choice(available_townsfolk)
            else:
                fake_role = random.choice(BOTC_TEAMS["townsfolk"])
            drunk.game_state["fake_role"] = fake_role
            drunk.game_state["is_drunk"] = True
            self.log(f"  {drunk.name}是酒鬼(以为自己是{fake_role})")

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
        self.poisoned_players.clear()

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
            if step_name == "黎明":
                pass
            return

        players = self.registry.get_by_role(role_name)
        alive_players = [p for p in players if p.alive]

        # 守鸦人特殊处理：当晚死亡也可行动
        if role_name == "守鸦人" and not is_first:
            dead_this_night = [p for p in self.dead_players if any(
                a.name == p and not a.alive for a in self.registry.all_agents()
            )]
            rk_dead = [a for a in players if a.name in dead_this_night]
            if rk_dead:
                rk = rk_dead[0]
                targets = [a for a in self.registry.all_alive() if a.name != rk.name]
                if targets:
                    target = random.choice(targets)
                    rk.game_state["known_info"]["ravenkeeper"] = (target.name, target.role)
                    self.log(f"  [守鸦人] {rk.name}死亡后查验了{target.name}的身份: {target.role}")

        for player in alive_players:
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
                    self.protected_player = protect
                    player.game_state["protected"] = protect
                    self.log(f"  [僧侣] {player.name}保护了{protect}")

            elif role_name == "共情者":
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
                self.log(f"  [共情者] {player.name}得知相邻邪恶数: {evil_count}")

            elif role_name == "占卜师":
                alive_names = [a.name for a in self.registry.all_agents() if a.alive]
                others = [n for n in alive_names if n != player.name]
                if len(others) >= 2:
                    chosen = random.sample(others, 2)
                elif len(others) == 1:
                    chosen = [others[0], others[0]]
                else:
                    continue
                # 含干扰项机制：干扰项始终当作恶魔
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
                self.log(f"  [占卜师] {player.name}查验{chosen}: {result_text}")

            elif role_name == "送葬者" and not is_first:
                if self.last_executed:
                    exec_agent = self.get_player_by_name(self.last_executed)
                    if exec_agent:
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
                alive = [a for a in self.registry.all_agents() if a.alive and a.name != player.name]
                if len(alive) >= 2:
                    chosen = random.sample(alive, 2)
                    registered_townsfolk = [c for c in chosen if self._get_registered_team(c) == "townsfolk"]
                    target = registered_townsfolk[0] if registered_townsfolk else chosen[0]
                    shown_role = self._get_registered_role(target)
                    player.game_state["known_info"]["washerwoman"] = (target.name, shown_role)
                    self.log(f"  [洗衣妇] {player.name}得知{target.name}是{shown_role}")

            elif role_name == "图书管理员" and is_first:
                all_agents = self.registry.all_agents()
                alive_outsiders = [o for o in all_agents if o.alive and o.name != player.name
                                   and self._get_registered_team(o) == "outsider"]
                if alive_outsiders:
                    target = random.choice(alive_outsiders)
                    shown_role = self._get_registered_role(target)
                    player.game_state["known_info"]["librarian"] = (target.name, shown_role)
                    self.log(f"  [图书管理员] {player.name}得知{target.name}是外来者({shown_role})")
                else:
                    player.game_state["known_info"]["librarian"] = ("无", "本局没有外来者")
                    self.log(f"  [图书管理员] {player.name}得知本局没有外来者")

            elif role_name == "调查员" and is_first:
                all_agents = self.registry.all_agents()
                alive_minions = [m for m in all_agents if m.alive and m.name != player.name
                                 and self._get_registered_team(m) == "minion"]
                if alive_minions:
                    target = random.choice(alive_minions)
                    shown_role = self._get_registered_role(target)
                    player.game_state["known_info"]["investigator"] = (target.name, shown_role)
                    self.log(f"  [调查员] {player.name}得知{target.name}是爪牙({shown_role})")

            elif role_name == "厨师" and is_first:
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
                self.log(f"  [厨师] {player.name}得知相邻邪恶对数为: {evil_pairs}")

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
        entry = {"speaker": speaker, "text": speech, "phase": phase, "day": self.day_count}
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
        max_chats_per_player = 2  # 每人聊2个
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

        chat_rounds = 2  # 每对聊2轮

        for name_a, name_b in chat_pairs:
            a = self.get_player_by_name(name_a)
            b = self.get_player_by_name(name_b)
            if not a or not b:
                continue

            thread_key = f"D{self.day_count}_{name_a}🔄{name_b}"
            thread_msgs = []

            for rnd in range(1, chat_rounds + 1):
                self._update_suspicion_from_chat(a)
                self._update_suspicion_from_chat(b)

                s_a = self._gen_speech(a, b.name)
                self.log(f"  [第{rnd}轮] {a.name} 对 {b.name} 说: {s_a}")
                self.record_action(a.name, f"私聊{b.name}(第{rnd}轮)", s_a, "private_chat")
                self._store_chat(a.name, b.name, s_a, "private_chat")
                thread_msgs.append({"speaker": a.name, "text": s_a, "rnd": rnd})

                s_b = self._gen_speech(b, a.name)
                self.log(f"  [第{rnd}轮] {b.name} 对 {a.name} 说: {s_b}")
                self.record_action(b.name, f"私聊{a.name}(第{rnd}轮)", s_b, "private_chat")
                self._store_chat(b.name, a.name, s_b, "private_chat")
                thread_msgs.append({"speaker": b.name, "text": s_b, "rnd": rnd})

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

    def _gen_speech(self, player, listener=None):
        """基于记忆和推理的角色个性化发言"""
        name = player.name
        role = player.role
        gs = player.game_state
        info = gs.get("known_info", {})
        team = BOTC_ROLES.get(role, {}).get("team", "")
        dead = not player.alive
        day = self.day_count
        alive_names = self.get_alive_names()
        memory = gs.get("chat_memory", [])
        suspicion = gs.get("suspicion", {})
        suspect = self._pick_target_suspicion(player)

        # 提取聊天记忆中的身份声明和关键事件
        claim_map = {}  # {player: role}
        key_events = []  # 关键事件摘要
        for entry in memory[-20:]:
            sp = entry.get("speaker", "")
            txt = entry.get("text", "")
            for rn in BOTC_ROLES:
                if f"我是{rn}" in txt and sp not in claim_map:
                    claim_map[sp] = rn
            if "开枪" in txt or "射杀" in txt:
                key_events.append(f"{sp}开枪")
            if "处决" in txt and "提名" in txt:
                key_events.append(f"{sp}发起提名")

        # ==================== 私聊（多轮深层对话） ====================
        if listener:
            trust = gs.get("trust", {}).get(listener, 50)
            sus = gs.get("suspicion", {}).get(listener, 50)
            listener_role_claim = claim_map.get(listener, None)
            my_claim = claim_map.get(name, None)
            my_real_team = team

            # 统计本轮已和listener交换了多少条消息
            exchanged = sum(1 for m in gs.get("chat_memory", [])
                          if m.get("phase") == "private_chat"
                          and m.get("speaker") in (name, listener)
                          and m.get("day") == self.day_count)
            partner_last_msg = ""
            # 从当前玩家记忆中找对方最后一条私聊消息
            for m in reversed(gs.get("chat_memory", [])):
                if m.get("speaker") == listener and m.get("phase") == "private_chat":
                    partner_last_msg = m.get("text", "")
                    break

            def _has_info_role(r):
                return r in ("占卜师","共情者","调查员","洗衣妇","图书管理员","厨师","送葬者","守鸦人")

            # 引用对方最近说的内容作为回应上下文
            reply_context = ""
            if partner_last_msg and len(partner_last_msg) > 5:
                # 提取关键词：对方提到的玩家名或角色
                for rn in BOTC_ROLES:
                    if rn in partner_last_msg:
                        reply_context = f"你说到{rn}，"
                        break
                for p in self.registry.all_agents():
                    if p.name in partner_last_msg and p.name != name and p.name != listener:
                        reply_context = f"你提到{p.name}，"
                        break
                if not reply_context:
                    reply_context = "针对你刚才说的，"

            # ----- 邪恶阵营私聊（多轮深入） -----
            if team in {"demon", "minion"}:
                self._init_evil_strategy()
                fake_role = self._evil_plan.get(name, {}).get("fake_role", "镇民")
                listener_fake = self._evil_plan.get(listener, {}).get("fake_role", "镇民")

                # 多轮上下文判断：exchanged≈已交换消息数
                # 0=第一轮首次发, 1=第一轮对方首次回, 2=第二轮首次发, 3=第二轮对方回, 4=第三轮...
                if team == "demon" and "minions" in info and listener in info.get("minions", []):
                    if exchanged >= 3:  # 第三轮+
                        return f"{name}: {reply_context}好，一切按计划。今晚我杀{suspect or '一个信息位'}，你白天继续攻击目标。"
                    if exchanged >= 1:  # 第二轮
                        return f"{name}: {reply_context}对，就这么办。你坚持{listener_fake}的身份别动摇。另外注意{suspect or '那几个人'}，他们可能在交换信息了。"
                    # 第一轮
                    strategies = [
                        f"{name}: 是我，{role}。你假装{listener_fake}，我伪装{info.get('current_bluff', fake_role)}。白天你负责攻击{random.choice([p for p in self.get_alive_names() if p not in (name, listener)])}。",
                        f"{name}: {listener}，我们的伪装是：你{listener_fake}，我{info.get('current_bluff', fake_role)}。今晚我打算杀{suspect or '最像信息位的'}，可行吗？",
                        f"{name}: 计划：你假装{listener_fake}提供伪信息，我假装{info.get('current_bluff', fake_role)}带节奏。目标是让好人互咬。",
                    ]
                    return random.choice(strategies)

                if "demon" in info and info.get("demon") == listener:
                    if exchanged >= 3:
                        attack_target = random.choice([p for p in self.get_alive_names() if p not in (name, listener)])
                        return f"{name}: {reply_context}明白。我继续佯攻{attack_target}，帮他拉仇恨。"
                    if exchanged >= 1:
                        return f"{name}: {reply_context}懂了老大。我继续假装{listener_fake}，同时把矛头指向{suspect or '目标'}。"
                    spy_info = gs.get("known_info", {}).get("spy_info", {})
                    if spy_info:
                        key_good = [(n, r) for n, r in spy_info.items()
                                    if BOTC_ROLES.get(r, {}).get("team") in ("townsfolk", "outsider")][:2]
                        key_info = ", ".join([f"{n}是{r}" for n, r in key_good])
                        return f"{name}: 老大，我看到魔典了，{key_info}。我建议先杀{key_good[0][0] if key_good else suspect}，他肯定是信息位。"
                    return f"{name}: 老大，我假装{listener_fake}。要不要我去踩{random.choice([p for p in self.get_alive_names() if p not in (name, listener)])}把水搅浑？"

                # 邪恶遇到高怀疑
                if sus > 60:
                    if exchanged >= 3:
                        return f"{name}: {reply_context}你仍然没说服我。如果你拿不出证据，我只能认为你在故意针对。"
                    if exchanged >= 1:
                        return f"{name}: {reply_context}你还没正面回答我。你为什么盯上我？你的依据是什么？"
                    return random.choice([
                        f"{name}: {listener}，你为什么盯上我？你是不是有什么信息没说出来？",
                        f"{name}: {listener}，你{listener_role_claim or '的身份'}一直让我觉得不对劲。",
                        f"{name}: {listener}，我观察你好久了。你一直在针对我，是不是想转移焦点？",
                    ])

                # 邪恶接触善良/其他邪恶
                if exchanged >= 3:
                    return f"{name}: {reply_context}总之，保持联系。今天先观察{suspect or '目标'}的反应，投票时见。"
                if exchanged >= 1:
                    return random.choice([
                        f"{name}: {reply_context}有道理。那你觉得{suspect or '谁'}最值得今天处决？",
                        f"{name}: {reply_context}有意思。除了{suspect or '这个'}，你还有没有别的怀疑对象？",
                    ])
                evil_pc = [
                    f"{name}: {listener}，现在局势很乱。你觉得{suspect or '有谁'}比较可疑？我是{fake_role}。",
                    f"{name}: {listener}，我是{fake_role}。你是什么身份？我们交换一下信息。",
                    f"{name}: {listener}，场上信息你觉得哪些可信？我比较关注{suspect or '某人'}。",
                ]
                return random.choice(evil_pc)

            # ----- 善良阵营私聊（多轮深入） -----
            if trust > 70:
                info_sharing = ""
                if "seer" in info:
                    chosen, has = info["seer"]
                    base_info = f"我昨晚查了{chosen[0]}和{chosen[1]}，{'有恶魔嫌疑' if has else '都是好人'}。"
                    info_sharing = base_info
                    if has and exchanged >= 2:
                        info_sharing = base_info + f"我建议今天从{chosen[0]}开始处决，你觉得呢？"
                elif "empathy" in info:
                    base_info = f"我旁边邪恶数是{info['empathy']}。"
                    info_sharing = base_info
                    if info['empathy'] > 0 and exchanged >= 2:
                        idx = self.player_order.index(name)
                        ns = [self.player_order[(idx - 1) % len(self.player_order)], self.player_order[(idx + 1) % len(self.player_order)]]
                        info_sharing = base_info + f"我的邻居{'、'.join(ns)}中有坏人，你觉得是哪一个？"
                elif "investigator" in info:
                    info_sharing = f"我查到{info['investigator'][0]}是{info['investigator'][1]}！今天必须推动处决他。"
                elif "washerwoman" in info:
                    info_sharing = f"我知道{info['washerwoman'][0]}是{info['washerwoman'][1]}。你觉得这个信息可信吗？"
                elif "chef" in info:
                    info_sharing = f"相邻邪恶对数为{info['chef']}。"
                    if exchanged >= 2 and info['chef'] > 0:
                        info_sharing += "你有没有观察到哪两个人总是互相包庇？"
                else:
                    info_sharing = "你那边有什么发现？"
                if exchanged >= 2:
                    return f"{name}: {reply_context}我重复一下，我的真实身份是{role}。{info_sharing}"
                return f"{name}: 我信任你，我是真正的{role}。{info_sharing}"

            if sus > 60:
                if exchanged >= 2:
                    return f"{name}: {reply_context}你还是没正面回答我的问题。你{listener_role_claim or '的身份'}和你的行为对不上。如果你不能解释清楚，我只能投你的票了。"
                return f"{name}: {listener}，你{listener_role_claim or '的身份'}我一直觉得对不上。能详细说说你的信息和推理过程吗？比如你昨天做了什么，查到了什么？"

            if _has_info_role(role):
                if exchanged >= 2:
                    return f"{name}: {reply_context}我已经把我的信息告诉你了。你还没说你的身份，这不公平吧？"
                return f"{name}: {listener}，我有一些关键信息，但想先听听你的身份和掌握的信息，我们交叉验证一下。"

            # 无信息角色的多轮对话
            if exchanged >= 4:
                return f"{name}: {reply_context}总结一下，我们都怀疑{suspect or '某个人'}。今天投票时保持一致，先把他投出去看看反应。"
            if exchanged >= 1:
                return f"{name}: {reply_context}有道理。你说的{suspect or '情况'}我也注意到了。那除了他之外，还有没有其他你觉得可疑的？"
            day1_phrases = [
                f"{name}: {listener}，我是{role}，暂时没什么关键信息。你那边有什么发现或怀疑的人吗？",
                f"{name}: {listener}，第一天信息太少，你觉得谁的表现比较反常？我关注的是{suspect or '目前还没明确的'}。",
                f"{name}: {listener}，我一直观察大家的发言。你相信{suspect or '谁'}的说法？有没有觉得谁在带节奏？",
                f"{name}: {listener}，我注意到{suspect or '有人'}表现得不太自然，你有同感吗？我们交换一下看法。",
            ]
            return random.choice(day1_phrases)

        # ==================== 死者发言 ====================
        if dead:
            if "undertaker" in info:
                exec_role = info['undertaker']
                return f"{name}(已死亡): 我是送葬者，昨天被处决的是{exec_role}。{'处决对了' if exec_role in BOTC_TEAMS['demon'] + BOTC_TEAMS['minion'] else '处决错了'}，活着的各位重新推理一下吧。"
            if "ravenkeeper" in info:
                rk_target, rk_role = info['ravenkeeper']
                team_label = "邪恶" if rk_role in BOTC_TEAMS['demon'] + BOTC_TEAMS['minion'] else "善良"
                return f"{name}(已死亡): 我是守鸦人！死前查了{rk_target}是{rk_role}({team_label})！这是我用命换来的信息！"

            analysis_parts = []
            claims_list = [f"{p}自称{r}" for p, r in list(claim_map.items())[:5]]
            if claims_list:
                analysis_parts.append(f"身份声明：{'，'.join(claims_list)}")
            clash_found = False
            roles_seen = {}
            for sp, rn in claim_map.items():
                if rn in roles_seen and roles_seen[rn] != sp:
                    analysis_parts.append(f"注意！{sp}和{roles_seen[rn]}都自称{rn}")
                    clash_found = True
                roles_seen[rn] = sp
            if key_events:
                analysis_parts.append(f"关键事件：{'，'.join(key_events[:3])}")
            if analysis_parts:
                return f"{name}(已死亡): 我总结一下：{'，'.join(analysis_parts)}。活着的人帮我找出矛盾！"
            dead_templates = [
                f"{name}(已死亡): 我虽然死了但一直在观察。{suspect or '某个人'}很可疑，大家仔细想想他的发言！",
                f"{name}(已死亡): 死前我提醒大家：注意{suspect or '投票时抱团的人'}，邪恶阵营一定在互相掩护！",
            ]
            return random.choice(dead_templates)

        # ==================== 邪恶阵营 ====================
        if team in {"minion", "demon"}:
            self._init_evil_strategy()
            evil_plan = self._evil_plan.get(name, {})
            target_for_accusation = suspect
            if not target_for_accusation and claim_map:
                candidates = [p for p in claim_map if p != name]
                if candidates:
                    target_for_accusation = random.choice(candidates)

            # 确定恶魔使用的伪装角色
            if team == "demon" and "fake_roles" in info:
                bluff = info.get("current_bluff")
                if not bluff:
                    bluff = random.choice(info["fake_roles"])
                    info["current_bluff"] = bluff
            
            # 爪牙也分配伪装角色
            minion_bluff = evil_plan.get("fake_role")
            
            # 构建指向特定目标的指控
            accusation = ""
            if day > 1:
                if target_for_accusation and target_for_accusation in claim_map:
                    target_role_claim = claim_map[target_for_accusation]
                    # 找该目标在投票中的反常行为
                    vote_info = self.game_record.get("vote_history", {})
                    target_votes = []
                    for day_str, votes in vote_info.items():
                        for v in votes:
                            if v.get("voter") == target_for_accusation:
                                target_votes.append(v.get("target"))
                    if target_votes:
                        vote_str = "/".join(target_votes[:2])
                        accusation = f"{target_for_accusation}自称{target_role_claim}，但投票处决过{vote_str}，行为和他声称的身份不符！"
                    else:
                        accusation = f"我注意到{target_for_accusation}自称{target_role_claim}，但他的发言和这个身份对不上。"
                # 撞身份攻击
                if team == "demon" and not accusation and "fake_roles" in info:
                    for sp, rn in list(claim_map.items()):
                        if sp != name and rn == bluff:
                            accusation = f"{sp}也自称{bluff}，这就有意思了——他在冒充我！"
                            break
                # 随机攻击没有身份声明的玩家
                if not accusation:
                    silent_players = [p for p in self.get_alive_names() if p != name and p not in claim_map]
                    if silent_players and random.random() < 0.4:
                        mute = random.choice(silent_players)
                        accusation = f"{mute}一直不表明身份，非常可疑，大家逼他交身份！"

            # ===== 恶魔公聊 =====
            if team == "demon" and "fake_roles" in info:
                bluff = info.get("current_bluff", "镇民")
                if accusation:
                    demon_variants = [
                        f"{name}: 我是{bluff}。{accusation}",
                        f"{name}: 重申我是{bluff}。{accusation} 今天必须推进处决！",
                        f"{name}: 我是{bluff}，{self._gen_fake_info(name, bluff)} {accusation}",
                        f"{name}: 大家听我说，我是{bluff}。{accusation} 你们不觉得这很可疑吗？",
                    ]
                else:
                    focus = target_for_accusation or "局势"
                    demon_variants = [
                        f"{name}: 我是{bluff}。目前比较关注{focus}，大家多交流信息。",
                        f"{name}: 重申我是{bluff}。场上信息混乱，但我认为{focus}值得重点关注。",
                        f"{name}: 我是{bluff}。第一天我会多观察，{focus}的表现我会记下来。",
                    ]
                return random.choice(demon_variants)

            # ===== 爪牙公聊 =====
            if team == "minion":
                gs_minion = gs
                # 爪牙如果有伪装角色，用伪装身份发言
                if minion_bluff and minion_bluff in ("洗衣妇", "图书管理员", "厨师", "调查员", "共情者", "占卜师"):
                    fake_info_text = self._gen_fake_info(name, minion_bluff)
                    if accusation:
                        return f"{name}: 我是{minion_bluff}，{fake_info_text} {accusation}"
                    focus = target_for_accusation or "局势"
                    return f"{name}: 我是{minion_bluff}，{fake_info_text} 我比较关注{focus}。"
                
                # 没有伪装角色的爪牙：制造混乱
                if accusation:
                    return f"{name}: {accusation}"
                
                minion_variants = [
                    f"{name}: 大家注意{target_for_accusation or '某些人'}的发言前后不一，太明显了。",
                    f"{name}: 我怀疑{target_for_accusation or '有人'}在故意混淆视线，今天必须推进处决。",
                    f"{name}: 场上信息很乱，但{target_for_accusation or '有玩家'}一直在转移话题，非常可疑。",
                    f"{name}: 我觉得{target_for_accusation or '局势'}需要有人推动，不能一直观望。",
                ]
                return random.choice(minion_variants)

        # ==================== 善良阵营 ====================
        # 共情者
        if "empathy" in info:
            e = info['empathy']
            idx = self.player_order.index(name)
            neighbors = [self.player_order[(idx - 1) % len(self.player_order)], self.player_order[(idx + 1) % len(self.player_order)]]
            if e > 0:
                neighbor_claims = [f"{n}(自称{claim_map.get(n, '?')})" for n in neighbors]
                return f"{name}: 我是共情者，昨晚得知左右邪恶数为{e}！我的邻居{'，'.join(neighbor_claims)}中至少有{e}个坏人，大家帮我分析！"
            safe_neighbors = [f"{n}自称{claim_map.get(n, '?')}" if n in claim_map else n for n in neighbors]
            return f"{name}: 我是共情者，左右邪恶数为0，{'，'.join(safe_neighbors)}都是好人。那坏人一定在对面{suspect or '区域'}。"

        # 占卜师
        if "seer" in info:
            chosen, has_demon = info["seer"]
            if has_demon:
                return f"{name}: 我是占卜师！昨晚查{chosen[0]}和{chosen[1]}，结果有恶魔！这两人中必须处决一个，我建议从{chosen[0]}开始。"
            excluded = [n for n in alive_names if n not in chosen and n != name]
            return f"{name}: 我是占卜师，{chosen[0]}和{chosen[1]}昨晚验过都不是恶魔。恶魔在{'、'.join(excluded[:3])}之中，我们得缩小范围。"

        # 调查员
        if "investigator" in info:
            t_name, t_role = info["investigator"]
            return f"{name}: 我是调查员！{t_name}是{t_role}——他是爪牙！今天必须处决{t_name}，不能让他再混淆视听了！"

        # 厨师
        if "chef" in info:
            c = info['chef']
            if c > 0:
                return f"{name}: 我是厨师，相邻邪恶对数为{c}。有{c}组邪恶坐在一起，大家看看谁和谁总是互相包庇、投票一致？"
            return f"{name}: 我是厨师，相邻邪恶对数为0。邪恶之间不相邻，分布比较分散，但这也意味着他们更难被发现。"

        # 洗衣妇
        if "washerwoman" in info:
            t_name, t_role = info["washerwoman"]
            return f"{name}: 我是洗衣妇，我得知{t_name}是{t_role}。{t_name}，你自己说说是这个身份吗？我们需要交叉验证。"

        # 图书管理员
        if "librarian" in info:
            t_name, t_role = info["librarian"]
            if t_name == "无":
                return f"{name}: 我是图书管理员，本局没有外来者。谁自称外来者就是在说谎！"
            return f"{name}: 我是图书管理员，{t_name}是{t_role}。{t_name}你能证明自己的身份吗？"

        # 送葬者
        if "undertaker" in info:
            exec_role = info['undertaker']
            correct = exec_role in BOTC_TEAMS['demon'] + BOTC_TEAMS['minion']
            return f"{name}: 我是送葬者，昨晚得知被处决的是{exec_role}。{'处决对了，我们方向正确！' if correct else f'处决错了{exec_role}是善良的，大家调整推理方向！'}"

        # 守鸦人（活着时一般不触发，以防万一）
        if "ravenkeeper" in info:
            rk_target, rk_role = info['ravenkeeper']
            return f"{name}: 我是守鸦人，昨晚查验了{rk_target}是{rk_role}。{'他是邪恶的！' if rk_role in BOTC_TEAMS['demon'] + BOTC_TEAMS['minion'] else '他是好人。'}"

        # 僧侣/士兵/镇长/管家等无信息角色
        if role == "僧侣":
            protected = info.get("protected", "某人")
            return f"{name}: 我是僧侣，昨晚保护了{protected}。如果明天{protected}还活着，说明我挡住了恶魔的刀。"

        if role == "士兵":
            return f"{name}: 我是士兵，恶魔杀不了我。我可以放心活到最后，帮我找出真正的恶魔吧。"

        if role == "镇长":
            mayors = [
                f"{name}: 我是镇长。大家冷静思考，不要被带节奏。{suspect or '某些人'}的表现很可疑。",
                f"{name}: 我是镇长，活着的我才有用。我建议今天先处决{suspect or '最可疑的人'}。",
            ]
            return random.choice(mayors)

        if role == "管家":
            master = info.get("butler_master", "某人")
            return f"{name}: 我是管家，我的主人是{master}。虽然能力有限，但我真心支持好人。"

        # 外来者
        if team == "outsider":
            outsider_claims = [
                f"{name}: 我是{role}，虽然帮不上太大忙但我是好人。别在我身上浪费处决。",
                f"{name}: 我是{role}。请大家把注意力放在{suspect or '真正可疑的人'}身上，我虽然是外来者但绝不帮邪恶。",
            ]
            return random.choice(outsider_claims)

        # 引用聊天记录整合信息（第2天起）
        if day > 1 and claim_map:
            clash_msgs = []
            roles_seen = {}
            for sp, rn in claim_map.items():
                if rn in roles_seen and roles_seen[rn] != sp:
                    clash_msgs.append(f"{sp}和{roles_seen[rn]}都自称{rn}")
                roles_seen[rn] = sp
            if clash_msgs:
                return f"{name}: 大家注意！{'，'.join(clash_msgs[:2])}，肯定有人在说谎！"
            if suspect and suspect in claim_map:
                return f"{name}: 我怀疑{suspect}，他自称{claim_map.get(suspect, '?')}但有很多疑点。大家注意观察他的投票和行为。"
            summary = '，'.join([f"{p}自称{r}" for p, r in list(claim_map.items())[:5]])
            return f"{name}: 我整理一下目前的信息：{summary}。大家看看有没有对不上的地方？"

        # 默认镇民第一天
        default_day1 = [
            f"{name}: 我是{role}，暂时没有关键信息。大家多交流才能找到线索。",
            f"{name}: 我是{role}，今天会仔细观察大家的发言再做判断。",
            f"{name}: 我是{role}。第一天信息有限，我重点观察{suspect or '有反常表现的人'}。",
            f"{name}: 我是{role}。希望能听到更多信息角色的分享，帮助锁定坏人。",
        ]
        return random.choice(default_day1)

    def _gen_fake_info(self, name, bluff_role):
        """生成伪装角色的假信息（更逼真）"""
        alive_names = self.get_alive_names()
        others = [n for n in alive_names if n != name]
        fake_victim = random.choice(others) if others else "某人"
        
        # 第二天起，可以引用前一天处决的情况
        exec_ref = ""
        if self.day_count >= 2 and self.last_executed:
            exec_ref = f"昨天被处决的{self.last_executed}大家还记得吧？"
        
        fakes = {
            "共情者": random.choice([
                f"昨晚我旁边的邪恶数是{random.randint(0,1)}，我觉得{random.choice(others) if others else '某人'}很可疑。",
                f"{exec_ref}昨晚我睡下时感应到左右邪恶数为{random.randint(0,1)}，数据说明问题。",
            ]),
            "占卜师": random.choice([
                f"昨晚我查了{random.choice(others)}和{random.choice(others)}，结果让我很在意。",
                f"{exec_ref}我的占卜结果指向了某个人，我需要更多信息确认。",
            ]),
            "厨师": random.choice([
                f"昨晚我得知相邻邪恶对数为{random.randint(0,1)}，这个数据很关键。",
                f"{exec_ref}厨师的结果显示邪恶分布有规律，大家想想谁和谁总在一起。",
            ]),
            "洗衣妇": random.choice([
                f"昨晚我得知了两名玩家的身份信息，已经基本确认了一个好人。",
                f"{exec_ref}我手里有两条身份信息，暂时不便公开但我会用来交叉验证。",
            ]),
            "调查员": random.choice([
                f"昨晚我查到了一个爪牙的线索！现在说出来怕打草惊蛇。",
                f"{exec_ref}调查结果指向{fake_victim}附近，我需要更多投票数据。",
            ]),
            "图书管理员": random.choice([
                f"昨晚我确认了外来者的情况，信息对好人有利。",
                f"{exec_ref}我的信息显示有些人自称的身份对不上，大家多留意。",
            ]),
            "僧侣": random.choice([
                f"昨晚我保护了{fake_victim}，如果今天他还活着说明我挡住了刀。",
                f"{exec_ref}僧侣的保护还在继续，恶魔的刀法会被我干扰。",
            ]),
            "士兵": "我是士兵，恶魔杀不了我，我可以安全活到最后提供信息。",
            "送葬者": random.choice([
                f"如果今天有人被处决，我就能知道他的真实身份。",
                f"{exec_ref}作为送葬者，我掌握着处决者的真实身份信息。",
            ]),
        }
        default_msgs = [
            "我得到了一些有用的信息，暂时不方便全部透露。",
            "根据我的观察，场上有人在说谎，大家多留意反常的发言。",
        ]
        return fakes.get(bluff_role, random.choice(default_msgs))

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

        # 猎手技能：基于推理决定是否开枪（每局一次）
        hunters = [a for a in self.registry.all_alive() if a.role == "猎手" and a.name not in self.hunter_used]
        for hunter in hunters:
            self._update_suspicion_from_chat(hunter)
            target = self._gen_hunter_decision(hunter)
            if target:
                self.hunter_used.add(hunter.name)
                target_agent = self.get_player_by_name(target)
                registered_role = self._get_registered_role(target_agent) if target_agent else None
                sus_score = hunter.game_state.get("suspicion", {}).get(target, 50)
                if sus_score >= 80:
                    shot_speech = f"我开枪射杀{target}！他是我最怀疑的人，必须解决！"
                elif sus_score >= 60:
                    shot_speech = f"我开枪射杀{target}！他的言行非常可疑，我赌他是恶魔！"
                else:
                    shot_speech = f"我开枪射杀{target}！虽然不确定，但概率上他最值得一试！"
                if target_agent and (target_agent.role in BOTC_TEAMS["demon"] or registered_role in BOTC_TEAMS["demon"]):
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
        """初始化邪恶阵营策略"""
        if hasattr(self, '_evil_inited'):
            return
        self._evil_inited = True
        self._evil_plan = {}  # {player_name: {fake_role: str, bus_target: str, strategy: str}}
        
        demons = [a for a in self.registry.all_agents() if a.role in BOTC_TEAMS["demon"]]
        minions = [a for a in self.registry.all_agents() if a.role in BOTC_TEAMS["minion"]]
        
        for demon in demons:
            gs = demon.game_state
            fake_roles = gs.get("known_info", {}).get("fake_roles", [])
            chosen_bluff = random.choice(fake_roles) if fake_roles else "镇民"
            self._evil_plan[demon.name] = {
                "fake_role": chosen_bluff,
                "strategy": "lead",
                "fake_data": {}
            }
        
        for minion in minions:
            minion_fake_roles = ["洗衣妇", "图书管理员", "厨师", "士兵", "僧侣", "管家"]
            chosen = random.choice(minion_fake_roles)
            self._evil_plan[minion.name] = {
                "fake_role": chosen,
                "strategy": "support",
                "fake_data": {}
            }

    def _gen_nomination_speech(self, nominator_name, target_name):
        """基于证据和推理的提名发言"""
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

        target_claims = set()
        for entry in memory:
            if entry.get("speaker") == target_name:
                txt = entry.get("text", "")
                for rn in BOTC_ROLES:
                    if f"我是{rn}" in txt:
                        target_claims.add(rn)

        reason_parts = []
        if known.get("investigator") and known["investigator"][0] == target_name:
            reason_parts.append(f"我是调查员，查出{target_name}是{known['investigator'][1]}(爪牙)")
        if known.get("empathy", 0) > 0:
            reason_parts.append(f"共情者显示旁边邪恶数{known['empathy']}，{target_name}是我邻居之一")
        if known.get("seer") and target_name in known["seer"][0] and known["seer"][1]:
            reason_parts.append(f"占卜师昨晚查{known['seer'][0][0]}和{known['seer'][0][1]}，{target_name}有恶魔嫌疑")
        if len(target_claims) > 1:
            reason_parts.append(f"{target_name}先后声称是{'/'.join(target_claims)}，身份反复变化")

        vote_info = self.game_record.get("vote_history", {})
        target_votes = []
        for day_str, votes in vote_info.items():
            for v in votes:
                if v.get("voter") == target_name:
                    target_votes.append(v.get("target"))
        if target_votes and len(target_votes) >= 2:
            reason_parts.append(f"{target_name}投票处决过{'/'.join(target_votes[:3])}")

        if suspicion > 75 and not reason_parts:
            reason_parts.append(f"综合{target_name}的发言表现，可疑度非常高")

        # 邪恶提名：如果提名的是自家人，战略性卖队友获取信任
        if nom_team in {"demon", "minion"}:
            target_team = BOTC_ROLES.get(target.role, {}).get("team", "")
            if target_team in {"demon", "minion"} and target_name != nominator_name:
                if random.random() < 0.3:  # 30%概率卖队友
                    return f"我提名{target_name}！我一直觉得{target_name}有问题，今天处决他获取关键信息！"
            fake_reasons = [
                f"{target_name}昨天的发言和今天完全对不上，明显在编故事",
                f"我注意到{target_name}在投票时跟着邪恶方走，行为反常",
                f"{target_name}一直在转移焦点，不敢正面回答质疑",
                f"根据我的观察，{target_name}给的信息和别人对不上，极有可能是邪恶的",
            ]
            if reason_parts:
                return f"我提名{target_name}！{'，'.join(reason_parts)}。今天必须处决他！"
            return f"我提名{target_name}！{random.choice(fake_reasons)}。今天必须解决这个威胁！"

        if reason_parts:
            return f"我提名{target_name}！{'，'.join(reason_parts)}。请大家支持处决！"
        return f"我提名{target_name}！根据我的观察，{target_name}的发言存在多处疑点，建议今天处决。"

    def _gen_defense_speech(self, target_name, nominator_name):
        """被提名者辩护发言"""
        target = self.get_player_by_name(target_name)
        if not target:
            return f"我是清白的！{nominator_name}在乱提名！"
        role = target.role
        team = BOTC_ROLES.get(role, {}).get("team", "")
        gs = target.game_state
        known = gs.get("known_info", {})

        if "seer" in known:
            chosen, has = known["seer"]
            demon_found = "查出了恶魔" if has else "正在缩小范围"
            return f"大家冷静！我是占卜师，{demon_found}，处决我会让好人失去重要信息来源！"
        if "empathy" in known:
            e = known["empathy"]
            return f"我是共情者，我旁边邪恶数为{e}。杀了我你们就失去每晚的邪恶探测了！"
        if "investigator" in known:
            inv_name, inv_role = known["investigator"]
            return f"我是调查员！我查出{inv_name}是{inv_role}，这才是真正的爪牙！别搞错目标！"
        if "washerwoman" in known:
            return f"我是洗衣妇，我知道某个玩家的身份，处决我信息就断了！"

        if role == "圣徒":
            return random.choice([
                f"我是圣徒！处决我会导致善良阵营直接落败！千万别投票处决我！",
                f"想清楚！我死了好人就输了！{nominator_name}在故意害好人！",
            ])
        if role == "镇长":
            return "我是镇长！活着的镇长才有用！而且只有3人存活时我能直接带来胜利！"
        if role == "士兵":
            return "我是士兵，恶魔杀不了我，我可以一直活到决赛圈提供帮助！"
        if role == "僧侣":
            return "我是僧侣，每晚能保护一个人不被恶魔杀，我活着对好人很重要！"
        if role == "管家":
            return f"我是管家，虽然能力有限但我始终支持好人。{nominator_name}的信息是错的！"

        if team in {"demon", "minion"}:
            return random.choice([
                f"大家别被{nominator_name}带节奏！他才是真正可疑的人！",
                f"我完全清白！{nominator_name}拿不出实质证据就想处决我，反而暴露了他自己！",
                f"冷静分析一下：{nominator_name}为什么急着处决我？因为他怕我活着揭穿他！",
            ])

        return random.choice([
            f"我是{role}，虽然不起眼但也是好人！{nominator_name}的指控没有实质证据！",
            f"大家想一想，{nominator_name}的指控站得住脚吗？他能拿出证据吗？",
            f"我确实是{role}，如果怀疑我可以继续观察，但今天处决我太草率了！",
        ])

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
            if nom_agent and nom_agent.game_state.get("suspicion"):
                sorted_targets = sorted(targets, key=lambda t: nom_agent.game_state["suspicion"].get(t, 50), reverse=True)
                target = sorted_targets[0]
            else:
                target = random.choice(targets)

            # 贞洁者能力：第一次被提名时，若提名者是镇民则提名者被处决
            target_agent = self.get_player_by_name(target)
            if target_agent and target_agent.role == "贞洁者":
                self.nomination_count[target] = self.nomination_count.get(target, 0) + 1
                if self.nomination_count[target] == 1:
                    nominator_agent = self.get_player_by_name(nominator)
                    if nominator_agent and nominator_agent.role in BOTC_TEAMS["townsfolk"]:
                        nominator_agent.alive = False
                        self.dead_players.append(nominator)
                        self.executed_today = True
                        self.log(f"  [贞洁者] {target}是贞洁者! 提名者{nominator}是镇民, 被立即处决!")
                        self._check_game_end()
                        if self.game_record.get('result'):
                            return
                        continue

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

        # 邪恶阵营：战略性投票（含卖队友策略）
        if voter.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
            nom_agent = self.get_player_by_name(nominee)
            if nom_agent and nom_agent.role in BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"]:
                return 0.85
            # 卖队友策略：30%概率投票处决邪恶队友获取信任
            if nom_agent and nom_agent.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
                if nom_agent.name == voter.name:
                    return 0.0
                # 如果场上存活人数<=4，不再内讧
                alive_count = len(self.get_alive_names())
                if alive_count <= 4:
                    return 0.0
                if random.random() < 0.3:
                    return 0.85
            return 0.2

        # 善良阵营：基于怀疑/信任评分
        base = (suspicion - 50) / 50  # -1 ~ +1
        if "seer" in known_info:
            chosen, has = known_info["seer"]
            if nominee in chosen and has:
                return 0.95
            if nominee in chosen and not has:
                return 0.15
        if "investigator" in known_info:
            inv_name, inv_role = known_info["investigator"]
            if nominee == inv_name:
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
        for voter_name in alive_names:
            if voter_name == nominee:
                continue
            voter = self.get_player_by_name(voter_name)
            if not voter or not voter.alive:
                continue
            self._update_suspicion_from_chat(voter)
            vote_prob = self._get_vote_probability(voter, nominee)
            cast_vote = random.random() < vote_prob
            if cast_vote:
                vote_records.append({"voter": voter_name, "target": nominee, "day": self.day_count})
            if cast_vote:
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
        return self.game_record
