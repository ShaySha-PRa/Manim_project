"""Closed scientific-reproduction catalog. Never invent equations."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from scipy.integrate import odeint

_PARAM = re.compile(
    r"(?:alpha|α)\s*=\s*([0-9.]+).*(?:beta|β)\s*=\s*([0-9.]+).*"
    r"(?:gamma|γ)\s*=\s*([0-9.]+).*(?:delta|δ)\s*=\s*([0-9.]+)",
    re.I | re.S,
)


@dataclass(frozen=True, slots=True)
class PaperMatch:
    system: str
    alpha: float
    beta: float
    gamma: float
    delta: float
    time_column: str
    x_column: str
    y_column: str
    confidence: float


def extract_pdf_text(payload: bytes) -> str:
    if payload.startswith(b"%PDF"):
        latin = payload.decode("latin-1", errors="ignore")
        chunks = re.findall(r"\((?:\\.|[^\\)])*\)", latin)
        text = " ".join(_unescape_pdf_string(item) for item in chunks)
        if text.strip():
            return text
    return payload.decode("utf-8", errors="replace")


def match_paper_catalog(paper_text: str, csv_header: str | None = None) -> PaperMatch | None:
    blob = paper_text.lower()
    named = "lotka" in blob and "volterra" in blob
    named_zh = "洛特卡" in paper_text and "沃尔泰拉" in paper_text
    if not (named or named_zh):
        return None
    if not re.search(r"dx\s*/\s*dt|dxdt|捕食|prey", blob):
        return None
    parsed = _PARAM.search(paper_text)
    if parsed is None:
        return None
    alpha, beta, gamma, delta = (float(parsed.group(index)) for index in range(1, 5))
    time_column, x_column, y_column = _columns_from_header(csv_header)
    return PaperMatch(
        system="lotka_volterra",
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        delta=delta,
        time_column=time_column,
        x_column=x_column,
        y_column=y_column,
        confidence=1.0,
    )


def lotka_paper_text() -> str:
    return (
        "Lotka-Volterra predator-prey model.\n"
        "dx/dt = alpha * x - beta * x * y\n"
        "dy/dt = delta * x * y - gamma * y\n"
        "alpha=1.0 beta=0.1 gamma=1.5 delta=0.075\n"
        "Observed series: Year, Hare, Lynx.\n"
    )


def lotka_csv_text() -> str:
    years = np.arange(1900, 1920, dtype=np.float64)
    t = years - years[0]
    alpha, beta, gamma, delta = 1.0, 0.1, 1.5, 0.075

    def rhs(state: np.ndarray, _time: float) -> list[float]:
        prey, predator = state
        return [
            alpha * prey - beta * prey * predator,
            delta * prey * predator - gamma * predator,
        ]

    path = odeint(rhs, [40.0, 9.0], t)
    rows = ["Year,Hare,Lynx"]
    for year, hare, lynx in zip(years, path[:, 0], path[:, 1], strict=True):
        rows.append(f"{int(year)},{hare:.6f},{lynx:.6f}")
    return "\n".join(rows) + "\n"


def _unescape_pdf_string(raw: str) -> str:
    inner = raw[1:-1]
    return inner.replace("\\(", "(").replace("\\)", ")").replace("\\n", "\n")


def _columns_from_header(csv_header: str | None) -> tuple[str, str, str]:
    names = []
    if csv_header:
        first = csv_header.strip().splitlines()[0]
        names = [item.strip() for item in first.split(",") if item.strip()]
    lowered = {name.lower(): name for name in names}

    def pick(aliases: tuple[str, ...], fallback: str) -> str:
        for alias in aliases:
            if alias in lowered:
                return lowered[alias]
        return fallback

    return (
        pick(("year", "time", "t"), "Year"),
        pick(("hare", "prey", "x"), "Hare"),
        pick(("lynx", "predator", "y"), "Lynx"),
    )
