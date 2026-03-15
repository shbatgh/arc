"""Frozen dataclass holding cell-isolation color-filter configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IsolationConfig:
    color_space: str  # "hsv" or "rgb"
    lower: tuple[int, int, int]
    upper: tuple[int, int, int]
    ratio: float  # 0.0-1.0

    def to_cli_args(self) -> list[str]:
        bounds = (
            f"{self.lower[0]},{self.lower[1]},{self.lower[2]},"
            f"{self.upper[0]},{self.upper[1]},{self.upper[2]}"
        )
        args = [f"--isolate-{self.color_space}", bounds]
        if self.ratio != 0.5:
            args.extend(["--isolate-ratio", str(self.ratio)])
        return args
