# ADR-003: LLM does not write free Manim; Compiler and Tools emit code

## Status

Accepted

## Date

2026-08-19

## Context

The workbench already has a contract-first API, an append-only version chain, and a network-off Docker render sandbox. Scene IR 1.6 plus the ManimCE 0.21 compiler can emit allowlisted Python for formula, function, plane geometry, proof, and 3D gallery templates.

That path cannot express scientific field evolution. `IrExprId` is a closed teaching set (`pow3`, `sine`, …). `SURFACE` is a fixed saddle. `IMAGE_REF` only accepts uploaded PNG paths. The code-generation prompt still asks a model to mutate a reference `Scene`. A handwritten wave-packet scene would prove rendering, not the product.

The 2026-08-19 research report (`docs/research/animation-agent-v2.md`) concludes that raising Manim prompt freedom is the wrong investment. Vega/Lottie-style declarative IR plus a deterministic compiler is the asset.

## Decision

The Animation Agent V2 path is:

```text
one sentence → IntentSpec → registered scientific tools → AnimationIR 2.0
  → deterministic Manim compiler → existing render sandbox → MP4
```

Binding rules:

1. The LLM, when used, may only fill `IntentSpec` JSON (`domain`, `goal`, `assumptions`, `tools_needed`). It must not emit Scene Python, lambdas, or free NumPy in a Scene.
2. Numbers, fields, trajectories, and series come from a `ToolRun` with parameter hash, input hash, and output artifact hash. AnimationIR stores `artifact_ref`, never raw samples.
3. The compiler lowers `scalar_field` to `ImageMobject` over **precomputed** arrays (`np.load(..., allow_pickle=False)`). The Scene must not evaluate `np.exp` (or any other free field kernel) live.
4. Unknown IR capabilities return `UnsupportedFeature` and apply a declared fallback. The compiler never asks a model to patch Python.
5. Render sandbox stays network-off. Compute is a separate sandbox: allowlisted SymPy/NumPy/SciPy/pandas ops, read-only inputs, isolated outputs, `allow_pickle=False`.
6. ContentPlan 1.1 remains the teaching specialization. The old LLM Python path is not the V2 entry and is not deleted in this slice.

## Consequences

- New contracts: `IntentSpec`, `AnimationIR` schema 2.0, `ToolRun`, `AgentRunResponse`.
- `ir_compiler.py` remains the Scene IR 1.6 backend; `compiler/manim.py` lowers AnimationIR 2.0.
- P0 proves six vertical slices, starting with two-dimensional wave-packet interference.
- Formula/function/geometry regressions must keep passing.

## Alternatives considered

### Stronger Manim prompts

Rejected: first-pass rate and the AST allowlist fight each other; the model still cannot be the source of scientific numbers.

### Keep extending Scene IR 1.6 expression IDs

Rejected as the long-term core. Teaching IR stays; scientific dataflow needs `data` / `states` / `bindings` / `assertions`.
