import json
import random
from .memory import ExperienceMemory, GameMemory
from pathlib import Path


class SocialDeductionAgent:
    """社交推理游戏AI Agent基类 - 所有游戏角色的基类"""

    def __init__(self, name: str, role: str, model=None, memory_capacity=1000):
        self.name = name
        self.role = role
        self.model = model
        self.alive = True
        self.game_state = {}
        self.knowledge_base = []
        self.experience_memory = ExperienceMemory(capacity=memory_capacity)
        self.game_memory = GameMemory()

    def speak(self, context: dict) -> str:
        """根据当前游戏上下文生成发言"""
        raise NotImplementedError

    def vote(self, context: dict) -> str:
        """投票决策"""
        raise NotImplementedError

    def night_action(self, context: dict) -> dict:
        """夜间行动"""
        raise NotImplementedError

    def learn_from_game(self, game_record: dict):
        """从对局中学习"""
        self.game_memory.save_game(game_record, type(self).__name__)
        for round_data in game_record.get("rounds", []):
            for action in round_data.get("actions", []):
                if action.get("agent") == self.name:
                    self.experience_memory.add({
                        "context": action.get("context", ""),
                        "action": action.get("action", ""),
                        "reward": action.get("reward", 0),
                        "role": self.role,
                        "result": game_record.get("result", ""),
                    })

    def recall_similar(self, query: str, k=5) -> list:
        """回忆相似经验 - RAG式检索"""
        if len(self.experience_memory) == 0:
            return []
        samples = self.experience_memory.buffer
        scored = []
        for exp in samples:
            ctx = exp.get("context", "")
            score = len(set(ctx) & set(query)) / max(len(set(query)), 1)
            scored.append((score, exp))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s[1] for s in scored[:k]]

    def update_belief(self, observation: str):
        """更新信念状态"""
        self.game_state["last_observation"] = observation
        if "observations" not in self.game_state:
            self.game_state["observations"] = []
        self.game_state["observations"].append(observation)

    def get_strategy_prompt(self) -> str:
        """生成策略提示"""
        return (
            f"你是{self.name}，身份是{self.role}。\n"
            f"当前存活状态：{'存活' if self.alive else '死亡'}\n"
            f"游戏状态：{json.dumps(self.game_state, ensure_ascii=False)}\n"
            f"已知信息：{self.knowledge_base}\n"
            f"请根据身份和当前局面做出最佳决策。"
        )


class AgentRegistry:
    """Agent注册管理器"""

    def __init__(self):
        self._agents = {}

    def register(self, name: str, agent: SocialDeductionAgent):
        self._agents[name] = agent

    def get(self, name: str) -> SocialDeductionAgent:
        return self._agents.get(name)

    def all_alive(self):
        return [a for a in self._agents.values() if a.alive]

    def all_agents(self):
        return list(self._agents.values())

    def get_by_role(self, role: str):
        return [a for a in self._agents.values() if a.role == role]
