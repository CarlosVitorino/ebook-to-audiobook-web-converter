# One host, two products

narrator.guru and BuildCase move onto a single VPS and share one Caddy. This file is the plan
for that move as it concerns *this* repo. BuildCase keeps the mirror of it at
`venture-lab/docs/18-the-shared-host.md`; the two must agree, because they are describing one
machine.

`docs/deploy.md` still describes the single-product server, and most of it stays true — domain,
`.env`, Creem, search engines, the launch checklist. What this file supersedes is step 4: this
project no longer runs its own Caddy and no longer owns ports 80 and 443.

---

## 1. The host

Everything after this section is written for an **8-core / 16 GB / NVMe** host, and that shape
is the only host-specific assumption in the file. Changing provider means changing §1 and
nothing else.

**Chosen: OnetSolutions HP-16** — 8 vCPU (AMD EPYC 9554, Zen 4, 3.1–3.75 GHz), 16 GB DDR5,
160 GB NVMe, 1 Gbps, France. €31.99/mo net monthly, €25.59/mo net paid annually.

**Start on the monthly term, not the annual one.** Annual is 20% cheaper and there is no
renewal increase — genuinely rare, and the main reason to pick them. But two things stay
unresolved until the machine exists: independent review of the live order form reports the VPS
line carries *no advertised money-back guarantee*, despite a 30-day claim elsewhere on the
site; and the platform is sold as "KVM, isolated resources" rather than dedicated cores. One
month at €31.99 answers both without needing a refund to exist. Move to annual once §8 passes.

The switch itself is self-service and costs nothing operationally. The console prices the move
first and then creates a prorated invoice; the API describes it as changing the cycle "without
touching the hardware", and it takes effect when that invoice is paid. No migration, no
reinstall, no ticket. It is **one-way** — only longer cycles are offered, so annual back to
monthly would mean cancelling and rebuilding.

The deadline that matters runs the other way: **services auto-renew unless cancelled at least
15 days before expiry**, so on a monthly term the decision to leave has to be made around day
15, not day 30. Put that date in a calendar on the day the server is ordered. (For contrast,
netcup has no equivalent self-service switch — its own forum tells customers to open a ticket
with support, which is the part of netcup with a documented multi-day backlog. There, pick the
term at order time.)

**Fallback: netcup RS 2000 G12.5** — 8 *contractually dedicated* cores (EPYC 9645, Zen 5c),
16 GB, 256 GB NVMe, 99.9% SLA, €34.20/mo net on a 12-month term. About €103/year more for a
dedicated-core guarantee and 96 GB more disk. This is where to go if §8 shows steal time.

Hetzner was the original plan and is no longer in the running: the whole Cost-Optimized line
(CX/CAX, including the CX53 this document first specified) is unavailable to order, and the
nearest equivalents are CPX42 at €69.99 or CCX33 at €138.99.

### Why AVX-512 decides this

Kokoro-82M inference on CPU leans on AVX-512. It is the one hardware property worth paying for
here, and the one most hosts decline to publish:

| CPU generation | AVX-512 |
|---|---|
| Zen 2 — EPYC 7282 (Contabo VDS) | no |
| Zen 3 — EPYC 7313 (Clouvider), EPYC 7443 (OnetSolutions **P** line) | no |
| Zen 4 — EPYC 9554 (OnetSolutions **HP** line) | **yes** |
| Zen 5c — EPYC 9645 (netcup RS) | **yes** |
| Intel Xeon E5-2680 v4 (OnetSolutions **GP** line) | no |

Note the last row. The "General Purpose" line runs 2016-era Xeons, is what the homepage steers
you toward, and costs *more* than High Performance at every tier where both exist. **Order HP.**

The 9554's 3.1 GHz base is well above the 9645's 2.30 GHz — netcup's part is a dense 96-core
design that trades clock for core count. Per core, the cheaper host may be the faster one. That
is a reason to measure (§8), not a reason to assume.

## 2. Shape

```
host (8 vCPU · 16 GB · NVMe)
├─ docker network: edge (external, created once)
├─ edge/compose.yml      caddy:2 — the only thing listening on :80 and :443
├─ buildcase             postgres · migrate · web (buildcase-web:4321) · worker
└─ narrator              web (narrator-web:8000) · worker
```

Caddy lives in the BuildCase repo at `deploy/edge/`. That is not a statement about ownership —
it is simply where it was written first, and one copy is the point. It terminates TLS for every
site on the host and reaches each app by its service alias on the `edge` network. Nothing else
publishes a port.

## 3. What changes in this repo

### 3.1 Give up port 80 and 443

`docker-compose.prod.yml` currently starts its own Caddy. Two Caddies cannot both bind 443, so
it goes. The replacement joins the shared network instead:

```yaml
# On the server: docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
# HTTPS is not ours any more: the shared Caddy on the `edge` network terminates TLS for every
# site on this host. See docs/shared-host.md.
services:
  web:
    environment:
      FORWARDED_ALLOW_IPS: "*"   # trust the edge proxy's X-Forwarded-For, so rate limits see the real visitor
    ports: !reset []             # nothing on the host; the only way in is through Caddy
    mem_limit: 512m
    networks:
      default: {}
      edge:
        aliases: [narrator-web]

  worker:
    cpus: 6
    cpu_shares: 256
    mem_limit: 3g
    environment:
      ONNX_THREADS: 6

networks:
  edge:
    external: true
```

`ports: !reset []` needs Compose v2.24 or newer, which is what `get.docker.com` installs today.

`FORWARDED_ALLOW_IPS: "*"` is now trusting anything that can reach the container on `edge`,
which is every other container on this host rather than only Caddy. Everything on `edge` is
ours, so this is accepted rather than fixed. It stops being acceptable the day something runs
here that we did not write.

### 3.2 The CPU split

The limits above are the whole contention plan, and on 8 cores it is a real trade rather than
insurance. The reasoning is worth keeping because it is easy to get wrong:

- **`cpus: 6`** is a ceiling, not a reservation. It guarantees the lab 2 cores by denying them
  to narration, which is the only direction a ceiling works in. Two cores is enough for
  Postgres, Astro SSR and one Chromium context; it is not enough for two, which is why
  `VL_WORKER_CONCURRENCY` starts at 1 on the other side.
- **`cpu_shares: 256`** against the default 1024 is what hands the cores *back*. When both are
  busy the kernel splits contested CPU by cgroup weight, so the lab wins 4:1. Without this,
  `cpus` alone would let narration hold its 6 cores while the lab queued.
- **`nice` would do nothing here.** Each container is its own cgroup and the kernel divides CPU
  between cgroups by weight; `nice` only ranks processes *within* one. It cannot make narration
  yield to the lab because they are not in the same group.

### 3.3 Tell ONNX Runtime how many cores it actually has

This is the part the limits above do not cover on their own. `app/narrate.py` builds
`Kokoro(...)` with default session options, and **ONNX Runtime sizes its intra-op thread pool
from the host's core count, not from our cgroup quota.** On this host it would start 8 threads
and then be throttled against a 6-core budget, losing real throughput to context switching and
CFS throttling. It has to be told:

```python
import onnxruntime as rt

ONNX_THREADS = int(os.environ.get("ONNX_THREADS", "0"))


def kokoro() -> Kokoro:
    global _kokoro
    if _kokoro is None:
        model = os.path.join(MODEL_DIR, "kokoro-v1.0.onnx")
        voices = os.path.join(MODEL_DIR, "voices-v1.0.bin")
        if ONNX_THREADS:
            # ORT reads the host's core count, not our cgroup quota, and oversubscribes.
            opts = rt.SessionOptions()
            opts.intra_op_num_threads = ONNX_THREADS
            _kokoro = Kokoro.from_session(
                rt.InferenceSession(model, opts, providers=["CPUExecutionProvider"]),
                voices,
                espeak_config=_espeak(),
            )
        else:
            _kokoro = Kokoro(model, voices, espeak_config=_espeak())
    return _kokoro
```

Default of `0` keeps local development exactly as it is today. `ONNX_THREADS` must track
`cpus`: if one moves, move the other.

Kokoro-82M is small enough that intra-op scaling flattens out well before 8 threads, so capping
at 6 should cost less than the core count suggests. "Should" is doing work in that sentence —
it is an expectation, not a measurement (§8).

### 3.4 Memory

`mem_limit: 3g` on the worker, not 8g. The audio path streams: `narrate()` writes into a
`SoundFile` on disk sentence by sentence rather than accumulating the book in RAM, so peak RSS
is the ONNX arena — roughly 1.5–2 GB. A 3 GB cap actually catches a runaway; an 8 GB cap on a
box whose other tenant is Postgres mostly guarantees that the OOM killer reaches Postgres
first, which is the outcome the cap exists to prevent.

The host budget, all limits summed:

| | |
|---|---|
| BuildCase postgres · web · worker | 2 + 1 + 4 GB |
| narrator web · worker | 0.5 + 3 GB |
| Caddy | ~50 MB |
| **Total capped** | **~10.5 of 16 GB** |

That leaves ~5.5 GB for the kernel and page cache. It is enough, but it is no longer generous
the way 32 GB was, and the caps are now the thing keeping the machine honest rather than a
formality. Raising any `mem_limit` on either side is a change to a shared agreement, not a
local decision. The swapfile in §5 stops being optional for the same reason.

### 3.5 Disk

160 GB, and the thing to watch is not the finished audiobooks. `narrate()` writes an
intermediate `book.wav` at PCM_16 24 kHz — **about 172 MB per hour of audio** — before ffmpeg
encodes it to 64k AAC at ~28 MB per audio-hour and deletes the WAV. A 10-hour book transiently
needs ~1.7 GB. One book at a time, so that is the peak, not a multiple.

Steady state is 7 days of finished M4Bs, which at any plausible launch volume is single-digit
GB. Against ~30 GB of OS, Docker images, Postgres and Chromium, 160 GB still has room — but it
is 96 GB less room than the netcup fallback, and this is the resource that runs out quietly.
**This project and Postgres share one filesystem**: a disk filled here takes the lab down with
it. Alerting on disk is worth more than alerting on CPU.

## 4. The edge Caddyfile

Add to `deploy/edge/Caddyfile` in the BuildCase repo, where a commented placeholder for this
project is already waiting:

```caddyfile
narrator.guru {
	encode zstd gzip
	request_body {
		max_size 110MB
	}
	reverse_proxy narrator-web:8000
}

www.narrator.guru {
	redir https://narrator.guru{uri} permanent
}
```

**`request_body` is the easiest thing here to forget.** It is in this repo's own `Caddyfile`
and absent from the edge one. Caddy sets no body limit of its own, so dropping the directive
does not break uploads — it does something quieter: a 200 MB file is streamed all the way to
the app before anything rejects it, instead of being refused at the edge with a 413. Carry it
over so the behaviour matches what is deployed and tested today.

## 5. Host setup

**Ubuntu 26.04 LTS (Resolute Raccoon)**, supported to April 2031. It is past its first point
release, Docker publishes a `resolute` repository so `get.docker.com` works, and `systemd` 259
has dropped cgroup v1 entirely — which only confirms the v2 semantics §3.2 depends on. Almost
nothing of ours runs in host userspace, so the newer base costs little.

Two defaults changed in the run-up to this release and are worth knowing before a shell script
behaves oddly: `sudo` is now `sudo-rs` (the original is `sudo.ws`, and `sudo-ldap` is gone), and
the core utilities come from `rust-coreutils` rather than GNU. `cp`, `mv` and `rm` are still
GNU; the rest are not, and any GNU-only flag in a script can be reached with a `gnu` prefix, as
in `gnuls`. `deploy/backup.sh` uses only portable options, but it is the kind of thing to check
after the first nightly run rather than assume.

Then, once, on a fresh server, before either project starts:

1. `curl -fsSL https://get.docker.com | sh`
2. `docker network create edge`
3. Firewall: inbound 22, 80, 443 only. Use the provider's network firewall if there is one — it
   sits in front of the NIC and cannot lock you out. OnetSolutions offers a configurable
   firewall in its console; if it proves limited, fall back to `ufw` on the host and be careful
   to allow 22 **before** enabling it.
4. 4 GB swapfile, `vm.swappiness=10`. At 16 GB with ~10.5 GB capped this is necessary, not
   insurance — an OOM kill on Postgres is a real outcome here rather than a theoretical one.
5. `unattended-upgrades` for security patches.
6. `/etc/docker/daemon.json` with `log-driver: json-file`, `max-size: 10m`, `max-file: 5`.
   BuildCase sets this per service; this project does not, and an unrotated container log is a
   slow-motion disk-full.

This is all declarative enough to be a cloud-init user-data file, which is the better form: the
server configures itself on first boot from something readable beforehand.

## 6. Backups

Two products, two kinds of state, both needed:

- **This project** — SQLite holds accounts and purchases. The cron in `docs/deploy.md` §7 keeps
  14 daily copies in `data/backups/`. Audiobooks are not backed up: they expire in 7 days.
- **BuildCase** — `deploy/backup.sh`, nightly `pg_dump`, 14 kept.
- **Both** — copy the dumps off the host. A backup on the disk it protects is not a backup.
  This is the part that actually matters, because the provider add-on below may not be bought.

**On OnetSolutions, automated daily backup is a paid extra at about €4.99/mo and on-demand
snapshots about €2.99/mo**, despite the plan cards listing daily backup as an included feature.
Verify the price in the cart rather than on the marketing page. Their backup is written to a
second datacentre more than 100 km away with no stated storage cap, which is better than the
market norm — but the two cron jobs above, shipped off-host, are the baseline and do not
depend on buying it.

One secret needs backing up outside the database: BuildCase's `VL_CREDENTIAL_MASTER_KEY`.
Losing it makes stored tokens unreadable and no dump will help.

## 7. Order of operations

1. Order the host **on the monthly term** (§1). Run §5.
2. **Before anything else, `lscpu | grep -o avx512f`.** If that prints nothing, stop: the CPU
   is not what was advertised, and the right move is to leave inside the first month rather
   than build on it. Everything after this step assumes it printed something.
3. Point `narrator.guru`, `www.narrator.guru` and `buildcase.dev` at it. Let DNS settle before
   starting Caddy — repeated certificate failures against a name that does not resolve count
   against Let's Encrypt rate limits.
4. Start the edge Caddy with `ACME_EMAIL` set.
5. Bring up BuildCase. Confirm TLS and sign-in.
6. Make the changes in §3 here, add the Caddyfile block from §4, bring this up.
7. Convert a real book end to end: upload, confirm, narrate, email, download, plays in Apple
   Books.
8. **Measure §8 while that book runs.** This is the decision point, and it has a deadline: the
   results either justify switching to the annual term in the console, or justify cancelling —
   and cancelling has to be filed by about day 15 of the month (§1).
9. `/stats` reports the speed multiple against real time. Put it in `NARRATION_SPEED` and
   restart, so the confirm page's "ready in about" tells the truth. If it disagrees with the
   landing page's Gatsby line (~6×), the copy changes, not the number.
10. Run the rest of the `docs/deploy.md` §9 checklist.

## 8. What to measure, and what is still unknown

**Narration speed on this host is not known.** The 5× in `NARRATION_SPEED` is a default and the
~6× on the landing page is from a different machine. This matters more than it looks: at one
book at a time, the speed multiple *is* the throughput ceiling. At 4× a 10-hour book takes
2.5 hours and the worker tops out near 9 books a day.

In order, during and after the first real book:

- **`lscpu | grep avx512`** — pass/fail, and the only one that is worth leaving over.
- **Steal time.** `vmstat 1` during a saturated run, the `st` column. This is the empirical
  answer to the question the marketing copy dodges: "KVM, isolated resources" is not a
  dedicated-core guarantee, and sustained non-zero steal means the cores are contended. If it
  climbs, move to netcup and stop arguing with the wording.
- **Speed multiple** from `/stats` at `ONNX_THREADS=6`. Then try 8 once, with the lab idle, to
  learn what the cap is costing; if 8 is not meaningfully better, 6 was free.
- **Disk.** OnetSolutions scores poorly on independent disk-IO testing, and this workload
  writes ~172 MB per audio-hour. Run `fio` once, and watch whether the WAV write phase becomes
  the bottleneck rather than inference.
- **Peak worker RSS** during a long book, against the 3 GB cap.

## 9. Risks taken knowingly

- **One host, two products.** A kernel panic, a full disk or a bad `docker compose` takes both
  down. Accepted because both are pre-revenue and the cost of two hosts is not only money.
- **No contractual dedicated-core guarantee.** The host sells "KVM, isolated resources". §8
  tests it; the netcup fallback is what buys the guarantee outright if the test fails.
- **The provider's own documentation is unreliable.** Independent review found the FAQ
  promising dedicated servers, phone support, live chat and free backups — none of which exist
  — and advertised 10-second provisioning that measures nearer three minutes. Treat the cart as
  the source of truth and the marketing pages as decoration. The flat renewal pricing, which is
  the actual reason to be here, is the part reviewers consistently confirm.
- **Support is tickets and email, with no phone and no escalation path**, and reported response
  latency is erratic. Two documented cases of silence during real incidents. This is a real
  cost of the price.
- **Thin independent reputation.** Effectively no Reddit footprint, two LowEndTalk threads in
  fifteen years, and a Trustpilot average resting on pre-2024 reviews. The one historic "scam"
  thread reads, on inspection, as a 2016 complaint about Minecraft tick rate on OpenVZ and was
  dismissed by that forum at the time. Absence of evidence, in both directions.
- **The worker restarts books from the beginning.** Rebuilding the `worker` service loses a
  book in progress. Deploy this project when the queue is empty, or accept the re-run.
- **One Caddy is a single point of failure for both sites.** It is also one certificate store
  and one config to get wrong. Worth it against running two proxies on one host, which cannot
  be done at all without giving one of them a non-standard port.
