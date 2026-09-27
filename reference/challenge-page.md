magicpin AI Challenge \| Build Vera Better

[Challenge](https://partners.magicpin.com/vera/ai-challenge/#challenge) [Rubric](https://partners.magicpin.com/vera/ai-challenge/#rubric) [Examples](https://partners.magicpin.com/vera/ai-challenge/#examples) [Testing](https://partners.magicpin.com/vera/ai-challenge/#testing) [Package](https://partners.magicpin.com/vera/ai-challenge/#package) [Submit](https://partners.magicpin.com/vera/ai-challenge/#submit) [FAQ](https://partners.magicpin.com/vera/ai-challenge/#faq)

![Engineer working on AI tools at a multi-screen desk](https://partners.magicpin.com/vera/ai-challenge/assets/hero-desktop-figma.png)

## India’s Biggest  AI Challenge

No Resume \| No Interview \| No Experience Required

Take the AI Challenge & apply to build
**India’s Largest Retailer AI, VERA**

[Start the challenge](https://partners.magicpin.com/vera/ai-challenge/#apply) [See how it works](https://partners.magicpin.com/vera/ai-challenge/#rubric)

The task

## Build the message engine behind Vera.

![](https://partners.magicpin.com/vera/ai-challenge/assets/task-icon-source.png)

### What Vera is

Vera is magicpin's AI assistant for merchant growth.
It helps merchants improve listings, run campaigns, and reply faster.


### What you build

Build a deterministic `compose(category, merchant, trigger, customer?)` function.
It should return the next message, CTA, send-as identity, suppression key, and rationale.


### What strong entries do

Use merchant context to decide what Vera should say next.
Make every message specific, useful, and easy to reply to.


01

### Category

The right tone, offer patterns, seasonal moments, and what to avoid.

02

### Merchant

Business identity, performance signals, live offers, and conversation history.

03

### Trigger

Why this message should go now: recall, spike, dip, research, or festival.

04

### Customer

Optional context for direct outreach: relationship, consent, status, and preference.

How scoring works

## Our AI scores decisions, not just writing style.

Each dimension is scored from 0–10 (10 = highest score).

**judge\_simulator** v1.0.0·30 canonical test pairs·30s timeout·20 actions/tick

Each scored out of 10

/10

### Decision quality

Can your bot pick the best signal for this moment?
Great outputs combine trigger + merchant state + category fit before writing.


/10

### Specificity

Use real numbers, offers, dates, and local facts from the given input.

/10

### Category fit

Keep tone true to the business type: clinical, visual, timely, or utility-first.

/10

### Merchant fit

Personalize to merchant metrics, offer catalog, and prior conversation behavior.

/10

### Engagement compulsion

Give one strong reason to reply now with a low-effort next action.

### Judge simulator (official local harness)

This package includes the LLM-powered judge as `judge_simulator.py`.


- Validates endpoint behavior: `/healthz`, `/metadata`, `/context`,
`/tick`, `/reply`
- Before running, open `judge_simulator.py` and set `LLM_PROVIDER`,
`LLM_API_KEY`, and `BOT_URL`
- Runs one deterministic judge pass for your submitted bot URL
- Scores quality across all five rubric dimensions
- Prints the complete output in a single run

Run judge simulator (after setting LLM API key)

```
python judge_simulator.py
```

Your output should stay deterministic for the same input and simulator settings.


Read judging guidanceClick to
expand

### 1\. Decision quality

Strong bots do not repeat every available fact.
They choose the one signal that should drive the next message.


### 2\. Engagement

Engagement means the merchant is likely to reply, not just read.
Keep asks short and low-friction, with one clear next step.


### 3\. Bold high-compulsion messaging

Bold does not mean hype.
It means a sharp hook from real context, without invented claims.


### 4\. Generic messages lose

Generic copy gets penalized.
Grounded copy with real merchant facts scores better.


Message craft

## What a strong message looks like.

Generic

Hi Doctor, want to run a discount campaign today to increase sales?


- No trigger
- No merchant fact
- No category voice

High compulsion

190 people in your locality are searching for "Dental Check Up". Should I send them a discounted check up
at ₹299?


- Specific benchmark
- Real offer
- Single CTA

### Levers that work

Use proof, urgency, curiosity, and one simple yes/no action.


### Hard constraints

Respect the session rules: one clear CTA per send, no fake claims.


### What judges change

After submission, judges inject new digest items, metric shifts, triggers, and customer contexts.


Dataset

## Every team starts from the same base data.

```
$ tree magicpin-ai-challenge/
magicpin-ai-challenge/
├── challenge-brief.md
├── challenge-testing-brief.md
├── engagement-design.md
├── engagement-research.md
├── dataset/
│   ├── categories/         # 5 verticals: dentists, salons, restaurants, gyms, pharmacies
│   ├── merchants_seed.json   # 10 seeds → expanded to 50 merchants
│   ├── customers_seed.json   # 15 seeds → expanded to 200 customers
│   ├── triggers_seed.json    # 25 seeds → expanded to 100 triggers
│   └── generate_dataset.py   # deterministic expansion + 30 canonical test pairs
└── examples/
    ├── api-call-examples.md
    └── case-studies.md       # 10 judge-scored anchors

$ python3 dataset/generate_dataset.py --seed-dir dataset --out expanded
# →  expanded/  · 50 merchants · 200 customers · 100 triggers · 30 test pairs
```

### What you submit

Submit a public bot URL. A one-page
`README.md` can explain approach, model choice, and tradeoffs.


Testing setup

## Submit one public bot URL for evaluation.

magicpin's harness calls your URL, sends context, simulates replies, and scores each output.
Your bot should stay stateful, fast, and grounded in received context.


POST /v1/contextPOST /v1/tickPOST /v1/replyGET /v1/healthzGET /v1/metadata

```
# Push merchant context (idempotent by scope + version)
$ curl -sS https://your-bot.example/v1/context \
    -H "Content-Type: application/json" \
    -d '{
      "scope": "merchant",
      "context_id": "m_001_drmeera",
      "version": 3,
      "payload": { "identity": {...}, "performance": {...}, "offers": [...] },
      "delivered_at": "2026-04-29T10:00:00Z"
    }'

# Response — 200 OK
{ "accepted": true, "ack_id": "ack_abc123", "stored_at": "2026-04-29T10:00:00.123Z" }

# Re-posting the same version is a no-op. Higher version replaces atomically.
```

```
# Periodic wake-up — your bot decides what to send
$ curl -sS https://your-bot.example/v1/tick \
    -d '{ "now": "2026-04-29T10:30:00Z",
         "available_triggers": ["trg_research_digest_dentists"] }'

# Response — ≤ 20 actions/tick
{
  "actions": [{\
    "merchant_id": "m_001_drmeera",\
    "trigger_id": "trg_research_digest_dentists",\
    "body": "Dr. Meera, your CTR is 2.1% vs 3.0% South Delhi peer median. You already have Dental Cleaning @ ₹299. Want me to draft a 160-char patient message around it?",\
    "cta": "open_ended",\
    "suppression_key": "research:dentists:2026-W17"\
  }]
}
```

```
# Merchant or customer replied — bot returns send / wait / end within 30s
$ curl -sS https://your-bot.example/v1/reply \
    -d '{ "conversation_id": "conv_001",
         "from_role": "merchant",
         "message": "Yes, send me the abstract",
         "turn_number": 2 }'

# Three valid actions: send, wait, end
{ "action": "send",
  "body": "Sending now — also drafted a 90-sec patient-ed WhatsApp...",
  "rationale": "Honoring accept; adding next-best-step low-friction" }
```

```
# Liveness probe — three consecutive failures disqualify the run
$ curl -sS https://your-bot.example/v1/healthz

{ "status": "ok",
  "uptime_seconds": 3600,
  "contexts_loaded": { "category": 5, "merchant": 50, "customer": 200, "trigger": 100 } }
```

```
# Team identity for the leaderboard
$ curl -sS https://your-bot.example/v1/metadata

{ "team_name": "Team Alpha",
  "team_members": ["Alice", "Bob"],
  "model": "claude-opus-4-7",
  "approach": "single-prompt composer with retrieval",
  "version": "1.2.0" }
```

See full testing flowClick to
expand

01

### Warmup

Health and metadata checks, then base context load: categories, merchants, customers.

02

### Test window

60 simulated minutes. Every 5 minutes, the judge pushes updates and calls `/v1/tick`.

03

### Adaptive injection

Fresh digest items, metric shifts, new triggers, and surprise customer scopes arrive mid-test.

04

### Replay test

Top 10 bots face auto-replies, intent transitions, and hostile/off-topic scenarios.

05

### Score report

Teams receive message scores, logs, transcripts, timeline, and judge rationale.

See technical constraintsClick to
expand

**Timeout** Max response timeout: 30 seconds

**Rate** 10 requests/sec from judge

**Payload** 500 KB context cap

**Tick cap** 20 actions per tick

See deployment and local test notesClick to expand

### Deployment options

Host the bot on any cloud provider.
The submitted public URL must expose all required endpoints.


### Local self-test

Before submission, run endpoint checks locally using the `Judge Simulator` and the sample API
calls in
`examples/api-call-examples.md` to validate payload handling, response
shape,
and timeout behavior.


Starter package

## Everything you need to start building fast.

The zip includes the brief, test contract, dataset generator, API examples, and scored case studies.
It matches the package used by the judge harness.


[Download challenge zip](https://partners.magicpin.com/vera/ai-challenge/assets/magicpin-ai-challenge.zip)

Dataset seeds

### 5 categories + base seeds

Category contexts plus seed files for merchants, customers, and triggers.


Generator

### Deterministic expansion

`generate_dataset.py` expands seeds to 50 merchants, 200 customers,
100 triggers, and 30 canonical test pairs.


Examples

### API + scoring references

Request/response examples and 10 case studies with inputs, outputs, and scorecards.


### Run this after extraction

All teams use the same seed and get the same expanded base dataset.

```
python3 dataset/generate_dataset.py --seed-dir dataset --out expanded
```

See full package layout and case anchorsClick to expand

```
magicpin-ai-challenge/
engagement-design.md
engagement-research.md
challenge-brief.md
challenge-testing-brief.md
dataset/
  categories/
    dentists.json
    salons.json
    restaurants.json
    gyms.json
    pharmacies.json
  merchants_seed.json
  customers_seed.json
  triggers_seed.json
  generate_dataset.py
examples/
  api-call-examples.md
  case-studies.md
```

### 10 sample case anchors

- Dentists: research digest + recall reminder
- Salons: bridal followup + curious ask
- Restaurants: IPL match day + corporate thali planning
- Gyms: seasonal dip reframe + customer lapse winback
- Pharmacies: compliance alert + chronic refill reminder

## How submission works

1. 01

### Build the composer


Implement deterministic message composition from structured JSON context.

2. 02

### Share your bot URL


Submit a hosted URL where the judge can call the required API endpoints.


3. 03

### Handle new context


Judges inject fresh facts after submission to test adaptability and grounding.

4. 04

### Pass replay scenarios


Strong submissions are replay-tested on replies, objections, auto-replies, and intent handoffs.


Open submissions

## Start your challenge journey in 4 steps.

No long process.
Build something real, show your thinking, and submit.


Start journey

Step 1 **Download the challenge pack**

Get the starter zip and review the context format.

Step 2 **Build a working message engine**

Start with one clear end-to-end flow.

Step 3 **Set your public bot URL**

Submit one public base URL (example: `https://mybot.example.com`). Judge will call
`POST /v1/context`, `POST /v1/tick`, `POST /v1/reply`,
`GET /v1/healthz`, and `GET /v1/metadata`.


Step 4 **Submit your final entry**

Share your details and keep your bot live for evaluation.

Frequently Asked Questions (FAQ)

## Straight answers before you submit.

This challenge is a direct quality filter: sharp reasoning, strong product judgment, and reliable execution.


### The simulator is an anchor. The exam is fresh scenarios.

The local `judge_simulator` gives you a deterministic dry-run on the
30 canonical test pairs. The actual judge harness uses the same scoring logic
but injects new facts you haven't seen — fresh digest items, performance
shifts, surprise customer scopes, replies you can't predict. **Your score**
**depends on how your bot handles those, not on how it does on the 30 pairs.**
Bots that pattern-match the simulator will fail. Bots that ground every output
in the context they've actually been given will not.


### What we actually care about

Signal quality. If your decisions are grounded, deterministic, and useful for
merchants, we notice.

### What this can lead to

A **full-time offer** — or an **internship** that can convert into a
full-time offer. Strong submissions help us find people who can join the team.

### How hard is the challenge?

Building the bot is easy. Building one a merchant actually wants to engage with
is the hard part — that's the filter.

What happens after I submit?Click
to expand

Keep your bot live and reachable after you submit. The judge harness runs scoring
on fresh scenarios, and selected candidates hear from the team after evaluation.


Is the simulator the same as the judge?Click to expand

Same scoring logic, different inputs. The `judge_simulator` runs
locally and evaluates against the 30 canonical test pairs you can see. The
**judge harness** — the real evaluation — uses the same scoring
code but injects fresh scenarios you haven't seen. The simulator is for
development confidence. The harness is for the score.


Who can apply?Click to
expand

Solo applications only. Students and working professionals are both welcome.
The full-time role is based out of our Gurgaon office. Before the final offer,
we'll verify that you actually did the work yourself.


Any length or URL limits on replies?Click to expand

No hard cap. Write the message length that best fits the context.
Include links only when they add real value for the merchant.


Do I need past AI experience?Click
to
expand

No. We judge the output quality and reasoning quality, not years of experience.

Can I submit multiple times?Click
to
expand

Yes, but each submission is judged on quality. More submissions do not help if the core logic is weak.

What gets rejected quickly?Click to
expand

Hallucinated facts, generic templates, unstable responses, and broken endpoint behavior.

What makes a strong submission?Click
to expand

Specific merchant-aware messaging, sharp decision logic, and consistent behavior across judge scenarios.

Open challenge

## Submissions are open

Come in, do the challenge, and submit your working bot URL when ready.

Entries are open for evaluation.

### OPENNOW

Submit anytime

Vera challenge journey

Close

## Start your submission journey.

Step 1 of 5

Step 1

### Download and review

Download the challenge zip, run the dataset generator, and understand the context structure.

[Download challenge zip](https://partners.magicpin.com/vera/ai-challenge/assets/magicpin-ai-challenge.zip)

Step 2

### Build one strong flow

Start small and deterministic: handle trigger, merchant, and category context correctly.

Step 3

### Submit your bot endpoint

Share one public base URL (example: `https://mybot.example.com`) and ensure these are live:

- `POST /v1/context`
- `POST /v1/tick`
- `POST /v1/reply`
- `GET /v1/healthz`
- `GET /v1/metadata`

Step 4

### Share final details

Full name _\*_Email _\*_Phone number _\*_Submission URL _\*_LinkedIn URL (optional)

Required fields must be valid before submission.

1st Submission


### Thanks for taking India's biggest AI challenge.

Our AI is now reviewing your AI bot

You will get a response on your mail soon!

Keep your bot live for evaluation

You can try the challenge again after the result.

BackNext