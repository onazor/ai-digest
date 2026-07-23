# AI Digest (Jul 06, 2026)

Here is a concise digest of the most relevant accepted sources from the latest run, with links for deeper follow-up.

## Why Chain-of-Thought Supercharges Transformer Expressivity

### What changed
New theoretical results show that adding explicit chain-of-thought (CoT) tokens fundamentally boosts the formal computational power of transformer decoders. With sufficiently long CoT traces, transformers can simulate powerful classical computation models, connecting practical prompting tricks to rigorous complexity-theoretic guarantees.

### The bigger story
- Linear-length CoT lets transformers recognize all regular languages, matching classical finite automata in expressive power.
- Polynomial-length CoT elevates transformers to solving any problem in P, via simulation of polynomial-time Turing machines.
- Expressivity gains come from using CoT as external working memory, clarifying why structured intermediate reasoning can unlock qualitatively new behaviors.

### Why it matters
These results justify investing in CoT-style prompting and architectures as more than heuristic hacks: they unlock provably stronger computation regimes. For CoEs, it supports prioritizing tooling, evaluation, and training strategies that elicit and control intermediate reasoning steps.

### Read more
- [The Expressive Power of Transformers with Chain of Thought](https://doi.org/10.48550/ARXIV.2310.07923) - Core theory paper linking CoT prompting to formal computational complexity.
