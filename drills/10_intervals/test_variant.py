from datetime import datetime


def d(day, hour):
    return datetime(2026, 9, day, hour)


ROTA = [
    ("aoife", d(21, 9), d(21, 17)),
    ("bryan", d(21, 16), d(22, 0)),
    ("ciara", d(22, 2), d(22, 9)),
]


def test_coverage_gaps_example(variant):
    assert variant.coverage_gaps(ROTA, d(21, 9), d(22, 9)) == [(d(22, 0), d(22, 2))]


def test_coverage_gaps_at_both_edges_and_unsorted_input(variant):
    shifts = [("bryan", d(21, 14), d(21, 18)), ("aoife", d(21, 10), d(21, 12))]
    assert variant.coverage_gaps(shifts, d(21, 8), d(21, 20)) == [
        (d(21, 8), d(21, 10)),
        (d(21, 12), d(21, 14)),
        (d(21, 18), d(21, 20)),
    ]


def test_coverage_gaps_clips_and_nested_shift(variant):
    shifts = [("aoife", d(20, 0), d(21, 23)), ("bryan", d(21, 10), d(21, 11)), ("x", d(25, 0), d(26, 0))]
    assert variant.coverage_gaps(shifts, d(21, 9), d(22, 0)) == [(d(21, 23), d(22, 0))]


def test_coverage_gaps_no_shifts_and_back_to_back(variant):
    assert variant.coverage_gaps([], d(21, 0), d(22, 0)) == [(d(21, 0), d(22, 0))]
    shifts = [("a", d(21, 0), d(21, 12)), ("b", d(21, 12), d(22, 0))]
    assert variant.coverage_gaps(shifts, d(21, 0), d(22, 0)) == []


def test_double_booked_example(variant):
    assert variant.double_booked(ROTA) == [(d(21, 16), d(21, 17), ["aoife", "bryan"])]


def test_double_booked_handover_is_not_overlap(variant):
    shifts = [("a", d(21, 0), d(21, 12)), ("b", d(21, 12), d(22, 0))]
    assert variant.double_booked(shifts) == []


def test_double_booked_changing_people(variant):
    shifts = [
        ("cian", d(21, 0), d(21, 10)),
        ("aoife", d(21, 2), d(21, 6)),
        ("bryan", d(21, 4), d(21, 8)),
    ]
    assert variant.double_booked(shifts) == [
        (d(21, 2), d(21, 4), ["aoife", "cian"]),
        (d(21, 4), d(21, 6), ["aoife", "bryan", "cian"]),
        (d(21, 6), d(21, 8), ["bryan", "cian"]),
    ]


def test_double_booked_same_person_overlapping_is_not_two_people(variant):
    shifts = [("aoife", d(21, 0), d(21, 10)), ("aoife", d(21, 5), d(21, 12)), ("bryan", d(21, 11), d(21, 14))]
    assert variant.double_booked(shifts) == [(d(21, 11), d(21, 12), ["aoife", "bryan"])]


def test_double_booked_joins_adjacent_same_people(variant):
    # a's second shift starts exactly when the first ends, so a is continuously on with b.
    shifts = [("a", d(21, 0), d(21, 5)), ("a", d(21, 5), d(21, 10)), ("b", d(21, 0), d(21, 10))]
    assert variant.double_booked(shifts) == [(d(21, 0), d(21, 10), ["a", "b"])]
