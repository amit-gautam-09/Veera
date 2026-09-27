# 01 — Product Requirements Document: Vera (challenge build)

| | |
|---|---|
| Owner | Amit Gautam |
| Status | Draft v1 (M1) |
| Related | `02-TRD.md`, `07-trigger-playbook.md`, `08-category-voice-guide.md`, `09-conversation-policy.md` |

## 1. Problem
magicpin's merchants are small operators: a solo dentist in Lajpat Nagar, a family salon in Kapra, a pizza
shop on a trial plan. They do not open dashboards. WhatsApp is where they can be reached, and Vera is magicpin's
way of reaching them: it keeps their Google profile healthy, suggests offers, runs campaigns, and messages their
own customers for them. Vera is also magicpin's bet on recurring merchant SaaS revenue (dossier §7), so the
number that matters is **how often a merchant finds a Vera message worth replying to**.

Production Vera loses that reply in four ways (challenge brief §3):

| # | Failure | Cost |
|---|---|---|
| P1 | Treats WhatsApp Business auto-replies as real replies | 40–70% of "replies" are canned; 2–3 wasted turns each |
| P2 | Keeps qualifying after the merchant commits | Momentum lost at the moment of intent |
| P3 | Generic discount copy | Indian merchants respond to service + price, not "10% off" |
| P4 | Only functional nudges | Too rare to sustain 3–5 touches a week |

This build is Vera's message engine: given the four contexts, decide whether to message, whom, and what to say;
then carry the conversation to an outcome or a graceful exit.

## 2. Goals and non-goals
**Goals**
- G1. Every sent message would pass a strict reviewer on the 9-point bar in §8.
- G2. Zero fabricated facts: every number, date, price, name and citation traces to pushed context.
- G3. Handle live replies well: detect auto-replies fast, switch to action on intent, exit on hostility, stay on
  mission on curveballs.
- G4. Never fail operationally: no timeouts, malformed responses, crashes, repeats or URLs; healthz exact.
- G5. Generalise: fresh digest items, new merchants, new trigger kinds and mid-test version bumps are used
  correctly the first time they appear.
- G6. Deterministic: identical inputs give byte-identical outputs.

**Non-goals**
- Real WhatsApp/Meta sends, template approval, or Kaleyra integration.
- Real magicpin or Google data; scraping of any kind; calls to non-LLM external APIs with payload data.
- A merchant-facing UI, auth, multi-tenant hosting, or horizontal scale beyond one process.
- Executing merchant actions for real (publishing GBP posts, charging renewals). Vera *offers and drafts*; the
  simulated merchant decides.

## 3. Personas
| Persona | What they want from a message | What makes them ignore it |
|---|---|---|
| Dentist (e.g. Dr. Meera, solo practice) | Clinically credible, source-cited, peer tone; things that affect their patients or compliance | Hype, "guaranteed", retail-promo tone |
| Salon owner (e.g. Lakshmi, Studio11) | Practical, warm, service + price, seasonal timing, stylist-level detail | Vague growth talk, "permanent results" |
| Restaurant operator (e.g. Suresh, SK Pizza) | Operator-to-operator numbers: covers, AOV, delivery, match nights; fast deliverables | Anything that costs them a busy evening to read |
| Gym owner (e.g. Karthik, PowerHouse) | Coach-like, disciplined, retention and slot utilisation, seasonality reframes | "Shred in 7 days" style claims |
| Pharmacist (e.g. Ramesh, Apollo Health Plus) | Precise, trustworthy: molecules, batches, compliance dates, refill workflows | Alarmist tone, unsupported "best price" |
| Merchant's customer (patient, member, diner) | A relevant, polite reminder in their language with a concrete slot/price | Guilt-tripping, pushy promos, wrong language |
| The LLM judge (the "buyer") | Evidence the bot picked the single best signal, grounded every fact, and would get a reply | Generic templates, invented data, repetition |

## 4. User stories
Merchant-facing (`send_as: vera`)
- US-1. As a dentist, when a research item relevant to my patient mix lands, I get the finding, the source, and
  an offer to turn it into something I can use.
- US-2. As any merchant, when my calls or views move sharply, I learn the number, the likely reason if the data
  shows one, and one concrete thing Vera can do now.
- US-3. As a merchant with a deadline (renewal, compliance date, festival), I get the date and what I lose by
  missing it, with a single yes/no.
- US-4. As a merchant Vera has not heard from, I get a low-effort question about my business rather than a pitch.
- US-5. As a merchant who says "yes, do it", I immediately receive the draft or the next step, not another
  question.
- US-6. As a merchant who says "stop", I never hear from Vera again in this test window.

Customer-facing (`send_as: merchant_on_behalf`)
- US-7. As a patient due for recall, I get my name, the reason, real slots and the real price, in my language.
- US-8. As a lapsed member, I get a no-guilt, no-commitment way back that fits what I used to come for.
- US-9. As a customer replying "2" or "Wed works", I get a confirmation of exactly that slot.

Jobs to be done: *keep my listing working without thinking about it; tell me what changed and what to do; do
the busywork (drafts, replies, reminders) for me; don't waste my time.*

## 5. Functional requirements
Composition
- **FR-1** Compose `{body, cta, send_as, suppression_key, rationale, template_name, template_params}` from
  category + merchant + trigger (+ customer).
- **FR-2** Each message is built on one primary signal chosen by the trigger playbook (`07`), plus at most two
  supporting facts.
- **FR-3** Every number, ₹ amount, percentage, date, time and proper noun in a body traces to a fact in the fact
  sheet (pushed context or a value derived from it in code). Untraceable output is repaired or replaced.
- **FR-4** Research, compliance, alert and trend claims carry their source as given in the context.
- **FR-5** Placeholder triggers (`payload.placeholder = true`) are composed from merchant + category facts only;
  missing specifics (times, slots, metrics, competitor names) are never invented.
- **FR-6** A trigger kind that does not fit the merchant's category is reinterpreted for the category or
  skipped; the rationale says which.
- **FR-7** Merchant salutation uses the owner's first name when present, with category salutation rules
  (dentists: "Dr. {name}", never "Dr. Dr."). Vera does not re-introduce itself after the first message of a
  conversation.
- **FR-8** Offers: the merchant's active offers are quoted as theirs; catalog offers are only ever *suggested*
  ("want me to set up X @ ₹Y?"), never presented as already running.
- **FR-9** Exactly one CTA, in the final sentence. CTA type is one of `open_ended`, `binary_yes_no`,
  `binary_confirm_cancel`, `multi_choice_slot` (customer booking only), `none` (information-only).
- **FR-10** No URLs in any body. No taboo words from `voice.vocab_taboo`. No internal field names or jargon
  (`ctr_below_peer_median`, `trigger`, `payload`, `lapsed_180d_plus`) in any body.

Tick decisioning
- **FR-11** `/v1/tick` returns 0–20 actions, each with all required fields; empty is a valid answer.
- **FR-12** A trigger is skipped if its suppression key was already sent, the merchant opted out or is in
  cooldown, the customer's consent does not cover the purpose, or required merchant/category context is
  missing. Every skip is logged with a reason.
- **FR-13** At most one new merchant-facing conversation per merchant per tick; ranking by urgency, deadline
  proximity, freshness of recently injected context, then deterministic tie-break.
- **FR-14** `conversation_id` is new, unique and decodable; never reused by a later tick.

Replies
- **FR-15** Classify every inbound (auto-reply, opt-out, hostile, accept, question, off-topic, defer, soft no,
  engaged info, slot selection, unclear) with rules first and an LLM only when rules are inconclusive.
- **FR-16** Auto-replies are detected on first sight by pattern and by repetition per merchant across
  conversations: first → one owner-directed line; second → wait 24h; third → end.
- **FR-17** Explicit acceptance switches to action mode: the reply contains the draft or concrete next step and a
  confirm-style CTA, with no qualifying question.
- **FR-18** Opt-out or hostility → `end` (or one apology line with no pitch) and a 30-day merchant suppression.
- **FR-19** Off-topic asks are declined in one line and the thread returns to the original topic with one CTA.
- **FR-20** "Busy / later" → `wait` with the requested or a sensible duration.
- **FR-21** Questions are answered only from context; unknowns are admitted plainly with the nearest grounded
  next step.
- **FR-22** Customer slot replies confirm only slots present in context; without slots, ask for a preferred
  time and say the merchant will confirm.
- **FR-23** Reply language mirrors the latest inbound when it switches.
- **FR-24** Stop after 3 consecutive bot turns without a genuine reply.
- **FR-25** No body is ever repeated verbatim to the same merchant.

Context and state
- **FR-26** Context pushes are versioned per `(scope, context_id)`: higher replaces atomically; same or lower
  returns 409 `stale_version`; malformed returns 400. Healthz counts equal accepted contexts per scope.
- **FR-27** State survives a process restart (write-through persistence) and is wiped by `/v1/teardown`.
- **FR-28** Unknown conversation ids on `/v1/reply` are accepted and lazily bound to the given merchant.

## 6. Non-functional requirements
| ID | Requirement | Target |
|---|---|---|
| NFR-1 | `/v1/tick` latency, up to 20 actions, cold cache | p99 < 8 s (simulator limit 15 s, official 30 s) |
| NFR-2 | `/v1/tick` latency, warm cache | p99 < 500 ms |
| NFR-3 | `/v1/reply` latency | p99 < 6 s |
| NFR-4 | `/v1/context`, `/v1/healthz`, `/v1/metadata` | p99 < 200 ms |
| NFR-5 | Availability during the test window | No healthz failure; no 5xx |
| NFR-6 | Determinism | Identical inputs → byte-identical outputs (compose cache) |
| NFR-7 | Payloads | Accept up to 500 KB; reject larger with 413-style 400 and a reason |
| NFR-8 | Privacy | Payload data leaves the process only to the LLM provider; wiped on teardown |
| NFR-9 | Throughput | 10 req/s sustained for 45 minutes |
| NFR-10 | Cost guard | Bounded LLM concurrency; token usage logged per call |

## 7. Success metrics
| Metric | Target | Measured by |
|---|---|---|
| Local simulator average (`full_evaluation`) | ≥ 45/50 | `scripts/run_simulator.py` |
| Extended harness average (30 pairs + adversarial variants) | ≥ 45/50 | `eval/` LLM judge |
| Grounding audit findings | 0 untraceable facts | `eval/` grounding auditor |
| Timeouts / malformed / URL / verbatim repeats | 0 | soak + full run logs |
| Internal replay suite | 100% pass | `tests/replay/` |
| Case-study similarity | No body above threshold (0.6 `difflib` ratio) | `eval/` similarity check |

## 8. The message quality bar
A message ships only if all nine hold:
1. **Why now** is explicit and tied to the trigger.
2. It rests on **one** primary signal.
3. Every number, date, price, name and citation exists in context or is derived from it in code.
4. Voice, vocabulary and salutation fit the category; no taboo words.
5. It is personal to this merchant or customer (name, locality, their numbers, offers, history, language).
6. It uses 1–3 fitting compulsion levers and ends with exactly one low-effort CTA.
7. No preamble, hype, URL, re-introduction, repetition or internal jargon.
8. The rationale is concise, honest and matches the body.
9. When nothing is worth saying, the bot stays silent and logs why.

### Original examples (good vs bad)
These are our own; none reuse case-study text.

**Dentists — `regulation_change` (Dr. Meera, Delhi, languages en/hi)**
- Good: "Dr. Meera, DCI ke naye radiograph circular (dated 4 Nov 2026) ke hisaab se IOPA exposure limit 1.5 mSv
  se 1.0 mSv ho rahi hai, effective 15 Dec 2026. E-speed film aur digital RVG pass karte hain, D-speed film
  nahi. Kya main aapke SOP ke liye ek 1-page X-ray audit checklist bana doon?"
  *Why*: one signal (the circular), cited, exact numbers and date, clinical vocabulary, Hinglish, effort
  externalised, single yes/no.
- Bad: "Hi Doctor! Big news on X-ray rules — upgrade your machine today to stay 100% safe! Reply YES for info,
  NO to skip, or CALL for a demo." *Why*: no source or numbers, taboo phrase, hype, three CTAs.

**Salons — digest trend (Studio11, Hyderabad, languages en/hi/te)**
- Good: "Lakshmi, one quick win from this week's magicpin salon data: salons that add "walk-in available" to
  their Google description are seeing 23% more calls in their locality, strongest on weekday afternoons.
  Studio11 already gets 62 calls a month against a 28-call peer average, so this compounds a lead you have.
  Shall I add the line to your profile today?"
  *Why*: attributed stat, her own numbers vs peers (social proof), zero effort, binary CTA.
- Bad: "Boost your salon's visibility with our amazing new feature! Guaranteed glow-up for your business!"

**Restaurants — `review_theme_emerged` (SK Pizza Junction, Delhi)**
- Good: "Suresh ji, pichhle 30 din mein 4 reviews ne late delivery ki baat ki hai — ek ne likha "took 50 mins
  for a 15 min ride". Achhi baat: 8 reviews pizza quality ki tareef karte hain, toh issue kitchen nahi, dispatch
  ka lag raha hai. Main in 4 reviews ke liye short, polite replies draft kar doon?"
  *Why*: exact count and quote from context, a judgment (dispatch, not kitchen) drawn from the two themes,
  concrete deliverable, one ask.
- Bad: "Your reviews could be better. Want to run a 30% off campaign to get more customers?"

**Gyms — `perf_spike` (Zen Yoga Studio, Chennai)**
- Good: "Padma, calls to Zen Yoga are up 15% this week against a baseline of 18, and the lift lines up with
  the kids yoga post. Those are mostly parents asking: want me to draft a 3-line WhatsApp reply you can send
  every parent who calls, with your First Month @ ₹499 offer in it?"
  *Why*: the spike and its driver from the payload, her real offer, curiosity + effort externalisation.
- Bad: "Great news!! Your gym is trending 🔥🔥 Let's go viral with a mega discount!"

**Pharmacies — `category_seasonal` (Apollo Health Plus, Jaipur)**
- Good: "Ramesh ji, summer demand shift shuru ho gaya hai: ORS +40%, sunscreen +38%, anti-fungal +45%, aur
  cold-cough −60%. Counter pe ORS aur sunscreen aage rakhna is hafte ka sabse aasaan kaam hai. Kya main aapke
  customers ke liye ek short summer first-aid WhatsApp note draft kar doon, Free Home Delivery > ₹499 ke saath?"
  *Why*: payload numbers verbatim, a concrete shelf action, his real offer, one ask.
- Bad: "Summer sale! Best prices in town on all medicines, guaranteed!"

**Customer-facing — `customer_lapsed_hard` framing rule (any gym)**
- Good pattern: first name, the merchant's name, the real gap in weeks or the last-visit date, something that
  matches their stated focus, a no-commitment option, one yes/no.
- Bad pattern: guilt ("we miss you, don't give up!"), invented classes or dates, pushy upsell.

## 9. Release criteria
- All FRs covered by at least one automated test; all NFR targets met in the M8 soak.
- Pre-flight checklist in `11-deployment-runbook.md` fully green against the public URL.
- `submission.jsonl` (30 lines), `bot.py`, `conversation_handlers.py`, README consistent with the live bot.

## 10. Out of scope (explicit)
Payments, real template approval, image/PDF generation, multi-process scaling, a UI, analytics dashboards,
long-term storage after the test (teardown wipes everything), and any use of the due-diligence dossier inside
messages.
