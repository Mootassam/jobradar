# JobRadar — worldwide job search (personal use)

One search → job boards, remote boards, government portals and hundreds of company career pages at once,
filtered by **country, state/region, city, job title**, with **emails, phone numbers and company contacts**.

## Start
Double-click **`Start.bat`** → opens http://127.0.0.1:5090 (runs only on this computer).

## Sources
| Source | Coverage | Setup |
|---|---|---|
| Remotive, Remote OK, Jobicy, Himalayas, Working Nomads, We Work Remotely | Remote jobs worldwide | none |
| Arbeitnow | Germany / Europe | none |
| **National job boards**: Keejob (Tunisia), Jobberman (Nigeria), BrighterMonday (Kenya) | Real local jobs, each job page cached 7 days | none |
| Careerjet | ~90 countries via local sites (e.g. optioncarriere.tn) | free affiliate ID |
| ReliefWeb | UN / NGO jobs, 150+ countries | free approved app name |
| **Company career pages** (Greenhouse, Lever, Ashby, Recruitee, SmartRecruiters, Personio) | Direct from employers, worldwide. Starts with 178 verified companies and **grows automatically** when new ones are discovered | none — add more in Sources |
| Adzuna | 19 countries, millions of jobs | free API key |
| Jooble | 70+ countries | free API key |
| USAJOBS | US federal | free API key |
| Company websites crawler | any careers page you add (schema.org JobPosting) | add URLs |
| **Job-alert email import** | LinkedIn, Indeed, Glassdoor alerts from your inbox | email + app password |

## Features
- **CV check & match** (page "CV check & match"): reads your CV like an ATS robot (columns, tables, text boxes, header
  contacts, scans, broken fonts), checks contact/sections/dates/bullets/numbers/length, shows "what the robot reads",
  and compares your skills with what employers ask for your target job. Every job gets a **match score** (skills
  required vs nice-to-have, job family in any language, experience, languages incl. the post's language, education,
  location) with a breakdown, the **best CV version** per job (also used by the autofill extension), a **skill-gap**
  report ("learning X unlocks N good jobs") and **top-match alerts**. Jobs list: sort "Best match", filter "Match 75%+".
- **Hiring signals**: every company career board is snapshotted over time → hiring surges, first jobs in a new
  country (yours), new teams, recruiters being hired, new jobs in your field. ☆ Watch a company = notified the moment
  it posts. Anonymous posts are ignored.
- **Spontaneous applications**: finds companies with a real contact (HR person > jobs@ > manager > contact@; never
  legal@/privacy@/noreply@) from JobRadar and your **Lead Finder** database, writes personal drafts (FR/EN by country,
  your best CV attached), you approve each one, then sends from **your own mailbox** (daily limit, random gaps, office
  hours, never the same company twice, auto-pause on errors). Follow-up drafts after N days; replies / interview
  invitations / rejections / bounces detected in your inbox (read-only). Optional export to MailBlaster.
- **Night deep scan** (default 02:00): saved searches (or your target role), refresh of every company board, alert
  emails, recruiters for the best companies, dead-job check of your pipeline, match scoring, reply check, backup →
  **morning report**. Catch-up run if the PC was off; keeps Windows awake while scanning; optional scheduled task that
  **wakes the PC** (Night scan → "Set it up"; removable the same way). `server.py --background` starts it silently.
- **Multilingual search**: "accountant" also searches comptable, Buchhalter, contable, محاسب… (8 languages, ~75 job
  families); sources are queried in the country's own language(s). Toggle "Multilingual" in Advanced.
- **Resumable searches**: every run saves a checkpoint per source. If the internet drops, JobRadar waits and continues;
  if the app/PC closes, the run shows **Resume** (or resumes by itself on start - setting "Auto-resume").
- **Autofill helper** (Chrome/Edge extension in `extension/`): fills name, contacts, links, CV upload, cover letter
  ({company} {job_title} {my_name}) and common questions from **My profile**. Never submits, never answers
  diversity / date-of-birth questions, lists the questions only you can answer, and **Mark as applied** puts the job
  in your pipeline. Install: `edge://extensions` → Developer mode → Load unpacked → `D:\jobradar\extension` →
  paste the pairing code from My profile → press Alt+Shift+F on an application page. Try it on `/autofill-test`.
- **Recruiter finder**: HR / recruiters, leadership and hiring managers that each company publishes on its own website
  (team, about, imprint/legal, contact, careers pages - EN/FR/DE/ES/IT/AR) or names in its job posts; ranked by relevance,
  with published email / phone / LinkedIn link. Nothing is guessed. Searchable **Recruiters** page + Excel export.
- **Email intelligence**: every email classified - recruiting inbox (jobs@, rh@, careers@…), personal, general
- **Deep company profile**: description, logo, address, founding year, employees, social links (up to 18 pages per site)
- **Job insights**: experience, seniority, education, languages, skills, contract (CDI/CDD/freelance/internship),
  benefits (visa, relocation, remote…), application deadline; filters for contract, max experience, visa, recruiter
- Salary detection that ignores non-pay amounts (budgets, funding) and understands "2 500 € brut", "1 800 DT"
- Live progress per source, stop anytime; results stream in while searching
- Smart de-duplication (same job on several sites = one row, details merged)
- **Strict country targeting**: only jobs located in the chosen country (remote jobs open to it are an opt-in switch)
- Typo-tolerant country picker (tunisa → Tunisia)
- Location intelligence for every country (states/regions for US, CA, AU, IN, DE, GB, FR, ES, IT, NL, BR, MX, MA, AE…)
- Emails & phones extracted from job posts; **Find contacts** visits the company's own website (contact/about/imprint pages)
- Full-text search, filters (email / phone / salary / remote / date / source / status), Excel & CSV export
- Pipeline board (Saved → Applied → Interview → Offer / Rejected), notes
- Saved searches that run automatically + notifications
- Automatic backups in `data/backups`

## How it collects (and what it won't do)
Official/public APIs and feeds, public company job boards, schema.org data on sites you add (robots.txt respected),
and your own alert emails. Honest user-agent, per-site delays, no login/captcha/block bypassing.
LinkedIn, Indeed and Glassdoor are **not scraped** — use the alert-email import for their jobs.

## Tests
`python -m unittest discover -s tests -v`
