# 00 — Context Digest

Two-page onboarding summary of the challenge and the business behind it. Sources: `reference/challenge/*.md`,
`reference/challenge-page.md`, `reference/research/Magicpin_Due_Diligence_Report.md`. Everything load-bearing
here is verified against those files; see `12-risk-and-ambiguity-register.md` where sources disagree.

## 1. The business
- **magicpin** (Samast Technologies Pvt. Ltd., Gurgaon, founded 2015) is a hyperlocal discovery, rewards and
  online-to-offline commerce platform: ~100k merchant partners across 50+ cities (restaurants, salons, gyms,
  dentists, pharmacies, retail). Merchants pay per verifiable conversion, not per click.
- Its growth engine is ONDC (largest seller-side app on the network) and, from 2026, **Vera**: an AI assistant
  meant to move revenue from low-margin vouchers toward merchant SaaS. The dossier reports ~500k active merchants
  on Vera by mid-2026 with a 1M target by year-end.
- Why Vera matters to magicpin: every merchant Vera keeps engaged is a merchant whose listing, offers and
  customer re-engagement run through magicpin. Engagement frequency is the product metric.

## 2. What Vera does and where it falls short today
Vera talks to merchants on WhatsApp: Google Business Profile (GBP) upkeep, campaigns, offers, content, and
messages to the merchant's own customers on the merchant's behalf. Live numbers (23–25 Apr 2026): 5–10k merchants
engaged per day, ~4.7 messages per engaged merchant.

Four pain points the challenge asks us to beat:
1. **Auto-reply pollution** — 40–70% of "merchant replies" are WhatsApp Business canned replies; Vera burns 2–3
   turns on each.
2. **Intent-handoff failure** — merchant says "let's do it", Vera keeps qualifying.
3. **Generic copy** — "10% off" instead of service + price ("Haircut @ ₹99").
4. **Low frequency** — functional nudges are rare; curiosity- and knowledge-driven messages are needed for
   3–5 touches a week. Social proof and asking the merchant are the least-used levers.

## 3. The abstraction
`compose(category, merchant, trigger, customer?) → {body, cta, send_as, suppression_key, rationale}` plus
`template_name` / `template_params` for first-touch sends (WhatsApp 24h window).

| Context | Answers | Changes |
|---|---|---|
| Category | How to talk to this kind of business; offers, peer stats, weekly digest, seasonal beats, trends, taboos | Weekly / monthly |
| Merchant | Who this business is and how it is doing: identity, subscription, 30d performance + 7d deltas, offers, history, customer aggregate, signals, review themes | Daily / real time |
| Trigger | Why message now: kind, scope, payload, urgency 1–5, suppression key, expiry | Per event |
| Customer | The merchant's customer: identity + language, relationship, state, preferences, consent | Per visit |

`send_as` is `vera` for merchant-facing and `merchant_on_behalf` for customer-facing messages.

## 4. How we are tested
- **HTTP contract** (5 endpoints + optional teardown): `POST /v1/context`, `POST /v1/tick`, `POST /v1/reply`,
  `GET /v1/healthz`, `GET /v1/metadata`. Details: `05-api-contract.md`.
- **Harness flow**: warmup (push 5 categories, 50 merchants, 200 customers, 0 triggers; healthz counts must
  match) → 60 simulated minutes of 5-minute ticks, each followed by up to 5 judge-played reply turns → adaptive
  injection mid-test (new digest items, perf shifts, 15 new triggers, 5 new customers + `recall_due`) → replay
  scenarios for the top 10 (auto-reply ×4, intent transition, hostile then off-topic).
- **Scoring**: 5 dimensions × 10 — specificity, category fit, merchant fit, decision quality / trigger
  relevance ("why now"), engagement compulsion. Adaptation bonus up to +5 per dimension; replay up to +30;
  operational penalties up to −20 (healthz, timeouts, malformed, verbatim repeats, URLs).
- **Limits**: 30 s per call (local simulator: 15 s tick/reply, 10 s context, 5 s healthz), 10 req/s,
  20 actions per tick, 500 KB context payloads.
- **Local simulator** (`judge_simulator.py`) runs on the *seed* files, never pushes customers, and sends
  wall-clock `now`. The real judge injects context we have never seen, so pattern-matching the 30 pairs fails.

## 5. What scores 9–10 (from the case studies, paraphrased)
One primary signal; every number traceable to context; citation on research/compliance claims (none caps the
dimension at 7); owner first name; category vocabulary; customer messages honour language and relationship
state; *judgment* over templating (e.g. advising against a promo when the data says it will underperform);
exactly one low-friction CTA in the last sentence; concise rationale that matches the body. Any fabrication or
verbatim repetition caps every dimension at 5.

## 6. The dataset in one screen
- 5 categories (`dentists`, `salons`, `restaurants`, `gyms`, `pharmacies`), each with voice (`tone`,
  `vocab_allowed`, `vocab_taboo`, salutation examples), 8-item offer catalog, peer stats, 5 digest items,
  patient content library, seasonal beats, trend signals.
- 10 seed merchants (rich), 40 generated (sparse: no offers, history, signals or review themes).
- 15 seed customers (rich), 185 generated (consent scope only `promotional_offers`).
- 25 seed triggers (rich payloads), 75 generated (`payload: {"placeholder": true, "metric_or_topic": kind}`,
  kinds assigned to random merchants).
- 26 trigger kinds; the 30 canonical test pairs cover 18 of them, 13 with placeholder payloads.

## 7. Where to go next
PRD (`01`) for what we are building and the quality bar; TRD (`02`) for how; trigger playbook (`07`) and voice
guide (`08`) for message content; conversation policy (`09`) for replies; register (`12`) for every
contradiction and how we resolved it.
