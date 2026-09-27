# ADR-008: Customer consent gate and merchant-approval fallback

**Status**: Accepted (M1) · **Date**: 2026-09-27

## Context
Customer-facing messages go out from the merchant's number. Consent data varies: seed customers have specific
scopes (`recall_reminders`, `refill_reminders`, …); all 185 generated customers have only `promotional_offers`;
one seed walk-in has no consent at all. The simulator never pushes customer contexts. Six of the 30 test pairs
are customer-scoped with promotional-only consent.

## Options
| Option | Effect |
|---|---|
| Strict purpose match (scope must name the trigger's purpose) | Blocks most customer triggers, including test pairs; over-strict for an opted-in customer |
| Any opt-in allows any message | Ignores `reminder_opt_in: false` and walk-ins |
| **Opt-in gate + scope-driven framing + merchant-approval fallback** | Sends when the customer opted in; frames to the scope; otherwise asks the merchant |

## Decision
A customer send requires: the CustomerContext exists and belongs to the merchant; `consent.opted_in_at` is set;
`consent.scope` is non-empty; `preferences.reminder_opt_in` is not `false`; a phone is on file. The scope then
shapes framing (promotional-only → lead with the merchant's offer, not a clinical reminder claim). If the gate
fails or the customer context is missing, the trigger becomes a merchant-facing approval message
(`vera_customer_approval_v1`, `send_as: vera`, `customer_id: null`) using only payload facts, e.g. asking whether
to send the reminder with the listed slots. Names are never derived from ids; composite names address the parent;
walk-ins get no customer send.

## Consequences
- Every canonical pair still yields a defensible action.
- The simulator's customer-scoped seed triggers become merchant-facing messages (the scorer sees
  `send_as: vera`), which is the honest behaviour without a customer context.
