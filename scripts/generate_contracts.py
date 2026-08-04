from pathlib import Path

from manim_workbench_contracts.generation import render_contract_artifacts

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "packages" / "contracts" / "generated"


def main() -> None:
    schema, typescript = render_contract_artifacts()
    GENERATED.mkdir(parents=True, exist_ok=True)
    (GENERATED / "contracts.schema.json").write_text(schema, encoding="utf-8")
    (GENERATED / "contracts.ts").write_text(typescript, encoding="utf-8")


if __name__ == "__main__":
    main()
