# Office deliverables

Use this mode for Word documents, PDFs, spreadsheets, presentations, meeting outputs, email drafts, and executive summaries.

## Frame the deliverable

Identify the audience, decision or action the artifact should support, source material, required format, deadline, and any template or brand constraint. Ask only when a missing choice would materially change the result.

## Route to specialist capabilities

- Use the installed document skill for formatted Word work, redlining, or comments.
- Use the installed spreadsheet skill for formulas, data analysis, charts, and workbook edits.
- Use the installed presentation skill for PowerPoint creation or revision.
- Use the installed PDF skill for PDF-specific reading, creation, or inspection.
- Use connected Google Workspace tools only when the requested artifact lives there.

Do not duplicate the mechanics maintained by those skills. This mode supplies the brief, source discipline, approval boundary, and final quality review.

For semantic extraction or summarization where layout is not authoritative, a Markdown or plain-text intermediate may be used to reduce context. Keep the original artifact authoritative. Follow [token-efficiency.md](token-efficiency.md) before using MarkItDown or another converter; format-specific skills remain primary for layout, formulas, charts, comments, tracked changes, pagination, accessibility, and editability.

## Presentation sequence

For a deck, establish the decision narrative and slide outline before producing visuals. Gather evidence and permitted assets, create the editable deck, then inspect rendered slides for clipping, density, hierarchy, consistency, and legibility.

When useful, adapt the optional [presentation-brief template](../assets/templates/presentation-brief.md). Do not force the template onto a small edit or a deliverable with an established format.

## Final checks

Keep generation, rendering, actual image inspection and native-app testing
distinct. For a visual-inspection claim, retain the final artifact revision or
hash, rendered page/slide inventory, actual native image-view event references,
pages viewed, and observed issues. State coverage against that inventory;
do not claim pages shown only by a renderer log were visually inspected.
An agent-authored `visual-inspection.json`, image dimensions or extracted text
cannot substitute for a tool delivering the images for inspection.

If the tool/export does not retain a usable image-view event, report
**rendered; visual inspection unverified from retained evidence**. Keep an
independent reviewer's later image check separate with its own identity and
coverage. Do not replay or backfill an earlier agent's observation. Native
Word/PowerPoint opening remains separate from rendered-image checks.

- Match tone and depth to the audience.
- Reconcile numbers across text, tables, charts, and appendices.
- Attach citations close to supported claims.
- Confirm the output opens and remains editable when editability is required.
- Do not send, share, publish, or change a calendar without the permission required by `permissions.md`.
