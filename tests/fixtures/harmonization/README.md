# Harmonization golden sets

Real postings sampled from the live database (Anthropic, Databricks, Stripe; 2026-11-01).
Labels were assigned **by hand by the assistant (Claude)**, then reviewed by the project owner.
`split=holdout` rows (25 %, seed 13) are never used when tuning the rule data files. Their
accuracy is reported separately so that overfitting is visible.

## Labelling guidelines: `golden_titles.csv`
- **Family follows the job's function, not the team's domain.** "Staff Software Engineer,
  Finance Engineering" is `software_engineering`; "Data Scientist, Safeguards" is `data`.
- **Customer-facing technical roles are `solutions_engineering`:** Solutions/Applied AI
  Architect, Applied AI Engineer, Forward Deployed Engineer, Field Engineering, Implementation
  Consultant, Partner Solutions Engineer, Engagement Manager (FDE).
- **`<X> Program Manager` is `program_management`,** whatever X is (legal, privacy, GTM).
- **Seniority comes from explicit signals only. No signal means `mid`,** even for roles that are
  usually junior (BDR, SDR).
- **`manager` means people management:** "Manager, X", "Sr. Manager", "Engineering Manager",
  "Sales Manager", "Tech Lead Manager". IC titles that contain "Manager" (Product,
  Program, Account, Partner, Marketing, Communications) are not `manager`.
- **`director_plus`:** Director, Associate Director, Head of, VP, Chief, "Global ... Leader".
- **`staff_plus` beats `senior`** (`Sr. Staff`, `Staff + Sr.`). A bare "Lead" counts as `senior`.
- **New Grad and Associate (as a level) count as `entry`.** Intern counts as `intern`.

## `golden_locations.csv`
The most frequent real location pieces, labelled with the canonical key
`kind|country|region|city` (see `jobsignal.harmonization.locations`).
