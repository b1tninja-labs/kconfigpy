"""Work out the smallest set of options that lets a wanted symbol be enabled."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from kconfigpy.kconfig import And, Const, Definition, Expr, KconfigDb, Not, Or, Sym, Unknown, show

# Never chosen to satisfy an "either/or" dependency: it exists to widen build coverage.
BANNED = frozenset({"COMPILE_TEST"})


@dataclass
class Solution:
    enabled: dict[str, str] = field(default_factory=dict)  # symbol -> why
    # symbol -> why it is on, though its own dependencies are unmet: a select forces it, and it is not solved
    forced: dict[str, str] = field(default_factory=dict)
    # symbol -> the conditional select that was not followed, and why: "select X if <expr>" is followed
    # only when the requested options make <expr> hold
    conditional: dict[str, str] = field(default_factory=dict)
    excluded: dict[str, str] = field(default_factory=dict)  # symbol on the caller's exclude list -> who wanted it
    forbidden: dict[str, str] = field(default_factory=dict)  # symbol -> why it must stay off
    assumed: dict[str, str] = field(default_factory=dict)  # promptless symbol -> who needs it
    # promptless symbol -> its first visible default, when the request decides which one that is
    default_on: dict[str, str] = field(default_factory=dict)
    # symbol -> the option that implies it, when its own dependencies hold: likely on, though not requested
    implied: dict[str, str] = field(default_factory=dict)
    implied_off: dict[str, str] = field(default_factory=dict)  # symbol -> why an imply is not known to take effect
    default_off: dict[str, str] = field(default_factory=dict)
    unknown: dict[str, str] = field(default_factory=dict)  # unevaluated term -> who needs it
    conflicts: list[str] = field(default_factory=list)
    undefined: dict[str, str] = field(default_factory=dict)


class Solver:
    def __init__(self, db: KconfigDb) -> None:
        self.db = db
        self._solution = Solution()
        self._pending: list[tuple[str, str, Expr]] = []  # (owner, target, condition) not yet followed
        self._implies: list[tuple[str, str, Expr | None]] = []  # (owner, target, condition) of every imply seen
        self._excluded: dict[str, str] = {}  # symbol -> why the caller excludes it

    def exclude(self, name: str, why: str) -> None:
        """Never enable this symbol, and so never follow what it depends on or selects."""
        self._excluded[name] = why

    @property
    def solution(self) -> Solution:
        """The solution so far, with every conditional select judged against all that was requested."""
        self.settle()
        return self._solution

    def cost(self, expr: Expr) -> float:
        """How many new options this term would switch on; infinite if it cannot hold."""
        if isinstance(expr, Sym):
            if expr.name in BANNED or expr.name in self._solution.forbidden or expr.name in self._excluded:
                return math.inf
            on = expr.name in self._solution.enabled or expr.name in self._solution.forced
            return 0 if on or not self.db.is_settable(expr.name) else 1
        if isinstance(expr, Const):
            return 0 if expr.value == "y" else math.inf
        if isinstance(expr, Not):
            return math.inf if isinstance(expr.term, Sym) and expr.term.name in self._solution.enabled else 0
        if isinstance(expr, And):
            return self.cost(expr.left) + self.cost(expr.right)
        if isinstance(expr, Or):
            return min(self.cost(expr.left), self.cost(expr.right))
        return 0

    def want(self, name: str, why: str) -> None:
        """Enable a symbol, its dependencies, and whatever it selects."""
        definition = self.enable(name, why)
        if definition is not None:
            self.follow_selects(definition, name)

    def enable(self, name: str, why: str) -> Definition | None:
        """Enable a symbol and walk its dependencies; return its definition if it switched on."""
        if name in self._solution.enabled or name in self._solution.forced:
            return None
        if name in self._excluded:
            self._solution.excluded.setdefault(name, f"{self._excluded[name]}; wanted: {why}")
            return None
        if name in self._solution.forbidden:
            self._solution.conflicts.append(
                f"{name} is wanted ({why}) but must stay off ({self._solution.forbidden[name]})"
            )
            return None
        definition = self.db.preferred(name)
        if definition is None:
            self._solution.undefined[name] = why
            return None
        if not self.db.is_settable(name):
            # No prompt means it cannot be requested, but it can still default on once its
            # parents are enabled (USB_EHCI_PCI needs USB_EHCI_HCD), so the walk continues.
            if name in self._solution.assumed:
                return None
            self._solution.assumed[name] = why
        else:
            rival = self.choice_rival(definition, name)
            if rival is not None:
                held = self._solution.enabled.get(rival) or self._solution.forced[rival]
                choice = definition.choice
                where = f"{choice.file}:{choice.line}" if choice is not None else "?"
                conflict = (
                    f"{name} and {rival} are both members of the choice at {where}, which allows exactly one: "
                    f"{name} is wanted ({why}); {rival} is on ({held})"
                )
                if conflict not in self._solution.conflicts:
                    self._solution.conflicts.append(conflict)
                return None
            self._solution.enabled[name] = why
        for dependency in list(definition.all_deps()):
            self.satisfy(dependency, name)
        return definition

    def choice_rival(self, definition: Definition, name: str) -> str | None:
        """Another member of the same choice that is already on, if there is one."""
        if definition.choice is None:
            return None
        solution = self._solution
        return next(
            (m for m in definition.choice.members if m != name and (m in solution.enabled or m in solution.forced)),
            None,
        )

    def follow_selects(self, definition: Definition, owner: str) -> None:
        for target in definition.selects:
            self.select(target, owner)
        for target, condition in definition.select_if:
            if (owner, target, condition) not in self._pending:
                self._pending.append((owner, target, condition))
        for implied, when in definition.implies:
            if (owner, implied, when) not in self._implies:
                self._implies.append((owner, implied, when))

    def holds(self, expr: Expr) -> bool | None:
        """Whether the request decides this condition: True, False, or None when it does not.

        A symbol the request never mentions is undecided, not off: a default or another fragment may turn it
        on. So ``!X`` holds only when the request itself requires X off.
        """
        if isinstance(expr, Sym):
            solution = self._solution
            if expr.name in solution.enabled or expr.name in solution.forced or expr.name in solution.assumed:
                return True
            return False if expr.name in solution.forbidden else None
        if isinstance(expr, Const):
            return expr.value != "n"
        if isinstance(expr, Not):
            inner = self.holds(expr.term)
            return None if inner is None else not inner
        if isinstance(expr, And | Or):
            left, right = self.holds(expr.left), self.holds(expr.right)
            decisive = isinstance(expr, Or)  # one true side decides an "or", one false side an "and"
            if left is decisive or right is decisive:
                return decisive
            return None if left is None or right is None else not decisive
        return None

    def settle(self) -> None:
        """Follow each pending conditional select whose condition now holds, until nothing changes.

        Conditions without a negation go first: enabling more options can only make them truer. One with a
        negation is judged last, against everything the others switched on.
        """
        for negated in (False, True):
            changed = True
            while changed:
                changed = False
                for item in list(self._pending):
                    owner, target, condition = item
                    if item in self._pending and _negates(condition) is negated and self.holds(condition):
                        self._pending.remove(item)
                        self.select(target, owner, f" if {show(condition)}")
                        changed = True
        solution = self._solution
        self.predict_defaults()
        self.judge_implies()
        solution.conditional.clear()
        for owner, target, condition in self._pending:
            if target in solution.enabled or target in solution.forced or target in solution.assumed:
                continue
            if self.holds(condition) is False:
                verdict = "the requested options rule out"
            elif _unevaluated(condition):
                verdict = "is not evaluated"
            else:
                verdict = "the requested options do not decide"
            reason = f"selected by {owner} only if {show(condition)}, which {verdict}"
            previous = solution.conditional.get(target)
            solution.conditional[target] = f"{previous}; {reason}" if previous else reason

    def judge_implies(self) -> None:
        """Report each implied option as likely on when the request decides that its own dependencies hold.

        ``imply`` is a weak select: it raises the target's default but never past the target's direct
        dependencies, and the user can still turn it off. So it is never put in the fragment.
        """
        solution = self._solution
        solution.implied.clear()
        solution.implied_off.clear()
        for owner, target, condition in self._implies:
            if target in solution.enabled or target in solution.forced:
                continue
            by = f"implied by {owner}" + (f" if {show(condition)}" if condition is not None else "")
            definition = self.db.preferred(target)
            applies = True if condition is None else self.holds(condition)
            if definition is None:
                problem = "it is not defined"
            elif target in self._excluded:
                problem = f"it is excluded ({self._excluded[target]})"
            elif applies is not True:
                problem = "the condition " + ("is ruled out" if applies is False else "is not decided by the request")
            else:
                deps = list(definition.all_deps())
                held = self.holds_all(deps)
                if held is True:
                    previous = solution.implied.get(target)
                    solution.implied[target] = f"{previous}; {by}" if previous else f"{by}, and its dependencies hold"
                    continue
                shown = ", ".join(show(d) for d in deps)
                problem = f"its dependencies ({shown}) " + ("do not hold" if held is False else "are not decided")
            previous = solution.implied_off.get(target)
            solution.implied_off[target] = f"{previous}; {by}, but {problem}" if previous else f"{by}, but {problem}"
        for target in solution.implied:
            solution.implied_off.pop(target, None)

    def predict_defaults(self) -> None:
        """Say whether each promptless symbol is on or off by default, where the request decides it.

        Only ``default`` and ``select`` give such a symbol a value, so its first visible default is its value
        unless a select raises it. A condition the request does not decide leaves the symbol unpredicted.
        """
        solution = self._solution
        solution.default_on.clear()
        solution.default_off.clear()
        for name in solution.assumed:
            verdict, why = self.default_of(name)
            if verdict is True:
                solution.default_on[name] = why
            elif verdict is False:
                solution.default_off[name] = why

    def default_of(self, name: str) -> tuple[bool | None, str]:
        """The value the defaults give a symbol: True, False, or None when the request does not decide it."""
        for definition in self.db.definitions.get(name, []):
            visible = self.holds_all(list(definition.all_deps()))
            if visible is False:
                continue
            for value, condition in definition.defaults:
                applies = visible if condition is None else self.holds_all([condition, *definition.all_deps()])
                text = f"default {show(value)}" + (f" if {show(condition)}" if condition is not None else "")
                if applies is False:
                    continue
                if applies is None:
                    return None, f"{text} is not decided by the requested options"
                return self.holds(value), f"first visible {text}"
        return False, "no default applies"

    def holds_all(self, exprs: list[Expr]) -> bool | None:
        result: bool | None = True
        for expr in exprs:
            held = self.holds(expr)
            if held is False:
                return False
            if held is None:
                result = None
        return result

    def select(self, target: str, owner: str, condition: str = "") -> None:
        """Turn on a selected symbol whatever its own dependencies say (Kconfig only warns).

        If its dependencies cannot be met, the symbol is forced rather than solved: it is kept out of
        the fragment and listed as forced, and verify has the final say.
        """
        why = f"selected by {owner}{condition}"
        before = Counter(self.problems())
        definition = self.enable(target, why)
        if definition is None:
            return
        new = sorted((Counter(self.problems()) - before).elements())
        if new:
            self._solution.enabled.pop(target, None)
            self._solution.assumed.pop(target, None)
            self._solution.forced[target] = f"{why}, but its dependencies are unmet: {'; '.join(new)}"
        self.follow_selects(definition, target)

    def problems(self) -> list[str]:
        """Every conflict, undefined symbol and unevaluated term recorded so far."""
        return [
            *self._solution.conflicts,
            *(f"{name} is not defined" for name in self._solution.undefined),
            *(f"{term} is not evaluated" for term in self._solution.unknown),
        ]

    def satisfy(self, expr: Expr, owner: str) -> None:
        if isinstance(expr, Sym):
            self.want(expr.name, f"dependency of {owner}")
        elif isinstance(expr, And):
            self.satisfy(expr.left, owner)
            self.satisfy(expr.right, owner)
        elif isinstance(expr, Or):
            self.satisfy(expr.left if self.cost(expr.left) <= self.cost(expr.right) else expr.right, owner)
        elif isinstance(expr, Not):
            self.forbid(expr.term, owner)
        elif isinstance(expr, Const) and expr.value != "y":
            self._solution.conflicts.append(f"{owner} depends on constant {expr.value}: it cannot be built in")
        elif isinstance(expr, Unknown):
            self._solution.unknown.setdefault(expr.text, owner)

    def forbid(self, expr: Expr, owner: str) -> None:
        if isinstance(expr, Sym):
            held = self._solution.enabled.get(expr.name) or self._solution.forced.get(expr.name)
            if held is not None:
                self._solution.conflicts.append(f"{owner} needs {expr.name} off, but {held}")
            else:
                self._solution.forbidden.setdefault(expr.name, f"conflicts with {owner}")
        elif isinstance(expr, Or):  # !(a || b) is !a && !b
            self.forbid(expr.left, owner)
            self.forbid(expr.right, owner)
        elif isinstance(expr, And):  # !(a && b): turning off either one is enough
            self.forbid(expr.left if isinstance(expr.left, Sym) else expr.right, owner)
        elif isinstance(expr, Not):
            self.satisfy(expr.term, owner)


def _unevaluated(expr: Expr) -> bool:
    if isinstance(expr, Unknown):
        return True
    if isinstance(expr, And | Or):
        return _unevaluated(expr.left) or _unevaluated(expr.right)
    return isinstance(expr, Not) and _unevaluated(expr.term)


def _negates(expr: Expr) -> bool:
    if isinstance(expr, Not):
        return True
    if isinstance(expr, And | Or):
        return _negates(expr.left) or _negates(expr.right)
    return False
