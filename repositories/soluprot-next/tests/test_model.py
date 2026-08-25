import numpy as np
import pandas as pd
import pytest

from soluprot_core.model import ExportedGradientBoostingModel


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("data/models/grad_clf_v1_tc/model.json", 0.46970221),
        ("data/models/grad_clf_v1_tc_notmhmm/model.json", 0.45134219),
    ],
)
def test_exported_model_predicts_from_feature_means(path, expected):
    model = ExportedGradientBoostingModel.load(path)
    row = {feature: model.features_mean[feature] for feature in model.order}

    prediction = model.predict(pd.DataFrame([row]))[0]

    assert prediction == pytest.approx(expected, abs=1e-8)


def test_exported_model_uses_expected_feature_counts():
    full_model = ExportedGradientBoostingModel.load("data/models/grad_clf_v1_tc/model.json")
    no_tmhmm_model = ExportedGradientBoostingModel.load(
        "data/models/grad_clf_v1_tc_notmhmm/model.json"
    )

    assert len(full_model.order) == 96
    assert len(no_tmhmm_model.order) == 94
    assert any(feature.startswith("tmhmm_") for feature in full_model.order)
    assert not any(feature.startswith("tmhmm_") for feature in no_tmhmm_model.order)


def test_exported_model_uses_float32_threshold_semantics():
    threshold = np.float64(np.float32(0.1))
    feature_value = np.nextafter(threshold, np.inf)
    model = ExportedGradientBoostingModel(
        feature_order=["x"],
        features_mean={"x": 0.0},
        classes=np.asarray([0, 1]),
        soluble_class=1,
        learning_rate=1.0,
        init_prior=0.0,
        scaler_mean=None,
        scaler_scale=None,
        offsets=np.asarray([0, 3]),
        children_left=np.asarray([1, -1, -1]),
        children_right=np.asarray([2, -1, -1]),
        features=np.asarray([0, -2, -2]),
        thresholds=np.asarray([threshold, -2.0, -2.0]),
        values=np.asarray([0.0, -10.0, 10.0]),
    )

    prediction = model.predict(pd.DataFrame([{"x": feature_value}]))[0]

    assert prediction < 0.001
