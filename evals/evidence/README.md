# Versioned evaluation evidence

Each JSON file in this directory is an immutable evidence envelope. Its
`evidence_manifest` records the dataset semantic version and SHA-256, evaluator
version, relevant source-tree SHA-256, Git revision, tracked patch SHA-256,
generation time, and a secret-free runtime summary. The `results` object contains
the measured metrics and per-case outcomes.

Evidence writers use exclusive file creation and timestamped names, so a later
run cannot silently replace an earlier result. A dirty Git flag is expected for
pre-commit validation; the source and patch hashes identify the exact code that
was measured.

Generate the offline contract evidence:

```powershell
python .\evals\runners\run_deterministic_evals.py --evidence-dir evals/evidence
```

Generate the 30-case read-only live RAG evidence against a healthy local stack:

```powershell
python .\evals\runners\run_live_agentic_evals.py --timeout-seconds 90 --evidence-dir evals/evidence
```
