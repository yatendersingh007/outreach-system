# Outreach System (Workflow A)

Finds a client's competitors and turns them into reviewed Gmail drafts.

Give the Telegram bot a client firm. It works out who the client is, finds
competing firms, checks each one against the ICP, finds the right contacts
and their emails, and prepares personalized Gmail drafts with a custom pitch
deck attached. A person reviews and sends every draft.

## Pipeline

1. `/prospect "Client Firm Name"` starts a run.
2. The bot confirms the client and proposes a profile (firm type, asset
   classes, regions) for new clients.
3. It finds competitor firms and shows a numbered list to confirm or trim.
4. Each firm goes through the ICP check. Firms whose size cannot be verified
   are parked for human review.
5. Contacts and emails are found for qualified firms.
6. Personalized emails and pitch decks are drafted and saved as Gmail
   **drafts**.

## Telegram commands

| Command | Use |
|---|---|
| `/prospect "Client"` | Start a run for a client |
| `/prospect confirm` | Proceed with all found competitors |
| `/prospect trim 2, 5` | Drop some competitors, then proceed |
| `/prospect refresh` | Search again from scratch |
| `/prospect pick 2` | Pick the right client when the match is unclear |
| `/profile confirm` / `/profile edit ...` | Approve or correct a new client's profile |
| `/qualify "Firm" 800M` / `/disqualify "Firm"` | Resolve a parked firm |
| `/requalify` | Re-check all parked firms |
| `/clients` / `/client "Name"` | List or show client profiles |
| `/status` / `/status "Client"` | Totals, parked firms and spend |
| `/cancel` | Stop whatever is running. Always safe. |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env    # fill in your own keys
```

Postgres schema is in `schema.sql` and `migrations/`. Keep `.env`,
`credentials.json` and `token.json` out of git.

See `BUILD_SPEC.md` for the design and `HANDOVER.md` for day-to-day
operation.
