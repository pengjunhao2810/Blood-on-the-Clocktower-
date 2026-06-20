import json
import random
from collections import deque
from pathlib import Path
from datetime import datetime


class ExperienceMemory:
    """经验回放记忆系统 - 存储游戏中的经验用于后续学习"""

    def __init__(self, capacity=5000, memory_path=None):
        self.capacity = capacity
        self.memory_path = Path(memory_path) if memory_path else None
        self.buffer = deque(maxlen=capacity)
        self._load()

    def add(self, experience: dict):
        experience["timestamp"] = datetime.now().isoformat()
        self.buffer.append(experience)

    def add_batch(self, experiences: list):
        for exp in experiences:
            self.add(exp)

    def sample(self, batch_size=32):
        return random.sample(self.buffer, min(batch_size, len(self.buffer)))

    def __len__(self):
        return len(self.buffer)

    def _load(self):
        if self.memory_path and self.memory_path.exists():
            with open(self.memory_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data[-self.capacity:]:
                    self.buffer.append(item)

    def save(self):
        if self.memory_path:
            self.memory_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.memory_path, "w", encoding="utf-8") as f:
                json.dump(list(self.buffer), f, ensure_ascii=False, indent=2)

    def clear(self):
        self.buffer.clear()


class GameMemory:
    """完整游戏记忆 - 记录整局游戏的完整过程"""

    def __init__(self, storage_dir="data/game_logs"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save_game(self, game_record: dict, game_type: str = ""):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = game_type.replace(" ", "_") if game_type else "game"
        filename = f"{prefix}_{timestamp}.json"
        filepath = self.storage_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(game_record, f, ensure_ascii=False, indent=2)
        return str(filepath)

    def load_game(self, filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_games(self, game_type=None):
        games = []
        for f in self.storage_dir.glob("*.json"):
            if game_type and not f.name.startswith(game_type):
                continue
            games.append(str(f))
        return sorted(games)

    def generate_training_data(self, game_type=None):
        """从历史游戏中提取训练数据对"""
        samples = []
        for game_file in self.list_games(game_type):
            game = self.load_game(game_file)
            for round_data in game.get("rounds", []):
                for action in round_data.get("actions", []):
                    samples.append({
                        "context": action.get("context", ""),
                        "action": action.get("action", ""),
                        "reward": action.get("reward", 0),
                        "game_result": game.get("result", ""),
                    })
        return samples
