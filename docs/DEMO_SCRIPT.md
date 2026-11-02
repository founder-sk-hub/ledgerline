# Demo video (about 3:00)

`docs/video/ledgerline-demo.mp4` is produced by `backend/scripts/demo_video.py`. The script drives the real app (a
replay of the recorded Muse Spark run) at 1920×1080 with chapter cards, camera zooms and captions. The narration
comes from `docs/video/narration_v2.json` (`demo_voice.py`, ElevenLabs, the founder's own voice), plus seven
seconds of the synthetic staff voice memo. All documents in it are synthetic.

| Scene | On screen | Narration |
|---|---|---|
| Opening | Title card, then the 32 documents | Hi, I'm Sinda, a founder from Rothenburg ob der Tauber. Every month, small food businesses get a pile of supplier bills: PDFs, phone photos, emails, even voice notes from staff. Checking them takes hours, and mistakes cost real money. |
| Intro | Start screen, engine choice | Ledgerline is an AI bookkeeper built on Meta's Muse models. It checks every bill against your own records, and it never pays anything without you. |
| 1 · It reads everything | Replay of the recorded run, counters climbing | Muse Spark reads each document, German or English, crooked photos, even a stamped copy, and plans the work. Everything you see is from a real recorded run. |
| 2 · It checks against your books | Delivery photo with SAM's numbered boxes, then the held invoice | Here's a photo of a coffee delivery. Muse Spark decides what to count, and SAM 3.1 finds every sack: nine. But the invoice charges for ten. Ledgerline holds it and asks the supplier for a credit. |
| | Voice memo player and transcript, then the held milk invoice | (the memo itself) This is a voice memo from the cafe manager: only twenty-eight cans of milk arrived. Muse Voice Transcribe turns it into evidence, and the milk invoice is held too. |
| 3 · It catches what people miss | The lookalike-domain email, its flags, the second-pass claims | This one is dangerous: an email asking us to pay a new bank account. The domain is one letter off. Ledgerline rejects it and warns the real supplier. Every decision is checked a second time against the original, with the evidence highlighted. If it isn't sure, a human decides. |
| 4 · You approve | Approval queue, approve, create the SEPA file | Then it stops. It prepares the bank transfer and the supplier emails, but nothing happens until I approve. |
| Private mode | Engine choice, replay of the Muse Glimmer run | For businesses that can't send invoices to the cloud, the same agent runs on Muse Glimmer, right here on my laptop. |
| Results | Metrics and benchmark | In this demo month: thirty-two documents, all twelve planted problems stopped, over eight thousand euros flagged at risk, in six minutes, for about one euro of AI. |
| End card | Models and links | Ledgerline. Let the agent do the checking. You do the approving. |

## X post (Most Viral prize)

Post it with the video attached and tag @AIatMeta:

> Ten sacks of coffee billed. Nine on the pallet.
>
> I built Ledgerline for the @AIatMeta hackathon. It reads supplier bills, hears a staff voice memo, counts the
> delivery with SAM 3.1 and catches a fake bank-detail email, then waits for my OK before it makes any payment file.
>
> Muse Spark · Muse Voice Transcribe · SAM 3.1 · Muse Glimmer on my laptop
>
> Try it: founder-sk-hub.github.io/ledgerline
> Code: github.com/founder-sk-hub/ledgerline
