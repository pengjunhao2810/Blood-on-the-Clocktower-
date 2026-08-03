import random
from .roles import BOTC_ROLES, BOTC_TEAMS, NIGHT_ORDER_FIRST, NIGHT_ORDER_OTHER
from .ml_policy import (
    encode_observation, get_policy, get_trainer,
    is_enabled, is_recording,
)


class NightMixin:
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

    def _ml_pick_kill_target(self, player, candidates):
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
        alive_names = [a.name for a in self.registry.all_alive() if a.name != player.name]
        alive_count = len(alive_names) + 1
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
        if player.role == "间谍":
            return random.choice(["townsfolk", "outsider", "townsfolk", "minion"])
        if player.role == "陌客":
            return random.choice(["townsfolk", "outsider", "minion", "demon"])
        return BOTC_ROLES.get(player.role, {}).get("team", "")

    def _get_registered_role(self, player):
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
