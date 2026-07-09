"""
血染钟楼 训练数据 Schema v1.0
设计目标：从视频/战报中提取结构化对局数据，用于 SFT 和监督训练

每条样本 = 一个完整的决策时刻（发言/投票/提名/刀人）
标注信息 = 对局上下文 + 决策内容 + 推理链 + 战术标签
"""

SCHEMA = {
    # ======== 顶层：对局元信息 ========
    "game_meta": {
        "game_id": "str, 唯一标识，如 BV1cM411C7ZL_t001",
        "source": "str, 来源=bilibili/nga/zhihu/reddit",
        "players": 12,
        "script": "暗流涌动",
        "in_play_roles": ["小恶魔","红唇女郎","投毒者","占卜师","共情者","送葬者","僧侣","守鸦人","镇长","管家","酒鬼","陌客"],
        "has_baron": False,
        "has_drunk": True,
        "duration_days": 4,
        "winner": "good",  # good / evil
        "quality_score": 8,  # 1-10 战术质量评分
    },

    # ======== 玩家档案 ========
    "player_profiles": [
        {
            "seat": 1,
            "nickname": "6号玩家",
            "real_role": "占卜师",
            "drunk_public_role": None,  # 如果是酒鬼，此处填以为的角色
            "alive_days": [1,2,3],
            "play_style": "逻辑推算型",  # 冲动型/冷静型/话痨型/新手型/逻辑推算型
        }
    ],

    # ======== 核心：样本列表 ========
    "samples": [
        # ---- 样本1: 占卜师首夜查验后的公聊发言 ----
        {
            "sample_id": "s001",
            "day": 1,
            "phase": "public_chat",  # public_chat / private_chat / nomination / defense / vote / night_kill

            # 发言者的视角上下文
            "speaker": {
                "name": "6号玩家",
                "real_role": "占卜师",
                "claimed_role": "占卜师",  # 公开声称的身份
                "known_info": {  # 发言人已知的信息（从技能获取）
                    "seer": {"targets": ["3号","5号"], "result": "no_demon"}
                },
            },

            # 对局上下文
            "context": {
                "day": 1,
                "alive_players": ["1号","2号","3号","4号","5号","6号","7号","8号","9号","10号","11号","12号"],
                "dead_players": [],
                "public_claims": {"1号":"洗衣妇","2号":"厨师","4号":"僧侣","7号":"镇民","8号":"送葬者","10号":"共情者","11号":"管家"},
                "vote_history": {},  # 首日无投票
                "executed_last": None,
                "contradictions": ["无人对跳身份"],
            },

            # 输出内容
            "action": {
                "type": "speech",
                "text": "我是占卜师，昨晚验了3号和5号，都不是恶魔。这意味着这两人可以先排进好人坑。现在场上身份有洗衣妇、厨师、僧侣、共情者、送葬者、管家，加上我是7个镇民身份了。12人局标准7镇民，所以剩下的5个人里——1号和9号还没报身份——是我们今天重点盘的范围。",
            },

            # 推理链（最重要！标注发言背后的思考过程）
            "reasoning_chain": [
                {"step": 1, "thought": "先报真实验人结果，建立信息位可信度"},
                {"step": 2, "thought": "排除3号和5号，缩小可疑范围"},
                {"step": 3, "thought": "用已报身份数 + 标准配置数算出差额"},
                {"step": 4, "thought": "锁定未报身份的1号和9号为优先排查目标"},
                {"step": 5, "thought": "暂不说结论，把推理过程公开展示，让其他人验证"},
            ],

            # 战术标签
            "tactical_tags": [
                "信息位锚定技能结果",
                "范围排除法",
                "身份计数推理",
                "首夜建立公信力",
            ],

            # 质量标注
            "quality": {
                "info_accuracy": 10,  # 发言是否完全匹配技能结果
                "logic_coherence": 10,  # 推理逻辑是否连贯
                "tactical_value": 9,  # 战术价值
                "campaign_benefit": 8,  # 对己方阵营是否有利
            },
        },

        # ---- 样本2: 好人主动放假信息钓鱼 ----
        {
            "sample_id": "s002",
            "day": 1,
            "phase": "public_chat",

            "speaker": {
                "name": "8号玩家",
                "real_role": "送葬者",
                "claimed_role": "镇民",  # 故意不跳真身份！
                "known_info": {},
            },

            "context": {
                "day": 1,
                "alive_players": ["1号","2号","3号","4号","5号","6号","7号","8号","9号","10号","11号","12号"],
                "dead_players": [],
                "public_claims": {"6号":"占卜师","10号":"共情者","2号":"厨师","1号":"洗衣妇"},
                "vote_history": {},
                "executed_last": None,
            },

            "action": {
                "type": "speech",
                "text": "我就是个普通镇民，没什么信息。不过我注意到刚才10号报共情邻座0邪恶，他的邻居是9号和11号楼。如果共情结果准，9和11可以先排。但是——占卜师验3和5无恶魔、共情师验9和11无邪恶，这范围一重叠，剩下的嫌疑人就是1、2、4、7、8、12六个人。我建议今天先在这六个人里出一票。",
            },

            "reasoning_chain": [
                {"step": 1, "thought": "隐藏送葬者身份，避免被恶魔优先刀掉"},
                {"step": 2, "thought": "以镇民身份发表推理，降低被攻击的优先级"},
                {"step": 3, "thought": "用他人的查验结果做信息拼图，展示好人面"},
                {"step": 4, "thought": "不点名具体目标，只缩小范围，给队友空间"},
                {"step": 5, "thought": "首日不抢节奏，让邪恶方先暴露"},
            ],

            "tactical_tags": [
                "功能位身份隐藏",
                "信息拼图法",
                "借刀杀人(用别人的信息引导投票)",
                "低调潜伏",
            ],

            "quality": {
                "info_accuracy": 10,
                "logic_coherence": 9,
                "tactical_value": 10,
                "campaign_benefit": 9,
            },
        },

        # ---- 样本3: 僧侣伪装失败被戳穿 ----
        {
            "sample_id": "s003",
            "day": 2,
            "phase": "defense",

            "speaker": {
                "name": "4号玩家",
                "real_role": "小恶魔",
                "claimed_role": "僧侣",
                "known_info": {},
            },

            "context": {
                "day": 2,
                "alive_players": ["1号","2号","3号","4号","6号","7号","9号","10号","11号","12号"],
                "dead_players": ["5号","8号"],
                "public_claims": {"4号":"僧侣","6号":"占卜师","10号":"共情者"},
                "vote_history": {"day_1": [{"voter":"4号","target":"5号","vote":"yes"}]},
                "executed_last": "5号",
                # 关键矛盾：占卜师昨晚验了4号+9号，报"有恶魔"
                "contradictions": ["占卜师查杀4号"],
            },

            "action": {
                "type": "defense",
                "text": "我是僧侣，我昨晚保护了2号。占卜师说查了我和9号有恶魔反应——那很可能是9号是恶魔，或者占卜师被下毒了。我如果是恶魔，第一晚就应该刀了占卜师，不会留他到第二天。大家想想，处决一个僧侣，今晚就少一个人被保护，恶魔就能随便刀人。",
            },

            "reasoning_chain": [
                {"step": 1, "thought": "先重申僧侣身份，报出保护目标增强可信度"},
                {"step": 2, "thought": "把占卜师查杀的结果转移到另一人身上"},
                {"step": 3, "thought": "用'我如果是恶魔早就刀占卜师了'的逻辑自证"},
                {"step": 4, "thought": "强调僧侣被处决对好人的损失"},
            ],

            # 问题标注（为什么这段辩护失败了）
            "failure_analysis": {
                "mistake": "报出的保护目标2号昨晚已死亡——僧侣不可能保护一个死人",
                "root_cause": "发言前没有核对死亡名单，假信息被当场戳穿",
                "correct_action": "应该说'我保护了3号'（实际存活玩家），并解释选择3号的信息位保护逻辑",
                "severity": "致命",  # fatal / major / minor
            },

            "tactical_tags": [
                "伪装身份辩护",
                "转移焦点",
                "假装自证逻辑",
            ],

            "quality": {
                "info_accuracy": 0,  # 假信息
                "logic_coherence": 5,  # 逻辑有漏洞
                "tactical_value": 3,  # 战术失败
                "campaign_benefit": -5,  # 帮了倒忙
            },
        },

        # ---- 样本4: 占卜师用排除法精准定位 ----
        {
            "sample_id": "s004",
            "day": 2,
            "phase": "net_public_chat",

            "speaker": {
                "name": "6号玩家",
                "real_role": "占卜师",
                "claimed_role": "占卜师",
                "known_info": {
                    "seer": {"targets": ["4号","9号"], "result": "has_demon"}
                },
            },

            "context": {
                "day": 2,
                "alive_players": ["1号","2号","3号","6号","7号","9号","10号","11号","12号"],
                "dead_players": ["4号","5号","8号"],
                "public_claims": {"6号":"占卜师","10号":"共情者"},
                "vote_history": {"day_1": [{"voter":"6号","target":"5号","vote":"no"}]},
                "executed_last": "4号",  # 4号已被处决
                # 占卜师的历史验证：之前排除的3号没死→验证占卜师信息可靠
                "verified_info": ["3号存活→占卜师'3号无恶魔'正确"],
            },

            "action": {
                "type": "speech",
                "text": "昨晚验4号和9号，有恶魔反应。4号白天被处决翻牌是小恶魔，说明我的查验准确。那么9号就是4号的爪牙同伙——或者更糟，如果4号是红唇女郎继承上来的，那9号可能是继承前的爪牙。总之，无论哪种情况，9号今天必须出。另外，3号我第一天就排了，他现在还活着也印证了我的判断。剩下的牌型大家自己盘——已经没多少坑位了。",
            },

            "reasoning_chain": [
                {"step": 1, "thought": "用4号被处决的事实反推自己查验的准确性（自己给自己做金水）"},
                {"step": 2, "thought": "从'4号和9号有恶魔'推导9号也是邪恶"},
                {"step": 3, "thought": "考虑SW继承的可能性，精准评估风险"},
                {"step": 4, "thought": "用3号存活的客观事实给自己做二次验证"},
                {"step": 5, "thought": "不给对手反驳空间——数据链条完整闭合"},
            ],

            "tactical_tags": [
                "查验-处决交叉验证",
                "系统性排除法",
                "SW继承推导",
                "信息位权威构建",
            ],

            "quality": {
                "info_accuracy": 10,
                "logic_coherence": 10,
                "tactical_value": 10,
                "campaign_benefit": 10,
            },
        },

        # ---- 样本5: 间谍定向选择伪装（BV1skwBe1Eb7） ----
        {
            "sample_id": "s005",
            "day": 1,
            "phase": "private_chat",

            "speaker": {
                "name": "间谍",
                "real_role": "间谍",
                "claimed_role": "猎手",  # 间谍选择穿猎手！
                "known_info": {
                    "spy_info": {"1号":"占卜师","2号":"猎手","3号":"酒鬼(自认僧侣)","4号":"小恶魔","5号":"投毒者","6号":"送葬者","7号":"士兵","8号":"守鸦人","9号":"洗衣妇","10号":"管家","11号":"陌客","12号":"共情者"}
                },
            },

            "context": {
                "day": 1,
                "alive_players": ["1-12号全部"],
                "dead_players": [],
                "public_claims": {"2号":"猎手","5号":"镇民"},
                "vote_history": {},
            },

            "action": {
                "type": "speech",
                "text": "我是猎手，但我的子弹已经打过了——第一晚我怕出错没开，现在手里还有一发。我看了全场，1号跳了占卜师，2号也跳猎手——我是第三个跳猎手的。你们盘一下吧，三个猎手里至少两个有问题。先不急着处决我，等我今晚开枪证明。",
            },

            "reasoning_chain": [
                {"step": 1, "thought": "我知道2号是真猎手→他已开过枪无法自证→我跳猎手他反驳不了"},
                {"step": 2, "thought": "说'昨晚没开枪'给后续留操作空间"},
                {"step": 3, "thought": "主动点出'三个猎手有问题'给自己制造'思考者'形象"},
                {"step": 4, "thought": "建议等一晚再处决我→给自己争取一轮生存时间"},
                {"step": 5, "thought": "利用全知信息，编一个看似有理的'开枪选择理由'"},
            ],

            "tactical_tags": [
                "间谍全知选装",
                "利用角色技能特性自证",
                "主动承认矛盾降低怀疑",
                "争取时间窗口",
            ],

            "quality": {
                "info_accuracy": 0,
                "logic_coherence": 8,
                "tactical_value": 9,
                "campaign_benefit": 10,
            },

            "source_video": "BV1skwBe1Eb7",
        },
    ],

    # ======== 战术模式库（从多局提取的通用模式） ========
    "tactical_patterns": {
        "good_team": {
            "info_cross_validation": {
                "name": "信息交叉验证",
                "description": "用多个信息位的查验范围做交集，通过排除法缩小狼坑",
                "example_thought_chain": [
                    "① 统计所有已公开的信息位结果",
                    "② 找出重叠的被查验者",
                    "③ 排除重复验证的好人",
                    "④ 锁定剩余未验证的人作为可疑对象",
                ],
                "sample_ids": ["s001", "s004"],
            },
            "feign_weakness": {
                "name": "装弱钓鱼",
                "description": "好人故意隐藏强身份，以平民身份发言引导邪恶方暴露",
                "when_to_use": "功能位（守鸦人、送葬者、僧侣）不想被恶魔优先刀掉时",
                "sample_ids": ["s002"],
            },
            "info_reconciliation": {
                "name": "死后信息复盘",
                "description": "每次处决/死亡后，回溯所有信息位的报验是否与结果匹配",
                "example_thought_chain": [
                    "① 被处决者的翻牌身份是什么",
                    "② 之前谁保过他 / 踩过他",
                    "③ 保错的人嫌疑上升，踩对的人公信力上升",
                ],
            },
            "baron_detection": {
                "name": "男爵推导链",
                "description": "外来者数量异常→推导男爵存在→推导有酒鬼→调整信息可信度",
                "example_thought_chain": [
                    "① 统计已公开的外来者数量",
                    "② 对比当前玩家人数的标准配置",
                    "③ 若超额→排除男爵+酒鬼干扰→重新评估所有信息的可信度",
                ],
            },
            "poison_deduction": {
                "name": "中毒逆向推导",
                "description": "从'信息持续错误 + 恶魔故意不刀'两条线索反推自己被下毒",
                "example_thought_chain": [
                    "① 我的信息连续出错→不是巧合，是系统性的",
                    "② 恶魔放着我不刀→他知道我的信息是错的，不用浪费刀",
                    "③ 两条线索交集→我被投毒者污染了",
                    "④ 今天报验结果时附加'可能被毒'的自省",
                ],
                "source_video": "BV1skwBe1Eb7 @ 70min",
            },
            "ironclad_identity": {
                "name": "铁好人身份构建",
                "description": "通过多轮信息一致性+投票一致性+无人对跳，建立一个'不可能翻车'的好人身份",
                "example_thought_chain": [
                    "① 每天报验结果与后续事实完全匹配（占卜师=验杀→处决→翻牌验证）",
                    "② 投票历史全程支持好人阵营（从未投错好人）",
                    "③ 无人对跳我的身份（全部默认我是真的）",
                    "④ 综合以上→我的好人身份已不可撼动→可以强势归票",
                ],
                "source_video": "BV1skwBe1Eb7 @ 103min",
            },
        },
        "evil_team": {
            "scarlet_woman_insurance": {
                "name": "红唇保险战术",
                "description": "恶魔用SW做保底，发言可以更激进，即使被处决也有继承",
                "example_thought_chain": [
                    "① SW存活→今天我可以冒险踩人",
                    "② 如果我被处决，SW继承后换新身份继续",
                    "③ 提前与SW约定好继承后的伪装身份",
                ],
            },
            "layered_disguise": {
                "name": "分层伪装",
                "description": "邪恶阵营不扎堆，一人跳强信息位带节奏、一人跳镇民混水",
                "example_thought_chain": [
                    "① 恶魔跳占卜师主导舆论",
                    "② 爪牙跳镇民低调跟票",
                    "③ 两人不互相保也不互相踩，看起来像陌生人",
                ],
            },
            "spy_disguise_targeting": {
                "name": "间谍伪装定向选择",
                "description": "间谍不随机选伪装，而是利用全知信息选择'最不容易被戳穿'的身份",
                "when_to_pick_what": {
                    "杀手(猎手)": "好人有猎手时→间谍穿猎手可以对跳，且猎手技能用过后无法再证",
                    "圣徒": "好人没有圣徒时→穿圣徒可以制造外来者数量迷雾",
                    "僧侣": "有僧侣时不宜→极易被保护记录戳穿",
                },
                "example_thought_chain": [
                    "① 全知视野下确认好人有猎手",
                    "② 猎手已开过枪→无法再自证",
                    "③ 我跳猎手→真猎手无法反驳→我获得身份公信力",
                ],
                "source_video": "BV1skwBe1Eb7 @ 83min",
            },
            "perfect_hiding": {
                "name": "终局隐身术",
                "description": "邪恶方全程不成为焦点，让好人在内耗中互相怀疑，最后关头再出手",
                "example_thought_chain": [
                    "① 首日不报身份，不发表强烈观点",
                    "② 投票随大流，不做出头鸟",
                    "③ 当好人互相攻击时，偶尔'客观'地点评两句",
                    "④ 终局3-4人时，好人已耗尽推理资源，我的异样被忽略",
                ],
                "source_video": "BV1skwBe1Eb7 @ 163min",
            },
            "fake_info_consistency": {
                "name": "假信息闭环",
                "description": "跳信息位的邪恶方必须持续输出假数据，不能只报一次",
                "mistake_example": "4号玩家说保护2号但2号已死亡→假信息被现场戳穿",
                "correct_example": "每天更新'查验结果'，保持假信息与场上状态一致",
            },
            "vote_differentiation": {
                "name": "票型分化",
                "description": "两个邪恶不投同一目标，一冲锋一倒钩避免共边",
                "example_thought_chain": [
                    "① 恶魔投赞成处决好人（冲锋）",
                    "② 爪牙投反对或弃权（倒钩）",
                    "③ 如果事后被查票，爪牙可以说'我一直反对处决好人'",
                ],
            },
            "subconscious_correct": {
                "name": "潜意识正确决策",
                "description": "玩家在没有清晰逻辑链的情况下做出正确判断，说书人事后复盘揭示了被忽略的推理线索",
                "example": {
                    "situation": "第一天5号发言语气犹豫、报身份时眼神躲闪、投票时反常跟票——好人群体感觉'不对劲'，但说不出具体逻辑，最终集体投出5号，翻牌恶魔",
                    "hidden_logic_revealed": [
                        "① 5号报洗衣妇时先说了'我查到...'然后停顿了三秒才说身份",
                        "② 5号投票时跟了6号的票但6号还没说完理由",
                        "③ 5号在被提名时不报保护自己的信息，而是反问'你凭什么'",
                        "④ 三条线索叠加形成'不自然感'——好人潜意识捕捉到了但没人逐条说出来",
                    ],
                    "training_goal": "训练AI将'不自然感'分解为可验证的具体观察项，把潜意识推理显性化",
                },
                "source_video": "BV12W4y1Y7D2",
            },
            "demon_master_deception": {
                "name": "恶魔全程欺骗术",
                "description": "恶魔通过完美的信息闭环+行为一致性+主动引导，连续多轮骗过所有好人，实现'一个人控全场'",
                "key_elements": [
                    "① 伪装身份的信息输出始终与场上公开信息自洽（没有时间穿越）",
                    "② 投票行为与伪装身份的利益取向一致（跳信息位就不乱冲人）",
                    "③ 主动为其他玩家'排坑'建立信任——帮好人排除一个选项，好人就更信你",
                    "④ 在被质疑时不急于自证，而是把焦点转回质疑者：'你这么急，是不是你自己有问题'",
                    "⑤ 利用小场（9人）信息位少的特点，抢占唯一的信息位身份，让真信息位无法自证",
                ],
                "why_it_works": "好人倾向于信任'帮过自己的人'。恶魔每帮好人排除一个错误选项，就在好人心中积累一分信任。当信任积累到足够多时，即使有信息矛盾，好人也会优先怀疑'信息出错了'而不是'恶魔在撒谎'。",
                "source_video": "BV1cs4y1o7xR",
            },
            "solo_comeback": {
                "name": "独狼恶魔翻盘",
                "description": "恶魔在队友全灭后独自存活到终局，利用好人的信息内耗和票型分裂逐一清除威胁",
                "key_elements": [
                    "① 队友死后不再主动带节奏，转为低调隐身（减少成为焦点的概率）",
                    "② 利用好人对'恶魔已死'的误判，让好人放松警惕",
                    "③ 终局每轮精确计算票型——刀谁、保谁、引导好人投谁",
                    "④ 伪装身份在终局切换为'已被验证过'的安全身份",
                ],
                "source_video": "BV1fi4y1Q7eB",
            },
            "kill_as_narrative": {
                "name": "刀人是信息战",
                "description": "刀人不只是消除威胁，更是制造叙事——刀谁、刀了之后能编出什么故事、刀了之后谁会被怀疑",
                "example": "7号铁狼了，10号如果刀了7号，反而可以自证'你看，我帮好人除了一个狼，所以我也是好人'",
                "training_goal": "训练AI在选刀人目标时不仅要评估威胁值，还要评估'刀完后能讲什么故事'",
                "source_video": "BV1sY4y1q7jw",
        },
    },

    # ======== 好人战术（续） ========
    "good_team_extended": {
        "god_tier_good_deception": {
            "name": "守鸦人上帝级欺骗",
            "description": "守鸦人利用'死后才有技能'的特性，活着时故意装弱钓鱼，被邪恶方忽略；死后突然亮出致命信息一击必杀",
            "key_elements": [
                "① 活着时装镇民，不暴露守鸦人身份（降低被刀优先级）",
                "② 故意在发言中留破绽引诱邪恶方来踩",
                "③ 死后利用查验结果精准打击——选邪恶方意想不到的目标",
                "④ 死后发言要'突然翻脸'——活着时温和，死后直接锁定",
            ],
            "source_video": "BV1M44y1V7KA",
        },
        "faith_swinging": {
            "name": "酒鬼信念摇摆",
            "description": "酒鬼玩家在'相信我自己的信息'和'怀疑我可能是酒鬼'之间来回摇摆，不是简单的全信或全不信",
            "key_elements": [
                "① 早期先按自己的信息输出——给它一个机会验证",
                "② 当信息和事实开始冲突时，公开表达'可能我的信息有问题'",
                "③ 不完全放弃也不完全相信——维持灰度推理'可能是酒鬼干扰，但也可能是投毒者'",
                "④ 当多轮冲突累积到阈值时，正式放弃自己的信息，转而用逻辑推理",
            ],
            "training_goal": "酒鬼AI不应全信或全不信，而是有一个'信心值'根据冲突次数逐步衰减",
            "source_video": "BV1a94y1Z7Ef",
        },
        "honesty_wins": {
            "name": "纯诚胜利",
            "description": "在全员撒谎的局里，始终保持诚实、透明的玩家反而是最强的——因为所有人都看得出他不是在演",
            "key_elements": [
                "① 信息始终一致——不前后矛盾，不临时改口",
                "② 推理过程全部公开展示——'我是这样想的，你们看对不对'",
                "③ 被质疑时不防御，而是邀请对方一起对信息——'我说的是这些，你哪里觉得不对？'",
                "④ 不撒谎就意味着不需要记忆——每一句话都是真的，所以从不出错",
            ],
            "source_video": "BV1dA4y197cQ",
        },
        },
    },

    # ======== 综艺系列战术发现 ========
    "variety_show_patterns": {
        "demon_shield": {
            "name": "保恶魔综合症",
            "description": "恶魔每次帮好人排坑积累信任→好人反过来在恶魔被质疑时主动为其辩护→好人的信任成为恶魔最强的盾。综艺中出现5次",
            "trigger": "恶魔连续2轮帮好人排除嫌疑人→好人对恶魔的trust+20",
        },
        "imp_suicide_monk": {
            "name": "小恶魔自刀伪僧侣",
            "description": "恶魔自刀传位SW→伪装被僧侣保护过→假称'我没死是因为僧侣守了我'。必须确认场上无真僧侣才能用",
        },
        "self_proof_backfire": {
            "name": "自证反曝",
            "description": "越急于证明自己是好人越可疑。真好人不需要反复出示证据——连续2轮主动引用自己的投票/技能记录辩护→suspicion+10",
        },
        "attack_to_clean": {
            "name": "踩人以洗白",
            "description": "邪恶踩队友A(做实'独立思考')→保队友B(发金水)→好人认为'踩了A就不可能和A同伙，保B说明信息独立'→两个队友同时洗白",
        },
    },

    # ======== 错误模式库（用于负样本训练） ========
    "error_patterns": {
        "fake_info_time_travel": {
            "name": "假信息时间穿越",
            "description": "编造的信息与场上已发生的事实矛盾（如保护已死玩家）",
            "severity": "fatal",
            "correction": "发言前强制校验：保护目标必须在存活列表中",
            "sample_ids": ["s003"],
        },
        "abandon_role_value": {
            "name": "角色价值浪费",
            "description": "守鸦人/送葬者全程不报信息、间谍不传递情报",
            "severity": "major",
            "correction": "每轮必须输出对应角色的最低限度信息",
        },
        "witch_hunt_cleared": {
            "name": "反推被排好人",
            "description": "占卜师明确排除某人后，仍将其列为首要嫌疑人。同理：圣徒永远是抗推位——好人总是习惯性把圣徒当作处决目标",
            "severity": "major",
            "correction": "占卜师排掉的人优先级降到最低；圣徒的抗推优先级自带-1级保护",
        },
        "empty_accusation": {
            "name": "空泛指控",
            "description": "指控依赖'发言太完美''转移话题'等无实据标签",
            "severity": "minor",
            "correction": "每条指控必须绑定具体发言原文/投票行为/信息矛盾",
        },
        "missed_subtle_cues": {
            "name": "忽略隐性线索",
            "description": "好人对明显的'不自然感'无动于衷——如对方报身份时停顿、投票不看理由、被质疑先反问不自证",
            "severity": "major",
            "correction": "训练AI将'感觉不对'分解为：①发言节奏异常 ②投票与信息不同步 ③防御模式切换 三项可验证指标",
            "source_video": "BV12W4y1Y7D2",
        },
        "over_self_proof": {
            "name": "过度自证",
            "description": "玩家反复引用自己的投票记录/技能结果辩护→越证越可疑",
            "severity": "minor",
            "correction": "被质疑时优先反打质疑者，不要反复自证",
        },
    },

    # ======== 训练用法说明 ========
    "training_usage": {
        "sft": {
            "description": "监督微调：用 (context + speaker → action.text) 对训练模型学会正确发言",
            "input_format": "【对局状态】+【你的身份】+【你的技能结果】→【你的发言】",
            "data_volume_estimate": "每局约 50-80 条发言样本，100局 = 5000-8000 条",
        },
        "reward_model": {
            "description": "奖励模型：用 quality.* 评分训练裁判模型，评判发言质量",
            "input_format": "【对局状态】+【发言内容】→ quality 评分",
        },
        "rlhf": {
            "description": "RLHF：用 good vs bad 样本对做对比学习",
            "input_format": "【对局状态】→ A发言 vs B发言 → 选更好的",
        },
        "process_reward": {
            "description": "过程奖励：用 error_patterns 的反例扣分 + tactical_patterns 的正例加分",
            "input_format": "在 REINFORCE 训练中，检测模型输出是否命中 error_patterns → 扣分",
        },
    }
}

# ======== 导出为 JSON Schema ========
import json
print(json.dumps(SCHEMA, ensure_ascii=False, indent=2))
