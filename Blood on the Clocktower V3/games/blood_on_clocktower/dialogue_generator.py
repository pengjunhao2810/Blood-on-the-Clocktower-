"""
推理链对话生成器 V3.5 — 混合架构
模板骨架 + LLM 填充关键推理句，大幅提升自然度
"""

import random

try:
    from .llm_filler import generate_text
except ImportError:
    try:
        from llm_filler import generate_text
    except ImportError:
        generate_text = None


def _pick(arr):
    return random.choice(arr)


def _maybe(prob=0.5, a="", b=""):
    return a if random.random() < prob else b


# ========== LLM 辅助 ==========

_LLM_PROB = 0.40  # LLM 调用概率

_SYS_PROMPT = "你是血染钟楼桌游的玩家，正在用中文发言。" \
              "说话要自然、口语化，像真人玩桌游一样。" \
              "不要用'首先其次最后'这种结构化表达。"


def _llm(user_prompt, max_tokens=80, temperature=0.85):
    if not generate_text:
        return None
    if random.random() >= _LLM_PROB:
        return None
    result = generate_text(_SYS_PROMPT, user_prompt, max_tokens, temperature)
    if result and len(result) > 6:
        return result.rstrip("，。；") + "。"
    return None


# ========== 推理链构建工具 ==========

def _claim_ref(claim_map, player):
    return claim_map.get(player, "?")


def _build_observation(claim_str, vote_str, suspect,
                       speaker_name=None, speaker_role=None):
    """构建观察段落（可选 LLM 增强）"""
    # 尝试 LLM
    if speaker_name and claim_str and vote_str and suspect and "还没有" not in claim_str:
        prompt = (
            f"场上的身份声明：{claim_str}。"
            f"投票记录：{vote_str}。"
            f"你是{speaker_name}（{speaker_role}）。你最怀疑{suspect}。"
            f"请用1句话自然地描述局势，点出{suspect}的可疑之处。"
        )
        llm = _llm(prompt)
        if llm:
            return llm

    # 模板兜底
    parts = []
    if claim_str:
        parts.append(f"目前场上身份声明情况是：{claim_str}")
    if vote_str:
        parts.append(f"再看投票记录：{vote_str}")
    if suspect:
        parts.append(f"综合来看，{suspect}的嫌疑比较突出")
    return "；".join(parts) if parts else "目前信息有限，但有些细节值得推敲"


def _build_analysis(suspect, claim_map, vote_info,
                    speaker_name=None, speaker_role=None):
    """构建分析段落（可选 LLM 增强）"""
    # 尝试 LLM
    if speaker_name and suspect and claim_map:
        claim_ref = _claim_ref(claim_map, suspect)
        vote_str_parts = []
        if vote_info:
            for d, votes in vote_info.items():
                for v in votes:
                    vote_str_parts.append(f"{v.get('voter')}投了{v.get('target')}")
        vote_str = "，".join(vote_str_parts[:4]) if vote_str_parts else ""
        prompt = (
            f"你是{speaker_name}（{speaker_role}）。"
            f"场上身份声明：{', '.join(f'{p}自称{r}' for p, r in list(claim_map.items())[:5])}。"
        )
        if vote_str:
            prompt += f"投票记录：{vote_str}。"
        prompt += (
            f"你怀疑{suspect}自称{claim_ref}。"
            f"请用1-2句中文分析{suspect}的可疑之处，引用具体票型或发言行为。"
            f"不要用'首先其次'，要像真人聊天一样自然。"
        )
        llm = _llm(prompt, max_tokens=100)
        if llm:
            return llm

    # 模板兜底
    analyses = [
        f"为什么我怀疑{suspect}？第一，他的身份声明和实际行为对不上——{_claim_ref(claim_map, suspect)}这个身份在当前的局面下太安全了，安全到像是编的；"
        f"第二，他的投票轨迹显示他在保某些人、踩某些人，这不是好人的投票逻辑，更像是邪恶在操作票型",
        f"我来论证一下{suspect}的可疑之处。关键矛盾在于：如果他真是{_claim_ref(claim_map, suspect)}，为什么不敢正面回应质疑？"
        f"好人被冤枉时会激动地拿出自己的信息反驳，而他只会反问和转移话题——这是邪恶的标准防御姿态",
        f"分析{suspect}的行为模式：他的发言前后存在不一致，早期和晚期的说法有微妙出入。"
        f"人在编故事时最容易犯的错误就是前后矛盾，因为真实的记忆是连贯的，而虚构的叙述需要不断调整",
        f"我注意到一个关键细节：{suspect}在其他人被质疑时的反应很不自然——他要么急着撇清关系，要么过度维护对方。"
        f"正常的好人会对所有可疑对象保持警惕，而不是选择性失明。这种'选择性关注'本身就是最大的疑点",
        f"让我们从概率角度分析：如果{suspect}是好人，那他被这么多人怀疑却拿不出自证清白的证据，这本身就不合理。"
        f"一个真正的好人一定会拼命证明自己——而{suspect}的反应更像是'你们爱信不信'的摆烂姿态",
    ]
    return _pick(analyses)


def _build_conclusion(target, action="处决",
                      speaker_name=None, speaker_role=None):
    """构建结论段落（可选 LLM 增强）"""
    # 尝试 LLM
    if speaker_name:
        prompt = (
            f"你是{speaker_name}（{speaker_role}）。"
            f"你坚信{target}是邪恶方。"
            f"请用1句话总结结论，建议今天{action}{target}。要果断、坚定。"
        )
        llm = _llm(prompt)
        if llm:
            return llm

    # 模板兜底
    conclusions = [
        f"结论很明确：{target}就是我们要找的目标。今天{action}{target}是最优解，"
        f"即使翻出是好人，也能从投他票的人里顺藤摸瓜找到同伙——这叫'投石问路'",
        f"所以我的判断是：{target}不能留。今天{action}他是必须的操作，"
        f"理由有三点我已经说清楚了。如果错了，我主动背锅，但我不认为我会错",
        f"说了这么多，核心就一句话：{target}有问题。我建议今天先{action}{target}，"
        f"明天根据他的翻牌结果决定后续方向。这是当前收益最高的打法",
    ]
    return _pick(conclusions)


def _build_strategy(suspect, team, day_count, alive_count):
    """构建阵营打法思路段落"""
    if team in ("demon", "minion"):
        strategies = [
            f"后续策略：今天处理掉{suspect}之后，明天顺着投票链继续施压。"
            f"好人的弱点在于他们总想找'铁证'，而我们只需要制造足够的混乱就能赢。"
            f"如果局面不利，我还有备用方案——拉{_pick(['一个替死鬼', '另一个目标', '反向指控'])}出来转移视线",
            f"长远来看，我们的目标不是说服所有人，而是让好人的票分散。"
            f"只要他们内部产生分歧，我们的票就是决定性的。所以今天的核心任务不是讲道理，"
            f"是把水搅浑——让好人之间互相猜疑。{suspect}只是第一块多米诺骨牌",
            f"终局思考：现在已经第{day_count}天了，剩下{alive_count}个人。"
            f"如果我们能活到决赛圈，关键在于谁掌握了好人的信任。所以今天我不仅要出{suspect}，"
            f"还要趁机拉拢{_pick(['中间派', '摇摆的好人', '那些还没表态的人'])}——他们的票在决赛圈就是胜负手",
        ]
    else:
        strategies = [
            f"我的阵营思路是这样的：今天找出{suspect}后，如果他是邪恶，那么投他票的人里大概率有他的队友——"
            f"因为邪恶方在投票时倾向于抱团。我们先把{suspect}出了，明天从跟票的人里继续盘",
            f"从大局看，现在已经第{day_count}天，好人不能分散投票了。"
            f"我们必须统一目标，集中票数。我建议今天锁定{suspect}，所有人一起投。"
            f"如果错了，至少我们排除了一个选项，明天缩小范围继续盘",
            f"我的打法原则：宁可错杀不可放过——不是因为我激进，而是因为邪恶方在决赛圈的操作空间太大了。"
            f"只有在白天不断缩小嫌疑人范围，晚上才不会被邪恶牵着鼻子走。{suspect}是目前嫌疑最大的人，"
            f"先出了他，我们才能看清剩下的局势",
        ]
    return _pick(strategies)


def _build_call_to_action(target, action="投票"):
    """构建号召行动段落"""
    calls = [
        f"所以我希望大家今天把票投给{target}。不要犹豫，犹豫就会败北。"
        f"好人的劣势就在于信息不透明，而信息越不透明，越需要果断的行动",
        f"现在不是谦虚的时候。我明确表态：今天{action}{target}。支持我的请跟上，"
        f"反对的请给出理由——但你的理由最好足够有力，因为放过{target}的代价可能就是这个游戏的胜负",
        f"话说到这个份上，剩下的就看大家了。我该分析的都分析了，该摆的证据都摆了。"
        f"{target}是不是有问题，每个人自己心里都有判断。我不强迫任何人，"
        f"但如果你放过了{target}而他翻出是邪恶，请记住今天谁在保他",
    ]
    return _pick(calls)


# ========== 核心生成函数 ==========

def gen_good_private_discuss(name, role, suspect, claim_map, vote_info, day_count):
    """善良方私聊推理链"""
    claim_str = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:5]]) if claim_map else "目前还没有人公开身份"
    vote_str_parts = []
    if vote_info:
        for d, votes in vote_info.items():
            for v in votes:
                vote_str_parts.append(f"{v.get('voter')}投了{v.get('target')}")
    vote_str = "，".join(vote_str_parts[:4]) if vote_str_parts else "目前投票记录还比较少"

    obs = _build_observation(claim_str, vote_str, suspect, name, role)
    analysis = _build_analysis(suspect, claim_map, vote_info, name, role)
    conclusion = _build_conclusion(suspect, speaker_name=name, speaker_role=role)
    strategy = _build_strategy(suspect, "townsfolk", day_count, 7)
    action = _build_call_to_action(suspect)

    return f"{obs}。{analysis}。{conclusion}。{strategy}。{action}"


def gen_evil_private_plan(name, role, target, claim_map, vote_info, day_count, partner):
    """邪恶方私聊计划——带完整推理链"""
    claim_str = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:3]]) if claim_map else "目前还没有人公开身份"

    obs = f"目前场上局势：{claim_str}。我判断{target}是威胁最大的信息位，今晚必须处理掉"
    analysis = f"为什么选{target}？从发言模式看，{target}在主动收集信息而不是被动防守，这是信息位的典型特征。"
    analysis += f"而且{target}的投票轨迹显示他在试图引导方向——不能让他继续活着分析我们"
    plan = f"你的任务：明天公聊你跳{_pick(['洗衣妇', '调查员', '占卜师', '厨师'])}，"
    plan += f"就说你查到{target}有问题。我配合你从另一个角度咬他。"
    plan += f"具体话术：你不用太具体——就说'我查到的信息跟{target}的声明对不上'。这种模糊指控最难反驳"
    strategy = f"长远策略：处理掉{target}后，好人阵营会失去一个重要信息源。"
    strategy += f"接下来我们继续制造矛盾，目标是让好人内部产生分歧。"
    strategy += f"只要好人的票分散了，我们就能活到决赛圈。记住：我们不需要说服所有人，只需要让好人无法形成共识"

    return f"{obs}。{analysis}。{plan}。{strategy}"


def gen_good_public_reasoning(name, role, suspect, claim_map, vote_info, day_count, alive_count):
    """善良方公聊推理——长篇分析"""
    claim_str = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:6]]) if claim_map else "目前还没有人公开身份"
    vote_str_parts = []
    if vote_info:
        for d, votes in vote_info.items():
            for v in votes:
                vote_str_parts.append(f"{v.get('voter')}投了{v.get('target')}")
    vote_str = "，".join(vote_str_parts[:4]) if vote_str_parts else "目前投票记录还比较少"

    opening = _pick([
        f"我是{role}，我来说一下我的完整分析：",
        f"大家好，我是{role}。经过前几轮的发言和投票，我形成了以下几个判断：",
        f"各位，我是{role}。局势越来越复杂了，我梳理一下我的思路：",
    ])

    obs = _build_observation(claim_str, vote_str, suspect, name, role)
    analysis = _build_analysis(suspect, claim_map, vote_info, name, role)
    conclusion = _build_conclusion(suspect, speaker_name=name, speaker_role=role)
    strategy = _build_strategy(suspect, "townsfolk", day_count, alive_count)

    body = f"{obs}。{analysis}。{conclusion}"
    body += f"。{strategy}"

    closing = _pick([
        f"以上是我的完整分析。大家有问题可以讨论，但我坚持今天的出人目标是{suspect}。",
        f"我说完了。总结就是一句话：今天出{suspect}。理由和逻辑都在上面了，大家自己判断。",
        f"该说的我都说了。这是一个{role}基于现有信息做出的判断，希望对大家有帮助。",
    ])

    return f"{opening}{body}。{closing}"


def gen_good_bluff(name, role, real_role_info, target, claim_map, vote_info):
    """善良方诈身份——假跳信息位钓鱼"""
    bluff_templates = []
    if real_role_info:
        info_item = list(real_role_info.items())[0]
        fake_info = f"我查验了{target}，我的技能告诉我{_pick(['他的身份有问题', '他不是他声称的那个人', '他的声明和我的信息对不上'])}"
        bluff_templates.append(
            f"大家注意，我其实不是{role}——我是{_pick(['占卜师', '调查员', '共情者'])}，之前一直没跳是因为想多收集信息。"
            f"现在我不得不跳了：{fake_info}。{target}绝对不能留。"
            f"我承认我之前隐瞒身份是钓鱼——现在鱼上钩了，{target}就是我要钓的那条。"
        )
    bluff_templates.append(
        f"我怀疑我们中间有人在冒充身份。我提议一个方案：每个人轮流说出自己第一天晚上的行动细节。"
        f"真正的信息位一定能说出具体操作，假信息位只能泛泛而谈。{target}敢接这个挑战吗？"
        f"不敢的话——你知道你是什么情况。"
    )
    bluff_templates.append(
        f"我来抛个砖：我已经掌握了部分信息，但我不打算全部公开——因为我想看看谁会'对号入座'。"
        f"具体来说，{_pick(['关于昨晚的行动', '关于某个身份的声明', '关于某个投票的动机'])}，我知道一些事情。"
        f"如果有人急着来'解释'，那他就暴露了自己。{target}，你有什么想说的吗？"
    )
    if claim_map:
        clashes = [(sp, rn) for sp, rn in claim_map.items() if list(claim_map.values()).count(rn) > 1]
        if clashes:
            sp, rn = clashes[0]
            bluff_templates.append(
                f"关于{sp}和{rn}的身份冲突，我有一个大胆的推测："
                f"这两个人里必然有一个是假的。但也许两个都是假的——一个真邪恶在冒充，一个假好人在跟风。"
                f"真正的好人不会去凑热闹冒充别人身份，只有邪恶才会觉得'多一个假身份水更浑'。"
                f"所以我建议今天从这两个人里出一票，看翻牌结果再决定下一步。"
            )
    return _pick(bluff_templates)


def gen_evil_public_reasoning(name, role, bluff, fake_info, target, claim_map, vote_info, day_count, alive_count):
    """邪恶方公聊推理——装好人的长篇大论"""
    claim_str = "，".join([f"{p}自称{r}" for p, r in list(claim_map.items())[:5]]) if claim_map else "目前还没有人公开身份"
    vote_str_parts = []
    if vote_info:
        for d, votes in vote_info.items():
            for v in votes:
                vote_str_parts.append(f"{v.get('voter')}投了{v.get('target')}")
    vote_str = "，".join(vote_str_parts[:4]) if vote_str_parts else "目前投票记录还比较少"

    opening = _pick([
        f"我是{bluff}，我来做一个完整的信息梳理：",
        f"各位好，我是{bluff}。经过思考，我认为现在是时候把信息摊开来说了：",
        f"我是{bluff}。长话短说，我有几个关键判断：",
    ])

    fake_evidence = fake_info or f"我通过{bluff}的技能确认了{target}有问题——具体细节我不能多说，"
    fake_evidence += "但我的信息来源是可靠的"

    obs = f"从目前的身份声明看：{claim_str}。从投票记录看：{vote_str}。"
    obs += f"把这些信息综合起来，{target}的嫌疑就非常明显了"

    analysis = f"让我具体说说为什么盯上{target}："
    analysis += f"第一，{fake_evidence}；"
    analysis += f"第二，{target}在之前的发言中存在逻辑矛盾——"
    analysis += f"他开始说{_pick(['自己没有信息', '自己是平民', '自己在观察'])}，后来又{_pick(['突然有了结论', '开始带节奏', '表现得过于积极'])}，"
    analysis += f"这种转变不符合好人的行为模式；"
    analysis += f"第三，从票型看，{target}的投票选择更倾向于{_pick(['保人而不是出人', '跟风而不是独立判断', '制造平票而不是明确表态'])}"

    conclusion = f"综合以上三点，我的结论很明确：{target}今天必须出局。"
    conclusion += f"我拿{bluff}的身份担保，{target}翻不出好人。"

    strategy = f"长远来看，今天出{target}后，我们需要关注{_pick(['那些保过{target}的人', '投票时游移不定的人', '一直不报身份的人'])}——"
    strategy += f"邪恶方在队友被处决后会露出马脚，那就是我们下一轮的目标"

    closing = _pick([
        f"以上是我的分析，供大家参考。但我明确表示：今天投{target}。",
        f"我分析完了。信息摆在这里，信不信由你。但如果你放过了{target}，别后悔。",
    ])

    return f"{opening}{obs}。{analysis}。{conclusion}。{strategy}。{closing}"


def gen_naturalize_advanced(text, personality=None):
    """高级自然化——插入语气词、人格特征、口语化元素"""
    if not text or len(text.strip()) < 3:
        return text

    if personality:
        return personality.apply_to_text(text)

    openers = ["嗯……", "那个……", "怎么说呢……", "其实吧", "哎", "老实说", "我直接说吧"]
    closers = ["吧", "啊", "嘛", "呢", "哈", "哦"]
    inserts = ["说实话", "我感觉", "我觉得吧", "你想想", "讲真"]

    r = random.random()
    if r < 0.20:
        op = random.choice(openers)
        text = f"{op}，{text}"
    elif r < 0.33:
        cl = random.choice(closers)
        try:
            if text.rstrip()[-1] in "！。？吗的":
                text = text.rstrip()[:-1] + f"{cl}。"
            else:
                text = f"{text}{cl}。"
        except IndexError:
            pass
    elif r < 0.45:
        ins = random.choice(inserts)
        if "，" in text:
            a, b = text.split("，", 1)
            text = f"{a}，{ins}，{b}"
    return text
