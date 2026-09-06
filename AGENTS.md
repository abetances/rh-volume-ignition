# AGENTS.md - rh-volume-ignition

## Project Boundary
- Stay inside this project root. Run `./scripts/safety_guard.sh --assert-root` before state-changing project work.
- Do not modify other trading projects, global OpenClaw config, unrelated credentials, or unrelated databases from this project session.

## Dev Server Rules
- Use `./scripts/run.sh` for local manual startup.
- Do not use `nohup python`, broad `pkill`, or `lsof ... | xargs kill`.
- If port 5555 is busy, identify the exact PID first with `ss -ltnp` or `pgrep -af`.
- Kill only an exact PID that clearly belongs to this project. If ownership is unclear, report `PID_OWNERSHIP_UNKNOWN`.
- Treat no matching PID as already clean, not as a failure.
- Do not kill OpenClaw, gateway, browser, n8n, shell parents, or processes from another project.

## Verification
- Health check: `curl -fsS http://localhost:5555/api/v1/health`.
- If the server is already running and healthy, do not restart it just to verify.
