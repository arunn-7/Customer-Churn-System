"""Static consistency checks for the company-workspace migration.

    .\\venv\\Scripts\\python.exe tests\\test_migration_guards.py

These parse `migrations/versions/0001_company_workspace.py` with `ast` and never
open a database connection, so they are safe to run at any time and cannot touch
live data.

Why this file exists
--------------------
`_assert_no_operational_data()` protects every table that `downgrade()` drops.
That list was once missing `companies`, so a registered company with no imports
yet was silently destroyed. These tests make that class of mistake fail loudly
instead of depending on someone re-reading the migration by hand.

If you add an `op.create_table(...)` or `op.drop_table(...)` to the migration,
these tests will fail until `_OPERATIONAL_TABLES` is updated to match.
"""

import ast
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATION = os.path.join(
    PROJECT_ROOT, "migrations", "versions", "0001_company_workspace.py"
)

RESULTS: list[tuple[bool, str, str]] = []


def check(condition: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(condition), name, detail))


def _load() -> tuple[str, ast.Module]:
    source = open(MIGRATION, encoding="utf-8").read()
    return source, ast.parse(source)


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name}() not found in migration")


def _operational_tables(tree: ast.Module) -> list[str]:
    """Read the _OPERATIONAL_TABLES tuple literal."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "_OPERATIONAL_TABLES" in targets:
                return [el.value for el in node.value.elts]
    raise AssertionError("_OPERATIONAL_TABLES not found in migration")


def _dropped_tables(func: ast.FunctionDef) -> list[str]:
    """Every op.drop_table("x") target inside a function."""
    found = []
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "drop_table"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            found.append(node.args[0].value)
    return found


def _created_tables(func: ast.FunctionDef) -> list[str]:
    """Every op.create_table("x") target inside a function."""
    found = []
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_table"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            found.append(node.args[0].value)
    return found


def _first_call_name(func: ast.FunctionDef) -> str | None:
    """Name of the function called by the first statement in a body."""
    body = [s for s in func.body if not isinstance(s, ast.Expr) or
            not isinstance(s.value, ast.Constant)]
    if not body:
        return None
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Call):
        call = first.value
        if isinstance(call.func, ast.Name):
            return call.func.id
        if isinstance(call.func, ast.Attribute):
            return call.func.attr
    return None


def test_guard_covers_every_dropped_table():
    """THE regression test: every drop_table() target must be guarded."""
    _, tree = _load()
    guarded = set(_operational_tables(tree))
    dropped = set(_dropped_tables(_func(tree, "downgrade")))

    check(
        "companies" in guarded,
        "1a. companies is in _OPERATIONAL_TABLES",
        f"guarded={sorted(guarded)}",
    )
    missing = dropped - guarded
    check(
        not missing,
        "1b. every op.drop_table() target is guarded",
        f"dropped={sorted(dropped)} missing_from_guard={sorted(missing)}"
        if missing else f"{len(dropped)} tables, all guarded",
    )
    check(
        len(dropped) == 6,
        "1c. downgrade drops the expected six tables",
        f"dropped={sorted(dropped)}",
    )


def test_guard_does_not_block_rollback_forever():
    """Tables that survive downgrade must NOT be guarded.

    If `customers` were guarded, downgrade could never run because the IBM
    rows always exist.
    """
    _, tree = _load()
    guarded = set(_operational_tables(tree))
    survivors = {"customers", "users"}
    wrongly = guarded & survivors
    check(
        not wrongly,
        "2. surviving tables (customers/users) are not in the guard",
        f"wrongly_guarded={sorted(wrongly)}" if wrongly else "OK",
    )


def test_created_tables_are_all_guarded():
    """A newly created table must also be added to the guard."""
    _, tree = _load()
    guarded = set(_operational_tables(tree))
    created = set(_created_tables(_func(tree, "upgrade")))
    created.discard("alembic_version")
    missing = created - guarded
    check(
        not missing,
        "3. every op.create_table() target is guarded",
        f"created={sorted(created)} missing={sorted(missing)}"
        if missing else f"{len(created)} tables, all guarded",
    )


def test_guards_run_before_any_ddl():
    _, tree = _load()
    up_first = _first_call_name(_func(tree, "upgrade"))
    down_first = _first_call_name(_func(tree, "downgrade"))
    check(
        up_first == "_preflight",
        "4a. _preflight() is the first statement in upgrade()",
        f"first call = {up_first}",
    )
    check(
        down_first == "_assert_no_operational_data",
        "4b. _assert_no_operational_data() is first in downgrade()",
        f"first call = {down_first}",
    )


def _executed_sql(tree: ast.Module) -> list[str]:
    """Raw SQL strings handed to op.execute().

    op.drop_table()/op.drop_column() are Alembic helpers and are handled by the
    guards. Raw SQL is different: it bypasses Alembic's bookkeeping, so a
    DROP TABLE / TRUNCATE / DELETE issued here would slip past the guard.
    """
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.append(node.args[0].value)
    return found


def test_no_destructive_sql():
    """op.execute() must never carry destructive SQL that bypasses the guards."""
    _, tree = _load()
    offenders = [
        sql for sql in _executed_sql(tree)
        if any(kw in sql.lower() for kw in ("drop table", "truncate", "delete from"))
    ]
    check(
        not offenders,
        "5. no destructive raw SQL in op.execute()",
        f"found={offenders}" if offenders
        else f"{len(_executed_sql(tree))} executed statement(s), all non-destructive",
    )


def test_docstring_lists_every_table():
    """The guard's docstring must not fall behind the tuple again."""
    _, tree = _load()
    guarded = _operational_tables(tree)
    doc = ast.get_docstring(_func(tree, "_assert_no_operational_data")) or ""
    missing = [t for t in guarded if t not in doc]
    check(
        not missing,
        "6. _assert_no_operational_data docstring names every table",
        f"missing_from_docstring={missing}" if missing else f"all {len(guarded)} named",
    )


def test_uses_migration_connection():
    """Both guards must read through the migration's own connection."""
    _, tree = _load()
    for fn in ("_preflight", "_assert_no_operational_data"):
        body = ast.dump(_func(tree, fn))
        check(
            "get_bind" in body,
            f"7. {fn}() uses op.get_bind()",
            "ok" if "get_bind" in body else "MISSING get_bind",
        )


def main() -> int:
    test_guard_covers_every_dropped_table()
    test_guard_does_not_block_rollback_forever()
    test_created_tables_are_all_guarded()
    test_guards_run_before_any_ddl()
    test_no_destructive_sql()
    test_docstring_lists_every_table()
    test_uses_migration_connection()

    width = max(len(name) for _, name, _ in RESULTS)
    print("=" * 96)
    print("MIGRATION GUARD CONSISTENCY (static, no database connection)")
    print("=" * 96)
    for passed, name, detail in RESULTS:
        print(f"[{'PASS' if passed else 'FAIL'}] {name.ljust(width)}  {detail}")
    print("=" * 96)
    failed = [n for ok, n, _ in RESULTS if not ok]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
    print("=" * 96)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
