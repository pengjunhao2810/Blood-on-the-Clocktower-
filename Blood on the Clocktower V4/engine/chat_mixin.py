import random
from .roles import BOTC_ROLES, BOTC_TEAMS
from .dialogue_dataset import DialogueDataset as DD
from .dialogue_generator import (gen_good_private_discuss, gen_evil_private_plan,
                                 gen_good_public_reasoning, gen_good_bluff,
                                 gen_evil_public_reasoning)
from .personality import assign_personality, set_current_personality


class ChatMixin:
    def _gen_private_chat(self, player, listener):
        name = player.name
        role = player.role
        gs = player.game_state
        team = BOTC_ROLES.get(role, {}).get("team", "")
        info = gs.get("known_info", {})
        trust = gs.get("trust", {}).get(listener, 50)
        sus = gs.get("suspicion", {}).get(listener, 50)
        suspect = self._pick_target_suspicion(player)

        exchanged = sum(1 for m in gs.get("chat_memory", [])
                      if m.get("phase") == "private_chat"
                      and ((m.get("speaker") == name and m.get("listener") == listener)
                           or (m.get("speaker") == listener and m.get("listener") == name))
                      and m.get("day") == self.day_count)

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
        contradict = []
        seen_roles = {}
        for sp, rn in claim_map.items():
            if rn in seen_roles and seen_roles[rn] != sp:
                contradict.append(f"{sp}和{seen_roles[rn]}都自称{rn}")
            seen_roles[rn] = sp
        contradict_str = "，".join(contradict[:2])

        kwargs = dict(
            name=name, listener=listener, target=suspect or (alive_others[0] if alive_others else "某人"),
            suspect=suspect or "某人", role=role, my_fake=role,
            my_claim=my_claim or "未声明", claim=listener_claim or "身份不明",
            claim_str=claim_str, vote_str=vote_str, contradict_str=contradict_str or "暂无矛盾",
            info_share="暂无特殊信息",
            other=random.choice(alive_others) if len(alive_others) > 1 else (alive_others[0] if alive_others else "某人"),
            other_target=random.choice(alive_others) if alive_others else "某人",
            ref=partner_last_msg[partner_last_msg.find(": ")+2:][:50] if partner_last_msg and ": " in partner_last_msg else (partner_last_msg[:50] if partner_last_msg else "你的发言"),
            listener_fake=listener_claim or "镇民",
        )

        used_key = f"_used_priv_{self.day_count}"
        used = gs.setdefault(used_key, set())

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

            if team == "demon" and listener in minions:
                kwargs["target"] = suspect or (alive_others[0] if alive_others else "目标")
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

            if sus > 60:
                kwargs["target"] = suspect or (alive_others[0] if alive_others else "某人")
                t = DD.get_filled("EVIL_COUNTER_ATTACK", used=used, **kwargs)
                t = DD.naturalize(t)
                return f"{name}: {t}"

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
                return f"知道{info['washerwoman'][0]}是{info['washerwoman'][1]}"
            if "chef" in info:
                return f"相邻邪恶对数{info['chef']}"
            return f"我是{role}，暂无信息"

        if trust > 70:
            kwargs["info_share"] = _build_info_share()
            kwargs["target"] = suspect or (alive_others[0] if alive_others else "某人")
            t = DD.get_filled(good_phases[cp], used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

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

        if _has_info_role(role):
            kwargs["target"] = suspect or (alive_others[0] if alive_others else "某人")
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

        kwargs["target"] = suspect or (alive_others[0] if alive_others else "某人")
        noninfo_phases = ["GOOD_PRIVATE_OPEN", "GOOD_NOINFO_PROBE", "GOOD_PRIVATE_PERSUADE",
                          "GOOD_PRIVATE_COORDINATE", "GOOD_PRIVATE_CLOSING"]
        t = DD.get_filled(noninfo_phases[cp], used=used, **kwargs)
        t = DD.naturalize(t)
        return f"{name}: {t}"

    def _gen_dead_speech(self, player):
        name = player.name
        gs = player.game_state
        info = gs.get("known_info", {})
        _, _, claim_map = self._build_chat_summary(player)
        suspect = self._pick_target_suspicion(player)
        alive_names = self.get_alive_names()
        kwargs = dict(name=name, target=suspect or "某人",
                      other=random.choice([p for p in alive_names if p != name]) if alive_names else "某人")

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
        name = player.name
        role = player.role
        gs = player.game_state
        team = BOTC_ROLES.get(role, {}).get("team", "")
        info = gs.get("known_info", {})
        suspect = self._pick_target_suspicion(player)
        day = self.day_count
        _, _, claim_map = self._build_chat_summary(player)

        def _claim_of(p):
            return claim_map.get(p, "?")

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

            claim_str = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:6]]) if claim_map else ""
            vote_info = self.game_record.get("vote_history", {})
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

            kwargs = dict(name=name, target=target_for_accusation or "某人", accusation=accusation,
                         bluff=bluff, fake_info=self._gen_consistent_fake_info(name, bluff),
                         claim_str=claim_str, vote_str=vote_str, contradict_str=cstr, claim="?",
                         other=random.choice(list(claim_map.keys())) if claim_map else "某人",
                         other_target=random.choice(list(claim_map.keys())) if claim_map else "某人")

            claim_battle_msg = self._detect_claim_battle(name, evil_plan, claim_map, claim_str, vote_str)
            if claim_battle_msg:
                return f"{name}: {claim_battle_msg}"

            used_pub = gs.setdefault(f"_used_pub_{self.day_count}", set())

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

        claim_str = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:6]]) if claim_map else ""
        vote_info = self.game_record.get("vote_history", {})
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

        def _claim_of(p):
            return claim_map.get(p, "?")

        used_key = f"_used_pub_{self.day_count}"
        used = gs.setdefault(used_key, set())

        kwargs = dict(name=name, role=role, target=suspect or "某人", suspect=suspect or "某人",
                     claim_str=claim_str, vote_str=vote_str, contradict_str=cstr,
                     claim=_claim_of(suspect) if suspect else "?", voted="某人",
                     other=random.choice(list(claim_map.keys())) if claim_map else "某人",
                     other_target=random.choice(list(claim_map.keys())) if claim_map else "某人")

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
            t_name, t_role = info["investigator"]
            kwargs.update(target=t_name, role=t_role)
            t = DD.get_filled("GOOD_PUBLIC_INVESTIGATOR", used=used, **kwargs)
            t = DD.naturalize(t)
            return f"{name}: {t}"

        info_or_opinion = ""
        if "chef" in info:
            info_or_opinion = f"厨师结果：相邻邪恶对数{info['chef']}"
        elif "washerwoman" in info:
            info_or_opinion = f"洗衣妇信息：{info['washerwoman'][0]}是{info['washerwoman'][1]}"
        elif "librarian" in info:
            t, r = info["librarian"]
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

        kwargs["info_or_opinion"] = "暂时没有关键信息"
        kwargs["opinion"] = f"我会重点观察{suspect or '大家的发言'}"
        text = DD.get_filled("GOOD_PUBLIC_ANALYSIS", used=used, **kwargs)
        text = DD.naturalize(text)
        return f"{name}: {text}"

    def _gen_speech(self, player, listener=None):
        name = player.name
        gs = player.game_state
        team = BOTC_ROLES.get(gs.get("role", player.role), {}).get("team", "")
        dead = not player.alive
        assign_personality(player)
        set_current_personality(player._personality)
        p = player._personality
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
        name = player.name
        role = player.role
        gs = player.game_state
        team = BOTC_ROLES.get(role, {}).get("team", "")
        if team not in ("townsfolk", "outsider"):
            return None
        info = gs.get("known_info", {})
        if any(k in info for k in ("seer", "empathy", "investigator", "washerwoman", "chef", "ravenkeeper")):
            return None
        suspect = self._pick_target_suspicion(player)
        if not suspect or self.day_count < 2:
            return None
        if random.random() > 0.30:
            return None
        if gs.get("_bluffed_already"):
            return None
        gs["_bluffed_already"] = True
        _, _, claim_map_live = self._build_chat_summary(player)
        text = gen_good_bluff(name, role, info, suspect, claim_map_live,
                              self.game_record.get("vote_history", {}))
        text = DD.naturalize(text)
        return text

    def _detect_claim_battle(self, name, evil_plan, claim_map, claim_str="", vote_str=""):
        tactic = evil_plan.get("tactic", "")
        if tactic != "claim_battle":
            return None
        alive_names = [a for a in self.get_alive_names() if a != name]
        battle_roles = {"猎手": "CLAIM_BATTLE_HUNTSMAN", "士兵": "CLAIM_BATTLE_SOLDIER",
                        "僧侣": "CLAIM_BATTLE_MONK", "镇长": "CLAIM_BATTLE_MAYOR",
                        "占卜师": "CLAIM_BATTLE_SEER",
                        "镇民": None}
        candidates = [(sp, rn) for sp, rn in claim_map.items()
                      if sp != name and sp in alive_names]
        if not candidates:
            return None
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
        alive_names = [a for a in self.get_alive_names() if a != name]
        others_pool = alive_names[:]
        random.shuffle(others_pool)
        if not others_pool:
            return ""
        v1 = others_pool[0]
        v2 = others_pool[1] if len(others_pool) > 1 else v1
        v3 = others_pool[2] if len(others_pool) > 2 else v1

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

        self._evil_fake_log.setdefault(name, {})[self.day_count] = {
            "claimed_role": bluff_role,
            "target": v1,
            "target2": v2,
            "message": msg[:60],
        }

        return msg

    def _gen_consistent_fake_info(self, name, bluff_role):
        msg = self._gen_fake_info(name, bluff_role)

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
        gs = hunter.game_state
        memory = gs.get("chat_memory", [])
        known = gs.get("known_info", {})

        if gs.get("suspicion"):
            sorted_suspects = sorted(gs["suspicion"].items(), key=lambda x: -x[1])
            if sorted_suspects:
                top = sorted_suspects[0]
                if top[1] >= 70:
                    return top[0]

        if "seer" in known:
            chosen, has = known["seer"]
            if has and chosen:
                return chosen[0]

        if self.day_count <= 1:
            alive = [a.name for a in self.registry.all_alive() if a.name != hunter.name]
            if alive:
                return random.choice(alive)

        for entry in reversed(memory):
            for rn in BOTC_ROLES:
                if f"我是{rn}" in entry.get("text", ""):
                    speaker = entry["speaker"]
                    if speaker != hunter.name:
                        return speaker

        alive = [a.name for a in self.registry.all_alive() if a.name != hunter.name]
        return alive[0] if alive else None

    def _public_chat_phase(self):
        self.log(f"\n--- [公聊环节] 玩家公开讨论 ---")
        self.game_phase = f"PUBLIC_CHAT_D{self.day_count}"

        alive_names = self.get_alive_names()

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

        all_names = [a.name for a in self.registry.all_agents()]
        for player in self.registry.all_agents():
            self._update_suspicion_from_chat(player)
            speech = self._gen_speech(player)
            context = f"公聊环节, 存活: {self.get_alive_names()}"
            self.record_action(player.name, context, speech, "speech")
            self.log(f"  {speech}")
            self._store_chat(player.name, "all", speech, "public_chat")
            for role_name in BOTC_ROLES:
                if f"我是{role_name}" in speech:
                    self.public_claims[player.name] = role_name
                    break
