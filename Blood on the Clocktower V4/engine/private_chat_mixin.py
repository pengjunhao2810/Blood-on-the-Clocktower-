import random
from .roles import BOTC_ROLES, BOTC_TEAMS
from .personality import apply_personality


class PrivateChatMixin:
    def _store_chat(self, speaker, listener, speech, phase):
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
        history = {}
        for p in self.registry.all_agents():
            claims = p.game_state.get("my_claims", [])
            if claims:
                history[p.name] = [(c["day"], c["role"]) for c in claims]
        return history

    def _update_suspicion_from_chat(self, player):
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

            if sp_name in claim_history:
                roles_on_days = claim_history[sp_name]
                unique_roles = set(r for d, r in roles_on_days)
                if len(unique_roles) > 1:
                    gs["suspicion"][sp_name] = min(100, gs["suspicion"][sp_name] + 25)
                    gs["trust"][sp_name] = max(0, gs["trust"][sp_name] - 15)

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

            if "提名" in text or "处决" in text:
                for other_name in self.public_claims:
                    if other_name != sp_name and other_name in text:
                        if other_name not in gs["suspicion"]:
                            gs["suspicion"][other_name] = 50
                        if other_name not in gs["trust"]:
                            gs["trust"][other_name] = 50
                        gs["suspicion"][other_name] = min(100, gs["suspicion"][other_name] + 3)

    def _get_last_exchange(self, name_a, name_b, n=3):
        exchanges = []
        for p in self.registry.all_agents():
            mem = p.game_state.get("chat_memory", [])
            for entry in reversed(mem):
                sp = entry.get("speaker", "")
                txt = entry.get("text", "")
                phase = entry.get("phase", "")
                if phase == "private_chat" and sp in (name_a, name_b) and txt:
                    other = name_b if sp == name_a else name_a
                    if other in txt or True:
                        exchanges.append((sp, txt))
                        if len(exchanges) >= n:
                            return list(reversed(exchanges))
        return exchanges

    def _private_chat_phase(self):
        self.log(f"\n--- [私聊环节] 玩家可以私下交流 ---")
        self.game_phase = f"PRIVATE_CHAT_D{self.day_count}"

        if "private_chat_history" not in self.game_record:
            self.game_record["private_chat_history"] = {}

        alive = [a for a in self.registry.all_agents() if a.alive]
        random.shuffle(alive)

        used_pairs = set()
        chat_pairs = []
        max_chats_per_player = 3
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

        chat_rounds = 3

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
                name_prefix = f"{a.name}: "
                if s_a.startswith(name_prefix):
                    s_a = s_a[len(name_prefix):]
                s_a = apply_personality(a, s_a)
                self.log(f"  [第{rnd}轮] {a.name} 对 {b.name} 说: {s_a}")
                self.record_action(a.name, f"私聊{b.name}(第{rnd}轮)", s_a, "private_chat")
                self._store_chat(a.name, b.name, s_a, "private_chat")
                thread_msgs.append({"speaker": a.name, "text": s_a, "rnd": rnd})

                s_b = self._gen_speech(b, a.name)
                name_prefix = f"{b.name}: "
                if s_b.startswith(name_prefix):
                    s_b = s_b[len(name_prefix):]
                s_b = apply_personality(b, s_b)
                self.log(f"  [第{rnd}轮] {b.name} 对 {a.name} 说: {s_b}")
                self.record_action(b.name, f"私聊{a.name}(第{rnd}轮)", s_b, "private_chat")
                self._store_chat(b.name, a.name, s_b, "private_chat")
                thread_msgs.append({"speaker": b.name, "text": s_b, "rnd": rnd})

            self.game_record["private_chat_history"][thread_key] = thread_msgs

        if not chat_pairs:
            self.log(f"  (玩家较少, 私聊环节跳过)")

    def _pick_target_suspicion(self, player):
        gs = player.game_state
        if gs.get("suspicion"):
            sorted_suspects = sorted(gs["suspicion"].items(), key=lambda x: -x[1])
            for name, score in sorted_suspects:
                if score >= 60 and name != player.name:
                    return name
        alive = [a for a in self.registry.all_agents() if a.alive and a.name != player.name]
        return alive[0].name if alive else None

    def _build_chat_summary(self, player):
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
