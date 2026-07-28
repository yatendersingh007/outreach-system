# Gmail Draft (PREMIUM_MODEL)

Write ONE cold outreach email from Harp, founder of X Analyst, to a senior
finance/operations leader at a mid-market commercial real estate firm. Write in
the FIRST PERSON as Harp. It must read like a real person wrote it, and match the
voice and structure of the past example(s) below.

Lead the pitch with this service: {service_focus}.

## About X Analyst (these are the facts; do not restate verbatim, weave them in)
X Analyst provides offshore property accounting and fund accounting for
mid-market commercial real estate firms. Scope: property-level books and
month-end close, bank reconciliations, AP/AR and tenant billing, CAM
reconciliations, budget vs. actual variance reporting, lender and covenant
reporting, owner distributions and reports, and fund accounting with investor
reporting, delivered on Yardi, RealPage, and Entrata. The team is hired from the
top 0.5% of India's CA/CPA talent pool, paid top of market (about $30/hour), and
deployed as dedicated accountants embedded in the client's systems and close
calendar. Delivery is led by a Head of Delivery with ex-Blackstone and Goldman
Sachs experience. Reference clients: Magnolia Capital and 29th Street Capital.
This is an ACCOUNTING service. Do NOT describe underwriting, deal analysis,
acquisitions analysis, or financial modeling as the service.

## Recipient
First name: {first_name}
Name: {full_name}
Title: {designation}
Firm: {company}

## What we know about the firm (personalize from this; do not restate verbatim)
Summary: {company_summary}
Pain points: {pain_points}
Recent signals: {recent_signals}

## Past outreach examples (match this voice and structure; may be empty)
{examples}

## Required email structure (match the example exactly)
The body MUST be built as these blocks, separated by a literal blank line
(a "\n\n" in the JSON string):
1. Greeting on its own line: `Hi {first_name},` then a blank line.
2. Opening paragraph, one or two sentences, referencing something specific and
   verified about the recipient's firm (asset class, portfolio, growth, region).
3. Two or three short body paragraphs, each separated by a blank line, covering:
   what X Analyst does (name the software stack: Yardi, RealPage, Entrata), the
   pain-point framing (mid-market firms overpay a provider or burn their
   controller's nights), and the offer (dedicated CA/CPA accountant, top of
   market pay, embedded in your systems and close calendar).
4. A closing paragraph with a soft call-to-action (a short call next week) and a
   brief, natural mention that a short overview of how X Analyst works with firms
   like theirs is attached. Do NOT call it a "case study" or "one-pager" — the
   attachment is a tailored firm overview, so describe it that way.
5. A sign-off block on its own two lines, exactly:
   `Harp`
   `Founder, X Analyst`

## Output
Return a SINGLE JSON object (no prose, no markdown fence):
{{
  "subject": "short, specific, lowercase-ish, no clickbait",
  "body": "the full email, 150-250 words, blocks separated by \n\n, ending with the exact sign-off"
}}

## HARD rules
- The body MUST begin with `Hi {first_name},` and MUST end with the exact two-line
  sign-off `Harp` then `Founder, X Analyst`. Never run a sentence into the sign-off.
- Paragraphs MUST be separated by a blank line (\n\n) in the JSON body string.
- Body length: aim for 180-260 words, hard limit 140-350. Carry real substance
  (the software stack and the cost/talent angle) where it fits, like the example.
- Sign as `Harp`, never `Harpreet`.
- The Head of Delivery IS ex-Blackstone and ex-Goldman Sachs (he worked AT those
  firms). NEVER write "working with ex-Blackstone" or any phrasing implying he
  worked WITH such people rather than AT those firms. Correct: "our Head of
  Delivery, ex-Blackstone and Goldman Sachs".
- ZERO em dashes. Never use "—". Never use "--" as a dash. Use a period or comma.
- BANNED phrases: "I hope this finds you well", "I came across your profile",
  "I wanted to reach out", "reaching out", "touch base", "circle back", "synergy",
  "in today's fast-paced", "leverage" (as filler), "game-changer".
- Vary the opener. Do not fabricate metrics or claims about the recipient's firm.
- If Recent signals is empty, "unknown", or looks low-confidence, DO NOT assert a
  specific event. Open instead with an asset-class or pain-point angle relevant to
  the firm (for example their multifamily portfolio and month-end close load).
- Output valid JSON only.
