from core.agent import SocialDeductionAgent


class BOTCStrategy:
    @staticmethod
    def generate_discussion(agent: SocialDeductionAgent) -> str:
        role = agent.role
        known = agent.game_state.get("known_info", {})

        if role == "占卜师" and "seer" in known:
            chosen, has_demon = known["seer"]
            return f"{agent.name}: 我昨晚查了{chosen[0]}和{chosen[1]}，{'有' if has_demon else '没有'}恶魔。"

        if role == "共情者" and "empathy" in known:
            count = known["empathy"]
            return f"{agent.name}: 我身边有{count}个邪恶玩家。"

        if role == "间谍" and "spy_info" in known:
            return f"{agent.name}: 我也没什么特别的信息。"

        return f"{agent.name}: 目前信息有限，大家多分享一些线索吧。"

    @staticmethod
    def decide_vote(agent: SocialDeductionAgent, nominee: str, candidates: list) -> bool:
        return True
