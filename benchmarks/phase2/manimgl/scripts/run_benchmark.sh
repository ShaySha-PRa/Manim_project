#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${ALLOW_ELIMINATED_MANIMGL_REPRO:-}" != "1" ]]; then
    echo "ManimGL was eliminated by ADR-001; set ALLOW_ELIMINATED_MANIMGL_REPRO=1 only to reproduce the recorded failure." >&2
    exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACTS="${ROOT}/artifacts"
IMAGE="${MANIMGL_IMAGE:-manim-project/manimgl-benchmark:v1.7.2}"
SCENE_CLASSES=(FormulaTransform Derivative FunctionPlot ParameterSweep Tangent Area)
SCENE_IDS=(formula_transform derivative function_plot parameter_sweep tangent area)

rm -rf "${ARTIFACTS}"
mkdir -p "${ARTIFACTS}/logs" "${ARTIFACTS}/videos"
: > "${ARTIFACTS}/runs.jsonl"
rm -f "${ROOT}/result.json"

BUILD_COMMAND="docker build --build-arg MANIM_TAG=v1.7.2 -t ${IMAGE} -f ${ROOT}/Dockerfile ${ROOT}"
if ! docker build --build-arg MANIM_TAG=v1.7.2 \
    -t "${IMAGE}" -f "${ROOT}/Dockerfile" "${ROOT}" \
    >"${ARTIFACTS}/logs/build.log" 2>&1; then
    printf 'Docker build failed.\nCommand: %s\nRaw log: %s\n' \
        "${BUILD_COMMAND}" "${ARTIFACTS}/logs/build.log" \
        > "${ARTIFACTS}/BLOCKED.md"
    exit 1
fi

docker_value() {
    docker run --rm "${IMAGE}" sh -lc "$1"
}

IMAGE_ID="$(docker image inspect --format '{{.Id}}' "${IMAGE}")"
ENGINE_VERSION="$(docker_value "git -C /opt/manim describe --tags --exact-match HEAD")"
PYTHON_VERSION="$(docker_value "python3 -VV 2>&1")"
FFMPEG_VERSION="$(docker_value "ffmpeg -version 2>&1 | head -n 1")"
LATEX_VERSION="$(docker_value "latex --version 2>&1 | head -n 1")"
FONT_VERSIONS="$(docker_value "dpkg-query -W -f='fonts-dejavu-core=\${Version}; fonts-liberation2=\${Version}' fonts-dejavu-core fonts-liberation2")"

python3 - "${ARTIFACTS}/environment.json" \
    "${ENGINE_VERSION}" "${PYTHON_VERSION}" "${FFMPEG_VERSION}" \
    "${LATEX_VERSION}" "${FONT_VERSIONS}" "${IMAGE_ID}" <<'PY'
import json
import sys

path, engine, python, ffmpeg, latex, fonts, image_id = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump({
        "engine_version": engine,
        "python_version": python,
        "ffmpeg_version": ffmpeg,
        "latex_version": latex,
        "font_versions": [item.strip() for item in fonts.split(";") if item.strip()],
        "container_or_environment": image_id,
    }, handle, indent=2)
    handle.write("\n")
PY

record_run() {
    local scene_id="$1" iteration="$2" success="$3" exit_code="$4"
    local duration="$5" command="$6" output_path="$7" output_hash="$8" log_path="$9"
    python3 - "${ARTIFACTS}/runs.jsonl" "${scene_id}" "${iteration}" \
        "${success}" "${exit_code}" "${duration}" "${command}" \
        "${output_path}" "${output_hash}" "${log_path}" <<'PY'
import json
import sys

path, scene, iteration, success, exit_code, duration, command, output, digest, log = sys.argv[1:]
record = {
    "scene_id": scene,
    "iteration": int(iteration),
    "success": success == "true",
    "exit_code": int(exit_code),
    "duration_seconds": float(duration),
    "command": command,
    "output_path": output,
    "output_sha256": digest,
    "log_path": log,
}
with open(path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
PY
}

for index in "${!SCENE_CLASSES[@]}"; do
    scene_class="${SCENE_CLASSES[$index]}"
    scene_id="${SCENE_IDS[$index]}"
    for iteration in 1 2; do
        run_dir="${ARTIFACTS}/videos/${scene_id}/run_${iteration}"
        log_path="${ARTIFACTS}/logs/${scene_id}_run_${iteration}.log"
        mkdir -p "${run_dir}"
        find "${run_dir}" -type f -delete

        command="docker run --rm -e LIBGL_ALWAYS_SOFTWARE=1 -e MESA_LOADER_DRIVER_OVERRIDE=llvmpipe -v ${ROOT}:/benchmark -w /benchmark ${IMAGE} xvfb-run -a -s '-screen 0 1280x720x24 +extension GLX +render -noreset' manimgl scenes.py ${scene_class} -l -w --video_dir /benchmark/artifacts/videos/${scene_id}/run_${iteration}"
        start_ns="$(date +%s%N)"
        set +e
        docker run --rm \
            -e LIBGL_ALWAYS_SOFTWARE=1 \
            -e MESA_LOADER_DRIVER_OVERRIDE=llvmpipe \
            -v "${ROOT}:/benchmark" -w /benchmark "${IMAGE}" \
            xvfb-run -a -s '-screen 0 1280x720x24 +extension GLX +render -noreset' \
            manimgl scenes.py "${scene_class}" -l -w \
            --video_dir "/benchmark/artifacts/videos/${scene_id}/run_${iteration}" \
            >"${log_path}" 2>&1
        exit_code=$?
        set -e
        end_ns="$(date +%s%N)"
        duration="$(python3 -c "print((${end_ns} - ${start_ns}) / 1_000_000_000)")"

        output="$(find "${run_dir}" -type f -name '*.mp4' -print -quit)"
        success=false
        output_hash=""
        relative_output=""
        if [[ "${exit_code}" -eq 0 && -n "${output}" ]]; then
            success=true
            output_hash="$(sha256sum "${output}" | awk '{print $1}')"
            relative_output="${output#${ROOT}/}"
        fi
        relative_log="${log_path#${ROOT}/}"
        record_run "${scene_id}" "${iteration}" "${success}" "${exit_code}" \
            "${duration}" "${command}" "${relative_output}" "${output_hash}" "${relative_log}"
    done
done

# result.json is emitted after all 12 measured attempts, including failures.
python3 "${ROOT}/scripts/write_result.py" "${ROOT}"
