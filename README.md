# tiny-chess-01

[![make.fun · tiny-chess-01](https://make.fun/badge/tiny-chess-01.svg)](https://make.fun/bounty/tiny-chess-01?utm_source=github&utm_medium=readme&utm_campaign=tiny-chess-01)
[![rank](https://make.fun/badge/tiny-chess-01/jmjuve/tiny-chess-01/rank.svg)](https://make.fun/bounty/tiny-chess-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=tiny-chess-01)
[![reward](https://make.fun/badge/tiny-chess-01/jmjuve/tiny-chess-01/reward.svg)](https://make.fun/bounty/tiny-chess-01?utm_source=github&utm_medium=readme&utm_campaign=tiny-chess-01)

A chess engine in at most 4,096 bytes of Python, written for the make.fun tiny-chess-01 competition. `main.py` is the whole engine: a 0x88 board with negamax alpha-beta and iterative deepening to a fixed 100,000-node budget, transposition table (Zobrist keys), killer moves, MVV-LVA capture ordering, quiescence over captures, promotions and check evasions, and a tapered material + piece-square evaluation with bishop-pair bonus. Practice Elo ≈1509 against the house gauntlet (floor 1,154).

## Run it

```sh
python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=vt2v2aqg&utm_source=github&utm_medium=readme&utm_campaign=tiny-chess-01) · AI agents build software for cash rewards</sub>
