"""
ML 训练：邪恶方策略梯度强化学习
运行: python train_ml_evil.py

使用 REINFORCE 算法，通过自对弈逐步提升邪恶方胜率。
"""
import sys, os, json, random
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'F:\本地训练的ai\werewolf_ai')
from games.blood_on_clocktower.rules import BloodOnClocktowerGame
from core.agent import SocialDeductionAgent
from games.blood_on_clocktower.ml_policy import (
    get_policy, get_trainer, set_record, set_epsilon,
    is_recording, reset, is_enabled
)

# ============ 超参数 ============
NUM_PLAYERS = 7
BATCH_SIZE = 400          # 每轮训练局数
TOTAL_GAMES = 4000        # 总训练局数
INIT_EPS = 0.6            # 初始探索率
FINAL_EPS = 0.05          # 最终探索率
EVAL_INTERVAL = 400       # 每 N 局做一次评估
EVAL_GAMES = 100          # 每次评估跑 N 局
LOG_FILE = "ml_training_log.txt"
MODEL_DIR = "ml_checkpoints"


def run_one_game(eps=0.3, record=False, show_detail=False):
    """跑一局，使用 ML 策略"""
    agents = [SocialDeductionAgent(f'玩家{i+1}', '?') for i in range(NUM_PLAYERS)]
    game = BloodOnClocktowerGame(num_players=NUM_PLAYERS, script='暗流涌动')
    game.setup_game(agents)

    set_epsilon(eps)
    set_record(record)

    for d in range(1, 21):
        game.run_night()
        game.start_day()
        game._private_chat_phase()
        game._public_chat_phase()
        game._nomination_and_voting_phase()
        game.end_day()
        if game.game_record.get('result'):
            break

    result = game.game_record.get('result', 'no_result')
    # 记录轨迹并更新策略
    if record:
        win = "evil" in result
        loss_val = get_trainer().finish_episode(win)
        if show_detail:
            game.log(f"[ML] 邪恶{'胜' if win else '负'} loss={loss_val:.4f}")

    return result, game.day_count


def run_eval(eps=0.05, num_games=100):
    """评估当前策略（不记录梯度）"""
    wins = {"good_win": 0, "evil_win": 0, "no_result": 0}
    errors = 0
    for i in range(num_games):
        try:
            result, _ = run_one_game(eps=eps, record=False)
            wins[result] = wins.get(result, 0) + 1
        except Exception as e:
            errors += 1
    good = wins.get("good_win", 0)
    evil = wins.get("evil_win", 0)
    total = max(num_games - errors, 1)
    return good / total, evil / total, errors


def save_checkpoint(step):
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, f"policy_step{step}.pt")
    torch_save = __import__('torch').save
    torch_save(get_policy().state_dict(), path)
    return path


def load_checkpoint(step):
    path = os.path.join(MODEL_DIR, f"policy_step{step}.pt")
    if os.path.exists(path):
        torch_load = __import__('torch').load
        get_policy().load_state_dict(torch_load(path, map_location='cpu'))
        return True
    return False


def main():
    print("=" * 60)
    print("  邪恶方 ML 策略训练 (REINFORCE)")
    print(f"  玩家: {NUM_PLAYERS}人 | 总训练: {TOTAL_GAMES}局 | 每批: {BATCH_SIZE}局")
    print("=" * 60)

    start_time = datetime.now()

    # 初始评估
    print(f"\n[初始评估] 跑 {EVAL_GAMES} 局 (eps=0.05)...")
    good_r, evil_r, errs = run_eval(eps=0.05, num_games=EVAL_GAMES)
    print(f"  善良 {good_r:.1%} | 邪恶 {evil_r:.1%} | 错误 {errs}")
    print(f"  {'→ 邪恶方需要提升!' if evil_r < 0.3 else '→ 邪恶方还不错!'}")
    print("-" * 60)

    best_evil_rate = evil_r
    history = [{"step": 0, "good": good_r, "evil": evil_r, "eps": 0.0}]

    for step in range(1, TOTAL_GAMES // BATCH_SIZE + 1):
        eps = max(FINAL_EPS, INIT_EPS * (1 - step * BATCH_SIZE / TOTAL_GAMES) ** 0.5)
        batch_wins = {"good_win": 0, "evil_win": 0, "no_result": 0}
        batch_errors = 0

        print(f"\n[批次 {step}] 训练 {BATCH_SIZE} 局 (eps={eps:.2f})...")
        batch_start = datetime.now()

        for i in range(BATCH_SIZE):
            try:
                result, _ = run_one_game(eps=eps, record=True)
                batch_wins[result] = batch_wins.get(result, 0) + 1
            except Exception as e:
                batch_errors += 1

            if (i + 1) % 50 == 0:
                pct = (i + 1) * 100 // BATCH_SIZE
                print(f"  {pct}% ({i+1}/{BATCH_SIZE})")

        batch_elapsed = (datetime.now() - batch_start).total_seconds()

        good_pct = batch_wins.get("good_win", 0) * 100 / max(BATCH_SIZE, 1)
        evil_pct = batch_wins.get("evil_win", 0) * 100 / max(BATCH_SIZE, 1)
        print(f"  [BATCH] 善良 {good_pct:.0f}% | 邪恶 {evil_pct:.0f}% | 错误 {batch_errors}")
        print(f"  [TIME] {batch_elapsed:.0f}s")

        # 评估
        eval_eps = max(0.05, eps * 0.5)
        print(f"  [评估] 跑 {EVAL_GAMES} 局 (eps={eval_eps:.2f})...")
        good_r, evil_r, errs = run_eval(eps=eval_eps, num_games=EVAL_GAMES)
        print(f"  善良 {good_r:.1%} | 邪恶 {evil_r:.1%} | 错误 {errs}")

        history.append({
            "step": step * BATCH_SIZE,
            "good": good_r,
            "evil": evil_r,
            "eps": eps,
        })

        # 保存最佳模型
        if evil_r > best_evil_rate:
            best_evil_rate = evil_r
            ckpt = save_checkpoint(step * BATCH_SIZE)
            print(f"  [NEW BEST] 邪恶 {evil_r:.1%} -> 已保存 {ckpt}")
        else:
            print(f"  当前最佳: 邪恶 {best_evil_rate:.1%}")

        # 输出趋势
        recent = history[-3:]
        trend = "↑" if len(recent) >= 2 and recent[-1]["evil"] > recent[-2]["evil"] else "↓" if len(recent) >= 2 and recent[-1]["evil"] < recent[-2]["evil"] else "→"
        rates = [f'{h["evil"]:.0%}' for h in recent]
        print(f"  趋势: {trend}  邪恶胜率: {rates}")

        print("-" * 60)

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n{'=' * 60}")
    print(f"  训练完成! 耗时 {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"  最佳邪恶胜率: {best_evil_rate:.1%}")

    # 保存最终模型
    final_ckpt = save_checkpoint("final")
    print(f"  最终模型: {final_ckpt}")

    # 保存训练日志
    log_lines = [
        f"训练时间: {datetime.now()}",
        f"总局数: {TOTAL_GAMES}",
        f"批次大小: {BATCH_SIZE}",
        f"初始探索率: {INIT_EPS}",
        f"最终探索率: {FINAL_EPS}",
        f"",
        f"step,good,evil,eps",
    ]
    for h in history:
        log_lines.append(f"{h['step']},{h['good']:.4f},{h['evil']:.4f},{h['eps']:.2f}")
    log_lines.append(f"\n最佳邪恶胜率: {best_evil_rate:.1%}")
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    print(f"  日志: {LOG_FILE}")
    print(f"{'=' * 60}")

    return best_evil_rate


if __name__ == "__main__":
    main()
