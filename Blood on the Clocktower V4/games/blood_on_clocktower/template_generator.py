"""
模板生成器 — 通过碎片化组合产生海量变体，避免硬编10000条
每个模板类别可从几百个基础片段组合出上万种变体
"""
import random

# ====== 好人私聊开场片段 ======
GOOD_OPEN_PREFIX = [
    "你好{listener}，私聊时间不多，直接聊正事——",
    "{listener}，趁现在私聊，我有个想法想跟你讨论——",
    "嗨{listener}，时间有限我们快速对一下——",
    "{listener}你好，我有几个观察想跟你确认——",
    "嘿{listener}，想找你聊一下局势，特别是关于——",
    "{listener}，正好私聊，我需要一个判断——",
]

GOOD_OPEN_TOPIC = [
    "你觉得目前场上最该优先排查的是谁？",
    "你现在的怀疑对象是谁？有没有具体理由？",
    "你有没有注意到某些人的发言轨迹不太对？",
    "你对{target}怎么看？我有些观察但想听听你的判断。",
    "目前{claim_str}里谁最让你不安？",
    "你有确认过的信息吗？我们能交叉验证一下。",
    "我注意到一些细节，但想先听听你的角度——你先说我再补充。",
    "你觉得今天的局势走向怎么样？好人应该集中火力往哪个方向打？",
]

GOOD_OPEN_GUARDED = [
    "先不说我自己的身份——你先说说你的分析和怀疑对象。",
    "我不先交底牌，但我想听听你的判断，看我们能不能同路。",
    "我们互不先报身份，光聊线索——你最近观察到什么不对劲的？",
    "安全起见我们先不互相暴露身份，只聊推理。你那边有什么发现？",
]

# ====== 好人讨论核心片段 ======
GOOD_OBSERVE = [
    "我注意到{target}有个细节——",
    "仔细观察{target}的行为模式，你会发现——",
    "我复盘了{target}这几轮的发言，有个规律——",
    "你有没有觉得{target}在面对质疑时——",
    "{target}在公聊的表现让我一直在留意——",
    "比较{target}和其他人的互动频率——",
    "我对比了{target}在不同轮次的发言密度——",
    "{target}和{other}之间的互动方式挺奇怪的——",
]

GOOD_REASONING = [
    "他作为{claim}，按理说应该主动对信息、验证身份，但他全程在回避这一步。",
    "信息位被深入追问时应该越说越清楚，但他反着来——越问越模糊，底气不够。",
    "他的发言一直只跟评不主动提方向，不像有独立判断——更像在降低存在感。",
    "身为{claim}，正常会找其他信息位交叉验证，但他全程没找过任何人。",
    "每次有人点名问他{claim}的细节，他都会绕到其他人身上，这个回避模式很可疑。",
    "真信息位被人问查验结果时会有明确数据，他每次都说'我还需要再观察'——持续观察可以，但不能永无结论。",
    "好人的发言会有犹豫和修正，他的发言反而太完美——太一致的东西往往不真实。",
    "他在被不同人问同一个问题时，回答几乎一字不差，像是准备好的——真人不会这么整齐。",
    "作为一个有独立信息来源的人，他的立场不应该完全跟着舆论走。",
    "如果他真的知道自己是{claim}，那他现在最该做的事不是自保，而是帮好人缩小范围。",
]

GOOD_CONCLUSION = [
    "所以我倾向于{target}是第一优先级。你同意还是觉得我忽略了什么？",
    "综合这几个点，{target}是我目前最怀疑的人。你有反驳的角度吗？",
    "我觉得至少应该让他今天站出来把{contradict_str}解释清楚——不解释就是默认有鬼。",
    "我不是说一定是坏人，但他的行为跟真{claim}的表现确实有差距，值得重点关注。",
    "如果{target}翻出来是好人，我们再从保他的人里反推——风险评估是可控的。",
    "你的判断呢？独立来说——我想确认我们两个的结论是不是独立的。",
    "先不急投票，再观察一轮也行。但如果他明天还拿不出新信息，就别犹豫了。",
]

# ====== 好人交叉验证片段 ======
GOOD_CROSS_PREFIX = [
    "我相信信息位之间应该互相验证——",
    "我们各有各的信息源，如果能对上就铁了——",
    "两条独立信息线交叉，说服力远超单人直觉——",
    "我不会先暴露我查到的全部，但可以先对范围——",
    "我们做个安全的信息交换——",
]

GOOD_CROSS_METHOD = [
    "你先说你查过的人里有没有包含{target}？有的话我们就有交集。",
    "我不需要你的完整结果，只要点头或者摇头——你查过{other}吗？",
    "我们分别说一个自己最有把握的判断，看看能不能互相印证。",
    "我提示一个方向：{target}和{other}，你查过其中任何一个吗？",
    "如果我们都指向同一个人，那他就不是嫌疑人了——是铁狼。",
]

# ====== 好人要求实锤片段 ======
GOOD_EVIDENCE_PREFIX = [
    "等一下，你说{target}有问题——",
    "我先打断一下——你刚才说{target}可疑——",
    "我尊重你的判断，但在跟票之前我得确认——",
    "好的，你的怀疑我收到了。但我需要一点额外的信息——",
]

GOOD_EVIDENCE_ASK = [
    "具体是他哪句话让你觉得不对劲？公聊第几轮说的？我去翻翻。",
    "你是靠技能查到的还是纯观察推理的？这两种情况判断标准不一样。",
    "有没有投票记录或者发言时间点可以指给我？口说无凭。",
    "如果是技能结果，你能说范围就行——如果是推理，我需要具体行为。",
    "你能举一个他言行不一致的具体例子吗？光说'发言有问题'我无法判断。",
]

# ====== 好人金水信任片段 ======
GOOD_TRUST_PREFIX = [
    "好，你的信息和我这边对上了——",
    "确认了，你的查验结果跟我的没有冲突——",
    "验证通过——",
]

GOOD_TRUST_CONFIRM = [
    "从这刻开始我信你是自己人。后面你要什么信息我配合。",
    "金水关系成立。对方要冲你的时候我会保你，你也记得保我。",
    "现在开始我们的信息可以共享。但我有一个条件：新发现第一时间通知对方。",
    "接下来我们分头盯人：你盯{target}，我盯{other}，每天对一次进度。",
]

# ====== 邪恶私聊内部分工片段 ======
EVIL_PLAN_PREFIX = [
    "{listener}，我盘了一下局面——",
    "来对一下战术。我看了一圈——",
    "速聊，我有个想法——",
    "{listener}，想跟你同步一下我的判断——",
    "私聊时间紧，直接说重点——",
]

EVIL_PLAN_TARGET = [
    "{target}是当前最大的威胁——他的{claim}身份信息量太大了。",
    "我越来越觉得{target}必须优先处理——他如果是真的{claim}，我们后面很难打。",
    "从信息输出来看，{target}的威胁排在第一位。",
    "{target}和{other}，我个人倾向先处理{target}——理由是他查的东西跟我们有关。",
]

EVIL_PLAN_COORD = [
    "我建议我们分开角度：你从{listener_fake}的方向分析，我以{my_fake}的视角补充——两个独立来源更有说服力。",
    "公私两线走：公聊上你从{listener_fake}的视角轻微质疑一下，我从{my_fake}的立场呼应；晚上我们优先处理{target}。",
    "顺序很重要：你先在公聊抛一个方向，别直接点名——等好人自发怀疑了，我再'顺着分析'介入。先点后铺。",
    "别同时出击，容易被看出配合。你第一轮先低调观察，等我发完言你再表态——节奏拉开，看起来像独立判断。",
    "如果今天推不掉{target}，转攻{other_target}——备选方案要提前准备好，不能临时换人显得慌乱。",
]

# ====== 邪恶对外伪装片段 ======
EVIL_FAKE_PREFIX = [
    "说实话，我一直在关注{target}——",
    "我想跟你聊一个不太舒服的观察——",
    "有个细节你可能没注意到——",
    "我本来不想说的，但越想越不对劲——",
    "我觉得我们应该谈谈{target}——",
]

EVIL_FAKE_OBSERVE = [
    "他的发言节奏有个微妙的规律：每次有人被集火前他都会提前淡化那个人的嫌疑，像在为自己的同伙铺路。",
    "他全程只踩那些已经被质疑过的人，从不主动指出新目标——不像是独立判断，更像在跟着舆论走。",
    "你仔细看他被问到{claim}身份时的小动作——总是先沉默几秒再回答，信息位对自己查验结果应该脱口而出才对。",
    "{target}跟每个人的私聊内容几乎一模一样，我分别问了两个人，他们对他的说法高度重合——真信息位不会对不同人说同样的话。",
    "他的投票总是最后一个，而且从不自己起头——怎么看都是在看风向再决定。",
]

EVIL_FAKE_SOFTEN = [
    "当然这不是铁证，我只是在观察趋势——",
    "我不确定，所以想听听你的判断——两个人判断总比一个人准。",
    "可能是我多心了，但如果不止我一个人有这种感觉，就值得关注了。",
    "单看一个点不说明什么，但这几个点串在一起概率就高了。",
    "我不会只靠这一点就咬死他，但加上其他的观察，确实值得盘。",
]

# ====== 邪恶应变反制片段 ======
EVIL_COUNTER_PREFIX = [
    "情况不对，{target}开始反击了——",
    "风向变了，我们需要调整——",
    "不好，好人的怀疑方向开始往我们这边偏了——",
    "时间不多了，我们快速重新对齐一下——",
]

EVIL_COUNTER_ACTION = [
    "你公聊先质疑{other_target}，把火力引开——说他跟{target}有私下互保的嫌疑。",
    "我去公聊假装'突然发现'{target}的一个矛盾点，把话题从他身上转移到别处。",
    "我们都别直接回应质疑——反问对方'你有什么实锤证据'，把举证压力还给好人。",
    "Plan B启动：如果我被盯上了，你立刻表态'我早就觉得{listener}有问题'，假装你不是我同伙。",
    "如果今天实在挡不住，做好最坏打算——你我之间至少留一个活口继续带队。",
]

# ====== 好人公聊推理片段 ======
GOOD_PUBLIC_PREFIX = [
    "大家好，我有几个观察想分享——",
    "我盘了一下目前的信息——",
    "大家先别急着投票，听我说一个方向——",
    "我想提出一个各位可能没注意到的角度——",
    "综合目前的公开信息——",
]

GOOD_PUBLIC_REASON = [
    "{target}的{claim}身份声明有逻辑缺口——{contradict_str}。如果他是真的，这几个点应该能解释通。",
    "对比{target}和其他信息位的发言质量——其他{claim}型角色的信息输出有犹豫有修正，他的太整齐了。",
    "如果厨师的0相邻信息没错，结合{target}的座位和身份声明，他的位置非常尴尬。不是巧合这么简单。",
    "我建议今天集中火力推{target}——不是因为我确定，而是因为他身上的信息矛盾最多，处决他能验证最多东西。",
    "从目前的死亡顺序和处决结果反推，{target}的收益是最大的——每一次好人死掉，他的生存空间就大一圈。",
]

# ====== 好人投票统筹片段 ======
GOOD_VOTE_COORD = [
    "今天的投票策略：统一投{target}。",
    "我建议今天集中票力处决{target}——",
    "票型统一很重要，如果分散了邪恶就能捡漏——",
    "我们今天就打{target}这个点，不要分票——",
    "归票{target}。理由我一会公聊展开说——",
]

GOOD_VOTE_REASON = [
    "他的身份矛盾是全场最多的，翻出他是好人也不亏——能排除一整条线。",
    "从投票记录反推，保护他的人和他之间很可能有同伙关系。",
    "风险是可控的：即使翻出是好人，处决他验证的信息量比处决别人大。",
    "不投他的人就是下一个排查目标——今天统一票型也能帮我们定位邪恶。",
]

# ====== 组合生成函数 ======
def _gen_good_private_open():
    prefix = random.choice(GOOD_OPEN_PREFIX)
    topic = random.choice(GOOD_OPEN_TOPIC + GOOD_OPEN_GUARDED)
    return prefix + " " + topic

def _gen_good_private_discuss():
    obs = random.choice(GOOD_OBSERVE)
    reason = random.choice(GOOD_REASONING)
    concl = random.choice(GOOD_CONCLUSION)
    return obs + " " + reason + " " + concl

def _gen_good_cross_ref():
    pre = random.choice(GOOD_CROSS_PREFIX)
    method = random.choice(GOOD_CROSS_METHOD)
    return pre + " " + method

def _gen_good_demand_evidence():
    pre = random.choice(GOOD_EVIDENCE_PREFIX)
    ask = random.choice(GOOD_EVIDENCE_ASK)
    return pre + " " + ask

def _gen_good_trust_confirm():
    pre = random.choice(GOOD_TRUST_PREFIX)
    conf = random.choice(GOOD_TRUST_CONFIRM)
    return pre + " " + conf

def _gen_evil_plan():
    pre = random.choice(EVIL_PLAN_PREFIX)
    target = random.choice(EVIL_PLAN_TARGET)
    coord = random.choice(EVIL_PLAN_COORD)
    return pre + " " + target + " " + coord

def _gen_evil_fake():
    pre = random.choice(EVIL_FAKE_PREFIX)
    obs = random.choice(EVIL_FAKE_OBSERVE)
    soft = random.choice(EVIL_FAKE_SOFTEN)
    return pre + " " + obs + " " + soft

def _gen_evil_counter():
    pre = random.choice(EVIL_COUNTER_PREFIX)
    action = random.choice(EVIL_COUNTER_ACTION)
    return pre + " " + action

def _gen_good_public():
    pre = random.choice(GOOD_PUBLIC_PREFIX)
    reason = random.choice(GOOD_PUBLIC_REASON)
    return pre + " " + reason

def _gen_good_vote():
    coord = random.choice(GOOD_VOTE_COORD)
    reason = random.choice(GOOD_VOTE_REASON)
    return coord + " " + reason

# ====== 批量生成入口 ======
GENERATORS = {
    "GOOD_PRIVATE_OPEN_GEN": _gen_good_private_open,
    "GOOD_PRIVATE_DISCUSS_GEN": _gen_good_private_discuss,
    "GOOD_CROSS_REFERENCE_GEN": _gen_good_cross_ref,
    "GOOD_DEMAND_EVIDENCE_GEN": _gen_good_demand_evidence,
    "GOOD_TRUST_CONFIRM_GEN": _gen_good_trust_confirm,
    "EVIL_PLAN_GEN": _gen_evil_plan,
    "EVIL_FAKE_GEN": _gen_evil_fake,
    "EVIL_COUNTER_GEN": _gen_evil_counter,
    "GOOD_PUBLIC_REASONING_GEN": _gen_good_public,
    "GOOD_VOTE_GEN": _gen_good_vote,
}

def generate(category, count=10):
    """生成count条该类别变体模板"""
    gen = GENERATORS.get(category)
    if not gen:
        return []
    return [gen() for _ in range(count)]
