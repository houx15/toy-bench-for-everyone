import math

import pytest

from scorer_kit.calibration import agreement, cohen_kappa, pearson, spearman


def test_kappa_hand_computed():
    # po = 0.75, pe = 0.5*0.25 + 0.5*0.75 = 0.5  ->  kappa = 0.5
    assert cohen_kappa([1, 1, 0, 0], [1, 0, 0, 0]) == pytest.approx(0.5)


def test_kappa_perfect_and_chance():
    assert cohen_kappa(list("abcab"), list("abcab")) == pytest.approx(1.0)
    # rater b always says "x": no agreement beyond chance
    assert cohen_kappa(["x", "y", "x", "y"], ["x", "x", "x", "x"]) == pytest.approx(0.0)


def test_kappa_constant_identical_raters_defined_as_one():
    assert cohen_kappa(["a"] * 4, ["a"] * 4) == 1.0


def test_quadratic_weighted_kappa_full_reversal_is_minus_one():
    assert cohen_kappa([1, 2, 3], [3, 2, 1], labels=[1, 2, 3], weights="quadratic") == pytest.approx(-1.0)


def test_weighted_kappa_credits_near_misses():
    a, b = [1, 2, 3, 3, 2, 1], [1, 3, 3, 2, 2, 1]
    plain = cohen_kappa(a, b, labels=[1, 2, 3])
    weighted = cohen_kappa(a, b, labels=[1, 2, 3], weights="quadratic")
    assert weighted > plain


def test_kappa_rejects_unknown_labels_and_length_mismatch():
    with pytest.raises(ValueError):
        cohen_kappa([1, 2], [1])
    with pytest.raises(ValueError):
        cohen_kappa([1, 5], [1, 2], labels=[1, 2])


def test_pearson_and_spearman():
    assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    # monotone but non-linear: spearman 1, pearson < 1
    x, y = [1, 2, 3, 4], [1, 4, 9, 100]
    assert spearman(x, y) == pytest.approx(1.0)
    assert pearson(x, y) < 1
    # ties get averaged ranks
    assert spearman([1, 1, 2], [1, 1, 2]) == pytest.approx(1.0)
    assert math.isnan(pearson([1, 1, 1], [1, 2, 3]))


def test_agreement_dispatches_by_kind():
    assert agreement("categorical", ["a", "b"], ["a", "b"])["metric"] == "kappa"
    assert agreement("ordinal", [1, 2, 3], [1, 2, 3], [1, 2, 3])["metric"] == "weighted_kappa"
    assert agreement("numeric", [0, 1, 2], [0, 1, 3])["metric"] == "pearson"
