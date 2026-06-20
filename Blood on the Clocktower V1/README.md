# Blood on the Clocktower V1 — AI Self-Play Simulator

An AI-driven simulation of the social deduction game **Blood on the Clocktower** (Trouble Brewing script). Features a **Flask web UI** with real-time game visualization, multi-round private chat with bubble UI, and full day/night cycle automation.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Flask](https://img.shields.io/badge/flask-3.x-green)
![GitHub](https://img.shields.io/badge/license-MIT-yellow)

## Features

- **Full Game Engine** — Faithful implementation of Trouble Brewing (暗流涌动): 22 roles, night order, poisoning, drifting, Baron modifier, and all role abilities.
- **AI Players** — Each player is powered by a rule-based AI agent with memory, suspicion scoring, trust modeling, and strategic voting. Evil team coordinates via private chat.
- **Multi-Round Private Chat** — Each player chats with 2 other players per day, 2 rounds each. Conversations are stored as threaded chat logs with a realistic **bubble UI** (left = speaker A, right = speaker B).
- **Web Interface** — Flask-based single-page app with:
  - Player cards showing role icons and status
  - Step-by-step or auto-play (0.9s interval)
  - Clickable private chat threads
  - Role distribution table (5–12 players, base config)
  - Game log with highlighted player names and role tags
- **Self-Play Training** — Supports running hundreds of games headlessly for win-rate analysis. Achieves ~53% good / ~47% evil balance.

## Quick Start

### Requirements

- Python 3.10–3.12
- Flask 3.x

```bash
pip install flask
```

### Run

```bash
cd "Blood on the Clocktower V1"
python botc_web/app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

*Keep the terminal window open while using the app.*

## How to Use

| Button | Action |
|--------|--------|
| ▶ Next Step | Advance the game by one phase |
| ▶ Auto Play | Auto-advance every 0.9 seconds |
| ↻ New Game | Reset with the same player count |
| Player Selector (top-right) | Choose 5–12 players |

### Phases

1. **Role Assignment** — Roles are dealt; each player sees their role.
2. **Night** — Night actions execute in official order (poisoner → spy → washerwoman → librarian → investigator → chef → empath → fortune teller → butler → dawn).
3. **Private Chat** — Players pair up for 2-round whispered conversations.
4. **Public Chat** — All alive players speak in turn, claiming roles and sharing info.
5. **Nomination & Voting** — Players nominate, defend, and vote to execute.

## Project Structure

```
botc_web/
  app.py              — Flask server, HTML template with embedded CSS/JS
games/
  blood_on_clocktower/
    rules.py          — Game logic: setup, night, day, voting, win conditions
    roles.py          — 22 role definitions, night order tables
core/
  agent.py            — SocialDeductionAgent: memory, suspicion, speech generation
  game_manager.py     — Base GameManager class
  memory.py           — GameMemory and ExperienceMemory
README.md             — This file
```

## Role Distribution (Base Config)

| Players | Townsfolk | Outsider | Minion | Demon |
|---------|-----------|----------|--------|-------|
| 5 | 3 | 0 | 1 | 1 |
| 6 | 3 | 1 | 1 | 1 |
| 7 | 5 | 0 | 1 | 1 |
| 8 | 5 | 0 | 2 | 1 |
| 9 | 5 | 2 | 1 | 1 |
| 10 | 7 | 0 | 2 | 1 |
| 11 | 7 | 1 | 2 | 1 |
| 12 | 7 | 2 | 2 | 1 |

*Baron adds +2 Outsiders (replacing Townsfolk).*

## Night Order

**First Night**: Dusk → Minion Info → Demon Info → Poisoner → Spy → Washerwoman → Librarian → Investigator → Chef → Empath → Fortune Teller → Butler → Dawn

**Other Nights**: Dusk → Poisoner → Monk → Spy → Scarlet Woman → Imp → Ravenkeeper → Undertaker → Empath → Fortune Teller → Butler → Dawn

## Training

To run headless self-play games (e.g., 200 games for win-rate analysis):

```python
from games.blood_on_clocktower.rules import BloodOnClocktowerGame
from core.agent import SocialDeductionAgent

game = BloodOnClocktowerGame(num_players=7)
agents = [SocialDeductionAgent(f'P{i+1}', 0.3) for i in range(7)]
game.setup_game(agents)

for r in range(20):
    game.run_day()
    if game.game_record.get('result'): break
    game.run_night()
    if game.game_record.get('result'): break

print(game.game_record['result'])
```

## Known Limitations

- Trouble Brewing script only
- Player names are fixed as "玩家1" ~ "玩家N"
- AI uses rule-based heuristics (no LLM / neural network)
- UI labels and chat are in Chinese
- Development Flask server (not production-ready)

## License

MIT
