"""Work out the smallest set of options that lets a wanted symbol be enabled."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from kconfigpy.kconfig import And, Const, Definition, Expr, KconfigDb, Not, Or, Sym, Unknown

# Never chosen to satisfy an "either/or" dependency: it exists to widen build coverage.
BANNED = frozenset({"COMPILE_TEST"})


@dataclass
class Solution:
    enabled: dict[str, str] = field(default_factory=dict)  # symbol -> why
    # symbol -> why it is on, though its own dependencies are unmet: a select forces it, and it is not solved
    forced: dict[str, str] = field(default_factory=dict)
    forbidden: dict[str, str] = field(default_factory=dict)  # symbol -> why it must stay off
    assumed: dict[str, str] = field(default_factory=dict)  # promptless symbol -> who needs it
    unknown: dict[str, str] = field(default_factory=dict)  # unevaluated term -> who needs it
    conflicts: list[str] = field(default_factory=list)
    undefined: dict[str, str] = field(default_factory=dict)


class Solver:
    def __init__(self, db: KconfigDb) -> None:
        self.db = db
        self.solution = Solution()

    def cost(self, expr: Expr) -> float:
        """How many new options this term would switch on; infinite if it cannot hold."""
        if isinstance(expr, Sym):
            if expr.name in BANNED or expr.name in self.solution.forbidden:
                return math.inf
            on = expr.name in self.solution.enabled or expr.name in self.solution.forced
            return 0 if on or not self.db.is_settable(expr.name) else 1
        if isinstance(expr, Const):
            return 0 if expr.value == "y" else math.inf
        if isinstance(expr, Not):
            return math.inf if isinstance(expr.term, Sym) and expr.term.name in self.solution.enabled else 0
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
        if name in self.solution.enabled or name in self.solution.forced:
            return None
        if name in self.solution.forbidden:
            self.solution.conflicts.append(
                f"{name} is wanted ({why}) but must stay off ({self.solution.forbidden[name]})"
            )
            return None
        definition = self.db.preferred(name)
        if definition is None:
            self.solution.undefined[name] = why
            return None
        if not self.db.is_settable(name):
            # No prompt means it cannot be requested, but it can still default on once its
            # parents are enabled (USB_EHCI_PCI needs USB_EHCI_HCD), so the walk continues.
            if name in self.solution.assumed:
                return None
            self.solution.assumed[name] = why
        else:
            self.solution.enabled[name] = why
        for dependency in list(definition.all_deps()):
            self.satisfy(dependency, name)
        return definition

    def follow_selects(self, definition: Definition, owner: str) -> None:
        for target in definition.selects:
            self.select(target, owner)

    def select(self, target: str, owner: str) -> None:
        """Turn on a selected symbol whatever its own dependencies say (Kconfig only warns).

        If its dependencies cannot be met, the symbol is forced rather than solved: it is kept out of
        the fragment and listed as forced, and verify has the final say.
        """
        why = f"selected by {owner}"
        before = Counter(self.problems())
        definition = self.enable(target, why)
        if definition is None:
            return
        new = sorted((Counter(self.problems()) - before).elements())
        if new:
            self.solution.enabled.pop(target, None)
            self.solution.assumed.pop(target, None)
            self.solution.forced[target] = f"{why}, but its dependencies are unmet: {'; '.join(new)}"
        self.follow_selects(definition, target)

    def problems(self) -> list[str]:
        """Every conflict, undefined symbol and unevaluated term recorded so far."""
        return [
            *self.solution.conflicts,
            *(f"{name} is not defined" for name in self.solution.undefined),
            *(f"{term} is not evaluated" for term in self.solution.unknown),
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
            self.solution.conflicts.append(f"{owner} depends on constant {expr.value}: it cannot be built in")
        elif isinstance(expr, Unknown):
            self.solution.unknown.setdefault(expr.text, owner)

    def forbid(self, expr: Expr, owner: str) -> None:
        if isinstance(expr, Sym):
            held = self.solution.enabled.get(expr.name) or self.solution.forced.get(expr.name)
            if held is not None:
                self.solution.conflicts.append(f"{owner} needs {expr.name} off, but {held}")
            else:
                self.solution.forbidden.setdefault(expr.name, f"conflicts with {owner}")
        elif isinstance(expr, Or):  # !(a || b) is !a && !b
            self.forbid(expr.left, owner)
            self.forbid(expr.right, owner)
        elif isinstance(expr, And):  # !(a && b): turning off either one is enough
            self.forbid(expr.left if isinstance(expr.left, Sym) else expr.right, owner)
        elif isinstance(expr, Not):
            self.satisfy(expr.term, owner)
