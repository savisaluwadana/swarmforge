# Local operations and deployment boundaries

## Start and stop
Use the root README. Generated .env is mode 0600 on POSIX and contains three independent credentials. Do not put credentials into URLs, commits, screenshots, recordings or model prompts. All host ports bind loopback. `docker compose ps -a` should show healthy PostgreSQL and API, completed migrator, running worker and web. Inspect `docker compose logs api worker` for errors; avoid sharing logs containing private data. Health readiness checks database schema, not the worker or entire service. A queued run without a matching engine version remains queued; do not edit its immutable manifest. Keep API and worker on the same build ID.

`docker compose down` stops containers while preserving the volume. Do not use `down -v` unless you explicitly intend to delete all local experiments. The CI uses disposable data only. To upgrade, back up first, use a clean checkout, rebuild, and run migrations. The migration runner checks historical SQL checksums; never modify already applied SQL. Drain old-version queued runs first.

## Backup
```bash
docker compose exec -T postgres pg_dump -U swarmforge -d swarmforge -Fc > swarmforge-backup.dump
```
Store privately. Restore into a separate empty database first; validate migration checksums and run exports. No automatic restore or disaster-recovery guarantee. Database volume is persistent but is not a backup.

## Troubleshooting
- 401: check appropriate credential and seeded principal. REST and MCP credentials are not interchangeable.
- 403 approval: distinct secret plus plan owner/editor and exact hash required. Expired plans must be newly drafted.
- 409: inspect state, idempotency conflict, archived scenario or stale cursor; do not blindly retry.
- 429: decrease run budget or pending work.
- Worker loss: lease expiry marks failure, committed prefix retained. Re-run manually with frozen manifest; no silent resumption.
- Model disabled: draft without AI or use local MCP. Never bypass budgets to get a demo working.

## Hosting
Local research preview only. The Next.js web tier can later be hosted separately (including Vercel) with a fixed HTTPS backend origin, but the durable Python worker, PostgreSQL and long-lived API/SSE need persistent container/VM hosting. Vercel alone is not the complete runtime. Before any public deployment: TLS, actual OIDC provider, production step-up identity and per-client scopes, remote MCP OAuth discovery and protected-resource metadata, tenant security review, DB backups/restore drills, monitoring, rate limiting, CORS/Origin/host controls, network policy and secret manager. Never forward the local MCP token or expose the local demo identity publicly. No paid hosting or external provider call has been authorized by this release work.

## Limits
The engine retains traces in memory. A scale smoke independently tests 100 robots at 20 ticks and one robot at 10,000 ticks, not 100 robots at 10,000 ticks or worst-case communication/1000-task load. Actual resource observations are runner-specific. Treat maximum values as syntax bounds, not a supported capacity SLA. Interactive mode caps 300 ticks, 20 commands; playback caps 20,000 events.
