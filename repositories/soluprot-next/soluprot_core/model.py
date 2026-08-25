from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .exceptions import ModelInvalidPath, ModelIsNotCompatible


@dataclass(frozen=True)
class ExportedGradientBoostingModel:
    feature_order: list[str]
    features_mean: dict[str, float]
    classes: np.ndarray
    soluble_class: int | float | str
    learning_rate: float
    init_prior: float
    scaler_mean: np.ndarray | None
    scaler_scale: np.ndarray | None
    offsets: np.ndarray
    children_left: np.ndarray
    children_right: np.ndarray
    features: np.ndarray
    thresholds: np.ndarray
    values: np.ndarray

    @classmethod
    def load(cls, model_path: str | Path) -> "ExportedGradientBoostingModel":
        path = Path(model_path)
        if path.is_dir():
            path = path / "model.json"
        if not path.exists() or path.suffix.lower() != ".json":
            raise ModelInvalidPath()

        try:
            metadata = json.loads(path.read_text())
            arrays = np.load(path.with_name(metadata["arrays"]), allow_pickle=False)
            scaler = metadata.get("scaler")
            return cls(
                feature_order=list(metadata["feature_order"]),
                features_mean={
                    str(k): float(v) for k, v in metadata["features_mean"].items()
                },
                classes=np.asarray(metadata["classes"]),
                soluble_class=metadata["soluble_class"],
                learning_rate=float(metadata["learning_rate"]),
                init_prior=float(metadata["init_prior"]),
                scaler_mean=(
                    np.asarray(scaler["mean"], dtype=np.float64)
                    if scaler is not None
                    else None
                ),
                scaler_scale=(
                    np.asarray(scaler["scale"], dtype=np.float64)
                    if scaler is not None
                    else None
                ),
                offsets=arrays["offsets"].astype(np.int64),
                children_left=arrays["children_left"].astype(np.int64),
                children_right=arrays["children_right"].astype(np.int64),
                features=arrays["features"].astype(np.int64),
                thresholds=arrays["thresholds"].astype(np.float64),
                values=arrays["values"].astype(np.float64),
            )
        except KeyError as exc:
            raise ModelIsNotCompatible() from exc

    @property
    def order(self) -> list[str]:
        return self.feature_order

    def predict(self, features: Any) -> np.ndarray:
        matrix = features[self.feature_order].astype(np.float64).to_numpy(copy=True)
        if self.scaler_mean is not None and self.scaler_scale is not None:
            matrix = (matrix - self.scaler_mean) / self.scaler_scale
        # Exported tree thresholds were generated with float32 prediction
        # inputs; keep that numeric convention for stable model output.
        matrix = matrix.astype(np.float32, copy=False)

        raw = np.full(matrix.shape[0], self.init_prior, dtype=np.float64)
        for tree_index in range(len(self.offsets) - 1):
            start = int(self.offsets[tree_index])
            raw += self.learning_rate * self._predict_tree(matrix, start)

        prob_class_one = _sigmoid(raw)
        if len(self.classes) != 2:
            raise ModelIsNotCompatible()
        if self.soluble_class == self.classes[1].item():
            return prob_class_one
        if self.soluble_class == self.classes[0].item():
            return 1.0 - prob_class_one
        raise ModelIsNotCompatible()

    def _predict_tree(self, matrix: np.ndarray, start: int) -> np.ndarray:
        predictions = np.empty(matrix.shape[0], dtype=np.float64)
        for row_index, row in enumerate(matrix):
            node = 0
            while self.children_left[start + node] != -1:
                feature = self.features[start + node]
                threshold = self.thresholds[start + node]
                if row[feature] <= threshold:
                    node = int(self.children_left[start + node])
                else:
                    node = int(self.children_right[start + node])
            predictions[row_index] = self.values[start + node]
        return predictions


def _sigmoid(raw: np.ndarray) -> np.ndarray:
    out = np.empty_like(raw, dtype=np.float64)
    positive = raw >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-raw[positive]))
    exp_raw = np.exp(raw[~positive])
    out[~positive] = exp_raw / (1.0 + exp_raw)
    return out
