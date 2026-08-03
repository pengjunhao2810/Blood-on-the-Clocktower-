"""
自我升级引擎 — 每局自动评估→学习→优化，跨局积累进化
"""
import json, os, random, time
from collections import Counter, defaultdict
from datetime import datetime

UPGRADE_DIR = os.path.join(os.path.dirname(__file__), "upgrade_memory")
os.makedirs(UPGRADE_DIR, exist_ok=True)

# ===== 持久化记忆 =====
class SelfUpgrader:
    def __init__(self):
        self.generation = 0
        self.total_games = 0
        self.scores_history = []       # 每局评分
        self.template_weights = {}      # 模板类别→权重
        self.llm_hit_rate = 0.5         # LLM使用率（动态调整）
        self.best_patterns = []          # 高分对话片段
        self.trust_params = {            # 信任评估参数
            "info_match_bonus": 15,
            "consistency_bonus": 8,
            "vote_evil_bonus": 12,
            "evasion_penalty": -10,
        }
        self._load_memory()
    
    def _memory_path(self):
        return os.path.join(UPGRADE_DIR, "upgrader_memory.json")
    
    def _save_memory(self):
        data = {
            "generation": self.generation,
            "total_games": self.total_games,
            "scores_history": self.scores_history[-200:],
            "template_weights": self.template_weights,
            "llm_hit_rate": self.llm_hit_rate,
            "trust_params": self.trust_params,
            "last_upgrade": datetime.now().isoformat(),
        }
        with open(self._memory_path(), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _load_memory(self):
        path = self._memory_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.generation = data.get("generation", 0) + 1
            self.total_games = data.get("total_games", 0)
            self.scores_history = data.get("scores_history", [])
            self.template_weights = data.get("template_weights", {})
            self.llm_hit_rate = data.get("llm_hit_rate", 0.5)
            if "trust_params" in data:
                self.trust_params.update(data["trust_params"])
            print(f"[Upgrader] 加载第{self.generation}代记忆 ({self.total_games}局经验)")
        except Exception as e:
            print(f"[Upgrader] 记忆加载失败: {e}")
    
    # ===== 自评估 =====
    def evaluate_game(self, game_record):
        """对一局游戏综合打分 0-100"""
        score = 50
        issues = []
        bonuses = []
        
        pch = game_record.get("private_chat_history", {})
        thought_log = game_record.get("thought_log", {})
        result = game_record.get("result", "error")
        
        # 1. 对话多样性检测
        all_texts = []
        for tk, msgs in pch.items():
            for m in msgs:
                if m.get("speaker") != "__day__":
                    all_texts.append(m.get("text", ""))
        
        if all_texts:
            # 去重率
            unique_ratio = len(set(all_texts)) / len(all_texts) if all_texts else 0
            if unique_ratio < 0.7:
                score -= 20
                issues.append(f"重复率过高({round(1-unique_ratio,0)*100}%)")
            elif unique_ratio > 0.9:
                score += 10
                bonuses.append("对话多样性好")
            
            # 平均长度（太短=模板化）
            avg_len = sum(len(t) for t in all_texts) / len(all_texts)
            if avg_len < 20:
                score -= 15
                issues.append(f"平均对话太短({round(avg_len)}字)")
            elif avg_len > 40:
                score += 10
                bonuses.append(f"对话深度好({round(avg_len)}字/条)")
        
        # 2. 推理质量（思考日志是否丰富）
        if thought_log:
            total_entries = sum(len(es) for es in thought_log.values())
            if total_entries < 5:
                score -= 10
                issues.append("思考日志过于稀疏")
            elif total_entries > 10:
                score += 5
                bonuses.append("思考链路完整")
        
        # 3. 残句/错误检测
        bad_patterns = ["理由在", "你的你的", ":", "：", "在。" ]
        bad_count = sum(1 for t in all_texts for bp in bad_patterns if t.strip().endswith(bp) or f"理由在" in t)
        if bad_count > len(all_texts) * 0.05:
            score -= 10
            issues.append(f"残句数偏高({bad_count})")
        
        # 4. 胜负奖励
        if result == "evil_win":
            score += 5   # 邪恶胜=策略有效
        else:
            score += 2   # 善良胜=推理有效
        
        score = max(0, min(100, score))
        self.scores_history.append({
            "score": score, "result": result,"issues": issues, "bonuses": bonuses,
            "time": datetime.now().isoformat()
        })
        return score, issues, bonuses
    
    # ===== 学习反馈 =====
    def learn_from_game(self, game_record, score):
        """根据一局游戏结果调整参数"""
        result = game_record.get("result", "error")
        pch = game_record.get("private_chat_history", {})
        
        # 1. 模板权重调整：高分→增加生成模板权重，低分→回退静态模板
        if "GOOD_PRIVATE_DISCUSS_GEN" not in self.template_weights:
            self.template_weights["GOOD_PRIVATE_DISCUSS_GEN"] = 1.0
        if "EVIL_FAKE_GEN" not in self.template_weights:
            self.template_weights["EVIL_FAKE_GEN"] = 1.0
        
        if score >= 65:
            # 高分→提高生成模板权重
            for cat in ["GOOD_PRIVATE_DISCUSS_GEN", "EVIL_FAKE_GEN", "GOOD_PRIVATE_OPEN_GEN"]:
                self.template_weights[cat] = min(2.0, self.template_weights.get(cat, 1.0) + 0.05)
            # 提高LLM使用率
            self.llm_hit_rate = min(0.8, self.llm_hit_rate + 0.01)
        else:
            # 低分→降低生成模板权重
            for cat in ["GOOD_PRIVATE_DISCUSS_GEN", "EVIL_FAKE_GEN", "GOOD_PRIVATE_OPEN_GEN"]:
                self.template_weights[cat] = max(0.5, self.template_weights.get(cat, 1.0) - 0.02)
            self.llm_hit_rate = max(0.2, self.llm_hit_rate - 0.01)
        
        # 2. 信任参数微调：邪恶胜→加强信息校验权重
        if result == "evil_win" and self.total_games % 10 == 0:
            self.trust_params["info_match_bonus"] = min(25, self.trust_params["info_match_bonus"] + 1)
            self.trust_params["evasion_penalty"] = max(-15, self.trust_params["evasion_penalty"] - 1)
        
        # 3. 收集高质量对话片段（高分局）
        if score >= 70:
            for tk, msgs in pch.items():
                for m in msgs:
                    if m.get("speaker") != "__day__" and len(m.get("text","")) > 30:
                        self.best_patterns.append({
                            "text": m.get("text", ""),
                            "score": score,
                        })
            # 只保留最近500条
            self.best_patterns = self.best_patterns[-500:]
        
        self.total_games += 1
        
        # 每10局保存一次
        if self.total_games % 10 == 0:
            self._save_memory()
    
    # ===== 应用升级 =====
    def apply_to_game(self, game_instance):
        """将学习到的参数注入游戏实例"""
        # 信任参数注入
        if hasattr(game_instance, '_trust_bonus'):
            game_instance._trust_bonus.update(self.trust_params)
        
        # 返回模板权重（供_private_chat_phase使用）
        return {
            "template_weights": self.template_weights,
            "llm_hit_rate": self.llm_hit_rate,
        }
    
    def get_status(self):
        """返回当前进化状态"""
        avg_score = (sum(s["score"] for s in self.scores_history[-50:]) / max(1, len(self.scores_history[-50:])))
        return {
            "generation": self.generation,
            "total_games": self.total_games,
            "avg_score_50": round(avg_score, 1),
            "llm_rate": round(self.llm_hit_rate, 2),
            "template_weights": dict(self.template_weights),
        }


# ===== 全局单例 =====
_upgrader = None

def get_upgrader():
    global _upgrader
    if _upgrader is None:
        _upgrader = SelfUpgrader()
    return _upgrader
