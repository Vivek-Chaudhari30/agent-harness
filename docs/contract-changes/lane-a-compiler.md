# Contract-change proposals: Lane A (lane-a-compiler)

## 1. `company_name_mentioned` check requires caller-injected company name

**Affected file**: `src/rules.py` → `CHECKS["company_name_mentioned"]`
**Contract section**: CONTRACTS.md section 2, `check_email` signature

### Observation

The `CHECKS["company_name_mentioned"]` function is deterministic and does a simple substring
check: is `params["company"]` present in the email text? This works correctly, but the company
name is recipient-specific — it lives in `emails.json -> recipient_context.company`, not in the
instruction set. The `Rule` compiled by `compile_instructions` cannot know the company name at
compile time.

### Current workaround

`compile_instructions` sets `params={"company": ""}` for `company_name_mentioned` rules. The
check silently passes when `company` is empty (cannot verify without the name). The contract
says callers invoke the check via `CHECKS[rule.check_id](email_text, rule.params)`, so the
caller must inject the company name before calling:

```python
# In grader.py (Integration) — pseudocode
params = dict(rule.params)
if rule.check_id == "company_name_mentioned":
    params["company"] = email_record["recipient_context"]["company"]
passed, reason = CHECKS[rule.check_id](email_text, params)
```

### Proposed contract addition

`check_email(email: str, rules: list[Rule]) -> list[RuleResult]` should be extended to accept an
optional `context: dict` parameter. Alternatively, `grade_email` in `grader.py` (Integration)
should mutate `rule.params` by cloning the Rule with the injected company name before passing to
`check_email`.

A third option: make `company_name_mentioned` a semantic rule (model checks if a company name
appears) and drop the deterministic implementation. This is simpler but uses a model call for
something verifiable.

### Recommendation

Have `grader.py` (Integration) clone affected rules with injected params before calling
`check_email`. This keeps the checker signature clean and puts the context-injection responsibility
in the orchestration layer where the email record is available.

**Building against contract as written**: Lane A ships `check_id="company_name_mentioned"` with
`params={"company": ""}`. The check passes silently when the company is unknown, which means the
deterministic check is effectively disabled unless the grader injects the name. This is documented
in `src/rules.py`.
