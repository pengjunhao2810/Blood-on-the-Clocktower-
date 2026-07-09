"""Memory module for saving/loading game state"""
import json, os
from datetime import datetime


class Memory:
    def __init__(self):
        self.games = []

    def save_game(self, game_record, game_type="blood_on_clocktower"):
        try:
            base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "game_logs")
            os.makedirs(base_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{game_type}_{timestamp}.json"
            filepath = os.path.join(base_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(game_record, f, ensure_ascii=False, indent=2, default=str)
            return filepath
        except Exception:
            return ""

    def load_game(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
