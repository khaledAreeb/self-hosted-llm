# 2026-10-01 results

`code-sql-top-customers@shadeform` was answered by the **Shadeform VM**, not by Modal:
- the server was started by `shadeform_deploy.py up --hours 1`;
- its vLLM flags were identical to `deploy.py` at commit `68cff7e` (task 1.2).

`eval/run_eval.py` normally copies `deploy.py` next to its results. That copy
isn't committed here, because it wasn't the configuration that served these
answers.
