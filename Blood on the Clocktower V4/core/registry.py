"""Agent Registry for tracking all game participants"""

class Registry:
    def __init__(self):
        self._agents = []

    def add_agent(self, agent):
        self._agents.append(agent)

    def all_agents(self):
        return self._agents

    def all_alive(self):
        return [a for a in self._agents if a.alive]

    def get_by_role(self, role_name):
        return [a for a in self._agents if a.role == role_name]

    def get(self, name):
        for a in self._agents:
            if a.name == name:
                return a
        return None

    def find(self, name):
        return self.get(name)
