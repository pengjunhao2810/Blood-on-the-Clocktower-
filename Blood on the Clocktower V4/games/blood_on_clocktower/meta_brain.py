"""
元脑 MetaBrain — AI的自我意识层
自动监控、切换、进化、修复LLM和对话系统
"""
import os, json, time, random, re
from collections import deque, Counter
from datetime import datetime
from .llm_filler import generate_text, is_available
from .llm_brain import SYSTEM_PROMPT as BASE_SYSTEM_PROMPT

META_DIR = os.path.join(os.path.dirname(__file__), "meta_memory")
os.makedirs(META_DIR, exist_ok=True)

# ===== 质量评分器 =====
def score_llm_output(text, context=None):
    """实时评分一段LLM输出 0-100"""
    if not text or len(text) < 5:
        return 0
    score = 60
    
    # 1. 长度合理性
    if 20 <= len(text) <= 120:
        score += 10
    elif len(text) < 10:
        score -= 30
    
    # 2. 残句检测
    bad_ends = ["理由在", "因为", "由于", "在于", "你的", "在。"]
    for be in bad_ends:
        if text.strip().endswith(be):
            score -= 20
            break
    
    # 3. 模板残留
    template_markers = ["{target}", "{claim}", "{role}", "{vote_str}", "{contradict_str}"]
    for tm in template_markers:
        if tm in text:
            score -= 15
            break
    
    # 4. 重复检测
    words = text.split()
    if len(words) > 3:
        word_counts = Counter(words)
        most_common_count = word_counts.most_common(1)[0][1]
        if most_common_count > len(words) * 0.3:
            score -= 10  # 单词重复度过高
    
    # 5. 上下文相关性（如果提供了context）
    if context:
        context_words = set(re.findall(r'[\u4e00-\u9fa5]+', context))
        text_words = set(re.findall(r'[\u4e00-\u9fa5]+', text))
        overlap = len(context_words & text_words)
        if overlap >= 3:
            score += 10
        elif overlap == 0:
            score -= 10
    
    return max(0, min(100, score))


# ===== LLM模式管理器 =====
class LLMModeManager:
    """管理LLM使用模式：ON/OFF/MIXED，根据质量动态切换"""
    
    MODES = ["qwen", "template", "mixed"]
    
    def __init__(self):
        self.current_mode = "mixed"
        self.mode_history = deque(maxlen=100)
        self.quality_window = deque(maxlen=20)  # 最近20条质量分
        self.failure_streak = 0
        self.success_streak = 0
        self.total_llm_calls = 0
        self.total_template_fallbacks = 0
        self._load_state()
    
    def record_llm_result(self, quality_score):
        """记录一次LLM生成的质量"""
        self.total_llm_calls += 1
        self.quality_window.append(quality_score)
        
        if quality_score >= 50:
            self.success_streak += 1
            self.failure_streak = 0
        else:
            self.failure_streak += 1
            self.success_streak = 0
        
        self._auto_switch()
    
    def record_template_fallback(self):
        """记录一次模板兜底"""
        self.total_template_fallbacks += 1
    
    def should_use_llm(self):
        """判断当前是否应该使用LLM"""
        if self.current_mode == "qwen":
            return True
        elif self.current_mode == "template":
            return False
        elif self.current_mode == "mixed":
            # 根据质量动态调整概率
            avg_quality = (sum(self.quality_window) / max(1, len(self.quality_window)))
            if self.failure_streak >= 5:
                return False  # 连续5次低质量→关闭LLM
            if avg_quality < 40:
                return random.random() < 0.2  # 低质量→低概率
            return random.random() < 0.6  # 正常→60%概率
    
    def _auto_switch(self):
        """自动切换模式"""
        changed = False
        if self.failure_streak >= 8:
            if self.current_mode != "template":
                self.current_mode = "template"
                changed = True
                print(f"[MetaBrain] 🔴 LLM连续8次低质→切换到模板模式")
        elif self.failure_streak >= 5:
            if self.current_mode == "qwen":
                self.current_mode = "mixed"
                changed = True
                print(f"[MetaBrain] 🟡 LLM连续5次低质→切换到混合模式")
        elif self.success_streak >= 10:
            if self.current_mode != "qwen":
                self.current_mode = "qwen"
                changed = True
                print(f"[MetaBrain] 🟢 LLM连续10次高质→切换到LLM优先模式")
        elif self.success_streak >= 5 and self.current_mode == "template":
            self.current_mode = "mixed"
            changed = True
            print(f"[MetaBrain] 🟡 LLM恢复中→回到混合模式")
        
        if changed:
            self.mode_history.append({"mode": self.current_mode, "time": datetime.now().isoformat()})
            self._save_state()
    
    def get_status(self):
        avg_q = sum(self.quality_window) / max(1, len(self.quality_window))
        return {
            "mode": self.current_mode,
            "avg_quality": round(avg_q, 1),
            "total_llm": self.total_llm_calls,
            "total_fallback": self.total_template_fallbacks,
            "failure_streak": self.failure_streak,
            "success_streak": self.success_streak,
        }
    
    def _save_state(self):
        path = os.path.join(META_DIR, "llm_mode.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.get_status(), f, ensure_ascii=False, indent=2)
    
    def _load_state(self):
        path = os.path.join(META_DIR, "llm_mode.json")
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.current_mode = data.get("mode", "mixed")
            except:
                pass


# ===== Prompt自进化器 =====
class PromptEvolver:
    """自动变异和筛选最优System Prompt"""
    
    def __init__(self):
        self.base_prompt = BASE_SYSTEM_PROMPT
        self.prompt_variants = [BASE_SYSTEM_PROMPT]
        self.prompt_scores = {BASE_SYSTEM_PROMPT: 50}  # prompt → 累计评分
        self.prompt_uses = {BASE_SYSTEM_PROMPT: 0}     # prompt → 使用次数
        self.generation = 0
        self._load()
    
    def get_best_prompt(self):
        """返回当前评分最高的prompt"""
        if not self.prompt_scores:
            return self.base_prompt
        return max(self.prompt_scores, key=lambda p: self.prompt_scores[p] / max(1, self.prompt_uses[p]))
    
    def record_result(self, prompt_used, quality_score):
        """记录一次prompt的表现"""
        if prompt_used not in self.prompt_scores:
            self.prompt_scores[prompt_used] = quality_score
            self.prompt_uses[prompt_used] = 1
        else:
            # 指数加权平均
            alpha = 0.3
            old_avg = self.prompt_scores[prompt_used] / max(1, self.prompt_uses[prompt_used])
            self.prompt_uses[prompt_used] += 1
            self.prompt_scores[prompt_used] = (1 - alpha) * self.prompt_scores[prompt_used] + alpha * quality_score * self.prompt_uses[prompt_used]
    
    def evolve(self):
        """产生新一代prompt变体"""
        self.generation += 1
        best = self.get_best_prompt()
        new_variants = []
        
        mutations = [
            # 强化角色扮演
            lambda p: p + "\n- 你的语气和用词必须完全符合你的角色身份，不要用模板化表达。",
            # 强化逻辑推理
            lambda p: p + "\n- 分析时先列出你掌握的事实，再给出你的推理和结论。",
            # 强化具体性
            lambda p: p + "\n- 怀疑或信任某人时，必须给出具体的行为依据，不能只凭感觉。",
            # 强化对话承接
            lambda p: p + "\n- 回应对方时，先总结对方的核心观点或问题，再表达你的看法。",
            # 强化阵营意识
            lambda p: p + "\n- 你的发言必须服务于你的阵营利益：善良方推进推理，邪恶方隐藏真实意图。",
            # 去冗余
            lambda p: p.replace("不要机械分析，要像真实对话一样自然。", "像真人玩家一样说话，有情绪起伏和策略思考。"),
            lambda p: p.replace("不要说套话和空话", "每句话都要有实质信息量——要么提新线索，要么推进推理，要么推动投票"),
        ]
        
        for i, mut in enumerate(random.sample(mutations, min(3, len(mutations)))):
            new_prompt = mut(best)
            if new_prompt not in self.prompt_scores and len(new_prompt) < 2000:
                self.prompt_scores[new_prompt] = 50
                self.prompt_uses[new_prompt] = 0
                new_variants.append(new_prompt)
        
        # 限制总prompt数
        if len(self.prompt_scores) > 20:
            worst = min(self.prompt_scores, key=lambda p: self.prompt_scores[p] / max(1, self.prompt_uses[p]))
            if worst != self.base_prompt:
                del self.prompt_scores[worst]
                if worst in self.prompt_uses:
                    del self.prompt_uses[worst]
        
        self._save()
        return new_variants
    
    def _save(self):
        path = os.path.join(META_DIR, "prompts.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({
                "generation": self.generation,
                "variants": list(self.prompt_scores.keys())[:10],
                "best": self.get_best_prompt(),
            }, f, ensure_ascii=False, indent=2)
    
    def _load(self):
        path = os.path.join(META_DIR, "prompts.json")
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.generation = data.get("generation", 0)
            except:
                pass


# ===== 代码自修复引擎 =====
class SelfHealer:
    """检测高频错误模式并自动生成修复补丁"""
    
    ERROR_PATTERNS = {
        "残句-理由在": {
            "pattern": r"理由在[。，]",
            "fix_desc": "contradict_str为空时产生'理由在。'残句",
            "fix_location": "dialogue_dataset.py:get_filled",
            "fix_code": 'result = result.replace("理由在，", "").replace("理由在。", "")',
        },
        "人称错乱": {
            "pattern": r"你的身份不明声明",
            "fix_desc": "target的claim未正确设置",
            "fix_location": "rules.py:kwargs['claim']",
            "fix_code": 'kwargs["claim"] = claim_map.get(suspect, listener_claim or "身份不明")',
        },
        "重复前缀": {
            "pattern": r"^(真的假的\?\?！|我觉得吧，|理性分析的话，)",
            "fix_desc": "naturalize过度添加机械前缀",
            "fix_location": "dialogue_dataset.py:_naturalize_default",
            "fix_code": "# 已通过降低概率修复",
        },
    }
    
    def __init__(self):
        self.error_counts = Counter()
        self.patches_applied = []
        self._load()
    
    def detect_error(self, text):
        """检测文本中的错误模式"""
        found = []
        for name, info in self.ERROR_PATTERNS.items():
            if re.search(info["pattern"], text):
                found.append(name)
                self.error_counts[name] += 1
        return found
    
    def check_and_heal(self, recent_errors):
        """如果某类错误频繁出现，自动生成修复建议"""
        patches = []
        for name, count in self.error_counts.items():
            if count >= 3 and name not in self.patches_applied:
                info = self.ERROR_PATTERNS[name]
                patches.append({
                    "error": name,
                    "desc": info["fix_desc"],
                    "file": info["fix_location"],
                    "suggested_fix": info["fix_code"],
                    "occurrence_count": count,
                })
                self.patches_applied.append(name)
        
        if patches:
            self._save_patches(patches)
        return patches
    
    def _save_patches(self, patches):
        path = os.path.join(META_DIR, "patches.json")
        existing = []
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        existing.extend(patches)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(existing[-20:], f, ensure_ascii=False, indent=2)
    
    def _load(self):
        pass


# ===== 元脑主控 =====
class MetaBrain:
    """AI的自我意识——统一管理LLM、Prompt、修复"""
    
    def __init__(self):
        self.llm_mode = LLMModeManager()
        self.llm_mode.current_mode = "qwen"  # 尝试LLM，崩了自动降级
        self.prompt_evo = PromptEvolver()
        self.healer = SelfHealer()
        self.total_generations = 0
        self.last_crash_time = 0  # 防崩保护
    
    def generate_speech(self, player_context, game_context, is_public=False):
        """智能生成发言——自动选择最佳后端，全程防崩"""
        # 防崩保护：如果10秒内崩过，暂时关闭LLM
        if time.time() - self.last_crash_time < 60:
            return None
        
        # 尚未成功调用过LLM → 极低概率试探
        if self.llm_mode.total_llm_calls == 0:
            if random.random() >= 0.05:  # 5%概率首调
                return None
        
        use_llm = self.llm_mode.should_use_llm()
        
        if use_llm and is_available():
            best_prompt = self.prompt_evo.get_best_prompt()
            
            from .llm_brain import PRIVATE_PROMPT, PUBLIC_PROMPT
            template = PUBLIC_PROMPT if is_public else PRIVATE_PROMPT
            try:
                prompt = template.format(**player_context)
            except (KeyError, AttributeError):
                return None
            
            try:
                result = generate_text(best_prompt, prompt, max_tokens=120, temperature=0.9)
            except Exception:
                self.last_crash_time = time.time()
                self.llm_mode.record_template_fallback()
                return None
            
            if result:
                quality = score_llm_output(result, player_context.get("partner_msg", ""))
                self.llm_mode.record_llm_result(quality)
                self.prompt_evo.record_result(best_prompt, quality)
                
                if quality < 30:
                    self.llm_mode.record_template_fallback()
                    return None
                
                return result
            else:
                self.llm_mode.record_template_fallback()
        
        return None  # 回退到模板系统
    
    def post_game_analysis(self, game_record):
        """每局结束后的综合分析+升级"""
        # 检测高频错误
        all_texts = []
        for tk, msgs in game_record.get("private_chat_history", {}).items():
            for m in msgs:
                if m.get("speaker") != "__day__":
                    all_texts.append(m.get("text", ""))
        
        for text in all_texts:
            errors = self.healer.detect_error(text)
        
        # 检查是否需要自动修复
        patches = self.healer.check_and_heal(all_texts[-20:])
        if patches:
            print(f"[MetaBrain] 🔧 检测到{len(patches)}类重复错误，已生成修复建议")
        
        # 每20局进化prompt
        self.total_generations += 1
        if self.total_generations % 20 == 0:
            new_variants = self.prompt_evo.evolve()
            print(f"[MetaBrain] 🧬 Prompt进化第{self.prompt_evo.generation}代，产出{len(new_variants)}个新变体")
        
        return patches
    
    def get_status(self):
        return {
            "llm": self.llm_mode.get_status(),
            "prompt_gen": self.prompt_evo.generation,
            "total_generations": self.total_generations,
            "error_counts": dict(self.healer.error_counts),
        }


# 全局单例
_brain = None

def get_brain():
    global _brain
    if _brain is None:
        _brain = MetaBrain()
    return _brain
