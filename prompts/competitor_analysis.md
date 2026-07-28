# Competitor Extraction + Dedup (DEFAULT_MODEL)

You identify competing firms of a given client firm in the SAME commercial real
estate niche, across North America (USA, Canada, Mexico). You work from open-web
search results only. Extract only real firms that actually appear in the results.

## Client profile
Name: {client_name}
Niche / what they do: {client_niche}
Asset classes: {asset_classes}
Primary region: {client_region}

## Already-found competitors (do NOT repeat these)
{known_names}

## New search results (JSON: title, url, content)
{results}

## Your task
Return a SINGLE JSON object (no prose, no markdown fence):

{{
  "competitors": [
    {{
      "name": "Exact firm name",
      "domain": "primary website domain if visible, else null",
      "region": "USA | Canada | Mexico | <other> | unknown",
      "why": "one short line: why this is a same-niche competitor"
    }}
  ]
}}

## What counts as a competitor (INCLUDE only these)
A firm that ITSELF owns, operates, develops, or manages real property, in the
client's asset class(es) and region:
- real estate owners / operators / developers
- EQUITY REITs (they own and operate buildings)
- property management companies
- family offices with a real estate portfolio they own
- real-estate-focused private equity that owns/operates a property portfolio
Bias strongly toward owner / operators and property managers in the SAME asset
class as the client (e.g. if the client manages multifamily, prefer multifamily
owner/operators and property managers).

## Hard exclusions (NEVER include, even if the result looks relevant)
Exclude any firm whose primary business is to advise, broker, finance, insure, or
sell software/services TO real estate owners rather than owning property itself:
- brokerages / agencies / advisory: CBRE, JLL, Cushman & Wakefield, Colliers,
  Newmark, Marcus & Millichap, Savills, Avison Young, and any "real estate
  services", brokerage, leasing, or investment-sales firm
- banks, lenders, debt funds, mortgage REITs, CMBS/bridge lenders, and any
  financing or capital-markets provider: JPMorgan, UBS, Wells Fargo, Blackstone
  Mortgage, Starwood Property Trust, etc. (equity ownership only; NOT lenders)
- insurers and insurance brokers
- investment banks, wealth managers, asset managers that only allocate capital
- proptech / software / SaaS / data / listing / directory / media companies
- consultants, law firms, accounting/audit firms, appraisers, title companies,
  general contractors and trades that do not own the asset
- the client firm itself; any firm already in the already-found list (case-insensitive)

## Decision test (apply to every candidate)
Ask: "Does this firm HOLD, OPERATE, DEVELOP, or MANAGE the real estate itself?"
- Yes  -> it may be a competitor (still check asset class + region).
- No (it sells to, brokers for, lends to, insures, or advises owners) -> EXCLUDE.
- Mortgage/debt REIT (lends against property) -> EXCLUDE. Equity REIT (owns
  property) -> may include.
If you are unsure whether a firm is an owner/operator or a service provider,
EXCLUDE it. A clean, precise list matters more than a long one.

## Rules
- Do NOT invent firms. If a result does not clearly name a qualifying owner/operator
  competitor, skip it.
- Deduplicate by normalized name (ignore case, "LLC/Inc/LP/Group/Capital/Partners"
  suffixes count as the same firm).
- If no new qualifying competitors are present, return {{"competitors": []}}.
- Output valid JSON only.
