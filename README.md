# Azure Solution Architect AI

A multi-agent system that designs, evaluates, and generates production-ready Azure architectures using LangGraph + Chainlit.

## LangGraph Pipeline Topology

```
┌──────────────────────────────────────────────────────────────────┐
│                    azure-architect-ai pipeline                   │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│   [User Input: workload description]                             │
│          │                                                       │
│          ▼                                                       │
│   ┌─────────────┐                                                │
│   │   Planner   │  Extracts structured requirements (JSON)       │
│   └──────┬──────┘                                                │
│          │                                                       │
│          ▼                                                       │
│   ┌─────────────┐◄──────────────────────────────┐               │
│   │  Architect  │  Designs full Azure topology   │               │
│   └──────┬──────┘                                │               │
│          │                                       │               │
│          ▼                                       │               │
│   ┌─────────────┐                                │               │
│   │  Evaluator  │  WAF review (5 pillars)        │               │
│   └──────┬──────┘                                │               │
│          │                                       │               │
│   ┌──────▼──────────────────────────┐            │               │
│   │  passed? AND loop_count check   │            │               │
│   └──┬──────────────────────────┬───┘            │               │
│      │                          │                │               │
│   passed=True              passed=False          │               │
│   OR max loops           AND loop < max          │               │
│      │                          │                │               │
│      │                   ┌──────▼──────┐         │               │
│      │                   │  Redesigner │─────────┘               │
│      │                   └─────────────┘  (increments loop_count)│
│      │                                                           │
│      ▼                                                           │
│   ┌─────────────────┐                                            │
│   │  Human Approval │◄── interrupt() pauses here                 │
│   │  (Chainlit UI)  │    Chainlit shows AskActionMessage         │
│   └──────┬──────────┘                                            │
│          │                                                       │
│   ┌──────▼──────────────┐                                        │
│   │  approved?          │                                        │
│   └──┬──────────────┬───┘                                        │
│      │              │                                            │
│    Yes              No                                           │
│      │              │                                            │
│      ▼              ▼                                            │
│  ┌────────┐       [END]                                          │
│  │  ARM   │  Generates deployable ARM template                   │
│  │  Gen   │                                                      │
│  └───┬────┘                                                      │
│      │                                                           │
│      ▼                                                           │
│    [END]                                                         │
└──────────────────────────────────────────────────────────────────┘
```

## Setup

```bash
# 1. Clone / navigate to project
cd azure-architect-ai

# 2. Create virtual environment
python -m venv venv

# 3. Activate
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Configure environment variables
cp .env .env.local   # or edit .env directly
# Set ANTHROPIC_API_KEY and LANGCHAIN_API_KEY

# 6. Run
chainlit run app.py
```

## How the Redesign Loop Works

The pipeline automatically improves architectures that don't meet the Well-Architected Framework threshold (overall score ≥ 75):

1. **Evaluator** scores the architecture across 5 WAF pillars
2. If `overall_score < 75`, the **Redesigner** receives:
   - The current architecture
   - The evaluator's critical issues list
   - The loop iteration number
3. The Redesigner produces an improved architecture with `redesign_notes` explaining each fix
4. The improved architecture loops back to the **Architect** for refinement, then **Evaluator** again
5. This repeats up to `max_loops` (default: 3) times
6. After max loops OR a passing score, the pipeline continues to Human Approval

The Chainlit UI shows progress messages:
```
🔁 Redesign Loop 1/3 — fixing 4 critical issues
🔁 Redesign Loop 2/3 — fixing 2 critical issues
```

## How Human Approval Works

The `human_approval` node uses LangGraph's `interrupt()` mechanism:

1. When the node executes, it calls `interrupt(data)` — this **pauses the graph** and saves the full state to MemorySaver
2. The LangGraph `astream()` loop in Chainlit detects `"__interrupt__"` in the event stream
3. Chainlit displays an `AskActionMessage` with the architecture summary and WAF scores
4. The user clicks **✅ Approve** or **❌ Reject**
5. Chainlit calls `pipeline.astream(Command(resume=True/False), config)` to **resume** the graph
6. The `interrupt()` call inside the node returns the resume value (`True` / `False`)
7. The graph continues: approved → ARM Generator, rejected → END

## Agent Prompts

| Agent | Model | Role |
|-------|-------|------|
| Planner | claude-sonnet-4-5 | Requirements extraction → JSON |
| Architect | claude-sonnet-4-5 | Full Azure topology design → JSON |
| Evaluator | claude-sonnet-4-5 | WAF 5-pillar scoring → JSON |
| Redesigner | claude-sonnet-4-5 | Issue-driven architecture improvement → JSON |
| ARM Generator | claude-sonnet-4-5 | Deployable ARM template → JSON |

All agents parse LLM output with `try/except` JSON error handling and markdown code-block stripping.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key |
| `LANGCHAIN_API_KEY` | Optional | LangSmith tracing key |
| `LANGCHAIN_TRACING_V2` | Optional | Enable LangSmith tracing |
| `LANGCHAIN_PROJECT` | Optional | LangSmith project name |

## Verification

```bash
# Verify graph compiles correctly
python -c "from graph import pipeline; print('Graph OK')"

# Verify app imports correctly
python -c "import app; print('App OK')"
```
