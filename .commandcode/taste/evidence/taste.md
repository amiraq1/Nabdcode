# evidence
- Validate that evidence content actually supports the claim, not just that the evidence ID exists. Confidence: 0.85
- Reject findings that reference evidence records where `success=False`; only accept successful tool calls as valid evidence. Confidence: 0.85
- Assign a type to each evidence record (filesystem, shell, memory, web, database, config, git) and let each claim specify which evidence types it accepts. Confidence: 0.75
- Track `covered_subjects` on each evidence record to prevent reusing a single piece of evidence for unrelated claims. Confidence: 0.70
- Make evidence records immutable after creation to prevent tampering. Confidence: 0.80
- Use an independent Verifier LLM stage between draft report and final publish to validate evidence quality. Confidence: 0.80
- Derive claim confidence from evidence strength/count (1 evidence=0.5, 2 independent=0.8, 3+ independent=0.95) rather than from LLM estimation. Confidence: 0.75
