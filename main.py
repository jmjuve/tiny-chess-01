import base64, json, os, random, sys, urllib.request

# Tiny chess engine: 0x88 board, negamax alpha-beta, iterative deepening to
# a fixed node budget, transposition table, killer moves, MVV-LVA ordering,
# quiescence over captures/promotions/check evasions, incremental eval
# (material + piece-square tables + bishop pair, king tapered by phase).
# Deterministic: no clock, no unseeded randomness.

U = os.environ["MAKEFUN_ENV_URL"]
VAL = [0, 100, 320, 330, 500, 900, 0]
MATE = 100000
NODES = 60000
OPEN = 6600  # 2*(2*320+2*330+2*500+900): non-pawn material at the start

# Piece-square tables: 7 tables (pawn, knight, bishop, rook, queen, king
# middlegame, king endgame), a8-first, left half only (mirrored). Base64 of
# bytes holding value+80.
_PST = base64.b64decode(
    "UFBQUIKCgoJaWmRuVVVaaVBQUGRVS0ZQVVpaPFBQUFAeKDIyKDxQUDJQWl8yVV9kMlBfZDJVWl8oPFBVHigyMjxGRkZGUFBQRlBVWkZVVVpGUFpaRlpaWkZVUFA8RkZGUFBQUFVaWlpLUFBQS1BQUEtQUFBLUFBQS1BQUFBQUFU8RkZLRlBQUEZQVVVLUFVVUFBVVUZVVVVGUFVQPEZGSzIoKB4yKCgeMigoHjIoKB48MjIoRjw8PGRkUFBkblpQHigyPDI8RlAyRmRuMkZueDJGbngyRmRuMjJQUB4yMjI="
)
_T = []
for _i in range(7):
    _tab = []
    for _r in range(8):
        _half = list(_PST[_i * 32 + _r * 4 : _i * 32 + _r * 4 + 4])
        _tab += [v - 80 for v in _half + _half[::-1]]
    _T.append(_tab)
# PV[p+6][sq]: material + piece-square value of piece p on 0x88 square sq,
# signed (black pieces negative) so the incremental score is a plain sum.
PV = [[0] * 128 for _ in range(13)]
for _t in range(5):
    for _sq in range(128):
        if _sq & 0x88:
            continue
        _r, _f = _sq >> 4, _sq & 7
        PV[_t + 7][_sq] = VAL[_t + 1] + _T[_t][(7 - _r) * 8 + _f]
        PV[5 - _t][_sq] = -(VAL[_t + 1] + _T[_t][_r * 8 + _f])
KMG, KEG = _T[5], _T[6]

_R = random.Random(0xC0FFEE)
Z = [[_R.getrandbits(64) for _ in range(128)] for _ in range(13)]
ZW = _R.getrandbits(64)
ZC = [_R.getrandbits(64) for _ in range(16)]
ZE = [_R.getrandbits(64) for _ in range(8)]
KEEP = [15] * 128
KEEP[4] = 12
KEEP[7] = 14
KEEP[0] = 13
KEEP[116] = 3
KEEP[119] = 11
KEEP[112] = 7

# Mutable position state.
B = [0] * 128  # 0x88 board; white 1..6, black -1..-6
W = True       # side to move is white
C = 0          # castling rights: 1 WK, 2 WQ, 4 BK, 8 BQ
E = -1         # en passant target square, or -1
H = 0          # halfmove clock
S = 0          # incremental eval, white perspective, non-king pieces
K = 0          # zobrist key
PH = 0         # non-pawn material, both sides
KS = [4, 116]  # king squares: [white, black]
CNT = [0] * 13 # piece counts by code+6
HIST = set()   # position keys of the game so far
PATH = set()   # position keys on the search path
TT = {}        # key -> (depth, flag, score, best move)
KIL = [[0, 0] for _ in range(128)]
N = 0          # nodes searched this move
LIM = 0        # node budget this move


class Abort(Exception):
    pass


def kingval(sq, white):
    r, f = sq >> 4, sq & 7
    i = (7 - r) * 8 + f if white else r * 8 + f
    return (KMG[i] * PH + KEG[i] * (OPEN - PH)) // OPEN


def ev():
    s = S + kingval(KS[0], True) - kingval(KS[1], False)
    if CNT[9] >= 2:
        s += 30
    if CNT[3] >= 2:
        s -= 30
    return s if W else -s


def atk(sq, white):
    # Is sq attacked by side `white`?
    if white:
        for d in (-15, -17):
            if not (sq + d) & 0x88 and B[sq + d] == 1:
                return True
    else:
        for d in (15, 17):
            if not (sq + d) & 0x88 and B[sq + d] == -1:
                return True
    p = 2 if white else -2
    for d in (33, 31, 18, 14, -14, -18, -31, -33):
        t = sq + d
        if not t & 0x88 and B[t] == p:
            return True
    p = 6 if white else -6
    for d in (1, -1, 16, -16, 15, 17, -15, -17):
        t = sq + d
        if not t & 0x88 and B[t] == p:
            return True
    for d, ps in ((15, 3), (17, 3), (-15, 3), (-17, 3), (1, 4), (-1, 4), (16, 4), (-16, 4)):
        t = sq + d
        while not t & 0x88:
            q = B[t]
            if q:
                if (q > 0) == white and abs(q) in (ps, 5):
                    return True
                break
            t += d
    return False


def gen(caps=False):
    ms = []
    ap = []
    for sq in range(128):
        if sq & 0x88:
            continue
        p = B[sq]
        if not p or (p > 0) != W:
            continue
        t = abs(p)
        if t == 1:
            d = 16 if W else -16
            r = sq >> 4
            t1 = sq + d
            if not caps or (r == 6 if W else r == 1):
                if B[t1] == 0:
                    if r == (6 if W else 1):
                        for pr in (5, 4, 3, 2):
                            ms.append(sq | (t1 << 7) | (pr << 14))
                    else:
                        ms.append(sq | (t1 << 7))
                        if r == (1 if W else 6):
                            t2 = sq + 2 * d
                            if B[t2] == 0:
                                ms.append(sq | (t2 << 7))
            for dd in (d - 1, d + 1):
                t3 = sq + dd
                if t3 & 0x88:
                    continue
                q = B[t3]
                if q and (q > 0) != W:
                    if r == (6 if W else 1):
                        for pr in (5, 4, 3, 2):
                            ms.append(sq | (t3 << 7) | (pr << 14))
                    else:
                        ms.append(sq | (t3 << 7))
                elif t3 == E:
                    ms.append(sq | (t3 << 7))
        elif t == 2:
            for d in (33, 31, 18, 14, -14, -18, -31, -33):
                t1 = sq + d
                if t1 & 0x88:
                    continue
                q = B[t1]
                if not q or (q > 0) != W:
                    if not caps or q:
                        ms.append(sq | (t1 << 7))
        elif t == 6:
            for d in (1, -1, 16, -16, 15, 17, -15, -17):
                t1 = sq + d
                if t1 & 0x88:
                    continue
                q = B[t1]
                if not q or (q > 0) != W:
                    if not caps or q:
                        ms.append(sq | (t1 << 7))
            if not caps:
                if W:
                    if C & 1 and B[5] == 0 and B[6] == 0 and B[7] == 4 \
                            and not atk(4, False) and not atk(5, False) and not atk(6, False):
                        ms.append(4 | (6 << 7))
                    if C & 2 and B[3] == 0 and B[2] == 0 and B[1] == 0 and B[0] == 4 \
                            and not atk(4, False) and not atk(3, False) and not atk(2, False):
                        ms.append(4 | (2 << 7))
                else:
                    if C & 4 and B[117] == 0 and B[118] == 0 and B[119] == -4 \
                            and not atk(116, True) and not atk(117, True) and not atk(118, True):
                        ms.append(116 | (118 << 7))
                    if C & 8 and B[115] == 0 and B[114] == 0 and B[113] == 0 and B[112] == -4 \
                            and not atk(116, True) and not atk(115, True) and not atk(114, True):
                        ms.append(116 | (114 << 7))
        else:
            ds = (15, 17, -15, -17) if t == 3 else (1, -1, 16, -16) if t == 4 \
                else (1, -1, 16, -16, 15, 17, -15, -17)
            for d in ds:
                t1 = sq + d
                while not t1 & 0x88:
                    q = B[t1]
                    if q:
                        if (q > 0) != W:
                            ms.append(sq | (t1 << 7))
                        break
                    if not caps:
                        ms.append(sq | (t1 << 7))
                    t1 += d
    return ms


def make(m):
    global W, C, E, H, S, K, PH
    f = m & 127
    t = (m >> 7) & 127
    pr = m >> 14
    p = B[f]
    cap = B[t]
    u = (m, cap, C, E, H, S, K, PH, KS[0], KS[1])
    K ^= ZW ^ ZC[C]
    if E >= 0:
        K ^= ZE[E & 7]
    S -= PV[p + 6][f]
    K ^= Z[p + 6][f]
    B[f] = 0
    if cap:
        S -= PV[cap + 6][t]
        K ^= Z[cap + 6][t]
        CNT[cap + 6] -= 1
        if abs(cap) != 1:
            PH -= VAL[abs(cap)]
    np = pr if pr else p
    if pr:
        np = pr if p > 0 else -pr
        CNT[p + 6] -= 1
        CNT[np + 6] += 1
        PH += VAL[pr]
    B[t] = np
    S += PV[np + 6][t]
    K ^= Z[np + 6][t]
    if abs(p) == 6:
        KS[0 if p > 0 else 1] = t
        if t - f == 2:  # kingside castle
            B[t - 1] = B[t + 1]
            B[t + 1] = 0
            S += PV[B[t - 1] + 6][t - 1] - PV[B[t - 1] + 6][t + 1]
            K ^= Z[B[t - 1] + 6][t - 1] ^ Z[B[t - 1] + 6][t + 1]
        elif f - t == 2:  # queenside castle
            B[t + 1] = B[t - 2]
            B[t - 2] = 0
            S += PV[B[t + 1] + 6][t + 1] - PV[B[t + 1] + 6][t - 2]
            K ^= Z[B[t + 1] + 6][t + 1] ^ Z[B[t + 1] + 6][t - 2]
    elif abs(p) == 1 and t == E and not cap:
        # en passant: captured pawn sits beside the target
        cs = t - 16 if p > 0 else t + 16
        cp = B[cs]
        B[cs] = 0
        S -= PV[cp + 6][cs]
        K ^= Z[cp + 6][cs]
        CNT[cp + 6] -= 1
        u = u + (cs,)
    else:
        u = u + (-1,)
    if abs(p) == 1 and abs(t - f) == 32:
        E = (f + t) // 2
    else:
        E = -1
    # castling rights: a king or rook leaving its home square, or a rook
    # captured on its home square, loses that side's rights
    C &= KEEP[f]
    if cap and abs(cap) == 4:
        C &= KEEP[t]
    if E >= 0:
        K ^= ZE[E & 7]
    K ^= ZC[C]
    H = 0 if abs(p) == 1 or cap else H + 1
    W = not W
    return u


def unmake(u):
    global W, C, E, H, S, K, PH
    m, cap, C, E, H, S, K, PH, k0, k1 = u[:10]
    cs = u[10] if len(u) > 10 else -1
    f = m & 127
    t = (m >> 7) & 127
    pr = m >> 14
    p = B[t]
    if pr:
        CNT[(p) + 6] -= 1
        CNT[(1 if p > 0 else -1) + 6] += 1
        p = 1 if p > 0 else -1
    B[f] = p
    B[t] = cap
    if cs >= 0:
        cp = -1 if p > 0 else 1
        B[cs] = cp
        CNT[cp + 6] += 1
    if cap:
        CNT[cap + 6] += 1
    if abs(p) == 6:
        if t - f == 2:
            B[t + 1] = B[t - 1]
            B[t - 1] = 0
        elif f - t == 2:
            B[t - 2] = B[t + 1]
            B[t + 1] = 0
    KS[0], KS[1] = k0, k1
    W = not W


def order(ms, pl, ttm=0):
    k0, k1 = KIL[pl]

    def sc(m):
        if m == ttm:
            return 1 << 20
        t = (m >> 7) & 127
        cap = B[t]
        s = 0
        if cap:
            s = 100000 + VAL[abs(cap)] * 10 - abs(B[m & 127])
        if m >> 14:
            s += 900000
        elif m == k0:
            s = 50000
        elif m == k1:
            s = 40000
        return s

    ms.sort(key=sc, reverse=True)


def qs(a, b, pl):
    global N
    N += 1
    if N >= LIM:
        raise Abort
    if pl >= 100:
        return ev()
    if atk(KS[0 if W else 1], not W):
        ms = gen()
        order(ms, pl)
        best = -MATE
        legal = 0
        for m in ms:
            u = make(m)
            if atk(KS[0 if not W else 1], W):
                unmake(u)
                continue
            legal += 1
            if K in HIST or K in PATH:
                sc = 0
            else:
                PATH.add(K)
                sc = -qs(-b, -a, pl + 1)
                PATH.discard(K)
            unmake(u)
            if sc > best:
                best = sc
            if sc >= b:
                return sc
            if sc > a:
                a = sc
        return -MATE + pl if legal == 0 else best
    stand = ev()
    if stand >= b:
        return stand
    if stand > a:
        a = stand
    ms = gen(caps=True)
    order(ms, pl)
    for m in ms:
        u = make(m)
        if atk(KS[0 if not W else 1], W):
            unmake(u)
            continue
        if K in HIST or K in PATH:
            sc = 0
        else:
            PATH.add(K)
            sc = -qs(-b, -a, pl + 1)
            PATH.discard(K)
        unmake(u)
        if sc >= b:
            return sc
        if sc > a:
            a = sc
    return a


def search(d, a, b, pl):
    global N
    if pl and H >= 100:
        return 0
    if d <= 0:
        return qs(a, b, pl)
    N += 1
    if N >= LIM:
        raise Abort
    e = TT.get(K)
    if e and e[0] >= d:
        s = e[2]
        if s > MATE - 1000:
            s -= pl
        elif s < -MATE + 1000:
            s += pl
        if e[1] == 1 or (e[1] == 2 and s >= b) or (e[1] == 3 and s <= a):
            return s
    ttm = e[3] if e else 0
    ms = gen()
    order(ms, pl, ttm)
    best = -MATE - 1
    bm = 0
    a0 = a
    for m in ms:
        u = make(m)
        if atk(KS[0 if not W else 1], W):
            unmake(u)
            continue
        if K in HIST or K in PATH:
            sc = 0
        else:
            PATH.add(K)
            sc = -search(d - 1, -b, -a, pl + 1)
            PATH.discard(K)
        unmake(u)
        if sc > best:
            best = sc
            bm = m
        if sc > a:
            a = sc
        if a >= b:
            if not B[(m >> 7) & 127] and not (m >> 14):
                if KIL[pl][0] != m:
                    KIL[pl][1] = KIL[pl][0]
                    KIL[pl][0] = m
            break
    if best == -MATE - 1:
        return -MATE + pl if atk(KS[0 if W else 1], not W) else 0
    s = best
    if s > MATE - 1000:
        s += pl
    elif s < -MATE + 1000:
        s -= pl
    TT[K] = (d, 1 if best > a0 and best < b else 2 if best >= b else 3, s, bm)
    return best


def uci(m):
    f = m & 127
    t = (m >> 7) & 127
    s = "abcdefgh"[f & 7] + str((f >> 4) + 1) + "abcdefgh"[t & 7] + str((t >> 4) + 1)
    if m >> 14:
        s += "nbrq"[(m >> 14) - 2]
    return s


def parse_uci(s):
    f = "abcdefgh".index(s[0]) + ("12345678".index(s[1]) << 4)
    t = "abcdefgh".index(s[2]) + ("12345678".index(s[3]) << 4)
    pr = "nbrq".index(s[4]) + 2 if len(s) == 5 else 0
    return f | (t << 7) | (pr << 14)


SQ = {c: i for i, c in enumerate("abcdefgh")}


def setfen(fen):
    global B, W, C, E, H, S, K, PH
    parts = fen.split()
    B = [0] * 128
    S = 0
    PH = 0
    for i in range(13):
        CNT[i] = 0
    pm = {"p": 1, "n": 2, "b": 3, "r": 4, "q": 5, "k": 6}
    for r, row in enumerate(parts[0].split("/")):
        rank = 7 - r
        f = 0
        for ch in row:
            if ch.isdigit():
                f += int(ch)
            else:
                sq = rank * 16 + f
                p = pm[ch.lower()] * (1 if ch.isupper() else -1)
                B[sq] = p
                CNT[p + 6] += 1
                if abs(p) == 6:
                    KS[0 if p > 0 else 1] = sq
                else:
                    S += PV[p + 6][sq]
                    if abs(p) != 1:
                        PH += VAL[abs(p)]
                f += 1
    W = parts[1] == "w"
    C = 0
    if parts[2] != "-":
        for ch in parts[2]:
            C |= {"K": 1, "Q": 2, "k": 4, "q": 8}[ch]
    E = -1 if parts[3] == "-" else SQ[parts[3][0]] + ("12345678".index(parts[3][1]) << 4)
    H = int(parts[4])
    K = 0
    for sq in range(128):
        if B[sq]:
            K ^= Z[B[sq] + 6][sq]
    if not W:
        K ^= ZW
    K ^= ZC[C]
    if E >= 0:
        K ^= ZE[E & 7]


def setup(moves):
    # Replay the game from the start position; record every position key.
    global HIST, PATH
    setfen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    HIST = {K}
    PATH = set()
    for u in moves:
        want = parse_uci(u)
        for m in gen():
            if (m & 127) == (want & 127) and ((m >> 7) & 127) == ((want >> 7) & 127) \
                    and (m >> 14) == (want >> 14):
                make(m)
                HIST.add(K)
                break
        else:
            # Should not happen; fall back to applying the raw move.
            make(want)
            HIST.add(K)


def choose():
    global N, LIM
    ms = []
    for m in gen():
        u = make(m)
        if not atk(KS[0 if not W else 1], W):
            ms.append(m)
        unmake(u)
    if len(ms) == 1:
        return ms[0]
    if len(TT) > 300000:
        TT.clear()
    N = 0
    LIM = NODES
    best = ms[0]
    scores = {}
    try:
        for d in range(1, 13):
            ms.sort(key=lambda m: scores.get(m, 0), reverse=True)
            a = -MATE - 1
            b = MATE + 1
            cur = best
            for m in ms:
                u = make(m)
                if K in HIST or K in PATH:
                    sc = 0
                else:
                    PATH.add(K)
                    sc = -search(d - 1, -b, -a, 1)
                    PATH.discard(K)
                unmake(u)
                scores[m] = sc
                if sc > a:
                    a = sc
                    cur = m
            best = cur
    except Abort:
        pass
    return best


def post(path, body):
    req = urllib.request.Request(
        U + path, data=json.dumps(body).encode(),
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req) as res:
        return json.load(res)


while True:
    g = post("/game", {})
    if g["status"] == "done":
        break
    while g["status"] == "your_move":
        setup(g["moves"])
        mv = uci(choose())
        try:
            g = post("/move", {"game": g["game"], "move": mv})
        except Exception:
            g = post("/move", {"game": g["game"], "move": g["legal_moves"][0]})
    print(f"game {g['game']}: {g['outcome']} by {g['reason']}", file=sys.stderr)
print(f"done: {g.get('wins')} won, {g.get('draws')} drawn, {g.get('losses')} lost",
      file=sys.stderr)
