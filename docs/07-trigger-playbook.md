# 07 — Trigger Playbook

One section per trigger kind in the dataset (26) plus a generic handler for kinds we have never seen. The
composer (`06-composer-spec.md`) reads this doc as policy: the **FactSheetBuilder** and the **decision step** in
code apply the rules here; the LLM only writes prose inside the frame this doc sets. Voice details per category
live in `08-category-voice-guide.md`; reply handling after the first message lives in `09-conversation-policy.md`.

Sources: `reference/challenge/expanded/triggers/*.json` (100 triggers), `expanded/test_pairs.json` (30 pairs),
seed files, category JSONs. Every claim about the data below was checked against those files.

## 1. How to read a section
Each kind has the same fields:

| Field | Meaning |
|---|---|
| Scope / send_as | `merchant` → `vera`; `customer` → `merchant_on_behalf` (or the approval path, §4.5) |
| Template / CTA | `template_name` and the CTA the code sets (the LLM never picks the CTA) |
| Intent | What the message must achieve |
| Primary signal | The one fact that answers "why now" (payload field when present) |
| Supporting | At most two extra facts, in priority order |
| Levers | 1–3 compulsion levers from brief §10 |
| Rich payload | Strategy when the payload is real |
| Thin payload | Strategy when `payload.placeholder == true` (never invent the missing specifics) |
| Mismatch | What to do when the kind does not fit the merchant's category |
| On accept | What action mode delivers if the merchant says yes (only things buildable from context) |
| Silent when | Conditions that make the planner skip, beyond the global guards |
| Test pairs | Canonical pairs (T01–T30) that exercise the kind |

Suppression key for every kind: the trigger's `suppression_key` verbatim; if absent,
`{kind}:{merchant_id}:{customer_id or -}:{trigger_id}`.

## 2. Families
| Family | Kinds | Template | send_as | Default CTA | Default levers |
|---|---|---|---|---|---|
| knowledge | research_digest, regulation_change, cde_opportunity, supply_alert, category_seasonal | `vera_knowledge_v1` | vera | binary_yes_no | specificity + citation, reciprocity, effort externalisation |
| performance | perf_dip, perf_spike, seasonal_perf_dip, milestone_reached | `vera_performance_v1` | vera | binary_yes_no | specificity, loss aversion or social proof, effort externalisation |
| account | renewal_due, winback_eligible, dormant_with_vera, gbp_unverified | `vera_account_v1` | vera | binary_yes_no (renewal: binary_confirm_cancel; dormant: open_ended) | loss aversion, single binary commitment, asking the merchant |
| moment | festival_upcoming, ipl_match_today, competitor_opened | `vera_moment_v1` | vera | binary_yes_no | timing/urgency, judgment, effort externalisation |
| reputation | review_theme_emerged | `vera_reputation_v1` | vera | binary_yes_no | specificity (count + quote), reciprocity, effort externalisation |
| conversation | curious_ask_due, active_planning_intent | `vera_conversation_v1` | vera | curious: open_ended; planning: binary_confirm_cancel | asking the merchant, curiosity; planning: effort externalisation |
| customer reminder | recall_due, appointment_tomorrow, chronic_refill_due | `merchant_reminder_v1` | merchant_on_behalf | multi_choice_slot with real slots, else binary_confirm_cancel / binary_yes_no | personalisation, specificity (date/slot/price), low friction |
| customer winback | customer_lapsed_soft, customer_lapsed_hard | `merchant_winback_v1` | merchant_on_behalf | binary_yes_no | no-guilt warmth, a reason to return, zero commitment |
| customer followup | trial_followup, wedding_package_followup | `merchant_followup_v1` | merchant_on_behalf | multi_choice_slot with real slots, else binary_yes_no | continuity, timing window, low friction |
| approval | any customer kind that cannot go to the customer (§4.5) | `vera_customer_approval_v1` | vera, `customer_id: null` | binary_yes_no | effort externalisation, specificity |
| generic | unknown kinds | `vera_generic_v1` | per `trigger.scope` | binary_yes_no | specificity, one binary ask |

`cta: none` is reserved for pure information with nothing to ask (never used by default; a message that asks
nothing usually wastes the send).

## 3. The decision step (code, before any LLM call)
1. **Resolve** trigger → merchant (`trigger.merchant_id`) → category (`merchant.category_slug`) → customer
   (`trigger.customer_id`) → digest item (`payload.top_item_id` / `digest_item_id` / `alert_id`, else §4.3).
2. **Gate**: global guards from `02-TRD.md` (suppression, opt-out, missing merchant/category). Customer kinds also
   pass the consent gate (§4.5) or divert to the approval template.
3. **Classify the payload**: `rich` or `thin` (`payload.placeholder == true`). Thin payloads use the "Thin
   payload" line of the section; nothing the placeholder lacks may appear in the body.
4. **Check fit**: if the kind is outside its native category, apply the mismatch rule (§4.4).
5. **Pick one primary signal** (the section's "Primary signal", falling back down the list) and at most two
   supporting facts, scored by: relevance to the kind > visible to the scorer (§4.7) > merchant-specific over
   category-generic > recency. Ties break on fact-id order (deterministic).
6. **Pick 1–3 levers and the CTA** from the section. The LLM receives the chosen facts, levers, CTA type,
   language directive and salutation, and writes `opener` / `middle` / `ask` + `rationale`.
7. **Restraint**: if steps 3–5 leave no defensible primary signal, skip and log `no_hook`.

## 4. Shared strategies (referenced by the sections)

### 4.1 Hard content rules (every kind)
- Every digit-run in the body traces to a fact: a context value, a code-derived value (percent from a ratio,
  gap vs peer, sum of two counts), an effort integer ≤ 10 ("2-min read", "3 posts"), or the merchant's own inbound
  text. The validator enforces it.
- **No clock arithmetic.** The simulator's `now` is wall-clock (Sept 2026) while payload dates sit in
  Apr–Jun 2026. Quote the explicit payload date ("Diwali on 31 Oct") instead of a duration ("in 188 days"), even
  when the payload supplies `days_until`. "Tomorrow" / "today" / "tonight" are allowed only when the kind itself
  asserts them (`appointment_tomorrow`, `ipl_match_today`).
- **Payload beats digest** when they disagree about the same event (atorvastatin: trigger says `MfrZ`, digest
  says "manufacturer X" → write MfrZ). Cite the digest's `source` as given.
- Merchant active offers are "yours"; catalog offers only ever appear as a suggestion ("want me to set up
  Hair Spa @ ₹499?"). Customer-facing bodies never quote a catalog offer the merchant does not run.
- No URLs, no taboo phrases (`voice.vocab_taboo`, parenthetical stripped), no snake_case or field names
  (`ctr_below_peer_median`, `lapsed_180d_plus`, `placeholder`, `trigger`).
- Never take a name from an id. `"Aanya (parent: Sneha)"` → address Sneha about Aanya;
  `"(walk-in, no profile)"` → no customer send.

### 4.2 Metric selection for thin performance triggers (S-PERF)
Generated perf triggers carry no metric, and their merchant deltas often contradict the kind (T25's "perf_dip"
merchant has views +8% and calls +2%; one perf_spike merchant has both deltas negative). Rule:
1. `perf_dip`: take the most negative of `delta_7d.views_pct` / `calls_pct` / `ctr_pct`. If none is negative, take
   the largest shortfall vs the category peer average (`calls` vs `avg_calls_30d`, `views` vs `avg_views_30d`,
   `ctr` vs `avg_ctr`) and frame it as "the one number lagging", not a dip. If nothing lags, skip (`no_hook`).
2. `perf_spike`: take the most positive delta. If it is under +10%, frame it as a steady rise, not a spike. If
   none is positive, take the largest lead over the peer average and frame it as a strength. Else skip.
3. Deltas render as whole percents (`-0.26` → "26% down"); peer gaps are computed in code and added to the fact
   sheet (e.g. `22 vs 28 calls`, `5.3% vs 2.5% CTR, about 2x`).

### 4.3 Digest item selection (S-DIGEST)
Use the payload's item id when present. Otherwise pick from `category.digest` by kind preference:
research_digest → `research`, then `tech`, then `trend`; regulation_change → `compliance`; cde_opportunity →
`cde`; supply_alert → `alert`, then `supply`; category_seasonal → `seasonal`. Among equals prefer an item whose
`patient_segment`/`summary` matches a merchant signal or aggregate (e.g. `high_risk_adult_cohort`), else list
order. Every digest-backed body names the `source` in-line.

### 4.4 Category-mismatch rules (S-MISMATCH)
Generated triggers assign kinds to random merchants. Native categories and reinterpretations:

| Kind | Native | Reinterpret as (other categories) | Skip when |
|---|---|---|---|
| recall_due | dentists | salons: maintenance visit (touch-up/spa); gyms: return-session check-in; pharmacies: routine check-in (never the word "recall", which reads as a product recall); restaurants: "your usual" re-order | no last_visit and no hook |
| chronic_refill_due | pharmacies | all others: "time for your next visit" reminder anchored on `last_visit` + `visits_total`; never mention medicines or refills | no last_visit |
| appointment_tomorrow | dentists, salons, gyms | restaurants: reservation tomorrow; pharmacies: pickup/delivery tomorrow | — |
| trial_followup | gyms, salons | pharmacies/dentists/restaurants: first-visit check-in ("how was your visit on {last_visit}?") | no last_visit |
| wedding_package_followup | salons | dentists: whitening before the date; gyms: prep programme; others skip | no wedding date in context |
| ipl_match_today | restaurants | others: skip (a match is not a reason to message a dentist) | always outside restaurants |
| category_seasonal, festival_upcoming | all | use the category's own seasonal beats (§4.6) | no matching beat |
| supply_alert, regulation_change, cde_opportunity | category of the digest item | an item from another category's digest: skip | item category ≠ merchant category |

The rationale states the reinterpretation ("recall kind on a gym → framed as a return-session check-in").

### 4.5 Consent gate and the approval path (S-CONSENT)
Customer send requires all of: CustomerContext present; `consent.opted_in_at` set; `consent.scope` non-empty;
`preferences.reminder_opt_in` not `false`; `identity.phone_redacted` not null; `customer.merchant_id ==
trigger.merchant_id`. **Scope decides framing, not eligibility**: if the scope has no purpose match (e.g. only
`promotional_offers` on a reminder kind), lead with value or the merchant's real offer rather than a clinical
reminder. If the gate fails or the customer context is missing (the local simulator never pushes customers),
send `vera_customer_approval_v1` to the merchant instead: `send_as: vera`, `customer_id: null`, built from
payload facts only, no customer name, ending "want me to send it?". If even the payload is a placeholder, skip.

### 4.6 Seasonal beats (S-SEASON)
Choose beats by relevance to the kind, not by the clock: festival kinds take the beat whose note mentions
festival/wedding/Diwali (salons Oct-Dec, pharmacies Oct-Nov, restaurants Oct-Nov, gyms Aug-Oct, dentists Oct-Dec
wedding whitening); dip kinds take the beat that explains a low season (gyms Apr-Jun). Quote the beat's own
`month_range`. When the trigger payload carries an explicit date (festival `date`, `deadline_iso`, match time),
the beat whose `month_range` contains that date's month wins; otherwise ties break on list order. The tick's
`now` is never used (it is wall-clock time in the simulator).

### 4.7 Scorer visibility (S-VISIBLE)
The local scorer sees only: category slug, tone, five taboos, merchant name/owner/locality/languages,
views/calls/ctr, signals, active offer titles, trigger kind/payload/urgency, customer identity. When two facts are
equally strong, prefer the visible one as the primary signal. When a deeper fact is used (digest, peer stats,
aggregates, review themes, history), attribute it in the body: "this week's JIDA digest", "the metro salon
average on magicpin", "your magicpin dashboard shows", "your reviews this month".

### 4.8 Customer placeholder strategy (S-CUST-THIN)
Generated customers have `last_visit: 2026-04-01`, `visits_total`, `state`, `language_pref`, consent
`["promotional_offers"]`, no services. Build from: first name, merchant name + locality, the explicit last-visit
date, the relationship (`visits_total` "5 visits"), the merchant's active offer if any, else one
`patient_content_library` item as a value-first hook. Respect `state`: when the state contradicts the kind
(an `active` customer on a lapse trigger), drop lapse framing and send the value-first version.

## 5. Knowledge family

### research_digest
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_knowledge_v1` / binary_yes_no.
- **Intent**: hand the merchant one finding that matters to *their* practice, cited, with an offer to make it
  usable (patient note, post, SOP line).
- **Primary signal**: the digest item (`payload.top_item_id`): `title`, `source`, `trial_n`, the headline number
  in `summary`.
- **Supporting**: the merchant fact that makes it relevant (`high_risk_adult_count`, a matching signal, the
  service mix they asked about in history); peer stat only if it sharpens relevance.
- **Levers**: specificity + citation, reciprocity ("I'll turn it into…"), curiosity.
- **Rich payload**: lead with the finding in one sentence, tie it to their cohort, cite `source` (e.g. "JIDA Oct
  2026, p.14"), offer one deliverable.
- **Thin payload** (5 of 6): S-DIGEST picks the item; everything else identical. If the category digest has no
  research/tech/trend item, skip.
- **Mismatch**: digest is per category, so none; never cite another category's item.
- **On accept**: the item's `summary` + `actionable` rewritten in plain words inline, plus a 3–4 line patient
  WhatsApp draft built from the summary (or the closest `patient_content_library` item). Never "sending the PDF".
- **Silent when**: the same item id was already sent to this merchant.
- **Test pairs**: none (golden set adds `trg_001_research_digest_dentists`).

### regulation_change
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_knowledge_v1` / binary_yes_no.
- **Intent**: make sure the merchant knows the rule, the deadline and the one check they must do.
- **Primary signal**: the compliance digest item (`top_item_id`): the before/after values in `summary`, the
  effective date (`payload.deadline_iso`), `source`.
- **Supporting**: what passes vs fails (from `summary`), the `actionable` line.
- **Levers**: loss aversion (deadline), specificity + citation, effort externalisation (checklist).
- **Rich payload**: rule → numbers → date → who is affected → offer a 1-page audit checklist. Clinical, calm, no
  alarm. Quote dates as dates.
- **Thin payload**: none in data; if one appears, S-DIGEST with `compliance`, else skip.
- **Mismatch**: item category ≠ merchant category → skip.
- **On accept**: a checklist from `actionable` + `summary` (e.g. "confirm film speed / sensor type, record it
  in your SOP, re-check before {date}").
- **Silent when**: no compliance item resolvable.
- **Test pairs**: T30 (dentists, Dr. Meera, DCI radiograph circular).

### cde_opportunity
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_knowledge_v1` / binary_yes_no.
- **Intent**: a professional-development invite worth their evening.
- **Primary signal**: the cde item (`payload.digest_item_id`): title, date/time, credits (`payload.credits`),
  fee line (`payload.fee` / item `actionable`).
- **Supporting**: link to the merchant's stated interest (Dr. Meera asked for whitening and aligner posts, and
  the IDA session covers digital impressions / CAD-CAM); speaker from `summary`.
- **Levers**: curiosity, specificity, low-cost commitment ("want me to block the evening?").
- **Rich payload**: what, when (quoted date and time), credits, cost for them, one reason it fits their work.
- **Thin payload**: none in data; S-DIGEST `cde` else skip.
- **Mismatch**: skip if the item belongs to another category.
- **On accept**: a calendar-style summary (title, date, time, credits, fee rule) and a note on how the topic
  links to their practice; no registration link.
- **Silent when**: the cde item cannot be resolved. Event dates are not compared with the clock for listed
  triggers (they are authoritative, TRD B6).
- **Test pairs**: T06 (dentists, Dr. Meera, IDA webinar, 2 credits).

### supply_alert
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_knowledge_v1` / binary_yes_no.
- **Intent**: urgent, precise, calm: which batches, why, what to do today.
- **Primary signal**: `payload.molecule`, `affected_batches`, `manufacturer` (payload wins over the digest's
  "manufacturer X").
- **Supporting**: alert `summary` (sub-potency, no safety risk beyond suboptimal LDL control), `source`
  (CDSCO alert); the merchant's `chronic_rx_count` as the pool to screen (never an invented "N affected").
- **Levers**: urgency + specificity, bounded risk framing, effort externalisation (customer note + pickup flow).
- **Rich payload**: batch numbers verbatim; one line on risk; one line on the action; offer to draft the
  customer note. History matters: m_009 already said "Yes send me the list please" → acknowledge and move to the
  next step, do not re-pitch.
- **Thin payload**: none in data; skip rather than generalise a recall.
- **Mismatch**: non-pharmacy merchant → skip.
- **On accept**: customer WhatsApp draft (batches, "please bring the strip back for replacement", no alarm) +
  a 3-step counter workflow from `actionable`.
- **Silent when**: never for urgency 5 unless opted out.
- **Test pairs**: none (golden set adds `trg_018_supply_atorvastatin_recall`).

### category_seasonal
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_knowledge_v1` / binary_yes_no.
- **Intent**: a timely stocking / positioning move for the season.
- **Primary signal**: `payload.trends` rendered as the numbers they carry (`ORS_demand_+40` → "ORS +40%").
- **Supporting**: the seasonal digest item's `actionable` (shelf move), one merchant offer that fits (Free Home
  Delivery > ₹499).
- **Levers**: timing, specificity, effort externalisation (customer note draft).
- **Rich payload**: 3–4 numbers max, one shelf action, one offer to draft a customer-facing note.
- **Thin payload**: S-SEASON beat + S-DIGEST `seasonal` item; no invented percentages.
- **Mismatch**: none (beats are per category).
- **On accept**: a short customer note built from the matching `patient_content_library` item (pharmacies:
  summer first-aid) + the merchant's real offer.
- **Silent when**: no seasonal item or beat.
- **Test pairs**: T05 (pharmacies, Apollo Health Plus, summer demand shift).

## 6. Performance family

### perf_dip
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_performance_v1` / binary_yes_no.
- **Intent**: name the drop, give the most likely lever from data, offer to do it.
- **Primary signal**: `payload.metric`, `delta_pct`, `window`, `vs_baseline`.
- **Supporting**: a signal that plausibly explains it (`unverified_gbp`, `stale_posts`, `no_active_offers`), a
  peer gap computed in code.
- **Levers**: loss aversion, specificity, effort externalisation.
- **Rich payload**: "calls down 50% this week against a baseline of 12" → one likely factor stated as a
  possibility, not a diagnosis → one fix Vera can start. If renewal is also near (Bharat: 12 days), mention only
  if it is the fix, never as a second CTA.
- **Thin payload** (5 of 6): S-PERF. Contradictory deltas (T25) → "the one number lagging" peer-gap framing.
- **Mismatch**: none.
- **On accept**: a GBP post draft using the merchant's active offer, or a suggested catalog offer clearly marked
  as a suggestion; or the verification steps if unverified.
- **Silent when**: S-PERF finds nothing lagging.
- **Test pairs**: T24 (dentists, Bharat, calls -50%), T25 (salons, The Beauty Bar, thin + contradictory).

### perf_spike
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_performance_v1` / binary_yes_no.
- **Intent**: turn momentum into bookings while it lasts.
- **Primary signal**: `payload.metric`, `delta_pct`, `vs_baseline`, `likely_driver`.
- **Supporting**: the offer that converts the extra demand; the driver content (kids yoga post).
- **Levers**: curiosity, timing, effort externalisation.
- **Rich payload**: number + driver → one move that captures it (reply script for callers, pinned offer).
- **Thin payload**: S-PERF (T27 Sunrise: calls +5% is a steady rise, and its bigger lever is the unverified
  profile / no offers, used as the supporting fact).
- **Mismatch**: none.
- **On accept**: a 3-line reply script for incoming calls/chats with the real offer, or a GBP post draft.
- **Silent when**: S-PERF finds no positive metric or lead.
- **Test pairs**: T26 (gyms, Zen Yoga, calls +15%), T27 (pharmacies, Sunrise Medicos, thin).

### seasonal_perf_dip
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_performance_v1` / binary_yes_no.
- **Intent**: pre-empt panic: the dip is seasonal, here is where to spend effort instead.
- **Primary signal**: `payload.metric`, `delta_pct`, `is_expected_seasonal`, `season_note`.
- **Supporting**: the matching seasonal beat / digest item (gyms Apr-Jun lowest acquisition window, "pause
  acquisition spend in May"), member count and churn from `customer_aggregate`.
- **Levers**: reassurance + judgment, specificity, effort externalisation (retention play).
- **Rich payload**: the number, why it is normal (cited beat), the retention move for their members, one offer
  to draft it. Avoid echoing any case-study phrasing; build from PowerHouse's own `monthly_churn_pct` 10% vs peer
  8% as the reason retention is the right focus.
- **Thin payload**: none in data; if thin, S-PERF + S-SEASON, else skip.
- **Mismatch**: none.
- **On accept**: a member-retention WhatsApp draft (attendance nudge) using the merchant's real offer.
- **Silent when**: `is_expected_seasonal` false → treat as perf_dip.
- **Test pairs**: none (golden set adds `trg_014_seasonal_acquisition_dip_powerhouse`).

### milestone_reached
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_performance_v1` / binary_yes_no.
- **Intent**: celebrate, then convert the moment into the next step (reviews, post).
- **Primary signal**: `payload.metric`, `value_now`, `milestone_value`, `is_imminent`.
- **Supporting**: what customers praise (top positive review theme), the offer they are known for.
- **Levers**: social proof, momentum, effort externalisation (review-request message).
- **Rich payload**: "145 reviews, 5 away from 150" → a review-request note for regulars built on their best
  theme (thali quality).
- **Thin payload** (5 of 6): never invent a milestone number. Use the merchant's strongest real lead over peers
  (T23 Pizza Spot: CTR 5.3% vs 2.5% restaurant average) framed as "a number worth showing off", then the same
  review/post ask.
- **Mismatch**: none.
- **On accept**: review-request WhatsApp draft + a GBP post draft celebrating the number.
- **Silent when**: no positive number at all.
- **Test pairs**: T22 (restaurants, Mylari, 145→150 reviews), T23 (restaurants, Pizza Spot, thin).

## 7. Account family

### renewal_due
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_account_v1` / binary_confirm_cancel.
- **Intent**: renew before the lapse, framed by what the plan keeps working.
- **Primary signal**: `payload.days_remaining`, `plan`, `renewal_amount` (Bharat: 12 days, Pro, ₹4,999).
- **Supporting**: one thing the plan currently protects (their views/calls, profile upkeep); a dip if present.
- **Levers**: loss aversion, single binary commitment.
- **Rich payload**: days + plan + amount → what stops if it lapses (only features evidenced in context) →
  "Reply CONFIRM and I'll raise the renewal".
- **Thin payload** (5 of 6): use `merchant.subscription` (`status`, `plan`, `days_remaining`). No amount → never
  quote a price. Expired subscription → reactivation framing with `days_since_expiry`.
- **Mismatch**: none.
- **On accept**: confirmation of plan + amount exactly as in payload/subscription, and what happens next
  ("you'll get the payment request on this number"); nothing invented.
- **Silent when**: subscription `active` with no days/amount anywhere → skip (`no_hook`).
- **Test pairs**: none (golden set adds `trg_005_renewal_due_bharat`).

### winback_eligible
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_account_v1` / binary_yes_no.
- **Intent**: show a lapsed subscriber what they are losing, with a low-effort way back.
- **Primary signal**: `payload.lapsed_customers_added_since_expiry`, `days_since_expiry`, `perf_dip_pct`.
- **Supporting**: `customer_aggregate.lapsed_90d_plus`, the calls delta.
- **Levers**: loss aversion, curiosity ("want to see who?"), single binary commitment.
- **Rich payload**: one loss number (24 customers lapsed since the plan paused), one performance number, an
  offer to restart with one quick win. History shows the last expiry note got no reply → do not repeat it.
- **Thin payload**: none in data; use `subscription.days_since_expiry` + deltas, else skip.
- **Mismatch**: none.
- **On accept**: a win-back WhatsApp draft for lapsed customers using a suggested catalog offer (marked as
  suggestion) + the reactivation step.
- **Silent when**: subscription is active (kind no longer true).
- **Test pairs**: none (golden set adds `trg_009_winback_glamour`).

### dormant_with_vera
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_account_v1` / open_ended.
- **Intent**: restart the conversation with something useful or a question, not a pitch.
- **Primary signal**: one fresh, merchant-specific number (a delta, a peer gap, a lapsed-customer count).
- **Supporting**: `payload.days_since_last_merchant_message` and `last_topic` (to avoid repeating it).
- **Levers**: reciprocity, asking the merchant, curiosity.
- **Rich payload** (T16 Glamour): last topic was subscription expiry with no reply → lead with their customers
  (180 lapsed 90d+) and ask a simple question about them; no renewal pitch.
- **Thin payload** (T17 Chai Point Cafe): no history → the most striking delta (calls -21% this week) + an
  asking-the-merchant question about what changed; no invented reasons.
- **Mismatch**: none.
- **On accept / reply**: whatever the reply points at, routed through `09-conversation-policy.md`.
- **Silent when**: opted out; or the merchant replied within the history window (kind not true).
- **Test pairs**: T16 (salons, Glamour Lounge), T17 (restaurants, Chai Point Cafe, thin).

### gbp_unverified
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_account_v1` / binary_yes_no.
- **Intent**: get the profile verified; it gates everything else.
- **Primary signal**: `payload.verified: false`, `verification_path`, `estimated_uplift_pct` (as a magicpin
  estimate, "about 30%").
- **Supporting**: `identity.verified`, their current views/calls (what the uplift would apply to).
- **Levers**: loss aversion, effort externalisation (Vera walks them through it).
- **Rich payload**: why it matters in one line, the uplift estimate attributed, the path (postcard or phone call),
  offer to start it.
- **Thin payload**: none in data; if thin, use `identity.verified == false` only; skip if verified.
- **Mismatch**: none.
- **On accept**: step list for the named path (request, wait for code, enter code), plus what Vera does after.
- **Silent when**: `identity.verified` is true.
- **Test pairs**: T20 (pharmacies, Sunrise Medicos).

## 8. Moment family

### festival_upcoming
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_moment_v1` / binary_yes_no.
- **Intent**: get a festival-ready offer or post live early.
- **Primary signal**: `payload.festival`, `date` (quoted as a date; ignore `days_until`).
- **Supporting**: the category beat for the season (S-SEASON), the merchant's active offer, or one catalog
  suggestion that suits the festival (salons: Bridal Trial @ ₹999).
- **Levers**: timing, effort externalisation, social proof via the beat's multiplier ("bookings 4x baseline").
- **Rich payload** (T18 Studio11, Diwali 31 Oct): date + season beat + one ready deliverable. Their last message
  (bridal searches) got no reply → different angle.
- **Thin payload** (5 of 6): never name a festival. Use the S-SEASON beat whose note mentions festival (gyms:
  Aug-Oct festival/wedding-prep window) and the merchant's offer, else a catalog suggestion.
- **Mismatch**: `category_relevance` in payload excludes the merchant's category → lean on the category beat;
  if none mentions festival/wedding, skip.
- **On accept**: GBP post + WhatsApp broadcast draft with the real or suggested offer and the quoted date.
- **Silent when**: no festival in payload and no festival beat for the category.
- **Test pairs**: T18 (salons, Studio11, Diwali), T19 (gyms, Bend & Burn, thin).

### ipl_match_today
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_moment_v1` / binary_yes_no.
- **Intent**: an informed call for tonight, including advising against the obvious promo when data says so.
- **Primary signal**: `payload.match`, `venue`, `match_time_iso` (render the local time), `is_weeknight`.
- **Supporting**: the IPL digest item (Saturday matches -12% covers, weeknights +18%, magicpin order data);
  the merchant's delivery vs dine-in split (180 vs 95 orders, a code-derived share); their active offer's days.
- **Levers**: judgment/contrarian insight, loss aversion, effort externalisation.
- **Rich payload** (T21 SK Pizza, Saturday): the offer runs Tue-Thu, so do not stretch it to Saturday; lean
  into delivery, which already carries most orders, and keep an eye on the late-delivery reviews before pushing
  volume. One deliverable (delivery-night post or a suggested Match-night Combo @ ₹399, marked as suggestion).
- **Thin payload**: none in data; skip without match details.
- **Mismatch**: non-restaurant → skip.
- **On accept**: the post/story text with the chosen offer and match time; no invented discount.
- **Silent when**: outside restaurants; merchant opted out.
- **Test pairs**: T21 (restaurants, SK Pizza Junction, DC vs MI).

### competitor_opened
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_moment_v1` / binary_yes_no.
- **Intent**: a calm competitive read and one differentiating move, never a price war by default.
- **Primary signal**: `payload.competitor_name`, `distance_km`, `their_offer`, `opened_date`.
- **Supporting**: the merchant's own comparable offer and strengths (positive review theme, cohort, CTR vs peer).
- **Levers**: curiosity, loss aversion, judgment.
- **Rich payload** (T09 Dr. Meera vs Smile Studio at 1.3 km with cleaning @ ₹199 vs her ₹299): do not match the
  price; lean on what patients already praise ("explains everything patiently", 5 mentions) and a clinical
  differentiator; offer a GBP post or description update.
- **Thin payload** (5 of 6, e.g. T10 Mylari): never name or locate a competitor. Say "a new listing in your
  category has come up near {locality}" only because the kind asserts it; then the merchant's strongest real
  lead (Mylari: 12,400 views, thali offer, 22 positive thali mentions) and a profile-refresh offer.
- **Mismatch**: none.
- **On accept**: GBP description/post draft that leads with the differentiator and their real offer.
- **Silent when**: never (it is informational), unless opted out.
- **Test pairs**: T09 (dentists, Dr. Meera), T10 (restaurants, Mylari, thin).

## 9. Reputation family

### review_theme_emerged
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_reputation_v1` / binary_yes_no.
- **Intent**: surface a pattern in reviews, what it suggests, and a reply/fix Vera can draft.
- **Primary signal**: `payload.theme`, `occurrences_30d`, `trend`, `common_quote`.
- **Supporting**: an opposing positive theme from `review_themes` that narrows the diagnosis (pizza quality praised
  → the problem is dispatch, not kitchen).
- **Levers**: specificity (count + quote), judgment, effort externalisation.
- **Rich payload**: count, quote verbatim in quotes, one-line read, offer to draft replies.
- **Thin payload** (5 of 6): use `merchant.review_themes` (highest `occurrences_30d`, negative first). Generated
  merchants have none → ask the merchant what customers mention most and offer to draft replies (asking lever,
  no numbers). Never invent a theme.
- **Mismatch**: none.
- **On accept**: 2–3 short review replies quoting or addressing `common_quote`, acknowledging without promising
  what the merchant has not committed to.
- **Silent when**: theme is positive-only and nothing to act on → switch to milestone-style social proof or skip.
- **Test pairs**: none (golden set adds `trg_011_review_theme_late_delivery`).

## 10. Conversation family

### curious_ask_due
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_conversation_v1` / open_ended.
- **Intent**: a low-stakes question about their business that Vera turns into content.
- **Primary signal**: `payload.ask_template` (e.g. `what_service_in_demand_this_week`), else a question built on
  their own offers.
- **Supporting**: their offers (make the question guessable: "Haircut @ ₹99 or Hair Spa @ ₹499?"), one number.
- **Levers**: asking the merchant, reciprocity (what Vera will make from the answer), curiosity.
- **Rich payload** (T11 Studio11): a concrete either/or question grounded in their two offers + the deliverable
  Vera builds from the answer. Their last message went unanswered → shorter, easier.
- **Thin payload** (T12 Mylari): a question grounded in their one offer (weekday thali) and volume.
- **Mismatch**: none.
- **On reply**: turn the answer into a GBP post draft + a short reply snippet, delivered in the next turn.
- **Silent when**: a curious ask went unanswered in the last cycle and nothing else changed.
- **Test pairs**: T11 (salons, Studio11), T12 (restaurants, Mylari, thin).

### active_planning_intent
- **Scope / send_as**: merchant / vera. **Template / CTA**: `vera_conversation_v1` / binary_confirm_cancel.
- **Intent**: the merchant already said yes; deliver the draft now (action mode on the first message).
- **Primary signal**: `payload.intent_topic`, `merchant_last_message`, the prior Vera proposal in history.
- **Supporting**: the merchant's real anchor offer/price and volume (Mylari thali @ ₹149, 18 orders/day in
  history; Zen Yoga kids programme proposal: 4 weeks, 3 classes/week, ages 7-12, ₹2,499 from history).
- **Levers**: effort externalisation, momentum, single confirm.
- **Rich payload**: the draft itself in the body (structure, the known numbers), unknowns left as
  merchant-fillable blanks ("rate for 10+ plates: ₹___, you set it"), then "Reply CONFIRM and I'll…". No
  qualifying question. No invented buildings, clients or tier prices.
- **Thin payload**: none in data; skip without an intent topic.
- **Mismatch**: none.
- **On accept**: publish-ready versions (GBP post, WhatsApp broadcast) of the confirmed draft.
- **Silent when**: never while the intent is fresh.
- **Test pairs**: T01 (restaurants, Mylari corporate thali), T02 (gyms, Zen Yoga kids yoga).

## 11. Customer families (send_as `merchant_on_behalf` after the consent gate, §4.5)

### recall_due
- **Template / CTA**: `merchant_reminder_v1` / multi_choice_slot when `payload.available_slots` exist, else
  binary_yes_no.
- **Intent**: book the due visit with real slots and real price.
- **Primary signal**: `payload.service_due`, `due_date`, `available_slots[].label`.
- **Supporting**: `last_service_date`, the merchant's matching active offer (Dental Cleaning @ ₹299), customer's
  `preferred_slots` (only to say the offered slots fit, never to invent new ones).
- **Levers**: personalisation, specificity, low-friction choice.
- **Rich payload** (T28 Priya): name, clinic, "6-month cleaning due on 12 Nov", the two slot labels verbatim,
  the real price, "Reply 1 or 2, or send a time that suits you". Hinglish per `hi-en mix`. No add-ons that are
  not in context.
- **Thin payload** (5 of 6): S-CUST-THIN + S-MISMATCH (T29 Zen Yoga, Diya: return-session check-in using the
  studio's Free Body Composition Analysis offer; English).
- **On reply**: slot number or label → confirm that exact slot; anything else → "we'll confirm a time".
- **Silent when**: consent gate fails and payload is thin (approval path has nothing to say).
- **Test pairs**: T28 (dentists, Priya), T29 (gyms, Diya, thin + mismatch).

### appointment_tomorrow
- **Template / CTA**: `merchant_reminder_v1` / binary_confirm_cancel.
- **Intent**: reduce no-shows: confirm or reschedule.
- **Primary signal**: the appointment itself (time/service from payload when present).
- **Supporting**: merchant name + locality, customer first name.
- **Levers**: low friction, clarity.
- **Rich payload**: service + time from payload, "Reply CONFIRM, or tell us if you need another time".
- **Thin payload** (5 of 5, T03/T04): no time exists → say "your appointment tomorrow at {merchant}" with no time
  or service; confirm/reschedule ask. Hindi/Hinglish for `hi` (T04 Riya), English for `en` (T03 Aditya).
- **Mismatch**: S-MISMATCH (restaurants → reservation, pharmacies → pickup/delivery).
- **On reply**: confirm → short thanks; reschedule → ask for a preferred time, say the merchant will confirm.
- **Silent when**: consent gate fails (transactional, but still needs an opted-in contact).
- **Test pairs**: T03 (salons, Karim's Salon, Aditya), T04 (salons, Beauty Lounge by Renu, Riya).

### chronic_refill_due
- **Template / CTA**: `merchant_reminder_v1` / binary_confirm_cancel.
- **Intent**: refill before stock runs out, with delivery if available.
- **Primary signal**: `payload.molecule_list`, `stock_runs_out_iso` (quoted as a date), `delivery_address_saved`.
- **Supporting**: the merchant's real offers that apply (Senior Citizen 15% OFF for a senior, Free Home Delivery
  > ₹499), `preferences.channel` (via son → address the family member respectfully).
- **Levers**: specificity (molecules, date), convenience, single confirm.
- **Rich payload** (T07 Mr. Sharma, Hindi): molecules named exactly, run-out date, same pack ready, which offers
  apply, "Reply CONFIRM to deliver to the saved address". No invented total, time slot or phone number.
- **Thin payload**: pharmacies → "your regular medicines" with last-visit date only, no molecules.
- **Mismatch** (T08 dentist Bright Smile, Vivaan): S-MISMATCH → "time for your next visit" reminder on the
  last-visit date; never medicines.
- **On reply**: confirm → dispatch confirmation text; dosage change → "please call the pharmacy / share the new
  prescription".
- **Silent when**: consent gate fails and payload is thin.
- **Test pairs**: T07 (pharmacies, Mr. Sharma), T08 (dentists, Vivaan, thin + mismatch).

### customer_lapsed_soft
- **Template / CTA**: `merchant_winback_v1` / binary_yes_no.
- **Intent**: a warm, no-pressure reason to come back.
- **Primary signal**: last-visit date and visit count; any payload specifics.
- **Supporting**: the merchant's active offer, else one `patient_content_library` item.
- **Levers**: warmth, value-first, zero commitment.
- **Rich payload**: none in data.
- **Thin payload** (5 of 5): S-CUST-THIN. State contradictions: T14 (Asha Dental, Reyansh, `churned`) → gentlest
  tone, one easy yes; T15 (Daily Care Medicos, Reyansh, `active`) → no lapse framing, value-first content
  (seasonal tip) in Hinglish.
- **On reply**: yes → offer to share timings / hold a slot; no → thank and close.
- **Silent when**: consent gate fails (approval path would have nothing but a name-less note → skip).
- **Test pairs**: T14 (dentists, thin), T15 (pharmacies, thin).

### customer_lapsed_hard
- **Template / CTA**: `merchant_winback_v1` / binary_yes_no.
- **Intent**: win back a long-gone customer without guilt.
- **Primary signal**: `payload.days_since_last_visit`, `previous_focus`, `previous_membership_months`.
- **Supporting**: the merchant's real no-commitment offer (PowerHouse: 3 FREE Trial Classes), owner first name as
  the sender.
- **Levers**: no-guilt warmth, relevance to their old goal, zero commitment.
- **Rich payload** (T13 Rashmi): gap stated plainly (57 days), her focus (weight loss) linked to the real offer,
  a yes/no to hold a trial class. Never invent a class, schedule or date.
- **Thin payload**: S-CUST-THIN.
- **On reply**: yes → ask which evening suits (her preference is weekday evening), merchant confirms.
- **Silent when**: consent gate fails.
- **Test pairs**: T13 (gyms, PowerHouse, Rashmi).

### trial_followup
- **Template / CTA**: `merchant_followup_v1` / multi_choice_slot with `payload.next_session_options`, else
  binary_yes_no.
- **Intent**: convert a trial into a second visit.
- **Primary signal**: `payload.trial_date`, `next_session_options[].label`.
- **Supporting**: the relevant programme/offer; for a child, address the parent named in `identity.name`.
- **Levers**: continuity, specificity, low friction.
- **Rich payload** (Karthik jr, parent Sumitra, `ta-en mix` → English): trial date, the one next-session label,
  "Reply 1 to book it".
- **Thin payload** (5 of 6): S-CUST-THIN; pharmacies → first-visit check-in (S-MISMATCH).
- **On reply**: confirm the offered label exactly.
- **Silent when**: consent gate fails.
- **Test pairs**: none (golden set adds `trg_017_kids_yoga_trial_followup_karthik`).

### wedding_package_followup
- **Template / CTA**: `merchant_followup_v1` / binary_yes_no.
- **Intent**: move a bride from trial to the next prep step in time.
- **Primary signal**: `payload.wedding_date` (as a date), `trial_completed`, `next_step_window_open`.
- **Supporting**: customer's `preferred_slots` (Saturday), the merchant's real offer that fits prep (Hair Spa
  @ ₹499). No programme price that is not in context.
- **Levers**: timing window, continuity, single binary.
- **Rich payload** (Kavya, English): trial date → "the 30-day skin-prep window is open" → offer to hold a
  Saturday consult.
- **Thin payload**: none in data; skip without a wedding date.
- **Mismatch**: S-MISMATCH.
- **On reply**: yes → ask which Saturday; merchant confirms.
- **Silent when**: consent gate fails.
- **Test pairs**: none (golden set adds `trg_007_bridal_followup_kavya`).

## 12. Generic handler (unknown kinds)
- **Template / CTA**: `vera_generic_v1` / binary_yes_no; send_as from `trigger.scope` (customer scope still
  passes the consent gate).
- **Primary signal**: the most specific scalar in the payload (numbers, dates, names in payload), humanised; if
  the payload is empty or placeholder, the merchant's most notable real number.
- **Rule**: say what happened in plain words (derived from the payload keys, never from the snake_case kind name
  itself), why it matters to this merchant, one offer. Rationale names the kind and says "generic handler".
- **Silent when**: payload has no usable scalar and merchant has no notable number.

## 13. Canonical test-pair coverage
| Pair | Kind | Category / merchant | Payload | Customer | Handling notes |
|---|---|---|---|---|---|
| T01 | active_planning_intent | restaurants / Mylari | rich | — | draft in body, confirm CTA, blanks for unknown rates |
| T02 | active_planning_intent | gyms / Zen Yoga | rich | — | kids programme draft from history, English-primary |
| T03 | appointment_tomorrow | salons / Karim's Salon | thin | Aditya, lapsed_hard, en | no time invented; confirm/reschedule |
| T04 | appointment_tomorrow | salons / Beauty Lounge by Renu | thin | Riya, active, hi | Hindi/Hinglish |
| T05 | category_seasonal | pharmacies / Apollo | rich | — | trend numbers + shelf move + offer |
| T06 | cde_opportunity | dentists / Dr. Meera | rich | — | IDA session, credits, fee, aligner link |
| T07 | chronic_refill_due | pharmacies / Apollo | rich | Mr. Sharma, hi, via son | molecules, date, real offers, no invented total |
| T08 | chronic_refill_due | dentists / Bright Smile | thin | Vivaan, new, en | mismatch → next-visit reminder |
| T09 | competitor_opened | dentists / Dr. Meera | rich | — | no price war; review strength |
| T10 | competitor_opened | restaurants / Mylari | thin | — | no competitor name; profile refresh |
| T11 | curious_ask_due | salons / Studio11 | rich | — | either/or question on real offers |
| T12 | curious_ask_due | restaurants / Mylari | thin | — | question on the thali |
| T13 | customer_lapsed_hard | gyms / PowerHouse | rich | Rashmi, english | real offer (3 free trial classes) |
| T14 | customer_lapsed_soft | dentists / Asha Dental | thin | Reyansh, churned, en | gentlest winback |
| T15 | customer_lapsed_soft | pharmacies / Daily Care | thin | Reyansh, active, hi-en | value-first, no lapse framing |
| T16 | dormant_with_vera | salons / Glamour Lounge | rich | — | no renewal repeat; lapsed customers question |
| T17 | dormant_with_vera | restaurants / Chai Point | thin | — | delta + asking lever |
| T18 | festival_upcoming | salons / Studio11 | rich | — | Diwali on 31 Oct, not "188 days" |
| T19 | festival_upcoming | gyms / Bend & Burn | thin | — | no festival named; Aug-Oct beat |
| T20 | gbp_unverified | pharmacies / Sunrise | rich | — | postcard/phone path, ~30% estimate |
| T21 | ipl_match_today | restaurants / SK Pizza | rich | — | Saturday judgment; offer is Tue-Thu |
| T22 | milestone_reached | restaurants / Mylari | rich | — | 145 → 150 reviews |
| T23 | milestone_reached | restaurants / Pizza Spot | thin | — | no invented milestone; CTR lead |
| T24 | perf_dip | dentists / Bharat | rich | — | calls -50% vs baseline 12 |
| T25 | perf_dip | salons / The Beauty Bar | thin | — | deltas positive → calls 22 vs 28 peer |
| T26 | perf_spike | gyms / Zen Yoga | rich | — | +15% calls, kids yoga driver |
| T27 | perf_spike | pharmacies / Sunrise | thin | — | +5% steady rise; unverified as lever |
| T28 | recall_due | dentists / Dr. Meera | rich | Priya, hi-en mix | real slots, real price |
| T29 | recall_due | gyms / Zen Yoga | thin | Diya, en | mismatch → return check-in |
| T30 | regulation_change | dentists / Dr. Meera | rich | — | DCI circular, dates quoted |

Golden set additions (kinds absent from the 30 pairs): `trg_001_research_digest_dentists`,
`trg_005_renewal_due_bharat`, `trg_011_review_theme_late_delivery`,
`trg_014_seasonal_acquisition_dip_powerhouse`, `trg_018_supply_atorvastatin_recall`,
`trg_017_kids_yoga_trial_followup_karthik`, `trg_007_bridal_followup_kavya`, `trg_009_winback_glamour`.
