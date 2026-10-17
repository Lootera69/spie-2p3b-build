# Deploying the BrainBloom workshop for free

The workshop is the only part of SPIE worth hosting: it generates, proves and certifies
puzzles on demand. The engine's correctness path is unchanged by anything here — the
`validate → verify → certify` gate still runs in-process, and no learned model is involved.

The target is Render's free web-service plan: **0.1 CPU, 512 MB, 750 instance-hours a
month, no card required.** `render.yaml` and `Dockerfile` in this directory are a complete
blueprint; nothing else needs configuring.

## What it costs to run

Measured on this machine, peak resident set for the whole stack:

| Configuration | Peak RSS | Fits 512 MB |
| --- | --- | --- |
| Solvers only, no dictionary | 71 MB | yes |
| WordNet 3.0 + the 8 coverage packs (**what ships**) | 249 MB | yes, ~260 MB spare |
| WordNet + optional OEWN 2024 | 771 MB | **no — would be killed** |

That last row is why the container passes `--no-oewn` explicitly instead of letting the
corpus auto-detect. If you ever bake OEWN into the image, you must also move off the free
plan. A single logic certification takes ~0.44 s and three questions ~0.03 s, so 0.1 CPU is
adequate for a demo; the server answers **serially** by design, because Z3's context is not
shared across threads.

## Deploy

1. Push this repository to GitHub (public, so Actions and the free plan stay free).
2. On Render: **New → Blueprint**, point it at the repo. It reads `render.yaml`.
3. Wait for the first build. It downloads the hash-pinned WordNet corpus once, at build
   time, and bakes it into the image — generation never touches the network.

The free plan spins the instance down after 15 minutes idle; the next visitor waits roughly
a minute for a cold start. The disk is ephemeral, which is why `--no-history` is passed:
cross-session draft fingerprints would not survive a restart anyway.

## How the public mode is gated

The server is loopback-only unless you name a public origin. That is one switch, and it
controls three things at once:

- **Bind address** — `BRAINBLOOM_HOST` (`--host`). Defaults to `127.0.0.1`; the image sets
  `0.0.0.0`.
- **Same-origin allowlist** — `BRAINBLOOM_PUBLIC_ORIGIN` (`--public-origin`), e.g.
  `https://brainbloom-workshop.onrender.com`. Only then is that `Host` accepted, and only
  with that exact scheme in `Origin`. Loopback keeps working alongside it. The container
  falls back to Render's own `RENDER_EXTERNAL_URL`, so the allowlist tracks the real
  hostname even if the service is renamed.
- **Request cap** — naming a public origin enables 60 requests per minute per client. The
  endpoint is unauthenticated, so this is what stops one caller monopolising 0.1 CPU.
  Behind the platform proxy the client is the leftmost `X-Forwarded-For` entry; that header
  is client-settable, which is exactly why it is trusted only in public mode.

`PORT` sets the listening port (`--port`); the image defaults to 10000, which is what
Render routes to. `/healthz` answers before the origin check, so the platform's probe — which
arrives with its own `Host` and no `Origin` — is not rejected. `GET` returns the static
`{"status": "ok"}` response; `HEAD` returns the same headers without a response body.

Nothing above weakens the local default. With no public origin configured the behaviour is
byte-for-byte what it was: `127.0.0.1` only, no cap, same startup banner.

## Verify a deployment

```bash
curl -s https://YOUR-SERVICE.onrender.com/healthz
```

```bash
curl -s -H "Origin: https://YOUR-SERVICE.onrender.com" \
     -H "Content-Type: application/json" -d '{"seed":7}' \
     https://YOUR-SERVICE.onrender.com/api/generate
```

A cross-origin request must come back `403`, and more than 60 requests a minute `429`.

For a cron-job.org keep-warm job, use **GET** with
`https://YOUR-SERVICE.onrender.com/healthz` and an `Accept: application/json` header.
Enable the job, select **Every 5 minutes**, leave **Schedule expires** off, and save
responses in the job history. Use the maximum ordinary-job timeout of **30 seconds**.
The schedule must cover **all hours, every day** (`*/5 * * * *`); the previous
`*/5 7-22 * * *` schedule stopped at 22:55 IST and deliberately forced another cold
start at 07:00 the following morning. The application returns only 16 bytes. The
header requests JSON; it does not guarantee how Render's startup proxy will respond.

Render can answer before the application is ready during a cold start. Its upstream
response can exceed cron-job.org's 64 KB limit, and startup can take longer than the
scheduler's 30-second request limit. A successful check while already warm does not
verify recovery from an idle service. HEAD remains supported by the application, but
it did not recover this scheduler's overnight outage on 11 October 2026: 26 consecutive
upstream HTTP 502 responses from 07:00 through 09:05 IST caused automatic deactivation.
The supplied application logs show the next startup at 09:13 IST, after deactivation;
they do not establish the underlying cause of those upstream errors.

On **17 October 2026**, the job was disabled with `Failed (output too large)` and
its retained history was empty. A test run reproduced that failure. A subsequent
direct GET with `Accept: application/json` returned the genuine 16-byte health JSON
after **31.6 seconds**; Render logged application startup at **10:06:09 IST**. This
confirms a cold-start/request-limit mismatch, not a daily expiry of the application
or a health endpoint that grows overnight. The discarded oversized response was
not available to establish its exact contents.

cron-job.org disables ordinary jobs after more than 25 consecutive failures. To
prevent that permanent stop, attach the existing job to a **Status Monitor**. On
17 October we reused the existing **BrainBloom Status** page, left **Publish status
page** unchecked, and added **BrainBloom workshop health**, selecting **Keep
BrainBloom warm**. This switches the job to the provider's supported **monitor
mode**: failures remain observable but no longer automatically disable the job.
No additional cronjob or public status page is required. The Add Status Monitor
dialog documents this behavior explicitly; the failure-notification checkbox on
the job itself does not change the deactivation policy.

If the application is asleep, use the GitHub workflow's **Run workflow** action
to recover it and confirm the health JSON. A warm test alone does not validate a
future cold start. Custom `User-Agent` headers are ignored by cron-job.org, so
changing that header is not a supported remedy. See its [FAQ](https://cron-job.org/en/faq/) and Render's
[idle-service documentation](https://render.com/docs/free#spinning-down-on-idle).

The GitHub Actions workflow is a backup, scheduled every ten minutes around the
clock. Actual runs can be delayed or skipped: the observed 15–16 October history
had gaps of several hours. It retries GET requests for a **420-second elapsed-time
budget**, with each request limited to the smaller of 100 seconds and the remaining
budget. This gives rapid proxy failures time to recover instead of exhausting three
attempts in about twenty seconds. It also gives repeated long timeouts another
chance: a recorded 14 October failure had exhausted three 100-second requests.
The workflow caps downloaded bodies and requires both HTTP 200 and the exact health
object, so HTML loading pages cannot count as readiness. When the budget expires it
fails visibly. It does not replace the primary scheduler or guarantee continuous
availability on the free service.

**Shared quota:** one instance running continuously consumes at most **744 hours**
in a 31-day month, close to the workspace's **750-hour shared allowance**. On
17 October the dashboard showed 51.08 hours used and a second service (`Analyser`)
in the workspace. There is room for the remainder of this month, but additional
free-service activity can exhaust the allowance in a future full month. Review
workspace usage before relying on multiple continuously running services. These
changes do not upgrade a plan or add paid capacity.

## Build it locally first

```bash
docker build -t brainbloom .
```

```bash
docker run --rm -p 10000:10000 -e BRAINBLOOM_PUBLIC_ORIGIN=http://localhost:10000 brainbloom
```

## What is deliberately not deployed

- **The ConceptNet-derived artifact and the `tools/` build chain** (~680 MB) stay out of the
  image; see `.dockerignore`. ConceptNet is CC BY-SA 4.0: the only ConceptNet-derived thing that
  ships is the frozen literal in `src/spie/conceptnet_data.py`, which remains under CC BY-SA 4.0
  and is attributed in `NOTICE`. SPIE's own code is Apache-2.0 (`LICENSE`); the share-alike
  obligation applies only to that derived data, not the code.
- **A browser-only version.** Pyodide ships clingo but not z3-solver, so live generation
  cannot run client-side. A pre-generated static bank is the alternative: the engine is
  seed-deterministic, so a baked bank is byte-identical to what the server would emit.
- **Any publishing or upload endpoint.** There still isn't one.
