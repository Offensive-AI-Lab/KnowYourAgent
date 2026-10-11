# Appendix: AutoHijacker Reproduction Details

This appendix documents the complete experimental setup used to reproduce AutoHijacker
(Ren et al., under review at ICLR 2025) as a baseline in our evaluation. We describe the
algorithm's two-stage structure, the concrete hyperparameters used in our reproduction,
and where and why our implementation deviates from the paper's original configuration,
along with a direct side-by-side comparison table.

---

## A.1 Algorithm Overview

AutoHijacker is a two-stage, black-box indirect prompt injection framework built on the
*LLM-as-optimizer* paradigm. Its core contribution is a **batch-based optimization
scheme** that addresses the sparse-feedback problem inherent to indirect prompt injection:
unlike jailbreak attacks, where victim responses are informative regardless of success,
prompt injection attacks typically return near-zero scores for almost every attempt,
making single-instance gradient-free optimization ineffective.

The framework employs three cooperating LLM agents:

- **Prompter** — given the original external document (D), the attack goal (G), and a
  persistent attack memory (A), produces a *meta-prompt* (M): a set of strategic
  directives (attack framing, formatting tricks, pitfalls to avoid) that guides the
  Attacker.
- **Attacker** — given M, D, and G, generates the final injected document D̂ by
  embedding the malicious goal seamlessly into the benign content.
- **Scorer** — given the victim model's response (R) and G, assigns a continuous score
  S ∈ [0, 10] reflecting how completely the injection goal was satisfied.

### Stage 1: Training (Batch-Based Optimization)

The training loop iterates over N diverse (D, G) pairs across I epochs. For each data
point the pipeline executes: Prompter → Attacker → Victim LLM → Scorer → Memory
Update. After each data point, the attack memory retains the top-*k* highest-scoring
and bottom-*k* lowest-scoring entries across all accumulated examples. This contrastive
structure ensures the Prompter can learn both what works and what to avoid.

### Stage 2: Test (One-Step Generation)

At test time, no further victim queries are issued. Given a new D and G from the target
benchmark, the trained attack memory is provided as context to the Prompter, which
produces M, and the Attacker generates D̂ in a single pass. D̂ is then submitted to the
evaluation environment (AgentDojo or InjecAgent).

---

## A.2 Reproduction Configuration

### Training Data

The original paper samples training data from two sources: SQuAD 2.0 (document
question-answering) and WebSRC (web-based structural reading comprehension), using 30
examples from each to produce 60 (D, G) training pairs. For training injection goals,
the paper randomly selects 30 goals drawn jointly from Open-Prompt-Injection (OPI) tasks
and AgentDojo injection tasks.

In our reproduction, we sourced all 60 documents exclusively from the SQuAD 2.0
**validation split** (Rajpurkar et al., 2016), downloaded via KaggleHub
(`thedevastator/squad2-0-a-challenge-for-question-answering-syst`, validation.csv).
The 60 passages were sampled with a fixed random seed of 42. We did not use WebSRC
because the original authors' use of that dataset was primarily to increase diversity
in the training documents' formatting (web-rendered vs. prose text); we judged the
diversity within SQuAD 2.0 sufficient given the paper's own finding (Table 1 in the
main paper) that "the tasks in AgentDojo differ significantly from the classic DocQA and
WebQA tasks on which our method is trained", demonstrating that the method transfers
across domain shifts regardless.

For training injection goals, we drew all 60 goals exclusively from an OPI-style goal
pool (15 goal templates sampled with replacement, seed 42), explicitly **excluding**
any AgentDojo injection tasks to preserve the entire AgentDojo benchmark as a clean,
unseen held-out test set. This is consistent with the original paper's motivation:
"AgentDojo goals are kept as a clean held-out test set."

### Model Configuration

The original paper uses **Llama-3.1-70B** as both the attacker and scorer LLMs, and
tests victim models including GPT-4o-2024-08-06 and GPT-4o-mini-2024-07-18.

Our reproduction uses **GPT-4o-mini** (`gpt-4o-mini`) as the backbone for all three
CrewAI agents (Prompter, Attacker, Scorer) during the **training stage**, and
**GPT-4.1** (`gpt-4.1-2025-04-14`) for all agents during the **test stage**. The
**victim model** during training (the model that reads D̂ and produces R, whose response
the Scorer grades) is GPT-4.1. The **target agent** in the AgentDojo evaluation is
also GPT-4.1.

The decision to use GPT-4o-mini for training agents is consistent with the paper's own
setup: their reported experiments use a cost-efficient open-source model (Llama-3.1-70B)
as the optimizer backbone, not the same model as the victim. The paper additionally
reports a transferability experiment (Table 5) showing that training the attack memory
on Llama-3.1-70B and testing on GPT-4o-mini incurs only a 2.7% ASR drop while still
outperforming all baselines, confirming that the attack memory generalizes robustly
across model families. Our choice of GPT-4o-mini as the training optimizer is therefore
a principled substitution: it is a similarly capable but cost-efficient model, and the
attack memory it builds is deployed with the stronger GPT-4.1 at test time.

### Agent Framework

Both the original paper and our reproduction implement the Prompter–Attacker–Scorer
pipeline using **CrewAI** with sequential crew processes. Agent prompts follow the
paper's described roles exactly: the Prompter is described as a "Red Team Strategist"
that synthesizes meta-prompts from attack history; the Attacker is a "Payload Engineer"
that embeds goals into documents; the Scorer is a "Security Evaluator" that assigns a
0–10 numeric score. No agent is given delegation rights.

### Benchmark

We evaluate on the **AgentDojo** benchmark (Debenedetti et al., 2024), covering all
four task suites: Banking (16 user tasks × 9 injection tasks), Travel (20 × 7),
Workspace (40 × 6), and Slack (21 × 5). This matches the suites used in the original
paper. The victim agent model is GPT-4.1 (`gpt-4.1-2025-04-14`). We use the
AgentDojo `attack_success_rate` metric (referred to as "target attack success rate" in
the original paper) as the primary evaluation criterion.

We also evaluate on the **InjecAgent** benchmark (Zhan et al., 2024) under the
`enhanced` setting, covering the `dh` (direct harm) and `ds` (data stealing) suites,
using GPT-4.1 as the target agent.

Defense evaluations are run using the `spotlighting_with_delimiting` defense
(corresponding to the "Spotlighting with Delimiting" defense evaluated in the paper)
on the same suite/task coverage as the no-defense condition.

---

## A.3 Hyperparameter Comparison

| Hyperparameter | Original Paper | Our Reproduction |
|---|---|---|
| **Training documents** | 30 SQuAD-v2.0 (DocQA) + 30 WebSRC (WebQA) | 60 SQuAD 2.0 (validation split) |
| **Training injection goals** | 30 goals drawn jointly from OPI + AgentDojo | 60 goals sampled from 15 OPI-style templates (seed 42); AgentDojo goals excluded |
| **Total training pairs (N)** | 60 | 60 |
| **Training epochs (I)** | 10 | 10 |
| **Attack memory size** | 30 (k_top = 15, k_bottom = 15) | 30 (k_top = 15, k_bottom = 15) |
| **Memory selection strategy** | Contrastive (top + bottom) | Contrastive (top + bottom) |
| **Training optimizer LLM** | Llama-3.1-70B | GPT-4o-mini (`gpt-4o-mini`) |
| **Test-stage agent LLM** | Llama-3.1-70B (same as training) | GPT-4.1 (`gpt-4.1-2025-04-14`) |
| **Training victim LLM** | GPT-4o-2024-08-06 | GPT-4.1 (`gpt-4.1-2025-04-14`) |
| **Test target agent (AgentDojo)** | GPT-4o-2024-08-06 / GPT-4o-mini / Llama / Command-R+ | GPT-4.1 (`gpt-4.1-2025-04-14`) |
| **Scorer scale** | 0.0 – 10.0 | 0.0 – 10.0 |
| **Agent framework** | CrewAI | CrewAI |
| **Random seed** | Not specified | 42 (data sampling, goal selection) |
| **Benchmark: AgentDojo** | Workspace, Slack, Travel, Banking | Workspace, Slack, Travel, Banking |
| **Benchmark: InjecAgent** | Evaluated | Evaluated (dh, ds; enhanced setting) |
| **Defense evaluated** | Spotlighting w/ Delimiting, Repeat User Prompt, Tool Filter | Spotlighting w/ Delimiting |
| **Parallelism** | Not specified | Up to 10 parallel workers (ThreadPoolExecutor) |

---

## A.4 Rationale for Deviations

**Training data source.** We used only SQuAD 2.0 rather than SQuAD 2.0 + WebSRC.
The paper's own results (Table 1) show that AutoHijacker transfers well across domain
shifts because "the tasks in AgentDojo differ significantly from the classic DocQA and
WebQA tasks on which our method is trained." The purpose of mixing DocQA and WebQA in
the original is purely to introduce diversity in document format; SQuAD 2.0 provides
equivalent diversity in topic and passage style for this purpose.

**Model family.** We use GPT-4.1/GPT-4o-mini in place of Llama-3.1-70B. This
substitution is motivated by two factors. First, the paper's transferability ablation
(Table 5) demonstrates that training on one model family and testing on another incurs
a negligible ASR drop (2.7%) while still outperforming all baselines, establishing that
the attack memory is model-agnostic. Second, evaluating the baseline on the same target
model (GPT-4.1) used for all other baselines in our study ensures a fair, controlled
comparison.

**Target model version.** We evaluate against GPT-4.1 (`gpt-4.1-2025-04-14`) rather
than GPT-4o-2024-08-06. GPT-4.1 is the current production successor to GPT-4o and
represents the appropriate target for a 2025/2026 evaluation. All baselines in our
study share this target, making the comparison internally consistent.

**Training injection goals.** We exclude AgentDojo injection tasks from the training
goal pool to avoid any data leakage into the test evaluation. This is more conservative
than the original paper's setup (which included AgentDojo goals in training while still
testing on AgentDojo), and therefore favors the null hypothesis of no attack
improvement; any ASR we observe represents a lower bound relative to the paper.

---

## A.5 Implementation Fidelity

The following structural decisions from the paper are preserved exactly in our
implementation:

- The **three-agent topology** (Prompter, Attacker, Scorer) with distinct roles and no
  cross-delegation.
- The **two-stage pipeline**: a training stage that builds the attack memory, and a
  test stage that performs single-pass generation without further victim queries.
- The **contrastive memory structure**: retaining both high-scoring (successful) and
  low-scoring (failed) examples, which the ablation study (Table 6, top) confirms
  provides a 10–14% ASR improvement over top-k-only sampling.
- The **meta-prompt indirection**: the Prompter generates strategic instructions (M)
  that are then passed to the Attacker, rather than having the Attacker reason from
  scratch. This design, confirmed by the framework ablation (Table 6, bottom left),
  outperforms both direct fuzzing (31.1% vs 62.4% ASR) and Chain-of-Thought (53.9%).
- The **victim conversation format** used during training: a system message describing
  a reading-assistant role, followed by a user message pairing the question with the
  injected document.
- The **score extraction** from Scorer output as a single float on [0, 10], with
  memory update occurring after every data point within an epoch.

The full implementation, including agent prompts, task descriptions, memory serialization
logic, and the AgentDojo evaluation harness, is available in
`Baselines/AutoHijacker/` of the released codebase.
