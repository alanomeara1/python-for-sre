# 10 · Explained: how and why, line by line

Read this in the Study step, and come back to it whenever you're stuck. `reference.py` shows you
*what* to write. This file is *why* it's written that way, so you can rebuild it from scratch
instead of fishing for a memory.

---

## The mental model

Four functions, but only **two ideas**:

```
merge_intervals(intervals)          idea 1: sort, then walk, extending the last window
total_downtime(outages, s, e)       merge -> clip to the window -> sum
availability(outages, s, e)         1 - downtime / window length
concurrent_outages(by_service, n)   idea 2: sweep line over +1/-1 events
```

**Idea 1 (sort and walk)** answers "what is one continuous outage?". **Idea 2 (sweep line)**
answers "how many things are happening at this instant?". Almost every interval question in an
interview is one of those two, or both stacked: `concurrent_outages` uses `merge_intervals` twice,
once on the way in and once on the way out.

**Memory hook: sort-and-walk for ONE timeline, sweep line for MANY timelines.**

Why it matters in the job: this is how a pile of overlapping alerts becomes the single availability
number in an SLO review, and how you answer "were we ever down on two services at once?".

---

## Chunk 1: `merge_intervals`

```python
def merge_intervals(intervals: Iterable[tuple]) -> list[tuple]:
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
```

**Shape: sort → for each, extend the last one or start a new one.**

### Why sort first

The loop only ever compares the current interval with **the last merged one**, `merged[-1]`. That
shortcut is only valid if nothing later can start earlier than something already placed, which is
exactly what sorting by start guarantees. Skip the sort and you'd have to compare each interval
against *all* previous ones, turning an O(n log n) algorithm into O(n²) — and the version in front
of you would simply give wrong answers.

`sorted(intervals)` sorts tuples left to right: by start, then by end as a tie-break. You only need
the start ordering; the end tie-break is harmless.

`sorted()` also takes any iterable and returns a list, so a generator input works with no extra
code. That's `test_merge_empty_and_generator`.

### Why `<=` and not `<`

`(10:00–10:30)` and `(10:30–11:00)` touch but don't overlap. With `<` they stay separate. The drill
defines touching windows as one continuous outage, which matches how monitoring behaves: one
incident that re-fired an alert at the boundary is not two incidents.

### Why `max(merged[-1][1], end)`

The new interval might be **entirely inside** the last one: `(1, 10)` then `(2, 3)`. Assigning `end`
blindly would shrink the merged window to `(1, 3)` and lose seven units of downtime. `max` keeps
whichever end is later. That's `test_merge_contained_interval_keeps_outer_end`.

### Why rebuild the tuple instead of mutating it

Tuples are immutable, so `merged[-1][1] = end` raises `TypeError`. Replacing the whole element,
`merged[-1] = (start_of_last, new_end)`, is the idiom. (A list of lists would let you mutate in
place; tuples are the better default because the result is a value, not a workspace.)

### Rebuilding it from first principles

Say the algorithm out loud, then type what you said:

> "Sort by start. For each interval: does it begin at or before the end of the window I'm currently
> building? If yes, stretch that window's end to whichever end is later. If no, that window is
> finished; start a new one."

---

## Chunk 2: `total_downtime`

```python
def total_downtime(outages, window_start, window_end):
    total = window_start - window_start
    for start, end in merge_intervals(outages):
        start, end = max(start, window_start), min(end, window_end)
        if start < end:
            total += end - start
    return total
```

### `total = window_start - window_start` is the zero trick

This is the line people stare at. It produces **the additive identity of whatever type you're
working in**: `0` for numbers, `timedelta(0)` for datetimes. Starting at a literal `0` works for
epoch seconds and then explodes on datetimes, because `0 + timedelta(...)` raises
`TypeError: unsupported operand type(s) for +: 'int' and 'datetime.timedelta'`.

The rejected alternative is `isinstance(window_start, datetime)` and two code paths. It works, it's
noisier, and it quietly fails for `date`, `numpy` datetimes, or anything else that subtracts
sensibly. Subtracting a value from itself asks the type for its own zero.

### Why merge before summing

Two alerts for one incident overlap. Summing them raw counts the overlap twice and makes your
availability number *worse than reality* — you'd report a breached SLO that never happened. Say
this out loud in an interview: it's the SRE judgement the question is really testing.
`test_total_downtime_numbers_merges_before_summing` checks exactly this: `(10,20)` and `(15,25)`
must total 15, not 20.

### Why clip, and why the `if start < end` guard

`max(start, window_start)` and `min(end, window_end)` cut each outage down to the part that falls
inside the reporting window. An outage that began last month shouldn't put last month's minutes on
this month's budget.

After clipping, an outage **entirely outside** the window comes back inverted — start after end.
Without the guard, `end - start` is negative and you'd *subtract* time from the total, silently
improving your availability figure. A negative duration is the kind of bug that survives review
because the output still looks plausible.

---

## Chunk 3: `availability`

```python
def availability(outages, window_start, window_end) -> float:
    return 1 - total_downtime(outages, window_start, window_end) / (window_end - window_start)
```

- **One line covers both types** because `timedelta / timedelta` returns a plain `float` (true
  division between two timedeltas has been defined since Python 3.2). `timedelta(minutes=43) /
  timedelta(days=30)` is `0.000995…`, which is why this needs no special case for datetimes.
- **`1 - downtime/window` rather than `uptime/window`**: arithmetically identical, but it states the
  SLO definition directly, and it means you never have to compute uptime separately.
- **Honest gap:** a zero-length window raises `ZeroDivisionError`. There's no test for it and the
  reference doesn't guard it. Worth one sentence in an interview ("I'd guard the empty window"),
  and worth not pretending the code does something it doesn't.

---

## Chunk 4: `concurrent_outages`, the sweep line

```python
    events = []
    for windows in outages_by_service.values():
        for start, end in merge_intervals(windows):
            if start < end:
                events.append((start, +1))
                events.append((end, -1))

    events.sort()

    periods = []
    down = 0
    opened_at = None
    for time, delta in events:
        down += delta
        if down >= min_services and opened_at is None:
            opened_at = time
        elif down < min_services and opened_at is not None:
            periods.append((opened_at, time))
            opened_at = None

    return merge_intervals(periods)
```

### The idea

Stop thinking about intervals. Think about **moments when the number of things changes**. Every
outage contributes exactly two such moments: `+1` when it starts, `-1` when it ends. Sort all those
moments, walk them in order, and keep a running count. The count between two consecutive events is
constant, so you only ever need to look at the events themselves.

This is the whole technique. It scales to "how many aircraft are airborne", "how many meeting rooms
do I need", "peak concurrent sessions" — same five lines.

### Why merge each service's own windows first

A flapping service raises two overlapping alerts. Un-merged, that's `+1` and `+1`, and the sweep
thinks two *services* are down. Merging per service first collapses a service's own noise into one
window, so the count really is a count of services. `test_concurrent_outages_service_overlapping_itself_counts_once`
proves it: `api` with `(0,10)` and `(5,15)` plus an unrelated `db` outage must yield nothing.

### Why ends sort before starts at the same instant

`events.sort()` sorts `(time, delta)` tuples. When two events share a timestamp, the tuple
comparison falls through to the second element, and `-1 < +1`, so **every end is processed before
every start at that instant**.

That's what makes `(0,10)` and `(10,20)` not concurrent: at `10` the count drops to 0 before it
rises to 1, so it never reaches 2. It encodes the half-open interval `[start, end)`: an outage
"ending at 10:00" was already over at 10:00. `test_concurrent_outages_touching_is_not_concurrent`
is the check.

**Be honest about this one:** the ordering is a happy accident of choosing `-1` and `+1` as the
deltas. Nothing in the code says "ends first" out loud. The variant does it properly, with named
constants (`START, END = 1, 0`) and an explicit sort key. If you write the implicit version in an
interview, say the sentence — "I'm relying on -1 sorting before +1 here" — so it reads as a decision
rather than luck.

### Why `opened_at` rather than "was the count above the threshold last time?"

`opened_at` does two jobs at once: it's the "am I currently inside a qualifying period?" flag
(`is None` or not), and it remembers where that period began. Two variables collapsed into one, with
no way for them to disagree.

### Why merge the result at the end

Events at the same timestamp are processed one at a time, so the running count can dip below the
threshold and come straight back up at the *same instant*. With `a: (0,10)`, `b: (0,5)`, `c: (5,10)`,
the walk closes a period at 5 and opens another at 5, giving `[(0,5), (5,10)]`. Those are one
continuous period of two-service downtime, so a final `merge_intervals` joins them.
That's `test_concurrent_outages_contiguous_periods_are_merged`.

### Rebuilding the sweep from first principles

> "Every window becomes two events: plus one when it starts, minus one when it ends. Sort them,
> ends first at equal times. Walk with a running count. When the count first reaches the threshold,
> remember where. When it drops below, close that period. Merge the results, because a period can
> close and reopen at the same instant."

---

## When a test fails

| Failing test | What it's telling you |
|---|---|
| `test_merge_overlapping_and_touching` | you used `<` instead of `<=`, so touching windows stayed apart |
| `test_merge_unsorted_and_disjoint` | you forgot `sorted()`, or compared against the wrong merged element |
| `test_merge_contained_interval_keeps_outer_end` | you assigned `end` instead of `max(last_end, end)` |
| `test_merge_empty_and_generator` | you indexed or `len()`-ed the input instead of passing it to `sorted()` |
| `test_total_downtime_numbers_merges_before_summing` | you summed raw outages without merging, double-counting the overlap |
| `test_total_downtime_clips_to_window` | no `max`/`min` clipping, or a missing `if start < end` letting a negative duration through |
| `test_total_downtime_datetimes_returns_timedelta` | you started the total at literal `0` (`TypeError: int + timedelta`) |
| `test_availability` | dividing downtime by the wrong span, or returning uptime instead of the ratio |
| `test_concurrent_outages_two_of_three` | threshold compared with `>` instead of `>=`, or the count not reset |
| `test_concurrent_outages_touching_is_not_concurrent` | starts processed before ends at equal timestamps |
| `test_concurrent_outages_service_overlapping_itself_counts_once` | you didn't merge each service's own windows first |
| `test_concurrent_outages_contiguous_periods_are_merged` | no final `merge_intervals(periods)` |
| `test_concurrent_outages_datetimes_and_zero_length` | no `if start < end` guard, so a zero-length outage emitted `+1`/`-1` |

---

## The variant: what actually changes

On-call rota gaps and double-bookings. Same two ideas, four real differences:

1. **The tuple starts with a name, so plain `sorted()` is wrong.** Shifts are
   `(person, start, end)`, and `sorted(shifts)` would order them *alphabetically by person*. Hence
   `sorted(shifts, key=lambda s: s[1])`. In the main drill the tuple happened to start with the
   time, which is why it got away with a bare `sorted()`. This is the single easiest place to lose
   half an hour.

2. **Gaps are the complement, found with a cursor.** Instead of collecting covered windows, you walk
   a `cursor` that means "everything before here is covered". Each shift either starts after the
   cursor (emit a gap) or doesn't. The `cursor = max(cursor, end)` matters: a short shift nested
   inside a long one would otherwise drag the cursor *backwards* and invent a gap that isn't there.
   And don't forget the tail gap after the loop — the rota can simply stop before the period ends.

3. **The sweep's running state is *who*, not *how many*.** `double_booked` has to report names, so
   the state is a `Counter` of people. Why a Counter and not a set: if one person has two
   overlapping shifts and the first ends, `set.discard(person)` would take them off call entirely
   while they're still on. The Counter decrements to 1, and only `del`s at 0.
   (`test_double_booked_same_person_overlapping_is_not_two_people`.)

4. **Emit the stretch *before* applying the current event.** The people on call during
   `[previous, time)` are whoever the *earlier* events put there. So the loop reports that stretch
   first, then applies `+1`/`-1`. Adjacent stretches with an identical cast are joined
   (`result[-1][1] == previous and result[-1][2] == people`), which is what turns one person's
   back-to-back shifts alongside a colleague into a single overlap rather than two
   (`test_double_booked_joins_adjacent_same_people`).

Also note the explicitness upgrade: `START, END = 1, 0` with `events.sort(key=lambda e: (e[0], e[1]))`
says "ends before starts" in words, instead of leaving it to the sign of the delta.

The judgement call to voice: **run this in CI against the rota file.** A coverage gap should fail a
pull request, not be discovered at 1am when nobody answers the page.
