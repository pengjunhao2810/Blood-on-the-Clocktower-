"""
训练循环：跑200局自我对弈，收集统计数据
运行: python train_loop.py
"""
import sys, os, json, random
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from games.blood_on_clocktower.rules import BloodOnClocktowerGame
from core.agent import SocialDeductionAgent

TOTAL_GAMES = 200
NUM_PLAYERS = 7
LOG_FILE = "training_log.txt"


def run_one_game():
    agents = [SocialDeductionAgent(f'玩家{i+1}', '?') for i in range(NUM_PLAYERS)]
    game = BloodOnClocktowerGame(num_players=NUM_PLAYERS, script='暗流涌动')
    game.setup_game(agents)
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
    return result, game.day_count


def main():
    wins = {"good_win": 0, "evil_win": 0, "no_result": 0}
    errors = 0
    total_days = 0
    finished = 0
    start = datetime.now()

    print(f"=== 血染钟楼 训练循环 ===")
    print(f"总局数: {TOTAL_GAMES}, 每局玩家: {NUM_PLAYERS}")
    print(f"开始时间: {start.strftime('%H:%M:%S')}\n")
    print("-" * 50)

    for i in range(1, TOTAL_GAMES + 1):
        try:
            result, days = run_one_game()
            wins[result] = wins.get(result, 0) + 1
            total_days += days
            finished += 1
            msg = f"[{i:3d}/{TOTAL_GAMES}] 第{days}天 {'善良' if result=='good_win' else '邪恶' if result=='evil_win' else '?'}胜"
        except Exception as e:
            errors += 1
            msg = f"[{i:3d}/{TOTAL_GAMES}] ❌ 错误: {e}"

        # 每10局输出一次进度统计
        if i % 10 == 0:
            good_pct = wins.get("good_win", 0) * 100 // max(finished, 1)
            evil_pct = wins.get("evil_win", 0) * 100 // max(finished, 1)
            avg_days = total_days / max(finished, 1)
            print(f"{msg} | 完成{finished}局: 善良{good_pct}% 邪恶{evil_pct}% 平均{avg_days:.1f}天")
        else:
            print(msg)

        if i % 50 == 0 and i < TOTAL_GAMES:
            print("-" * 50)

    elapsed = (datetime.now() - start).total_seconds()
    print("\n" + "=" * 50)
    print(f"训练完成！耗时{elapsed:.0f}s")
    print(f"有效局: {finished}, 错误: {errors}")
    print(f"善良胜: {wins.get('good_win', 0)} ({wins.get('good_win', 0)*100//max(finished,1)}%)")
    print(f"邪恶胜: {wins.get('evil_win', 0)} ({wins.get('evil_win', 0)*100//max(finished,1)}%)")
    print(f"平均时长: {total_days/max(finished,1):.1f}天")
    print("=" * 50)

    # 保存日志
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"训练时间: {datetime.now()}\n")
        f.write(f"总局数: {TOTAL_GAMES}, 每局玩家: {NUM_PLAYERS}\n")
        f.write(f"善良胜: {wins.get('good_win', 0)} ({wins.get('good_win', 0)*100//max(finished,1)}%)\n")
        f.write(f"邪恶胜: {wins.get('evil_win', 0)} ({wins.get('evil_win', 0)*100//max(finished,1)}%)\n")
        f.write(f"平均天数: {total_days/max(finished,1):.1f}\n")
    print(f"日志已保存至 {LOG_FILE}")


if __name__ == "__main__":
    main()
