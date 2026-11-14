import json
from pathlib import Path

from scripts.check_dbt_docs import find_undocumented, main


def _node(name: str, description: str, columns: dict[str, str], **extra: str) -> dict:
    node = {
        "name": name,
        "resource_type": "model",
        "package_name": "ecommerce_analytics",
        "description": description,
        "columns": {key: {"description": value} for key, value in columns.items()},
    }
    node.update(extra)
    return node


MANIFEST = {
    "nodes": {
        "model.a": _node("fct_good", "Documented.", {"id": "Key."}),
        "model.b": _node("fct_missing", "", {"id": "Key.", "amount": "  "}),
        "seed.c": _node("seed_cats", "Seed.", {"code": ""}, resource_type="seed"),
        "test.d": _node("some_test", "", {}, resource_type="test"),
        "model.e": _node("utils_model", "", {"x": ""}, package_name="dbt_utils"),
    }
}


def test_finds_missing_model_and_column_descriptions() -> None:
    assert find_undocumented(MANIFEST) == [
        "fct_missing",
        "fct_missing.amount",
        "seed_cats.code",
    ]


def test_ignores_tests_and_other_packages() -> None:
    names = find_undocumented(MANIFEST)
    assert not any(name.startswith(("some_test", "utils_model")) for name in names)


def test_main_exit_codes(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"nodes": {"model.a": MANIFEST["nodes"]["model.a"]}}))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(MANIFEST))
    assert main(["--manifest", str(good)]) == 0
    assert main(["--manifest", str(bad)]) == 1
    assert main(["--manifest", str(tmp_path / "absent.json")]) == 1
