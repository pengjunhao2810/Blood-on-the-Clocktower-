import random
from core.game_manager import GameManager
from .roles import BOTC_ROLES, BOTC_TEAMS
from .ml_policy import is_enabled, is_recording, get_trainer
from .evil_mixin import EvilMixin
from .night_mixin import NightMixin
from .private_chat_mixin import PrivateChatMixin
from .chat_mixin import ChatMixin
from .voting_mixin import VotingMixin


class BloodOnClocktowerGame(VotingMixin, EvilMixin, ChatMixin, PrivateChatMixin, NightMixin, GameManager):
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
        self.public_claims = {}
        self.nomination_count = {}
        self.hunter_used = set()
        self.chat_history = []

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
                "chat_memory": [],
                "suspicion": {},
                "trust": {},
                "my_claims": [],
            }
            self.add_player(agent)
        self.player_order = [a.name for a in self.registry.all_agents()]

        drunk_agents = [a for a in agents if a.role == "酒鬼"]
        for drunk in drunk_agents:
            existing_roles = {a.role for a in agents}
            available_townsfolk = [r for r in BOTC_TEAMS["townsfolk"] if r not in existing_roles]
            if available_townsfolk:
                fake_role = random.choice(available_townsfolk)
            else:
                fake_role = random.choice(BOTC_TEAMS["townsfolk"])
            drunk.game_state["fake_role"] = fake_role
            drunk.game_state["is_drunk"] = True
            self.log(f"  {drunk.name}是酒鬼(以为自己是{fake_role})")

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

    def phase_role_assignment(self):
        self.log(f"\n========== 剧本: {self.script} ==========")
        self.log(f"玩家人数: {self.num_players}")
        self.log("\n--- 角色分配 ---")
        for a in self.registry.all_agents():
            team_names = {"townsfolk": "镇民", "outsider": "外来者", "minion": "爪牙", "demon": "恶魔"}
            t = team_names.get(BOTC_ROLES[a.role].get("team", ""), "未知")
            self.log(f"  {a.name}: {a.role} ({t})")
        self.game_phase = "NIGHT"

    def run_day(self):
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
        if self.executed_today:
            self.log(f"\n[处决] 今天有玩家被处决。")
            self.peaceful_day = False
        else:
            self.log(f"\n[平安日] 今天无人被处决, 是个平安日。")
        self._check_game_end(check_mayor=True)

    def _check_scarlet_woman_conversion(self):
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
        demon_alive = any(
            a.alive for a in self.registry.all_agents()
            if a.role in BOTC_TEAMS["demon"]
        )
        alive_count = len(self.get_alive_names())

        if not demon_alive:
            if self._check_scarlet_woman_conversion():
                return False

        if check_mayor and alive_count <= 3 and not self.executed_today:
            mayor_players = [a for a in self.registry.all_agents()
                             if a.role == "镇长" and a.alive]
            if mayor_players:
                self.end_game("good_win")
                self.log(f"\n========== 游戏结束: 善良阵营获胜! ==========")
                self.log("镇长能力触发: 仅3人存活且无人被处决。")
                return True

        good_wins = not demon_alive
        evil_wins = alive_count <= 2

        if good_wins and evil_wins:
            self.end_game("good_win")
            self.log(f"\n========== 游戏结束: 善良阵营获胜! ==========")
            self.log("恶魔被处决，同时场上不足3人，善良阵营优先获胜。")
            return True

        if not demon_alive:
            self.end_game("good_win")
            self.log(f"\n========== 游戏结束: 善良阵营获胜! ==========")
            self.log("所有恶魔均已死亡。")
            return True

        if alive_count <= 2:
            self.end_game("evil_win")
            self.log(f"\n========== 游戏结束: 邪恶阵营获胜! ==========")
            self.log("场上只剩两名存活玩家。")
            return True

        return False

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

        if is_recording():
            win = "evil" in self.game_record.get("result", "")
            loss_val = get_trainer().finish_episode(win)
            if show_detail:
                self.log(f"[ML训练] 邪恶{'胜利' if win else '失败'}，loss={loss_val:.4f}")

        return self.game_record
