"""Near-duplicate de claims (A0) : clustering glouton par cosinus."""

from src.services.analysis.claim_embeddings import _greedy_groups


def test_groups_near_identical_vectors():
    a = [1.0, 0.0, 0.0]
    b = [0.99, 0.02, 0.0]   # quasi colinéaire à a
    c = [0.0, 1.0, 0.0]     # orthogonal → à part
    groups = _greedy_groups([(1, a), (2, b), (3, c)], threshold=0.92)
    assert groups == [[1, 2]]            # a&b regroupés ; c seul → écarté


def test_no_group_when_all_distinct():
    v = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    groups = _greedy_groups([(i, x) for i, x in enumerate(v)], threshold=0.9)
    assert groups == []                  # aucun doublon


def test_three_in_one_group():
    base = [1.0, 0.0]
    items = [(1, [1.0, 0.0]), (2, [0.98, 0.02]), (3, [0.97, 0.05])]
    groups = _greedy_groups(items, threshold=0.9)
    assert len(groups) == 1 and sorted(groups[0]) == [1, 2, 3]
