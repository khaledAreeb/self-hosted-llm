# 2026-10-04 results

`code-sql-top-customers@shadeform-tp2` was answered by a **Shadeform VM with two A100s and tensor parallelism**:
- the server was started by `shadeform_deploy.py up --tensor-parallel 2 --gpu A100`;
- its vLLM flags were the phase 4 set plus `--tensor-parallel-size 2`;
- results are in `NOTES.md`, "Phase 5".

`eval/run_eval.py` normally copies `deploy.py` next to its results. That copy
(`deploy.py` in this folder) isn't the configuration that served these answers,
and is left out of commits.
