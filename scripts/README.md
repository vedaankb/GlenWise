# Optional benchmarks

```bash
# A GleanWise with a language model configured must be running.
uv run --directory services/core python ../../scripts/benchmark.py \
  --dataset path/to/questions.jsonl --mode pro --out report.json
```

Each JSONL row needs `question` and may carry `answer` (the expected answer). The report lists per-question
latency, time to first token and sources used; with expected answers it also reports a normalized
"contains the expected answer" accuracy. That is a coarse check, not a substitute for the benchmark's own grader.

Not installed by `deploy/install.sh`.
