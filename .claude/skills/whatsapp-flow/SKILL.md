---
name: whatsapp-flow
description: Rules and constraints for changing the WhatsApp conversation flow — states, buttons, list messages, copy, or the Cloud API payload shape. Use whenever editing flow/, whatsapp/, adding a conversation step, changing patient-visible wording, or debugging why a message fails to send or renders wrongly.
---

# Working on the WhatsApp conversation flow

## Where things live

| Concern | File | Rule |
|---|---|---|
| State machine | `flow/router.py` | Transitions only. No copy, no HTTP. |
| Message building | `flow/views.py` | Pure functions. No DB, no session mutation. |
| Patient-visible copy | `whatsapp/messages.py` | **All** of it. Never inline a string in a handler. |
| Button / row ids | `flow/ids.py` | A wire protocol — see below. |
| States | `flow/states.py` | |
| Cloud API JSON | `whatsapp/cloud_api.py` | |
| Message types + limits | `whatsapp/base.py` | |

## Button and row ids are a wire protocol

Ids travel to WhatsApp and come back on the next inbound message. A patient may tap a
button from a message sent days ago.

- **Never change an existing id value.** Only add new ones.
- Prefixed ids (`svc:`, `doc:`, `date:`, `slot:`, `bk:`, `more:`) carry a payload.
- Always build with `ids.make()` and parse with `ids.parse()`.

## WhatsApp limits are hard, and violating them fails the send

Enforced in `whatsapp/base.py` — structural violations raise, display text is clipped.

| Limit | Value |
|---|---|
| Reply buttons per message | **3** |
| Button title | 20 chars |
| List rows per message, all sections | **10** |
| Row title | 24 chars |
| Row description | 72 chars |
| Body text | 1024 chars |
| Header / footer | 60 chars |

**More than 10 rows must be paginated**, never truncated. Use `views.paginate()`, which
emits 9 rows plus a "Show more" row. **Body text longer than 1024 must be chunked** with
`views.chunk_body()` — a clinic with many services will exceed it.

## Non-negotiable behaviour

- **The bot never dead-ends.** Every state needs a fallback that re-prompts. Use
  `Router._fallback()`, which nudges *and* repeats the current question.
- **Re-check slot availability at confirmation.** Never trust what was listed earlier —
  see `slot_is_free()` and the `SlotTakenError` path.
- **Only ever reply.** Never send an unprompted message. Business-initiated template
  messages are **paid** and would break the ₹0 guarantee.
- **A patient may only act on their own bookings.** `Router._resolve_booking()` checks
  `booking.patient.wa_id`; keep that check.

## Adding a conversation step

1. Add the state to `flow/states.py`.
2. Add copy to `whatsapp/messages.py`.
3. Add a view to `flow/views.py`.
4. Add ids to `flow/ids.py` if new taps are involved.
5. Add the handler to `Router._dispatch`'s table **and** to `_render_current()` so the
   fallback can re-prompt it.
6. Write the flow test before wiring it up.
7. Update `PROJECT_PLAN.md` §3.1 — the diagram is the contract.

## Testing without a phone

`tests/conftest.py` gives a `bot` fixture that drives whole conversations:

```python
bot.say("Hi")                    # patient types
bot.tap(ids.BTN_BOOK)            # patient taps a button
bot.pick_row(ids.P_SERVICE)      # patient selects a list row
out.has_button(...) / out.row_ids() / out.contains(...)
```

Assert on **ids and exact copy**, not on loose substrings.

## Debugging a failing send

1. `MessageTooLargeError` → a limit was exceeded; paginate or chunk.
2. Meta HTTP 400 → inspect the JSON from `build_payload()` against Meta's docs.
3. Buttons arriving as plain text → the number is not a real Cloud API business number.
4. Nothing arrives → check the webhook signature and Meta's delivery log.
