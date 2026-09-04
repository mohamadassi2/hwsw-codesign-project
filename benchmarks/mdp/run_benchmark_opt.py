import collections
from collections import defaultdict
from fractions import Fraction

import pyperf


def topoSort(roots, getParents):
    """Return a topological sorting of nodes in a graph.

    roots - list of root nodes to search from
    getParents - function which returns the parents of a given node
    """

    results = []
    visited = set()

    # Use iterative version to avoid stack limits for large datasets
    stack = [(node, 0) for node in roots]
    while stack:
        current, state = stack.pop()
        if state == 0:
            # before recursing
            if current not in visited:
                visited.add(current)
                stack.append((current, 1))
                stack.extend((parent, 0) for parent in getParents(current))
        else:
            # after recursing
            assert(current in visited)
            results.append(current)
    return results


def getDamages(L, A, D, B, stab, te):
    x = (2 * L) // 5
    x = ((x + 2) * A * B) // (D * 50) + 2
    if stab:
        x += x // 2
    x = int(x * te)
    return [(x * z) // 255 for z in range(217, 256)]


_CRITDIST_CACHE = {}


def getCritDist(L, p, A1, A2, D1, D2, B, stab, te):
    # The same (level, crit-probability, stats, power) tuple is requested
    # thousands of times per evaluation; the Fraction arithmetic below is the
    # expensive part, so memoize the finished distribution.  Arithmetic is
    # unchanged (still exact Fractions), only repeated.
    key = (L, p, A1, A2, D1, D2, B, stab, te)
    hit = _CRITDIST_CACHE.get(key)
    if hit is not None:
        return hit
    p = min(p, Fraction(1))
    norm = getDamages(L, A1, D1, B, stab, te)
    crit = getDamages(L * 2, A2, D2, B, stab, te)

    dist = defaultdict(Fraction)
    for mult, vals in zip([1 - p, p], [norm, crit]):
        mult /= len(vals)
        for x in vals:
            dist[x] += mult
    # store a plain dict: the callers only iterate .items(), and a defaultdict
    # would silently grow if any future caller read a missing key
    dist = dict(dist)
    _CRITDIST_CACHE[key] = dist
    return dist


def plus12(x):
    return x + x // 8


stats_t = collections.namedtuple('stats_t', ['atk', 'df', 'speed', 'spec'])
NOMODS = stats_t(0, 0, 0, 0)


fixeddata_t = collections.namedtuple(
    'fixeddata_t', ['maxhp', 'stats', 'lvl', 'badges', 'basespeed'])
halfstate_t = collections.namedtuple(
    'halfstate_t', ['fixed', 'hp', 'status', 'statmods', 'stats'])


def applyHPChange(hstate, change):
    hp = min(hstate.fixed.maxhp, max(0, hstate.hp + change))
    return hstate._replace(hp=hp)


def applyBadgeBoosts(badges, stats):
    return stats_t(*[(plus12(x) if b else x) for x, b in zip(stats, badges)])


attack_stats_t = collections.namedtuple(
    'attack_stats_t', ['power', 'isspec', 'stab', 'te', 'crit'])
attack_data = {
    'Ember': attack_stats_t(40, True, True, 0.5, False),
    'Dig': attack_stats_t(100, False, False, 1, False),
    'Slash': attack_stats_t(70, False, False, 1, True),
    'Water Gun': attack_stats_t(40, True, True, 2, False),
    'Bubblebeam': attack_stats_t(65, True, True, 2, False),
}


def _applyActionSide1(state, act):
    me, them, extra = state

    if act == 'Super Potion':
        me = applyHPChange(me, 50)
        return {(me, them, extra): Fraction(1)}

    mdata = attack_data[act]
    aind = 3 if mdata.isspec else 0
    dind = 3 if mdata.isspec else 1
    pdiv = 64 if mdata.crit else 512
    dmg_dist = getCritDist(me.fixed.lvl, Fraction(me.fixed.basespeed, pdiv),
                           me.stats[aind], me.fixed.stats[aind], them.stats[
                               dind], them.fixed.stats[dind],
                           mdata.power, mdata.stab, mdata.te)

    dist = defaultdict(Fraction)
    for dmg, p in dmg_dist.items():
        them2 = applyHPChange(them, -dmg)
        dist[me, them2, extra] += p
    return dist


def _applyAction(state, side, act):
    if side == 0:
        return _applyActionSide1(state, act)
    else:
        me, them, extra = state
        dist = _applyActionSide1((them, me, extra), act)
        return {(k[1], k[0], k[2]): v for k, v in dist.items()}


class Battle(object):

    def __init__(self):
        self.successors = {}
        self.min = defaultdict(float)
        self.max = defaultdict(lambda: 1.0)
        self.frozen = set()

        self.win = 4, True
        self.loss = 4, False
        self.max[self.loss] = 0.0
        self.min[self.win] = 1.0
        self.frozen.update([self.win, self.loss])

    def _getSuccessorsA(self, statep):
        st, state = statep
        for action in ['Dig', 'Super Potion']:
            yield (1, state, action)

    def _applyActionPair(self, state, side1, act1, side2, act2, dist, pmult):
        for newstate, p in _applyAction(state, side1, act1).items():
            if newstate[0].hp == 0:
                newstatep = self.loss
            elif newstate[1].hp == 0:
                newstatep = self.win
            else:
                newstatep = 2, newstate, side2, act2
            dist[newstatep] += p * pmult

    def _getSuccessorsB(self, statep):
        st, state, action = statep
        dist = defaultdict(Fraction)
        for eact, p in [('Water Gun', Fraction(64, 130)),
                        ('Bubblebeam', Fraction(66, 130))]:
            priority1 = state[0].stats.speed + \
                10000 * (action == 'Super Potion')
            priority2 = state[1].stats.speed + 10000 * (action == 'X Defend')

            if priority1 > priority2:
                self._applyActionPair(state, 0, action, 1, eact, dist, p)
            elif priority1 < priority2:
                self._applyActionPair(state, 1, eact, 0, action, dist, p)
            else:
                self._applyActionPair(state, 0, action, 1, eact, dist, p / 2)
                self._applyActionPair(state, 1, eact, 0, action, dist, p / 2)

        return {k: float(p) for k, p in dist.items() if p > 0}

    def _getSuccessorsC(self, statep):
        st, state, side, action = statep
        dist = defaultdict(Fraction)
        for newstate, p in _applyAction(state, side, action).items():
            if newstate[0].hp == 0:
                newstatep = self.loss
            elif newstate[1].hp == 0:
                newstatep = self.win
            else:
                newstatep = 0, newstate
            dist[newstatep] += p
        return {k: float(p) for k, p in dist.items() if p > 0}

    def getSuccessors(self, statep):
        try:
            return self.successors[statep]
        except KeyError:
            st = statep[0]
        if st == 0:
            result = list(self._getSuccessorsA(statep))
        else:
            if st == 1:
                dist = self._getSuccessorsB(statep)
            elif st == 2:
                dist = self._getSuccessorsC(statep)
            result = sorted(dist.items(), key=lambda t: (-t[1], t[0]))
        self.successors[statep] = result
        return result

    def getSuccessorsList(self, statep):
        if statep[0] == 4:
            return []
        temp = self.getSuccessors(statep)
        if statep[0] != 0:
            temp = list(zip(*temp))[0] if temp else []
        return temp

    def evaluate(self, tolerance=0.15):
        badges = 1, 0, 0, 0

        starfixed = fixeddata_t(59, stats_t(40, 44, 56, 50), 11, NOMODS, 115)
        starhalf = halfstate_t(starfixed, 59, 0, NOMODS,
                               stats_t(40, 44, 56, 50))
        charfixed = fixeddata_t(63, stats_t(39, 34, 46, 38), 26, badges, 65)
        charhalf = halfstate_t(charfixed, 63, 0, NOMODS, applyBadgeBoosts(
            badges, stats_t(39, 34, 46, 38)))
        initial_state = charhalf, starhalf, 0
        initial_statep = 0, initial_state

        dmin, dmax, frozen = self.min, self.max, self.frozen
        stateps = topoSort([initial_statep], self.getSuccessorsList)

        # --- Build an integer-indexed view of the state graph once. ---------
        # The original keys dmin/dmax/frozen by nested namedtuple states, so
        # every value-iteration step re-hashes deep tuples several times.
        # Here each state gets a small int; the sweep below then only touches
        # flat lists.  Sweep order, in-place (Gauss-Seidel) update, freezing
        # rule and floating-point operation order are all kept identical, so
        # the result is bit-for-bit the same as the original.
        index = {}
        for sp in stateps:
            index[sp] = len(index)
        succ_i = []      # successor indices per state
        succ_p = []      # successor probabilities per state (None for choice nodes)
        choice = []
        for sp in stateps:
            if sp[0] == 4:
                succ_i.append(()); succ_p.append(None); choice.append(False)
                continue
            succ = self.getSuccessors(sp)
            if sp[0] == 0:
                ids = []
                for sp2 in succ:
                    if sp2 not in index:
                        index[sp2] = len(index)
                    ids.append(index[sp2])
                succ_i.append(tuple(ids)); succ_p.append(None); choice.append(True)
            else:
                ids, ps = [], []
                for sp2, p in succ:
                    if sp2 not in index:
                        index[sp2] = len(index)
                    ids.append(index[sp2]); ps.append(p)
                succ_i.append(tuple(ids)); succ_p.append(tuple(ps)); choice.append(False)
        n = len(index)
        vmin = [0.0] * n              # defaultdict(float) default
        vmax = [1.0] * n              # defaultdict(lambda: 1.0) default
        fz = [False] * n
        for sp, v in dmin.items():
            if sp in index:
                vmin[index[sp]] = v
        for sp, v in dmax.items():
            if sp in index:
                vmax[index[sp]] = v
        for sp in frozen:
            if sp in index:
                fz[index[sp]] = True
        # succ_i/succ_p/choice are only filled for stateps, so the sweep walks
        # `order` (= the stateps indices) and never range(n); any state that
        # entered `index` merely as a successor has a value but no row.
        order = [index[sp] for sp in stateps]
        i0 = index[initial_statep]

        itercount = 0
        while vmax[i0] - vmin[i0] > tolerance:
            itercount += 1

            for i in order:
                if fz[i]:
                    continue

                S = succ_i[i]
                if choice[i]:
                    # choice node
                    a = max([vmin[j] for j in S])
                    b = max([vmax[j] for j in S])
                else:
                    P = succ_p[i]
                    a = 0
                    b = 0
                    for j, p in zip(S, P):
                        a += vmin[j] * p
                        b += vmax[j] * p
                vmin[i] = a
                vmax[i] = b

                if a >= b:
                    vmax[i] = vmin[i] = (a + b) / 2
                    fz[i] = True

        # Write the converged values back so self.min/self.max/self.frozen
        # keep the same meaning they had in the original.
        for sp, i in index.items():
            dmin[sp] = vmin[i]
            dmax[sp] = vmax[i]
            if fz[i]:
                frozen.add(sp)
        return (vmax[i0] + vmin[i0]) / 2


def bench_mdp(loops):
    expected = 0.89873589887
    max_diff = 1e-6
    range_it = range(loops)

    t0 = pyperf.perf_counter()
    for _ in range_it:
        result = Battle().evaluate(0.192)
    dt = pyperf.perf_counter() - t0

    if abs(result - expected) > max_diff:
        raise Exception("invalid result: got %s, expected %s "
                        "(diff: %s, max diff: %s)"
                        % (result, expected, result - expected, max_diff))
    return dt


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.metadata['description'] = "MDP benchmark"
    runner.bench_time_func('mdp', bench_mdp)
