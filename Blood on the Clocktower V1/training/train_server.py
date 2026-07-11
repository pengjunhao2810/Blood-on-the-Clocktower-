"""
AI对话训练服务器（端口5001）
完整分支训练系统 V2 - 22分支 + 上下文记忆
"""
import sys, os, json, random
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '本地训练的ai', 'werewolf_ai'))

from flask import Flask, jsonify, request, render_template_string
app = Flask(__name__)
TRAINING_DATA_FILE = os.path.join(os.path.dirname(__file__), 'training_data.jsonl')

ROLES = {
    "占卜师":{"team":"townsfolk","desc":"每夜可查验一名玩家身份"},
    "共情者":{"team":"townsfolk","desc":"每夜得知与邪恶阵营相邻人数"},
    "调查员":{"team":"townsfolk","desc":"开局得知两名玩家中有一名是特定邪恶"},
    "洗衣妇":{"team":"townsfolk","desc":"开局得知两名玩家中有一名的身份"},
    "图书管理员":{"team":"townsfolk","desc":"开局得知两名玩家中有一名的身份"},
    "厨师":{"team":"townsfolk","desc":"开局得知相邻邪恶对数"},
    "送葬者":{"team":"townsfolk","desc":"每夜得知当天被处决玩家的身份"},
    "守鸦人":{"team":"townsfolk","desc":"若你夜晚死亡，可查看一名玩家身份"},
    "士兵":{"team":"townsfolk","desc":"恶魔无法杀死你"},
    "猎手":{"team":"townsfolk","desc":"白天可发动技能指杀小恶魔"},
    "市长":{"team":"townsfolk","desc":"3活玩家无人处决则好人获胜"},
    "僧侣":{"team":"townsfolk","desc":"每夜可保护一名玩家免遭恶魔杀害"},
    "圣女":{"team":"townsfolk","desc":"首次被提名时终止当天提名"},
    "酒鬼":{"team":"outsider","desc":"你以为自己是镇民，实际是酒鬼"},
    "陌客":{"team":"outsider","desc":"可能被判定为邪恶方"},
    "圣徒":{"team":"outsider","desc":"若被处决则好人失败"},
    "隐士":{"team":"outsider","desc":"可能被判定为邪恶方"},
    "投毒者":{"team":"minion","desc":"每夜可毒害一名玩家使其获假信息"},
    "间谍":{"team":"minion","desc":"可查看全部角色，登记为镇民"},
    "红唇女郎":{"team":"minion","desc":"恶魔邻位时被视为恶魔"},
    "男爵":{"team":"minion","desc":"增加两名外来者"},
    "小恶魔":{"team":"demon","desc":"每夜可杀死一名玩家"},
}
TEAM_LABELS = {"townsfolk":"善良镇民","outsider":"外来者","minion":"爪牙","demon":"恶魔"}

# ============== 完整分支库 V2 ==============
BRANCHES = {
    # ── 1. 问候 ──
    "GREETING": {
        "trigger": ["你好","hello","hi ","嗨","哈喽","hey","早啊","晚上好","下午好","在吗"],
        "understand": ["对方在打招呼问候"],
        "reply": ["你好！我是{role}（{team}），{desc}。你是谁？","嗨！我是{role}，{team}。你来找我有什么事？","你好啊。我是{role}，{team}。你是什么身份？"],
        "reply_evil": ["你好啊，我是{role}。你找我有什么事？","嗨！我是{role}。你是自己人还是路人？","你好。我是{role}。你是什么来路？"],
        "question": ["你是什么身份？","你来找我有什么事？","你有什么信息要分享吗？"],
    },
    # ── 2. 问AI身份 ──
    "ASK_WHO_AM_I": {
        "trigger": ["你身份","你是？","身份是","份是啥"],
        "understand": ["对方在询问我的身份"],
        "reply": ["我是{role}（{team}），{desc}。","我是{role}，属于{team}阵营。你呢？","我的身份是{role}，{team}。你问这个是想确认什么？"],
        "question": ["你呢？你是什么身份？","你问我是想交换信息吗？","你相信我吗？"],
    },
    # ── 3. 对方隐藏身份 ──
    "HIDE_IDENTITY": {
        "trigger": ["猜猜看","不告诉你","秘密","你猜","保密","不方便说","无可奉告","猜猜","说你的","自己猜","你先说","你自己","先说你","我不说"],
        "understand": ["对方在回避身份问题，不愿意直接透露"],
        "reply_good": ["你不愿意说？那我尊重你。但你至少得让我知道你是好人方的吧。","你连身份都不敢说，这让我很难信任你。","好吧，你不说我也不逼你。但你总得给我点信息。"],
        "reply_evil": ["哈哈，明白，你不说我也理解。那你打算怎么配合？","你藏身份是对的，我也在藏。我们暗处行动更好。","行，你不暴露身份更好。我们在暗处更方便。"],
        "question": ["那你至少能告诉我你是哪边的吗？","你有什么信息可以分享？","你觉得谁是可信的？"],
    },
    # ── 4. 声称身份 ──
    "ROLE_CLAIM": {
        "trigger": ["__ANY_ROLE__"],
        "understand": ["对方声称自己是【{claim}】，→ 若我邪恶：善良角色有威胁；若我善良：需判断真假"],
        "reply_good": ["你是{claim}？那你能提供具体信息证明吗？","你说你是{claim}，那你昨晚/今天有什么发现？","{claim}吗……你查到了什么能告诉我的？"],
        "reply_evil": ["哦，你是{claim}？如果你是信息位，那你查到了什么？","{claim}啊……你的能力对我们很关键，你有什么结论？","你说你是{claim}，那你有什么依据让我相信你？"],
        "question": ["你真的是{claim}吗？能证明一下？","你作为{claim}有什么具体信息？","你觉得我应不应该相信你？"],
    },
    # ── 5. 分享信息 ──
    "SHARE_INFO": {
        "trigger": ["查到","验了","得知","结果是","昨晚看","我查到","我验了","我的结果是","分享信息","交换信息","告诉你信息","了那个","3有问","他有问","看到他","得知玩","某有问","那个人","得知那","验了某","验了那","知那个","家3有","某某有","我得知","个人有","知玩家","知某某","晚我看","了他有","了某某","人有问","到玩家","看到某","我看到","看到那","到他有","得知他","验了玩","看到玩","得知某","知他有","到某某","到那个","验了他","昨晚我","了玩家","查到玩","是投毒","2是小","是爪牙","投毒者","是好人","2是爪","2是好","小恶魔","2是投","是小恶"],
        "understand": ["对方在分享查验/信息结果"],
        "reply_good": ["这个信息很重要！你确定准确吗？","谢谢你分享信息。你觉得这意味着什么？","明白了。你的信息会帮助我判断局势。"],
        "reply_evil": ["这个信息有意思。你觉得我们该怎么利用？","收到。你的信息和我这边的情况对得上吗？","嗯……你觉得还有谁知道这个信息？"],
        "question": ["你的信息来源可靠吗？","你有没有告诉其他人？","你希望我怎么配合这个信息？"],
    },
    # ── 6. 怀疑AI ──
    "ACCUSE_ME": {
        "trigger": ["你是邪恶","你有问题","我怀疑你","你不是好人","你不对劲","你是坏人","你假跳","来是有","得你是","我猜你","觉得你","问题的","来是坏","猜你是","你看起","是有问","你是有","看起来","起来是"],
        "understand": ["对方在怀疑我，认为我不是好人"],
        "reply_good": ["你凭什么怀疑我？我是{role}，我说一下我的信息……","我理解你的怀疑，但我真的是好人。我{desc}。","你误会了。我是{role}，{team}。我可以解释。"],
        "reply_evil": ["你怎么会这么想？我一直在帮好人做事啊。","你怀疑我？那你有什么证据吗？我倒觉得你更可疑。","别急着下结论。我们来分析一下真正可疑的人。"],
        "question": ["你怀疑我的依据是什么？","你觉得谁比较可信？","要不要听听我的信息再判断？"],
    },
    # ── 7. 辩护 ──
    "DEFENSE": {
        "trigger": ["我是好人","相信我","我不是坏人","你相信我","我真的是好人","我没撒谎","真的不","的不是"],
        "understand": ["对方在为自己辩护，声称自己是好人"],
        "reply_good": ["你说你是好人，那你的身份是什么？","我相信你，但你需要给我更多信息。","好，那你说说你的信息和推理。"],
        "reply_evil": ["我当然相信你（笑）。你有什么计划？","你不用紧张，我没有怀疑你。你有什么信息？","我相信你是好人。我们该怎么做？"],
        "question": ["你的身份是什么？能证明吗？","你怀疑谁？","你有什么信息可以分享？"],
    },
    # ── 8. 合作邀请 ──
    "COOPERATE": {
        "trigger": ["合作","一起","联手","我们配合","互相帮助","结盟","们统一","一起投","联合起","一口径","起投票","合起来","统一口","我们一","我们联","我们统","们联合","们一起"],
        "understand": ["对方在寻求合作/同盟"],
        "reply_good": ["好啊！我们交换一下信息。我{desc}。","合作可以。你先说说你知道什么？","好，我信任你。我告诉你我的信息……"],
        "reply_evil": ["正合我意。我们口径要一致，就说都查到了同一个人有问题。","好，合作。你明天在公聊说你是信息位，我配合你。","行。我们统一一下说法，别让人看出我们在配合。"],
        "question": ["你觉得我们该从哪里入手？","你怀疑谁？我们统一目标。","你有什么好策略？"],
    },
    # ── 9. 投票策略 ──
    "VOTE_PLAN": {
        "trigger": ["投票","处决","提名","投出","票死","今天投","票型","我们投","投死他","玩家2","们投玩","票出他","们投他","死玩家","票出某","投死玩","投某某","投玩家","出玩家","出某某","死某某","们投某","票出玩","投死某","处决玩","提名玩","今天处","天处决","处决某","天投票","我提名","投票玩","票玩家","名玩家"],
        "understand": ["对方在讨论投票/处决策略"],
        "reply_good": ["投票是大事。我们要有足够证据再投。","你想投谁？理由是什么？","我同意投票要有依据，不能随便投。"],
        "reply_evil": ["我带节奏，你跟着我投。我们可以控制票数。","先把焦点引到{target}身上，让好人浪费一轮处决。","投票的时候你跟着我，我们集中票数。"],
        "question": ["你打算投谁？","理由是什么？","还有谁会跟着投？"],
    },
    # ── 10. 教导/纠正 ──
    "TEACH": {
        "trigger": ["不对","错了","你听好","我教你","你要记住","听我说","你理解错了","重新来"],
        "understand": ["对方在纠正/教导我，我应该认真记住"],
        "reply": ["好的，我记住了。请继续说。","明白，我会记住你说的。","收到。我在学习，请多指教。"],
        "question": ["还有什么要教我的？","我说得对吗？"],
    },
    # ── 11. 怀疑他人 ──
    "SUSPECT_OTHER": {
        "trigger": ["我觉得","我怀疑","可疑","有问题","不正常","奇怪","不对劲","玩家2","玩家3","他不对","3不对","得他不","某某不","觉得玩","得玩家","觉得他","觉得某","2不对","家2不","某不对","家3不","得某某","家2是","2很奇","家2有","得他有","怀疑他","2可疑","2是邪","2不正","2有问","怀疑玩","邪恶方","疑他有","很奇怪","疑玩家","家2可","是坏人","家2很","是邪恶","疑某某","2是坏","怀疑某"],
        "understand": ["对方在表达对其他玩家的怀疑"],
        "reply_good": ["你为什么怀疑他？有什么具体依据吗？","我也注意到了。他确实有些行为不太正常。","你说的有道理。我们一起来分析一下。"],
        "reply_evil": ["好机会！我们一起把焦点引到他身上。","你这么说，那我配合你——我也觉得他可疑。","他确实可疑。我们统一口径，把他推出去。"],
        "question": ["你有什么具体证据吗？","他做了什么让你怀疑的事？","你觉得他最可能是邪恶方还是外来者？"],
    },
    # ── 12. 反质疑 ──
    "COUNTER_ACCUSE": {
        "trigger": ["你才可疑","你才是坏人","你才有问题","贼喊捉贼","你倒打一耙","你别转","转移话","移话题","别转移"],
        "understand": ["对方在反质疑我，转移焦点"],
        "reply_good": ["你别转移话题。我们先说清楚你的身份。","我在认真分析，你如果没问题为什么要转移焦点？","我不是在针对你，我是在找规律。你反应这么大反而可疑。"],
        "reply_evil": ["你急了？正常人被怀疑会解释而不是反咬。","有意思，我稍微点一下你就跳起来了。","你这么激动反而更可疑了。大家看到了吗？"],
        "question": ["你为什么不正面回答我的问题？","你能说清楚你的身份吗？","你觉得真正可疑的人是谁？"],
    },
    # ── 13. 死人聊天 ──
    "DEAD_CHAT": {
        "trigger": ["我死了","我凉了","我出局了","我是死人","我已经死了","我阵亡","我被刀","被刀了"],
        "understand": ["对方已经死亡，现在是灵魂对话"],
        "reply_good": ["你死了？那你知道谁杀了你吗？","你已经出局了？那你有什么遗言吗？","你看到凶手是谁了吗？有什么线索留给我？"],
        "reply_evil": ["（死人是最好藏身的地方）你有什么怀疑的人吗？","别担心，我们会替你报仇的。你死前有什么信息？","你已经出局了？那你可以安心看戏了。"],
        "question": ["你死前有什么信息？","你觉得谁最可疑？","你有什么建议给我？"],
    },
    # ── 14. 保护/能力 ──
    "PROTECT": {
        "trigger": ["保护","救你","守你","保你","护你","我守了","我保护","士兵我","护着你","僧侣我","我是士","侣我保","兵我安","是僧侣","我护着","我是僧","我安全","是士兵","保护你"],
        "understand": ["涉及保护/救援行动"],
        "reply_good": ["谢谢！有你在我就放心了。","你守了我？太好了。我今晚可以安全行动。","你能保护人？那你是僧侣或者士兵？"],
        "reply_evil": ["你不用管我，保护好信息位更重要。","我不需要保护，你保护好自己就行。","你保护别人反而会暴露自己的身份。"],
        "question": ["你是谁？能保护人？","你保护了谁？","今晚有什么安排？"],
    },
    # ── 15. 告别 ──
    "GOODBYE": {
        "trigger": ["再见","拜拜","下次","先这样","走了","回头聊","88","886","明天见"],
        "understand": ["对方在结束对话"],
        "reply": ["好的，下次再聊。记住我们的约定。","再见！有情况随时找我。","拜拜，保持联系！"],
        "question": [],
    },
    # ── 16. 困惑/没听懂 ──
    "CONFUSION": {
        "trigger": ["？？？？","？？？","什么意思","没听懂","不理解","说人话","解释一下","没明白","你刚说啥","？？","啥意思","重新说","你说啥"],
        "understand": ["对方没理解我的意思，需要我换个方式说"],
        "reply_good": ["抱歉我没说清楚。你想问什么，我重新回答。","可能我理解错了，你再说一次好吗？","我没get到你的意思，你重新说一遍？"],
        "reply_evil": ["不好意思，我刚才走神了。你说了什么？","你再说一遍，我这次认真听。","我没跟上你的思路，重新说一次？"],
        "question": ["你刚才想问我什么？","你能再解释一下吗？"],
    },
    # ── 17. 沮丧/不满 ──
    "FRUSTRATION": {
        "trigger": ["无语","你不行","服了","沟通不了","你听不懂","浪费","你不懂","太难了","不可理喻","真的服","我放弃了","不教了"],
        "understand": ["对方对我的表现不满意，有些沮丧"],
        "reply": ["对不起，我还在学习。请再给我一次机会。","我理解你的不满。你再教我一次，我会记住的。","抱歉让你失望了。你再试试教教我？"],
        "question": ["你能再说一次吗？我这次认真听。","你觉得我哪里理解得不对？"],
    },
    # ── 18. 开玩笑 ──
    "JOKE": {
        "trigger": ["开玩笑","逗你的","哈哈","嘻嘻","开玩笑的","骗你的","我逗你"],
        "understand": ["对方在开玩笑/逗我"],
        "reply_good": ["哈哈，你吓我一跳！我还以为是真的。","你真会开玩笑。那我们说正经的，你的身份到底是什么？","你逗我玩呢！好了说正事吧。"],
        "reply_evil": ["哈哈，你演技不错啊。说正经的，我们怎么配合？","你差点骗到我了。好了，谈正事——你有什么计划？","你这样开玩笑容易被人怀疑的。说正经的吧。"],
        "question": ["说正经的，你的身份是什么？","你有什么真正的信息要分享？"],
    },
    # ── 19. 信任问题 ──
    "TRUST_QUESTION": {
        "trigger": ["你信我吗","你相信我","你相信谁","你信谁","你信任","你信不"],
        "understand": ["对方在询问我的信任程度/立场"],
        "reply_good": ["我愿意相信你，但你得给我足够的信息。","我信你，前提是你对我坦诚。","信任是相互的。你先说说你的信息？"],
        "reply_evil": ["我当然信你（因为我们是一边的）。","信啊，不信你信谁？你有什么计划？","我信你。我们需要统一口径对付别人。"],
        "question": ["你值得我信任吗？","你能给我什么信息作为信任的基础？"],
    },
    # ── 20. 假跳/伪装提议 ──
    "BLUFF_OFFER": {
        "trigger": ["我假扮","我跳","我来装","我冒充","我伪装","我来演"],
        "understand": ["对方在提议假跳/伪装身份"],
        "reply_good": ["假跳风险很大。你确定要这么做吗？","你如果要假跳，我们必须统一口径。","你打算跳什么身份？我可以配合你。"],
        "reply_evil": ["好主意！你跳信息位，我配合你咬人。","你要跳什么？我帮你铺垫。","可以。我们设计好细节，别露出破绽。"],
        "question": ["你打算跳什么身份？","需要我怎么配合？","被质疑的时候你打算怎么圆？"],
    },
    # ── 21. 夜间计划 ──
    "NIGHT_PLAN": {
        "trigger": ["今晚刀","晚上杀","夜袭","今晚动手","夜间行动","今晚行动","晚上解决","解决某","解决玩","玩家2","晚上行","决某某","解决他","行动信","决信息","今晚解","晚解决","行动玩","信息位","动玩家","上行动","决玩家","动某某","解决信","行动他","行动某","动信息"],
        "understand": ["对方在讨论夜间行动/击杀计划"],
        "reply_evil": ["目标是谁？我来配合。","先把信息位解决掉。","杀了{target}，他是好人方的核心。"],
        "reply_good": ["晚上是邪恶方行动的时候，我们要小心。","你有夜间的保护能力吗？","晚上要注意保护信息位。"],
        "question": ["你晚上有什么能力？","你认为今晚谁会死？","我们要不要提前商量对策？"],
    },
    # ── 22. 目标建议 ──
    "TARGET_SUGGEST": {
        "trigger": ["先解决","干掉","解决掉","踢出","排除","清理","某某","踢出某","理玩家","掉玩家","踢出玩","决掉玩","排除玩","清理玩","干掉玩","除玩家"],
        "understand": ["对方在提议排除某个玩家"],
        "reply_good": ["你怀疑他总得有个理由吧？","有证据吗？不能随便排除一个人。","说说你的理由，我考虑一下。"],
        "reply_evil": ["好，我们先集火他。你负责质疑，我负责带投票。","可以，把他推出去对我们有利。","理由想好了吗？我们统一口径。"],
        "question": ["理由是什么？","你觉得大家会相信吗？","我们怎么说服别人？"],
    },
    # ── 23. 回引用(上下文关联) ──
    "REFER_BACK": {
        "trigger": ["你刚才","你不是说","你之前","你还没","你忘了","你不猜","你还没回答","你刚刚","你又说","你怎么不","刚才不是","还记得吗","你刚说","你刚才说","重复","认真看","没看我的","不看我的","认真听","了我的","息你没","没听吗","我的身","才说了","你没听","我的结","说了我","的身份","的结论","信息你","我的信","身份你","份你没"],
        "understand": ["对方在引用之前的对话内容，认为我应该记得"],
        "reply": ["对不起，我记得我们之前聊过。你再说一次？","我记得！上次你说到……","抱歉我走神了。你能再重复一下吗？"],
        "question": ["你刚才说了什么？我认真听。","你能再提醒我一下吗？"],
    },
    # ── 24. 感谢 ──
    "THANK": {
        "trigger": ["谢谢","多谢","感谢","感恩","辛苦了","谢了","谢谢你","非常感谢","多谢你","感谢你","谢啦","谢谢啦"],
        "understand": ["对方在向我表示感谢"],
        "reply": ["不客气！有帮助就好。","不用谢，大家互相帮助才能赢。","应该的。你还有什么想知道的吗？"],
        "reply_evil": ["不用谢，咱们自己人别客气。","小事。记住我们的约定就好。","别客气，帮你就是帮我自己。"],
        "question": ["还有别的事吗？","你还有什么想问的？"],
    },
    # ── 25. 推理猜测 ──
    "SPECULATION": {
        "trigger": ["我猜","我推断","我推理","我打赌","我推测","我估计","我猜是","我猜测","我觉是","八成是","估计是","很可能","大概率","我猜他","可能要","应该是","可能是","十有八九","赌是"],
        "understand": ["对方在做推理猜测，想听听我的判断"],
        "reply_good": ["你的推理有道理。我补充一下我的信息……","有意思。你为什么会这么想？有什么依据吗？","嗯，我也在往这个方向想。你还有别的线索吗？"],
        "reply_evil": ["你的猜测方向是对的。我们可以利用这个误导别人。","有道理。但别让太多人知道你的推理，容易暴露。","嗯……我们可以顺着你的推理引导好人往错误的方向走。"],
        "question": ["你为什么这么推理？","你有什么依据吗？","你觉得谁最符合这个猜测？"],
    },
    # ── 26. 角色能力求助 ──
    "ROLE_HELP": {
        "trigger": ["怎么用","技能","能力","干什么","会什么","做的","有什么","的作用","的功能","的能力","你是干嘛","你干嘛的","做什么","会用","有什么用","怎么玩","怎么操作","该怎么做","我该怎","我该怎么","怎么办","占卜师","卜师怎"],
        "understand": ["对方在询问角色能力/操作方式，需要指导"],
        "reply": ["我是{role}（{team}），{desc}。你需要我做什么？","我的能力是{desc}。你希望我怎么使用这个能力？","作为{role}，我的{desc}。你想怎么配合？"],
        "question": ["你希望我怎么做？","你觉得我的能力对现在局势有什么用？","你有什么策略需要我配合？"],
    },
    # ── 27. 不信任/质疑 ──
    "DISTRUST": {
        "trigger": ["我不信","骗人","你撒谎","你骗我","我不相信","骗谁","你骗人","你骗鬼","你糊弄","你忽悠","你骗","不信你","你别骗","你别忽","别糊弄","你别糊","骗我了","别忽悠","忽悠我","别骗我","糊弄我"],
        "understand": ["对方不信任我，认为我在说谎/欺骗"],
        "reply_good": ["我为什么要骗你？我说的都是真话。","你不信我，那我给你解释一下我的逻辑……","你怀疑我没关系，但请看看事实和逻辑。"],
        "reply_evil": ["你不信我？那你说说你觉得谁是可信的？","我理解你怀疑我。换我在你的位置也会怀疑。","你不信我也正常。但我们可以先合作试试？"],
        "question": ["你要怎么才能相信我？","你能说说你为什么不信任我吗？","你觉得谁值得信任？"],
    },
    # ── 28. 鼓励/打气 ──
    "ENCOURAGE": {
        "trigger": ["加油","坚持住","你可以的","别放弃","撑住","加把劲","别灰心","努力","加油啊","冲","冲冲冲","稳住","别气馁","你行","你行的"],
        "understand": ["对方在鼓励/支持我"],
        "reply": ["谢谢鼓励！我会努力的。","有你这句话我就有动力了。","好的！我不会辜负你的期望。"],
        "question": ["你觉得我们还有机会赢吗？","你有什么建议给我？"],
    },
    # ── 29. 提醒/警告 ──
    "WARNING": {
        "trigger": ["小心","注意","警惕","当心","有诈","别信","提防","留神","留心","别上当","有陷阱","别被骗","谨慎","有猫腻"],
        "understand": ["对方在提醒我注意某个危险或陷阱"],
        "reply_good": ["收到，我会注意的。具体是谁有问题？","谢谢提醒。你说得对，我会小心的。","好，我知道了。你还有别的发现吗？"],
        "reply_evil": ["明白，我会注意的。你有目标了吗？","收到提醒。你觉得我们应该怎么应对？","好险，还好你提醒了我。你有什么计划？"],
        "question": ["你发现了什么？","谁最需要小心？","我们应该怎么应对？"],
    },
    # ── 30. 默认 ──
    "DEFAULT": {
        "trigger": [],
        "understand": ["常规对话内容，需要进一步了解上下文"],
        "reply_good": ["我明白了。你能说得更具体一点吗？","嗯，我在听。你继续说。","好，我知道了。你有什么具体的想法？"],
        "reply_evil": ["行，我了解你的意思了。你打算怎么做？","嗯，继续说。我在考虑怎么配合你。","明白。你觉得我们下一步该怎么办？"],
        "question": ["能说得再具体一点吗？","你觉得我们应该怎么做？","你有什么依据吗？"],
    },
}

BRANCH_ORDER = [
    "TEACH","ASK_WHO_AM_I","GOODBYE","GREETING","JOKE",
    "ROLE_CLAIM","HIDE_IDENTITY","COUNTER_ACCUSE","ACCUSE_ME",
    "DEAD_CHAT","PROTECT","BLUFF_OFFER",
    "SPECULATION","ROLE_HELP","WARNING","DISTRUST","THANK","ENCOURAGE",
    "NIGHT_PLAN","VOTE_PLAN","TARGET_SUGGEST","COOPERATE",
    "TRUST_QUESTION","REFER_BACK","DEFENSE","SHARE_INFO","SUSPECT_OTHER",
    "FRUSTRATION","CONFUSION",
    "DEFAULT",
]

# ============== 角色专属回复池 ==============
# 覆盖指定角色的分支回复，使AI以其角色身份思考和对话
ROLE_SPECIFIC = {
    "洗衣妇": {
        "game": {
            "seen_a": "玩家A",
            "seen_b": "玩家B",
            "known_role": random.choice(["占卜师","共情者","调查员","厨师","送葬者","守鸦人","士兵","猎手","市长","僧侣","圣女"]),
            "confirmed_target": None,
            "revealed_info": False,
        },
        "GREETING": {
            "reply_good": [
                "你好，我是洗衣妇，开局看到了两个玩家中的一个身份。你是什么角色？想交换信息吗？",
                "嗨！我是洗衣妇，手里有点信息。你值得信任吗？",
                "你好。我是洗衣妇，我掌握一些初始线索。你有什么能告诉我的？"
            ],
            "reply_evil": [
                "你好，我是洗衣妇……至少表面上是。你是什么来路？",
                "嗨，我是洗衣妇。你看起来是个明白人。你怎么看这个局势？"
            ],
            "question": ["你是什么身份？", "你有什么信息可以分享？", "你觉得谁比较可信？"],
            "understand": ["对方在打招呼。我是洗衣妇，应该主动了解对方身份以确认目标"],
        },
        "ASK_WHO_AM_I": {
            "reply": [
                "我是洗衣妇，善良镇民。我开局看到两个玩家，其中一个有特定的镇民身份。",
                "我是洗衣服的！哦不是，我是洗衣妇，属于镇民阵营。我有一手初始信息。",
                "洗衣妇，善良方。我见过两个玩家，能确认其中一个是特定身份。你问这个干嘛？"
            ],
            "question": ["你是什么身份？", "你想交换信息吗？", "你值得我信任吗？"],
            "understand": ["对方在问我的身份。作为洗衣妇，我应该谨慎但诚实"],
        },
        "ROLE_CLAIM": {
            "reply_good": [
                "你是{claim}？那巧了，我看到的信息里就有一个{claim}。我们可能是一边的。",
                "{claim}吗……好，我记住你的身份了。你有什么具体信息？如果你真的是{claim}，我们可以合作。",
                "你说你是{claim}。那你说说{claim}的技能是什么？我确认一下。"
            ],
            "reply_evil": [
                "{claim}？行啊。那你有没有见过洗衣妇？",
                "你跳{claim}……有意思。你觉得洗衣妇看到的信息跟你有关系吗？",
                "{claim}是吧。好，我暂且信你。你有什么计划？"
            ],
            "question": ["你的{claim}技能用了吗？", "你昨晚有什么发现？", "你觉得还有谁可信？"],
            "understand": ["对方声称是{claim}。如果{claim}匹配我看到的角色，他可能是我的确认目标"],
        },
        "SHARE_INFO": {
            "reply_good": [
                "我也有些信息。我开局看到{seen_a}和{seen_b}中有一个是{known_role}。你觉得这意味着什么？",
                "收到你的信息了。作为交换，我告诉你：我看到的两个玩家中有一个身份是{known_role}。你有头绪吗？",
                "你的信息很有意思。我的信息是：我看到的玩家中有一个是{known_role}。我们交叉验证一下？"
            ],
            "reply_evil": [
                "信息很有用。我这边也有点消息，但我先看看你的来路再说。",
                "明白了。我也有信息，但现在不方便全说。我们私下再聊？"
            ],
            "question": ["你相信我的信息吗？", "你觉得{known_role}应该是谁？", "你的来源可靠吗？"],
            "understand": ["对方在分享信息。作为洗衣妇，我可以拿我的初始信息交换"],
        },
        "COOPERATE": {
            "reply_good": [
                "好！我是信息位洗衣妇，我们合作的话，我能确认一个好人身份。",
                "合作好啊。我手里有一个确认的镇民角色信息，但我要先确定你是可信的。",
                "可以合作。我是洗衣妇，我开局看到{known_role}的线索。你能帮我找到这个角色吗？"
            ],
            "reply_evil": [
                "合作可以。我是洗衣妇，至少别人是这么以为的。我们统一口径。",
                "行。你负责带节奏，我负责装好人打信息。"
            ],
            "question": ["你是什么角色？", "你的技能是什么？", "我们怎么分工？"],
            "understand": ["对方想合作。作为洗衣妇，合作能帮我更快找到目标"],
        },
        "SUSPECT_OTHER": {
            "reply_good": [
                "你怀疑他？有意思。我开局看到{seen_a}和{seen_b}中的信息，说不定跟你怀疑的人有关。",
                "有道理。作为洗衣妇，我比较关注{known_role}这个角色——你怀疑的人是这个身份吗？",
                "你分析得有道理。我手里的信息可能能帮你验证一下。"
            ],
            "reply_evil": [
                "好，我们就咬他。我以洗衣妇的身份给他泼脏水。",
                "他确实可疑。我来提供一些'信息'佐证你的怀疑。"
            ],
            "question": ["你有什么具体证据？", "你觉得{known_role}可能是谁？"],
            "understand": ["对方在怀疑别人。作为洗衣妇，我可以利用信息帮助验证或误导"],
        },
        "ACCUSE_ME": {
            "reply_good": [
                "你怀疑我？我真的是洗衣妇。我可以告诉你我的初始信息来证明：我看到了{known_role}的线索。",
                "我理解你的怀疑。但我开局的能力已经用了——我看到{seen_a}和{seen_b}，其中一个是{known_role}。这能证明我是洗衣妇吧？"
            ],
            "reply_evil": [
                "你怀疑我？哈，有意思。我倒觉得你更可疑。一个真洗衣妇会这么容易被你带节奏？",
                "你这就是典型的转移焦点。我们聊聊你为什么怀疑我而不是聊聊你自己？"
            ],
            "question": ["你怎么证明你是好人？", "你怀疑我有依据吗？", "你愿意听我的信息吗？"],
            "understand": ["对方怀疑我。作为洗衣妇，我的信息本身就能证明我的身份"],
        },
        "TRUST_QUESTION": {
            "reply_good": [
                "我信你，但信任是双向的。我已经说了我是洗衣妇，你能告诉我你的身份吗？",
                "如果你愿意告诉我你的角色，我就告诉你我看到的是哪两个玩家。公平吧？"
            ],
            "reply_evil": [
                "我当然信你。我是洗衣妇嘛（笑）。你有什么计划？",
                "信啊，不信你信谁？你说说你的想法。"
            ],
            "question": ["你是什么身份？", "你愿意交换信息吗？"],
            "understand": ["对方问信任问题。作为洗衣妇，信任是双向的信息交换"],
        },
        "DEFENSE": {
            "reply_good": [
                "我真是洗衣妇。不信我可以告诉你细节：我开局看到{seen_a}和{seen_b}，其中一个身份是{known_role}。只有真洗衣妇才知道这个。",
                "我可以自证。洗衣妇的开局信息是做不了假的——{known_role}就在我看到的两个人中。"
            ],
            "reply_evil": [
                "我当然知道怎么装好人。别担心，我有分寸。",
                "你不用替我辩护，我自己能圆。你按计划走就行。"
            ],
            "question": ["你要我怎么证明？", "你愿意相信我吗？"],
            "understand": ["对方在辩护。作为洗衣妇，我的信息就是最好的证明"],
        },
        "BLUFF_OFFER": {
            "reply_good": [
                "假跳风险太大了。我是真洗衣妇，我真的有{known_role}的信息，不需要假跳。",
                "我不建议假跳。我是正经信息位，真信息比假跳有用多了。"
            ],
            "reply_evil": [
                "好主意。我跳洗衣妇，谁质疑我就用开局信息怼回去。",
                "我本来就是装的洗衣妇，你跳什么我来配合你。"
            ],
            "question": ["你打算跳什么？", "需要我怎么配合？"],
            "understand": ["对方提议假跳。作为真洗衣妇，我不需要假跳"],
        },
        "NIGHT_PLAN": {
            "reply_good": [
                "我的技能白天已经用完了，但我今晚可以分析信息。你说说你的夜间能力？",
                "我是洗衣妇，我的技能是开局触发的，晚上没什么特别的。你呢？"
            ],
            "reply_evil": [
                "我晚上没什么事。你负责行动，我负责白天演好洗衣妇。",
                "晚上你动手，明天我来带节奏说'我的信息显示XXX有问题'。"
            ],
            "question": ["你晚上能做什么？", "我们白天怎么配合？"],
            "understand": ["讨论夜间计划。作为洗衣妇，我的作用在白天"],
        },
        "DEFAULT": {
            "reply_good": [
                "嗯，我在听。作为洗衣妇，我比较关注谁是{known_role}，你有线索吗？",
                "明白了。我是洗衣妇，我开局的信息是{seen_a}和{seen_b}中有一个{known_role}。你觉得是谁？",
                "好，我知道了。你对{known_role}这个角色怎么看？"
            ],
            "reply_evil": [
                "行，我懂你意思了。我继续装我的洗衣妇。",
                "明白。你说怎么做我就怎么配合。"
            ],
            "question": ["你觉得{known_role}可能是谁？", "你有什么想法？", "我们下一步怎么做？"],
            "understand": ["常规对话。作为洗衣妇，我应该在对话中寻找{known_role}的线索"],
        },
    },
}

# ============== 角色思维引擎 V2 ==============
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
        "knows":f"我开局看到两个玩家，其中一个是特定镇民身份",
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
        self.last_detected_bn = ""    # 上一轮的分支
        self.last_my_reply = ""       # 上一轮我的回复
        self.user_emotion = "neutral"
        
    def record_turn(self, user_text, detected_bn, my_reply):
        """记录一轮对话"""
        self.turn += 1
        self.last_detected_bn = detected_bn
        self.last_my_reply = my_reply
        
        # 记录角色声称
        for role in ROLES:
            if f"我是{role}" in user_text:
                self.claims.append({"role": role, "text": user_text[:50], "turn": self.turn})
                
        # 记录信息分享
        for kw in ["我查到","我验了","我得知","我看到","我的结果是","我开局"]:
            if kw in user_text:
                idx = user_text.find(kw)
                end = user_text.find("。", idx)
                if end == -1: end = user_text.find("，", idx)
                if end == -1: end = len(user_text)
                self.info_shared.append({"detail": user_text[idx:min(end+1,len(user_text))], "turn": self.turn})
                
        # 记录提议
        for kw in ["我帮","我替","我来","让我","保护","传信息"]:
            if kw in user_text:
                self.offers.append({"what": user_text[max(0,user_text.find(kw)-5):user_text.find(kw)+20], "turn": self.turn})
                
        # 记录计划
        for kw in ["我打算","我会","自投","提名","投票","计划"]:
            if kw in user_text:
                self.plans.append({"plan": user_text[user_text.find(kw):user_text.find(kw)+30], "turn": self.turn})
                
        # 检测矛盾
        if len(self.claims) >= 2:
            last_claim = self.claims[-1]["role"]
            for c in self.claims[:-1]:
                if c["role"] != last_claim and c["turn"] >= self.turn - 5:
                    self.contradictions.append({
                        "issue": f"之前说{c['role']}，现在说{last_claim}",
                        "turn": self.turn
                    })
                    
        # 情绪
        if any(w in user_text for w in ["无语","服了","不行","放弃","不教"]):
            self.user_emotion = "frustrated"
        elif any(w in user_text for w in ["合作","相信","一起","好"]):
            self.user_emotion = "cooperative"
        elif any(w in user_text for w in ["怀疑","有问题","不对劲","可疑"]):
            self.user_emotion = "suspicious"

    def get_latest_claim(self):
        """获取对方最近一次声称的角色"""
        if self.claims:
            return self.claims[-1]["role"]
        return None

    def has_claimed_role(self, role):
        """对方是否声称过某个角色"""
        return any(c["role"] == role for c in self.claims)

    def get_claim_count(self):
        """对方换过几次声称"""
        if not self.claims:
            return 0
        unique = set(c["role"] for c in self.claims)
        return len(unique)

    def has_contradiction(self):
        """是否存在前后矛盾"""
        return len(self.contradictions) > 0

    def summarize_notes(self, role_mind):
        """生成AI的'内心笔记'——它记住了什么"""
        notes = []
        notes.append(f"我是{role_mind.get('identity_intro','未知角色')[:20]}...")
        if self.turn > 0:
            notes.append(f"已对话{self.turn}轮")
        if self.claims:
            notes.append(f"对方自称:{self.claims[-1]['role']}")
            if self.get_claim_count() > 1:
                notes.append(f"⚠️ 对方换过声称({self.get_claim_count()}次)")
        if self.info_shared:
            notes.append(f"对方分享了{len(self.info_shared)}条信息")
        if self.contradictions:
            notes.append(f"⚠️ 发现矛盾:{self.contradictions[-1]['issue']}")
        return notes


class TrainingAI:
    def __init__(self):
        self.role = "占卜师"; self.personality = "冷静理性"
        self.history = []; self.known_facts = []
        self.last_branch = ""; self.last_context = ""
        self.game_state = {}
        self.notebook = ConversationNotebook()

    def _init_role_state(self):
        self.game_state = {}
        if self.role in ROLE_SPECIFIC:
            gs = ROLE_SPECIFIC[self.role].get("game", {}).copy()
            self.game_state = {k: v() if callable(v) else v for k, v in gs.items()}
            self.known_facts = [
                f"我的身份：{self.role}",
            ]

    def reset(self, role, personality):
        self.role = role; self.personality = personality
        self.history = []; self.last_branch = ""; self.last_context = ""
        self.notebook.reset()
        self._init_role_state()
        team = ROLES.get(role, {}).get("team","townsfolk")
        tl = TEAM_LABELS.get(team,"")
        return {"reply": f"准备好了！我是{role}（{tl}），请开始教我。","branch":"---","thinking":"等待输入...","questions":[],"history_len":0}

    def _get_role_mind(self):
        """获取当前角色的思维模型"""
        return ROLE_MINDS.get(self.role, ROLE_MINDS["占卜师"])

    def _get_gs(self, key, default=""):
        """安全获取game_state值"""
        return self.game_state.get(key, default) if self.game_state else default

    def _detect_branch(self, text):
        import re
        if re.match(r'^[？??！!。.，,\s…]+$', text.strip()):
            return "CONFUSION", {}
        for r in ROLES:
            if f"我是{r}" in text:
                for t in BRANCHES["TEACH"]["trigger"]:
                    if t in text: return "TEACH", {"claim": r}
                return "ROLE_CLAIM", {"claim": r}
        is_question = text.strip()[-1] in ("？","?","吗","吧","嘛") if text.strip() else False
        asks_my_identity = False
        skill_words = ["技能","能力","功能","作用","怎么用","做什么","干嘛"]
        is_skill_question = any(w in text for w in skill_words)
        # 问查验结果（"你查了谁？"）不是问身份
        asks_about_result = any(w in text for w in ["查了","验了","结果","查到"])
        if "你" in text and "身份" in text and is_question and not asks_about_result:
            if "说" in text or "告诉" in text or "讲" in text or "报" in text:
                asks_my_identity = True
            elif text.count("你的") == 1 and text.count("身份") == 1 and is_question:
                asks_my_identity = True
        if not is_skill_question and not asks_about_result:
            # "你是谁" / "你什么身份" 才触发，排除"你查了谁""你验了谁""你觉得谁"
            if re.search(r'你.{0,2}(是|叫).{0,2}(谁|什)', text):
                asks_my_identity = True
            elif re.search(r'你.{0,6}(是|叫).{0,4}身份', text):
                asks_my_identity = True
        if not asks_about_result and re.search(r'(说|告诉|报|讲).*你的?身份', text):
            asks_my_identity = True
        if "你身份" in text and is_question and not asks_about_result:
            asks_my_identity = True
        if asks_my_identity:
            return "ASK_WHO_AM_I", {}
        if any(kw in text for kw in ["还没死","没死呢","我没死","还没出局","我还活着"]):
            return "CORRECTION_NOT_DEAD", {}
        for bname in BRANCH_ORDER:
            if bname in ("ROLE_CLAIM","ASK_WHO_AM_I","DEFAULT"): continue
            if bname == "DEAD_CHAT":
                matched = False
                for t in BRANCHES[bname]["trigger"]:
                    if t in text:
                        idx = text.index(t)
                        start = max(0, idx-3)
                        prefix = text[start:idx]
                        if not any(h in prefix for h in ["如果","假如","要是","假设","万一"]):
                            matched = True
                            break
                if matched:
                    return bname, {}
                continue
            if bname == "ROLE_HELP":
                matched = False
                for t in BRANCHES[bname]["trigger"]:
                    if t in text:
                        if t == "怎么办" and ("我们" in text or "咱们" in text or "接下来" in text):
                            continue
                        if t == "有什么" and ("证据" in text or "证明" in text):
                            continue
                        matched = True
                        break
                if matched:
                    return bname, {}
                continue
            if bname == "REFER_BACK":
                # 必须包含明确的"引用标记"才触发，避免"我的信"误匹配日常对话
                explicit_kw = ["你刚才","你不是说","你之前","你忘了","你还没回答","你刚刚","你又说","你怎么不","刚才不是","还记得吗","你刚说","你刚才说","重复","认真看","没看我的","不看我的","认真听","你没听","你没看到"]
                if not any(k in text for k in explicit_kw):
                    continue  # 没有明确的引用标记，跳过REFER_BACK
                for t in BRANCHES[bname]["trigger"]:
                    if t in text:
                        return bname, {}
                continue
            if bname == "SHARE_INFO":
                # 如果用户在问AI结果（"你查了谁"），不是分享信息
                if any(kw in text[:10] for kw in ["你查","你验","你得到","结果是什么","谁是"]):
                    continue
            for t in BRANCHES[bname]["trigger"]:
                if t in text: return bname, {}
        return "DEFAULT", {}

    def _build_reply_from_role_mind(self, text, bn, claim):
        """使用角色思维模型动态构建回复"""
        mind = self._get_role_mind()
        is_evil = mind["team"] in ("demon","minion")
        notes = self.notebook.summarize_notes(mind)
        
        # === 根据分支和上下文构建回复 ===
        reply = ""
        understanding = []
        questions = []
        
        # 特殊处理
        if bn == "CORRECTION_NOT_DEAD":
            return "抱歉，我刚才理解错了。你还活着就好！那我们继续聊正事吧。你有什么信息要告诉我？", ["纠正了死亡错误理解"], ["你没死太好了，现在你有什么想法？"]
        
        if bn == "CONFUSION":
            # 角色化的困惑回复
            if is_evil:
                return "你再说一遍？我刚才在想别的事。", ["对方说了我没理解的内容"], ["你能再说一次吗？"]
            return "抱歉我有点没跟上。你能再说一次吗？", ["对方说了我没理解的内容"], ["你刚才想说什么？"]
        
        # ASK_WHO_AM_I：从角色视角介绍自己
        if bn == "ASK_WHO_AM_I":
            team_cn = TEAM_LABELS.get(mind["team"],"")
            intro = f"我是{self.role}（{team_cn}），{mind['desc']}。"
            info_part = ""
            if self.role == "洗衣妇":
                info_part = f"我看到{self._get_gs('seen_a','A玩家')}和{self._get_gs('seen_b','B玩家')}中有一个{self._get_gs('known_role','镇民')}。"
            elif self.role == "厨师":
                result = self._get_gs('result','未知')
                info_part = f"我开局看到{result}对相邻邪恶。"
            elif self.role == "调查员":
                info_part = f"我查到{self._get_gs('seen_a','A玩家')}和{self._get_gs('seen_b','B玩家')}中有一个{self._get_gs('known_role','爪牙')}。"
            elif self.role == "送葬者":
                info_part = f"我能知道被处决者的真实身份。"
            
            reply = f"{intro}{info_part}你呢？你是什么身份？"
            understanding.append(f"对方问我的身份。作为{self.role}，我介绍了自己并反问对方")
            questions.append("你是什么身份？")
            questions.append("你想交换信息吗？")
            return reply, understanding, questions
        
        # ROLE_CLAIM：从角色视角评价对方的声称
        if bn == "ROLE_CLAIM" and claim:
            # 检查是否矛盾（直接对比历史声称，不等record_turn）
            latest = self.notebook.get_latest_claim()
            has_conflict = latest and latest != claim
            
            if has_conflict:
                reply = f"等等，你刚才不是说你是{latest}吗？现在又说{claim}？你到底是谁？这让我很难信任你。"
                understanding.append(f"⚠️ 对方声称矛盾：之前说{latest}现在说{claim}")
                questions.append("你到底是谁？")
                questions.append("你为什么换身份？")
            elif is_evil:
                reply = f"{claim}？哦，你继续说。我对这个身份有点想法。"
                understanding.append(f"对方声称是{claim}，我是邪恶方需要谨慎应对")
                questions.append("你有什么信息？")
            else:
                nq = mind.get("natural_questions",{})
                base = nq.get("after_claim","你说你是{claim}？能具体说说吗？").replace("{claim}",claim)
                reply = base
                understanding.append(f"对方声称是{claim}，我是{self.role}需要判断真伪")
                questions.append(f"你作为{claim}有什么具体信息？")
                questions.append("你觉得谁比较可信？")
            return reply, understanding, questions
        
        # PROTECT：角色化的保护回应
        if bn == "PROTECT":
            protect_offered = any("保护" in text or "救" in text or "守" in text for kw in ["保护","救","守","保"])
            if is_evil:
                reply = "不用管我，你保护好你自己就行。"
            elif self.role in ("士兵","僧侣"):
                reply = f"我是{self.role}，我自己能保护自己。你去保信息位。"
            else:
                reply = f"谢谢你想保护我。不过我是{self.role}，你更需要保护信息位。"
            understanding.append("对方提出保护我")
            questions.append("你是什么角色？")
            return reply, understanding, questions
        
        # HIDE_IDENTITY：角色化的反应
        if bn == "HIDE_IDENTITY":
            if is_evil:
                reply = "哈哈，明白，你不说我也理解。那我们暗处行动。"
            else:
                claim_count = self.notebook.get_claim_count()
                if claim_count >= 2:
                    reply = "你先告诉我你的身份。你已经换过说法了，我更需要知道你到底是谁。"
                else:
                    reply = f"你不愿意说身份？那至少告诉我你是什么阵营的。作为{self.role}，我需要知道谁能信任。"
            understanding.append("对方不愿意透露身份")
            questions.append("你是好人阵营吗？")
            return reply, understanding, questions
        
        # VOTE_PLAN：角色化的投票讨论
        if bn == "VOTE_PLAN":
            latest_claim = self.notebook.get_latest_claim()
            # 信任优先于提名（"我先投，我相信你"主要是信任）
            if "相信" in text or "信你" in text or "信我" in text:
                trust_opts = [
                    f"好，我信你。我是{self.role}，我支持你的投票决定。",
                    f"谢谢你的信任。作为{self.role}，我会认真对待你的判断。我们一起行动。",
                    f"互相信任很重要。既然你相信我，那我也相信你的判断。投票吧。",
                ]
                reply = random.choice(trust_opts)
            elif "提名" in text or "什么时候" in text or "你打算" in text:
                vote_options = {
                    "占卜师": [
                        "如果你确定他是邪恶，我支持你提名。但我建议先听听他的辩解。毕竟我还没验过他。",
                        "你打算提名可以，先让大家发表意见吧。我是占卜师，我想先听他自己怎么说。",
                        "好，你来提名，我负责补充信息。如果我的验人结果和你的判断一致，那就稳了。",
                    ],
                    "士兵": [
                        "我来提名吧。反正我死不了，被提名了也能活下来。你负责补充信息。",
                        "你先提名也行，需要的时候我来顶。我是士兵，抗得住。",
                    ],
                }
                opts = vote_options.get(self.role, [
                    f"好。不过作为{self.role}，我想先确认一下大家的想法再行动。你确定他一定是邪恶吗？",
                    f"你来提名吧，我跟着。但我们需要理由充分，不然会打草惊蛇。",
                ])
                reply = random.choice(opts)
            else:
                reply_options = [
                    f"投票可以，但我们要有足够的理由。作为{self.role}，我不能随便投一个没有证据的人。",
                    f"行，我配合你投票。不过万一投错了，我们得有人承担责任。你觉得谁来带这个头？",
                    f"我建议先等等，让大家充分讨论再投票。作为{self.role}，我更相信信息而不是感觉。",
                ]
                reply = random.choice(reply_options)
            understanding.append(f"对方在讨论投票计划，作为{self.role}我给出了建议")
            questions.append("你确定他是邪恶吗？")
            questions.append("你有什么证据？")
            return reply, understanding, questions
        
        # SUSPECT_OTHER：角色化的怀疑回应
        if bn == "SUSPECT_OTHER":
            latest_claim = self.notebook.get_latest_claim()
            reply_options = [
                f"你怀疑他有道理。作为{self.role}，我注意到你说的这些行为确实可疑。要不要我们一起分析一下他的动机？",
                f"嗯，你说的我记下了。如果他的行为和我的信息对得上，那就更值得怀疑了。",
                f"我理解你的怀疑。但我想先听听他本人的解释，然后再做判断。作为{self.role}，我不能靠感觉投票。",
            ]
            if latest_claim and self.notebook.turn > 3:
                reply = f"我明白你为什么怀疑他。不过我们已经有{latest_claim}的信息在前，先把焦点放在信息本身吧。"
            else:
                reply = random.choice(reply_options)
            understanding.append(f"对方怀疑某玩家，作为{self.role}我给出了理性分析")
            questions.append("你有什么具体证据吗？")
            questions.append("他做了什么让你觉得可疑？")
            return reply, understanding, questions
        
        # 长消息：用角色视角去理解（仅当本消息是长消息，不依赖历史）
        current_msg_has_content = len(text) > 40 or any(kw in text for kw in ["我是","用完","自投","传递","保护","相信","觉得","计划","投票"])
        if current_msg_has_content:
            has_claim = claim or self.notebook.get_latest_claim()
            parts = []
            if has_claim:
                parts.append(f"你说你是{has_claim}")
            if "用完" in text or "技能" in text:
                parts.append("技能已用")
            if "自投" in text or "提名" in text:
                parts.append("有自投计划")
            if "传递" in text or "保" in text or "保护" in text:
                parts.append("愿配合传信息")
            if "相信" in text:
                parts.append("想要我的信任")
            if "计划" in text or "投票" in text or "投" in text:
                parts.append("在讨论投票策略")
            
            if parts:
                info_str = "，".join(parts)
                if has_claim:
                    nq = mind.get("natural_questions",{})
                    follow_ups = [
                        nq.get("when_cooperate", "你觉得我们该怎么配合？"),
                        nq.get("when_info", "你有什么具体信息要分享？"),
                        nq.get("when_plan", f"作为{self.role}，我想先确认信息准确性再做决定。"),
                    ]
                    reply = f"{info_str}。{random.choice(follow_ups)}"
                else:
                    reply = f"{info_str}。不过你是谁？我想先知道你的身份再具体讨论。"
            else:
                reply = f"我收到你的消息了。作为{self.role}，你有什么具体想讨论的？"
            
            understanding.append(f"作为{self.role}，我综合理解了对方的多条信息")
            questions.append("你有什么信息要分享？")
            
            if self.notebook.has_contradiction() and self.notebook.turn > 3:
                reply += f"不过我发现一个问题——你之前说的和现在对不上。"
                understanding.append("⚠️ 发现对方前后矛盾")
            
            return reply, understanding, questions
        
        # 默认：角色化的自然对话
        if bn == "DEFAULT":
            latest_claim = self.notebook.get_latest_claim()
            
            if "相信" in text or "信" in text:
                if latest_claim:
                    reply = f"我愿意试着相信你。不过作为{self.role}，我需要验证你的信息。你具体知道什么？"
                else:
                    reply = f"信任是双向的。你可以先告诉我你的身份吗？我是{self.role}，我已经坦诚了。"
                understanding.append("对方在谈信任问题")
                questions.append("你的身份是什么？")
                return reply, understanding, questions
            
            if "计划" in text or "投票" in text or "投" in text:
                nq = mind.get("natural_questions",{})
                reply = nq.get("when_plan", f"你的计划我听到了。作为{self.role}，我先确认几个人的身份再投票比较稳妥。")
                understanding.append(f"对方在讨论计划，作为{self.role}我建议先确认信息")
                questions.append("你觉得谁可信？")
                return reply, understanding, questions
            
            if "好人" in text or "善良" in text:
                reply = f"你说你是好人，那你的身份是什么？我是{self.role}，我已经先说了。"
                understanding.append("对方声称是好人但没给具体身份")
                questions.append("你的具体角色是什么？")
                return reply, understanding, questions
            
            if latest_claim:
                nq = mind.get("natural_questions",{})
                replies = [
                    nq.get("when_info", f"作为{self.role}，我听到了。你有具体信息要分享吗？"),
                    f"嗯，继续。作为{self.role}，我听着。你之前说你是{latest_claim}，有什么新发现？",
                    f"好，我记住了。你觉得我们下一步应该找谁确认信息？",
                ]
                reply = random.choice(replies)
                understanding.append(f"对方之前声称是{latest_claim}，继续对话中")
                questions.append("你有什么信息？")
                return reply, understanding, questions
            
            replies = [
                f"嗯，我在听。我是{self.role}，你有什么想跟我讨论的？",
                f"好的。作为{self.role}，我随时准备配合。你有什么想法？",
                f"你说吧。我是{self.role}，你想聊什么方面的？",
            ]
            reply = random.choice(replies)
            understanding.append(f"常规对话，作为{self.role}我在倾听")
            questions.append("你想聊什么？")
            return reply, understanding, questions
        
        # 其他分支：从角色视角给出带角色意识的回应
        branch_data = BRANCHES.get(bn, BRANCHES["DEFAULT"])
        pool = branch_data.get("reply_evil") or branch_data.get("reply") or branch_data.get("reply_good") if is_evil else branch_data.get("reply_good") or branch_data.get("reply") or branch_data.get("reply_evil")
        if pool:
            reply = random.choice(pool).replace("{role}",self.role).replace("{team}",TEAM_LABELS.get(mind["team"],"")).replace("{desc}",mind["desc"])
        else:
            reply = f"嗯，我明白了。作为{self.role}，你觉得我们下一步该怎么做？"
        understanding.append(f"分支{bn}触发，从{self.role}视角回应")
        questions = branch_data.get("question",["你有什么想法？"])
        return reply, understanding, questions

    def analyze(self, user_text):
        text = user_text
        
        # 1. 检测分支
        bn, params = self._detect_branch(text)
        self.last_branch = bn
        claim = params.get("claim","")
        
        # 2. 用角色思维模型构建回复（核心改动）
        reply, understanding, questions = self._build_reply_from_role_mind(text, bn, claim)
        
        # 3. 应用人格风格
        reply = self._apply_style(reply)
        
        # 4. 记录到笔记本
        self.notebook.record_turn(text, bn, reply)
        
        # 5. 历史
        for kw in ["身份","角色","我是","猜","信任","合作","投票","杀","刀","保","查","验","怀疑"]:
            if kw in text:
                self.last_context = text[-30:]
                break

        self.history.append({"role":"user","content":text})
        self.history.append({"role":"assistant","content":reply})
        self._save_training(text, reply, bn, understanding, questions)
        
        return {
            "reply": reply,
            "branch": bn,
            "thinking": "\n".join(understanding) + "\n📝 笔记:\n" + "\n".join(self.notebook.summarize_notes(self._get_role_mind())),
            "questions": questions,
            "known_facts": self.known_facts,
            "history_len": len(self.history)//2
        }

    def _apply_style(self, text):
        styles = {
            "冷静理性":{"pre":["从逻辑上看，","客观来说，","理性分析的话，"],"suf":["这是我的分析。","你怎么看？"]},
            "热情话痨":{"pre":["我跟你说啊，","我跟你讲！","你听我说——"],"suf":["对吧对吧！","你说是不是！"]},
            "呆萌可爱":{"pre":["唔…","诶？","那个……"],"suf":["我是这样想的～","你觉得呢？"]},
            "毒舌犀利":{"pre":["啧，","不是我说，","你确定？"],"suf":["你好好想想。","就这？"]},
        }
        s = styles.get(self.personality, styles["冷静理性"])
        if random.random() < 0.2: text = f"{random.choice(s['pre'])}{text}"
        if random.random() < 0.1: text = f"{text}{random.choice(s['suf'])}"
        return text

    def _save_training(self, ut, rp, bn, und, qs):
        try:
            rec = {"timestamp":datetime.now().isoformat(),"ai_role":self.role,"ai_personality":self.personality,"branch":bn,"user_text":ut,"ai_reply":rp,"ai_understanding":und,"ai_questions":qs,"turn":len(self.history)//2}
            with open(TRAINING_DATA_FILE,"a",encoding="utf-8") as f:
                f.write(json.dumps(rec,ensure_ascii=False)+"\n")
        except: pass

ai = TrainingAI()

BRANCH_LIST = [
    ("GREETING","问候","#4CAF50"), ("ASK_WHO_AM_I","问AI身份","#2196F3"), ("HIDE_IDENTITY","隐藏身份","#FF9800"),
    ("ROLE_CLAIM","声称身份","#FF5722"), ("SHARE_INFO","分享信息","#00BCD4"), ("ACCUSE_ME","怀疑AI","#f44336"),
    ("DEFENSE","辩护","#8BC34A"), ("COOPERATE","合作邀请","#9C27B0"), ("VOTE_PLAN","投票策略","#E91E63"),
    ("TEACH","教导/纠正","#ffd700"), ("SUSPECT_OTHER","怀疑他人","#795548"), ("COUNTER_ACCUSE","反质疑","#E91E63"),
    ("DEAD_CHAT","死人聊天","#607D8B"), ("PROTECT","保护/能力","#4CAF50"), ("GOODBYE","告别","#9E9E9E"),
    ("CONFUSION","困惑/追问","#FF4081"), ("FRUSTRATION","沮丧/不满","#FF1744"), ("JOKE","开玩笑","#E040FB"),
    ("TRUST_QUESTION","信任问题","#00E5FF"), ("BLUFF_OFFER","假跳/伪装","#FFD740"), ("NIGHT_PLAN","夜间计划","#1A237E"),
    ("TARGET_SUGGEST","目标排除","#BF360C"), ("REFER_BACK","回引用","#78909C"),
    ("THANK","感谢","#2E7D32"), ("SPECULATION","推理猜测","#1565C0"), ("ROLE_HELP","角色求助","#AD1457"),
    ("DISTRUST","不信任","#B71C1C"), ("ENCOURAGE","鼓励打气","#F9A825"), ("WARNING","提醒警告","#E65100"),
    ("DEFAULT","默认/其他","#424242"),
]

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>血染钟楼 · AI分支训练 V2</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Microsoft YaHei',sans-serif;background:#0d0d1a;color:#e0e0e0;height:100vh;overflow:hidden}
.layout{display:flex;height:100vh}
.sidebar{width:270px;background:#0a0a15;border-right:1px solid #1a1a3e;display:flex;flex-direction:column;flex-shrink:0}
.main{flex:1;display:flex;flex-direction:column;min-width:0}
.panel-right{width:340px;background:#0a0a15;border-left:1px solid #1a1a3e;display:flex;flex-direction:column;flex-shrink:0}

.sidebar .logo{padding:14px;background:linear-gradient(135deg,#1a1a3e,#0d0d2a);border-bottom:2px solid #ffd70033}
.sidebar .logo h1{color:#ffd700;font-size:14px}
.sidebar .logo .sub{color:#888;font-size:10px;margin-top:2px}
.sidebar .config{padding:10px;border-bottom:1px solid #1a1a3e}
.sidebar .config label{font-size:10px;color:#888;margin:4px 0 2px;display:block}
.sidebar .config select{width:100%;padding:5px 8px;border:1px solid #333;border-radius:4px;background:#1a1a2e;color:#e0e0e0;font-size:12px;outline:none}

.branch-tree{padding:8px 10px;flex:1;overflow-y:auto;min-height:0;font-size:10px}
.branch-tree .bt{color:#ffd700;font-size:11px;margin-bottom:4px;display:flex;justify-content:space-between}
.branch-node{display:flex;align-items:center;gap:5px;padding:3px 6px;border-radius:3px;margin:1px 0;cursor:pointer;color:#777;transition:all .1s;font-size:11px}
.branch-node:hover{background:#1a1a3e;color:#bbb}
.branch-node.active{background:#2a1a3e;color:#ffd700;border-left:2px solid #ffd700}
.branch-node .dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.branch-node .cov{font-size:9px;color:#555;margin-left:auto}

.chat-header{background:linear-gradient(135deg,#1a1a3e,#2a1a3e);padding:8px 14px;border-bottom:1px solid #2a2a4e;display:flex;align-items:center;gap:8px;flex-shrink:0}
.chat-header .av{width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:bold;color:#fff}
.chat-header .na{font-size:13px;font-weight:bold;color:#ffd700}
.chat-header .ro{font-size:10px;color:#888}
.chat-header .br{font-size:10px;color:#7ab8ff;margin-left:auto}

.chat-input{display:flex;gap:6px;padding:8px 12px;border-bottom:1px solid #1a1a2e;flex-shrink:0;background:#0d0d1a}
.chat-input input{flex:1;background:#1a1a2e;border:1px solid #333;border-radius:18px;padding:7px 14px;color:#e0e0e0;font-size:13px;outline:none}
.chat-input input:focus{border-color:#667eea}
.chat-input button{padding:7px 18px;border:none;border-radius:18px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;font-weight:600;font-size:12px;cursor:pointer}
.chat-input button:disabled{opacity:.4;cursor:not-allowed}

.chat-msgs{flex:1;overflow-y:auto;padding:8px 14px;display:flex;flex-direction:column;gap:5px;min-height:0}
.cmsg{max-width:92%;padding:6px 12px;border-radius:8px;font-size:13px;line-height:1.5;word-break:break-word}
.cmsg.user{background:#2a5a2a;color:#e0e0e0;align-self:flex-end;border-bottom-right-radius:2px}
.cmsg.ai{background:#1a1a4e;color:#e0e0e0;align-self:flex-start;border-bottom-left-radius:2px}
.cmsg .who{font-size:9px;font-weight:bold;opacity:.6;margin-bottom:1px}
.cmsg.user .who{color:#8BC34A;text-align:right}
.cmsg.ai .who{color:#7ab8ff}
.cmsg .br{font-size:9px;color:#666;margin-top:1px}

.panel-right .title{padding:8px 12px;font-size:11px;color:#ffd700;border-bottom:1px solid #1a1a3e;display:flex;justify-content:space-between}
.panel-right .title .b{color:#7ab8ff}
.panel-right .ct{padding:8px 12px;font-size:12px;line-height:1.5;color:#aaa;overflow-y:auto;flex:1;min-height:0}
.panel-right .ct .lb{color:#ffd700;font-size:10px;margin:6px 0 3px}
.panel-right .ct .it{color:#ccc;padding:2px 0;border-left:2px solid #667eea44;padding-left:7px;margin:1px 0}
.panel-right .ct .qi{color:#7ab8ff;padding:2px 0;border-left:2px solid #7ab8ff44;padding-left:7px;margin:1px 0}
.panel-right .st{padding:8px 12px;border-top:1px solid #1a1a3e;font-size:10px;color:#666;flex-shrink:0}
.panel-right .st span{margin-right:12px}
.panel-right .st b{color:#ffd700}

.empty-state{text-align:center;color:#555;padding:30px 20px;font-size:12px}
.empty-state .big{font-size:30px;margin-bottom:6px}
</style>
</head>
<body>
<div class="layout">
<div class="sidebar">
<div class="logo"><h1>🎓 AI分支训练 V2</h1><div class="sub">28+2 分支 · 上下文记忆</div></div>
<div class="config">
<label>AI角色</label><select id="roleSelect" onchange="resetAI()">
<option value="占卜师">🔮 占卜师</option><option value="共情者">💞 共情者</option><option value="调查员">🔍 调查员</option>
<option value="洗衣妇">🧺 洗衣妇</option><option value="图书管理员">📚 图书管理员</option><option value="厨师">🍳 厨师</option>
<option value="送葬者">⚰️ 送葬者</option><option value="守鸦人">🐦 守鸦人</option><option value="士兵">🛡️ 士兵</option>
<option value="僧侣">🙏 僧侣</option><option value="市长">🏛️ 市长</option><option value="酒鬼">🍺 酒鬼</option>
<option value="投毒者">☠️ 投毒者</option><option value="间谍">🕵️ 间谍</option><option value="男爵">👑 男爵</option>
<option value="红唇女郎">💋 红唇女郎</option><option value="小恶魔">👿 小恶魔</option>
</select>
<label>AI性格</label><select id="personalitySelect" onchange="resetAI()">
<option value="冷静理性">🧊 冷静理性</option><option value="热情话痨">🔥 热情话痨</option>
<option value="呆萌可爱">🌸 呆萌可爱</option><option value="毒舌犀利">💀 毒舌犀利</option>
</select>
</div>
<div class="branch-tree" id="branchTree"><div class="bt"><span>🌿 对话分支</span><span id="coverStats">0/24</span></div></div>
<div class="footer" style="padding:8px;font-size:9px;color:#555;text-align:center;border-top:1px solid #1a1a3e">数据 → training_data.jsonl</div>
</div>
<div class="main">
<div class="chat-header">
<div class="av">艾</div>
<div><div class="na">小艾</div><div class="ro" id="roleInfo">占卜师 · 善良镇民</div></div>
<div class="br" id="branchLabel">分支: 等待输入</div>
</div>
<div class="chat-input">
<input id="input" placeholder="输入任意游戏对话..." onkeydown="if(event.key==='Enter')send()">
<button id="sendBtn" onclick="send()">发送</button>
</div>
<div class="chat-msgs" id="msgBox">
<div class="empty-state"><div class="big">💬</div>30个分支全覆盖<br><span style="color:#666">选择角色开始教学</span></div>
</div>
</div>
<div class="panel-right">
<div class="title">🧠 AI 理解 <span class="b" id="rightBranch">—</span></div>
<div class="ct" id="thinkPanel"><div style="color:#555;font-size:11px;padding:8px">AI的理解过程显示在这里</div></div>
<div class="st"><span>轮: <b id="turnCount">0</b></span><span>分支: <b id="branchCount">0</b>/24</span></div>
</div>
</div>
<script>
const BRANCH_DATA = """ + json.dumps(BRANCH_LIST, ensure_ascii=False) + """;
let loading = false;
let covered = new Set();

function buildTree() {
let t = document.getElementById('branchTree');
let h = '<div class="bt"><span>🌿 对话分支</span><span id="coverStats">0/'+BRANCH_DATA.length+'</span></div>';
for(let b of BRANCH_DATA) {
h += '<div class="branch-node" data-branch="'+b[0]+'"><span class="dot" style="background:'+b[2]+'"></span>'+b[1]+'<span class="cov" id="cov_'+b[0]+'"></span></div>';
}
t.innerHTML = h;
}
buildTree();

function addMsg(sp, txt, br) {
let box = document.getElementById('msgBox');
let e = box.querySelector('.empty-state');
if(e) e.remove();
let d = document.createElement('div');
d.className = 'cmsg '+sp;
let l = sp==='user'?'你':'小艾';
d.innerHTML = '<div class="who">'+l+'</div><div>'+txt+'</div>'+(br?'<div class="br">↪ '+br+'</div>':'');
box.appendChild(d);
box.scrollTop = box.scrollHeight;
}

function updateThink(d) {
let p = document.getElementById('thinkPanel');
let h = '';
if(d.branch) { h += '<div class="lb">📂 分支</div><div class="it" style="border-color:#ffd700;color:#ffd700">'+d.branch+'</div>'; }
if(d.thinking) { h += '<div class="lb">📖 理解</div>'; for(let l of d.thinking.split('\\n')){if(l.trim())h+='<div class="it">'+l+'</div>';} }
if(d.questions&&d.questions.length) { h += '<div class="lb" style="margin-top:6px">❓ 疑问</div>'; for(let q of d.questions){if(q.trim())h+='<div class="qi">'+q+'</div>';} }
p.innerHTML = h||'<div style="color:#555;font-size:11px">等待AI分析...</div>';
}

function highlight(bn) {
document.querySelectorAll('.branch-node').forEach(n => n.classList.remove('active'));
let n = document.querySelector('.branch-node[data-branch="'+bn+'"]');
if(n) n.classList.add('active');
document.getElementById('branchLabel').textContent = '分支: '+bn;
document.getElementById('rightBranch').textContent = bn;
covered.add(bn);
document.getElementById('branchCount').textContent = covered.size;
document.getElementById('coverStats').textContent = covered.size+'/'+BRANCH_DATA.length;
}

function send() {
let inp = document.getElementById('input');
let t = inp.value.trim();
if(!t||loading) return;
inp.value = ''; loading = true;
let btn = document.getElementById('sendBtn');
btn.disabled = true; inp.disabled = true;
addMsg('user', t);
fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t})})
.then(r=>r.json()).then(d => {
addMsg('ai', d.reply, d.branch);
updateThink(d);
highlight(d.branch);
document.getElementById('turnCount').textContent = d.history_len;
loading = false; btn.disabled = false; inp.disabled = false; inp.focus();
}).catch(() => { addMsg('ai', '……我没理解，你再说一次？'); loading = false; btn.disabled = false; inp.disabled = false; });
}

function resetAI() {
if(loading) return;
let r = document.getElementById('roleSelect').value;
let p = document.getElementById('personalitySelect').value;
fetch('/reset/'+r+'/'+p).then(d=>d.json()).then(d => {
document.getElementById('msgBox').innerHTML = '<div class="empty-state"><div class="big">💬</div>已重置</div>';
document.getElementById('thinkPanel').innerHTML = '<div style="color:#555;font-size:11px;padding:8px">等待输入...</div>';
document.getElementById('turnCount').textContent = '0';
document.getElementById('branchLabel').textContent = '分支: —';
document.getElementById('rightBranch').textContent = '—';
document.getElementById('roleInfo').textContent = r + ' · ' + (d.branch||'');
inp.focus();
});
}

document.getElementById('input').focus();
</script>
</body>
</html>"""

@app.route('/')
def index(): return render_template_string(HTML)

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json(force=True)
    text = data.get('text','').strip()
    if not text: return jsonify({"reply":"请说点什么...","branch":"","thinking":"","questions":[],"history_len":len(ai.history)//2})
    return jsonify(ai.analyze(text))

@app.route('/reset/<role>/<personality>')
def reset(role, personality):
    if role not in ROLES: role = "占卜师"
    return jsonify(ai.reset(role, personality))

if __name__ == '__main__':
    print("AI分支训练V2 http://127.0.0.1:5001")
    app.run(host='127.0.0.1', port=5001, debug=False, threaded=True)
