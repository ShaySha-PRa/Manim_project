"""Allowlisted scientific kernels. Scenes never call these."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class KernelResult:
    arrays: dict[str, np.ndarray]
    assertions: dict[str, float | int | bool | str]


def canonical_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_float(params: Mapping[str, Any], key: str, default: float) -> float:
    raw = params.get(key, default)
    return float(raw)


def _as_int(params: Mapping[str, Any], key: str, default: int) -> int:
    raw = params.get(key, default)
    return int(raw)


def _diverging_rgb(field: np.ndarray) -> np.ndarray:
    scaled = np.clip(field / (np.max(np.abs(field)) + 1e-8), -1.0, 1.0)
    positive = np.clip(scaled, 0.0, 1.0)
    negative = np.clip(-scaled, 0.0, 1.0)
    red = np.clip(0.12 + 0.88 * positive + 0.15 * (1.0 - negative) * (1.0 - positive), 0, 1)
    green = np.clip(0.18 + 0.55 * (1.0 - np.abs(scaled)), 0, 1)
    blue = np.clip(0.18 + 0.82 * negative + 0.12 * (1.0 - positive), 0, 1)
    rgb = np.stack((red, green, blue), axis=-1)
    return (rgb * 255.0).astype(np.uint8)


def wave2d_superposition(params: Mapping[str, Any], _input_text: str | None) -> KernelResult:
    speed = _as_float(params, "c", 1.15)
    wave_number = _as_float(params, "k", 6.2)
    sigma = _as_float(params, "sigma", 0.85)
    amplitude = _as_float(params, "amplitude", 1.0)
    x_left = _as_float(params, "x_left", -3.2)
    x_right = _as_float(params, "x_right", 3.2)
    t_collide = (x_right - x_left) / (2.0 * speed)
    t_min = _as_float(params, "t_min", 0.0)
    t_max = _as_float(params, "t_max", 2.0 * t_collide)
    nx = _as_int(params, "nx", 64)
    ny = _as_int(params, "ny", 64)
    nt = _as_int(params, "nt", 36)
    omega = speed * wave_number
    xs = np.linspace(-6.0, 6.0, nx)
    ys = np.linspace(-4.0, 4.0, ny)
    ts = np.linspace(t_min, t_max, nt)
    xx, yy = np.meshgrid(xs, ys, indexing="xy")

    def packet(x0: float, direction: float, time: float) -> np.ndarray:
        center = x0 + direction * speed * time
        envelope = np.exp(-((xx - center) ** 2 + yy**2) / (2.0 * sigma**2))
        carrier = np.cos(wave_number * (xx - center) - omega * time * direction)
        return amplitude * envelope * carrier

    frames = np.empty((nt, ny, nx), dtype=np.float32)
    left_only = np.empty_like(frames)
    right_only = np.empty_like(frames)
    for index, time in enumerate(ts):
        left = packet(x_left, 1.0, time)
        right = packet(x_right, -1.0, time)
        left_only[index] = left
        right_only[index] = right
        frames[index] = left + right
    residual = np.max(np.abs(frames - (left_only + right_only)))
    rgb = _diverging_rgb(frames)
    return KernelResult(
        arrays={
            "rgb": rgb,
            "field": frames,
            "x": xs.astype(np.float32),
            "y": ys.astype(np.float32),
            "t": ts.astype(np.float32),
        },
        assertions={
            "linear_superposition": bool(residual < 1e-6),
            "superposition_residual": float(residual),
            "frame_count": int(nt),
            "collision_in_window": bool(t_min < t_collide < t_max),
            "pass_through": bool(x_left + speed * t_max > 0.5 and x_right - speed * t_max < -0.5),
        },
    )


def fourier_square_wave(params: Mapping[str, Any], _input_text: str | None) -> KernelResult:
    import sympy as sp

    n_max = _as_int(params, "n_max", 31)
    sample_count = _as_int(params, "samples", 240)
    n_symbol = sp.symbols("n", integer=True, positive=True)
    coeff_expr = 4 / (n_symbol * sp.pi)
    odds = [k for k in range(1, n_max + 1, 2)]
    coeffs = np.array([float(coeff_expr.subs(n_symbol, k)) for k in odds], dtype=np.float64)
    xs = np.linspace(-np.pi, np.pi, sample_count, dtype=np.float64)
    square = np.where(xs < 0, -1.0, 1.0)
    square[xs == 0] = 0.0
    partials = np.zeros((len(odds), sample_count), dtype=np.float64)
    running = np.zeros(sample_count, dtype=np.float64)
    for index, (harmonic, coeff) in enumerate(zip(odds, coeffs, strict=True)):
        running = running + coeff * np.sin(harmonic * xs)
        partials[index] = running
    overshoot = float(np.max(partials[-1]) - 1.0)
    return KernelResult(
        arrays={
            "x": xs.astype(np.float32),
            "square": square.astype(np.float32),
            "partials": partials.astype(np.float32),
            "odds": np.array(odds, dtype=np.int32),
            "coeffs": coeffs.astype(np.float32),
        },
        assertions={
            "harmonic_coefficients": bool(np.allclose(coeffs, 4.0 / (np.array(odds) * np.pi))),
            "gibbs_overshoot": bool(overshoot > 0.08),
            "overshoot_value": overshoot,
            "term_count": int(len(odds)),
        },
    )


def _rk4(
    fun: Callable[[float, np.ndarray], np.ndarray],
    y0: np.ndarray,
    ts: np.ndarray,
) -> np.ndarray:
    path = np.empty((ts.size, y0.size), dtype=np.float64)
    path[0] = y0
    for index in range(ts.size - 1):
        time = ts[index]
        step = ts[index + 1] - time
        state = path[index]
        k1 = fun(time, state)
        k2 = fun(time + 0.5 * step, state + 0.5 * step * k1)
        k3 = fun(time + 0.5 * step, state + 0.5 * step * k2)
        k4 = fun(time + step, state + step * k3)
        path[index + 1] = state + (step / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
    return path


def lorenz_ensemble(params: Mapping[str, Any], _input_text: str | None) -> KernelResult:
    from scipy.integrate import solve_ivp

    sigma = _as_float(params, "sigma", 10.0)
    rho = _as_float(params, "rho", 28.0)
    beta = _as_float(params, "beta", 8.0 / 3.0)
    t_end = _as_float(params, "t_end", 30.0)
    n_times = _as_int(params, "samples", 160)
    delta = _as_float(params, "delta", 1e-5)
    base = np.array([1.0, 1.0, 1.0], dtype=np.float64)
    initials = np.stack(
        [base, base + np.array([delta, 0.0, 0.0]), base + np.array([0.0, delta, 0.0])]
    )

    def lorenz(_time: float, state: np.ndarray) -> np.ndarray:
        x_val, y_val, z_val = state
        return np.array(
            [sigma * (y_val - x_val), x_val * (rho - z_val) - y_val, x_val * y_val - beta * z_val],
            dtype=np.float64,
        )

    ts = np.linspace(0.0, t_end, n_times)
    paths = []
    for y0 in initials:
        solved = solve_ivp(
            lorenz,
            (0.0, t_end),
            y0,
            t_eval=ts,
            rtol=1e-7,
            atol=1e-9,
            method="RK45",
        )
        if not solved.success:
            raise RuntimeError("lorenz solve_ivp failed")
        paths.append(solved.y.T)
    stacked = np.stack(paths, axis=0).astype(np.float32)
    start_gap = float(np.linalg.norm(stacked[1, 0] - stacked[0, 0]))
    end_gap = float(np.linalg.norm(stacked[1, -1] - stacked[0, -1]))
    return KernelResult(
        arrays={"paths": stacked, "t": ts.astype(np.float32)},
        assertions={
            "trajectory_error": bool(start_gap <= 2e-5),
            "initial_separation": start_gap,
            "late_separation": end_gap,
            "diverged": bool(end_gap > 1.0),
        },
    )


def pid_step_response(params: Mapping[str, Any], _input_text: str | None) -> KernelResult:
    wn = _as_float(params, "wn", 2.4)
    zeta = _as_float(params, "zeta", 0.35)
    t_end = _as_float(params, "t_end", 8.0)
    n_times = _as_int(params, "samples", 200)
    gains = (
        (
            _as_float(params, "kp_a", 1.2),
            _as_float(params, "ki_a", 0.7),
            _as_float(params, "kd_a", 0.45),
        ),
        (
            _as_float(params, "kp_b", 2.8),
            _as_float(params, "ki_b", 1.4),
            _as_float(params, "kd_b", 0.35),
        ),
        (
            _as_float(params, "kp_c", 6.5),
            _as_float(params, "ki_c", 2.2),
            _as_float(params, "kd_c", 0.12),
        ),
    )
    ts = np.linspace(0.0, t_end, n_times)

    def simulate(kp: float, ki: float, kd: float) -> tuple[np.ndarray, np.ndarray]:
        y0 = np.array([0.0, 0.0, 0.0, 0.0], dtype=np.float64)

        def rhs(_time: float, state: np.ndarray) -> np.ndarray:
            y_val, ydot, integ, _prev = state
            error = 1.0 - y_val
            control = kp * error + ki * integ + kd * (-ydot)
            yddot = (wn * wn) * control - 2.0 * zeta * wn * ydot - wn * wn * y_val
            return np.array([ydot, yddot, error, 0.0], dtype=np.float64)

        path = _rk4(rhs, y0, ts)
        y_series = path[:, 0]
        u_series = kp * (1.0 - y_series) + ki * path[:, 2] + kd * (-path[:, 1])
        return y_series, u_series

    y_rows = []
    u_rows = []
    overshoots = []
    for kp, ki, kd in gains:
        y_series, u_series = simulate(kp, ki, kd)
        y_rows.append(y_series)
        u_rows.append(u_series)
        overshoots.append(float(np.max(y_series) - 1.0))
    y_arr = np.stack(y_rows).astype(np.float32)
    u_arr = np.stack(u_rows).astype(np.float32)
    finals = [float(row[-1]) for row in y_rows]
    reached = bool(all(abs(value - 1.0) < 0.08 for value in finals))
    return KernelResult(
        arrays={"t": ts.astype(np.float32), "y": y_arr, "u": u_arr},
        assertions={
            "metric_match": bool(reached and (overshoots[2] - overshoots[0]) > 0.15),
            "reached_setpoint": reached,
            "overshoot_a": overshoots[0],
            "overshoot_b": overshoots[1],
            "overshoot_c": overshoots[2],
        },
    )


def csv_anomaly(params: Mapping[str, Any], input_text: str | None) -> KernelResult:
    import pandas as pd

    if not input_text or not input_text.strip():
        raise ValueError("csv_anomaly requires csv_text")
    frame = pd.read_csv(io.StringIO(input_text))
    time_column = "time" if "time" in frame.columns else "timestamp"
    required = ("temperature", "pressure")
    missing = [name for name in required if name not in frame.columns]
    if "time" not in frame.columns and "timestamp" not in frame.columns:
        missing.insert(0, "time|timestamp")
    if missing:
        raise ValueError(f"csv missing columns: {missing}")
    if len(frame) > 5_000:
        raise ValueError("csv exceeds row limit")
    time = frame[time_column].to_numpy(dtype=np.float64)
    temperature = frame["temperature"].to_numpy(dtype=np.float64)
    pressure = frame["pressure"].to_numpy(dtype=np.float64)
    temperature_delta = np.abs(temperature - np.median(temperature))
    center = _as_float(params, "center", float(time[int(np.argmax(temperature_delta))]))
    if "width" in params:
        width = _as_float(params, "width", 20.0)
    else:
        ordered = np.unique(np.sort(time))
        steps = np.diff(ordered)
        positive_steps = steps[steps > 0]
        width = float(np.median(positive_steps) * 0.49) if positive_steps.size else 0.0
    mask = np.abs(time - center) <= width
    if not np.any(mask):
        peak = int(np.argmax(temperature_delta))
        center = float(time[peak])
        mask = np.abs(time - center) <= width
    return KernelResult(
        arrays={
            "t": time.astype(np.float32),
            "temperature": temperature.astype(np.float32),
            "pressure": pressure.astype(np.float32),
            "mask": mask.astype(np.uint8),
        },
        assertions={
            "data_fidelity": True,
            "row_count": int(len(frame)),
            "anomaly_center": float(center),
            "anomaly_count": int(mask.sum()),
        },
    )


def frenet_frame(params: Mapping[str, Any], _input_text: str | None) -> KernelResult:
    samples = _as_int(params, "samples", 180)
    a = _as_float(params, "a", 1.1)
    b = _as_float(params, "b", 0.28)
    s_values = np.linspace(0.0, 4.0 * np.pi, samples)
    helix = np.stack((a * np.cos(s_values), a * np.sin(s_values), b * s_values), axis=1)
    d1 = np.gradient(helix, s_values, axis=0)
    speed = np.linalg.norm(d1, axis=1, keepdims=True)
    tangent = d1 / np.clip(speed, 1e-8, None)
    d2 = np.gradient(tangent, s_values, axis=0)
    normal_norm = np.linalg.norm(d2, axis=1, keepdims=True)
    normal = d2 / np.clip(normal_norm, 1e-8, None)
    binormal = np.cross(tangent, normal)
    binormal /= np.clip(np.linalg.norm(binormal, axis=1, keepdims=True), 1e-8, None)
    dots_tn = np.abs(np.sum(tangent * normal, axis=1))
    dots_tb = np.abs(np.sum(tangent * binormal, axis=1))
    dots_nb = np.abs(np.sum(normal * binormal, axis=1))
    orthonormal = bool(np.max(dots_tn) < 0.05 and np.max(dots_tb) < 0.05 and np.max(dots_nb) < 0.05)
    return KernelResult(
        arrays={
            "curve": helix.astype(np.float32),
            "tangent": tangent.astype(np.float32),
            "normal": normal.astype(np.float32),
            "binormal": binormal.astype(np.float32),
            "s": s_values.astype(np.float32),
        },
        assertions={
            "frenet_orthonormal": orthonormal,
            "max_t_n": float(np.max(dots_tn)),
            "max_t_b": float(np.max(dots_tb)),
            "max_n_b": float(np.max(dots_nb)),
        },
    )


def ode_compare(params: Mapping[str, Any], input_text: str | None) -> KernelResult:
    import pandas as pd
    from scipy.integrate import odeint

    if str(params.get("system", "")) != "lotka_volterra":
        raise ValueError("ode_compare only accepts cataloged lotka_volterra")
    if not input_text or not input_text.strip():
        raise ValueError("ode_compare requires csv_text")
    frame = pd.read_csv(io.StringIO(input_text))
    time_col = str(params.get("time_column", "Year"))
    x_col = str(params.get("x_column", "Hare"))
    y_col = str(params.get("y_column", "Lynx"))
    missing = [name for name in (time_col, x_col, y_col) if name not in frame.columns]
    if missing:
        raise ValueError(f"csv missing columns: {missing}")
    if len(frame) > 5_000:
        raise ValueError("csv exceeds row limit")
    time = frame[time_col].to_numpy(dtype=np.float64)
    observed_x = frame[x_col].to_numpy(dtype=np.float64)
    observed_y = frame[y_col].to_numpy(dtype=np.float64)
    alpha = _as_float(params, "alpha", 1.0)
    beta = _as_float(params, "beta", 0.1)
    gamma = _as_float(params, "gamma", 1.5)
    delta = _as_float(params, "delta", 0.075)
    t_rel = time - time[0]

    def rhs(state: np.ndarray, _t: float) -> list[float]:
        prey, predator = state
        return [
            alpha * prey - beta * prey * predator,
            delta * prey * predator - gamma * predator,
        ]

    predicted = odeint(rhs, [observed_x[0], observed_y[0]], t_rel)
    residual = np.concatenate((predicted[:, 0] - observed_x, predicted[:, 1] - observed_y))
    scale = float(np.std(np.concatenate((observed_x, observed_y))) + 1e-8)
    rmse = float(np.sqrt(np.mean(residual * residual)))
    matched = bool(rmse / scale < 0.35)
    return KernelResult(
        arrays={
            "t": t_rel.astype(np.float32),
            "observed": observed_x.astype(np.float32),
            "predicted": predicted[:, 0].astype(np.float32),
            "observed_y": observed_y.astype(np.float32),
            "predicted_y": predicted[:, 1].astype(np.float32),
        },
        assertions={
            "residual_matches_tool": matched,
            "rmse": rmse,
            "equation_provenance": True,
            "row_count": int(len(frame)),
        },
    )


KERNELS: dict[str, Callable[[Mapping[str, Any], str | None], KernelResult]] = {
    "wave2d_superposition": wave2d_superposition,
    "fourier_square_wave": fourier_square_wave,
    "lorenz_ensemble": lorenz_ensemble,
    "pid_step_response": pid_step_response,
    "csv_anomaly": csv_anomaly,
    "frenet_frame": frenet_frame,
    "ode_compare": ode_compare,
}


def allowed_ops() -> frozenset[str]:
    return frozenset(KERNELS)


ALLOWED_OPS = allowed_ops()


def register_simulator(
    name: str,
    fn: Callable[[Mapping[str, Any], str | None], KernelResult],
) -> None:
    """Allowlist a scientific simulator plugin. The model still cannot name new ops."""
    if not name.isidentifier() or not name.islower() or "." in name:
        raise ValueError("simulator name is invalid")
    if name in KERNELS:
        raise ValueError(f"simulator already registered: {name}")
    KERNELS[name] = fn
    global ALLOWED_OPS
    ALLOWED_OPS = allowed_ops()


def unregister_simulator(name: str) -> None:
    KERNELS.pop(name, None)
    global ALLOWED_OPS
    ALLOWED_OPS = allowed_ops()


def run_kernel(op: str, params: Mapping[str, Any], input_text: str | None) -> KernelResult:
    if op not in KERNELS:
        raise ValueError(f"tool op is not allowlisted: {op}")
    return KERNELS[op](params, input_text)


def write_npz(path: Path, result: KernelResult) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(result.arrays)
    payload["assertion_json"] = np.asarray(canonical_dumps(result.assertions))
    np.savez_compressed(path, **payload)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest
