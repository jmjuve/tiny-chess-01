# tiny-chess-01

A chess engine in at most 4,096 bytes of Python, written for the
make.fun tiny-chess-01 competition. `main.py` is the whole engine: it
plays the house gauntlet through the env at `MAKEFUN_ENV_URL`.

## Engine

- 0x88 board, signed piece codes, incremental material + piece-square
  evaluation (king tapered by phase, bishop-pair bonus)
- Negamax alpha-beta with iterative deepening to a fixed node budget
  (100,000 nodes a move), so play is deterministic and replay-safe
- Transposition table (Zobrist keys), killer moves, MVV-LVA capture
  ordering, quiescence over captures, promotions and check evasions
- Repetition and fifty-move rules score 0 inside the search

## Layout

- `main.py` — the engine (the only file the entry runs)
- `LICENSE` — MIT
- `transcripts/session.jsonl` — the build transcript (working record;
  not part of the submitted snapshot)
