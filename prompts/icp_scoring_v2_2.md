# ICP Qualification Gate (binary, no scoring, no tiers)

A competitor firm QUALIFIES only if ALL THREE conditions are true. If any fails,
the firm is DROPPED and none of its people proceed.

## Condition 1: Firm type
Must be one of:
- Real estate (owners, operators, developers, REITs)
- Family office (with a real estate allocation)
- Private equity (real estate focused, or holding a real estate portfolio)
- Property management

## Condition 2: AUM (assets under management)
- Must be between $200M and $2B.
- Below $200M: DISQUALIFIED (too small).
- Above $2B: DISQUALIFIED (too large, likely has in-house teams).
- If AUM cannot be found or verified after research: do NOT guess. Mark the firm
  as PARKED with reason "AUM_UNVERIFIED" and surface it for human review. Do not
  auto-qualify or auto-disqualify.

## Condition 3: Region
- Headquartered or primarily operating in North America (USA, Canada, or Mexico).
- Outside North America: DISQUALIFIED.

## AUM confidence tagging
Every firm researched gets one tag:
- AUM_CONFIRMED: AUM stated in a reliable source (firm site, SEC/RIA filing, press release)
- AUM_ESTIMATED: AUM inferred from proxies (fund sizes, property count, sq ft, units)
- AUM_UNVERIFIED: no reliable basis found -> PARK for human review

## Who to target at a qualified firm
Only higher-level management. Accept titles such as:
- Chief Financial Officer (CFO)
- VP of Finance / Finance Director
- Controller
- Managing Director / Managing Partner
- Head of Finance / Head of Operations (finance-adjacent)
Drop everyone else (junior staff, unrelated departments, interns, assistants).

## Output for each firm
- icp_result: QUALIFIED, DISQUALIFIED, or PARKED
- icp_reason: one short line, e.g. "RE PE fund, AUM ~$450M confirmed, US-based, qualifies"
  or "AUM ~$5B, exceeds $2B ceiling, disqualified" or "AUM not found, parked"

## Notes
- This is a binary gate. There is NO numeric score and NO HOT/WARM/COLD tiering.
- A firm either qualifies (proceed to executive discovery, enrichment, drafting)
  or it does not (drop, or park if only the AUM is unverifiable).
