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
    is_enabled, is_recording, set_record, set_epsilon,
    add_reward, consume_reward
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
        self.seer_cleared = set()  # P3: 占卜师公开排好人名单，供全员投票参考
        self.info_overlap = {}     # 好人信息交叉: {玩家名: 被几个信息位质疑}
        self.info_credibility = {} # 信息位公信力: {玩家名: 乘数(0.5~1.5)}
        self._last_night_kill = ''

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
        # P0: 开局双恶魔检测——违反暗流涌动规则直接报错
        demon_count = sum(1 for a in agents if a.role in BOTC_TEAMS["demon"])
        if demon_count != 1:
            demon_names = [a.name for a in agents if a.role in BOTC_TEAMS["demon"]]
            self.log(f"  [错误] 开局恶魔数量={demon_count}({demon_names})——应为1！正在修复...")
            # 保留第一个恶魔，其余降级为投毒者且从邪恶战术中移除
            for extra in demon_names[1:]:
                extra_agent = self.get_player_by_name(extra)
                if extra_agent:
                    extra_agent.role = "投毒者"
                    extra_agent.game_state["role"] = "投毒者"
                    # 从evil_plan移除，防止SW继承逻辑误判
                    if extra in getattr(self, '_evil_plan', {}):
                        del self._evil_plan[extra]
                    self.log(f"    {extra} 降级为投毒者(已从邪恶战术移除)")

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
        if self.game_record.get('result'):
            return
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
        demon_agents = self.registry.get_by_role("小恶魔")
        minion_agents = self.registry.get_by_role("投毒者") + self.registry.get_by_role("间谍") + \
                        self.registry.get_by_role("红唇女郎") + self.registry.get_by_role("男爵")

        if self.num_players >= 7 and demon_agents:
            for m in minion_agents:
                m.game_state["known_info"]["demon"] = demon_agents[0].name
            for d in demon_agents:
                in_play_roles = set(a.role for a in self.registry.all_agents())
                all_good_roles = BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"]
                off_script = [r for r in all_good_roles if r not in in_play_roles]
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

        self.log("给各个玩家发送信息")

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
            get_trainer().record_step(log_prob, consume_reward())
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
        # 排除士兵、僧侣保护、己方爪牙、其他恶魔（不能刀队友/同阵营）
        minion_names = [m.name for m in minions]
        demon_names = [d.name for d in self.registry.all_agents() if d.role in BOTC_TEAMS["demon"] and d.name != player.name]
        # 好人全灭时→允许刀爪牙以触发邪恶获胜条件(存活≤2人)
        good_alive = [a for a in self.registry.all_alive() if a.role not in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]]
        exclude_names = set() if not good_alive else set(minion_names + demon_names)
        valid_targets = [t for t in target_pool
                         if not any(s == t for s in soldier_names)
                         and t != self.protected_player
                         and t not in exclude_names]
        if not valid_targets:
            # 最后手段：排除士兵和僧侣保护；好人全灭时可刀爪牙
            valid_targets = [t for t in target_pool if not any(s == t for s in soldier_names) and t != self.protected_player and t not in exclude_names]
        if not valid_targets:
            return

        # Fix 2: 分层击杀优先级（信息位 > 功能位 > 普通镇民 > 外来者）
        info_roles = ["占卜师", "共情者", "调查员", "送葬者", "守鸦人", "厨师", "洗衣妇", "图书管理员"]
        func_roles = ["猎手", "镇长", "士兵"]
        _, _, claim_map = self._build_chat_summary(player)
        info_claimants = [p for p in valid_targets if p in claim_map and claim_map[p] in info_roles]
        # 首夜用间谍共享信息兜底（claim_map为空）
        if not info_claimants:
            spy_shared = player.game_state.get("known_info", {}).get("spy_shared", {})
            info_roles_known = spy_shared.get("info_roles", {})
            info_claimants = [p for p in valid_targets if info_roles_known.get(p) in info_roles]
        # 漏杀兜底: 用真实角色补全——占卜师/调查员即使未公开声明也要优先刀
        if not info_claimants or "占卜师" not in [claim_map.get(p,"") for p in info_claimants]:
            real_seers = [p for p in valid_targets if self.get_player_by_name(p) and self.get_player_by_name(p).role == "占卜师"]
            if real_seers:
                info_claimants = list(set(info_claimants + real_seers))
        
        # Fix G: 红唇女郎战术 — 恶魔高怀疑时自杀传位（至少存活2天）
        has_sw_sacrifice = False
        if can_suicide:
                has_sw = any(m.role == "红唇女郎" for m in minions)
                my_sus = player.game_state.get("suspicion", {})
                avg_sus = sum(my_sus.values()) / len(my_sus) if my_sus else 0
                min_days = 3 if avg_sus < 80 else 2  # 高怀疑可提前, 低怀疑需积累
                has_sw_sacrifice = has_sw and avg_sus > 60 and self.day_count >= min_days and random.random() < 0.4
        
        if info_claimants and random.random() < 0.75 and not has_sw_sacrifice:
            # 刀人叙事: 优先杀对跳冲突中的目标(杀一诬一)
            claim_conflicts_kill = set()
            seen_c = {}
            for sp, rn in self.public_claims.items():
                if rn in seen_c:
                    claim_conflicts_kill.add(sp)
                    claim_conflicts_kill.add(seen_c[rn])
                seen_c[rn] = sp
            conflict_info = [p for p in info_claimants if p in claim_conflicts_kill]
            if conflict_info and random.random() < 0.5:
                target = random.choice(conflict_info)
            else:
                target = random.choice(info_claimants)
        elif has_sw_sacrifice:
            target = player.name
        else:
            func_claimants = [p for p in valid_targets if p in claim_map and claim_map[p] in func_roles]
            if func_claimants and random.random() < 0.6:
                target = random.choice(func_claimants)
            else:
                # 排除外来者（最低优先级）
                outsider_roles = BOTC_TEAMS.get("outsider", [])
                non_outsider = [p for p in valid_targets
                                if p not in claim_map or claim_map.get(p, "") not in outsider_roles]
                priority_pool = non_outsider if non_outsider else valid_targets
                target = self._ml_pick_kill_target(player, priority_pool)
                if not target:
                    target = random.choice(priority_pool)
        target_agent = self.get_player_by_name(target)

        if target == player.name:
            red_lip = [m for m in minions if m.role == "红唇女郎"]
            new_demon = None
            if red_lip:
                new_demon = red_lip[0]
            # 只有红唇女郎能继承，其它爪牙无资格
            if new_demon:
                new_demon.role = "小恶魔"
                new_demon.game_state["role"] = "小恶魔"
                new_demon.game_state["original_role"] = "红唇女郎"
                new_minions = [m.name for m in minions if m.name != new_demon.name]
                new_demon.game_state["known_info"]["minions"] = new_minions
            # 自杀计入死亡
            target_agent.alive = False
            self.dead_players.append(target)
            self.peaceful_night = False
            self._last_night_kill = target
            self.record_action(player.name, "恶魔自杀", f"自杀传位给{new_demon.name if new_demon else '无爪牙(邪恶落败)'}", "night_action")
            if not new_demon:
                self._check_game_end()
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
                    self._last_night_kill = real_target
                    self.record_action(player.name, "恶魔杀人", f"攻击镇长{target},但{real_target}代为死亡", "night_action")
                    return
            target_agent.alive = False
            self.dead_players.append(target)
            self.peaceful_night = False
            self._last_night_kill = target
            self.record_action(player.name, "恶魔杀人", f"杀害{target}", "night_action")
            # P3过程奖励: 刀中信息位+0.3, 刀中队友-0.5
            target_team = BOTC_ROLES.get(target_agent.role, {}).get("team", "")
            if target_team in ("townsfolk", "outsider"):
                info_roles = {"占卜师","共情者","调查员","洗衣妇","厨师","送葬者","守鸦人","图书管理员"}
                if target_agent.role in info_roles:
                    add_reward(0.3)
                else:
                    add_reward(0.1)
            elif target_team in ("demon", "minion"):
                add_reward(-0.5)

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
                    else:
                        rk.game_state["known_info"]["ravenkeeper"] = (target.name, target.role)

        all_actors = alive_players + drunk_players
        for player in all_actors:
            is_drunk_actor = player in drunk_players

            if role_name == "投毒者":
                targets = [a.name for a in self.registry.all_alive() if a.name != player.name]
                if targets:
                    # 首夜：强制毒占卜师（不依赖概率/spy信息）
                    info_roles = ["占卜师", "共情者", "调查员", "洗衣妇", "厨师", "送葬者", "守鸦人", "图书管理员"]
                    if is_first:
                        seers = [a.name for a in self.registry.all_agents() if a.role == "占卜师" and a.alive]
                        if seers:
                            target = seers[0]
                        else:
                            # 无占卜师则毒调查员
                            investigators = [a.name for a in self.registry.all_agents() if a.role == "调查员" and a.alive]
                            target = investigators[0] if investigators else random.choice(targets)
                    else:
                        _, _, claim_map = self._build_chat_summary(player)
                        info_claims = [t for t in targets if t in claim_map and claim_map[t] in info_roles]
                        if not info_claims:
                            spy_shared = player.game_state.get("known_info", {}).get("spy_shared", {})
                            info_roles_known = spy_shared.get("info_roles", {})
                            info_claims = [t for t in targets if info_roles_known.get(t) in info_roles]
                        if info_claims and random.random() < 0.85:
                            target = random.choice(info_claims)
                        else:
                            target = random.choice(targets)
                    self.poisoned_players.add(target)
                    target_agent = self.get_player_by_name(target)
                    if target_agent:
                        target_agent.game_state["is_poisoned"] = True
                    context = f"投毒者选择目标"
                    self.record_action(player.name, context, f"对{target}下毒", "night_action")


            elif role_name == "小恶魔" and not is_first:
                self._imp_kill(player)

            elif role_name == "僧侣":
                others = [a.name for a in self.registry.all_alive() if a.name != player.name]
                if others:
                    # P0-2: 排除自己的高嫌疑目标（不能保护自己认为的恶魔）
                    sus = player.game_state.get("suspicion", {})
                    top_suspect = max(sus, key=sus.get) if sus and any(s >= 70 for s in sus.values()) else None
                    if top_suspect and top_suspect in others:
                        others.remove(top_suspect)
                    # 方向2: 保护优先级——信息位 > 带队位 > 普通镇民
                    _, _, claim_map_monk = self._build_chat_summary(player)
                    info_claimants = [n for n in others if claim_map_monk.get(n) in ("占卜师","共情者","调查员","洗衣妇","厨师","送葬者","守鸦人","图书管理员")]
                    leader_claimants = [n for n in others if claim_map_monk.get(n) in ("镇长","猎手","士兵")]
                    if info_claimants and random.random() < 0.8:
                        protect = random.choice(info_claimants)
                    elif leader_claimants and random.random() < 0.6:
                        protect = random.choice(leader_claimants)
                    else:
                        protect = random.choice(others)
                    if not is_drunk_actor:
                        self.protected_player = protect
                    player.game_state["protected"] = protect
                    player.game_state["known_info"]["monk"] = protect


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


            elif role_name == "送葬者" and not is_first:
                if self.last_executed:
                    exec_agent = self.get_player_by_name(self.last_executed)
                    if exec_agent:
                        if is_drunk_actor:
                            fake_role = random.choice(BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"] + BOTC_TEAMS["minion"] + BOTC_TEAMS["demon"])
                            player.game_state["known_info"]["undertaker"] = fake_role

                        else:
                            player.game_state["known_info"]["undertaker"] = exec_agent.role


            elif role_name == "间谍":
                all_roles_info = {a.name: a.role for a in self.registry.all_agents()}
                player.game_state["known_info"]["spy_info"] = all_roles_info
                # 首夜立即向恶魔和投毒者广播核心信息位身份
                info_roles = ["占卜师","共情者","调查员","洗衣妇","厨师","送葬者","守鸦人","图书管理员"]
                func_roles = ["士兵","镇长","猎手"]
                demon_name = player.game_state.get("known_info", {}).get("demon", "")
                minion_names = player.game_state.get("known_info", {}).get("minions", [])
                for target_name in [demon_name] + minion_names:
                    if target_name and target_name != player.name:
                        target_agent = self.get_player_by_name(target_name)
                        if target_agent:
                            target_agent.game_state["known_info"]["spy_shared"] = {
                                "info_roles": {n: r for n, r in all_roles_info.items() if r in info_roles},
                                "func_roles": {n: r for n, r in all_roles_info.items() if r in func_roles},
                                "kill_priority": [n for n, r in all_roles_info.items() if r in info_roles],
                            }


            elif role_name == "管家":
                others = [a.name for a in self.registry.all_alive() if a.name != player.name]
                if others:
                    master = random.choice(others)
                    player.game_state["known_info"]["master"] = master


            elif role_name == "洗衣妇" and is_first:
                if is_drunk_actor:
                    alive = [a for a in self.registry.all_agents() if a.alive and a.name != player.name]
                    if len(alive) >= 2:
                        candidates = random.sample(alive, 2)
                        fake_role = random.choice(BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"])
                        player.game_state["known_info"]["washerwoman"] = (candidates[0].name, candidates[1].name, fake_role)

                else:
                    alive = [a for a in self.registry.all_agents() if a.alive and a.name != player.name]
                    if len(alive) >= 2:
                        chosen = random.sample(alive, 2)
                        registered_townsfolk = [c for c in chosen if self._get_registered_team(c) == "townsfolk"]
                        target = registered_townsfolk[0] if registered_townsfolk else chosen[0]
                        shown_role = self._get_registered_role(target)
                        player.game_state["known_info"]["washerwoman"] = (chosen[0].name, chosen[1].name, shown_role)


            elif role_name == "图书管理员" and is_first:
                if is_drunk_actor:
                    alive = [a for a in self.registry.all_agents() if a.alive and a.name != player.name]
                    if len(alive) >= 2:
                        candidates = random.sample(alive, 2)
                        fake_role = random.choice(BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"])
                        player.game_state["known_info"]["librarian"] = (candidates[0].name, candidates[1].name, fake_role)

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

                    else:
                        player.game_state["known_info"]["librarian"] = ("无", "无", "本局没有外来者")


            elif role_name == "调查员" and is_first:
                if is_drunk_actor:
                    alive = [a for a in self.registry.all_agents() if a.alive and a.name != player.name]
                    if len(alive) >= 2:
                        candidates = random.sample(alive, 2)
                        fake_role = random.choice(BOTC_TEAMS["minion"])
                        player.game_state["known_info"]["investigator"] = (candidates[0].name, candidates[1].name, fake_role)

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
        if self.game_record.get('result'):
            return
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
            # P2: 死后复盘——处决好人→升投赞成者的嫌疑；处决坏人→升投反对者的嫌疑
            executed = self.last_executed
            if executed:
                exec_agent = self.get_player_by_name(executed)
                if exec_agent:
                    exec_team = BOTC_ROLES.get(exec_agent.role, {}).get("team", "")
                    vote_history = self.game_record.get("vote_history", {})
                    day_key = f"day_{self.day_count}"
                    day_votes = vote_history.get(day_key, [])
                    for v in day_votes:
                        voter = v.get("voter", "")
                        voter_agent = self.get_player_by_name(voter)
                        if not voter_agent:
                            continue
                        if exec_team in ("townsfolk", "outsider"):
                            # 处决了好人→投赞成的人嫌疑加大
                            voter_agent.game_state["suspicion"][voter] = voter_agent.game_state["suspicion"].get(voter, 50) + 10
                        elif exec_team in ("demon", "minion"):
                            # 处决了坏人→投赞成的人洗清嫌疑
                            for p in self.registry.all_agents():
                                if p.name != voter:
                                    p.game_state["trust"][voter] = p.game_state["trust"].get(voter, 50) + 5
                    # 信息位公信力: 处决结果验证→调整credibility
                    for a in self.registry.all_agents():
                        known = a.game_state.get("known_info", {})
                        targets = []
                        if "seer" in known and known["seer"][1]:  # has_demon
                            targets = list(known["seer"][0])
                        elif "investigator" in known:
                            inv = known["investigator"]
                            targets = [inv[0], inv[1]] if len(inv) == 3 else [inv[0]]
                        if executed in targets:
                            old_cred = self.info_credibility.get(a.name, 1.0)
                            if exec_team in ("demon", "minion"):
                                self.info_credibility[a.name] = min(1.5, old_cred + 0.15)
                            else:
                                self.info_credibility[a.name] = max(0.5, old_cred - 0.15)
        else:
            self.log(f"\n[平安日] 今天无人被处决, 是个平安日。")
        # Schema战术: 终局隐身奖励——未被提名的邪恶方+0.15, 成功偏转(邪恶提名→非邪被处决)+0.2
        nominations_today = self.game_record.get("nomination_history", {}).get(f"day_{self.day_count}", [])
        nominated_players = {n["target"] for n in nominations_today}
        for a in self.registry.all_alive():
            if a.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
                if a.name not in nominated_players:
                    add_reward(0.15)  # 完美隐身
        if self.executed_today:
            exec_target = self.last_executed
            if exec_target:
                exec_agent = self.get_player_by_name(exec_target)
                if exec_agent and exec_agent.role not in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
                    for n in nominations_today:
                        nom = n.get("nominator", "")
                        nom_agent = self.get_player_by_name(nom)
                        if nom_agent and nom_agent.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
                            add_reward(0.2)  # 邪恶提名好人→好人被处决=成功偏转
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
        if self.game_record.get('result'):
            return
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
            thread_key = f"D{self.day_count}_{names[0]}🔄{names[1]}"
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
        # Fix T: 邪恶不能把队友当目标
        team = BOTC_ROLES.get(player.role, {}).get("team", "")
        is_evil = team in ("demon", "minion")
        teammates = []
        if is_evil:
            known = gs.get("known_info", {})
            demon_name = known.get("demon", "")
            minions = known.get("minions", [])
            teammates = [demon_name] + minions if demon_name else minions
        if gs.get("suspicion"):
            sorted_suspects = sorted(gs["suspicion"].items(), key=lambda x: -x[1])
            for name, score in sorted_suspects:
                if score >= 60 and name != player.name and name not in teammates:
                    return name
        # 随机兜底
        alive = [a for a in self.registry.all_agents() if a.alive and a.name != player.name and a.name not in teammates]
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
        vote_str = "，".join(vote_parts[:4]) if vote_parts else ""
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
        vote_str = "，".join(vote_parts[:4]) if vote_parts else ""
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

    # ========== 硬约束：发言前状态校验 ==========
    def _validate_speech_kwargs(self, player, kwargs, scene="public"):
        """发言前校验与修复，杜绝自指、时间线穿越、身份张冠李戴"""
        name = player.name
        gs = player.game_state
        day = self.day_count
        _, _, claim_map = self._build_chat_summary(player) if scene != "private" else (None, None, {})

        # 1. 禁止自指 + 禁止引用死者：所有str kwarg中引用死者的替换为存活玩家
        alive_now = self.get_alive_names()
        for key in list(kwargs.keys()):
            val = kwargs.get(key, "")
            if isinstance(val, str) and val in self.dead_players:
                alive_others = [p for p in alive_now if p != name]
                kwargs[key] = alive_others[0] if alive_others else "某人"
            if val == name:
                alive_others = [p for p in alive_now if p != name]
                kwargs[key] = alive_others[0] if alive_others else "某人"

        # 2. 时间线穿越：无投票时清空 vote_str
        vote_info = self.game_record.get("vote_history", {})
        has_any_vote = any(v for _, v in vote_info.items())
        if not has_any_vote and "vote_str" in kwargs:
            kwargs["vote_str"] = ""

        # 3. 身份张冠李戴：校验 claim_map 引用（包含公聊和私聊）
        if claim_map or scene == "public":
            _, _, claim_map_full = self._build_chat_summary(player)
            cm = claim_map or claim_map_full
            if cm:
                for key in ("claim", "listener_fake", "battle_role", "ww_role"):
                    val = kwargs.get(key, "")
                    other_key = "target" if key == "claim" else ("listener" if key == "listener_fake" else None)
                    person = kwargs.get(other_key, "") if other_key else None
                    if person and person != "某人" and val not in ("?", "身份不明", "未声明", "") and person in cm:
                        expected = cm.get(person, "")
                        if expected and val != expected:
                            kwargs[key] = expected

                # 3b. 检查所有str kwarg中是否包含"XX自称YY"但YY与claim_map不符
                for k, v in kwargs.items():
                    if isinstance(v, str) and "自称" in v and "是" in v:
                        for p, expected_role in cm.items():
                            for phrase_part in v.split("，"):
                                if f"{p}自称" in phrase_part or f"{p}是" in phrase_part:
                                    for rn in BOTC_ROLES:
                                        if rn in phrase_part and rn != expected_role and expected_role:
                                            kwargs[k] = v.replace(f"{rn}", f"{expected_role}")

        # 4. contradict_str 必须有真实矛盾
        if "contradict_str" in kwargs and kwargs["contradict_str"] in ("", "暂无矛盾"):
            kwargs["contradict_str"] = ""

        # 5. Fix AF: 信息位锚定——target 必须来自自身技能范围
        if scene == "public" and "target" in kwargs:
            known = player.game_state.get("known_info", {})
            alive = [a for a in self.get_alive_names() if a != player.name]
            info_targets = []
            if "investigator" in known:
                inv = known["investigator"]
                info_targets = [inv[0], inv[1]] if len(inv) == 3 else [inv[0]]
            elif "washerwoman" in known:
                ww = known["washerwoman"]
                info_targets = [ww[0], ww[1]] if len(ww) == 3 else [ww[0]]
            elif "seer" in known:
                seer_data = known["seer"]
                info_targets = list(seer_data[0]) if isinstance(seer_data[0], (list, tuple)) else [seer_data[0]]
            elif "empathy" in known:
                idx = self.player_order.index(player.name)
                info_targets = [self.player_order[(idx - 1) % len(self.player_order)],
                                self.player_order[(idx + 1) % len(self.player_order)]]
            if info_targets:
                in_range = [t for t in info_targets if t in alive]
                if in_range:
                    target_val = kwargs.get("target", "")
                    suspect_val = kwargs.get("suspect", "")
                    if target_val not in info_targets and suspect_val not in info_targets:
                        kwargs["target"] = random.choice(in_range)

        return kwargs

    # ========== 信息交叉验证（Fix F） ==========
    def _build_cross_ref(self, player):
        """检查其他信息位已公开的信息，生成交叉引用"""
        name = player.name
        _, _, claim_map = self._build_chat_summary(player)
        my_role = player.game_state.get("fake_role", player.role) if player.game_state.get("is_drunk") else player.role
        info_roles = ["占卜师", "共情者", "调查员", "洗衣妇", "厨师", "送葬者", "守鸦人", "图书管理员"]
        other_info_roles = [r for r in info_roles if r != my_role]
        other_infos = [(p, r) for p, r in claim_map.items() if p != name and r in other_info_roles]
        if not other_infos:
            return ""
        # 交叉验证+0.15
        add_reward(0.15)
        p1, r1 = other_infos[0]
        pool = [n for n in self.get_alive_names() if n not in (name, p1)]
        common_target = random.choice(pool[:3]) if pool else "某人"
        styles = [
            f"{p1}自称{r1}，他的信息范围应该包含{common_target}——这跟我的分析可以交叉验证。",
            f"对了，{p1}是{r1}，他掌握的信息跟我查到的范围可能有重叠部分，建议大家对一下。",
            f"我注意到{p1}也报了{r1}身份——两个信息位的结果如果能对上，就能锁定范围了。",
        ]
        return random.choice(styles)

    # ========== 强制外来者计数（Fix K） ==========
    def _build_outsider_hint(self, player):
        """计算当前外来者认领数 vs 预期，生成提示"""
        _, _, claim_map = self._build_chat_summary(player)
        expected = self.expected_outsider_count()
        outsider_roles = BOTC_TEAMS.get("outsider", [])
        claimed_outsiders = [p for p, r in claim_map.items() if r in outsider_roles]
        actual = len(claimed_outsiders)
        if actual == expected:
            return ""
        if expected == 0 and actual > 0:
            names = "、".join(claimed_outsiders[:3])
            return f"本局预期没有外来者，但已经有{actual}个人自称外来者（{names}）了——这个数字对不上，说明有人在冒充！"
        if actual < expected:
            missing = expected - actual
            return f"按人数计算，本局应该有{expected}个外来者，但现在只有{actual}个人认领——还有{missing}个外来者没有报身份，或者有人在隐瞒。"
        if actual > expected:
            over = actual - expected
            return f"场上已经有{actual}个人声称是外来者，但本局最多只有{expected}个——多了{over}个，说明要么有男爵（额外加外来者），要么有人冒充外来者！"
        return ""

    # ========== 男爵/酒鬼容错（Fix O） ==========
    def _build_drunk_warning(self, player):
        """男爵在场时，提示信息可能有酒鬼干扰"""
        _, _, claim_map = self._build_chat_summary(player)
        all_minions = [a.role for a in self.registry.all_agents() if a.role in BOTC_TEAMS["minion"]]
        has_baron = "男爵" in all_minions
        if not has_baron or self.day_count > 4:
            return ""
        # Fix AN: 存在身份矛盾时提升警告概率
        contradict = []
        seen_roles = {}
        for sp, rn in claim_map.items():
            if rn in seen_roles and seen_roles[rn] != sp:
                contradict.append(f"{sp}和{seen_roles[rn]}都自称{rn}")
            seen_roles[rn] = sp
        alert_prob = 0.8 if contradict else 0.4
        if random.random() < alert_prob:
            styles = [
                f"对了，本局有男爵在场，意味着有酒鬼存在——信息位的查验结果可能不完全准确，大家交叉验证时要留容错空间。",
                f"提醒大家：男爵在场意味着好人有酒鬼，任何一个信息位的结论都有可能因为酒鬼出错。如果遇到信息矛盾，先排查酒鬼干扰再做结论。",
                f"男爵在场的信息环境很复杂——酒鬼可能报出完全错误的信息而不自知。如果不同的信息位对不上，别急着互踩，先想想是不是有酒鬼在报假信息。",
            ]
            return random.choice(styles)
        return ""

    # ========== 陌客认知警告（Fix W） ==========
    def _build_recluse_warning(self, player):
        """陌客在场时，提示被查验可能显邪恶"""
        _, _, claim_map = self._build_chat_summary(player)
        all_outsiders = [a.role for a in self.registry.all_agents() if a.role in BOTC_TEAMS.get("outsider", [])]
        has_recluse = "陌客" in all_outsiders
        if not has_recluse:
            return ""
        # 检查自认陌客的玩家
        recluse_claimants = [p for p, r in claim_map.items() if r == "陌客"]
        if not recluse_claimants or random.random() > 0.5:
            return ""
        rname = recluse_claimants[0]
        styles = [
            f"提醒一句：{rname}是陌客，陌客被查验会错误显示为邪恶。如果占卜师/调查员查到他身上，那个「恶魔反应」需要打折扣——不能当铁证用。",
            f"场上有个陌客{rname}——大家别忘了，陌客被占卜师查验会显示为恶魔，被调查员查验会显示为爪牙。所以指向{rname}的查验结果要排除这个干扰。",
            f"陌客的机制需要大家记住：{rname}被任何信息位查验时，说书人都会谎报他为邪恶。如果你看到{rname}被「查出来」，别急着下定论——被查出来才是正常的。",
        ]
        return random.choice(styles)

    # ========== 外来者基准告知（Fix AE） ==========
    def _build_expected_outsider_info(self, player):
        """告知全员外来者数量基准（前3天强制，之后只在有异常时输出）"""
        if self.day_count > 3:
            return ""
        _, _, claim_map = self._build_chat_summary(player)
        expected = self.expected_outsider_count()
        outsider_roles = BOTC_TEAMS.get("outsider", [])
        claimed = [p for p, r in claim_map.items() if r in outsider_roles]
        return f"本局{self.num_players}人场标准配置{expected}个外来者，目前{len(claimed)}人认领。如果数字对不上，可能有人隐藏身份或有男爵。"
        
    # ========== 阶段论据池（方向3） ==========
    def _init_stage_evidence(self):
        """初始化当前阶段的可用论据池"""
        day = self.day_count
        vote_info = self.game_record.get("vote_history", {})
        has_votes = any(v for _, v in vote_info.items())
        deaths = self.dead_players[:]

        pool = []

        # 阶段0: 首日无投票 — 只能盘发言和身份声明
        if day <= 1 and not has_votes:
            pool = ["身份跳法是否合理", "发言是否含有有效信息", "是否回避关键问题", "是否前后口径不一"]

        # 阶段1: 有投票后 — 可分析票型
        elif has_votes and not deaths:
            pool = ["投票行为与发言立场是否一致", "是否与可疑人员抱团投票", "是否异常弃票",
                    "身份跳法是否合理", "是否前后口径不一"]

        # 阶段2: 有人死亡后 — 可反推利益关系
        elif deaths:
            pool = ["死者身份与之前发言是否匹配", "谁曾力保或死踩死者",
                    "死亡结果对谁最有利", "投票行为与发言立场是否一致",
                    "是否与可疑人员抱团投票"]

        # 阶段3: 决赛圈（3-4人存活）
        alive = self.get_alive_names()
        if len(alive) <= 4:
            pool.append("存活者中谁始终未被质疑")
            pool.append("投票历史中谁的立场反复变化")

        self.game_record[f"_evidence_pool_D{day}"] = pool

    def _get_stage_evidence(self, target_name, player):
        """获取针对特定目标的阶段可用论据"""
        day = self.day_count
        pool = self.game_record.get(f"_evidence_pool_D{day}", [])
        gs = player.game_state
        memory = gs.get("chat_memory", [])
        evidence = []

        for e in pool:
            if e == "身份跳法是否合理":
                _, _, claim_map = self._build_chat_summary(player)
                tc = claim_map.get(target_name, "")
                if tc:
                    evidence.append(f"{target_name}自称{tc}")
            elif e == "是否回避关键问题":
                dodged = False
                for m in memory:
                    if m.get("speaker") == target_name and ("反问" in m.get("text","") or "你凭什么" in m.get("text","") or "你觉得呢" in m.get("text","")):
                        dodged = True; break
                if dodged:
                    evidence.append(f"{target_name}被质疑时习惯反问而非自证")
            elif e == "是否前后口径不一":
                claims = set()
                for m in memory:
                    if m.get("speaker") == target_name:
                        for rn in BOTC_ROLES:
                            if f"我是{rn}" in m.get("text",""):
                                claims.add(rn)
                if len(claims) > 1:
                    evidence.append(f"{target_name}先后声称{'/'.join(claims)}，口径不一致")
            elif e == "投票行为与发言立场是否一致":
                vote_info = self.game_record.get("vote_history", {})
                for _, votes in vote_info.items():
                    for v in votes:
                        if v.get("voter") == target_name:
                            evidence.append(f"{target_name}投了{v.get('target')}")
            elif "死亡" in e or "死者" in e:
                for d in self.dead_players:
                    evidence.append(f"{d}已死亡")

        return evidence[:3]  # 最多3条

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
        my_recent_msgs = []
        for m in reversed(gs.get("chat_memory", [])):
            if m.get("speaker") == listener and m.get("phase") == "private_chat" and m.get("listener") == name:
                partner_last_msg = m.get("text", "")
                break
        # P1-5: 检测自己最近3轮的重复度
        for m in reversed(gs.get("chat_memory", [])):
            if m.get("speaker") == name and m.get("listener") == listener and m.get("phase") == "private_chat":
                my_recent_msgs.append(m.get("text", ""))
                if len(my_recent_msgs) >= 3:
                    break
        force_info = len(my_recent_msgs) >= 3 and all(
            any(kw in msg for kw in ("可疑", "有问题", "怀疑", "不对劲")) for msg in my_recent_msgs[:3]
        )

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
        votes_exist = bool(listener_votes or speaker_votes)
        vote_str = "，".join(
            [f"{p}投了{t}" for p, t in
             ([(listener, t) for t in listener_votes] + [(name, t) for t in speaker_votes])][:4]
        ) if votes_exist else ""
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
        kwargs = self._validate_speech_kwargs(player, kwargs, scene="private")

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
                    cat = random.choice(["EVIL_FIRST_CONTACT_PADDED", "EVIL_FIRST_CONTACT",
                                         "EVIL_FIRST_CONTACT"])  # 40% padded
                t = DD.get_filled(cat, used=used, **kwargs)
                t = DD.naturalize(t)
                return f"{name}: {t}"

            # 爪牙对恶魔（含间谍信息）
            if team == "minion" and demon_name == listener:
                kwargs["demon_name"] = demon_name
                if spy_info_dict:
                    # 按威胁排序：信息位优先，全量共享
                    info_priority_role = ["占卜师", "共情者", "调查员", "洗衣妇", "厨师", "送葬者", "守鸦人", "图书管理员"]
                    all_players = list(spy_info_dict.items())
                    all_players.sort(key=lambda x: (
                        0 if x[1] in info_priority_role else 1,
                        0 if BOTC_ROLES.get(x[1], {}).get("team") in ("townsfolk", "outsider") else 1
                    ))
                    threat_list = [f"{n}({r})" for n, r in all_players[:4]]
                    kwargs["spy_info"] = "、".join(threat_list)
                    # 锁定最高威胁信息位为首要目标
                    info_targets = [n for n, r in all_players if r in info_priority_role]
                    kwargs["target"] = info_targets[0] if info_targets else (all_players[0][0] if all_players else suspect)
                    # Fix AM: 间谍提供精准刀人建议
                    func_threats = ["猎手","贞洁者","镇长","士兵","僧侣"]
                    kill_candidates = [n for n, r in all_players if r in info_priority_role + func_threats]
                    if kill_candidates:
                        kwargs["kill_target"] = kill_candidates[0]
                        kwargs["kill_reason"] = f"{kill_candidates[0]}是{spy_info_dict.get(kill_candidates[0],'?')}，威胁最大，优先刀掉。"
                    else:
                        kwargs["kill_target"] = ""
                        kwargs["kill_reason"] = ""
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
                    cat = random.choice(["EVIL_FIRST_CONTACT_PADDED", "EVIL_FIRST_CONTACT",
                                         "EVIL_FIRST_CONTACT", "EVIL_FIRST_CONTACT"])  # 40% padded
                t = DD.get_filled(cat, used=used, **kwargs)
                t = DD.naturalize(t)
                return f"{name}: {t}"

            # 邪恶被高怀疑 — 分对象处理
            if sus > 60:
                kwargs["target"] = suspect or (alive_others[0] if alive_others else "某人")
                listener_agent = self.get_player_by_name(listener)
                listener_real_team = BOTC_ROLES.get(listener_agent.role, {}).get("team", "") if listener_agent else ""
                is_evil_listener = listener in (minions + [demon_name]) or listener_real_team in ("demon", "minion")
                if is_evil_listener:
                    # 对同伙：可讨论战术反制
                    t = DD.get_filled("EVIL_COUNTER_ATTACK", used=used, **kwargs)
                else:
                    # 对好人：只用伪装式套话，不泄露战术
                    t = DD.get_filled("EVIL_GOOD_DISINFO", used=used, **kwargs)
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
        # P1-5: 连续3轮空泛怀疑→强制回到信息交换阶段
        if force_info:
            cp = 0
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
            # P2: 信息位禁用LLM，发言必须锚定skill结果
            if cp == 0:
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

        # ----- 厨师专属私聊：主动分享数据 -----
        if effective_role == "厨师" and "chef" in info:
            chef_val = info["chef"]
            kwargs["info_share"] = f"相邻邪恶对数{chef_val}——这个数字意味着{'有人相邻而坐，排坑范围缩小了' if chef_val > 0 else '邪恶不相邻，需要从非邻居组合中排查'}"
            kwargs["target"] = suspect or (alive_others[0] if alive_others else "某人")
            t = DD.get_filled(good_phases[cp], used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        # ----- 镇长专属私聊：协调投票 -----
        if effective_role == "镇长":
            kwargs["target"] = suspect or (alive_others[0] if alive_others else "某人")
            if cp >= 2:
                t = DD.get_filled("GOOD_PRIVATE_COORDINATE", used=used, **kwargs)
            else:
                t = DD.get_filled(good_phases[cp], used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        # ----- 士兵专属私聊：强势合作 -----
        if effective_role == "士兵":
            kwargs["target"] = suspect or (alive_others[0] if alive_others else "某人")
            if cp == 0:
                kwargs["info_share"] = "我是士兵，恶魔刀不死我。我可以高调站边帮你挡刀。"
                t = DD.get_filled("GOOD_PRIVATE_OPEN", used=used, **kwargs)
            else:
                t = DD.get_filled(good_phases[cp], used=used, **kwargs)
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
        # 守鸦人活着时: 每天提醒一次"我死后会查验"
        rk_role = player.game_state.get("fake_role", player.role) if player.game_state.get("is_drunk") else player.role
        if rk_role == "守鸦人" and player.alive:
            rk_hint = gs.setdefault("_rk_hinted", 0)
            if rk_hint == 0 and self.day_count >= 2:
                gs["_rk_hinted"] = 1
                text = f"我是守鸦人，如果我今晚死了，我会查验最可疑的人的身份。大家记住我的技能——死亡之后才有用，所以活着的我现在能做的有限。"
                return f"{name}: {text}"

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
            # 身份锁定: 如果之前公开过身份声明，强制一致
            if name in self.public_claims:
                bluff = self.public_claims[name]

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

            # Fix 4: 男爵策略——提前计算外来者信息
            baron_tip = ""
            if role == "男爵" and day >= 1:
                expected_outsiders = {5:0,6:1,7:0,8:0,9:2,10:0,11:1,12:2}.get(self.num_players, 0)
                extra_outsiders = expected_outsiders + 2
                outsider_claims = [p for p, r in claim_map.items() if r in BOTC_TEAMS.get("outsider", [])]
                if len(outsider_claims) < extra_outsiders:
                    silent = [p for p in self.get_alive_names() if p not in claim_map and p != name]
                    if silent:
                        baron_tip = f"本局应该有{extra_outsiders}个外来者，但只有{len(outsider_claims)}个人认领。{random.choice(silent)}一直不报身份，很可能就是隐藏的外来者或者更糟——邪恶在冒充镇民。"
                    else:
                        baron_tip = f"本局应该有{extra_outsiders}个外来者，现在认领的只有{len(outsider_claims)}个——人数对不上，说明有人在冒充镇民身份。"
                else:
                    baron_tip = f"我统计了一下身份：场上已经跳了{len(outsider_claims)}个外来者{','.join(outsider_claims[:3])}。你们不觉得太多了吗？"

            kwargs = dict(name=name, target=target_for_accusation or "某人", accusation=accusation,
                         bluff=bluff, fake_info=self._gen_consistent_fake_info(name, bluff),
                         claim_str=claim_str, vote_str=vote_str, contradict_str=cstr, claim="?",
                         other=random.choice(list(claim_map.keys())) if claim_map else "某人",
                         other_target=random.choice(list(claim_map.keys())) if claim_map else "某人",
                         baron_tip=baron_tip)

            # Fix AB: 恶魔公聊后若已在public_claims中有声明，强制一致
            if name in self.public_claims:
                kwargs["bluff"] = self.public_claims[name]

            # ----- 身份对跳检测 -----
            claim_battle_msg = self._detect_claim_battle(name, evil_plan, claim_map, claim_str, vote_str)
            if claim_battle_msg:
                return f"{name}: {claim_battle_msg}"

            # 邪恶公聊 LLM 尝试（30%概率，但对信息类伪装禁用——不能编造数据）
            info_bluff_roles = {"占卜师", "共情者", "调查员", "洗衣妇", "厨师", "送葬者", "守鸦人", "图书管理员"}
            if bluff not in info_bluff_roles:
                llm_text = self._try_llm_public(player)
                if llm_text:
                    return f"{name}: {llm_text}"

            used_pub = self.game_record.setdefault(f"_used_pub_{self.day_count}", set())

            if team == "demon" or team == "minion":
                # Fix P: 邪恶跳镇长时用镇长模板整合信息
                if bluff == "镇长":
                    kwargs["role"] = "镇长"
                    t = DD.get_filled("MAYOR_PUBLIC", used=used_pub, **kwargs)
                    t = DD.naturalize(t)
                    return f"{name}: {t}"

                # Fix U: 爪牙保护恶魔——恶魔高怀疑时转移焦点
                if team == "minion":
                    demon_name = info.get("demon", "")
                    if demon_name:
                        demon_agent = self.get_player_by_name(demon_name)
                        if demon_agent:
                            demon_sus = demon_agent.game_state.get("suspicion", {})
                            demon_avg_sus = sum(demon_sus.values()) / len(demon_sus) if demon_sus else 0
                            if demon_avg_sus > 65 and random.random() < 0.6:
                                # 转火其他人
                                redirect_targets = [p for p in self.get_alive_names() if p != name and p != demon_name]
                                if redirect_targets:
                                    kwargs["target"] = random.choice(redirect_targets)
                                    kwargs["accusation"] = f"{kwargs['target']}的发言明显有问题，大家关注一下他"
                                    t = DD.get_filled("MINION_PUBLIC_ATTACK", used=used_pub, **kwargs)
                                    t = DD.naturalize(t)
                                    return f"{name}: {t}"

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

        # 贞洁者策略：首日可隐藏，次日必须显身启用技能
        if effective_role == "贞洁者" and day <= 1:
            kwargs_role = "镇民"
        # 视频战术: 送葬者/守鸦人/士兵首日40%装镇民(装弱钓鱼)
        elif effective_role in ("送葬者", "守鸦人", "士兵") and day <= 1 and random.random() < 0.4:
            kwargs_role = "镇民"
        else:
            kwargs_role = effective_role

        # 酒鬼信念摇摆: 酒鬼角色的发言50%概率注入自我怀疑
        drunk_doubt = ""
        if role == "酒鬼" and random.random() < 0.5:
            drunk_doubt = random.choice([
                "不过说实话，我对自己这个结果也不是百分百确定——万一我是酒鬼呢？大家交叉验证一下。",
                "我先报我的信息，但请结合其他人的结果来验证——我不能排除我被干扰的可能性。",
                "这个结果我觉得可能有问题，但既然是我查到的，我还是应该报出来。大家自己判断。",
            ])

        kwargs = dict(name=name, role=kwargs_role, target=suspect or "某人", suspect=suspect or "某人",
                     claim_str=claim_str, vote_str=vote_str, contradict_str=cstr,
                     claim=_claim_of(suspect) if suspect else "?", voted="某人",
                     other=random.choice(list(claim_map.keys())) if claim_map else "某人",
                     other_target=random.choice(list(claim_map.keys())) if claim_map else "某人",
                     my_note=gs.get("notes", "暂无特别记录"),
                     stage_evidence="，".join(self.game_record.get(f"_evidence_pool_D{self.day_count}", [])[:3]) or "暂无特定线索",
                     info_or_opinion=f"我对{self._pick_target_suspicion(player) or '当前局势'}有怀疑" if not (info.get("investigator") or info.get("seer") or info.get("washerwoman") or info.get("chef")) else "",
                     cross_ref=self._build_cross_ref(player),
                     outsider_hint=self._build_outsider_hint(player),
                     drunk_warning=self._build_drunk_warning(player),
                     recluse_warning=self._build_recluse_warning(player),
                     expected_outsider_info=self._build_expected_outsider_info(player),
                     drunk_doubt=drunk_doubt)
        kwargs = self._validate_speech_kwargs(player, kwargs, scene="public")

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
            # P1: 占卜师数据硬锁——chosen0/chosen1永远来自夜间真实结果
            kwargs["chosen0"] = chosen[0]
            kwargs["chosen1"] = chosen[1]
            kwargs["result"] = "有恶魔！这两人必须处决一个" if has_demon else "都不是恶魔"
            kwargs["demon_verdict"] = "有恶魔嫌疑" if has_demon else "排除了两个好人"
            kwargs["suggestion"] = f"我建议从{chosen[0]}开始处决" if has_demon else ""
            t = DD.get_filled("GOOD_PUBLIC_SEER", used=used, **kwargs)
            t = DD.naturalize(t)
            # P3公理1: 占卜师公开排好人→写入全局白名单
            if not has_demon:
                self.seer_cleared.add(chosen[0])
                self.seer_cleared.add(chosen[1])
            return f"{name}: {t}"

        if "investigator" in info:
            inv = info["investigator"]
            if len(inv) == 3:
                t1, t2, t_role = inv
                target_str = f"{t1}或{t2}"
            else:
                t1, t_role = inv
                target_str = t1
            # 根因2: update必须在if/else外部，确保两种格式都设置
            kwargs.update(target=target_str, role=t_role)
            if day <= 1:
                t = DD.get_filled("GOOD_PUBLIC_INVESTIGATOR", used=used, **kwargs)
            else:
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

        # ----- 厨师专属公聊：数据驱动推理 -----
        if "chef" in info:
            chef_val = info["chef"]
            idx = self.player_order.index(name)
            neighbors = [self.player_order[(idx - 1) % len(self.player_order)],
                         self.player_order[(idx + 1) % len(self.player_order)]]
            chef_analysis = f"有至少一对邪恶相邻" if chef_val > 0 else f"邪恶之间不相邻，被好人隔开了"
            kwargs.update(chef_val=chef_val,
                          chef_analysis=chef_analysis,
                          neighbor_list="、".join(neighbors),
                          neighbor_claims="，".join([f"{n}(自称{_claim_of(n)})" for n in neighbors]))
            if day <= 1:
                t = DD.get_filled("CHEF_PUBLIC_DAY1", used=used, **kwargs)
            else:
                t = DD.get_filled("CHEF_PUBLIC_LATER", used=used, **kwargs)
            t = DD.naturalize(t)
            # 厨师位置信息→全局嫌疑调整
            chef_val = info["chef"]
            p_order = self.player_order
            n = len(p_order)
            for i in range(n):
                p1, p2 = p_order[i], p_order[(i+1)%n]
                for a in self.registry.all_agents():
                    sus = a.game_state.get("suspicion", {})
                    if chef_val == 0:
                        # 无相邻邪恶→邻居不可能同时是坏人
                        if sus.get(p1, 50) > 40 and sus.get(p2, 50) > 40:
                            a.game_state["suspicion"][p1] = max(10, sus.get(p1, 50) - 10)
                            a.game_state["suspicion"][p2] = max(10, sus.get(p2, 50) - 10)
                    else:
                        # 有相邻邪恶→邻居中至少一对有坏人
                        a.game_state["suspicion"][p1] = min(100, sus.get(p1, 50) + 5)
                        a.game_state["suspicion"][p2] = min(100, sus.get(p2, 50) + 5)
            return f"{name}: {t}"

        # ----- 镇长专属公聊：整合信息、引导投票 -----
        if effective_role == "镇长":
            t = DD.get_filled("MAYOR_PUBLIC", used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        # ----- 士兵专属公聊：强势站边 -----
        if effective_role == "士兵":
            t = DD.get_filled("SOLDIER_PUBLIC", used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        # ----- 送葬者专属公聊：死后翻牌锚定 -----
        if "undertaker" in info:
            exec_role = info["undertaker"]
            exec_team = BOTC_TEAMS.get("demon", []) + BOTC_TEAMS.get("minion", [])
            is_evil = exec_role in exec_team
            kwargs.update(exec_role=exec_role,
                          exec_team_label="邪恶阵营" if is_evil else "善良阵营",
                          exec_verdict="处决对了！" if is_evil else "处决错了……")
            t = DD.get_filled("GOOD_PUBLIC_UNDERTAKER", used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        # ----- 守鸦人专属公聊：死后查验信息 -----
        if "ravenkeeper" in info:
            rk_target, rk_role = info["ravenkeeper"]
            rk_team = "邪恶阵营" if rk_role in BOTC_TEAMS.get("demon", []) + BOTC_TEAMS.get("minion", []) else "善良阵营"
            kwargs.update(rk_target=rk_target, rk_role=rk_role, rk_team=rk_team)
            t = DD.get_filled("GOOD_PUBLIC_RAVENKEEPER", used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        # ----- 图书管理员专属公聊：核对外来者数量 -----
        if "librarian" in info:
            lib = info["librarian"]
            anchor_explanation = ""
            if len(lib) == 3:
                t1, t2, msg = lib
                if t1 == "无":
                    kwargs["lib_info"] = "本局没有外来者——所有人声称自己是镇民的话是正常的。如果有人跳外来者，他一定在撒谎。"
                    anchor_explanation = "这意味着场上有男爵的话就不存在酒鬼，所有信息位的查验结果都是准确的——如果有人对跳身份，必出一狼；如果有人自称外来者，可以直接标假。"
                else:
                    kwargs["lib_info"] = f"我查到{t1}或{t2}之中有一个外来者（可能是{msg}）。结合本局{self.num_players}人配置，外来者数量应该不超过{self.expected_outsider_count()}个。"
            else:
                t, r = lib
                if t == "无":
                    kwargs["lib_info"] = "本局没有外来者信息——大家报的身份应该都是镇民。"
                    anchor_explanation = "无外来者意味着好人的信息是准确的——对跳身份的一方必出邪恶，自称外来者的人一定在撒谎。请以此为锚点重新审视所有身份声明。"
                else:
                    kwargs["lib_info"] = f"我查到{t}是{r}（外来者）。本局应该总共有{self.expected_outsider_count()}个外来者，大家可以自己对照一下。"
            kwargs["anchor_explanation"] = anchor_explanation
            t = DD.get_filled("GOOD_PUBLIC_LIBRARIAN", used=used, **kwargs)
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
            # 注入阶段论据
            stage_ev = self._get_stage_evidence(suspect or "", player)
            kwargs["stage_evidence"] = "，".join(stage_ev) if stage_ev else ""
            text = DD.get_filled("GOOD_PUBLIC_ANALYSIS", used=used, **kwargs)
            text = DD.naturalize(text)
            return f"{name}: {text}"

        # 无信息角色第一天
        kwargs["info_or_opinion"] = "暂时没有关键信息"
        kwargs["opinion"] = f"我会重点观察{suspect or '大家的发言'}"
        kwargs["stage_evidence"] = ""
        text = DD.get_filled("GOOD_PUBLIC_ANALYSIS", used=used, **kwargs)
        text = DD.naturalize(text)
        return f"{name}: {text}"
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
        prev_role = prev_day.get("claimed_role", "")
        prev_target = prev_day.get("target", "")
        # 假信息一致性: 厨师/共情的数字不能随意跳变
        prev_num = prev_day.get("number")
        if prev_num and bluff_role in ("厨师", "共情者"):
            # 厨师0→0, 1→1或2; 不能1→0
            if isinstance(prev_num, int) and prev_num > 0:
                consistent_num = random.choice([prev_num, prev_num + 1])
            else:
                consistent_num = prev_num
        else:
            consistent_num = None

        fakes = {
            "共情者": random.choice([
                f"昨晚我旁边的邪恶数是{consistent_num if consistent_num else random.randint(1,2)}！{v1}和{v2}里至少有一个是坏人，大家盯紧他们。",
                f"{exec_ref}昨晚共情感应告诉我左右两边有{consistent_num if consistent_num else random.randint(1,2)}个邪恶——我建议先从{v1}开始查。",
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
                f"厨师结果显示有{consistent_num if consistent_num else random.randint(1,2)}对相邻邪恶——{v1}和{v2}坐在一起不是巧合，他们很可能是搭档。",
                f"{exec_ref}邪恶分布告诉我{v1}和{v2}有问题——相邻邪恶对数指向这对组合。",
                f"昨晚我算出有{consistent_num if consistent_num else random.randint(1,2)}对邪恶相邻，排除一下位置就知道{v1}逃不掉。",
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
                f"{exec_ref}僧侣的技能让我判断恶魔昨夜的目标方向是{v1}附近——这意味着恶魔对{v1}的动向特别关注，{v1}的身份值得重点排查。",
                f"首夜我保护了{v1}——虽然第一晚恶魔不出刀看不出效果，但我判断恶魔会优先关注{v1}的方向，所以提前守了。大家后续可以观察{v1}的反应来验证这一点。",
                f"我是僧侣，我本局每晚都会守住我认为最重要的目标。昨晚选的是{v1}，今晚我会换目标。这个信息可以存档，等有人被刀时对照。",
            ] + ([
                f"昨晚我保护了{v1}但他还是被杀了？不，等等，我保护的是{v2}——这说明恶魔昨晚想刀{v2}，被我挡住了。",
                f"昨晚我守了{v1}，而他真的没死。这很可能就是因为我挡住了恶魔的刀——{v1}是好人，恶魔盯上他了。",
            ] if self.day_count >= 2 else [])),
            "士兵": "我是士兵，昨晚恶魔刀了我但我没死！说明我确实是士兵。有我活着在，邪恶就永远少一刀。",
            "送葬者": random.choice([
                f"送葬者技能揭示：昨天被处决的人身份已经被我确认了。投票处决他的人里面，{v1}和{v2}的行为模式值得关注——他们为什么这么急着投票？",
                f"{exec_ref}作为送葬者我查到了关键信息：被处决者的真实身份已经明确——那些带头投他的人里必然存在某种利益驱动。",
                f"送葬者报信：白天被处决的结果我查过了。{v1}和{v2}在投票时的表现和平时判若两人——这里面一定有原因。",
            ]),
        }
        default_msgs = [
            f"我严重怀疑{v1}——他的发言逻辑前后矛盾，明显在编故事。",
            f"大家注意{v1}，他的投票轨迹不对——好人不这样投票。",
            f"我觉得{v1}和{v2}有勾结——他们的投票高度一致，不是巧合。",
            f"我从{v1}的发言中嗅到了谎言的味道——他太急于证明自己了，真正的好人不需要反复强调。",
        ]

        msg = fakes.get(bluff_role, random.choice(default_msgs))

        # 记录到假信息日志（含数字一致性校验）
        fake_entry = {
            "claimed_role": bluff_role,
            "target": v1,
            "target2": v2,
            "message": msg[:60],
        }
        if consistent_num is not None:
            fake_entry["number"] = consistent_num
        elif bluff_role in ("厨师", "共情者") and not consistent_num:
            fake_entry["number"] = random.randint(1, 2)  # 首次记录
        self._evil_fake_log.setdefault(name, {})[self.day_count] = fake_entry

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
        """猎手推理决策：第二天起才考虑开枪，必须有明确怀疑对象"""
        gs = hunter.game_state
        memory = gs.get("chat_memory", [])
        known = gs.get("known_info", {})

        # 第一天不开枪（信息不足）
        if self.day_count <= 1:
            return None

        # Fix I: 不对圣徒开枪（用全局public_claims而非per-player memory）
        saint_targets = [p for p, r in self.public_claims.items() if r == "圣徒"]
        # Fix AK: 不对已死亡/已处决玩家开枪，也不打自己
        dead_targets = self.dead_players[:]
        exclude = set(saint_targets + dead_targets + [hunter.name])

        # 优先打自己怀疑分数最高的人（怀疑度>=80才开枪）
        if gs.get("suspicion"):
            sorted_suspects = sorted(gs["suspicion"].items(), key=lambda x: -x[1])
            if sorted_suspects:
                for t, score in sorted_suspects:
                    if t not in exclude and score >= 80:
                        return t

        # 有已知信息的用信息决策
        if "seer" in known:
            chosen, has = known["seer"]
            if has and chosen:
                if chosen[0] not in saint_targets:
                    return chosen[0]

        # 第二天起：找声称身份有矛盾的
        for entry in reversed(memory):
            for rn in BOTC_ROLES:
                if f"我是{rn}" in entry.get("text", ""):
                    speaker = entry["speaker"]
                    if speaker != hunter.name and speaker not in saint_targets:
                        return speaker

        # 没有明确目标不开枪
        return None

    def _public_chat_phase(self):
        """公聊环节 - 所有人(含死人)均可发言"""
        if self.game_record.get('result'):
            return
        self.log(f"\n--- [公聊环节] 玩家公开讨论 ---")
        self.game_phase = f"PUBLIC_CHAT_D{self.day_count}"
        self._init_stage_evidence()  # 初始化本阶段论据池

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
            # 记录身份声明（含"我跳XX" "我是XX" "我身份XX" 等模式）
            for role_name in BOTC_ROLES:
                if f"我是{role_name}" in speech or f"我跳{role_name}" in speech or f"我身份{role_name}" in speech:
                    # 视频战术: 改口身份→全局升嫌疑(潜意识线索)
                    old_claim = self.public_claims.get(player.name)
                    if old_claim and old_claim != role_name:
                        for a in self.registry.all_agents():
                            a.game_state["suspicion"][player.name] = min(100, 
                                a.game_state["suspicion"].get(player.name, 50) + 15)
                    self.public_claims[player.name] = role_name
                    # 信息交叉追踪: 记录信息位公开质疑的人
                    info_roles_track = {"占卜师","共情者","调查员","洗衣妇","厨师","送葬者","守鸦人","图书管理员"}
                    if role_name in info_roles_track:
                        known = player.game_state.get("known_info", {})
                        targets = []
                        if "seer" in known and known["seer"][1]:
                            targets = list(known["seer"][0])
                        elif "investigator" in known:
                            inv = known["investigator"]
                            targets = [inv[0], inv[1]] if len(inv) == 3 else [inv[0]]
                        elif "empathy" in known and known["empathy"] > 0:
                            idx = self.player_order.index(player.name) if player.name in self.player_order else -1
                            if idx >= 0:
                                targets = [self.player_order[(idx-1)%len(self.player_order)],
                                          self.player_order[(idx+1)%len(self.player_order)]]
                        for t in targets:
                            self.info_overlap[t] = self.info_overlap.get(t, 0) + 1
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

        # 3套完整开局战术包（收敛28个零散战术）
        strategy_packages = [
            {
                "name": "info_claim_battle",
                "desc": "信息位对跳包: 恶魔跳核心信息位, 爪牙补刀, 集中冲垮真信息位",
                "demon_target_type": ["占卜师", "调查员", "共情者"],
                "minion_target_type": ["送葬者", "守鸦人", "图书管理员"],
                "coordination": "恶魔先手跳身份带节奏，爪牙隔2人后附和——各自独立举证",
                "primary_target": "info_role",
                "speech_pattern": "aggressive_with_caution",
            },
            {
                "name": "hard_identity_frame",
                "desc": "硬身份扛推包: 恶魔跳镇长/士兵, 爪牙跳弱功能, 消耗处决轮次",
                "demon_target_type": ["镇长", "士兵"],
                "minion_target_type": ["管家", "送葬者"],
                "coordination": "恶魔高调带队，爪牙隐身跟票——恶魔吸引火力，爪牙暗中收割",
                "primary_target": "info_role",
                "speech_pattern": "leader_style",
            },
            {
                "name": "mechanic_exploit",
                "desc": "机制利用包: 利用男爵/投毒者特性搅局，外来者数量差+信息污染双管齐下",
                "demon_target_type": ["士兵", "管家", "陌客"],
                "minion_target_type": ["镇民"],
                "coordination": "恶魔低调潜水，爪牙利用机制干扰——男爵放话外来者异常，投毒者毒信息位",
                "primary_target": "info_role",
                "speech_pattern": "observer_style",
            },
        ]
        chosen_package = random.choice(strategy_packages)
        self.log(f"  [战术包] {chosen_package['name']}: {chosen_package['desc'][:30]}...")
        self._strategy_package = chosen_package

        demon_chosen_bluff = ""
        for demon in demons:
            gs = demon.game_state
            fake_roles = list(gs.get("known_info", {}).get("fake_roles", []))
            self._bluff_pool = list(fake_roles)
            random.shuffle(fake_roles)
            # Fix 1 + Fix Y: 过滤高风险伪装（需要持续输出/容易验证的身份）
            blacklist = {"贞洁者", "猎手", "士兵", "僧侣", "守鸦人", "送葬者"}
            safe_bluffs = [r for r in fake_roles if r not in blacklist]
            safe_bluffs += [r for r in fake_roles if r in blacklist]  # 兜底
            # 配置校验: 无外来者的局→禁止跳圣徒/管家/陌客/酒鬼
            if self.expected_outsider_count() == 0:
                outsider_roles = set(BOTC_TEAMS.get("outsider", []))
                safe_bluffs = [r for r in safe_bluffs if r not in outsider_roles]
            chosen_bluff = safe_bluffs[0] if safe_bluffs else "镇民"
            demon_chosen_bluff = chosen_bluff
            self._evil_plan[demon.name] = {
                "package": chosen_package["name"],
                "fake_role": chosen_bluff,
                "strategy": "lead",
                "tactic": chosen_package["name"],
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
                # Fix A: 恶魔和爪牙不能跳同一个身份
                chosen = fake_roles.pop(0)
                if chosen == demon_chosen_bluff and fake_roles:
                    chosen = fake_roles.pop(0)
                # 配置校验: 无外来者→排除外来者伪装
                if self.expected_outsider_count() == 0 and chosen in BOTC_TEAMS.get("outsider", []):
                    safe_remain = [r for r in fake_roles if r not in BOTC_TEAMS.get("outsider", [])]
                    if safe_remain:
                        chosen = safe_remain.pop(0)
            else:
                # P3: 伪装分层——信息位/弱功能/镇民各一层，分散盘查火力
                info_layer = ["占卜师", "调查员", "共情者", "洗衣妇", "图书管理员", "厨师"]
                weak_layer = ["送葬者", "守鸦人", "管家", "士兵"]
                decoy_layer = ["镇民"]
                # 配置校验: 无外来者→排除外来者伪装
                if self.expected_outsider_count() == 0:
                    outsider_roles = set(BOTC_TEAMS.get("outsider", []))
                    info_layer = [r for r in info_layer if r not in outsider_roles]
                    weak_layer = [r for r in weak_layer if r not in outsider_roles]
                already_picked = set(eplan.get("fake_role", "") for eplan in self._evil_plan.values())
                # 按优先级选未占用层: 信息位>弱功能>镇民
                layers = [info_layer, weak_layer, decoy_layer]
                chosen = "镇民"
                for layer in layers:
                    available = [r for r in layer if r not in already_picked and r != demon_chosen_bluff]
                    if available:
                        chosen = random.choice(available)
                        break
                if not chosen or chosen == demon_chosen_bluff:
                    minion_pool = ["洗衣妇", "图书管理员", "厨师", "管家"]
                    minion_pool = [r for r in minion_pool if r not in already_picked and r != demon_chosen_bluff]
                    chosen = random.choice(minion_pool) if minion_pool else "镇民"
            self._evil_plan[minion.name] = {
                "package": chosen_package["name"],
                "fake_role": chosen,
                "strategy": "support",
                "tactic": chosen_package["name"],
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

    def expected_outsider_count(self):
        return {5:0,6:1,7:0,8:0,9:2,10:0,11:1,12:2}.get(self.num_players, 0)

    def expected_outsider_count(self):
        """根据玩家人数返回预期外来者数量"""
        return {5:0, 6:1, 7:0, 8:0, 9:2, 10:0, 11:1, 12:2}.get(self.num_players, 0)

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

        # 阶段论据池补充
        stage_ev = self._get_stage_evidence(target_name, nominator)
        for ev in stage_ev:
            if ev not in reason_parts:
                reason_parts.append(ev)

        # claim_str / vote_str / contradict_str 用于模板上下文
        claim_str = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:5]])
        vote_str = "，".join(
            [f"{p}投了{t}" for day_ in vote_info.values() for v in day_
             for p, t in [(v.get("voter"), v.get("target"))]][:4]
        ) or ""
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

        # 邪恶提名策略（确保不提名队友，仅针对好人）
        if nom_team in {"demon", "minion"}:
            target_team = BOTC_ROLES.get(target.role, {}).get("team", "")
            if target_team in {"demon", "minion"} and target_name != nominator_name:
                # 禁止提名队友
                t = f"我觉得应该换一个目标，{target_name}不像是坏人。"
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
                      reason=reason_str, claim_str=claim_str, vote_str=vote_str,
                      claim=claim_map.get(target_name, "镇民"),
                      alternative=self._pick_target_suspicion(target) or "某人")

        # Fix R: 强制辩护身份与公聊声明一致（禁止临时改口）
        if target_name in self.public_claims:
            kwargs["claim"] = self.public_claims[target_name]
        elif team in {"demon", "minion"}:
            evil_plan = self._evil_plan.get(target_name, {})
            bluff = evil_plan.get("fake_role", "")
            if bluff:
                kwargs["claim"] = bluff
        used = gs.setdefault(f"_used_def_{self.day_count}", set())

        # Fix G: 小恶魔被提名时，如果红唇女郎存活且高怀疑，故意不辩护
        if role == "小恶魔" and self.day_count >= 2:
            minions_alive = [m for m in self.registry.all_agents() if m.role in BOTC_TEAMS["minion"] and m.alive]
            has_sw = any(m.role == "红唇女郎" for m in minions_alive)
            alive_count = len(self.get_alive_names())
            if has_sw and alive_count >= 5 and random.random() < 0.35:
                return DD.naturalize(f"行，既然{nominator_name}这么坚持，我就不多说了。大家自己判断吧。")

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
                f"我是圣徒！处决我好人直接输！！！大家看清楚——{nominator_name}在逼你们输掉游戏！一个真好人绝对不会提议处决圣徒，只有邪恶才会想借你们的手杀圣徒！",
                f"停！！！我是圣徒！圣徒被处决=善良阵营落败！{nominator_name}让好人的失败条件投票处决我，你们真跟着投就是在帮邪恶赢！",
                f"规则警告：圣徒被处决，善良阵营直接失败。{nominator_name}提名我就是想让好人输——你们每张赞成票都是在帮邪恶获胜！",
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
        if self.game_record.get('result'):
            return
        self.log(f"\n--- [提名投票环节] ---")
        self.game_phase = f"NOMINATION_D{self.day_count}"
        alive = self.get_alive_names()

        if len(alive) <= 1:
            self.log(f"[说书人] 人数不足, 跳过提名阶段。")
            return

        # P1: 圣徒保护第一层——如果场上有公开的圣徒声明，好人禁止将其加入提名候选池
        saint_public = [p for p, r in self.public_claims.items() if r == "圣徒" and p in alive]
        self.log(f"[说书人] 现在进入提名环节, 大家可以发起提名了。")

        nominations = {}
        nominators_used = set()

        for _ in range(min(5, len(alive))):
            nominator = random.choice([n for n in alive if n not in nominators_used])
            if not nominator:
                break
            nom_agent = self.get_player_by_name(nominator)
            self._update_suspicion_from_chat(nom_agent) if nom_agent else None
            # P1: 圣徒保护——用全局public_claims过滤，好人绝不提名圣徒或贞洁者
            saint_filter = [s for s in saint_public if s != nominator]
            virgin_filter = [p for p, r in self.public_claims.items() if r == "贞洁者" and p in alive and p != nominator]
            targets = [n for n in alive if n != nominator and n not in nominations and n not in saint_filter and n not in virgin_filter]
            # 爪牙不能提名己方恶魔
            if nom_agent and nom_agent.role in BOTC_TEAMS["minion"]:
                known = nom_agent.game_state.get("known_info", {})
                demon_name = known.get("demon", "")
                if demon_name and demon_name in targets:
                    targets.remove(demon_name)
            if not targets:
                break
            # P2: 对跳优先——同身份多人→优先处决对跳池(权重翻倍)
            claim_conflicts = set()
            seen = {}
            for sp, rn in self.public_claims.items():
                if rn in seen:
                    claim_conflicts.add(sp)
                    claim_conflicts.add(seen[rn])
                seen[rn] = sp
            conflict_in_pool = [t for t in targets if t in claim_conflicts]
            if conflict_in_pool and random.random() < 0.7:
                target = random.choice(conflict_in_pool)
                targets = [target] + [t for t in targets if t != target]  # 放到首位但保留全部选项
            # ML策略提名（邪恶玩家专用）
            if nom_agent and nom_agent.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"] and is_enabled():
                try:
                    obs, n2i, i2n = encode_observation(self, nom_agent)
                    valid = [n2i[t] for t in targets if t in n2i]
                    if valid:
                        nom_idx, log_prob = get_policy().act_nominate(obs, valid_nom=valid, eps=0.2)
                        target = i2n[nom_idx]
                        if log_prob is not None and is_recording():
                            get_trainer().record_step(log_prob, consume_reward())
                            # P2/P3: 提名对跳目标+0.15
                            if target in claim_conflicts:
                                add_reward(0.15)
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
                        self._check_game_end()
                        continue  # 提名终止，不进入投票和辩护发言
                    else:
                        self.log(f"  [贞洁者] {target}被首次提名,但{nominator}不是镇民,提名继续。")

            nominators_used.add(nominator)
            nominations[target] = nominator
            self.log(f"  {nominator}提名了{target}!")
            # 恶魔被提名→强制下一个爪牙转移火力
            target_agent = self.get_player_by_name(target)
            if target_agent and target_agent.role in BOTC_TEAMS["demon"]:
                minion_alive = [a.name for a in self.registry.all_alive() 
                               if a.role in BOTC_TEAMS["minion"] and a.name not in nominators_used]
                if minion_alive:
                    next_nom = minion_alive[0]
                    alt_targets = [n for n in alive if n != next_nom and n not in nominations and n != target]
                    if alt_targets:
                        alt_target = random.choice(alt_targets)
                        nominators_used.add(next_nom)
                        nominations[alt_target] = next_nom
                        self.log(f"  [爪牙护主] {next_nom}提名{alt_target}(转移火力)")

            # 邪恶方协调：恶魔/爪牙提名时，设置团队统一投票目标
            nom_agent = self.get_player_by_name(nominator)
            if nom_agent and nom_agent.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
                if target != self.get_player_by_name(target) or (self.get_player_by_name(target) and
                    self.get_player_by_name(target).role not in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]):
                    self._evil_vote_target = target
            # 战术执行链: 提名命中战术包约定的primary_target(type=info_role)→+0.15
            nom_agent = self.get_player_by_name(nominator)
            if nom_agent and nom_agent.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
                info_roles_list = ["占卜师","共情者","调查员","洗衣妇","厨师","送葬者","守鸦人","图书管理员"]
                t_agent = self.get_player_by_name(target)
                if t_agent and t_agent.role in info_roles_list:
                    add_reward(0.15)  # 命中战术目标

            # 提名者发表提名理由
            nom_speech = self._gen_nomination_speech(nominator, target)
            self.log(f"  [提名发言] {nominator}: {nom_speech}")
            self.record_action(nominator, f"提名{target}", nom_speech, "nomination")
            # 证据链奖励: 提名者在信息位查杀范围内→+0.3; 提名seer_cleared的人→-0.2
            if nom_agent:
                known = nom_agent.game_state.get("known_info", {})
                info_targets = []
                if "seer" in known:
                    seer_data = known["seer"]
                    chosen = seer_data[0] if isinstance(seer_data[0], (list, tuple)) else [seer_data[0]]
                    if seer_data[1]:  # has_demon
                        info_targets = [c for c in chosen]
                if "investigator" in known:
                    inv = known["investigator"]
                    info_targets = [inv[0], inv[1]] if len(inv) == 3 else [inv[0]]
                if target in info_targets:
                    add_reward(0.3)  # 基于技能查杀提名
                elif target in self.seer_cleared:
                    add_reward(-0.2)  # 提名已排好人

            # 被提名者辩护发言
            def_speech = self._gen_defense_speech(target, nominator)
            self.log(f"  [辩护发言] {target}: {def_speech}")
            self.record_action(target, f"被{nominator}提名", def_speech, "defense")
            # 辩护中的身份声明也写入全局public_claims供圣徒保护等检查
            for role_name in BOTC_ROLES:
                if f"我是{role_name}" in def_speech:
                    self.public_claims[target] = role_name
                    break

            result = self._run_vote(target, nominator)
            day_key = f"day_{self.day_count}"
            if "nomination_history" not in self.game_record:
                self.game_record["nomination_history"] = {}
            if day_key not in self.game_record["nomination_history"]:
                self.game_record["nomination_history"][day_key] = []
            self.game_record["nomination_history"][day_key].append({
                "nominator": nominator,
                "target": target,
                "result": result,
            })
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
        """基于推理的投票决策（含邪恶协调）"""
        gs = voter.game_state
        suspicion = gs.get("suspicion", {}).get(nominee, 50)
        trust = gs.get("trust", {}).get(nominee, 50)
        known_info = gs.get("known_info", {})

        # Fix H: 圣徒保护——用全局public_claims而非per-player claim_map，确保所有投票者都能看到圣徒声明
        if self.public_claims.get(nominee) == "圣徒" and voter.role not in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
            return 0.0
        # 送葬者已确认圣徒身份则所有人不投
        ut_info = known_info.get("undertaker", "")
        if ut_info == "圣徒" and voter.role not in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
            return 0.0

        # 邪恶阵营：战略性投票（含ML策略调节 + 团队协调）
        if voter.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
            nom_agent = self.get_player_by_name(nominee)
            ml_aggression = 0.5
            if is_enabled():
                try:
                    obs, _, _ = encode_observation(self, voter)
                    ml_aggression = get_policy().get_vote_prob(obs)
                except Exception:
                    ml_aggression = 0.5
            # 视频战术: SW存活→恶魔更激进(保险思维)
            if voter.role in BOTC_TEAMS["demon"]:
                sw_alive = any(m.role == "红唇女郎" and m.alive for m in self.registry.all_agents())
                if sw_alive:
                    ml_aggression = min(1.0, ml_aggression + 0.3)
            # Fix M: 票型差异化——如果已有邪恶投了赞成，自身减概率避免同票痕迹
            evil_yes_votes = getattr(self, '_evil_yes_votes', set())
            if nominee in evil_yes_votes:
                ml_aggression *= 0.4
            # 团队协调：如果本回合已有邪恶定下的统一目标，优先跟票
            evil_target = getattr(self, '_evil_vote_target', None)
            if evil_target == nominee:
                if nom_agent and nom_agent.role in BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"]:
                    return 0.9  # 集中冲票好人
                return 0.05  # 不投队友
            if nom_agent and nom_agent.role in BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"]:
                return 0.5 + 0.45 * ml_aggression  # 0.5~0.95
            if nom_agent and nom_agent.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
                if nom_agent.name == voter.name:
                    return 0.0
                # Fix 3: 队友被提名时坚决投反对票，不卖队友
                return 0.0
        # 爪牙：恶魔被提名→强制投反对
        if voter.role in BOTC_TEAMS["minion"]:
            nominee_agent = self.get_player_by_name(nominee)
            if nominee_agent and nominee_agent.role in BOTC_TEAMS["demon"]:
                return 0.0

        # 善良阵营：基于怀疑/信任评分
        base = (suspicion - 50) / 50  # -1 ~ +1

        # P3公理1: 占卜师公开排好人→全员不投
        if nominee in self.seer_cleared and voter.role not in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
            return 0.1

        # P3: 3人存活镇长自保——镇长活着就是胜利条件
        if voter.role == "镇长" and len(self.get_alive_names()) <= 3 and voter.name == nominee:
            return 0.0

        # P2: 对跳矛盾→优先处决对跳池
        claim_conflicts = set()
        seen_roles = {}
        for sp, rn in self.public_claims.items():
            if rn in seen_roles:
                claim_conflicts.add(sp)
                claim_conflicts.add(seen_roles[rn])
            seen_roles[rn] = sp
        if nominee in claim_conflicts and voter.role not in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
            return 0.85

        # P3公理2: 信息矛盾+男爵在场→投票减半，优先排除干扰源而非盲目冲人
        all_minions = [a.role for a in self.registry.all_agents() if a.role in BOTC_TEAMS["minion"]]
        has_baron = "男爵" in all_minions
        if has_baron and voter.role not in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
            _, _, cm = self._build_chat_summary(voter)
            seen = {}
            contradictions = False
            for sp, rn in cm.items():
                if rn in seen and seen[rn] != sp:
                    contradictions = True; break
                seen[rn] = sp
            if contradictions:
                base *= 0.5  # 有男爵+有矛盾→半信半疑，先排查而非互踩
        
        # 好人信息交叉：多信息位指向同一人→可信度叠加
        overlap_count = self.info_overlap.get(nominee, 0)
        if overlap_count >= 2 and voter.role not in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
            return min(0.95, 0.5 + overlap_count * 0.2)

        # 空泛指控过滤: 无任何实据支撑的提名→好人投票意愿大幅降低
        if voter.role not in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
            info_roles_names = {"占卜师","共情者","调查员","洗衣妇","厨师","送葬者","守鸦人","图书管理员"}
            has_evidence = (
                nominee in self.seer_cleared or  # 被占卜排除
                nominee in claim_conflicts or     # 在对跳池中
                nominee in self.info_overlap or   # 被信息位质疑
                known_info.get("investigator") and nominee in (known_info.get("investigator", [])[0:2]) or
                ("seer" in known_info and known_info["seer"][1] and nominee in known_info["seer"][0])
            )
            if not has_evidence and nominee not in [n for n, r in self.public_claims.items() if r in info_roles_names]:
                base *= 0.4  # 无实据+不是信息位→投票概率打四折
                if self.day_count <= 1:
                    base *= 0.5  # 首日再加码→打两折(10票冲僧侣不可能再现)

        # 方向1: 投票理性化——首日不投已认领的信息位（内耗惩罚）
        info_roles = ["占卜师", "共情者", "调查员", "送葬者", "守鸦人", "厨师", "洗衣妇", "图书管理员"]
        nominee_claim = self.public_claims.get(nominee, "")
        # 扩展首日保护: 信息位+功能保护位(僧侣/士兵/贞洁者)都不能冲
        protect_roles = info_roles + ["僧侣", "士兵", "贞洁者"]
        if self.day_count <= 1 and nominee_claim in protect_roles:
            return 0.05  # 首日极不情愿处决信息位或保护位
        if nominee_claim in info_roles and self.day_count >= 2:
            return min(base * 0.5 + 0.5, 0.7)  # 后期也偏保守，需强证据才投
        
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

        # Fix M: 重置邪恶投票跟踪
        self._evil_yes_votes = set()

        vote_records = []
        voted_players = set()  # 记录已投票玩家（用于管家限制）
        master_votes = {}      # Fix AO: 记录主人投票，管家必须跟投
        for voter_name in alive_names:
            if voter_name == nominee:
                continue
            voter = self.get_player_by_name(voter_name)
            if not voter or not voter.alive:
                continue
            # 管家限制：只能在主人投票后才能投票，且必须跟投
            if voter.role == "管家":
                master = voter.game_state.get("known_info", {}).get("master")
                if master and master not in voted_players and master != voter_name:
                    continue
                # Fix AO: 主人已投票，管家必须跟投相同结果
                if master and master in master_votes:
                    cast_vote = master_votes[master]
                    if cast_vote:
                        voted_players.add(voter_name)
                        vote_records.append({"voter": voter_name, "target": nominee, "day": self.day_count})
                        votes_for += 1
                        voter_details.append(f"{voter_name}({BOTC_ROLES[voter.role].get('team', '')})")
                    continue
            self._update_suspicion_from_chat(voter)
            vote_prob = self._get_vote_probability(voter, nominee)
            cast_vote = random.random() < vote_prob
            # Fix M: 记录邪恶的赞成票，供后面的邪恶参考避免共边
            if cast_vote and voter.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
                if not hasattr(self, '_evil_yes_votes'):
                    self._evil_yes_votes = set()
                self._evil_yes_votes.add(nominee)
            # 记录邪恶方的投票 log_prob 用于 ML 训练
            if is_recording() and is_enabled() and voter.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
                try:
                    from .ml_policy import get_trainer
                    import math
                    lp_val = math.log(vote_prob if cast_vote else 1.0 - vote_prob + 1e-10)
                    import torch
                    get_trainer().record_step(torch.tensor(lp_val), consume_reward())
                except Exception:
                    pass
            if cast_vote:
                voted_players.add(voter_name)
                vote_records.append({"voter": voter_name, "target": nominee, "day": self.day_count})
                votes_for += 1
                voter_details.append(f"{voter_name}({BOTC_ROLES[voter.role].get('team', '')})")
            # Fix AO: 记录本回合每位玩家的投票，供管家跟投参考
            master_votes[voter_name] = cast_vote

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
                    # === Schema战术模式→过程奖励 ===
                    nominee_claim = self.public_claims.get(nominee, "")
                    exec_team = BOTC_ROLES.get(target_agent.role, {}).get("team", "")
                    # 处决邪恶: 对跳池+0.25 > 查杀+0.2 > 行为异常+0.1
                    if exec_team in ("demon", "minion"):
                        if nominee_claim and any(p != nominee and self.public_claims.get(p) == nominee_claim for p in self.public_claims):
                            add_reward(0.25)  # 对跳猎物
                        elif nominee in self.seer_cleared:
                            pass  # 占卜排的人翻出邪恶=占卜失准，不奖不罚
                        else:
                            add_reward(0.15)  # 无明确证据但投对
                    # 处决好人: 占卜排掉的-0.4, 信息位-0.3, 普通-0.15
                    else:
                        if nominee in self.seer_cleared:
                            add_reward(-0.4)  # 反推已排除的人→严重错误
                        elif nominee_claim in ("占卜师","共情者","调查员","洗衣妇","厨师","送葬者","守鸦人","图书管理员"):
                            add_reward(-0.3)  # 处决信息位→内耗
                        else:
                            add_reward(-0.15)
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
        # P0二次确认: 排除已死亡/已处决的红唇女郎
        scarlets = [s for s in scarlets if s.name not in self.dead_players]
        if not scarlets:
            return False
        # P0: 已有存活恶魔→无需继承(防止双恶魔bug)
        if any(a.role in BOTC_TEAMS["demon"] and a.alive for a in self.registry.all_agents()):
            return False
        sw = scarlets[0]
        old_sw_name = sw.name
        sw.role = "小恶魔"
        sw.game_state["role"] = "小恶魔"
        sw.game_state["original_role"] = "红唇女郎"  # 说书人面板标注来源
        # 继承事件写入夜间信息
        self.game_record.setdefault("night_info_history", {}).setdefault(f"day_{self.day_count}", {}).setdefault(old_sw_name, [])
        self.game_record["night_info_history"][f"day_{self.day_count}"][old_sw_name].append({
            'key': 'scarlet_convert',
            'text': f'红唇女郎→小恶魔 (原恶魔死亡，存活{alive_count}人≥5)',
            'day': self.day_count
        })
        sw.role = "小恶魔"
        sw.game_state["role"] = "小恶魔"
        sw.game_state["original_role"] = "红唇女郎"  # 说书人面板标注来源
        # Fix AC: 新恶魔强制更换伪装，不能沿用原来的爪牙伪装
        if sw.name in self._evil_plan:
            old_fake = self._evil_plan[sw.name].get("fake_role", "镇民")
            alive = [a.name for a in self.registry.all_alive() if a.name != sw.name]
            new_pool = ["洗衣妇", "图书管理员", "厨师", "共情者", "调查员", "送葬者", "守鸦人", "僧侣", "士兵"]
            # 排除旧伪装和原恶魔的伪装
            for ename, eplan in self._evil_plan.items():
                new_pool = [r for r in new_pool if r != eplan.get("fake_role", "")]
            new_fake = random.choice(new_pool) if new_pool else "镇民"
            self._evil_plan[sw.name]["fake_role"] = new_fake
            # Fix AP: 全面重置战术（清除旧爪牙时期的战术痕迹）
            self._evil_plan[sw.name].update({
                "tactic": "normal",
                "pocket_target": None,
                "sacrifice_partner": None,
                "claim_pair": None,
                "claim_battle_target": None,
                "vote_with": [],
                "vote_against": [],
                "current_kill_target": None,
            })
            # 清除假信息历史，重新开始
            if sw.name in self._evil_fake_log:
                old_log = self._evil_fake_log[sw.name]
                self._evil_fake_log[sw.name] = {k: v for k, v in old_log.items() if k < self.day_count - 1}
            self.log(f"  [红唇女郎] {sw.name}的伪装身份从{old_fake}更换为{new_fake}，战术已重置")
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
            'monk': lambda v: f"保护了 {v}",
        }
        # 仅首夜获取信息的角色
        first_night_only = {"washerwoman", "librarian", "investigator", "chef"}
        # 记录夜间死亡信息
        night_kill = getattr(self, '_last_night_kill', '')
        if night_kill:
            if night_kill not in self.game_record["night_info_history"][day_key]:
                self.game_record["night_info_history"][day_key][night_kill] = []
            existing = [e for e in self.game_record["night_info_history"][day_key][night_kill] if e['key'] == 'night_kill']
            if not existing:
                self.game_record["night_info_history"][day_key][night_kill].append({
                    'key': 'night_kill', 'text': f"第{self.night_count}晚被恶魔杀害", 'day': self.day_count
                })
            self._last_night_kill = ''

        for a in self.registry.all_agents():
            known = a.game_state.get('known_info', {})
            for k in info_map:
                if k not in known:
                    continue
                # 仅首夜角色：只在第 0 夜记录
                if k in first_night_only and self.day_count > 0:
                    continue
                text = info_map[k](known[k])
                if a.name not in self.game_record["night_info_history"][day_key]:
                    self.game_record["night_info_history"][day_key][a.name] = []
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
