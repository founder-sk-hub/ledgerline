# Submission form answers (Cerebral Valley)

Paste each block into the matching field.

**Team Name:** Ledgerline

**Track:** Startups Track · **Problem statement:** Build for Your World

**Public GitHub Repository:** https://github.com/founder-sk-hub/ledgerline

**3-Minute Demo Video:** https://youtu.be/Ha7zp2gprn0

**X post link (optional, only for the Most Viral bonus prize):** leave empty if you don't post on X

---

**Project Description**

An invoice bills 600 kg of coffee, ten 60 kg sacks. The receiving photo shows nine. Ledgerline links the invoice,
the purchase order and the photo, flags the EUR 426 difference, and drafts a supplier email for review.

Ledgerline is an accounts-payable agent for small food businesses. It checks supplier bills against purchase
orders, contracts, VAT rules, payment history and what actually arrived (a staff voice memo or a delivery photo).
It holds or rejects what's wrong, drafts a SEPA payment file and supplier emails, and stops for a person to
approve. Every model call, tool result and decision is logged and can be replayed.

In a recorded run on 32 synthetic documents (a fictional coffee roaster), it stopped all 12 planted problem
documents with 100% flag precision and recall and 31/32 correct decisions. It flagged EUR 8,339 at risk in
5.8 minutes for $1.25 of model calls. That is one synthetic scenario, not measured customer results.

Try it in the browser (replays of recorded runs, you are the approver): https://founder-sk-hub.github.io/ledgerline/

---

**Describe your use of Meta products to build the submitted project**

- **Muse Spark 1.3 (Meta Model API)** reads each page image or email into structured fields with bounding-box
  evidence (vision, strict JSON schemas). It runs the investigation as a tool-calling loop over deterministic
  checks (vendor master, PO and contract, VAT, duplicates, goods receipt), writes supplier emails in German or
  English, and makes a second pass that checks each decision against the source image.
- **Muse Voice Transcribe** turns a German staff voice memo ("only 28 of 40 cans of milk came") into evidence. The
  vendor names are used as vocabulary bias.
- **SAM 3.1** counts delivered goods in a receiving photo. Muse Spark decides what to count ("jute coffee sack"),
  SAM segments every instance, and the count feeds a three-way match.
- **Muse Glimmer** runs the same agent on a laptop through Ollama (private mode, no document leaves the
  machine). A six-document run is recorded. It is slower and less precise and has no voice memos or SAM.
- **Muse Image** generated the one synthetic delivery photo in the sample data, during development only.
- Muse Spark Open on Baseten is configured as an optional engine (model `meta-models/muse-spark-open-1026`). Built
  with Muse Spark Open.

---

**Why are Meta's models important to your solution?**

The evidence that proves an invoice wrong is rarely a clean PDF. It is a crooked phone photo, a stamped scan, a
supplier email, a voice note from the back door, or a picture of the pallet. Ledgerline needs one model family
that reads images and PDFs, follows strict schemas and calls tools reliably (Muse Spark). It also needs speech
recognition that handles German with English mixed in (Muse Voice Transcribe) and pixel-level counting (SAM 3.1),
all from the same API. Because Meta also publishes open weights, the same agent can run on the business's own
machine with Muse Glimmer. That matters to small German businesses that don't want to send invoices to a cloud.

---

**Feedback on partner technologies (optional)**

Meta Model API was quick to integrate through the OpenAI SDK. Two things cost us time:
- `tool_choice` accepts only `"auto"`.
- Strict structured output needs every property required and `additionalProperties: false`; without that the
  model invented keys.

SAM 3.1 counted all nine sacks on the first try. Muse Glimmer on Ollama's MLX engine has no constrained decoding
and defaults to long reasoning; `reasoning_effort: "low"` made it about three times faster.

**Biggest obstacle:** finding clear documentation for structured-output limits, and slow local inference for the
open-weight model.

---

Before you submit, check:
- the repo is public (it is);
- the consent checkbox at the end of the form is ticked.
