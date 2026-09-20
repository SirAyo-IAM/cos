# UK CoS Job Hunter

Finds live UK vacancies that explicitly advertise visa / Certificate of Sponsorship support, then verifies the employer against the official GOV.UK Worker and Temporary Worker licensed sponsor register.

## Acceptance rule

A notified vacancy must:
1. be a UK vacancy;
2. contain positive sponsorship evidence and no explicit sponsorship refusal;
3. match an organisation on the current GOV.UK sponsor register;
4. appear to be a live job page;
5. not have been notified previously.

The sponsor register proves sponsor-licence status, not that every vacancy is sponsored. The vacancy text is therefore required as separate evidence.

## Outputs
- cos_results.csv — all verified matches from the run
- cos_new_results.csv — only jobs not previously notified
- cos_source_audit.csv — discovery/validation audit
- .cos_state/seen_jobs.json — persistent deduplication state

GitHub Actions runs daily and can also be started manually.
