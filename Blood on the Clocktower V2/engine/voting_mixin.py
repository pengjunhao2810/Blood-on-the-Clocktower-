import random
from .roles import BOTC_ROLES, BOTC_TEAMS
from .dialogue_dataset import DialogueDataset as DD
from .ml_policy import (
    encode_observation, get_policy, get_trainer,
    is_enabled, is_recording,
)


class VotingMixin:
    def _gen_nomination_speech(self, nominator_name, target_name):
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

        target_claims = set()
        for entry in memory:
            if entry.get("speaker") == target_name:
                txt = entry.get("text", "")
                for rn in BOTC_ROLES:
                    if f"我是{rn}" in txt:
                        target_claims.add(rn)

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

        if nom_team in {"demon", "minion"}:
            target_team = BOTC_ROLES.get(target.role, {}).get("team", "")
            if target_team in {"demon", "minion"} and target_name != nominator_name:
                if random.random() < 0.3:
                    t = f"我提名{target_name}！我一直觉得{target_name}有问题，今天处决他获取关键信息！"
                    return DD.naturalize(t)

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
        target = self.get_player_by_name(target_name)
        if not target:
            return f"我是清白的！{nominator_name}在乱提名！"
        role = target.role
        team = BOTC_ROLES.get(role, {}).get("team", "")
        gs = target.game_state
        known = gs.get("known_info", {})
        _, _, claim_map = self._build_chat_summary(target)

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

        if "seer" in known:
            chosen, has = known["seer"]
            demon_found = "查出了恶魔！这就是为什么我敢肯定{nominator}在胡说！" if has else "正在缩小范围，我还有用！"
            return DD.naturalize(f"大家冷静！我是占卜师，我查了{chosen[0]}和{chosen[1]}，{demon_found}")
        if "empathy" in known:
            e = known["empathy"]
            return DD.naturalize(f"我是共情者，我旁边邪恶数为{e}！处决我的话好人就失去了每晚的邪恶探测——这正中邪恶下怀！")
        if "investigator" in known:
            inv_name, inv_role = known["investigator"]
            return DD.naturalize(f"我是调查员！我查出{inv_name}是{inv_role}——这才是真正的爪牙！{nominator_name}急着处决我，"
                                 f"就是因为怕我继续查出他的同伙！")
        if "washerwoman" in known:
            return DD.naturalize(f"我是洗衣妇！{reason_str}处决我这条信息链就断了。{nominator_name}的目的就是销毁证据！")
        if "chef" in known:
            return DD.naturalize(f"我是厨师！{reason_str}nominator急着处决一个信息位，这不合逻辑！")

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

        if team in {"demon", "minion"}:
            kwargs["nominator"] = nominator_name
            t = DD.get_filled("DEFENSE_EVIL", used=used, **kwargs)
            return DD.naturalize(t)

        t = DD.get_filled("DEFENSE_GOOD", used=used, **kwargs)
        return DD.naturalize(t)

    def _nomination_and_voting_phase(self):
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
            targets = [n for n in alive if n != nominator and n not in nominations]
            if not targets:
                break
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

            nom_speech = self._gen_nomination_speech(nominator, target)
            self.log(f"  [提名发言] {nominator}: {nom_speech}")
            self.record_action(nominator, f"提名{target}", nom_speech, "nomination")

            def_speech = self._gen_defense_speech(target, nominator)
            self.log(f"  [辩护发言] {target}: {def_speech}")
            self.record_action(target, f"被{nominator}提名", def_speech, "defense")

            result = self._run_vote(target, nominator)

            # 记录提名历史
            day_key = f"day_{self.day_count}"
            if "nomination_history" not in self.game_record:
                self.game_record["nomination_history"] = {}
            if day_key not in self.game_record["nomination_history"]:
                self.game_record["nomination_history"][day_key] = []
            self.game_record["nomination_history"][day_key].append({
                "nominator": nominator,
                "target": target,
                "nominator_speech": nom_speech,
                "defense_speech": def_speech,
                "result": "executed" if result == "executed" else "failed",
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
        gs = voter.game_state
        suspicion = gs.get("suspicion", {}).get(nominee, 50)
        trust = gs.get("trust", {}).get(nominee, 50)
        known_info = gs.get("known_info", {})

        if voter.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
            nom_agent = self.get_player_by_name(nominee)
            ml_aggression = 0.5
            if is_enabled():
                try:
                    obs, _, _ = encode_observation(self, voter)
                    ml_aggression = get_policy().get_vote_prob(obs)
                except Exception:
                    ml_aggression = 0.5
            if nom_agent and nom_agent.role in BOTC_TEAMS["townsfolk"] + BOTC_TEAMS["outsider"]:
                return 0.5 + 0.45 * ml_aggression
            if nom_agent and nom_agent.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
                if nom_agent.name == voter.name:
                    return 0.0
                alive_count = len(self.get_alive_names())
                if alive_count <= 4:
                    return 0.0
                if ml_aggression > 0.6 and random.random() < 0.3:
                    return 0.85
            return 0.1 + 0.2 * (1 - ml_aggression)

        base = (suspicion - 50) / 50
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
            if is_recording() and is_enabled() and voter.role in BOTC_TEAMS["demon"] + BOTC_TEAMS["minion"]:
                try:
                    import math
                    import torch
                    lp_val = math.log(vote_prob if cast_vote else 1.0 - vote_prob + 1e-10)
                    get_trainer().record_step(torch.tensor(lp_val))
                except Exception:
                    pass
            if cast_vote:
                vote_records.append({"voter": voter_name, "target": nominee, "day": self.day_count})
            if cast_vote:
                votes_for += 1
                voter_details.append(f"{voter_name}({BOTC_ROLES[voter.role].get('team', '')})")

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
