"""LLM 填充 — HTTP调用独立推理服务，不阻塞游戏"""
import urllib.request, json

LLM_URL = "http://127.0.0.1:8765"

def is_available():
    """检查LLM服务是否就绪"""
    try:
        r = urllib.request.urlopen(f"{LLM_URL}/", timeout=2)
        data = json.loads(r.read())
        return data.get("ready", False)
    except:
        return False

def generate_text(system_prompt, user_prompt, max_tokens=100, temperature=0.9):
    """通过HTTP调用LLM服务生成文本"""
    try:
        data = json.dumps({
            "system": system_prompt,
            "user": user_prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode('utf-8')
        req = urllib.request.Request(f"{LLM_URL}/generate", data=data,
                                      headers={"Content-Type": "application/json"})
        r = urllib.request.urlopen(req, timeout=15)
        result = json.loads(r.read())
        text = result.get("text", "")
        return text if len(text) >= 5 else None
    except:
        return None
