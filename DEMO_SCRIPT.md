# Demo video: screen recording script (target 3:00, voice over, no face needed)

## Before you hit record (10 minutes)

1. Open a **new** PowerShell, then:
   ```
   cd C:\Users\CALEB\Documents\clinical-note-auditor-v6\clinical-note-auditor
   .\.venv\Scripts\Activate.ps1
   Remove-Item Env:EXTRACTOR -ErrorAction SilentlyContinue
   uvicorn app.main:app
   ```
2. In Chrome or Edge, open these tabs, in this order:
   - Tab 1: `http://127.0.0.1:8000/` (the app)
   - Tab 2: your GitHub repo page, scrolled to the **Architecture** diagram in the README
   - Tab 3: `ONE_PAGER.pdf`, opened in the browser, zoomed so the **Evidence** table fills the screen
3. Browser setup: zoom the app tab to **125%** (Ctrl and +) so the judges can read it. Hide the bookmarks bar (Ctrl+Shift+B). Close every other tab.
4. Turn on Windows **Do not disturb** so no notifications pop up. Plug in your laptop.
5. Rehearsal click: press **Hidden allergy** once. The line under the result must say `Extractor: hybrid` and there must be a red **HOLD ampicillin**. If either is missing, cut Scene 4 from the video and say nothing about it.
6. Press F5 on the app tab so it's back on its starting view (a note in the box, no result yet).

**Recorder:** OBS (Display Capture, 1920×1080, 30 fps) or the Windows Snipping Tool's video mode. Test 10 seconds of audio first: speak at normal volume, 15 to 20 cm from the mic, no fan noise.

**Recording in pieces is fine.** Record scenes 1 to 6 as one take and scenes 7 to 9 as a second take, then join them in Clipchamp (built into Windows). Delete long pauses in Clipchamp.

**Never show:** the PowerShell window, your `.env` file, test output walls, or any MTSamples note text.

## The script

Spoken lines have no hyphens or dashes. Pace: calm, about 140 words per minute.

| # | Time | On screen: what you do | Say |
|---|---|---|---|
| 1 | 0:00 | App tab, starting view (note in the box, no result yet). Move the mouse slowly over the title. | "Hi, I'm Cal. Clinical notes are written fast, in free text, full of shorthand and brand names. A penicillin allergy on one line and an amoxicillin order a few lines later is exactly the kind of mistake a tired reader misses. The World Health Organization estimates medication errors cost about 42 billion dollars a year. So I built Clinical Note Auditor. It reads a messy note and catches safety problems before the note is signed." |
| 2 | 0:25 | Click **Allergy conflict**. Hover over the red banner, then the first checklist item, then the grey evidence line under the first flag. | "Here's a simple note. Allergies: penicillin. Plan: amoxicillin. The red banner says there's a high severity issue. The checklist tells the clinician exactly what to do first: hold the amoxicillin and confirm the allergy. And every flag shows its evidence, so you can see exactly why it fired." |
| 3 | 0:50 | Click **Messy prose**. Hover over the note text, then over the meta line at the bottom: `allergies: penicillin · meds: amoxicillin`. | "Real notes look more like this. PCN is short for penicillin, and Augmentin is a brand of amoxicillin. The auditor translates both, so it still catches the conflict. It also notices there's no temperature or breathing rate, and asks for them." |
| 4 | 1:10 | Click **Hidden allergy**. Hover over "anaphylaxis after a pen-class antibiotic", then the red HOLD ampicillin item. | "This one is harder. There's no allergy line at all. Just a history that says anaphylaxis after a penicillin class antibiotic. Plain pattern matching misses that. The language model reads it, finds the penicillin allergy, and the rules then hold the ampicillin." |
| 5 | 1:30 | Click **Dose error**. Hover over the checklist item. | "Here, five thousand milligrams of metformin in one dose. That's above the labeled range, so it's flagged, and the checklist says to check for a milligram versus gram mistake." |
| 6 | 1:45 | Click **Allergy conflict** again. Click into the text box, select the word `penicillin` after "Allergies:" and type `none`. Click **Audit note**. Wait for the green banner. Then scroll down to the SOAP section. | "And this is the point of the tool. Say the clinician checks and the patient has no allergies. I fix the note, audit it again, and now it's clean. Down here, the messy note also comes back as a structured SOAP note." |
| 7 | 2:05 | Switch to Tab 2 (README architecture diagram). Point the mouse at the extractor box, then at rules.py. | "How it works. A language model only reads the note and pulls out allergies, medications and vitals. The safety decision is made by plain rules over a small reference table, and every entry has a source, like FDA drug labels. The AI can add findings, but it can never remove one. And if the AI fails, the screen says so. It never quietly says everything is fine." |
| 8 | 2:30 | Switch to Tab 3 (one-pager PDF, Evidence table). Hover over 61 and then 100. | "I tested it on 25 real anonymized notes that I labeled by hand. On 10 notes it had never seen, the AI raised medication recall from 61 percent to 100 percent, compared with rules alone. It's a small sample and it's not clinically validated. The limits are in my writeup." |
| 9 | 2:50 | Switch back to Tab 1 (the green result). Stop moving the mouse. | "The language model reads. The rules decide. That's Clinical Note Auditor. Thanks for watching." |

## After recording

1. Watch it once at normal speed with sound. Check: every number you say matches the one-pager (25 notes, 10 unseen, 61 to 100 percent), the text on screen is readable, no terminal or key is visible.
2. Upload to YouTube as **Unlisted**. Title: `Clinical Note Auditor | DSH Hacks V2`. Paste the link into Devpost and into README line 3.
3. Open the link in a private window to confirm it plays without logging in.
