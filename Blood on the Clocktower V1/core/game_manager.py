import json
import random
from datetime import datetime
from pathlib import Path
from .memory import GameMemory
from .agent import AgentRegistry


class GameManager:
    """通用游戏管理器"""

    def __init__(self, game_type: str, registry: AgentRegistry = None):
        self.game_type = game_type
        self.registry = registry or AgentRegistry()
        self.round_num = 0
        self.game_record = {
            "game_type": game_type,
            "started_at": datetime.now().isoformat(),
            "rounds": [],
            "result": "",
            "survivors": "",
            "players": [],
        }
        self.memory = GameMemory()

    def add_player(self, agent):
        self.registry.register(agent.name, agent)
        self.game_record["players"].append(agent.name)

    def start_game(self):
        raise NotImplementedError

    def run_round(self):
        raise NotImplementedError

    def run_night(self):
        raise NotImplementedError

    def run_day(self):
        raise NotImplementedError

    def end_game(self, result: str):
        self.game_record["result"] = result
        self.game_record["survivors"] = ", ".join(
            a.name for a in self.registry.all_alive()
        )
        self.game_record["ended_at"] = datetime.now().isoformat()
        filepath = self.memory.save_game(self.game_record, self.game_type)
        return filepath

    def broadcast(self, message: str):
        """向所有存活玩家广播信息"""
        for agent in self.registry.all_alive():
            agent.update_belief(message)

    def record_action(self, agent_name: str, context: str, action: str,
                      action_type: str = "speech", reward: float = 0):
        if not self.game_record["rounds"]:
            self.game_record["rounds"].append({
                "round_num": self.round_num or 0,
                "phase": "unknown", "actions": []
            })
        self.game_record["rounds"][-1]["actions"].append({
            "agent": agent_name,
            "context": context,
            "action": action,
            "type": action_type,
            "reward": reward,
            "round_num": self.round_num,
        })
