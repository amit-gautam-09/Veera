# ADR-002: Anthropic `claude-sonnet-5` behind a thin gateway

**Status**: Accepted (M1), latency settings re-measured in M4 · **Date**: 2026-09-27

## Context
The composer must write short, natural Hinglish and English in clinical, retail and operator registers, obey
strict grounding rules, and return parseable output within a ~5 s budget. The spec asked for temperature 0, a
composer model and a separate faster classifier model. Checking current API behaviour (claude-api reference)
showed: Sonnet 5 rejects `temperature`/`top_p` with a 400; it runs adaptive thinking when `thinking` is omitted
(and then `content[0]` can be a thinking block); structured output is `output_config.format` with a JSON schema;
the SDK defaults to a 10-minute timeout with 2 retries, and timeouts are retried.

## Options
| Option | For | Against |
|---|---|---|
| `claude-sonnet-5`, thinking disabled, structured output | Strong prose quality, JSON guaranteed, fast enough without thinking | No sampling control → determinism must come from caching |
| `claude-haiku-4-5` at temperature 0 | Fastest; accepts temperature | Weaker Hinglish and judgment; determinism still not guaranteed by temperature alone |
| `claude-opus-5` | Best quality | Slower and costlier for 20-message ticks |
| Separate Haiku classifier + Sonnet composer for replies | Cheap classification | Two round trips inside a 5 s reply budget |

## Decision
- Composer and reply model: `claude-sonnet-5` (env `VERA_COMPOSER_MODEL`), `thinking={"type": "disabled"}`,
  no sampling parameters, `output_config={"format": {"type": "json_schema", ...}}`, `max_tokens` 600,
  `AsyncAnthropic(max_retries=0)` with the per-call timeout set from the remaining deadline.
- No separate classifier model: rules classify replies; when they are inconclusive, the single reply call
  classifies and composes together.
- `LLMGateway` is a `Protocol` with one Anthropic implementation, so a second provider is a new class, not a
  refactor.

## Consequences
- Determinism is provided by the compose cache (ADR-004), not by sampling settings.
- Effort (`output_config.effort`) is tuned in M4 on measured latency and golden-set quality.
- The simulator wrapper must read the first *text* block when Sonnet 5 is used as the judge model.
