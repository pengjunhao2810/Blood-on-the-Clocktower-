"""
LLM 角色扮演 — 精简版Prompt，适配1.5B小模型
"""
from .llm_filler import generate_text, is_available
from .roles import BOTC_ROLES
import re

SYSTEM_PROMPT = ""  # Qwen2.5不使用system prompt（导致拒绝角色扮演），直接在user message中引导

PRIVATE_PROMPT = """【桌游时间】你正在玩血染钟楼，和{listener}私聊。请用中文回复他一句话（20-60字），先回应他的话再输出你的判断。

你的角色：{role_info}
你知道：{my_knowledge}
存活：{alive}
已死：{dead}
对方说：{partner_msg}

你的回复："""

PUBLIC_PROMPT = """公聊发言。
你的角色：{role_info}
已知：{my_knowledge}
场上存活：{alive}  已死：{dead}
今天投票目标：{vote_target}
请发言："""

def build_llm_context(player, game, listener=None):
    name = player.name
    role = player.role
    gs = player.game_state
    info = gs.get("known_info", {})
    effective_role = gs.get("fake_role", role) if gs.get("is_drunk") else role
    team = BOTC_ROLES.get(role, {}).get("team", "")
    
    # 精简角色信息
    if team in ("demon", "minion"):
        demon = info.get("demon", "")
        mins = info.get("minions", [])
        allies = [n for n in [demon]+mins if n and n != name]
        role_info = f"真实身份{role}，伪装成{gs.get('public_claim', effective_role)}，队友{'、'.join(allies)}" if allies else f"真实身份{role}，伪装成{gs.get('public_claim', effective_role)}"
    elif gs.get("is_drunk"):
        role_info = f"你以为是{effective_role}（实际是酒鬼）"
    else:
        role_info = f"{role}（{team}）"
    
    # 精简知识
    knowledge = []
    if "seer" in info:
        ch, has = info["seer"]
        targets = ch if isinstance(ch,(list,tuple)) else [ch]
        knowledge.append(f"查验{'和'.join(targets)}={'有恶魔' if has else '无恶魔'}")
    if "chef" in info:
        knowledge.append(f"邪恶相邻数={info['chef']}")
    if "investigator" in info:
        inv = info["investigator"]
        knowledge.append(f"调查{inv[0]}和{inv[1]}中有{inv[2]}")
    if "washerwoman" in info:
        ww = info["washerwoman"]
        if len(ww)==3:
            knowledge.append(f"洗衣妇：{ww[0]}或{ww[1]}是{ww[2]}")
    if "empathy" in info:
        knowledge.append(f"邻座邪恶数={info['empathy']}")
    if "demon" in info and team=="minion":
        knowledge.append(f"恶魔是{info['demon']}")
    if "minions" in info and team=="demon":
        knowledge.append(f"爪牙是{'、'.join(info['minions'])}")
    
    # 存活/死亡
    alive_names = [a.name for a in game.registry.all_alive()]
    alive_str = "、".join(alive_names[:8])
    dead_str = "、".join(game.dead_players[:5]) or "无"
    
    # 对方消息
    partner_msg = ""
    listener_name = "" 
    if listener:
        listener_name = listener if isinstance(listener, str) else listener.name
        chat_mem = gs.get("chat_memory", [])
        for m in reversed(chat_mem):
            if m.get("speaker") == listener_name and m.get("phase") == "private_chat":
                partner_msg = m.get("text", "")
                break
    
    # 投票目标
    sus = gs.get("suspicion", {})
    vote_target = max(sus, key=sus.get) if sus else "未定"
    
    return {
        "listener": listener_name,
        "role_info": role_info,
        "my_knowledge": "；".join(knowledge) if knowledge else "暂无",
        "alive": alive_str,
        "dead": dead_str,
        "partner_msg": partner_msg if partner_msg else "（首次对话，无历史）",
        "vote_target": vote_target,
    }

def generate_private_chat(player, game, listener):
    if not is_available(): return None
    ctx = build_llm_context(player, game, listener)
    prompt = PRIVATE_PROMPT.format(**ctx)
    result = generate_text(SYSTEM_PROMPT, prompt, max_tokens=80, temperature=0.85)
    if result and len(result)>=5:
        result = validate_output(result, ctx)
        return result
    return None

def generate_public_chat(player, game):
    if not is_available(): return None
    ctx = build_llm_context(player, game)
    prompt = PUBLIC_PROMPT.format(**ctx)
    result = generate_text(SYSTEM_PROMPT, prompt, max_tokens=80, temperature=0.85)
    if result and len(result)>=5:
        result = validate_output(result, ctx)
        return result
    return None

def validate_output(text, ctx):
    """轻量校验：只修复明确bug"""
    # 清理空话
    text = text.replace('重合度最高的嫌疑人——。', '')
    text = text.replace('理由在。', '')
    # 确保不是空
    if len(text) < 3:
        return None
    return text
