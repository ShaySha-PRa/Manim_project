import argparse
from pathlib import Path

from manim_workbench_contracts.generation import render_contract_artifacts

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "packages" / "contracts" / "generated"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate or verify shared contract artifacts")
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    schema, typescript = render_contract_artifacts()
    expected = {
        GENERATED / "contracts.schema.json": schema,
        GENERATED / "contracts.ts": typescript,
    }
    if arguments.check:
        stale = [path for path, content in expected.items() if path.read_text() != content]
        if stale:
            parser.error("generated contracts are stale: " + ", ".join(map(str, stale)))
        return
    GENERATED.mkdir(parents=True, exist_ok=True)
    for path, content in expected.items():
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
