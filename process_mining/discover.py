"""Process discovery: the paths cases take, as a model.

Three views of an event log, from the plainest to the most structured:

    variants          each distinct sequence of events, with how many traces took it
    directly-follows  how often one kind of event comes right after another
    process tree      a block-structured model found by the Inductive Miner

The Inductive Miner (Leemans, Fahland and van der Aalst, 2013; the
infrequent-behaviour variant, 2014) is used because of what it guarantees: the
model it returns is always sound, and with the noise threshold at zero it can
replay every trace it was given. It works by finding a cut in the
directly-follows graph (a choice, a sequence, a parallel block, or a loop),
splitting the log along the cut, and recursing on each part.

A tree is nested tuples:

    ("act", "plea")           one event
    ("tau",)                  nothing: a step that may be skipped
    ("seq", [a, b, ...])      a, then b, then ...
    ("xor", [a, b, ...])      exactly one of
    ("par", [a, b, ...])      all of, in any order
    ("loop", [body, redo])    body, then any number of (redo, body)

This is an implementation of the published algorithm written for this
repository, with no process-mining dependency. Of the algorithm's
fall-throughs it implements two: an activity that occurs once in every trace
is split off in parallel, and anything else becomes a flower model (any
activity, any number of times), which is what the algorithm does when it finds
no structure.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import product
from typing import Any, Iterable

Tree = tuple[Any, ...]
TAU: Tree = ("tau",)
Log = Counter  # Counter[tuple[str, ...]]


def variants(traces: Iterable[tuple[str, ...]]) -> Log:
    return Counter(tuple(trace) for trace in traces)


def directly_follows(log: Log) -> dict[str, Any]:
    edges: Counter = Counter()
    starts: Counter = Counter()
    ends: Counter = Counter()
    activities: Counter = Counter()
    for trace, count in log.items():
        if not trace:
            continue
        starts[trace[0]] += count
        ends[trace[-1]] += count
        for activity in trace:
            activities[activity] += count
        for left, right in zip(trace, trace[1:]):
            edges[(left, right)] += count
    return {"edges": edges, "starts": starts, "ends": ends, "activities": activities}


# ---------------------------------------------------------------------------
# Inductive Miner
# ---------------------------------------------------------------------------

def _filtered(dfg: dict[str, Any], noise: float) -> tuple[set[tuple[str, str]], set[str], set[str]]:
    """Edges, start and end activities, with infrequent ones dropped: an edge
    stays when it is at least `noise` times as frequent as the most frequent
    thing that follows the same activity, the end of the trace included."""
    # Ending the trace is one of the things an activity can be followed by.
    strongest: dict[str, int] = defaultdict(int, dfg["ends"])
    for (left, _), count in dfg["edges"].items():
        strongest[left] = max(strongest[left], count)
    edges = {edge for edge, count in dfg["edges"].items() if count >= noise * strongest[edge[0]]}
    top_start = max(dfg["starts"].values(), default=0)
    top_end = max(dfg["ends"].values(), default=0)
    starts = {a for a, count in dfg["starts"].items() if count >= noise * top_start}
    ends = {a for a, count in dfg["ends"].items() if count >= noise * top_end}
    return edges, starts, ends


def _components(nodes: set[str], linked) -> list[set[str]]:
    remaining, out = set(nodes), []
    while remaining:
        seed = remaining.pop()
        group, frontier = {seed}, [seed]
        while frontier:
            node = frontier.pop()
            for other in list(remaining):
                if linked(node, other):
                    remaining.discard(other)
                    group.add(other)
                    frontier.append(other)
        out.append(group)
    return out


def _reach(nodes: set[str], edges: set[tuple[str, str]]) -> dict[str, set[str]]:
    reach = {node: {b for a, b in edges if a == node} for node in nodes}
    changed = True
    while changed:
        changed = False
        for node in nodes:
            extra = set().union(*(reach[n] for n in reach[node])) - reach[node] if reach[node] else set()
            if extra:
                reach[node] |= extra
                changed = True
    return reach


def _xor_cut(nodes: set[str], edges: set[tuple[str, str]]) -> list[set[str]] | None:
    groups = _components(nodes, lambda a, b: (a, b) in edges or (b, a) in edges)
    return groups if len(groups) > 1 else None


def _sequence_cut(nodes: set[str], edges: set[tuple[str, str]]) -> list[set[str]] | None:
    reach = _reach(nodes, edges)
    # Two activities belong together when each can reach the other, or neither can.
    groups = _components(nodes, lambda a, b: (b in reach[a]) == (a in reach[b]))
    if len(groups) < 2:
        return None
    return sorted(groups, key=lambda group: -sum(1 for other in nodes - group if other in reach[next(iter(group))]))


def _parallel_cut(nodes: set[str], edges: set[tuple[str, str]], starts: set[str], ends: set[str]) -> list[set[str]] | None:
    groups = _components(nodes, lambda a, b: not ((a, b) in edges and (b, a) in edges))
    if len(groups) < 2:
        return None
    # Every branch of a parallel block can start the block and can end it.
    whole = [g for g in groups if g & starts and g & ends]
    if not whole:
        return None
    for group in groups:
        if not (group & starts and group & ends):
            whole[0] |= group
    return whole if len(whole) > 1 else None


def _loop_cut(nodes: set[str], edges: set[tuple[str, str]], starts: set[str], ends: set[str]) -> list[set[str]] | None:
    body = set(starts | ends)
    rest = nodes - body
    if not rest:
        return None
    redo = _components(rest, lambda a, b: (a, b) in edges or (b, a) in edges)
    kept = []
    for group in redo:
        entering = {(a, b) for a, b in edges if b in group and a not in group}
        leaving = {(a, b) for a, b in edges if a in group and b not in group}
        # A redo part is entered only from where the body ends and left only to where it starts,
        # and it is reachable from every end and returns to every start.
        ok = all(a in ends for a, _ in entering) and all(b in starts for _, b in leaving)
        if ok:
            firsts, lasts = {b for _, b in entering}, {a for a, _ in leaving}
            ok = all((end, first) in edges for first in firsts for end in ends) and all((last, start) in edges for last in lasts for start in starts)
        if ok and entering and leaving:
            kept.append(group)
        else:
            body |= group
    return [body, *kept] if kept else None


def _project(log: Log, group: set[str]) -> Log:
    out: Log = Counter()
    for trace, count in log.items():
        out[tuple(a for a in trace if a in group)] += count
    return out


def _split_loop(log: Log, parts: list[set[str]]) -> list[Log]:
    of = {activity: index for index, part in enumerate(parts) for activity in part}
    out: list[Log] = [Counter() for _ in parts]
    for trace, count in log.items():
        current, segment = 0, []
        for activity in trace:
            index = of[activity]
            if index != current:
                out[current][tuple(segment)] += count
                current, segment = index, []
            segment.append(activity)
        out[current][tuple(segment)] += count
        if current != 0:
            out[0][()] += count  # a trace that stops in a redo part still closes the body
    return out


def mine(log: Log, noise: float = 0.0, _depth: int = 0) -> Tree:
    """A process tree for `log`. `noise` in [0, 1]: 0 keeps every behaviour seen."""
    total = sum(log.values())
    empty = log.get((), 0)
    activities = {a for trace in log for a in trace}
    if not activities:
        return TAU
    if empty:
        rest = Counter({trace: count for trace, count in log.items() if trace})
        inner = mine(rest, noise, _depth + 1)
        # Skipping is part of the model unless it is rarer than the noise threshold.
        return inner if empty < noise * total else simplify(("xor", [TAU, inner]))
    if len(activities) == 1:
        activity = next(iter(activities))
        repeats = sum(count for trace, count in log.items() if len(trace) > 1)
        return ("act", activity) if repeats <= noise * total else ("loop", [("act", activity), TAU])
    if _depth > 40:
        return _flower(activities)

    dfg = directly_follows(log)
    edges, starts, ends = _filtered(dfg, noise)
    groups = _xor_cut(activities, edges)
    if groups:
        sublogs: list[Log] = [Counter() for _ in groups]
        for trace, count in log.items():
            # A trace goes to the branch most of its events belong to.
            best = max(range(len(groups)), key=lambda i: sum(1 for a in trace if a in groups[i]))
            sublogs[best][tuple(a for a in trace if a in groups[best])] += count
        return simplify(("xor", [mine(sub, noise, _depth + 1) for sub in _ordered(sublogs)]))
    groups = _sequence_cut(activities, edges)
    if groups:
        return simplify(("seq", [mine(_project(log, group), noise, _depth + 1) for group in groups]))
    groups = _parallel_cut(activities, edges, starts, ends)
    if groups:
        return simplify(("par", [mine(_project(log, group), noise, _depth + 1) for group in _sorted_groups(groups)]))
    groups = _loop_cut(activities, edges, starts, ends)
    if groups:
        parts = _split_loop(log, groups)
        body = mine(parts[0], noise, _depth + 1)
        redo = [mine(part, noise, _depth + 1) for part in parts[1:]]
        return simplify(("loop", [body, redo[0] if len(redo) == 1 else ("xor", redo)]))

    # Fall-through: an activity that happens exactly once in every trace runs beside the rest.
    for activity in sorted(activities):
        if all(trace.count(activity) == 1 for trace in log):
            rest = _project(log, activities - {activity})
            return simplify(("par", [("act", activity), mine(rest, noise, _depth + 1)]))
    return _flower(activities)


def _flower(activities: set[str]) -> Tree:
    return ("loop", [TAU, ("xor", [("act", a) for a in sorted(activities)])])


def _ordered(sublogs: list[Log]) -> list[Log]:
    return sorted(sublogs, key=lambda sub: (-sum(sub.values()), sorted(sub)[0] if sub else ()))


def _sorted_groups(groups: list[set[str]]) -> list[set[str]]:
    return sorted(groups, key=lambda group: sorted(group))


def simplify(tree: Tree) -> Tree:
    """Flatten nested operators of one kind and drop steps that do nothing."""
    kind = tree[0]
    if kind in ("act", "tau"):
        return tree
    children = [simplify(child) for child in tree[1]]
    if kind == "loop":
        return ("loop", children)
    flat: list[Tree] = []
    for child in children:
        flat.extend(child[1] if child[0] == kind else [child])
    if kind in ("seq", "par"):
        flat = [child for child in flat if child != TAU] or [TAU]
    if kind == "xor":
        unique: list[Tree] = []
        for child in flat:
            if child not in unique:
                unique.append(child)
        flat = unique
    return flat[0] if len(flat) == 1 else (kind, flat)


# ---------------------------------------------------------------------------
# What a tree allows
# ---------------------------------------------------------------------------

class TooLarge(Exception):
    """The model allows more traces than can be listed."""


def _shuffle(left: tuple[str, ...], right: tuple[str, ...]) -> set[tuple[str, ...]]:
    if not left:
        return {right}
    if not right:
        return {left}
    return {(left[0], *rest) for rest in _shuffle(left[1:], right)} | {(right[0], *rest) for rest in _shuffle(left, right[1:])}


def language(tree: Tree, max_loop: int = 3, cap: int = 50000) -> set[tuple[str, ...]]:
    """Every trace the tree allows, with each loop taken at most `max_loop` extra times."""
    kind = tree[0]
    if kind == "act":
        return {(tree[1],)}
    if kind == "tau":
        return {()}
    parts = [language(child, max_loop, cap) for child in tree[1]]
    if kind == "xor":
        out = set().union(*parts)
    elif kind == "seq":
        out = {()}
        for part in parts:
            out = {left + right for left, right in product(out, part)}
            if len(out) > cap:
                raise TooLarge
    elif kind == "par":
        out = {()}
        for part in parts:
            out = {mixed for left, right in product(out, part) for mixed in _shuffle(left, right)}
            if len(out) > cap:
                raise TooLarge
    else:  # loop
        body, redo = parts
        out = set(body)
        latest = set(body)
        for _ in range(max_loop):
            latest = {done + again + more for done, again, more in product(latest, redo, body)}
            out |= latest
            if len(out) > cap:
                raise TooLarge
    if len(out) > cap:
        raise TooLarge
    return out


def show(tree: Tree, indent: int = 0) -> str:
    """The tree as indented text."""
    pad = "  " * indent
    kind = tree[0]
    if kind == "act":
        return f"{pad}{tree[1]}"
    if kind == "tau":
        return f"{pad}(skip)"
    names = {"seq": "sequence", "xor": "one of", "par": "in any order", "loop": "loop: first line, then any number of (second line, first line)"}
    return "\n".join([f"{pad}{names[kind]}", *(show(child, indent + 1) for child in tree[1])])


def as_dict(tree: Tree) -> dict[str, Any]:
    kind = tree[0]
    if kind == "act":
        return {"activity": tree[1]}
    if kind == "tau":
        return {"skip": True}
    return {"operator": kind, "children": [as_dict(child) for child in tree[1]]}
