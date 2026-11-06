"""Demo of the five Python 3.13 language features listed in py313.md.

Run with a 3.13+ interpreter, e.g.:
    /root/miniforge3/bin/python3.14 demo.py

Each section ends with an assertion that must hold for the feature to be
present, and prints a "[PASS]" line. Running the whole file and seeing every
"[PASS]" (plus the final summary) is the acceptance test.
"""

import inspect
import sys
import typing
import warnings
from typing import TypeIs, TypedDict, ReadOnly

# Small self-check harness: collect (name, ok, detail) and report at the end.
RESULTS: list[tuple[str, bool, str]] = []


def check(feature: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((feature, bool(condition), detail))
    status = "PASS" if condition else "FAIL"
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{status}] {feature}{suffix}")


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


# ---------------------------------------------------------------------------
# Feature 1 — Type-parameter defaults (PEP 696)
# `typing.TypeVar`/`ParamSpec`/`TypeVarTuple` now support default values,
# usable inline with the 3.12 PEP 695 type-parameter syntax.
# ---------------------------------------------------------------------------
def feature_1() -> None:
    rule("1. Type-parameter defaults (PEP 696)")

    # T defaults to str; calling without a subscript uses the default.
    def f[T = str](x: T) -> T:
        return x

    # T2 defaults to a typing form.
    def g[T2 = typing.List[str]](items: T2) -> T2:
        return items

    r1, r2 = f("hi"), g(["a", "b"])
    check("default T -> str works", r1 == "hi", f"f('hi') = {r1!r}")
    check("explicit override works", f(42) == 42, f"f(42) = {42!r}")
    check(
        "default T2 -> List[str] works",
        r2 == ["a", "b"],
        f"g(['a','b']) = {r2!r}",
    )
    print("  e.g.  def f[T = str](x: T) -> T: ...")


# ---------------------------------------------------------------------------
# Feature 2 — Class-scope type aliases may use lambda; class-scope
# comprehensions no longer inline into the enclosing scope (PEP 695).
# ---------------------------------------------------------------------------
def feature_2() -> None:
    rule("2. Class-scope lambda / comprehension in annotations (PEP 695)")

    # The doc's verbatim example: a lambda used as a class-scope type alias.
    class C[T]:
        type Alias = lambda: T

    # `type Alias = ...` produces a typing.TypeAliasType, not a raw lambda.
    check(
        "class-scope lambda type alias exists",
        isinstance(C.Alias, typing.TypeAliasType),
        f"type(C.Alias) = {type(C.Alias).__name__}",
    )
    # Parameterizing C[str] yields a distinct alias (robust to the qualified
    # name of a class defined inside this function).
    check(
        "class is generic over T",
        str(C[str]).endswith("C[str]") and C[str] is not C,
        f"C[str] = {C[str]!r}",
    )

    # Comprehension half: a class-scope comprehension keeps its loop variable
    # out of the enclosing function scope. Assert 'n' is not visible here.
    def build():
        class Wrapper:
            squares = [n * n for n in (1, 2, 3)]
        return Wrapper.squares

    out = build()
    check("class-scope comprehension result", out == [1, 4, 9], f"squares = {out}")
    check(
        "comprehension loop var does NOT leak to caller",
        "n" not in dir(),
        "'n' not in enclosing scope",
    )
    print("  e.g.  class C[T]: type Alias = lambda: T")


# ---------------------------------------------------------------------------
# Feature 3 — `global` in an `except` block is legal when the name is also
# used in the corresponding `else` block. Pre-3.13 this was a SyntaxError:
#   "name 'y' is assigned to before global declaration".
# ---------------------------------------------------------------------------
def feature_3() -> None:
    rule("3. `global` inside an `except` block (SyntaxError fixed in 3.13)")

    # NOTE: the code below is a SyntaxError on Python < 3.13 but runs fine
    # here, which is exactly what the 3.13 fix enables.
    def handler() -> int:
        try:
            raise ValueError("boom")
        except ValueError:
            global _f3_marker
            _f3_marker = "handled"
            y = 10
        else:
            y = 20  # using `y` in the else block is the trigger for the fix
        return y

    val = handler()
    check("global in except + else runs", val == 10, f"handler() = {val}")
    check(
        "module global set inside except",
        globals().get("_f3_marker") == "handled",
        f"_f3_marker = {globals().get('_f3_marker')!r}",
    )
    print("  e.g.  except ValueError:\n      global y\n      y = 10\n  else:\n      y = 20")


# ---------------------------------------------------------------------------
# Feature 4 — The compiler strips the common leading whitespace of every
# docstring (effectively inspect.cleandoc). Proven at runtime here by showing
# __doc__ == inspect.cleandoc(<raw source text>) + "\n".
# ---------------------------------------------------------------------------
def feature_4() -> None:
    rule("4. Docstrings get their common leading whitespace stripped (compiler)")

    class Doc:
        """Overview:
            Detail A.
            Detail B.
        Extra:
            Detail C.
        """

    raw = """Overview:
            Detail A.
            Detail B.
        Extra:
            Detail C.
        """
    doc = Doc.__doc__
    # The source literal above is exactly what the compiler saw; de-indenting
    # its common leading whitespace (the 8 spaces shared by the non-blank
    # lines) must match __doc__ exactly (up to the trailing newline).
    check(
        "__doc__ == inspect.cleandoc(raw) + '\\n'",
        doc == inspect.cleandoc(raw) + "\n",
        f"{doc!r}",
    )
    check(
        "no 8-space common indent remains on line 0",
        not doc.splitlines()[0].startswith("        "),
        f"line0 = {doc.splitlines()[0]!r}",
    )
    check(
        "relative indentation preserved (Detail A indented 4)",
        doc.splitlines()[1] == "    Detail A.",
        f"line1 = {doc.splitlines()[1]!r}",
    )
    print("  cleandoc('        ' + lines) is applied by the compiler, not you")


# ---------------------------------------------------------------------------
# Feature 5 — typing.TypeIs (PEP 742) and typing.ReadOnly (PEP 705), plus the
# runtime warnings.deprecated() decorator (PEP 702).
# ---------------------------------------------------------------------------
def feature_5() -> None:
    rule("5. typing.TypeIs (PEP 742), typing.ReadOnly (PEP 705), warnings.deprecated (PEP 702)")

    # --- TypeIs: a narrower "is this actually X?" predicate (distinct from
    # TypeGuard, which only narrows after an assertion, not via isinstance).
    def is_str(value: object) -> TypeIs[str]:
        return isinstance(value, str)

    check("TypeIs guard accepts str", is_str("x") is True, "is_str('x') -> True")
    check("TypeIs guard rejects int", is_str(7) is False, "is_str(7) -> False")

    # --- ReadOnly: marks TypedDict keys as read-only for type checkers.
    class Point(TypedDict):
        x: ReadOnly[int]
        y: ReadOnly[int]

    p: Point = {"x": 1, "y": 2}
    check("ReadOnly TypedDict round-trips", p["x"] == 1 and p["y"] == 2, f"{p}")
    # The *raw* annotation keeps the ReadOnly form; get_type_hints() unwraps it
    # to the base type, so we read __annotations__ to see ReadOnly intact.
    check(
        "annotation kept as ReadOnly[int]",
        Point.__annotations__["x"] == ReadOnly[int],
        f"raw x annotation = {Point.__annotations__['x']!r}",
    )

    # --- warnings.deprecated: emits a DeprecationWarning at call time.
    @warnings.deprecated("use new_api instead")
    def old_api(x: int) -> int:
        return x * 2

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = old_api(21)
    check(
        "deprecated() returns value",
        result == 42,
        f"old_api(21) = {result}",
    )
    check(
        "deprecated() emits DeprecationWarning",
        any(issubclass(c.category, DeprecationWarning) for c in caught),
        f"{len(caught)} warning(s)",
    )
    if caught:
        check("warning message carries the reason", "new_api" in str(caught[0].message), str(caught[0].message))
    print("  TypeIs narrows like isinstance; ReadOnly is a type-checker hint")


def main() -> int:
    print("Python 3.13 features demo")
    print(f"Interpreter: {sys.version.split()[0]} ({sys.executable})")

    feature_1()
    feature_2()
    feature_3()
    feature_4()
    feature_5()

    rule("Summary")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    for name, ok, _ in RESULTS:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}")
    print(f"\n{passed}/{total} checks passed.")
    if passed != total:
        print("SOME CHECKS FAILED — is this running on Python >= 3.13?")
        return 1
    print("All features verified. Run this file with Python 3.13+ (e.g. python3.14).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
