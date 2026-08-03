"""
LLM 填充模块 — 为对话生成器提供自然语言推理能力
懒加载 Qwen2-VL-2B，失败时返回 None 自动降级
"""
from __future__ import annotations
import os, sys, time, random
import threading

_MODEL = None
_TOKENIZER = None
_LOADED = False
_LOCK = threading.Lock()
_LAST_OUTPUT = [""]
_SAME_COUNT = [0]


def _find_model_path():
    """搜索 Qwen2-VL 模型位置（已知路径优先）"""
    # 已知确切路径（最快）
    known = "F:/AI调试/测试代码放置区域/models/Qwen/Qwen2-VL-2B-Instruct"
    if os.path.isfile(os.path.join(known, "config.json")):
        return known
    # 相对路径推算
    rel = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                       "AI调试", "测试代码放置区域", "models", "Qwen", "Qwen2-VL-2B-Instruct")
    if os.path.isfile(os.path.join(rel, "config.json")):
        return os.path.abspath(rel)
    # 备用：在 F:\AI调试 下搜索（限一层）
    base = "F:/AI调试/测试代码放置区域/models/Qwen"
    if os.path.isdir(base):
        for name in os.listdir(base):
            p = os.path.join(base, name)
            if os.path.isfile(os.path.join(p, "config.json")) and "Qwen2-VL" in name:
                return p
    return None


def _ensure_model():
    global _MODEL, _TOKENIZER, _LOADED
    if _LOADED:
        return True
    with _LOCK:
        if _LOADED:
            return True
        path = _find_model_path()
        if not path:
            return False
        try:
            from transformers.models.qwen2_vl import Qwen2VLForConditionalGeneration
            from transformers import AutoTokenizer
            _load_start = time.time()
            _TOKENIZER = AutoTokenizer.from_pretrained(path, trust_remote_code=True, local_files_only=True)
            _MODEL = Qwen2VLForConditionalGeneration.from_pretrained(
                path, trust_remote_code=True,
                torch_dtype="auto", device_map="auto", local_files_only=True,
            )
            _LOADED = True
            print(f"[LLM Filler] Qwen2-VL 模型加载完成 ({round(time.time()-_load_start, 1)}s)")
            return True
        except Exception as e:
            print(f"[LLM Filler] 模型加载失败: {e}")
            return False


def generate_text(system_prompt: str, user_prompt: str,
                  max_tokens: int = 100, temperature: float = 0.85) -> str | None:
    if not _ensure_model():
        return None

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    text = _TOKENIZER.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = _TOKENIZER([text], return_tensors="pt").to(_MODEL.device)

    t0 = time.time()
    try:
        outputs = _MODEL.generate(
            **inputs, max_new_tokens=max_tokens,
            temperature=temperature, top_p=0.9,
            do_sample=True, pad_token_id=_TOKENIZER.eos_token_id,
        )
        elapsed = time.time() - t0
        response = _TOKENIZER.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        response = (response.replace("<|im_end|>", "").replace("<|im_start|>", "").strip()
                    .replace("。", "。").replace("，", "，"))
        if not response:
            return None
        # 防重复：连续相同输出则升温重试
        if response == _LAST_OUTPUT[0] and _SAME_COUNT[0] < 2:
            _SAME_COUNT[0] += 1
            return generate_text(system_prompt, user_prompt, max_tokens, min(temperature + 0.3, 1.2))
        _LAST_OUTPUT[0] = response
        _SAME_COUNT[0] = 0
        return response
    except Exception:
        return None


def is_available():
    return _ensure_model()
