# contract-changes

If a lane believes a frozen interface in `../CONTRACTS.md` is wrong, it does **not** edit
`CONTRACTS.md` and does not quietly fix it in a shared file. Four agents editing one spec file is a
guaranteed merge conflict, and a silent fix in a shared file is worse: it desynchronizes the other
three lanes without telling them.

Instead:

1. Write your proposal to `docs/contract-changes/<your-lane-id>.md`, your own file, which nobody
   else touches. Use the lane ids from `../AGENT_LANES.md`, for example `lane-b-judge.md`.
2. Say what is wrong, what you propose instead, and what you did as a workaround.
3. **Keep building against the contract as written.** Do not implement your proposal.

The integration phase reads every file here, reconciles them into `CONTRACTS.md` in one commit, and
records which proposals were accepted and which were not.

Template:

```markdown
## <short title>

- **Contract affected:** section N.N of CONTRACTS.md, or the specific type / field / signature
- **Problem:** what breaks or cannot be expressed
- **Proposed change:** the exact new shape
- **Workaround used in this lane:** what you actually built, so integration can find it
- **Blast radius:** which other lanes this would touch
```
