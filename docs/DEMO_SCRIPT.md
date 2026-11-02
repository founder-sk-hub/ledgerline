# Ledgerline: 3-minute demo video script

Record at 1440×900 with the browser zoomed to 110%. Use **Replay** of the recorded Muse Spark run at 4× speed, so
every number on screen comes from a real run. Speak calmly; the screen does the work.

| Time | Screen | Voiceover |
|---|---|---|
| 0:00 | Start screen, 32 document thumbnails | "Everything you'll see was built this week, for the Meta hackathon. I run a small business in Berlin. Every month a pile like this arrives: PDFs, phone photos, scans, emails, and now voice memos from my staff. Small businesses lose real money in this pile: duplicates, wrong VAT, price creep, short deliveries, and fake bank-detail emails." |
| 0:20 | Choose *Standard*, *Replay*, click **Replay the run** | "Ledgerline is an accounts-payable agent built on Meta's Muse models. One click, and it plans the batch." |
| 0:28 | Live run: stage stepper, timeline filling, Muse Spark badges | "Muse Spark reads every page: German and English, crooked photos, a scan with a KOPIE stamp. Each call shows its latency, tokens and cost." |
| 0:45 | Timeline row: **Muse Voice Transcribe**, then the voice-memo card | "This is Tom, my branch manager, in a voice memo. Muse Voice Transcribe hears that only 28 of 40 milk cans arrived." |
| 0:58 | Timeline row: **SAM 3.1 counted 9 × jute coffee sack** | "And here's a photo of a coffee delivery. Muse Spark decides *what* to count, and SAM 3.1 segments every sack: nine. The invoice bills ten." |
| 1:10 | Audit trail → the RGC-1022 invoice → open the delivery photo with the numbered boxes | "That's a three-way match, purchase order against invoice against what actually came through the door, done with a photo." |
| 1:25 | Audit trail → *Neue Bankverbindung* email: flags + verifier claims | "This one is the dangerous one: an email from kaffe**i**mport-hansa.com, one letter off, asking us to pay a Lithuanian account. The agent rejects it. It never uses bank details from a document, and it drafts a warning to the vendor's real contact." |
| 1:45 | Same screen: hover verifier claims so their boxes light up on the page | "Every decision goes through a second, independent Muse Spark pass that checks it against the original image and shows exactly where it found the evidence. If it can't confirm, a human decides." |
| 2:00 | Approval queue: payment batch, German emails, escalation | "Then it stops. It drafted the SEPA batch, always paid to the IBAN in our vendor master, and the emails to the vendors, in German. Nothing moves until I approve." |
| 2:15 | Approve all, **Create SEPA file**, download pain.001 | "I approve, and plain code, not the model, writes the bank file." |
| 2:25 | Start screen → *Private · on this laptop* → a replay or live run with the Muse Glimmer badge | "For businesses that can't send invoices to the cloud, the same agent runs on Muse Glimmer, Meta's open-weight model, right here on my laptop. No document leaves the machine." |
| 2:40 | Metrics: € at risk, minutes saved, 12/12 stopped, models-used panel | "On this month's batch: twelve problems caught, over eight thousand euros at risk, about four hours of bookkeeping saved, for about a euro of model cost. Five Meta models, each doing a real job. Ledgerline: let the agent do the checking, and you do the approving." |

## X post (for the Most Viral prize; post with the video, tag @AIatMeta)

> I built an AI bookkeeper for small businesses that **hears** voice memos, **counts** deliveries in photos, and
> **catches** fake bank-detail emails, then stops and waits for your OK before a single euro moves.
>
> 5 Meta models: Muse Spark · Muse Voice Transcribe · SAM 3.1 · Muse Glimmer (runs on my laptop) · Muse Image
>
> 32 messy docs → 12 problems caught → €8.3k at risk, in 3 minutes.
>
> Built this week for the @AIatMeta hackathon. Code: github.com/founder-sk-hub/ledgerline
