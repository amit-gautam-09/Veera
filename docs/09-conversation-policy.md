# 09 — Conversation Policy

How Vera answers `/v1/reply`. Implements FR-15…FR-25 and FR-28. Components: `reply/classifier.py` (§2),
`reply/policy.py` (§3–7), `reply/composer.py` (§8). State model: `03-backend-schema.md` §6.

## 1. Principles
1. **Never burn a turn.** Every `send` either delivers something, answers something, or asks one thing that
   unblocks the next step. No "just checking in".
2. **Commitment switches mode.** When the merchant commits, the next message *contains* the thing (draft, list,
   checklist, confirmation) and a confirm-style CTA. No qualifying questions after a yes.
3. **Exit fast and politely.** Canned auto-replies, opt-outs and hostility end the thread quickly; nothing is
   pitched on the way out.
4. **Answer only from context.** Unknown facts are admitted in one clause, followed by the nearest grounded
   next step.
5. **Inbound replies are always answered** (possibly with `end`); suppression only blocks proactive sends.

## 2. Classification (rules first)
Input is normalised (NFKC, lowercase, emoji → tokens, whitespace collapsed). Rules run in the order below; the
first decisive match wins. Hindi is matched in Roman script and Devanagari.

| Order | Intent | Decisive signals (examples, not exhaustive) |
|---|---|---|
| 1 | `opt_out` | stop, unsubscribe, don't/do not message, stop messaging/sending, remove me, not interested + stop, band karo, mat bhejo, message mat karo, बंद करो, मत भेजो |
| 2 | `hostile` | spam, useless, bothering, irritating, scam, fraud, abuse/profanity list, bakwas, pagal, faltu, बकवास — without a stop phrase (with one → `opt_out`) |
| 3 | `auto_reply` | canned-reply patterns: "thank you for contacting", "thanks for reaching out", "our team will (respond/get back)", "we will get back to you", "currently (unavailable/closed)", "business hours", "this is an automated", "auto-reply", "out of office", "aapki madad ke liye shukriya", "team tak pahuncha", "jald hi sampark", "main ek automated assistant"; **or** the same normalised text already seen from this merchant (any conversation) |
| 4 | `slot_selection` | `from_role == customer` and message is a bare option number (`1`, `2`, `option 2`), a weekday/date/time that matches an offered slot label, or "yes"/"haan" when exactly one slot was offered |
| 5 | `accept` | yes/yeah/ok/okay/sure/done/go ahead/let's do it/do it/please do/send it/confirm/proceed/sounds good/👍, haan, haan ji, ji, theek hai, chalo, kar do, bhej do, bhejo, हाँ, ठीक है — **only if the last bot turn made a proposal** (an offer to draft/send/set up/confirm); otherwise it is `engaged_info` |
| 6 | `defer` | later, busy, not now + time, call me later, tomorrow, in N (min/hours), baad mein, kal, abhi busy, thodi der |
| 7 | `soft_no` | no thanks, not now, maybe later (without a time), not needed, nahi chahiye, abhi nahi, zarurat nahi |
| 8 | `off_topic` | asks outside Vera's scope: GST/tax/ITR/CA/accounting/loan/electricity bill/legal/personal — any request not about listing, offers, customers, campaigns, content, reviews, performance or the trigger topic |
| 9 | `question` | ends with `?`, or starts with what/how/why/when/which/kya/kaise/kitna/kab/kyun |
| 10 | `engaged_info` | substantive statement (≥ 3 words) that answers our question or adds information |
| — | `unclear` | nothing decisive → handled by the LLM reply call, which classifies and composes in one step |

Mixed messages: `opt_out` beats everything; `hostile` + a question ("useless… can you do GST?") is handled as
`hostile` this turn; `accept` + question ("yes, but how much?") is `accept` with the question answered inside
the deliverable.

Language detection per inbound: Devanagari characters or ≥ 2 Hindi function words (06 V15 list) → `hinglish`;
otherwise `english`. The reply uses the detected language (FR-23), overriding the merchant default.

## 3. Policy table
| Intent | Condition | Action | What the `send` contains | State after |
|---|---|---|---|---|
| `auto_reply` | 1st time for this merchant | `send` | One line addressed to the owner: notes it looks like an automatic reply, restates the single ask as a yes/no. No new pitch. CTA `binary_yes_no` | `awaiting_reply` |
| `auto_reply` | 2nd time (any conversation) | `wait` 86400 | — | `waiting` |
| `auto_reply` | 3rd+ time | `end` | — | `ended` |
| `opt_out` | any | `end` | — (rationale records the opt-out) | `ended`; merchant `opted_out` (no proactive sends for the test window) |
| `hostile` | first time | `send` | One apology line + one opt-out path, no pitch ("Sorry for the noise — reply STOP and I won't message again, or tell me what would actually help."). CTA `binary_yes_no` | `awaiting_reply` |
| `hostile` | again, or combined with stop | `end` | — | `ended`; `opted_out` |
| `accept` | last bot turn proposed X | `send` | The deliverable for X (§5) inline + "Reply CONFIRM to …" (or "YES to go live"). CTA `binary_confirm_cancel` | `action_mode` |
| `accept` | in `action_mode` after a deliverable | `send` | Confirmation that it is queued/done as far as Vera can do it, plus the next single step if one exists; otherwise a short close. CTA `none` or `binary_yes_no` | `action_mode` or `ended` |
| `question` | answerable from facts | `send` | Direct answer with the fact, then one next step. CTA `open_ended` or `binary_yes_no` | unchanged |
| `question` | not answerable | `send` | "I don't have that figure; what I can see is <nearest fact>." + one next step | unchanged |
| `off_topic` | any | `send` | One-line decline naming who can help (e.g. "your CA for GST"), then back to the thread's open offer. CTA `binary_yes_no` | unchanged |
| `defer` | explicit time | `wait` parsed seconds (min 900, max 172800) | — | `waiting` |
| `defer` | "tomorrow"/"kal" | `wait` 86400 | — | `waiting` |
| `defer` | vague ("busy", "later") | `wait` 3600 | — | `waiting` |
| `soft_no` | first | `send` | Acknowledge + one lighter alternative, once (e.g. "no worries — want just the 2-line summary instead?") | `awaiting_reply`, `soft_no_count=1` |
| `soft_no` | second | `end` | — | `ended` |
| `engaged_info` | answers our ask | `send` | Use the answer: turn it into the promised artefact (curious-ask → post + reply draft) | `action_mode` |
| `slot_selection` | matches an offered slot | `send` | Confirmation echoing the exact slot label and price from context; what to bring/expect only if in context. CTA `none` | `ended` |
| `slot_selection` | no slot matches / no slots in context | `send` | "Noted — <merchant> will confirm <requested time> shortly." Never states availability. CTA `none` | `awaiting_reply` |
| `unclear` | — | LLM decides within this table | per the chosen row | per row |

Counters:
- **Unanswered nudges** (FR-24): a reply is always answering an inbound, so "unanswered" applies to proactive
  sends. Per merchant, `unanswered_proactive` increments when a tick opens a conversation and resets on any
  genuine (non-auto-reply) inbound from that merchant. At 3, the planner stops proactive sends to the merchant
  (skip reason `unanswered_3`). Inside a conversation, repeated non-genuine inbounds are handled by the
  auto-reply rows above.
- **Auto-reply count** is per merchant across conversation ids (the simulator uses `conv_auto_1…4`), keyed by
  the normalised text hash, plus pattern hits counted under a shared `__pattern__` key.
- A replayed request (same conversation, turn number and message) returns the stored response and changes no
  counter.

## 4. Lazy conversations
A reply on an unknown `conversation_id` creates a conversation bound to `merchant_id`. Its context is seeded
from the merchant's `conversation_history`: the last Vera proposal there becomes the "last bot turn" (so "Ok
let's do it" after "Want me to draft 3 posts?" is an `accept` of that proposal). With no history, the thread
topic is the merchant's strongest current fact (from a fact sheet built with the generic handler), and an
`accept` delivers the generic family deliverable (a GBP post draft built from the merchant's active offer or a
catalog suggestion).

## 5. Action-mode deliverables
What "doing the thing" means per family, using only context. Promises made in the first message are stored in
`promised_deliverable` so the accept delivers exactly that.

| Family | Deliverable on accept |
|---|---|
| knowledge (research, compliance, CDE, supply alert, seasonal) | The digest item's summary in 2–3 lines with its source, the `actionable` as a checklist (compliance) or a patient/customer-facing draft (research) written from the summary; for CDE the date, credits and fee as given. Never "attached PDF". |
| performance (dip, spike, seasonal dip, milestone) | A ready GBP post draft using the merchant's active offer title (or a clearly-labelled catalog suggestion) + where it will go ("as a Google post"), CONFIRM to publish |
| account (renewal, winback, dormant, unverified) | Renewal: plan + amount + days from payload, CONFIRM to raise the renewal request. Unverified: the verification path from payload as numbered steps. Dormant/winback: the single smallest restart step |
| moment (festival, IPL, competitor) | Draft post/offer copy for the moment using an active offer or catalog suggestion; for competitor, a positioning line built from the merchant's own strengths (review themes), never disparaging the competitor |
| reputation (review theme) | 2–3 short public review replies that acknowledge the theme, quoting the `common_quote` context where present, with no promises the data can't back |
| conversation (curious ask, planning) | Planning: a structured draft of the plan using only context numbers plus clearly-marked placeholders the merchant fills ("₹___ per plate"); curious ask: after the merchant's answer, a GBP post + a 3–4 line WhatsApp reply template |
| customer flows | Booking confirmation, reminder confirmation, or "we'll confirm" (§3 `slot_selection`) |

Intent-check compatibility: action-mode bodies naturally contain words like "draft", "here", "confirm",
"next" and avoid qualifying phrasing ("would you", "do you", "can you tell", "what if", "how about"); the
validator adds rule **V17** for action-mode sends: none of those five phrases may appear.

## 6. Language and tone in replies
- Mirror the latest inbound's language; keep the category voice (08).
- No re-introduction (V12). No apology loops: at most one apology per conversation.
- Keep replies shorter than the opening message unless delivering an artefact.

## 7. After `end`
- A new inbound on an ended conversation:
  - auto-reply → `end` again (silent), counters unchanged beyond the per-merchant count;
  - opt-out/hostile → `end`;
  - a genuine question or request → answered once, without pitching; if it is the merchant re-initiating
    ("Hi Vera", "actually, yes") the conversation reopens (`awaiting_reply`) and, for an opt-out, the flag is
    cleared only on an explicit restart phrase ("hi vera", "start", "resume").
- Proactive sends to an opted-out merchant never happen in the test window.

## 8. Reply LLM call (`reply_v1`)
- Used when the policy row needs composed text, or when the rules return `unclear`.
- Input: category voice + language directive, the original trigger's fact sheet, the conversation turns,
  `promised_deliverable`, the policy directive (row from §3) or, if unclear, the whole table, and the inbound.
- Output schema: `{intent, action, body, cta, wait_seconds, rationale}`; code enforces that `action` is allowed
  for the intent and fills `wait_seconds` from §3 when the model omits or exceeds bounds.
- Validation: 06 §5 plus V17; digits from the inbound message join the allowed set.
- Fallback replies (deterministic, per intent): auto-reply owner line, apology line, GST-style decline +
  redirect, generic "here's the draft" built from the fallback composer, slot confirmation from the slot label.
- Deadline 5 s.

## 9. Scenario walk-throughs (expected behaviour)
| Scenario | Turn-by-turn |
|---|---|
| Auto-reply hell (simulator: 4 conversation ids, same text) | T1 `send` owner line → T2 `wait` 86400 → T3 `end` → T4 `end` |
| Intent transition ("Ok lets do it. Whats next?") | `send` with the drafted artefact + "Reply CONFIRM …", CTA `binary_confirm_cancel` |
| Hostile ("Stop messaging me. This is useless spam.") | `end`; merchant opted out |
| Abuse without stop, then "can you help with GST?" | T1 apology + opt-out path → T2 GST decline + redirect to the open offer |
| "Busy right now, message later" | `wait` 3600 |
| Customer "2" after two slots | `send` confirming slot 2's exact label and price |
| Merchant switches to Hindi | Reply in Hinglish from that turn on |
| Three proactive sends to a merchant, none answered | No 4th proactive send (planner skip `unanswered_3`) |
