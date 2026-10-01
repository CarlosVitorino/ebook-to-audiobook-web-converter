# Build plan: Ebook-to-Audiobook Web Converter

Build and launch order for [turn ebooks into narrated audiobooks](/candidates/6931dbb7-8/): upload an EPUB or PDF, get back a narrated audiobook with captions. Every claim below rests on material the lab holds, cited inline to the source it came from. My own calls are marked as inference.

## The wedge

The engine exists and is proven. [abogen's GitHub page](/sources/38f6f7e2c274839c/) documents a MIT-licensed tool, 6,065 stars, last pushed 2026-09-07, that converts EPUB, PDF, TXT, MD and SRT into audio with synced subtitles using Kokoro-82M — and on an RTX 2060 laptop GPU it turns 3,000 characters into 3:28 of audio in 11 seconds. But it is a desktop tool: pip install, espeak-ng, CUDA setup. The people who want the output — readers with visual impairments, commuters, people with dyslexia, self-published authors — mostly cannot run it. The candidate's bet is that the gap is a web form in front of a known-good engine. My added observation: abogen's own install page is the proof of the gap, three operating systems and a troubleshooting FAQ for missing DLLs.

## What the free competition already gives away

Three free browser tools are on file. They define what a free tier is worth nothing, and therefore what anyone will pay for.

[koby.luarai.com](/sources/ede1a6b571aa9d2c/), posted on r/SideProject three months ago, is fully client-side: no upload, no signup, EPUB/PDF/Word input, built-in browser voices plus optional neural voices, read-along highlighting, speed up to 10x, sleep timer. Free.

[Yaps](/sources/101410ae7c84e6f1/) is free, on-device, no account, four preset voices, 31 languages, EPUB/PDF/TXT/Markdown. Its bounds are the opportunity: 25 MB file limit, sections capped at 6,000 characters, only the latest three generated sections kept in the tab, WAV at 5.29 MB per minute, "the web page itself does not remember your position tomorrow," and — the line that matters most — "The ZIP action groups existing WAVs; it does not turn them into a merged track or an M4B audiobook."

[OfflineTTS](/sources/38f6f7e2c274839c/) is free and browser-based, with a local bookshelf in IndexedDB and paragraph-by-paragraph generation cached as it finishes so a long book can resume. Its own privacy section admits the wrinkle: non-English Kokoro "sends the paragraph text being generated to api.offlinetts.com for phonemization."

The pattern: free tools do section-by-section work inside one browser tab, on the user's CPU, with browser voices, and none of them hands over a finished, chaptered, single-file audiobook of a whole book without the user babysitting generate-and-save steps. My inference: the payable job is whole book in, M4B with chapters and captions out, no babysitting. Speed and quality come with it — server GPU synthesis beats a phone CPU, and Kokoro output beats built-in browser voices.

The paid side confirms the shape sells. [AudiobookGen's own guide](/sources/5ca3b88222050bad/) sells pay-per-use and opens with market numbers: "$2.22 billion revenue; 13% YoY growth" in U.S. audiobooks for 2024 (attributed to Booketic, from Audio Publishers Association data) and global revenue "approximately $8.7 billion in 2024 … forecast to surpass $35 billion by 2030." It also gives a conversion benchmark: "a 90,000-word novel typically takes 30–60 minutes." [Narration Box](/sources/fa43135c148f6a9e/) sells a studio with expressive multilingual voices, voice cloning from a 20–60 second sample, and ACX-compliant export, and its own cost framing is the anchor price: recording a professional audiobook "can cost anywhere between $1,200 and $7,000 for a standard-length title." [Narratemi](/sources/c6d515f27d11fe74/) sells the same thing at a friendlier price point with free starter credits, and states the conversion speed our product will be judged against: "Average novel (80,000 words): ~10-15 minutes." Those market figures are as stated by vendors selling into the market, not our own research.

## Copyright: the stop condition, resolved

The brief says the project stops on copyright issues. The lab's material already contains the workable line, stated twice independently.

Narratemi's FAQ: "Yes, for personal use. If you've purchased an ebook, you have the right to format-shift it for your own use—the same principle that allows you to rip CDs to MP3. You cannot distribute or sell the resulting audiobook." AudiobookGen's prerequisite section: "The single most important prerequisite is having a DRM-free EPUB file." Audiobookify: "Only convert ebooks you own or have permission to use."

So the rule for us: accept DRM-free EPUB, text-based PDF, and TXT. Reject AZW/AZW3/KFX/MOBI by file type — a hard rejection, not a warning. Say "DRM-free books you own" in the product copy itself. Delete uploads and generated audio shortly after delivery; run no cloud library, no sharing, no public shelf. My inference: ephemeral processing is simultaneously the legal posture, an ops saving, and a cost saving — audiobook-sized files never get stored twice.

One caution, mine: Narratemi's instruction to run Kindle files through Calibre conversion is a step I would not copy into our own copy. Telling users how to strip DRM is a different posture from accepting DRM-free files. Narratemi can say it; a small new entrant should not.

## Architecture

Reuse the proven engine; do not rebuild it. From here to the end of this section is my inference — the lab holds no architecture notes.

1. Engine. Kokoro-82M behind abogen's pipeline or its equivalent: EPUB spine-aware text extraction, sentence splitting, per-sentence timestamp capture for caption sync, batch synthesis. abogen already produces M4B with chapters and SRT/VTT/ASS/LRC subtitles at line, sentence, or word granularity — its feature list is effectively our product spec. Read the Kokoro model license and voice terms before writing code; I have not verified them myself.
2. Job model. Upload to object storage, enqueue, one GPU worker pulls jobs. A full novel is roughly 500–700k characters; scaling abogen's 11s-per-3,000-chars linearly puts a whole book around 30–50 minutes of wall clock on a modest GPU — consistent with AudiobookGen's 30–60 minutes for a 90k-word novel. That is a background job with progress and an email-when-done, not a request/response. Worker writes M4B plus captions back to storage; user downloads; a cleanup job deletes everything after a fixed window.
3. Chunking and normalization. Split at paragraph boundaries, never mid-sentence. Text normalization — expanding "Dr.", "100", "etc." — is the difference between tolerable and good narration; AudiobookGen's QA checklist is effectively the acceptance test: listen to the opening, a middle, and the final chapter, check proper nouns and pacing, verify chapter markers and cover metadata.
4. Frontend. One page: dropzone, voice picker, progress, download. Server-rendered, fast, tool-shaped. The product promise is that the job finishes while the user makes coffee.
5. Voice licensing check before launch. Ivona-style voices are locked (the koby builder hit this: "the license doesn't allow using them elsewhere"), and browser neural voices have their own terms. Kokoro's voices are open, which is why every free tool uses them — and that is also the warning: the paid differentiator cannot be a voice nobody else has. It is convenience, quality over browser voices, and the finished M4B.

## Monetization: the pack model, sharpened

The brief's instinct — one free, then buy a pack — matches how this market already prices, with one refinement.

Free tier: one full-book conversion per account, ever or per month. It costs real GPU minutes, so it must be capped per account, not per session or IP.

Paid: credit packs, not a subscription, denominated in finished audio hours. Evidence for the shape: AudiobookGen sells explicitly on "a pay-per-use platform avoids the subscription costs that make audiobook production cost reduction difficult to achieve at scale," and this is an irregular one-shot purchase — someone converts a book and may not return for weeks. Narratemi's free-credits-then-account model is the same idea with subscription economics behind it. Price off measured GPU cost: at the extrapolated throughput above, a rented GPU spends well under a dollar of compute per full novel — my back-of-envelope from abogen's demo figure, not a measured number. Measure dollars per finished hour in Phase 1, then price the pack at a multiple that also covers storage, bandwidth, payment fees, and the free tier.

Second lever, later: an author tier. The sibling framing recorded on the candidate — indie publishers skipping audio because per-title narration runs $200–400 per finished hour — is the anchor that makes a $10-per-book tool look free, and authors have the repeat-purchase behavior packs want. The operator can already write the editorial content that reaches them.

## Order of work

Phase 1 — prove the engine end to end, no web. One script: EPUB in, M4B and captions out, on a rented GPU box. Measure minutes of audio per wall-clock minute and dollars per finished hour. Everything downstream prices off that number. If quality disappoints against a real browser neural voice in a blind listen, stop here and reconsider — every later step assumes Kokoro clears the bar.

Phase 2 — the web form. Upload, queue, progress, email-on-done, download, deletion, the DRM rejection list, the landing page written in the personal-use and accessibility frame. This is a shippable free product on its own and is how the first users arrive.

Phase 3 — pack payments. One SKU, Stripe, credits per finished hour. Ship it only after real users have finished real books, so the free cap is set from observed usage rather than guessed.

Phase 4 — SEO, the compounding channel that fits this operator. The SERP is already full of the exact page shapes to build, and they are aging: [kitaboo's converter roundup](/sources/1a3ee4af62a2231a/), [Narration Box's 2026 guide](/sources/fa43135c148f6a9e/) at 11 months old, [Narratemi's complete guide](/sources/c6d515f27d11fe74/) at 8 months, [Frateca's](/sources/535b818f441cb558/) at 3 months, [Camb.ai's](/sources/2eac0a6815f73566/) at 6 months, [Audiobookify's](/sources/bf87016e5b260dd0/) last updated June 2026. Build the honest versions: how-to guides, format explainers (EPUB versus scanned PDF, what DRM-free means), and one genuinely fair comparison page that names the free browser tools and says when they are the better choice — which is most single-chapter cases, and costs nothing to admit, because the sale here is whole books. Manual SEO compounds and matches how this operator already works. No social channel required.

Phase 5 — author tier and batch upload, only if Phase 4 traffic shows authors in the mix.

## What waits until later, deliberately

Scanned-PDF OCR — Yaps punts on it ("scanned pages need text extraction before narration") and every tool on file punts; it is a second pipeline, not a flag. Voice cloning and premium voices — Narration Box and Camb.ai compete there already, and it adds a consent and licensing surface; not our first fight. Distribution to stores — Narratemi's own framing is the boundary: personal use only, "distributing them is not" legal, so store-ready distribution is a different product with different rights. Non-English languages — OfflineTTS's phonemization endpoint shows the extra infrastructure; English first. Accounts and cloud bookshelves — everything says stay ephemeral. Mobile apps — the web form works in a phone browser.

## Open questions this plan does not answer

1. Measured cost per finished hour on a real GPU instance. All pricing here rests on an extrapolated 11s/3,000-char figure.
2. Whether Kokoro is visibly better than the free neural browser voices koby already offers, in a blind test. The free tier makes this the live willingness-to-pay question. Test in Phase 1, not after launch.
3. Whether a second r/SideProject launch lands, or whether SEO must carry launch alone. koby's post is three months old; that well can be re-dug but not twice.
4. Kokoro's model license and voice terms, read directly. Noted, not verified.
5. Where the free-tier line sits. One book per account is a guess; Phase 2 usage data settles it.
