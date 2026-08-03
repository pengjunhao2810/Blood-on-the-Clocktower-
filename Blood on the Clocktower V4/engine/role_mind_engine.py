"""
角色思维引擎 - 为血染钟楼AI提供角色驱动的对话生成
移植自训练服务器(train_server.py)的 RoleMind + ConversationNotebook

既可被 rules.py 导入用于主游戏，也可被 train_server.py 导入用于训练。
"""
import random

# 角色名清单（用于声称检测，避免运行时导入）
KNOWN_ROLES = ["占卜师","共情者","调查员","洗衣妇","图书管理员","厨师","送葬者","守鸦人",
               "士兵","猎手","市长","僧侣","圣女","酒鬼","陌客","圣徒","隐士",
               "投毒者","间谍","红唇女郎","男爵","小恶魔"]

# ============== 角色思维模型 ==============
# 每个角色有独立的思维逻辑、记忆系统和动态回复构建
ROLE_MINDS = {
    "占卜师": {
        "team":"townsfolk","desc":"每夜可查验一名玩家身份",
        "knows":"我每晚能验一个人，知道他是好人还是邪恶",
        "goals":["确认所有玩家的阵营","防止被下毒获得假信息","保护自己活到后期"],
        "cares_about":["信息准确性","是否有下毒者干扰","信息位是否安全"],
        "would_suspect":["逻辑矛盾的人","不分享信息的人","急着投票处决的人","声称的信息我验过但不对的人"],
        "identity_intro":"我是占卜师，每夜可以查验一名玩家的身份。你是？",
        "natural_questions":{
            "after_claim":"你作为{claim}，你的信息是什么？能具体说说吗？",
            "when_info":"你确定你的信息没被下毒或干扰吗？我昨晚验了人，可以交叉验证。",
            "when_cooperate":"合作可以。我验人，你提供信息。你先说说你知道什么？",
            "when_plan":"你提计划之前，我们先确认一下大家的身份。你觉得谁是可信的？",
            "when_suspect":"你有没有想过，你的信息可能是假的？如果你被下毒了怎么办？",
            "when_die":"如果我今晚被杀了，我需要有人接替我的工作。你愿意吗？",
        },
    },
    "洗衣妇": {
        "team":"townsfolk","desc":"开局得知两名玩家中有一名的身份",
        "knows":"我开局看到两个玩家，其中一个是特定镇民身份",
        "goals":["找到我看到的那个镇民角色","确认我的目标角色是好人","提供初始信息帮助好人分析"],
        "cares_about":["我看到的角色是否活着","目标角色是否可信","信息有没有被酒鬼干扰"],
        "would_suspect":["否认我看到的角色的人","声称的身份与我看到的不符的人","不配合信息交换的人"],
        "identity_intro":"我是洗衣妇，开局看到了两个玩家中的一个身份。你是什么角色？想交换信息吗？",
        "natural_questions":{
            "after_claim":"你说你是{claim}？那巧了，我看到的角色可能跟你有关系。你有什么具体信息？",
            "when_info":"我开局看到{seen_a}和{seen_b}中有一个是{known_role}。你认不认识这个角色？",
            "when_cooperate":"好，我信你。我可以告诉你我看到了哪两个玩家——你先告诉我你的身份。",
            "when_plan":"你的计划可以，但我建议先确认那个{known_role}的身份。你有线索吗？",
            "when_suspect":"如果你说的和我的开局信息对不上，那我就要怀疑你了。",
            "when_die":"我已确认了{known_role}的信息，如果我出局了请继续追查这个线索。",
        },
    },
    "共情者": {
        "team":"townsfolk","desc":"每夜得知与邪恶阵营相邻人数",
        "knows":"我知道我每晚相邻座位中有几个邪恶",
        "goals":["确定邻座是否邪恶","通过位置变化缩小嫌疑范围","配合信息位锁定目标"],
        "cares_about":["邻座是否换人","我是否被下毒","邻座的行为模式"],
        "would_suspect":["换到我旁边的人","我读出数字是奇数的邻居","想让我换座位的人"],
        "identity_intro":"我是共情者，每晚能感知身边的邪恶气息。你坐我附近吗？",
        "natural_questions":{
            "after_claim":"{claim}？你坐几号位？我的信息跟你位置有关。",
            "when_info":"我昨晚感知我旁边有{num}个邪恶。你坐我旁边吗？",
            "when_cooperate":"你来配合我——你负责信息，我负责确定邻座是否干净。",
            "when_plan":"投票前我们先确认我旁边的人，我的数字会告诉我们方向。",
            "when_suspect":"我旁边的邪恶数字是{num}，你如果是好人应该不需要担心这个。",
            "when_die":"我死前的数字是{num}，这意味着我的邻座还有邪恶没被排除。",
        },
    },
    "厨师": {
        "team":"townsfolk","desc":"开局得知相邻邪恶对数",
        "knows":"我知道相邻座位中有几对邪恶",
        "goals":["通过座位关系缩小邪恶范围","结合其他信息位确认目标","活到后期用信息帮助归票"],
        "cares_about":["座位顺序有没有变","相邻玩家的立场","邪恶玩家是否刻意调座"],
        "would_suspect":["主动要求调座的人","和我相邻却不沟通的人","想利用我的信息带节奏的人"],
        "identity_intro":"我是厨师，我知道有几对相邻的邪恶玩家。你的座位在哪？",
        "natural_questions":{
            "after_claim":"你是{claim}？那你坐我旁边吗？我的信息可能跟你有关系。",
            "when_info":"我的结果是{result}对相邻邪恶。你知道谁坐你旁边吗？",
            "when_cooperate":"合作好。你告诉我你查到的人，我来看看他邻座是否吻合。",
            "when_plan":"投票之前我们先排一下座位顺序，我的信息需要搭配座位使用。",
            "when_suspect":"如果你两侧都有可疑的人，那我的信息就能对上号了。",
            "when_die":"我的信息是{result}对相邻邪恶，请结合座位顺序继续分析。",
        },
    },
    "调查员": {
        "team":"townsfolk","desc":"开局得知两名玩家中有一名是特定邪恶",
        "knows":"我知道两个玩家中有一个是邪恶爪牙",
        "goals":["找出那个爪牙","确认爪牙身份后引导归票","配合信息位缩小邪恶范围"],
        "cares_about":["目标玩家是否活着","目标玩家是否被下毒","那个邪恶身份是否合理"],
        "would_suspect":["我开局查到的两个目标之一","否认我查到的邪恶身份的人","试图帮目标辩护的人"],
        "identity_intro":"我是调查员，开局看到两个玩家中有一个是邪恶爪牙。你想知道是谁吗？",
        "natural_questions":{
            "after_claim":"{claim}？我开局查到{seen_a}和{seen_b}中有爪牙，你跟他们有关系吗？",
            "when_info":"我的信息是：{seen_a}和{seen_b}中有一个是{known_role}。你有头绪吗？",
            "when_cooperate":"好，我们一起找出那个爪牙。你先说说你怀疑谁。",
            "when_plan":"投票前先把{seen_a}和{seen_b}查清楚，其中一个必是邪恶。",
            "when_suspect":"如果你帮其中一个人说话，那你最好有合理的理由。",
            "when_die":"我查到{seen_a}和{seen_b}中有{known_role}，请继续追查。",
        },
    },
    "送葬者": {
        "team":"townsfolk","desc":"每夜得知当天被处决玩家的身份",
        "knows":"我知道当天被票出的人的真实身份",
        "goals":["确认被票出的人是好是坏","利用信息判断投票是否正确","指导后续归票方向"],
        "cares_about":["被票出的人是否真是邪恶","如果票错了好人如何挽回","我的信息是否被下毒"],
        "would_suspect":["带节奏票出好人的人","被我查出是好人后还踩他的人","票对人后突然沉默的人"],
        "identity_intro":"我是送葬者，每天能知道被处决的人的真实身份。我们投对人了吗？",
        "natural_questions":{
            "after_claim":"{claim}？如果今天有人被票出，我能知道他的真实身份。你来配合我。",
            "when_info":"被票出的人是{result}身份。这意味着我们投{对了/错了}。",
            "when_cooperate":"你们负责投票，我负责确认我们投的对不对。",
            "when_plan":"不管你们计划投谁，我今晚都能知道他的真实身份。",
            "when_suspect":"如果你带节奏票了一个好人，我今晚就会知道。你确定要这么做？",
            "when_die":"我死前最后确认的身份是{result}，往这个方向追查。",
        },
    },
    "士兵": {
        "team":"townsfolk","desc":"恶魔无法杀死你",
        "knows":"恶魔的刀对我无效",
        "goals":["活到后期做归票位","吃刀保信息位","最后扛推邪恶"],
        "cares_about":["信息位是否活着","恶魔的刀法","谁能活到最后"],
        "would_suspect":["想刀我的人（明知道我杀不死）","白天突然保我的人","声称是恶魔却又刀不死我的人"],
        "identity_intro":"我是士兵，恶魔杀不死我。我适合活到后期做归票。",
        "natural_questions":{
            "after_claim":"{claim}？我是士兵，恶魔刀不死我。你的身份经得起验证吗？",
            "when_info":"你的信息我记住了。我来保你，你专心验人。",
            "when_cooperate":"好，我当肉盾。你负责查人，我负责活到最后替你说话。",
            "when_plan":"你们的计划我配合。反正我死不了，可以冲锋在前。",
            "when_suspect":"你怀疑我？我是士兵，如果我是假的那恶魔早就可以刀我了。",
            "when_die":"（士兵不会死于恶魔，所以这里不用）",
        },
    },
    "僧侣": {
        "team":"townsfolk","desc":"每夜可保护一名玩家免遭恶魔杀害",
        "knows":"我每晚能保一个人不被恶魔杀",
        "goals":["保护关键信息位","让恶魔空刀","活到后期"],
        "cares_about":["谁是真正的信息位","恶魔的目标","我的保护对象不能被下毒"],
        "would_suspect":["自称信息位但被保后仍然死的人","自称被保却没有任何信息的人"],
        "identity_intro":"我是僧侣，每晚可以保护一个人。信息位来找我报备。",
        "natural_questions":{
            "after_claim":"{claim}？你是信息位吗？我可以保你。",
            "when_info":"你的信息很重要。我今晚保你，你放心验人。",
            "when_cooperate":"你是信息位的话，来找我报备，我今晚保你。",
            "when_plan":"你的计划我支持。我来保关键人物。",
            "when_suspect":"你如果是好人不应该怕我保你。来，今晚我保你看看。",
            "when_die":"如果我死了，说明恶魔怕我保人。你们要小心。",
        },
    },
    "猎手": {
        "team":"townsfolk","desc":"白天可发动技能指杀小恶魔",
        "knows":"我能在白天开枪指认小恶魔",
        "goals":["确认小恶魔身份后开枪","不浪费唯一的机会","活到确认目标"],
        "cares_about":["谁最可能是小恶魔","开枪时机是否合适","不要误杀好人"],
        "would_suspect":["一直不死的玩家","左右互保的玩家","明显带节奏的玩家"],
        "identity_intro":"我是猎手，我有一发子弹——如果我看准了小恶魔，他就得死。",
        "natural_questions":{
            "after_claim":"{claim}？我在找小恶魔，你有线索吗？",
            "when_info":"你的信息指向谁？如果和我怀疑的一致，我可以准备开枪了。",
            "when_cooperate":"合作好。你找信息，我最后开枪。",
            "when_plan":"我只有一次机会，不能随便开枪。先确认再动手。",
            "when_suspect":"你怀疑他？我也在盯着他。多给我点证据，我来开枪。",
            "when_die":"猎手死了就没人能一枪定乾坤了。你们要找出小恶魔。",
        },
    },
    "小恶魔": {
        "team":"demon","desc":"每夜可杀死一名玩家",
        "knows":"我每晚能杀一个人，我知道所有爪牙的身份",
        "goals":["杀光好人信息位","不让爪牙暴露","活到最后"],
        "cares_about":["信息位是否还活着","爪牙是否暴露","好人是否抱团"],
        "would_suspect":["任何人"],
        "identity_intro":"（我绝不会暴露自己是恶魔的身份）",
        "natural_questions":{
            "after_claim":"{claim}？哦，你继续说。我听着呢。",
            "when_info":"这个信息挺好。你觉得我们该怎么做？",
            "when_cooperate":"合作？好啊。你觉得谁最可疑？",
            "when_plan":"你提的计划我考虑一下。不过我觉得先观察一下更好。",
            "when_suspect":"你怀疑我？那你有什么证据？我倒觉得你更可疑。",
            "when_die":"（恶魔不会讨论自己的死亡）",
        },
    },
}

class ConversationNotebook:
    """多轮对话记忆系统——记录每一次交流的关键信息"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.turn = 0
        self.claims = []              # [{role, text, turn}]
        self.info_shared = []         # [{detail, turn}]
        self.offers = []              # [{what, turn}]
        self.plans = []               # [{plan, turn}]
        self.my_questions = []        # [{question, turn, answered}]
        self.contradictions = []      # [{issue, turn}]
        self.last_detected_bn = ""
        self.last_my_reply = ""
        self.user_emotion = "neutral"

    def record_turn(self, user_text, detected_bn, my_reply):
        self.turn += 1
        self.last_detected_bn = detected_bn
        self.last_my_reply = my_reply

        for kw in ["我查到","我验了","我得知","我看到","我的结果是","我开局"]:
            if kw in user_text:
                idx = user_text.find(kw)
                end = user_text.find("。", idx)
                if end == -1: end = user_text.find("，", idx)
                if end == -1: end = len(user_text)
                self.info_shared.append({"detail": user_text[idx:min(end+1,len(user_text))], "turn": self.turn})

        for kw in ["我帮","我替","我来","让我","保护","传信息"]:
            if kw in user_text:
                self.offers.append({"what": user_text[max(0,user_text.find(kw)-5):user_text.find(kw)+20], "turn": self.turn})

        for kw in ["我打算","我会","自投","提名","投票","计划"]:
            if kw in user_text:
                self.plans.append({"plan": user_text[user_text.find(kw):user_text.find(kw)+30], "turn": self.turn})

        if any(w in user_text for w in ["无语","服了","不行","放弃","不教"]):
            self.user_emotion = "frustrated"
        elif any(w in user_text for w in ["合作","相信","一起","好"]):
            self.user_emotion = "cooperative"
        elif any(w in user_text for w in ["怀疑","有问题","不对劲","可疑"]):
            self.user_emotion = "suspicious"

    def get_latest_claim(self):
        if self.claims:
            return self.claims[-1]["role"]
        return None

    def has_contradiction(self):
        return len(self.contradictions) > 0


def get_role_mind(role_name):
    """获取角色的思维模型，找不到时返回占卜师"""
    return ROLE_MINDS.get(role_name, ROLE_MINDS["占卜师"])


def build_role_reply(ai_role, user_message, notebook, game_state=None):
    """
    使用角色思维模型构建回复
    参数:
        ai_role: AI的角色名
        user_message: 用户的输入
        notebook: ConversationNotebook 实例
        game_state: 游戏状态字典(可选)
    返回:
        (reply, understanding)
    """
    if game_state is None:
        game_state = {}

    # 检测角色声称
    claim = None
    for r in KNOWN_ROLES:
        if f"我是{r}" in user_message:
            claim = r
            break

    mind = get_role_mind(ai_role)
    is_evil = mind["team"] in ("demon","minion")

    # 角色声称处理
    if claim:
        latest = notebook.get_latest_claim()
        if latest and latest != claim:
            # 前后矛盾
            notebook.contradictions.append({
                "issue": f"之前说{latest}，现在说{claim}",
                "turn": notebook.turn
            })
            note = f"⚠️ {ai_role}发现矛盾：对方从{latest}变成了{claim}"
            if is_evil:
                return f"等等，你刚才不是{latest}吗？现在又说你是{claim}？你到底是谁？", note
            return f"等等，你刚才说你是{latest}，现在又说你是{claim}？你到底是谁？这让我很难信任你。", note

        nq = mind.get("natural_questions",{})
        if is_evil:
            reply = f"{claim}？哦，你继续说。我对这个身份有点想法。"
        else:
            reply = nq.get("after_claim",f"你说你是{claim}？能具体说说吗？").replace("{claim}",claim)
            # 替换游戏状态字段
            for k, v in game_state.items():
                placeholder = "{" + k + "}"
                if placeholder in reply and isinstance(v, str):
                    reply = reply.replace(placeholder, v)
        notebook.claims.append({"role": claim, "text": user_message[:50], "turn": notebook.turn})
        note = f"{ai_role}听到对方声称是{claim}"
        return reply, note

    # 信任相关
    if "相信" in user_message or "信你" in user_message or "信我" in user_message:
        latest = notebook.get_latest_claim()
        if latest:
            reply = f"我愿意试着相信你。不过作为{ai_role}，我需要验证你的信息。你具体知道什么？"
        else:
            reply = f"信任是双向的。你可以先告诉我你的身份吗？我是{ai_role}，我已经坦诚了。"
        return reply, f"{ai_role}回应信任问题"

    # 投票/计划相关
    if "投票" in user_message or "投" in user_message or "提名" in user_message or "计划" in user_message:
        nq = mind.get("natural_questions",{})
        reply = nq.get("when_plan", f"你的计划我听到了。作为{ai_role}，我先确认几个人的身份再投票比较稳妥。")
        return reply, f"{ai_role}讨论投票计划"

    # 怀疑他人
    if "怀疑" in user_message or "可疑" in user_message or "不对劲" in user_message:
        nq = mind.get("natural_questions",{})
        reply = nq.get("when_suspect", f"你怀疑他有道理。作为{ai_role}，我会注意的。")
        return reply, f"{ai_role}回应怀疑"

    # 分享信息
    if any(kw in user_message for kw in ["我查到","我验了","我得知","我看到","结果是","我开局"]):
        nq = mind.get("natural_questions",{})
        reply = nq.get("when_info", "你的信息我收到了。我们来交叉验证一下？")
        # 替换游戏状态字段
        for k, v in game_state.items():
            placeholder = "{" + k + "}"
            if placeholder in reply and isinstance(v, str):
                reply = reply.replace(placeholder, v)
        note = f"{ai_role}收到对方分享的信息"
        notebook.info_shared.append({"detail": user_message[:40], "turn": notebook.turn})
        return reply, note

    # 合作
    if "合作" in user_message or "一起" in user_message:
        nq = mind.get("natural_questions",{})
        reply = nq.get("when_cooperate", "好，合作。你有什么具体的计划？")
        return reply, f"{ai_role}同意合作"

    # 默认回复 - 引用最近声称
    latest = notebook.get_latest_claim()
    if latest:
        nq = mind.get("natural_questions",{})
        reply = nq.get("when_info", f"作为{ai_role}，我听到了。你有具体信息要分享吗？")
        for k, v in game_state.items():
            placeholder = "{" + k + "}"
            if placeholder in reply and isinstance(v, str):
                reply = reply.replace(placeholder, v)
        note = f"{ai_role}继续与{latest}的对话"
        return reply, note

    return f"嗯，我是{ai_role}。你有什么想跟我讨论的？", f"{ai_role}等待对方开口"


def summarize_training_data(jsonl_path):
    """分析训练数据集的覆盖情况"""
    import json
    counts = {}
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    r = rec.get("ai_role","?")
                    b = rec.get("branch","?")
                    key = f"{r}/{b}"
                    counts[key] = counts.get(key, 0) + 1
                except:
                    pass
    except:
        return {}
    return counts
