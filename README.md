# .github

Organization-level configuration for **[kratuvak](https://github.com/kratuvak)**.

- [`profile/README.md`](profile/README.md) — the public profile rendered at
  [github.com/kratuvak](https://github.com/kratuvak).

To change what visitors see on the org page, edit `profile/README.md` and push.

## Rules for agents and contributors

### No Docker on the owner's workstation; deployments run on the deployment host

Owner rule, 25 November 2026: "this mac SHOULD NOT RUN DOCKER !!!", and "deployments belong on [the designated deployment host]".

- **No Docker on the owner's interactive workstation.** It never runs Docker or Docker Desktop, not even briefly for a measurement.
- **Every deployment runs on the designated deployment host:** containers, services, MCP HTTP servers, dashboards and viewers, scheduled jobs, and backups. Throwaway, measurement and test containers also run there, over SSH.
- **Scheduled jobs on the deployment host are system LaunchDaemons with `UserName`,** not GUI LaunchAgents. A GUI LaunchAgent written over SSH is never loaded and never fires on a headless session. Verify each job with `sudo launchctl print system/<label>`, and fire it once as a positive control.
- **Monitoring alarms when Docker *is* running on the workstation.** "Docker down" there is the intended state, not an outage.

Why: Docker's disk image grew until the workstation fell far below its free-space floor, and in October 2026 Docker running near a full disk corrupted its disk image and caused a database outage. A scheduled backup installed as a GUI LaunchAgent silently missed its runs.
