# Business plan: Ebook-to-Audiobook Web Converter

The financial and infrastructure counterpart to [Build plan: Ebook-to-Audiobook Web Converter](/documents/21432bcb/). The build plan covers what ships and in what order; this covers what it costs to run, what to charge, where the price edge comes from, and who else races to the same customer. Claims from lab sources are cited inline; everything else is marked as my inference. Numbers that are extrapolations rather than measurements say so.

## The edge, stated plainly

The operator's read is that at this phase the edge is price, and the material supports that read. The competitive floor is three free browser tools — [koby](/sources/ede1a6b571aa9d2c/), [Yaps](/sources/38f6f7e2c274839c/), [OfflineTTS](/sources/101410ae7c84e6f1/) — none of which delivers a finished single-file M4B of a whole book. The paid tier above them is expensive in two ways: professional narration at "$1,200 and $7,000 for a standard-length title" ([Narration Box](/sources/fa43135c148f6a9e/)), or a $5,000 narrator quote for a 90,000-word novel ([Camb.ai](/sources/2eac0a6815f73566/)); and subscription converters charging monthly for what is really a one-shot job. The wedge: finished whole-book M4B with captions, at a per-book price that makes the subscription converters look mispriced for this job, on infrastructure cheap enough that the low price is permanent, not promotional. That is a cost-structure moat, not a feature moat — and it is the kind this operator can hold, because it comes from the server bill, not from daily work.

## The right Hetzner box: a ladder, not a choice

The central infrastructure decision is not one box. It is a sequence, and the material prices every rung. All Hetzner figures here come from [the Effloow Hetzner cost guide](/sources/333120035aeda121/), which states its cloud prices are post-15-June-2026 rates and that "GPU server prices (GEX44, GEX131) were not affected" by that adjustment.

Rung 0 — the operator's own machine, Phase 1. The candidate record says "the engine already does this," so synthesis already runs somewhere. Measure cost per finished hour and run the blind quality test on that box at zero marginal cost. My inference: rent nothing until the Phase 1 script has produced numbers.

Rung 1 — a CPU cloud instance at launch. This is the rung the build plan implies but never prices, and it is the important one at low volume. Kokoro is a small model — 82M parameters — small enough that abogen runs it on CPU. Hetzner's current rates: CX23 (2 vCPU, 4 GB) €5.49/mo, CX33 (4/8) €8.49, CX43 (8/16) €15.99, CX53 (16/32) €29.49. A CPU box converts slowly — my unmeasured guess is hours for a full novel rather than the 30–60 minutes a GPU needs ([AudiobookGen](/sources/5ca3b88222050bad/) benchmarks a 90,000-word novel at 30–60 minutes; [Narratemi](/sources/c6d515f27d11fe74/) claims ~10–15 for 80,000) — but this product is a background job with email-when-done. A user who uploads at 9pm and receives their M4B at 7am is served. At launch volume, a €15.99–29.49 instance processes everything overnight and the GPU bill is zero. The Effloow guide's own warning applies here: its CX throughput discussion is about LLM tokens per second, not TTS, so CPU synthesis speed for Kokoro specifically is unmeasured. Phase 1 must measure it; that one number decides the launch architecture.

Rung 2 — the GEX44 dedicated GPU server, €184/month (~$211), NVIDIA RTX 4000 SFF Ada, 20 GB VRAM. Real characteristics that matter: €79 one-time setup fee, 1–3 business days provisioning, bare metal with manual NVIDIA driver install, and — the structural constraint — no spot or burst option: "It is flat monthly pricing or nothing." Offset against that: "Traffic is unlimited on most plans," which matters for an audiobook-sized download per job, and EU data centers with GDPR by default. Downsides to accept knowingly: possible waitlists on dedicated GPU servers, and no US data centers, so US users get upload and download latency — tolerable for an async job, but say so in the onboarding copy if US traffic grows.

Rung 3 — a second GPU box or the GEX131 class, only when the first saturates.

The trigger between rungs, my inference: move to the GEX44 when CPU turnaround breaches an overnight promise — call it when jobs queue more than ~12 hours. Before that the €184 GPU is a cost with no revenue attached; after that it is what keeps the price edge alive.

One caution on third-party pricing sites: [ComputeStacker's Hetzner page](/sources/d1c90f8c47a65843/) lists "RTX 4000 On-Demand $0.10/hr ~$73/mo," which contradicts Hetzner's own €184 GEX44 figure. Plan against the vendor's own price. The same page is useful for the alternatives column: Massed Compute RTX 4090 "from $0.20/hr," other providers "$0.35–0.45/hr" — hourly rental that costs more than the GEX44 if always-on but scales to zero when idle. My inference: idle time is the dominant cost driver early on, which is exactly why the CPU rung comes first; hourly GPU rental is the fallback if CPU throughput proves too slow to ship at all.

For scale context, the same guide prices the hyperscaler equivalent: AWS g5.xlarge (A10G) "about $1.006/hour — roughly $734/month," GCP g2-standard-4 (L4) ~$516/month. Hetzner is "roughly one-third the AWS cost" at the GPU tier and 60–80% under for always-on compute generally. Caveats the guide itself gives: AWS and GCP sell the same capacity much cheaper via spot and committed-use discounts, which "Hetzner has nothing equivalent to" against — honest to note, though for a small always-on workload the flat price is what matters.

## Unit economics

Synthesis math, from [abogen's GitHub page](/sources/38f6f7e2c274839c/): 3,000 characters into 3:28 of audio in 11 seconds on a laptop RTX 2060 — roughly 28× realtime. A typical novel at 500–700k characters is therefore around 9–10 finished audio hours, processed in roughly 20–35 minutes of GPU wall clock. Consistent with AudiobookGen's 30–60 minutes for a 90k-word novel. The RTX 4000 SFF Ada should beat a laptop 2060; treat the laptop figure as a conservative floor, not a promise.

Cost per book on the GEX44 — my arithmetic, marked as inference:

- Theoretical capacity at ~30 min/book: ~48 books/day, ~1,400/month.
- At 10% utilization (~140 books/month): €184 ÷ 140 ≈ €1.31 per book.
- At 30% utilization: ~€0.44 per book.
- Storage and bandwidth: effectively zero at Hetzner's flat rates, given the ephemeral-processing design — uploads and outputs deleted on delivery.

Marginal cost per finished book lands somewhere between €0.50 and €2 at early volumes, and the driver is idle capacity, not synthesis. That is the number pricing hangs off. On the CPU rung the per-book cost is comparable — a CX43 at €15.99 doing even 30 books a month is €0.53/book — but turnaround is hours, not minutes.

Fixed monthly stack at launch, my estimate: CX23 or CX43 for frontend and queue (~€6–16), small ephemeral object storage, domain and DNS (~€1–2), Stripe at ~2.9% + €0.30 per charge, €0 for synthesis until the GPU trigger fires. Under €50/month before the first GPU; under €220/month after. Break-even on a €9 pack: roughly 6 packs/month on CPU-only, roughly 25 with a GEX44 running.

## Pricing: the pack, and where it sits

Credit packs denominated in finished audio hours, per the build plan — this is an irregular one-shot purchase, and [AudiobookGen](/sources/5ca3b88222050bad/) sells explicitly on avoiding subscriptions: "a pay-per-use platform avoids the subscription costs that make audiobook production cost reduction difficult to achieve at scale." Size the pack so one pack ≈ one book, no awkward remainders.

My proposed ladder, all inference pending Phase 1 cost measurement:

- Free: one book per account, capped. The demo and the SEO proof. Costs €0.50–2 to serve; treat it as acquisition spend.
- €9 pack: 10 finished audio hours — one book. Undercuts a $9.99 monthly plan for anyone holding a single book, and sits 20–40× below per-hour ACX narration.
- €29 pack: 40 hours (~4 books). The reader with a shelf, or an author's start.
- €79 pack: 120 hours (~12 books). The author and indie-publisher seed from the build plan's Phase 5.

Guardrail: at €9 against a €0.50–2 cost, gross margin is 75–95% and the free tier absorbs heavy abuse before it matters. What breaks this pricing is Phase 1 discovering throughput far worse than the abogen figures — if a book costs €10 of compute, the pack and the free tier both collapse. That is why the build plan puts the measurement script before pricing.

Anchor pricing in marketing copy against the professional numbers, which are vendors' own: $1,200–7,000 per title (Narration Box), $5,000 quote for a 90k-word novel (Camb.ai), "$5,000-$15,000+ per book" for traditional production (Narratemi). Also worth remembering, from Narratemi: "Traditional audiobook production is expensive ($5,000-$15,000+ per book) and time-consuming, so many great books—especially indie titles—never get audio versions." That is the customer: the one who was never going to buy narration at any price, for whom €9 is not a discount but the first real offer.

## Who else races to the same customer

Watchlist, with what each means for a price-led position:

- The free tools. [koby](/sources/ede1a6b571aa9d2c/) is three months old, fully client-side, free; [Yaps](/sources/38f6f7e2c274839c/) is free on-device with hard bounds — 25 MB files, 6,000-character sections, "The tab retains the latest three generated sections," and "The ZIP action groups existing WAVs; it does not turn them into a merged track or an M4B audiobook." The threat is not their price; it is Yaps or a successor adding single-file M4B merging and lifting the caps, which erases the main paid gap. The counter: server GPU synthesis always beats phone-CPU synthesis on speed for big books, and finished-file convenience is our home ground.
- Subscription converters. Inkfluence's $9.99/mo for 15 chapters is the direct pricing comparison for a one-shot customer, and a bad deal for that customer — that is the pitch. [Narratemi](/sources/c6d515f27d11fe74/) gives free starter credits and a friendlier entry; watch its effective per-book price.
- Pay-per-use converters. [AudiobookGen](/sources/5ca3b88222050bad/) is the closest structural competitor — same pack instinct, same 30–60-minute benchmark. If it comes to a price war, our Hetzner cost base prices under a metered-cloud competitor permanently.
- The professional end. [Narration Box](/sources/fa43135c148f6a9e/) and [Camb.ai](/sources/2eac0a6815f73566/) compete on voice quality, cloning, and ACX compliance at professional prices — "ACX-compliant files that meet Amazon Audible's audio specs" — not our fight this phase, and their pricing is our best anchor copy.
- Model-side risk. Every tool on file, free and paid, runs Kokoro-82M or similar open models. If the license or voice terms change, or a better open model appears under different terms, everyone moves at once. Read the license before writing code — flagged in the build plan, still unread.
- Enterprise publishing platforms. [Kitaboo](/sources/1a3ee4af62a2231a/) embeds narration inside publisher workflows rather than converting a reader's file — adjacent, not competing, and evidence the SERP separates reader-side conversion from publishing workflow, which is the distinction our positioning should keep.

Market tailwind, as vendors selling into the market state it rather than as our own research: U.S. audiobook revenue "$2.22 billion … increasing 13% year over year" in 2024, global "approximately $8.7 billion in 2024 … forecast to surpass $35 billion by 2030" ([AudiobookGen](/sources/5ca3b88222050bad/)); "52% of U.S. adults have listened to at least one audiobook, and 38% listened within the past year."

## Risks specific to this plan

Single box, no spot. The GEX44 has no burst option and possible provisioning waitlists — a spike queues jobs instead of scaling. Acceptable for an async product; the email-when-done promise absorbs it.

Idle cost before demand. €184/month for a box converting three books a day is a bad trade; hence the CPU-first ladder.

No US region. Fine for async, slow for big uploads. Watch complaint volume before paying for a second region.

Price-led positioning invites a price war with better-funded players. The defense is the cost base — we can sustain prices a metered-cloud competitor cannot — but only while the per-book cost stays measured and honest. Re-measure quarterly.

Every market figure on this page is vendor-stated and every throughput number is extrapolated from one demo line. The Phase 1 script replaces both; quote nothing here to a customer until it does.

## Open questions

1. Actual CPU throughput for a full novel on a CX43/CX53 — decides whether launch runs on a €16 box or needs hourly GPU rental. Phase 1 measures it.
2. Whether the operator already owns a GPU that runs the engine — only the operator knows, and it pushes the first GEX44 decision back by months.
3. Measured cost per finished hour on the RTX 4000 SFF Ada, once rented. Everything in unit economics extrapolates from a laptop-2060 demo figure.
4. Kokoro model and voice license terms, still unread. Blocks commercial launch, not development.
5. Live prices at Narratemi, AudiobookGen, Inkfluence on publish day — the figures here are from their marketing pages as gathered, and a comparison page with a stale competitor price is worse than none.
