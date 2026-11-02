# Submission text (Cerebral Valley form)

**Track:** Startup · **Theme:** Build for Your World

**Project name:** Ledgerline

**One-liner:** A verifiable accounts-payable agent for small businesses. It reads every invoice, hears staff voice
memos, counts deliveries in photos, catches the expensive mistakes, and stops for human approval before any money
moves.

**Links**
- Repo: https://github.com/founder-sk-hub/ledgerline
- Live demo (in the browser, no install): https://founder-sk-hub.github.io/ledgerline/
- Demo video: <YouTube link>

**Description**

Small businesses lose real money in their monthly invoice pile: duplicates, creeping prices, wrong VAT, short
deliveries and fake bank-detail emails. Ledgerline is an agent that does the checking a careful bookkeeper would
do, and shows its work.

Drop in a messy month: PDFs, phone photos, a stamped scan, supplier emails, a staff voice memo, a photo of a
delivery. **Muse Spark 1.3** plans the batch and reads every page, returning structured data with bounding-box
evidence. **Muse Voice Transcribe** turns the branch manager's German voice memo into evidence. For delivery photos,
Muse Spark decides *what* to count and **SAM 3.1** segments and counts it, which enables a three-way match of
purchase order, invoice and what actually arrived. An investigator agent calls deterministic tools for the vendor
master, PO and contracts, VAT rules, duplicates and goods receipt. Code does the arithmetic and computes the EUR at
risk; the model decides what it means. A second, independent Muse Spark pass verifies every decision against the
original image and escalates anything it can't confirm. A drafting agent prepares the SEPA batch (always to the
vendor-master IBAN) and vendor emails in the vendor's language. Then it **stops**: a human approves every
payment, email and exception, and plain code writes the pain.001 file. Every step is an append-only event, so the
audit trail is replayable and answers "why did it do that?".

For privacy, the same agent runs on **Muse Glimmer** (open weights) entirely on a MacBook via Ollama: no document
leaves the machine.

**Results** on a 32-document synthetic benchmark, scored against planted ground truth the agent never sees:
12/12 anomalies stopped, 100% flag recall and precision, 31/32 decisions correct (the other was escalated to a
human after the two passes read a blurry IBAN differently), EUR 8,339 at risk caught, in 5.8 minutes, for $1.25
of model calls.

**Meta models:** Muse Spark 1.3 · Muse Voice Transcribe · SAM 3.1 · Muse Glimmer (on-device) · Muse Spark Open
(optional private server) · Muse Image (generated one synthetic sample photo).

**Built during the hackathon:** everything in the repo was written Oct 26 – Nov 4, 2026 (see the git history).
Synthetic data only.
