import random
from .roles import BOTC_ROLES, BOTC_TEAMS


class EvilMixin:
    def _init_evil_strategy(self):
        if hasattr(self, '_evil_inited'):
            self._reevaluate_evil_tactics()
            return
        self._evil_inited = True
        self._evil_plan = {}
        self._evil_vote_target = {}
        self._evil_fake_log = {}

        demons = [a for a in self.registry.all_agents() if a.role in BOTC_TEAMS["demon"]]
        minions = [a for a in self.registry.all_agents() if a.role in BOTC_TEAMS["minion"]]

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
                "vote_with": [],
                "vote_against": [],
                "claimed_info_history": [],
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

        if len(double_claim_players) >= 2:
            shared_role = random.choice(["士兵", "僧侣", "管家"])
            for n in double_claim_players:
                self._evil_plan[n]["claim_pair"] = shared_role
                self._evil_plan[n]["fake_role"] = shared_role
        elif len(double_claim_players) == 1:
            self._evil_plan[double_claim_players[0]]["tactic"] = "normal"

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

        if len(bus_players) >= 2:
            for i in range(0, len(bus_players) - 1, 2):
                a, b = bus_players[i], bus_players[i + 1]
                self._evil_plan[a]["vote_against"].append(b)
                self._evil_plan[b]["vote_against"].append(a)
                self._evil_plan[a]["tactic_role"] = "bus_driver"
                self._evil_plan[b]["tactic_role"] = "bus_target"

        for n in deep_cover_players:
            self._evil_plan[n]["tactic_role"] = "deep_cover"
            self._evil_plan[n]["fake_role"] = random.choice(
                ["占卜师", "共情者", "调查员", "洗衣妇"]
            )

        if len(role_swap_players) >= 2:
            roles = [self._evil_plan[n]["fake_role"] for n in role_swap_players]
            random.shuffle(roles)
            for n, r in zip(role_swap_players, roles):
                self._evil_plan[n]["fake_role"] = r
                self._evil_plan[n]["claim_pair"] = r

        if pocket_players and common_target:
            for n in pocket_players:
                self._evil_plan[n]["pocket_target"] = common_target

        claim_battle_players = [n for n, p in self._evil_plan.items() if p["tactic"] == "claim_battle"]
        for n in claim_battle_players:
            self._evil_plan[n]["claim_battle_target"] = common_target

        for n in self._evil_plan:
            if common_target:
                self._evil_plan[n]["common_target"] = common_target
            partners = [e for e in evil_names if e != n and
                        self.get_player_by_name(e) and self.get_player_by_name(e).alive]
            self._evil_plan[n]["vote_with"] = partners

        for n in self._evil_plan:
            self._evil_fake_log.setdefault(n, {})

    def _reevaluate_evil_tactics(self):
        if not hasattr(self, '_evil_plan'):
            return

        alive_evil = []
        for name, plan in list(self._evil_plan.items()):
            agent = self.get_player_by_name(name)
            if not agent or not agent.alive:
                continue
            alive_evil.append(name)

            partner = plan.get("sacrifice_partner")
            if partner:
                partner_agent = self.get_player_by_name(partner)
                if not partner_agent or not partner_agent.alive:
                    plan["tactic"] = "normal"
                    plan["sacrifice_partner"] = None

        if not alive_evil:
            return

        alive_good = [a for a in self.registry.all_agents()
                      if a.alive and a.role not in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]]

        if alive_good:
            _, _, claim_map = self._build_chat_summary(list(self.registry.all_agents())[0])
            info_claimants = [p for p in alive_good for rn in
                              ["占卜师", "共情者", "调查员", "送葬者", "守鸦人"]
                              if claim_map.get(p.name) == rn]
            if info_claimants:
                new_target = random.choice(info_claimants).name
            else:
                new_target = random.choice(alive_good).name

            for name in alive_evil:
                self._evil_plan[name]["common_target"] = new_target

        for name in alive_evil:
            partners = [e for e in alive_evil if e != name]
            self._evil_plan[name]["vote_with"] = partners

            if alive_good:
                _, _, claim_map = self._build_chat_summary(
                    self.get_player_by_name(name) or list(self.registry.all_agents())[0])
                info_roles = ["占卜师", "共情者", "调查员", "送葬者", "守鸦人", "士兵"]
                for p in alive_good:
                    if claim_map.get(p.name) in info_roles:
                        self._evil_plan[name]["current_kill_target"] = p.name
                        break
                else:
                    self._evil_plan[name]["current_kill_target"] = new_target if alive_good else None
