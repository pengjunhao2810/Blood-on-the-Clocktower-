"""
人格系统 V2 - 4种鲜明性格，影响句式/词汇/长度/推理风格/情绪
"""

import random
import threading

_thread_local = threading.local()

def set_current_personality(p):
    _thread_local.current = p

def get_current_personality():
    return getattr(_thread_local, 'current', None)

PERSONALITY_TYPES = {
    "冲动型": {
        "traits": ["直率", "情绪化", "行动派", "大胆", "易怒"],
        "sentence_len": 0.7,
        "exclamation_rate": 0.4,
        "emoji": "",
        "style_note": "句子短、语气强、常用感叹号，被怀疑时立刻反击",
        "filler_words": ["我直接说了", "别绕弯子", "我敢肯定", "明摆着的事", "这还用想？"],
        "accusative_words": ["绝对是", "明摆着", "铁定是", "不可能有错", "百分之百"],
        "emotional_call": ["你慌什么？", "解释清楚！", "别转移话题！", "正面回答！"],
        "doubt_expr": ["不对劲", "有问题", "太假了", "编得也太次了"],
        "defensive": ["你凭什么这么说？", "拿出证据来！", "别血口喷人！", "你才是有问题的那个！"],
        "certainty": 0.85,
        "reasoning_style": "conclusion_first",
    },
    "冷静型": {
        "traits": ["理性", "客观", "沉稳", "逻辑性强", "有条理"],
        "sentence_len": 1.3,
        "exclamation_rate": 0.05,
        "emoji": "",
        "style_note": "列点分析(第一第二第三)，引用投票记录和发言事实",
        "filler_words": ["从逻辑上看", "理性分析的话", "综合现有信息", "客观来说", "基于已公开的信息"],
        "accusative_words": ["从证据看", "数据显示", "逻辑上存在矛盾", "合理的推断是", "概率上来说"],
        "emotional_call": ["我们来分析一下", "请看投票记录", "事实胜于雄辩", "用数据说话"],
        "doubt_expr": ["存在逻辑矛盾", "和已知信息不符", "行为模式异常", "缺乏合理解释"],
        "defensive": ["请拿出具体证据", "我们来理性讨论", "你的推论存在漏洞", "请正面回答我的问题"],
        "certainty": 0.7,
        "reasoning_style": "evidence_first",
    },
    "话痨型": {
        "traits": ["热情", "话多", "情绪外露", "爱分享", "发散"],
        "sentence_len": 1.6,
        "exclamation_rate": 0.2,
        "emoji": "",
        "style_note": "篇幅长、重复强调、喜欢讲故事、思维发散",
        "filler_words": ["我跟你们说啊", "真的假的？！", "我的天", "我觉得吧", "这个事情是这样的"],
        "accusative_words": ["我越想越不对", "你们不觉得奇怪吗", "让我捋一捋", "我跟你讲"],
        "emotional_call": ["大家听我说完！", "我还有话要说！", "你们听我分析！", "别打断我！"],
        "doubt_expr": ["这里面的问题大了", "这事儿没那么简单", "我觉得哪里不太对", "越想越觉得可疑"],
        "defensive": ["你们听我解释！", "我还没说完呢！", "事情不是你们想的那样！", "让我把话说完再判断！"],
        "certainty": 0.6,
        "reasoning_style": "story_first",
    },
    "新手型": {
        "traits": ["不确定", "犹豫", "易受影响", "谦虚", "跟随"],
        "sentence_len": 0.8,
        "exclamation_rate": 0.05,
        "emoji": "",
        "style_note": "大量不确定语气词(可能/大概/我不确定)，喜欢问别人意见",
        "filler_words": ["我不太确定", "可能是我理解错了", "我新手不太懂", "我想问问", "大家怎么看"],
        "accusative_words": ["会不会是", "有可能", "我猜", "感觉像是", "不太像好人"],
        "emotional_call": ["你们觉得呢？", "我该相信谁？", "谁能帮我分析一下？", "有点懵"],
        "doubt_expr": ["有点可疑", "不太对劲", "说不上来", "感觉怪怪的"],
        "defensive": ["我真的不是坏人", "我不知道该怎么解释", "大家相信我", "我没有撒谎"],
        "certainty": 0.35,
        "reasoning_style": "question_first",
    }
}

class Personality:
    def __init__(self, preassigned_type=None):
        if preassigned_type and preassigned_type in PERSONALITY_TYPES:
            self.type_name = preassigned_type
        else:
            self.type_name = random.choice(list(PERSONALITY_TYPES.keys()))
        traits = PERSONALITY_TYPES[self.type_name]
        for k, v in traits.items():
            setattr(self, k, v)

    def apply_to_text(self, text):
        return self.render(text)

    def render(self, text, emotion=None):
        if not text or len(text.strip()) < 2:
            return text
        t = PERSONALITY_TYPES[self.type_name]
        r = random.random()

        # 开头插入性格化语气词
        if r < 0.30:
            opener = random.choice(t["filler_words"])
            text = f"{opener}，{text[0].lower() if text else ''}{text[1:] if len(text) > 1 else ''}"

        # 句子长度调整 - 短句截断 / 长句不处理
        mod = t["sentence_len"]
        if mod < 0.9 and len(text) > 80 and random.random() < 0.3:
            # 冲动/新手：缩短
            text = _shorten(text)
        elif mod > 1.3 and len(text) < 60 and random.random() < 0.3:
            # 话痨：拉长
            text = _lengthen(text)

        # 感叹号频率
        if t["exclamation_rate"] > 0.2 and random.random() < t["exclamation_rate"]:
            text = text.replace("。", "！")
            if text.endswith("。"):
                text = text[:-1] + "！"

        # 情绪修饰
        if emotion == "defensive":
            if random.random() < 0.5:
                text = f"{random.choice(t['defensive'])}{' ' if text else ''}{text}"
        elif emotion == "confident":
            if random.random() < 0.4:
                text = f"{random.choice(t['accusative_words'])}，{text}"
        elif emotion == "uncertain":
            if self.certainty < 0.5 or random.random() < 0.3:
                text = f"我不太确定……{text}"

        # 结尾语气词（话痨/新手偏好）
        if self.type_name in ("话痨型", "新手型") and random.random() < 0.25:
            ending = random.choice(["吧", "啊", "呢", "哦"])
            if text.rstrip()[-1] in "！。？":
                text = text.rstrip()[:-1] + f"{ending}。"
        elif self.type_name == "冲动型" and random.random() < 0.2:
            if text.rstrip()[-1] in "。！？":
                text = text.rstrip()[:-1] + "！"

        return text

    def describe(self):
        return f"[Personality:{self.type_name}|{self.style_note}]"

    def pick_phrase(self, category):
        t = PERSONALITY_TYPES[self.type_name]
        pool = t.get(category, [])
        return random.choice(pool) if pool else ""

def _shorten(text):
    parts = [s for s in text.replace("？", "？。").replace("！", "！。").split("。") if s.strip()]
    if len(parts) > 3:
        return "。".join(parts[:3]) + "。"
    return text

def _lengthen(text):
    extras = ["其实吧", "这个", "怎么说呢", "让我想想"]
    if "。" in text:
        first, rest = text.split("。", 1)
        if random.random() < 0.5:
            ins = random.choice(extras)
            text = f"{first}。{ins}，{rest}"
    repeats = ["还有啊", "再补充一点", "另外呢"]
    if random.random() < 0.4:
        text = f"{text.rstrip('。')}。对了{random.choice(repeats)}，{_pick_detail()}"
    return text

def _pick_detail():
    details = [
        "我觉得我们要多观察几轮",
        "不知道大家注意到没有，他的发言有几个地方很奇怪",
        "这事儿我得捋一捋，感觉没那么简单",
        "不过他也有可能是好人，这个可能性不能排除",
        "但说真的，现在下结论确实有点早",
    ]
    return random.choice(details)

def assign_personality(agent):
    if not hasattr(agent, '_personality'):
        agent._personality = Personality()
    return agent._personality

def apply_personality(agent, text, emotion=None):
    p = assign_personality(agent)
    return p.render(text, emotion)
