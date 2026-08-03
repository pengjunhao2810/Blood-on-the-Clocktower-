"""Game Manager base class"""
from datetime import datetime
from .memory import Memory
from .registry import Registry


class GameManager:
    def __init__(self, game_type="", registry=None):
        self.game_type = game_type
        self.registry = registry or Registry()
        self.game_record = {"rounds": [], "actions": [], "steps": 0}
        self.storyteller_log = []
        self.memory = Memory()
        self._step_count = 0

    def log(self, message: str):
        self.storyteller_log.append(message)

    def add_player(self, agent):
        self.registry.add_agent(agent)

    def end_game(self, result: str):
        self.game_record["result"] = result
        self.game_record["survivors"] = ", ".join(a.name for a in self.registry.all_alive())
        self.game_record["ended_at"] = datetime.now().isoformat()
        filepath = self.memory.save_game(self.game_record, self.game_type)
        return filepath

    def broadcast(self, message: str):
        for agent in self.registry.all_alive():
            agent.update_belief(message)

    def record_action(self, agent_name: str, context: str, action: str, phase: str = "general"):
        actions = self.game_record.setdefault("actions", [])
        actions.append({"agent": agent_name, "context": context, "action": action, "phase": phase})
        agent = self.get_player_by_name(agent_name)
        if agent:
            agent.add_to_memory(context, action, phase, agent_name)

    def get_alive_names(self):
        if not self.registry:
            return []
        return [a.name for a in self.registry.all_alive()]

    def get_player_by_name(self, name):
        if not self.registry:
            return None
        for a in self.registry.all_agents():
            if a.name == name:
                return a
        return None

    def _store_chat(self, speaker, listener, text, phase):
        pass
