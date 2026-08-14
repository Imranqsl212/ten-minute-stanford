# Generated reports

The `generated/` directory is the publication boundary between analysis code and editorial outputs.

- `FINDINGS.md` summarizes the principal results.
- `analysis_summary.json` contains statistics quoted in the article and website.
- `validation.json` records collection, matching and routing counts.
- `source_manifest.json` inventories the active cached responses and hashes.
- `publication_audit.json` records the independently recomputed publication checks.
- `tables/` contains analytical CSV outputs.
- `figures/` contains publication graphics in PNG and SVG formats.
- `interactive/route_explorer.json` contains simplified route polylines and
  weighted 10-, 12- and 15-minute scenarios used by the static site.

Regenerate these files with:

```bash
make analyze
make visuals
make social
make audit
```

The production-site tests compare headline numbers against `analysis_summary.json` and fail when required Pages assets are missing.
