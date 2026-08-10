import shutil
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GENERATED_CONTRACTS = REPOSITORY_ROOT / "packages" / "contracts" / "generated" / "contracts.ts"
TYPESCRIPT_COMPILER = REPOSITORY_ROOT / "node_modules" / ".bin" / "tsc"


def test_generated_contracts_compile_for_recursive_json_consumer(tmp_path: Path) -> None:
    assert TYPESCRIPT_COMPILER.is_file(), "run npm ci before the contract test suite"
    shutil.copyfile(GENERATED_CONTRACTS, tmp_path / "contracts.ts")
    consumer = tmp_path / "consumer.ts"
    consumer.write_text(
        """
import type { JsonObject, JsonValue } from "./contracts";

const primitive: JsonValue = true;
const nullable: JsonValue = null;
const objectValue: JsonObject = {
  enabled: primitive,
  nested: { values: [1, "two", false, null] },
};
const readonlyValues: ReadonlyArray<JsonValue> = [objectValue, ["nested"] as const];
const document: JsonValue = { objectValue, readonlyValues };

void nullable;
void document;
""".strip()
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(TYPESCRIPT_COMPILER),
            "--noEmit",
            "--strict",
            "--skipLibCheck",
            "--target",
            "ES2022",
            "--module",
            "NodeNext",
            "--moduleResolution",
            "NodeNext",
            str(consumer),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
