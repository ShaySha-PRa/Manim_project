# ManimGL eliminated after runtime failure

Status: eliminated by project owner on 2026-08-04; do not retry in Phase 2.

The fixed `v1.7.2` image built successfully, but both attempted
`formula_transform` runs stalled inside `xvfb-run` before ManimGL started.
The parent stopped the runs after 397.276 and 56.773 seconds; both records have
exit code 130, no video and no hash. The process tree contained `xvfb-run` and
Xvfb but no `manimgl` process. The project owner then explicitly eliminated GL.

The failed command shape was:

```bash
docker run --rm ... manim-project/manimgl-benchmark:v1.7.2 \
  xvfb-run -a ... manimgl scenes.py FormulaTransform -l -w
```

The versioned failure summary is `../results/manimgl-failure.json`. Local logs
remain under ignored `artifacts/`; the runner implementation is retained only
as decision evidence and is not part of the selected production path.
