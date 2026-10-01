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
arrives with its own `Host` and no `Origin` — is not rejected; it is static and bodiless.

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
