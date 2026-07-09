import sys, os, json, datetime
sys.path.insert(0, r'F:\本地训练的ai\werewolf_ai')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import train_ml_evil

# 从22000继续
train_ml_evil.load_checkpoint(22000)
train_ml_evil.TOTAL_GAMES = 80000
train_ml_evil.BATCH_SIZE = 2000
train_ml_evil.EVAL_INTERVAL = 2000
train_ml_evil.EVAL_GAMES = 100
train_ml_evil.NUM_PLAYERS = 7

t0 = datetime.datetime.now()
log_entries = []

for batch_num in range(12, 41):  # 22000 -> 80000 (14 batches)
    step = batch_num * 2000
    eps = max(0.05, 0.6 * (1 - step / 80000) ** 0.5)
    
    _, evil_r, errs = train_ml_evil.run_eval(eps=0.05, num_games=100)
    now = datetime.datetime.now()
    elapsed = str(now - t0).split('.')[0]
    entry = f"step={step} | good={100-evil_r*100:.0f}% | evil={evil_r*100:.0f}% | eps={eps:.3f} | time={elapsed}"
    log_entries.append(entry)
    print(entry)
    train_ml_evil.save_checkpoint(step)
    
    # 训练一个batch
    bw = {"good_win": 0, "evil_win": 0, "no_result": 0}
    for i in range(2000):
        try:
            r, _ = train_ml_evil.run_one_game(eps=eps, record=True)
            bw[r] = bw.get(r, 0) + 1
        except Exception:
            errs += 1
        if (i + 1) % 500 == 0:
            print(f"  batch progress: {i+1}/2000 (evil_wins={bw.get('evil_win',0)})")
    print(f"  batch done: evil_win={bw.get('evil_win', 0)}/2000")
    train_ml_evil.save_checkpoint(step)

# 最终评估
_, final_evil, _ = train_ml_evil.run_eval(eps=0.05, num_games=200)
print(f"\nFINAL EVAL (200 games): evil win rate = {final_evil:.1%}")
train_ml_evil.save_checkpoint(80000)

with open(os.path.join(os.path.dirname(__file__), 'extended_log.txt'), 'a', encoding='utf-8') as f:
    f.write(f"\nTraining: {datetime.datetime.now()}\n")
    f.write("\n".join(log_entries))
    f.write(f"\nFinal: {final_evil:.1%}\n")
print("\nDONE")
