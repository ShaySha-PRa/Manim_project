import json

from manim_workbench_contracts import CONTRACT_SCHEMA_VERSION


def main() -> None:
    print(
        json.dumps(
            {
                "status": "idle",
                "service": "runner",
                "contract_schema_version": CONTRACT_SCHEMA_VERSION,
                "docker_access": False,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
