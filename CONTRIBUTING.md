# Contributing

Contributions that improve reproducibility, source validation, accessibility or explanatory clarity are welcome.

## Before opening a pull request

1. Explain the reporting or analytical problem the change addresses.
2. Preserve source provenance and do not silently replace cached values.
3. Add or update tests for parser, matching or analysis changes.
4. Do not add student-level, private or inferred personal data.
5. Run the complete verification suite.

```bash
ruff check .
pytest
python scripts/build_site.py --output _site
```

Any refreshed source snapshot must document its retrieval date. Changes to reported statistics must update the article, graphics, methodology and `analysis_summary.json` together.

