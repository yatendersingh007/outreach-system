# X Analyst Outreach Bot — Operator Handbook

This is the day-to-day guide for running the outreach bot from Telegram. You do
**not** need to touch any code. You send commands to the bot in Telegram; it finds
competitor firms for a client, checks each one against our target profile, finds
the right contacts, gets their emails, and prepares personalized Gmail drafts with
a tailored pitch deck attached.

**Nothing is ever sent automatically.** Every email is left as a **draft** in
Gmail for a human to review and send. See "Weekly rhythm" at the bottom.

---

## The one thing to remember

The bot goes out to the open web, so it takes a little time and it talks back to
you the whole way. Just read its messages. If anything ever looks stuck or wrong,
send **`/cancel`** — it always works and never breaks anything.

---

## Commands (what each one is for)

Send these as normal Telegram messages to the bot.

| Command | When to use it |
|---|---|
| `/prospect "Client Firm Name"` | **Start here.** Kicks off a run for a client: understands who they are, then finds competing firms. Always put the client name in quotes. |
| `/prospect confirm` | After the bot shows the list of found competitors — proceed with **all** of them. |
| `/prospect trim 2, 5` | Same list, but drop some first (by number or name), then proceed with the rest. E.g. `/prospect trim 2, 5` or `/prospect trim CBRE`. |
| `/prospect refresh` | Throw away a previously found list and search again from scratch for the same client. |
| `/prospect pick 2` | Use only when the bot says it **couldn't confidently identify** the client and shows you a numbered list of possible matches. Pick the right one. |
| `/cancel` | **Emergency stop.** Aborts whatever is running and makes the bot ready again immediately. Always safe. |
| `/profile confirm` | When starting a **brand-new client** the bot proposes a profile (firm type, asset classes, regions) and waits. This approves it and starts the search. |
| `/profile edit type=... assets=a,b regions=...` | Correct the proposed profile before approving. E.g. `/profile edit type=multifamily investor assets=multifamily,retail regions=USA,Canada`. |
| `/qualify "Firm Name" 800M` | **Rescue a PARKED firm** (see "Parked firms" below) once you've verified its size. Give the AUM you found. |
| `/disqualify "Firm Name"` | Reject a PARKED firm that isn't a fit. |
| `/requalify` | Re-run the size/type check on all parked firms (does a deeper web re-check). Occasional housekeeping. |
| `/clients` | List all client profiles we have on file (their band + pitch focus). |
| `/client "Name"` | Show one client's saved profile. |
| `/status` | Dashboard: totals, how many are parked, spend so far. |
| `/status "Client Name"` | Full per-firm detail for one client's run — see every firm and its verdict. |

---

## What the bot tells you during a run, and what it means

### 1. The "Understood:" line
Right after `/prospect`, the bot confirms who it thinks the client is. If this
looks wrong, `/cancel` and try again with a fuller name (e.g. add the city or
"Property Management").

### 2. The candidate list + confirm
It shows the competitor firms it found, numbered. Reply `/prospect confirm` (all)
or `/prospect trim ...` (drop some).

### 3. Live per-firm progress (one line per firm)
As it checks each firm you'll see lines like:

```
✅ [12/43] Monarch Investment — QUALIFIED (est. $1.0B, 15K units)
❌ [13/43] CBRE — disqualified (brokerage)
◐ [14/43] Timberlane Partners — parked (AUM unverified)
```

- **✅ QUALIFIED** — a real fit. It will get contacts, emails, and a draft.
- **❌ disqualified** — not a fit (e.g. a brokerage, or too big/small). Dropped.
- **◐ parked** — probably a fit, but the bot **couldn't confirm the firm's size
  (AUM)** from the web. It's set aside for you. See "Parked firms" below.

### 4. Apollo email lookup
For each qualified contact the bot looks up a verified email. If some qualified
contacts had **no email found**, at the end it sends one message:

```
No verified email (manual hunt needed):
- Jane Doe — CFO, Acme Real Estate (acme.com)
- Bob Roe — VP Finance, Beta Capital (betacapital.com)
```

These people are still saved in the system — they just need an email found by
hand (the company website / LinkedIn). Once you have it, that lead can be drafted
manually. If every contact got an email, you won't see this message at all.

### 5. Draft ready + confidence flag
For each finished draft:

```
📋 Draft ready: Jane Doe (Monarch Investment)
📊 Deck confidence: HIGH — Safe to review and send
```

**Confidence** is about the tailored pitch deck attached to that draft:

- **HIGH** — the deck is well-supported by research. **Safe to review and send.**
- **MEDIUM** — mostly good. **Glance at slide 3 (the firm-specific claims) before sending.**
- **LOW** or **UNKNOWN** — research was thin. **Read the deck carefully — especially
  slide 3 — and fix or drop anything not clearly true before sending.**

Higher confidence = less checking needed. When in doubt, open the deck.

### 6. Source-link lines (why the email says what it says)
Right after each draft you'll see a plain line like:

```
Timberlane Partners (Brianna): draft cites acquisition — source: https://...
```

This tells you **which recent event the email references** ("why now") and **the
web page it came from**, so you can click the link and confirm the claim is real
before sending. If the draft didn't lean on a specific event you'll see
`(no specific claim cited)` — that's fine, it just means a more general note.

### 7. Final summary + `/status`
A one-line wrap-up (researched / qualified / parked / drafts). Use
`/status "Client Name"` any time to review every firm with its verdict.

---

## Parked firms and the `/qualify` rescue

A firm gets **parked** when it looks like a good fit but the bot **couldn't verify
its assets under management (AUM)** on the web. It's not rejected — it's waiting
for you.

To rescue one:
1. Look up the firm's size yourself (their website, a news article, PitchBook, etc.).
2. If it's in our target band, run e.g. `/qualify "CFH Group" 800M`.
   - AUM can be typed many ways: `800M`, `1.2B`, `$500M`, `500000000`, `"800 million"`.
3. The bot re-checks it and, if it now qualifies, runs the **whole tail
   automatically** — contacts, emails, and a draft — then replies e.g.
   `CFH Group: QUALIFIED at $800M — 2 contacts, 1 email, 1 draft.`
4. If the number you gave is **outside** our band, the bot marks it disqualified
   and tells you why.

If a parked firm clearly isn't worth pursuing: `/disqualify "Firm Name"`.

Only **parked** firms can be `/qualify`'d or `/disqualify`'d. If you try it on a
firm that's already qualified or disqualified, the bot says so and changes nothing.

### Three kinds of "parked" — and the different action each needs
The parked reason (shown in `/status`) tells you which one it is:

| Reason says… | What it means | What you do |
|---|---|---|
| **"no web sources found"** | The web search returned nothing — usually the search quota is exhausted, or the firm is genuinely obscure. | Check the startup health line (below). If search is down, **re-run later** — don't hand-hunt yet. |
| **"AUM not verified"** | We found the firm but no dollar size. | Look up its size (site/LinkedIn/PitchBook). If in-band, `/qualify "Firm" <AUM>`. |
| **"firm type unverified"** | We couldn't tell what kind of firm it is. | Glance at what they are; `/qualify` if RE + in-band, `/disqualify` if not a fit. |
| **"proxy $Xm below floor — verify manually"** | A rough size estimate came out under $200M, but it may be a floor. | Verify the real AUM; `/qualify` if actually in-band. |

**Parking is normal, not failure.** For a batch of small/private firms, expect
**~50–60% parked** — most small firms don't publish their AUM. Your job is to
rescue the promising ones, not to worry that many parked.

---

## The startup health line (read it once a day)

When the bot starts (and after any restart) it posts one line like:

```
Startup: ✓ Exa ✓ Apollo ✓ LLM ✗ Tavily (quota exceeded) | Gmail token: 174d left
```

- **✓** = that service is working. **✗** = it's **down** — and a ✗ changes what a run means:
  - **✗ Tavily** → per-firm research can't search the web → **every firm parks as
    "no web sources found."** Verdicts that run are NOT trustworthy until it's fixed.
  - **✗ Exa** → competitor discovery falls back to Tavily (weaker), or finds fewer firms.
  - **✗ LLM / ✗ Apollo** → drafting / email lookup won't work.
- If you see a ✗, **don't trust that run** — report it (see below) and wait until the
  health line is all ✓ before relying on results.

### Billing / quota — where a ✗ usually comes from
The two web-search services are metered. When their monthly quota runs out you get a
✗ on the health line and firms park en masse. Top them up here:
- **Tavily** (per-firm research): https://app.tavily.com — dashboard shows usage/limit.
  Quota exhaustion looks like every firm parking "no web sources found" + `✗ Tavily`.
- **Exa** (competitor discovery): https://dashboard.exa.ai — usage/limit.

### Two expiry dates to watch (the bot warns you at 30 days)
`/status` and the startup line will prepend a ⚠ warning when either is within 30 days:
- **Azure LLM credits** end **~Oct 2026** — top up / renew before then or drafting stops.
- **Gmail token** expires **~Jan 2027** — needs a quick re-auth (ask the developer);
  until then drafts can't be created.

---

## Three rules

1. **Always put multi-word names in quotes** — `/prospect "Gold Triangle"`,
   `/qualify "CFH Group" 800M`. Without quotes the bot can misread the name.
2. **`/cancel` is always safe.** It never deletes your work — it just stops the
   current run and makes the bot ready again. Use it any time something looks off.
3. **If the bot misbehaves: `/cancel`, then try the command once more.** If it
   still misbehaves after that one retry, stop and escalate (contact the developer)
   rather than repeating it many times.

---

## Weekly rhythm

- Run `/prospect "..."` for the clients you're working that week; confirm the
  candidate lists; rescue any promising **parked** firms with `/qualify`.
- **All finished emails are Gmail *drafts*** in the **Drafts folder of
  `hs@xanalyst.co`**, each with its tailored deck attached. **Nothing is ever
  sent by the bot.**
- Before sending a draft: read it, check the **confidence** flag (open the deck
  if MEDIUM/LOW), and click the **source link** to confirm the "why now" claim.
- Chase the **"No verified email (manual hunt needed)"** list separately — find
  those emails by hand when you have time.
- Use `/status` to see where things stand and how much has been spent.
- **Spot-check the parked list (do this every run — it's how problems get caught).**
  Pick **2–3 parked firms** and look them up yourself for 60 seconds each. If a firm
  parked as "AUM not verified" but its own website/LinkedIn clearly shows a size in
  our band, that's a **signal the research missed findable data** — note the firm and
  **report it to the developer**. (That is exactly how a whole batch of wrongly-parked
  firms was caught — a human eyeballed the parked list and the numbers were right there.)
  A run where all your spot-checks look genuinely un-findable is a healthy run.

That's it. Read the bot's messages, review the drafts, and hit send when you're
happy. When in doubt, `/cancel` and start again.
