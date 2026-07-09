"""Social Deduction Agent base class"""

class SocialDeductionAgent:
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role
        self.alive = True
        self.game_state = {
            "known_info": {},
            "suspicion": {},
            "trust": {},
            "chat_memory": [],
            "notes": "",
            "is_poisoned": False,
            "is_drunk": False,
            "role": role,
        }

    def update_belief(self, message: str):
        pass

    def add_to_memory(self, context: str, action: str, phase: str, speaker: str):
        memory_entry = {
            "context": context,
            "text": action,
            "phase": phase,
            "speaker": speaker,
        }
        self.game_state.setdefault("chat_memory", []).append(memory_entry)
        if len(self.game_state["chat_memory"]) > 200:
            self.game_state["chat_memory"] = self.game_state["chat_memory"][-200:]
