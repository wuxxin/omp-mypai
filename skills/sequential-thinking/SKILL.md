---
name: sequential-thinking
description: Dynamic and reflective step-by-step problem-solving through sequential thoughts with revision and branching capabilities. Use when breaking down complex problems, planning multi-step solutions, analyzing ambiguous requirements, debugging intricate issues, exploring design alternatives, or tackling problems where the full scope is unclear. Enables thought revision, backtracking, branching, and iterative hypothesis verification.
---

# Sequential Thinking

Provides structured, iterative reasoning paired with the `mcp__sequential-thinking__sequentialthinking` MCP tool. Each thought can build on, question, or revise previous insights as understanding deepens.

## When to Trigger

Use `mcp__sequential-thinking__sequentialthinking` when the task involves:

- Multi-step reasoning with interconnected parts
- Ambiguous or uncertain scope that needs exploration
- Need to filter complexity to find core issues
- Anticipated need to backtrack, revise, or branch
- Design planning, trade-off analysis, or debugging with multiple hypotheses
- Hypothesis generation and verification cycles

**Skip for:** simple lookups, single-step facts, straightforward edits with no ambiguity.

## Tool Parameters

| Parameter | Required | Type | Description |
|---|---|---|---|
| `thought` | yes | string | Current reasoning step content |
| `nextThoughtNeeded` | yes | boolean | Whether more reasoning is needed |
| `thoughtNumber` | yes | integer (≥1) | Current step number |
| `totalThoughts` | yes | integer (≥1) | Estimated total steps (adjust dynamically) |
| `isRevision` | no | boolean | Whether this revises previous thinking |
| `revisesThought` | no | integer | Which thought number is being reconsidered |
| `branchFromThought` | no | integer | Thought number to branch from |
| `branchId` | no | string | Identifier for this branch |
| `needsMoreThoughts` | no | boolean | Signal more thoughts are needed |

## Workflow

1. Start with an initial estimate of `totalThoughts`, but adjust freely as understanding evolves.
2. For each step, express the current reasoning in `thought`.
3. Set `nextThoughtNeeded: true` to continue, `false` only when a satisfactory conclusion is reached.
4. Question or revise earlier thoughts when assumptions prove wrong.
5. Branch from a thought when multiple viable approaches exist — use `branchFromThought` + `branchId` to fork.
6. Express uncertainty explicitly — the chain is meant to refine, not to be perfect on the first pass.

## Patterns

### Basic linear sequence
Estimate total, step through, adjust estimate as needed, conclude.

### Revision
When an earlier assumption fails, set `isRevision: true` and `revisesThought: N` to reconsider that step. The new thought replaces or augments the original reasoning.

### Branching
When exploring alternatives, mark the fork point with `branchFromThought: N` and assign a `branchId`. Each branch forms an independent reasoning path — follow one to conclusion before evaluating the next.

### Hypothesis verification
Generate a candidate solution as a thought, then verify it in subsequent thoughts against the accumulated reasoning chain. Repeat until a verified answer is reached.
