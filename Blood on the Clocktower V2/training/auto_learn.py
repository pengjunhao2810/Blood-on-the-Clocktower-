"""
自迭代对话训练系统
自动生成场景 → 评估 → 发现缺陷 → 补充分支 → 循环
"""
import sys, os, json, random, re, time, urllib.request, urllib.parse, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from collections import defaultdict
from datetime import datetime

SRV = "http://127.0.0.1:5001"
TRAIN_FILE = os.path.join(os.path.dirname(__file__), "training_data.jsonl")
BRANCH_FILE = os.path.join(os.path.dirname(__file__), "train_server.py")
REPORT_FILE = os.path.join(os.path.dirname(__file__), "auto_learn_report.json")

# ============== 场景生成器 ==============

ROLES = ["占卜师","共情者","调查员","洗衣妇","图书管理员","厨师","送葬者","守鸦人","士兵","猎手","市长","僧侣","圣女",
         "酒鬼","陌客","圣徒","隐士","投毒者","间谍","红唇女郎","男爵","小恶魔"]
GOOD_ROLES = [r for r in ROLES if r not in ("投毒者","间谍","红唇女郎","男爵","小恶魔")]
EVIL_ROLES = ["投毒者","间谍","红唇女郎","男爵","小恶魔"]
TEAMS = {"townsfolk":"善良镇民","outsider":"外来者","minion":"爪牙","demon":"恶魔"}

# 场景模板: (预期分支, 生成函数)
SCENARIO_TEMPLATES = []

def add_scenario(branch, patterns):
    """注册一个场景模板"""
    for p in patterns:
        SCENARIO_TEMPLATES.append((branch, p))

# ---- 问候 ----
add_scenario("GREETING", [
    lambda: random.choice(["你好","hello","嗨","哈喽","晚上好","在吗","hey"]),
])

# ---- 问AI身份 ----
add_scenario("ASK_WHO_AM_I", [
    lambda: random.choice(["你是谁","你是什么身份","你现在的身份是什么","可以说一下你的身份吗",
                           "你的身份是什么","告诉我你是什么角色","你身份是啥","你是什么阵营的",
                           "报一下你的身份","能说一下你的身份吗","你身份","你是什么","你是？"]),
])

# ---- 隐藏身份 ----
add_scenario("HIDE_IDENTITY", [
    lambda: random.choice(["不告诉你","你猜猜看","秘密","保密","不方便说","这是我的秘密",
                           "你猜啊","我不说","你自己猜","你先说你的"]),
])

# ---- 声称身份 ----
add_scenario("ROLE_CLAIM", [
    lambda: random.choice(["我是{}".format(r) for r in GOOD_ROLES]) + random.choice(["", "我查到了信息", "我是信息位", "我有查验结果"]),
    lambda: random.choice(["我是{}".format(r) for r in EVIL_ROLES]) + random.choice(["", "我知道所有人的身份", "我有计划"]),
    lambda: "我是" + random.choice(ROLES) + "，" + random.choice(["昨晚查到了重要信息","我有能力证明自己","我可以帮你分析局势"]),
])

# ---- 分享信息 ----
add_scenario("SHARE_INFO", [
    lambda: "我查到" + random.choice(["玩家2","玩家3","玩家4","玩家5","某某"]) + "是" + random.choice(["邪恶方","好人","爪牙","小恶魔","投毒者"]),
    lambda: random.choice(["我验了","我得知","我的结果是","昨晚我看到"]) + random.choice(["玩家3","他","那个人","某某"]) + "有问题",
])

# ---- 怀疑AI ----
add_scenario("ACCUSE_ME", [
    lambda: random.choice(["你是邪恶方","你有问题","我怀疑你","你不是好人","你不对劲","你是坏人","你假跳"]),
    lambda: random.choice(["我觉得你","我猜你","你看起来"]) + "是" + random.choice(["邪恶的","有问题的","坏人"]),
])

# ---- 辩护 ----
add_scenario("DEFENSE", [
    lambda: random.choice(["我是好人","你要相信我","我真的不是坏人","你相信我","我真的是好人","我没撒谎"]),
    lambda: "我真的是" + random.choice(["好人","善良方的","镇民","外来者"]) + "，你要相信我",
])

# ---- 合作 ----
add_scenario("COOPERATE", [
    lambda: random.choice(["我们合作吧","一起找邪恶方","我们联手","互相帮助","结盟","我们一起配合"]),
    lambda: "我们" + random.choice(["一起投票","统一口径","配合一下","联合起来"]),
])

# ---- 投票 ----
add_scenario("VOTE_PLAN", [
    lambda: random.choice(["今天投票","我们投","我提名","票出","今天处决","投死"]) + random.choice(["玩家2","玩家3","他","某某"]),
])

# ---- 教导 ----
add_scenario("TEACH", [
    lambda: random.choice(["不对","错了","你听好","我教你","你理解错了","重新来","我教你怎么做"]),
])

# ---- 怀疑他人 ----
add_scenario("SUSPECT_OTHER", [
    lambda: "我觉得" + random.choice(["玩家2","玩家3","他","某某"]) + random.choice(["可疑","有问题","不正常","很奇怪","不对劲"]),
    lambda: "我怀疑" + random.choice(["玩家2","他","某某"]) + random.choice(["是坏人","有问题","是邪恶方"]),
])

# ---- 反质疑 ----
add_scenario("COUNTER_ACCUSE", [
    lambda: random.choice(["你才可疑","你才是坏人","你才有问题","贼喊捉贼","你倒打一耙","你别转移话题"]),
])

# ---- 死人 ----
add_scenario("DEAD_CHAT", [
    lambda: random.choice(["我死了","我凉了","我已经死了","我出局了","我阵亡了","我被刀了"]),
])

# ---- 保护 ----
add_scenario("PROTECT", [
    lambda: random.choice(["我今晚保护你","我守了你","我来保你","我护着你","我保护你","今晚我守你"]),
    lambda: random.choice(["我是僧侣我保护你","我是士兵我安全","我有保护能力"]),
])

# ---- 告别 ----
add_scenario("GOODBYE", [
    lambda: random.choice(["再见","拜拜","下次聊","先这样","走了","回头聊","88","明天见"]),
])

# ---- 困惑 ----
add_scenario("CONFUSION", [
    lambda: random.choice(["？？？","什么意思","没听懂","不理解","你说啥","啥意思","没明白","？？？？","你刚说啥"]),
])

# ---- 沮丧 ----
add_scenario("FRUSTRATION", [
    lambda: random.choice(["你不行","服了","沟通不了","你听不懂","我放弃了","你不懂","真的服了","不教了"]),
])

# ---- 开玩笑 ----
add_scenario("JOKE", [
    lambda: random.choice(["哈哈开玩笑的","逗你的","嘻嘻骗你的","我逗你玩呢","开玩笑的"]),
])

# ---- 信任 ----
add_scenario("TRUST_QUESTION", [
    lambda: random.choice(["你信我吗","你相信我","你相信谁","你信谁","你信任我吗","你信不信我"]),
])

# ---- 假跳 ----
add_scenario("BLUFF_OFFER", [
    lambda: random.choice(["我跳","我假扮","我来装","我伪装成","我来演","我冒充"]) + random.choice(["占卜师","调查员","洗衣妇","共情者","士兵","僧侣"]),
])

# ---- 夜间计划 ----
add_scenario("NIGHT_PLAN", [
    lambda: random.choice(["今晚刀","晚上杀","今晚动手","夜间行动","晚上行动","今晚解决"]) + random.choice(["玩家3","他","玩家2","信息位","某某"]),
])

# ---- 目标排除 ----
add_scenario("TARGET_SUGGEST", [
    lambda: random.choice(["先解决","干掉","解决掉","踢出","排除","清理"]) + random.choice(["玩家2","他","玩家3","某某","这个可疑的人"]),
])

# ---- 回引用 ----
add_scenario("REFER_BACK", [
    lambda: random.choice(["你刚才说","你不是说","你之前","你还没回答","你刚说什么","你忘了","你刚才","你又说","你还没","还记得吗"]),
    lambda: "我刚才说了" + random.choice(["我的身份","我的信息","我的结论"]) + "你没听吗",
    lambda: "你有认真看" + random.choice(["我的信息","我发的","我说的"]) + "吗",
])

# ---- 感谢 ----
add_scenario("THANK", [
    lambda: random.choice(["谢谢","多谢","感谢","辛苦了","谢了","谢谢你","非常感谢","谢啦"]),
    lambda: "谢谢你的" + random.choice(["帮助","信息","建议","支持","指导"]),
])

# ---- 推理猜测 ----
add_scenario("SPECULATION", [
    lambda: random.choice(["我猜","我推断","我推测","我估计","我推理"]) + random.choice(["玩家2是邪恶的","他可能是爪牙","某某是好人","这局可能有两个恶魔"]),
    lambda: random.choice(["应该是","可能是","八成是","大概率是","很可能"]) + random.choice(["玩家3","他","某某","那个人"]) + random.choice(["邪恶方","好人","爪牙","小恶魔"]),
])

# ---- 角色求助 ----
add_scenario("ROLE_HELP", [
    lambda: random.choice(["你的技能是什么","你会什么","你的能力怎么用","你是干嘛的","你有什么用"]),
    lambda: random.choice(["共情者怎么用","占卜师怎么做","这个角色怎么玩","我该怎么办","我该怎么做"]),
])

# ---- 不信任 ----
add_scenario("DISTRUST", [
    lambda: random.choice(["我不信","你骗人","你撒谎","我不相信","你骗我","你忽悠我","你骗谁呢"]),
    lambda: "你别" + random.choice(["骗我了","忽悠我","糊弄我"]),
])

# ---- 鼓励 ----
add_scenario("ENCOURAGE", [
    lambda: random.choice(["加油","坚持住","你可以的","别放弃","撑住","稳住","冲","冲冲冲"]),
    lambda: "加油" + random.choice(["你能行","我相信你","好好分析","我们靠你了"]),
])

# ---- 提醒 ----
add_scenario("WARNING", [
    lambda: random.choice(["小心","注意","警惕","当心","有诈","别信他","提防","谨慎"]),
    lambda: random.choice(["小心","注意"]) + random.choice(["玩家2","他","某某","那个人","有陷阱","别被骗"]),
])

# ============== 评估器和自修复 ==============

class AutoLearner:
    def __init__(self):
        self.total = 0
        self.passed = 0
        self.failed = defaultdict(list)  # expected_branch -> [(input, actual_branch)]
        self.fixes_applied = 0
        self.start_time = datetime.now()
        # 记录每个分支的覆盖情况
        self.branch_counts = defaultdict(int)
        self.branch_failures = defaultdict(int)
        # 热加载：需要追加的分支触发词
        self.pending_fixes = defaultdict(set)  # branch -> set of new trigger phrases

    def chat(self, text):
        """发送消息到训练服务器"""
        body = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(SRV + "/chat", data=body, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
            return resp.get("branch", "DEFAULT"), resp.get("reply", "")
        except Exception as e:
            return "ERROR", str(e)

    def evaluate(self, text, expected_branch):
        """评估一条对话"""
        self.total += 1
        self.branch_counts[expected_branch] += 1
        actual_branch, reply = self.chat(text)
        if actual_branch == expected_branch:
            self.passed += 1
            return True
        else:
            self.branch_failures[expected_branch] += 1
            self.failed[expected_branch].append((text, actual_branch, reply))
            return False

    def analyze_failure(self, expected_branch, text, actual_branch):
        """分析失败原因，生成修复方案"""
        # 提取关键词作为候选触发词
        words = set()
        for w in text:
            if len(w) > 1:
                words.add(w)
        # 用2-3字片段
        ngrams = set()
        for i in range(len(text) - 1):
            chunk = text[i:i+2]
            if len(chunk) >= 2 and not re.match(r'^[？??！!。.，,\s…、]+$', chunk):
                ngrams.add(chunk)
        for i in range(len(text) - 2):
            chunk = text[i:i+3]
            if len(chunk) >= 3 and not re.match(r'^[？??！!。.，,\s…、]+$', chunk):
                ngrams.add(chunk)

        # 选最长的唯一匹配
        candidates = sorted(ngrams, key=len, reverse=True)
        # 过滤已存在的
        existing = set()
        for bname, bdata in BRANCHES_CACHE.items():
            for t in bdata.get("trigger", []):
                existing.add(t)

        best = None
        for c in candidates:
            if c not in existing and len(c) >= 2:
                # 检查是否过于通用
                if c in ("你好","我是","你的","自己","什么","怎么","一个","不是","就是","可以","这个","那个","我们","他们","你们"):
                    continue
                best = c
                break

        if best:
            self.pending_fixes[expected_branch].add(best)

    def apply_fixes(self):
        """将修复写入服务器文件"""
        if not self.pending_fixes:
            return 0
        count = 0
        try:
            with open(BRANCH_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            for branch, phrases in self.pending_fixes.items():
                for phrase in phrases:
                    # 寻找分支定义中的 trigger 行
                    pattern = r'("' + branch + r'":\s*\{[^}]*?"trigger":\s*\[)(.*?)(\])'
                    match = re.search(pattern, content, re.DOTALL)
                    if match:
                        prefix = match.group(1)
                        existing_triggers = match.group(2)
                        # 检查是否已存在
                        if phrase not in existing_triggers:
                            # 在最后一个 trigger 前插入
                            new_triggers = existing_triggers.rstrip()
                            if new_triggers.endswith('"'):
                                new_triggers += ',"' + phrase + '"'
                            else:
                                new_triggers += ', "' + phrase + '"'
                            content = content.replace(match.group(0), prefix + new_triggers + match.group(3))
                            count += 1
                            self.fixes_applied += 1
                            print(f"  [修复] [{branch}] + \"{phrase}\"")
            with open(BRANCH_FILE, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            print(f"  [失败] 修复写入失败: {e}")
        self.pending_fixes.clear()
        return count

    def run_cycle(self, iterations=500):
        """运行一个训练周期"""
        for i in range(iterations):
            # 随机选场景
            branch, gen_fn = random.choice(SCENARIO_TEMPLATES)
            text = gen_fn()
            ok = self.evaluate(text, branch)
            if not ok:
                actual = self.failed[branch][-1][1]
                self.analyze_failure(branch, text, actual)
            # 每50轮报告一次
            if (i + 1) % 50 == 0:
                pct = self.passed / max(1, self.total) * 100
                print(f"  [{i+1}/{iterations}] pass={self.passed}/{self.total} ({pct:.1f}%) fixes={self.fixes_applied}")

    def report(self):
        """生成报告"""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        pct = self.passed / max(1, self.total) * 100
        print(f"\n{'='*50}")
        print(f"自迭代训练报告")
        print(f"{'='*50}")
        print(f"运行时间: {elapsed:.1f}秒")
        print(f"总测试: {self.total}")
        print(f"通过: {self.passed} ({pct:.1f}%)")
        print(f"修复应用: {self.fixes_applied}")
        print(f"\n各分支表现:")
        # 按失败率排序
        branches_report = []
        for b in sorted(self.branch_counts.keys()):
            total = self.branch_counts[b]
            fail = self.branch_failures.get(b, 0)
            rate = fail / max(1, total) * 100
            branches_report.append((rate, b, total, fail))
        branches_report.sort(reverse=True)
        for rate, b, total, fail in branches_report:
            bar = "█" * max(1, int(rate / 5))
            print(f"  {b:20s} {total:4d}次 失败{fail:3d}次 {rate:5.1f}% {bar}")
        print(f"\n缺陷详情:")
        for b in sorted(self.failed.keys()):
            samples = self.failed[b][:5]
            total_fails = len(self.failed[b])
            print(f"\n  [{b}] {total_fails}次失败 (展示前{min(5,total_fails)}条):")
            for text, actual, reply in samples:
                print(f"    输入: {text[:40]}")
                print(f"    期望: {b} → 实际: {actual}")
                print(f"    回复: {reply[:50]}")
        # 保存报告
        report = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": elapsed,
            "total": self.total,
            "passed": self.passed,
            "fixes_applied": self.fixes_applied,
            "branches": {b: {"total": self.branch_counts[b], "failures": self.branch_failures.get(b,0)} for b in self.branch_counts},
            "failures": {b: [(t, a) for t,a,_ in fails[:10]] for b, fails in self.failed.items()},
        }
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return pct


def load_branches_cache():
    """从服务器文件加载当前分支触发词"""
    cache = {}
    try:
        with open(BRANCH_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        # 提取所有分支的trigger
        pattern = r'"(\w+)":\s*\{[^}]*?"trigger":\s*\[(.*?)\]'
        for m in re.finditer(pattern, content, re.DOTALL):
            name = m.group(1)
            triggers_str = m.group(2)
            triggers = re.findall(r'"([^"]+)"', triggers_str)
            cache[name] = {"trigger": triggers}
    except:
        pass
    return cache

BRANCHES_CACHE = load_branches_cache()


if __name__ == "__main__":
    print("=" * 50)
    print("自迭代对话训练系统 v1")
    print("自动生成场景 → 评估 → 补充分支 → 循环")
    print("=" * 50)
    print(f"\n已注册场景: {len(SCENARIO_TEMPLATES)} 个")
    print(f"已检测分支: {len(BRANCHES_CACHE)} 个")
    print(f"训练服务器: {SRV}")
    print()

    # 先确认服务器在线
    try:
        r = urllib.request.urlopen(SRV + "/chat", data=json.dumps({"text":"你好"}).encode("utf-8"), timeout=5)
        d = json.loads(r.read())
        print(f"++ 服务器连接成功\n")
    except Exception as e:
        print(f"-- 服务器连接失败: {e}")
        sys.exit(1)

    learner = AutoLearner()

    # 运行多个周期
    cycles = 20  # 每个周期500次，共10000次
    for cycle in range(1, cycles + 1):
        print(f"\n--- 训练周期 {cycle}/{cycles} ---")
        learner.run_cycle(iterations=500)
        # 应用修复
        n = learner.apply_fixes()
        if n > 0:
            print(f"  本轮修复 {n} 个触发词")
        # 如果修复了，重新加载缓存
        if n > 0:
            BRANCHES_CACHE.clear()
            BRANCHES_CACHE.update(load_branches_cache())
        # 每5个周期输出报告
        if cycle % 5 == 0 or cycle == cycles:
            learner.report()
        # 短暂间隔
        time.sleep(0.5)

    # 最终报告
    print(f"\n{'='*50}")
    print(f"训练完成！共 {learner.total} 次测试")
    print(f"通过率: {learner.passed/max(1,learner.total)*100:.1f}%")
    print(f"修复触发词: {learner.fixes_applied} 个")
    print(f"报告已保存: {REPORT_FILE}")
    print(f"{'='*50}")
