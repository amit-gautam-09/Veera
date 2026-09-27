# ADR-012: Free Gemini provider through an OpenAI-compatible gateway

**Status**: Accepted (M11) · **Date**: 2026-09-27 · Amends ADR-002

## Context
No Anthropic API key is available for development or the test window. Amit asked for a free alternative. Free
tiers checked on 2026-09-27: Groq (8K tokens/min, 200K/day on `gpt-oss-120b`: about two compositions a minute),
OpenRouter `:free` (~50 requests/day), Cerebras (~30K TPM but a volatile catalogue), Mistral free plan (~50K TPM,
phone verification, data may be used for training), Google Gemini via AI Studio (Flash-family models, per-project
RPM/RPD limits shown in AI Studio). The bot already degrades to deterministic wording on 429/5xx/timeout, so a
rate-limited provider is acceptable as long as its successful calls are fast.

## Measured on the free key (OpenAI-compatible endpoint, JSON-schema output)
| Model | reasoning_effort | Result |
|---|---|---|
| gemini-3.8-flash | none / low | 503 high demand; then 429 after two calls |
| gemini-3.7-flash, gemini-3.5-flash | minimal / low | 503s and 30 s hangs |
| gemini-flash-latest | none / low | 3.7 s / 10.9 s |
| gemini-2.5-flash | any | 404: no longer available to new users |
| **gemini-3.5-flash-lite** | **low** | **~2.6 s, reliable** (`none` is rejected, `minimal` slower and variable) |

Golden set through the live model (38 cases, `composer_v3`): 36 LLM + 2 repaired, 0 fallbacks, 0 grounding
findings, p50 1.8 s, p90 2.3 s, max case-study similarity 0.26.

## Decision
- Add `OpenAICompatibleGateway` (official `openai` SDK, `max_retries=0`, `response_format` json_schema,
  `reasoning_effort`), selected with `VERA_LLM_PROVIDER=gemini` + `VERA_LLM_API_KEY`; base URL defaults to
  `https://generativelanguage.googleapis.com/v1beta/openai/`. `make_gateway(settings)` is the one factory for the
  app and `bot.py`.
- Gemini defaults: `gemini-3.5-flash-lite`, effort `low`, concurrency 4 (free RPM).
- Prompt `composer_v3` adds rules the smaller model needed: no claims about what customers did, peer averages
  are metro-wide, keep the ask's specifics, natural English with contractions, English-primary merchants get no
  Hindi beyond "ji". Validator V18: customer-facing messages must name the business; V15 now also rejects stray
  Hindi for English-primary merchants.
- Anthropic stays the default provider; switching back is one env var.

## Consequences
- The bot runs with an LLM at zero cost; bursts beyond the free RPM fall back to deterministic wording (by design).
- Free-tier Gemini prompts may be used by Google to improve its products: acceptable for the synthetic challenge
  data only.
- Free-tier model availability churns (2.5 Flash vanished for new keys; 3.8 Flash quota is tiny), so the model is
  configurable and should be re-probed before the judging window.
- The local judge can use the same key (`JUDGE_LLM_PROVIDER=gemini`), sharing the project's rate limit.
