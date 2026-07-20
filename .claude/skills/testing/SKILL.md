---
name: testing
description: Testing and automated bug-fixing discipline for the clinic booking bot. Use when writing tests, running the suite, investigating a failure, or doing the pre-handover verification pass. Covers the fixtures, what must be covered, and the required root-cause-before-fix loop.
---

# Testing

The user tests on two real handsets. Every bug the suite catches is a bug they do not
have to find by hand — so the suite carries the load, and manual testing only verifies
what software cannot: delivery, rendering, and UPI apps opening.

## Running

```bash
.venv/Scripts/python.exe -m pytest -q              # Windows
.venv/bin/python -m pytest -q                      # Linux
pytest tests/test_flow_booking.py -q               # one file
pytest -k "reschedule" -q                          # by name
pytest --cov=clinic_bot --cov-report=term-missing  # coverage
ruff check src tests
```

## Fixtures (`tests/conftest.py`)

Every test gets a throwaway SQLite database seeded from the real `config/clinic.yaml`,
with the clock frozen to **Monday 2026-08-03 09:00**. Never touches the working database.

```python
bot.say("Hi")                  # patient types
bot.tap(ids.BTN_BOOK)          # patient taps a button
bot.pick_row(ids.P_SERVICE)    # patient selects a list row, index=N for the Nth
bot2                           # a second, independent patient
```

The returned `FakeAdapter` holds **only that turn's** messages:
`has_button()`, `row_ids()`, `row_titles()`, `texts()`, `contains()`, `images()`.

## What must stay covered

- Every state transition in `PROJECT_PLAN.md` §3.1, including every fallback
- Exact copy for the wordings the user specified verbatim
- Slot correctness: lunch break, closing time, minimum notice, long services spanning slots
- **Double booking** — the guarantee a clinic cares about most
- Reschedule frees the old slot; cancel frees the slot; refs survive a reschedule
- One patient cannot act on another patient's booking
- Webhook: valid, missing, forged and tampered signatures; replayed deliveries
- Config validation: every mistake an operator can plausibly make
- WhatsApp limits: 3 buttons, 10 rows, 1024-char body, pagination terminating

## The bug-fixing loop — follow it in order

1. **Reproduce.** Run the failing test alone with `-x` for the full traceback.
2. **Find the root cause.** Never patch a symptom. If a test expects the wrong thing,
   fix the *test* and say so — but prove it is the test that is wrong first.
3. **Fix the cause.**
4. **Re-run the whole suite**, not just the failing test.
5. **Add a regression test** if the bug was not already covered.
6. **Record it in `docs/PROGRESS.md`**: symptom, root cause, fix. These entries are the
   most valuable thing in that file.

### Worked example, already in the repo

*Symptom:* every booking test failed after the third message with "session timed out".
*Root cause:* `ConversationSession.updated_at` used `onupdate=datetime.now`. When a save
wrote an unchanged timestamp, SQLAlchemy omitted the column from the UPDATE and `onupdate`
substituted **server wall-clock time** into a column compared against **clinic-timezone**
time. On a UTC server serving an IST clinic that would have expired every session
instantly — a production outage, not a test artifact.
*Fix:* all column defaults routed through `clock.now()`; `onupdate` removed from that
column; regression test in `tests/test_session.py`.

## Before handover

```bash
pytest -q                                   # all green
ruff check src tests                        # clean
bandit -r src -q                            # no high-severity findings
pip-audit                                   # no known CVEs
```

Then work `docs/TWO_PHONE_TEST.md` on real handsets. Do not tell the user it is ready
until the suite is green *and* you have said plainly what has and has not been verified
against real WhatsApp.
