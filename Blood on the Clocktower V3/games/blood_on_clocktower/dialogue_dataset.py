"""
目的驱动对话数据集 V2 - 长推理链 + 阵营意识 + 狡诈邪恶
{claim_str}: "玩家X自称Y" / {vote_str}: 投票记录 / {contradict_str}: 矛盾点 / {spy_info}: 间谍情报
"""

import random

from .personality import get_current_personality


class DialogueDataset:

    EVIL_FIRST_CONTACT = [
        "我是{role}。上来先说计划：今晚刀{target}——他是信息位必须死。你明天公聊直接说你是{listener_fake}，查到了{target}有问题。我跳{my_fake}配合你。我们两个独立信息位指向同一个人，好人必信。{spy_info}",
        "{listener}，时间紧。你装{listener_fake}编一套假查验结果：就说你查到{target}身份可疑。我跳{my_fake}假装从另一个角度验证。两个信息位交叉验证，没人敢保{target}。{spy_info}",
        "计划：你{listener_fake}明天编一段伪信息，说{target}的声明跟你查到的不符。我{my_fake}晚几个发言再跟上，假装独立思考后得出同样结论。间隔发言是关键——不能让人看出我们在配合。{spy_info}",
        "{listener}，你装{listener_fake}负责给{target}泼脏水，我{my_fake}负责做实锤。具体操作：你先在公聊说{target}的{claim}声明有问题，我紧接着说我也有类似发现。两个人从不同角度咬同一个人，在别人看来就是铁证。{spy_info}",
        "分工：你{listener_fake}去公聊编个假信息，就说你查到{target}不是好人。我在旁边帮腔说{my_fake}视角看{target}也确实可疑。记住咱俩要装不认识——你是独立查到的，我是独立推理出来的。今晚先刀{target}，明天看情况再决定下一步。{spy_info}",
        "作战会议：今晚刀{target}，明天你{listener_fake}主攻我{my_fake}策应。在公聊里你先抛出假信息，我装作被你的推理说服——这样既建立了你的可信度，也显得我理性客观好说话。{spy_info}",
        "先确认一下今晚的击杀顺序：第一目标{target}，如果保护了就转{other_target}。白天你的策略是假装对{target}有怀疑但不确定，让我来负责引导投票——这样你看起来反而更可信。{spy_info}",
    ]

    # Fix 9: 带铺垫的邪恶队内开场（更像正常对话，降低被窃听风险）
    EVIL_FIRST_CONTACT_PADDED = [
        "你好{listener}，刚看了一下局面，我觉得{target}的信息位威胁最大——你觉得呢？如果可以的话，今晚先处理他，明天你在公聊按{listener_fake}的视角带一下节奏，我来配合。{spy_info}",
        "{listener}，我想跟你对一下策略。我打算跳{my_fake}，你看{listener_fake}行不行？今晚的目标我个人倾向{target}——他如果是信息位越早处理越好。你觉得呢？{spy_info}",
        "有空聊聊吗？我刚在盘局势，{target}的问题越来越明显了。我的想法是：你{listener_fake}先在公聊抛出疑点，我{my_fake}后续跟上。这样看起来更自然。今晚先把{target}处理了。{spy_info}",
        "嘿{listener}，来对对思路。我注意到了{target}，这个人威胁很大。我的建议：你明天用{listener_fake}的身份去咬他，我{my_fake}从另一个角度配合。今晚先刀{target}——你觉得顺序合理吗？{spy_info}",
        "{listener}，商量一下。我跳{my_fake}，你拿{listener_fake}。我们先从{target}开始处理——你在公聊先抛假信息，我装作被说服。今晚目标{target}，有问题再调整。{spy_info}",
    ]

    EVIL_BLUFF_PROPOSE = [
        "听好，分配伪装角色：我跳{demon_fake}，你跳{minion_fake}。{fake_role_pool}这些是我们可用的身份池。{spare_suffix}记住：公聊时我们俩的声称要互相印证，不能出现一个说{target}是好人、另一个说他是邪恶的矛盾。",
        "伪装方案：我{demon_fake}，你{minion_fake}。{fake_role_pool}里面我优先选前面的，因为信息位身份更有威慑力。你辅助我咬人就行——我主攻，你补刀。{spare_suffix}",
        "角色分配完毕：我{demon_fake}，你{minion_fake}。剩下的{spare_suffix}核心原则：我说的话你要配合，你说的我绝不反驳——坏人最忌讳内讧。对外我们口径一致，对内我们再讨论真实目标。",
        "关于伪装身份：我拿{demon_fake}，你拿{minion_fake}。{fake_role_pool}里面挑信息位给我们自己，因为好人最信信息位。如果被质疑，就说我们是'独立查到同一个人有问题'——这逻辑无懈可击。",
    ]

    MINION_BLUFF_FEEDBACK = [
        "收到分配。我{demon_fake}没问题，但我觉得{spare_suffix}如果你那边需要调整，我可以换身份。关键是你{demon_fake}要站住脚，我配合你。",
        "明白，我{minion_fake}。我会在公聊时说查到了{target}有问题，你{demon_fake}接着咬。放心，我不会演崩。",
        "方案收到。我{minion_fake}配合你{demon_fake}。建议我们同步一下编的细节——比如我查到的具体时间、方式，免得被人盘出逻辑漏洞。",
        "分配收到，我拿{minion_fake}没问题。不过我想换一下策略：我先在公聊假装质疑你{demon_fake}，然后你巧妙回应解除我的'怀疑'——这样我俩的信任度都能提升。",
    ]

    EVIL_DEEP_PLAN = [
        "长远来看，我们这个战术的核心是让好人阵营的信息链条断裂。{claim_str}里面已经有人开始信我们的假信息了。接下来继续保持压力，让{target}成为焦点。只要好人在{target}身上浪费一轮处决，我们就赚了。",
        "我思考了一下局势：{vote_str}说明好人的票型开始分散了。这是好事——他们的共识在瓦解。我们要做的就是继续制造噪音：你继续编假信息，我继续带节奏。等到他们内部吵起来，我们就赢了。",
        "目前{claim_str}分析下来，{target}是最佳攻击点。我们集中火力咬他，理由有三：第一，他报的身份是{claim}，这个身份很容易被质疑；第二，从{vote_str}看他的投票有异常；第三，咬他风险最小——即使他翻出是好人，我们也只是排除了一个选项。",
        "盘一下剩余玩家。{claim_str}告诉我们还有多少人没报身份——这些沉默的人既是隐患也是机会。我们可以在他们开口之前先把{target}定义成'邪恶方'，等于提前占领了好人的心智。",
        "你看这个局势：好人的信息越多他们就吵得越厉害。{contradict_str}这个矛盾点我们可以利用——让他们先内耗，我们等时机成熟再出手。不急，时间在我们这边。",
    ]

    EVIL_COUNTER_ATTACK = [
        "情况不对，{target}开始反击了。我们需要立刻转移焦点——你跳出来说{other_target}更可疑，我配合你。理由就说{other_target}的投票记录不对——{vote_str}里面他投的票全是跟风。记住：最好的防守就是进攻。",
        "有人盯上我们了。按B计划：你主动承认自己是{listener_fake}但信息有误——就说你第一天看错了。我则跳出来说其实我才是{my_fake}，我之前没说是因为在收集信息。身份对换，重新洗牌。",
        "被怀疑了，别慌。我教你反制：你先发制人去质疑{target}——说他{claim}的身份信息跟别人对不上。好人有一个弱点：当他们发现有人互相质疑时，他们会观望而不是立刻下结论。我们利用这个窗口期重新掌握主动权。",
        "他们的矛头对准我了。这样，你来'保护'我——在公聊说你相信我是好人，因为你{listener_fake}的信息反过来印证了我的身份。这样一来，质疑我的人就是在质疑两个'信息位'，代价很高。",
        "对方在盘我们的逻辑漏洞了。告诉你一个技巧：把水搅浑的最好方式就是反问。不管对方质疑你什么，你就反问'那你觉得谁是邪恶？你的依据是什么？'——把问题抛回去，好人的逻辑往往是散的，经不起追问。",
    ]

    EVIL_SOW_DOUBT = [
        "我们来播撒怀疑的种子。你去私聊的时候跟{target}说'你被盯上了，有人在我这里说你坏话'——让好人也互相猜忌。离间计比直接攻击更有效。",
        "散布谣言：跟不同的人说不同的版本。跟{target}说{other_target}在怀疑他；跟{other_target}说{target}有问题。让他们互相咬起来，我们坐收渔利。",
    ]

    EVIL_CONSENSUS = [
        "今天的投票目标是{target}。我们需要至少4票才能处决他。我去拉拢中间派，你去说服其他人。记住统一口径：{target}的{claim}声明有问题，他的{vote_str}投票记录也很奇怪。",
    ]

    EVIL_SACRIFICE = [
        "苦肉计：我今天会故意犯一个错误——在公聊时'不小心'说错一个信息，让好人来质疑我。你到时候站出来替我'辩护'，赢得信任。等我被投出去后，你就能成为好人心中的'明好人'，掌握话语权。",
        "我准备牺牲了。今天我会在公聊上跟{target}硬刚，故意露出破绽。你到时候扮演理性的中间人，两边都批评一下，建立你独立思考的人设。我出局后，你在邪恶方就是最关键的一票。",
    ]

    EVIL_DOUBLE_CLAIM = [
        "双簧计划：我们俩都声称自己是{claim_pair}。两个{claim_pair}互相印证说{target}有问题——好人就会想'两个独立的信息位都说同一个人有问题，那肯定是真的'。他们不会想到两个{claim_pair}其实是串通好的。",
        "来，我们对冲一个平民身份——比如都说是{claim_pair}。好人不敢同时处决两个{claim_pair}，怕杀错人。这给我们争取了至少一轮的生存空间。在这一轮里，我们全力把{target}搞出局。",
    ]

    EVIL_FAKE_SOLVE = [
        "我们来构建一个完整的推理链：你{listener_fake}的角度看{target}有问题，我{my_fake}分析一下也得出同样结论。一个查验结论加上一个推理结论，在好人眼里就是双重证据。",
        "我盘了一下目前的线索：{vote_str}加上{claim_str}里面的疑点，指向{target}的嫌疑最大。我们可以拿这套逻辑去公聊推动投票。",
    ]

    EVIL_POCKET = [
        "{target}这个人值得拉拢。你去私聊他的时候，说'我觉得你被冤枉了，我的信息显示你应该是好人'。先给他安全感，再慢慢引导他的投票方向。被他信任比被他害怕更有价值。",
        "拉拢战术：你跟{target}说你在怀疑{other_target}，问他怎么看。如果他也同意，说明他跟你是一个思路——可以发展成盟友。如果他为{other_target}辩护，说明他们是队友或者他已经有立场了。",
    ]

    EVIL_INFO_CHAIN = [
        "制造验证链：你公聊跳信息位（比如洗衣妇），说你查到了{target}是某个角色。我配合说我也觉得{target}符合那个角色——两个独立信息位交叉验证同一结论，好人必信。",
        "我公聊说我查到{target}是邪恶，你接话说你也怀疑{target}很久了因为{vote_str}。一个查验加上你的推理佐证——这在好人眼中就是铁证。",
    ]

    EVIL_CLAIM_BATTLE_BRIEF = [
        "{battle_target}自称{battle_role}，你也在公聊跳{battle_role}，跟他打对台。他一轮说自己是{battle_role}，你下一轮也说自己是{battle_role}——两个人身份一样，好人就会迷惑。你不用编得太真，关键是把水搅浑，让好人分不清谁真谁假。",
        "策略：你出公聊说你是{battle_role}，跟{battle_target}对跳。记住：真的{battle_role}会提供具体信息，你只需要模仿他的口吻发言就行。一旦好人开始纠结两个{battle_role}谁是真的，我们就赢了。",
        "{battle_target}跳了{battle_role}，这是机会。你也跳{battle_role}，制造身份对跳。对跳的精髓不是让人信你，而是让好人不信他。只要好人不敢完全信{battle_target}，我们的假信息就能趁虚而入。",
        "你来打{battle_role}对跳，我来配合。你在公聊里报假信息说{target}有问题，我接话我也觉得{target}不对劲。两个{battle_role}的结论一致——真真假假，好人就彻底乱了。",
    ]

    MINION_CLAIM_BATTLE_ACK = [
        "明白，我公聊跳{battle_role}跟{battle_target}对线。我准备好了几个借口，到时候随机应变。",
        "好的，我下场跳{battle_role}。对跳我熟——只要我不崩人设，好人就得花一轮来盘我们俩。",
        "对跳{battle_role}？没问题。我就说我是{battle_role}，他才是冒牌货。他拿不出证据证明他是真的。",
    ]

    EVIL_TARGET_COORD = [
        "确认攻击目标：{target}。理由有三：第一他claim了{claim}，这身份容易被质疑；第二从{vote_str}看他投票有明显倾向；第三他在{claim_str}里面的定位是信息位，威胁最大。今天集中火力搞他。{kill_target}{kill_reason}",
        "今晚刀{target}，白天的公聊目标也是{target}。我们双管齐下：晚上物理消灭，白天舆论消灭。即使他晚上不死，白天也要让他出局。{kill_target}{kill_reason}",
        "目标锁定：{target}。我负责带节奏，你负责编证据。具体分工：我在公聊先开火，你隔几个人再跟上，看起来像是各自独立思考的结果。{kill_target}{kill_reason}",
        "你觉得{target}怎么样？我观察了他好几轮，感觉他的{claim}身份很假。要不今天我们两个都在公聊点一下他，看看其他人的反应？如果多人附和我们，今天就可以冲他。{kill_target}{kill_reason}",
        "{target}的发言越来越可疑了，他自称{claim}但说法前后不太一致。明天公聊我打算先提这一点，如果你也注意到了可以接我的话——这样看起来像是大家的共识而不是我一个人的判断。{kill_target}{kill_reason}",
        "我刚想到一个方向：{target}的{claim}声明和{vote_str}放在一起看很有问题。明天聊到这个话题时你可以顺着这个方向说，算是我俩各自的观察互相验证了。{kill_target}{kill_reason}",
    ]

    EVIL_REHEARSE = [
        "排练一下明天的公聊剧本。我先说：'我是{my_fake}，我查到{target}有问题。'然后你接：'巧了，我也在怀疑{target}，因为{vote_str}。'注意你的语气要像临时发现而不是商量好的。",
        "模拟一下被质疑时的应对。如果有人说'你们两个怎么同时怀疑同一个人'，你回答：'因为狐狸尾巴露出来了，谁都能看到。'自然带过，不要过度解释——越解释越可疑。",
        "刚才我在想，如果有人在公聊问起我们的{my_fake}身份，我就先说之前的信息比较模糊，需要再观察一轮。你到时候别说太多，帮腔点头就行——两个人都话多容易被盯上。",
        "明天你可以在公聊先聊点别的，别上来就直奔{target}——太刻意了。等两三个人发言之后你再自然提起'其实我观察{target}很久了'，这样看起来更真实。",
    ]

    EVIL_FINALIZE = [
        "最后一轮了。现在场上还有{alive_count}个人，我们需要明确票型。你负责说服{target}投{other_target}，我去搞定{another}。如果一切顺利，我们有三票在手，加上被迷惑的好人票，够处决任何人了。",
        "决赛圈策略：我们不能再互相私聊了，容易被盯上。所有交流通过公聊暗示进行。我说'今天天气不错'表示计划顺利，说'有点冷'表示需要调整。记住这些暗号。",
    ]

    EVIL_GOOD_FAKE_OPEN = [
        "你好{listener}，我是{my_fake}。想跟你聊聊对局势的看法。{claim_str}里面我注意到你报了{listener_fake}——说实话我也在关注同样的方向。你怎么看{target}这个人？",
        "嗨{listener}，我是{my_fake}。我觉得我们需要多交流，信息共享才能赢。你先说说你的想法？",
        "{listener}，想跟你对一下信息。我{my_fake}这边有一些发现，但不完整——我觉得跟你合一下数据会有帮助。你现在怀疑谁？",
        "嘿{listener}，我是{my_fake}。场上局势有点乱，我想找一个思路清晰的人聊聊——我注意到你之前的发言很有条理。你怎么看待目前的局面？",
    ]

    EVIL_GOOD_DISINFO = [
        "说实话，我有个怀疑对象一直没说——我怕说出来打草惊蛇。但我信得过你，我觉得{target}的问题很大。{vote_str}你看了吗？他的投票明显不对劲。你觉得呢？",
        "我的{my_fake}技能虽然没有直接查到铁证，但我的直觉告诉我{target}不能留。你观察一下他的发言方式——他太'完美'了，好人的发言应该是有瑕疵的。",
        "我跟你透露一个事：{target}跟我私聊的时候说了一些跟他公聊完全矛盾的话——他在对我和对大家说两套词。这本身就是最大的破绽。",
        "你有没有注意到{target}和{other_target}的互动？他们之间几乎不互相质疑——这在正常的游戏中是非常反常的。我怀疑他们是一伙的，互相打掩护。",
        "我复盘了{target}的全部公聊发言，发现几个具体矛盾：第一，他先说自己是{claim}，但{contradict_str}；第二，当有人质疑他的时候，他没有回应具体疑点而是转向了{other}；第三，{vote_str}里他的投票和{claim}身份的利益取向完全不符。",
        "{target}，我直接问你几个问题：你自称{claim}，那你的技能结果具体是什么？为什么{contradict_str}？{vote_str}里面你的投票是怎么考虑的？请具体回答，不要绕开。",
        "{target}的发言和行为对不上——他说自己是{claim}，但我观察到他{my_note}。一个真正的{claim}不应该有这种表现。我建议大家今天先排查他，如果他翻出是好人，我来背锅。",
    ]

    EVIL_GOOD_PROBE = [
        "我想听听你对{target}的看法。你觉得他可信吗？从我的视角看，他的{claim}声明有点问题——但我想知道你的判断。毕竟两个人看事情总比一个人全面。",
        "你信任谁？不信任谁？这个问题我其实在问所有人，但我先问你——因为我觉得你思路比较清晰。我个人目前最怀疑{target}。",
        "我注意到你一直在观察{target}。你发现什么了吗？我觉得他的声明有些站不住脚，但我需要另一个人的视角来确认。",
        "你觉得今天应该出谁？我还没完全决定，但我倾向于{target}——他的痕迹太明显了。如果你有不用的想法告诉我，我们商讨一个最优解。",
    ]

    EVIL_GOOD_CLOSE = [
        "跟你聊完我收获很大。今天就先到这里，后面有新的发现再交流。记住：如果{target}有什么异常举动，第一时间告诉我。",
        "好的，今天先到这。你我的谈话内容暂时保密——我不想让{target}知道我们在关注他。惊动了他反而不好查。",
        "聊得有收获。明天继续沟通——我们两个人信息共享比单打独斗强多了。今天先按这个方向走，有变化我通知你。",
        "好，先这样。记住今天的核心判断：{target}不能被放过。如果有人在保他，那保他的人也同样可疑——帮我盯着点。",
    ]

    # ========== 洗衣妇专属私聊 ==========
    GOOD_WASHERWOMAN_CONFIRM = [
        "你好{target}，我是洗衣妇。首夜得知你是{ww_role}——这个身份你认吗？如果你认，我们就是金水关系，后面信息共享。如果你不认，我需要去排查信息干扰来源。",
        "{target}，有件事需要直接确认：我首夜查到你是{ww_role}，这是真的吗？我需要你的正面回答才能安排后续策略。",
    ]
    GOOD_WASHERWOMAN_GOLDWATER_INV = [
        "已确认{target}是真实{ww_role}金水。请你今夜避开查验{target}，重点查验剩余外置位找爪牙与恶魔。我的信息已确认，后续我负责盯{target}的投票和发言。",
        "同步金水信息：{target}认了{ww_role}，和我首夜查验一致。这条信息链是干净的——请你把查验资源集中在其他人身上，{target}这边我来跟踪。",
    ]
    GOOD_WASHERWOMAN_GOLDWATER_SEER = [
        "已确认{target}是真实{ww_role}金水。请你今夜避开查验{target}，重点查验其他玩家。我的首夜信息已确认无误，{target}可以信任。",
        "金水确认：{target}是{ww_role}，和我首夜结果一致。请你把今晚的查验用在其他人身上——{target}这边已经排除了。",
    ]
    GOOD_WASHERWOMAN_POISON_SUSPECT = [
        "我是洗衣妇。{target1}和{target2}两人均不认我得知的镇民{ww_role}，怀疑首夜被投毒者下毒导致信息失真。你首夜查到的爪牙是谁？我们合并线索锁定投毒者，今夜请占卜师查验{target1}、{target2}身份。",
        "出问题了：{target1}和{target2}都不承认{ww_role}这个身份。要么我是酒鬼，要么首夜被投毒者下毒。你是调查员，你查到的爪牙是谁？如果是投毒者，我的信息就可能被污染了——必须优先排查。",
    ]
    GOOD_WASHERWOMAN_BARON_SUSPECT = [
        "我的两名目标{target1}和{target2}全部不认身份，怀疑本局存在男爵、我是酒鬼。请你告知本局外来者数量，我们统计全场跳外来者的玩家人数。如果外来者数量比预期多2以上，男爵基本确定在场。",
        "图书管理员，我需要你的信息。我首夜查到{target1}或{target2}是{ww_role}，但两人都否认。如果本局有男爵，我可能是酒鬼——请告诉我你查到的外来者情况。如果外来者数量异常，就能确认男爵在场、我的信息是假的。",
    ]
    GOOD_WASHERWOMAN_VIRGIN_PLAN = [
        "我计划提名贞洁者自证。如果我没被处决，有三种可能：①我是酒鬼；②贞洁者是酒鬼；③贞洁者昨夜被投毒者下毒。请图书管理员统计外来者数量、调查员盘投毒者爪牙，三方合并逻辑。",
        "信息混乱，我打算提名贞洁者来验证。结果出来后我们一起分析：未被处决有三种解释，需要你从你的视角帮我排查——看看是酒鬼、投毒者还是贞洁者自身的问题。",
    ]

    # ========== 善良私聊 ==========
    GOOD_PRIVATE_OPEN = [
        "你好{listener}，我是{role}。现在情报还不多，我想先听听你的判断——目前你怀疑谁？为什么？我觉得互相交换初步印象很重要，能帮我们尽快锁定目标。",
        "{listener}你好，我是{role}。第一天信息有限，但我注意到一些细节——{claim_str}里面有些人的声明不太自然。你同感吗？",
        "{listener}，我刚整理了一下笔记：{my_note}。你那边有什么发现？",
        "刚才你说的{ref}，我也想聊聊这个话题。我的看法是{target}确实值得重点观察，你觉得呢？",
    ]

    GOOD_PRIVATE_DISCUSS = [
        "来，我们对对信息。我的{role}技能告诉我一些事情：{info_share}。你觉得这意味着什么？结合{vote_str}来分析，重点嫌疑人应该已经很明显了。",
        "我越来越觉得{target}有问题。理由是：他的声明是{claim}，但他的{vote_str}完全不符合这个身份的行为模式。一个真正的{claim}不会这样投票。你分析一下是不是这个理？",
        "我们来盘一下目前的局势。{claim_str}里面有几个矛盾点特别值得关注。第一，{contradict_str}；第二，{target}的投票轨迹跟他的声明对不上。我的结论是{target}至少需要被好好审一审。",
        "我的笔记里记了几件事：{my_note}。结合你的信息来看，你觉得我是不是多疑了？",
        "我在想{target}的行为能不能用{claim}来解释——他自称是{claim}，但如果是真{claim}，应该会{claim}应该做的事，而不是像现在这样一直打太极。你觉得我的判断对吗？",
        "注意{target}的回应模式：第一次被质疑{claim}声明时他给了详细解释，但第二次被问到具体细节时回答明显缩短了。如果是真{claim}，应该每次都能给出同样的细节才对。这种信息密度递减的模式值得警惕。",
        "你刚才提到{ref}，这一点我也注意到了。不过我的角度不太一样——我觉得这恰恰说明{target}的可疑程度比想象中更高。",
    ]

    GOOD_PRIVATE_PERSUADE = [
        "我知道你可能还在犹豫，但我真的建议你今天投{target}。理由我再说一遍：{claim_str}和{vote_str}交叉验证的结果指向他。即使错了，我们明天也能从他翻出的身份继续推理——这比投一个不明不白的人强得多。",
        "听我分析完再做决定：如果{target}是好人翻出来，那投他的票数分布能告诉我们很多信息——邪恶方在投票时往往会抱团，我们可以从票型反推。所以投{target}的风险是可控的，收益却是巨大的。",
    ]

    GOOD_PRIVATE_COORDINATE = [
        "今天的投票策略：我们统一投{target}。我负责去说服其他人，你负责观察那些不愿意投{target}的人——他们可能就是我们要找的下一批目标。记住：邪恶方的最大弱点就是他们不敢投自己的队友。",
        "分头行动：我盯着{target}的发言找漏洞，你去跟其他人沟通统一票型。今天的目标很明确——出{target}。如果他翻出是好人，我们就从保过他的人里继续盘。",
    ]

    GOOD_PRIVATE_CLOSING = [
        "今天就到这。我们的共识是：{target}是第一嫌疑人。明天根据处决结果再调整策略。如果{target}是邪恶翻出来的，好事；如果是好人翻出来的，那投他票最快的那几个人就是下一轮的目标。",
        "好的，信息对完了。保持联系，有新发现马上沟通。记住：不要单独行动，我们好人的力量在于团结。分开就容易被邪恶逐个击破。",
        "我记一下今天的重点：{my_note}。明天继续跟进，有新情况随时找我。",
    ]

    GOOD_DEEP_ACTION = [
        "我有个大胆的想法：我来假跳一个信息位，看看谁会上钩。我会在公聊说我是占卜师查到了{target}有问题——如果{target}反应激烈，他很可能就是邪恶。如果{target}很冷静地反驳，那他可能是好人。演技和反应之间是有区别的。",
        "冒险方案：今天大家先不投{target}，让他多活一轮。这轮里我假装信任他，看他会不会露出马脚。有时候给邪恶一点空间，他们反而会自爆。",
    ]

    GOOD_INTERROGATE = [
        "{target}，你的{claim}声明有几个问题我想请教：第一，你这个信息的来源是什么？第二，你之前说{claim}的时候和现在的说法有出入，你能解释一下吗？第三，你的{vote_str}为什么会这样投？请正面回答，不要转移话题。",
        "{target}，我就直问了：你敢不敢发毒誓说你是好人？如果你的回答是'为什么不敢'而不是'我发誓'，那你的犹豫已经说明了一切。真正的好人面对质疑时的第一反应是证明自己，而不是反问质疑者。",
    ]

    GOOD_CONFRONT = [
        "我忍你很久了{target}。你的发言从头到尾都是漏洞：第一，你的{claim}声明前后不一致；第二，你的{vote_str}完全不符合好人的投票逻辑；第三，你一直在转移话题而不是正面回应质疑。你还有什么好说的？",
        "{target}，我现在公开质疑你。如果你真是好人，请用你的{role}技能证明给我看——说出你的具体信息。如果你说不出来，对不起，今天你必须出局。",
    ]

    GOOD_INFO_PROBE = [
        "我其实有特殊信息渠道——之前没跳是怕被刀。现在我公开：我查到的信息和{target}的声明有冲突。{target}说自己是{claim}，但可靠的信息显示他不是。大家自己判断。",
    ]

    GOOD_NOINFO_PROBE = [
        "我虽然没有查验技能，但我的逻辑告诉我{target}有问题。理由：{vote_str}里他的投票全是在跟风，没有一次是独立判断的。好人即使不确定也会有自己的判断，只有邪恶才会无脑跟票。",
        "综合观察下来，{target}的发言有问题。他总是回避关键问题，别人质疑他什么他就绕圈子。好人被质疑会急着解释，他却在反问质疑者——这是邪恶常用的手段。",
        "我注意到{target}的发言模式很可疑。他的每一句话都在'自保'而不是在'找狼'——真正的好人关心的是找出邪恶，而不是反复强调自己是好人。",
        "我对{target}的{claim}声明持保留态度。理由很具体：他的信息输出缺少一个真正信息位该有的犹豫和核实过程——{contradict_str}。建议今天重点关注他的发言，明天如果有新信息能交叉验证再下结论。",
        "对比了几个人的发言，{target}是最违和的。他的关注点全在自证清白上，而不是在分析局势上——好人和邪恶最大的区别就是关注点不同。",
        "我盘了一下{target}的时间线：他先说自己是{claim}，但在被质疑后又改口说'可能看错了'。一个真正的{claim}不可能看错自己的技能结果——他在临时编词。",
        "观察{target}的发言轨迹：他被第一次问到时给出了{claim}相关的解释，第二次追问具体动作时回答变笼统了。一个持续查验的信息位应该能持续产出新细节。如果第三轮还拿不出新信息，建议直接处决。",
    ]

    GOOD_NOINFO_ANALYZE = [
        "作为没有查验能力的平民，我选择用逻辑找出邪恶。我的方法很简单：观察每个人的发言和投票是否一致。{target}的问题是他说自己是{claim}，但他的{vote_str}完全不符合{claim}这个身份的利益取向。",
    ]

    # ========== 邪恶公聊 ==========
    DEMON_PUBLIC_ATTACK = [
        "我说一下{target}吧。他自称{claim}，但从{vote_str}来看，他的投票和这个身份的玩家通常的投票方向不太一样——不是说一定有问题，但这个偏差值得大家关注一下。{baron_tip}",
        "观察了几轮，{target}的发言让我有点在意。他说自己是{claim}，但{contradict_str}。如果他是真的{claim}，这几个点应该能解释清楚才对。建议大家今天盘一下他，至少让他把逻辑讲明白。{baron_tip}",
        "我不太想直接踩人，但{target}的几处细节确实让我不太舒服。{fake_info}。当然也可能是我多想了，大家可以自己判断。我个人倾向于今天先查他。{baron_tip}",
        "提一个可能的方向：{target}的{claim}声明和{vote_str}放在一起看，会有一点违和感。我不确定这是不是我的错觉，但如果其他人也有类似感受，这个人就值得认真盘了。{baron_tip}",
        "{claim_str}里面，{target}的定位让我有点困惑——他报的身份和实际表现之间存在落差。{fake_info}。我觉得至少有理由让他多解释几句。{baron_tip}",
        "我注意到{target}的一个细节：{my_note}。{fake_info}。单看这一个点不说明什么，但结合其他观察来看，概率上他确实比其他人更可疑一些。{baron_tip}",
        "说一个不一定对的感觉：{target}在不同轮次的发言节奏有个微妙变化。{fake_info}。我没有确凿证据，只是一直在观察他。建议先不要处决，但今天至少让他聊清楚。{baron_tip}",
    ]

    DEMON_PUBLIC_SOFT = [
        "我是{bluff}。{fake_info}目前我还没有特别确定的结论，但{target}有几个小细节让我一直在留意。不一定有事，但我觉得至少值得多观察一轮。{baron_tip}",
        "我是{bluff}。{fake_info}说一个不算证据的现象：{target}和{other}在讨论时的互动方式和其他人不太一样——不是说他们在串供，只是节奏上确实有点特殊。大家可以留意一下。{baron_tip}",
        "我是{bluff}，还在整理信息。{fake_info}。目前初步感觉，{target}是让我最拿不准的一个——他的声明和{vote_str}之间有一些需要解释的地方。不急下定论，先观察。{baron_tip}",
        "我是{bluff}。{fake_info}我不太想直接对{target}下判断，但他和{other}在某些话题上的节奏比较一致——可能只是巧合，但如果不止我一个人这么觉得，就值得关注了。{baron_tip}",
    ]

    MINION_PUBLIC_ATTACK = [
        "我是{bluff}，分享一下我注意到的几件事。{fake_info}。这些观察不一定完全准确，但概率上看，{target}确实比其他人更值得关注。大家帮忙一起判断一下。{baron_tip}",
        "聊一下{target}吧，他自称{claim}但有个细节让我有点在意：{accusation}。我不会说这一定是假的，但和真{claim}的表现确实有点区别。{fake_info}建议今天至少让他解释解释。{baron_tip}",
        "我对{target}一直有些疑惑——不是针对他个人，而是{contradict_str}这个点在逻辑上不太顺。{fake_info}。如果他是好人翻出来，我道歉，但在查清之前我觉得有必要提出来。{baron_tip}",
        "说句实话，我本来不想踩人，但{vote_str}和{target}自称的{claim}之间确实存在某种不协调。{fake_info}。我倾向于今天先盘他，至少听他怎么解释这个矛盾。{baron_tip}",
        "我不太确定，但{target}的发言模式和我之前遇到的一种情况很像——{fake_info}。不一定对，但如果不查清楚会很被动。大家觉得呢？{baron_tip}",
        "我是{bluff}，有几个观察想和大家对一下：{fake_info}。这里面的关键人物是{target}。如果有人觉得我的判断有偏差，欢迎指出来，但我个人认为这个人今天至少要交代清楚。{baron_tip}",
        "我其实一直在观察{target}。{fake_info}。{claim_str}里面我觉得最需要验证的就是他——不是因为他表现最差，而是因为他的信息跨度最大，一旦错判影响也最大。建议大家优先验证他。{baron_tip}",
    ]

    # ========== 身份对跳模板 ==========
    CLAIM_BATTLE_HUNTSMAN = [
        "{battle_target}说他是猎手？巧了，我也是猎手。昨晚我开枪打了{battle_victim}，他没死——说明{battle_victim}是士兵或者恶魔。{battle_target}冒充我只有一个解释：他是邪恶方想混进好人队伍。",
        "有意思，{battle_target}也自称猎手。那请你告诉大家：你昨晚打的是谁？打中了吗？我的子弹昨晚打中了{battle_victim}，他没死——要么是士兵，要么是邪恶。{battle_target}连开枪目标都说不出来，那他就是假猎手。",
        "我才是真正的猎手。{battle_target}冒充我只有一个目的：混淆视线，给邪恶制造生存空间。大家想想，如果他真是猎手，为什么不早点报信息？因为他根本没开枪！",
    ]
    CLAIM_BATTLE_SOLDIER = [
        "{battle_target}自称士兵？那巧了，我也是士兵。昨晚恶魔刀了我但我没事——这就是士兵的铁证。{battle_target}如果是真士兵，他应该跟我一样活蹦乱跳才对。他为什么需要强调自己是士兵？因为他在心虚。",
        "两个士兵？看来邪恶方找不到更好的身份编了。我活了这么多天就是最好的证明——恶魔刀不死我。{battle_target}如果是士兵，请说出你哪晚被刀的——他连这都编不出来。",
    ]
    CLAIM_BATTLE_MONK = [
        "{battle_target}说他每晚保护人？我才是真僧侣！我昨晚保护了{defend_target}——他没事，说明我的保护生效了。但就算我不保护他，他也死不了——因为他根本不是僧侣，恶魔不会刀他。",
        "僧侣的身份也有人敢冒充？我昨晚守了{defend_target}，他没事。{battle_target}，你守了谁？你说不出来是吧？因为僧侣每晚选人保护是有记录的，编不了。",
    ]
    CLAIM_BATTLE_MAYOR = [
        "我才是镇长。{battle_target}冒充我，无非是想在决赛圈拿到关键一票。但真正的镇长有我这一票就够了——等只剩三人时大家自然知道谁真谁假。{battle_target}，你敢等到那一步吗？",
        "我是镇长，我活着就能在三人局直接获胜。{battle_target}冒充我，等于在帮邪恶偷走好人的胜利条件。今天先不要处决任何镇长——等缩小范围后，真假自然分明。",
    ]
    CLAIM_BATTLE_SEER = [
        "{battle_target}也自称占卜师？真巧，我也是昨晚验了人的占卜师。我的占卜结果是：{battle_target}身上有恶魔反应！他如果是真占卜师，为什么我会查到他？答案只有一个——他是假占卜师、真恶魔！",
        "我才是真占卜师，我昨晚验了{checked1}和{checked2}——{result}。{battle_target}宣称的查验结果和我的完全对不上。占卜师一晚只能验两个人，我们俩之间必有一假。",
    ]
    CLAIM_BATTLE_GENERIC = [
        "{battle_target}自称{battle_role}？那我也是{battle_role}。一个人不可能有两个真身——我们两个里必定有一个假货。我建议大家都仔细回想一下{battle_target}之前的发言，答案很明显。",
        "有意思，{battle_target}也跳了{battle_role}冒充我。如果你真是{battle_role}，请回答我一个问题：你昨晚做了什么？说不出细节对不对？因为真{battle_role}才有具体操作。",
        "场上出现了两个{battle_role}。真的{battle_role}一定能说出自己的确切信息，敢跟我对质细节吗？你不敢，因为你编不出来。投票处决{battle_target}，假的露馅后真的一目了然。",
    ]

    # ========== 洗衣妇公聊 ==========
    GOOD_PUBLIC_WASHERWOMAN_CLEAR = [
        "我是洗衣妇。我的首夜信息确认{target1}或{target2}之中有{ww_role}——{target}本人已认领，信息链吻合。{cross_ref}建议今天从外置位盘，{target}暂排好人。{drunk_warning}",
        "洗衣妇报信息：我查到{target1}或{target2}之中有一个是{ww_role}，{target}本人已认领。{cross_ref}建议集中精力盘其他人。{drunk_warning}",
        "公聊同步：首夜查验{target1}/{target2}中有{ww_role}，{target}已确认认领。{cross_ref}这是我的信息链，请大家不要浪费处决机会在{target}身上。{drunk_warning}",
    ]
    GOOD_PUBLIC_WASHERWOMAN_CONFUSED = [
        "我是洗衣妇！我的信息显示{target1}或{target2}是{ww_role}，但两人都不认领。这有两种可能：要么我是酒鬼信息有误，要么有人在撒谎——后者的可能性更大！建议从{target1}和{target2}中排查，谁不认身份谁就有问题。",
        "洗衣妇同步：我的查验结果是{target1}或{target2}之中有{ww_role}。两人都不承认，恰恰说明至少有一人在撒谎——真身份的人没有理由隐藏。大家今天重点关注这两个位置。",
    ]
    GOOD_PUBLIC_WASHERWOMAN_VIRGIN = [
        "我提名贞洁者自证后未被处决。三种可能性：①我是酒鬼；②贞洁者是酒鬼；③贞洁者昨夜被投毒。请图书管理员统计外来者数量、调查员排查投毒者爪牙。等我方信息合并后再向全场汇报结论。",
        "贞洁者测试完成，我没死。现在需要图书管理员和调查员从我说的三个方向排查。在结论出来之前，不建议急推任何人。",
    ]

    # ========== 善良公聊·信息角色 ==========
    GOOD_PUBLIC_EMPATHY = [
        "我是共情者！昨晚我左右邪恶数为{e}，{neighbor_info}。如果{e}大于0，我们今天就一定要从这两个邻居开始盘！大家结合他们今天的发言和{vote_str}来交叉验证——不是凭感觉，是凭数据。{recluse_warning}",
        "共情者报数：邪恶数{e}！{neighbor_info}这个{e}意味着至少有一个邪恶就在这两个位置。我建议今天就从他们中间出一个。{recluse_warning}",
    ]
    GOOD_PUBLIC_SEER = [
        "我是占卜师，昨晚查验了{chosen0}和{chosen1}，{result}。{demon_verdict}我建议先从{chosen0}开始盘——如果他是好人翻出来，那{chosen1}就是铁邪恶。{drunk_warning}{recluse_warning}",
        "占卜师有重要发现！{chosen0}和{chosen1}——{result}。{suggestion}我的查验不会骗人，大家信我的判断。{drunk_warning}{recluse_warning}",
    ]
    GOOD_PUBLIC_INVESTIGATOR = [
        "我是调查员！我查出{target}是{role}——这就是爪牙！证据确凿，今天必须处决他！如果他是好人翻出来，我主动背锅。{cross_ref}{drunk_warning}{recluse_warning}",
        "调查员有重要发现：我的首夜查验显示{target}之中有{role}。这是我的技能铁证。{cross_ref}建议大家今天从这两个人中排查。{drunk_warning}{recluse_warning}",
        "首夜调查员信息已确认：{target}之中有{role}，不在范围内的人我先不看。请大家聚焦这两个位置排查。{cross_ref}{drunk_warning}{recluse_warning}",
    ]

    # ========== 厨师公聊：数据驱动推理 ==========
    CHEF_PUBLIC_DAY1 = [
        "我是厨师，首夜信息显示相邻邪恶对数为{chef_val}。这意味着我的邻居{neighbor_list}中{chef_analysis}。{cross_ref}大家可以参考这个信息来排坑。",
        "厨师情报：相邻邪恶对数{chef_val}。{neighbor_claims}。如果{chef_val}==0，说明邪恶之间不相邻，可以排除邻居共边的组合。大家盘位置时可以把这个因素考虑进去。",
        "我厨师首夜查到{chef_val}对相邻邪恶。这个数字意味着：{chef_analysis}。{cross_ref}欢迎大家一起分析。",
    ]
    CHEF_PUBLIC_LATER = [
        "我再重申一下厨师的初始信息：相邻邪恶对数为{chef_val}。结合这几轮的发言和投票来看，{neighbor_list}里面有人的行为模式值得深挖——厨师数据不会说谎，它缩小了我们排查的范围。",
        "回顾一下厨师首夜结果：{chef_val}对相邻邪恶。再看现在的{neighbor_claims}，我倾向于今天从邻居中出一个。厨师的初始数据和后续发言相互印证。",
    ]
    CHEF_PUBLIC_LATER = [
        "我再重申一下厨师的初始信息：相邻邪恶对数为{chef_val}。结合这几轮的发言和投票来看，{neighbor_list}里面有人的行为模式值得深挖——厨师数据不会说谎，它缩小了我们排查的范围。",
        "回顾一下厨师首夜结果：{chef_val}对相邻邪恶。再看现在的{neighbor_claims}，我倾向于今天从邻居中出一个。厨师的初始数据和后续发言相互印证。",
    ]

    # ========== 镇长公聊：带队整合 ==========
    MAYOR_PUBLIC = [
        "大家好，我是镇长。我来整合一下当前的信息：{claim_str}。{vote_str}。{expected_outsider_info}我的建议是今天集中处决{target}，理由：第一，{claim_str}中他的声明和谁对不上；第二，{vote_str}里面他的投票趋势和全场不同；第三，{stage_evidence}。请各位统一票型。{outsider_hint}",
        "我是镇长。当前存活玩家中，{claim_str}里有几个信息点值得关注：{contradict_str}。{info_or_opinion}。我提议今天出{target}——如果错了，我负全责。所有人都跟我的票走，不要分散。{outsider_hint}",
        "镇长归票时间：综合{claim_str}和{vote_str}，{target}是今天的最佳处决目标。理由：{stage_evidence}。我随时可以自证（三人存活时邪恶输），请大家相信我这次归票。{outsider_hint}",
        "我来理一下思路。{claim_str}里面最让我不安的是{target}——他的声明和{vote_str}有冲突。{info_or_opinion}。我建议今天就投{target}，有不同意见的可以私聊我讨论。{outsider_hint}",
    ]

    # ========== 士兵公聊：强势站边 ==========
    SOLDIER_PUBLIC = [
        "我是士兵，恶魔刀不死我。我来说句直白的：{target}有问题。{claim_str}里他的声明站不住脚——{info_or_opinion}。我不怕刀，所以我敢直接点名。今天出{target}，我担保他不是好人。",
        "士兵在此。我不需要拐弯抹角——{target}的可疑点太明显了：{stage_evidence}。{info_or_opinion}。谁要是保{target}，我连你一起怀疑。恶魔不敢刀我，所以我怎么说都安全。",
        "我没那么多弯弯绕绕——{target}就是有问题，{claim_str}里面的矛盾已经够了。{vote_str}投票记录也是铁证。我是士兵，死了也是为好人挡一刀，但{target}今天必须出局。",
    ]

    # ========== 送葬者公聊：死后翻牌锚定 ==========
    GOOD_PUBLIC_UNDERTAKER = [
        "我是送葬者！昨天被处决的{exec_role}身份是{exec_role}，属于{exec_team_label}。{exec_verdict}我以送葬者的名义确认，这个信息绝对准确。请大家根据这个结果重新盘票型——那些推波助澜投票的人值得重点关注。",
        "送葬者报身份：昨天出局的是{exec_role}，{exec_team_label}。{exec_verdict}这是铁证，我的技能不会错。基于这个结果，之前保{exec_role}的人要重点盘，踩{exec_role}的人可以考虑排好。",
        "死者身份已确认：{exec_role}，{exec_team_label}。{exec_verdict}送葬者的信息是可靠的，我建议好人以此为锚点重新评估局势。",
    ]

    # ========== 守鸦人公聊：死后查验 ==========
    GOOD_PUBLIC_RAVENKEEPER = [
        "我是守鸦人，死前查验了{rk_target}——他是{rk_role}，属于{rk_team}！我死之前查到的就是铁证。大家用我的信息去盘：{rk_target}如果是邪恶必须今天出局，如果是好人就要反推出谁在带节奏。",
        "守鸦人最后一验：{rk_target}是{rk_role}（{rk_team}）。我的信息绝对可信——没人能在死后伪造查验结果。建议好人以这条信息为基础重新排坑。",
    ]

    # ========== 图书管理员公聊：核对外来者 ==========
    GOOD_PUBLIC_LIBRARIAN = [
        "我是图书管理员。{lib_info}。{anchor_explanation}希望大家报一下自己的身份，我来核对总数是否正常。如果外来者数量对不上，说明可能有男爵在场或者有人冒充。",
        "图书管理员报告：{lib_info}。{anchor_explanation}请大家自报一下身份类别（镇民或外来者），我来统计一下全场的外来者总数是否和预期一致。",
    ]

    # ========== 图书管理员公聊：核对外来者数量 ==========
    GOOD_PUBLIC_LIBRARIAN_DATA = [
        "我是图书管理员。{lib_info}大家对照一下：目前有几个人跳了外来者？如果数量不对，说明要么有人冒充镇民，要么有男爵在场。",
        "图书管理员报信息：{lib_info}我建议大家都报一下自己的身份类别（镇民/外来者），我们来核对总数。数量对不上就是有问题的信号。",
        "我是图书管理员，我的信息是：{lib_info}请大家注意——如果外来者数量超出预期，说明可能有男爵在场上，意味着好人的信息可能被错误信息干扰了。",
    ]

    GOOD_PUBLIC_ANALYSIS = [
        "大家好，我是{role}。我来分析一下目前的局势：{info_or_opinion}。{stage_evidence}。{outsider_hint}{expected_outsider_info}我建议大家都把自己的怀疑说出来，信息越多，我们越容易找到突破口。{opinion}。",
        "现在是公聊时间，我分享一下我的推理：{info_or_opinion}。目前{claim_str}，而投票记录显示{vote_str}。{stage_evidence}。{outsider_hint}{expected_outsider_info}这些线索综合来看，我的{opinion}。希望大家也分享一下自己的观点。",
        "根据我的记录：{my_note}。{stage_evidence}。大家怎么看？",
        "我来盘一下目前的局面。{info_or_opinion}。{claim_str}，{vote_str}。{stage_evidence}。{outsider_hint}{expected_outsider_info}综合这些，我倾向{target}有问题——当然我也欢迎不同意见的讨论。",
        "分享一下我的观察：{info_or_opinion}。{claim_str}里面有几个点值得注意。{stage_evidence}。{outsider_hint}{expected_outsider_info}{opinion}。大家怎么看？",
    ]

    # ========== 死者发言 ==========
    DEAD_UNDERTAKER = [
        "我是送葬者，昨天被处决的是{exec_role}。{verdict}我建议大家复盘一下投票——那些带头投他的人里必然有邪恶在推波助澜。特别是{vote_str}里面跟票最快的那几个。",
    ]
    DEAD_RAVENKEEPER = [
        "我是渡鸦！我死前查验了{rk_target}——他是{rk_role}，属于{team}！大家注意，我的信息是准确的——我死之前查到的就是铁证。{rk_target}如果是邪恶，今天必须处决他！",
    ]
    DEAD_ANALYSIS = [
        "我已经是个死人了，我的判断应该更有参考价值。我死前最怀疑{target}，理由是我观察到{claim_str}里面的矛盾点和{vote_str}的异常。活着的兄弟们，帮我报仇。",
        "死者的话最客观。我回顾了整个游戏过程，{target}的嫌疑最大。他的声明是{claim_str}，但他的行为完全对不上。活着的各位，别让我的死白费。",
    ]

    # ========== 提名/辩护 ==========
    NOMINATION = [
        "我提名{target}。理由：第一，他的{claim}声明与{contradict_str}对不上；第二，{vote_str}里面他投的票和全场趋势不一致；第三，{claim_str}中他的定位有问题。请大家投票处决。",
    ]
    NOMINATION_EVIL = [
        "我提名{target}。{reasons}这是铁证。请大家投票。",
        "我提名{target}——理由很充分：{reasons}。我拿我的身份担保，{target}绝对不是好人。该投票了。",
        "提名{target}。{reasons}我不需要再多说了，证据摆在这里。谁反对可以站出来对质。",
    ]
    DEFENSE_INFO = [
        "大家冷静！我是{role}，我的技能告诉我{info_share}。处决一个信息位对好人来说是巨大的损失。请大家想清楚——杀了我，邪恶就少了一个障碍。",
    ]
    DEFENSE_EVIL = [
        "我是{claim}。{nominator}说我有问题，但他的理由站不住脚：他指控我的依据根本不成立。大家想想，如果我真有问题，{nominator}为什么不拿出实锤证据？因为他拿不出来——因为他自己才是心中有鬼的那个。我建议今天先查{alternative}，他才是真正可疑的人。",
        "我是{claim}，我清楚自己是好人。{nominator}对我的指控经不起推敲——我一没有投票异常，二没有身份矛盾，全是{nominator}单方面的猜测。一个真正的坏人会用这么空泛的理由指控我吗？我觉得{nominator}自己才值得被查。",
        "我是{claim}。{nominator}急着处决我，恰恰暴露了他的问题——他不敢让我活到明天，因为我知道更多信息。看看今天是谁在带节奏、是谁在冲票——这些人才是真正的可疑对象。",
        "我是{claim}。{nominator}指控我全靠推测，没有一条是实锤。这个游戏靠证据说话，不是靠感觉定罪的。我建议好人今天先投{alternative}，明天再盘我不迟。",
        "我是{claim}。{nominator}编了一大堆理由想让大家信服，但你仔细看就会发现全站不住脚：他说的第一点不存在、第二点是曲解、第三点是假设。全是空中楼阁。真正该被查的是{alternative}，大家注意观察他的反应。",
    ]
    DEFENSE_GOOD = [
        "我是{role}。我重申我的身份——我是好人阵营的{role}。{nominator}指控我，但理由完全是空泛的推测，没有任何实际行为能支撑他的结论。我的{vote_str}和{claim_str}可以证明我的立场。如果要处决，我建议先查{alternative}——他今天的发言才真正有问题。",
        "我是{role}，我的身份经得起验证。{nominator}的指控有几点站不住脚：首先，他说的问题并不存在；其次，{vote_str}显示我一直在支持好人；最后，{nominator}自己的{claim}声明本身就值得怀疑。与其在我身上浪费处决机会，不如去盘{alternative}，他才是更需要被查的人。",
        "我是{role}。我理解大家会怀疑我，但请看看事实：{claim_str}中我没有身份矛盾，{vote_str}中我没有异常投票，{nominator}对我的指控也不是基于实际行为而是感觉。我建议今天从{alternative}开始排查——一个处决机会用在我身上太浪费了。",
        "我是{role}，我的身份就是这个。{nominator}指控我，但他的论据全部站不住脚——他只是觉得'可疑'，却说不清到底哪里可疑。这对一个好人是致命的误判。我提议：如果大家不放心，明天可以再提我，但今天请集中查{alternative}，他身上的疑点更多。",
    ]

    @classmethod
    def get_filled(cls, category, used=None, **kwargs):
        templates = getattr(cls, category, None)
        if not templates:
            return ""
        if used is None:
            used = set()
        available = [t for t in templates if t not in used]
        if not available:
            available = templates
            used.clear()
        t = random.choice(available)
        used.add(t)
        try:
            return t.format(**kwargs)
        except (KeyError, ValueError):
            import re
            for ph in re.findall(r'\{(\w+)\}', t):
                if ph not in kwargs:
                    kwargs[ph] = "某人"
            return t.format(**kwargs)

    @classmethod
    def naturalize(cls, text, personality=None):
        p = personality or get_current_personality()
        if p:
            return p.apply_to_text(text)
        return cls._naturalize_default(text)

    @classmethod
    def _naturalize_default(cls, text):
        r = random.random()
        if r < 0.20:
            op = random.choice(["嗯……", "那个……", "怎么说呢……", "其实吧", "哎", "老实说", "我直接说吧"])
            text = f"{op}，{text}"
        elif r < 0.33:
            cl = random.choice(["吧", "啊", "嘛", "呢", "哈", "哦"])
            if len(text.rstrip()) > 0 and text.rstrip()[-1] in "！。？吗的":
                text = text.rstrip()[:-1] + f"{cl}。"
            else:
                text = f"{text}{cl}。"
        elif r < 0.45:
            ins = random.choice(["说实话", "我感觉", "我觉得吧", "你想想", "讲真"])
            if len(text) > 0 and "，" in text:
                a, b = text.split("，", 1)
                text = f"{a}，{ins}，{b}"
        return text
