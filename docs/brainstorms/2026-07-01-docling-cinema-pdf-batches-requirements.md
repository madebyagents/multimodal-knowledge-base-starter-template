---
date: 2026-07-01
topic: docling-cinema-pdf-batches
---

# Docling Cinema PDF Batches Requirements

## Summary

Process the cinema PDFs with a manifest-driven Docling batch plan. The main batch should use Docling level C, the hybrid intelligent mode, while level A is reserved for clean short PDFs and level B is reserved for OCR-heavy exceptions, failed retries, or documents whose value justifies the heavier run.

---

## Problem Frame

The external cinema source folder currently holds 84 PDFs across six topic folders. A quick local probe found 11,848 known pages, about 1.8 GB of PDFs, 20 large documents, and 9 documents whose sampled pages yielded weak text extraction. A single full-power run over all PDFs would waste time on clean documents, while a single lightweight run would under-read scanned, image-rich, or layout-heavy cinema material.

The goal is not to ingest these outputs yet. The goal is to decide how to batch Docling conversion so later Knowledge Hub, LightRAG, or multimodal ingest can consume clean Markdown, JSON, and extraction evidence without rerunning everything blindly.

---

## Key Decisions

- **Level C is the default for the cinema corpus.** Cinema books, manuals, shot-design material, magazines, and visual theory documents benefit from the hybrid Granite plus standard-rich pass.
- **Level A is a speed lane, not the corpus default.** Use it for short, born-digital, mostly textual teaching material where Markdown-first extraction is enough.
- **Level B is a targeted rescue lane.** Use it for weak text probes, scanned PDFs, OCR-heavy manuals, and failed C outputs, not as the default for all 84 files.
- **Batch by risk and topic, not just by directory.** Folder-level batches are readable, but large or OCR-risk PDFs need their own shard so failures do not block the rest.
- **Conversion output stays separate from ingest.** Docling outputs should be validated and summarized before any Knowledge Hub, LightRAG, or multimodal mutation is approved.

---

## Requirements

**Inventory and classification**

- R1. The batch plan must produce a manifest for every cinema PDF with source-relative path, topic folder, file size, page count, text-extraction probe, chosen Docling level, and selection reason.
- R2. The classifier must identify at least three lanes: level A for clean short documents, level C for default rich extraction, and level B for OCR-heavy or retry-needed documents.
- R3. The classifier must mark large documents separately so the operator can run them as resumable shards instead of one fragile all-folder command.

**Docling level policy**

- R4. Level A should be used when a PDF is short or medium, mostly textual, and the text probe is healthy enough that a Markdown-first output is likely sufficient.
- R5. Level C should be used for the main cinema batch, especially cinematography, film history, directing, shot-design, editing, manuals, magazines, and canonical books.
- R6. Level B should be used only when the PDF is scanned, the text probe is weak, C fails, C output is visibly poor, or the document is high-value enough to justify full OCR and enrichments.

**Batch execution**

- R7. The first run should be a smoke batch covering one representative PDF per lane before running the full corpus.
- R8. Full processing should run in bounded batches by topic folder and risk lane, with independent retry manifests for failures.
- R9. Existing successful outputs should be skipped on resume unless Andre explicitly asks to regenerate them.
- R10. Source PDFs must not be moved, renamed, deleted, or overwritten by the Docling batch.

**Validation and handoff**

- R11. The output summary must report converted, skipped, failed, retried, and needs-review counts.
- R12. The validation pass must sample outputs from each lane and compare expected content shape against the original file type: text continuity for books, layout preservation for manuals, OCR coverage for scans, and table or figure handling where relevant.
- R13. The batch must leave a downstream-ready index of Docling outputs so a later ingest plan can decide what enters Knowledge Hub classic, LightRAG KH-native, and multimodal.
- R14. No Knowledge Hub, LightRAG, multimodal, Qdrant, Postgres, Redis, Chroma, or vault mutation is in scope for this Docling batch brainstorm.

---

## Recommended Lane Assignment

| Lane | Docling level | Use for | Why |
|---|---:|---|---|
| Smoke | A, C, B sample | One representative file per lane | Proves wrappers, output paths, and runtime stability before spending hours |
| Fast text | A | Teaching, glossaries, syllabi, worksheets, clean short PDFs | Cheapest useful pass when layout and OCR are not the main value |
| Main cinema | C | Most film history, cinematography, directing, editing, and canonical books | Best balance for visually rich but not necessarily scanned cinema PDFs |
| Rescue | B | Low text-probe files, scanned books, failed C outputs, important manuals | Full OCR and enrichments are worth the cost only where C is insufficient |

---

## Candidate Batch Shape

The first batch should be a small smoke set: one clean teaching PDF through A, one canonical book or manual through C, and one weak text-probe PDF through B. If all three produce coherent outputs, the full run should proceed with C as the main default, A for clearly clean short teaching material, and B for the 9 weak text-probe files plus any C failures.

Large documents should be isolated in their own shards. The local probe found 20 PDFs at or above 50 MB or 250 pages, so a single all-folder `docling C` run is possible but not the best operational shape. Sharding lets the operator resume, retry, and inspect cost without losing the whole batch.

---

## Acceptance Examples

- AE1. **Clean teaching PDF:** Given a short syllabus or glossary with strong text extraction, when the classifier runs, then it chooses level A and records the reason as clean text-first extraction.
- AE2. **Canonical cinema book:** Given a film history or cinematography book with hundreds of pages and healthy embedded text, when the classifier runs, then it chooses level C because layout and structure still matter for later retrieval.
- AE3. **Scanned or weak-text PDF:** Given a PDF whose sampled pages produce little or no text, when the classifier runs, then it chooses level B or marks it as B-rescue after a failed C pass.
- AE4. **Large manual:** Given a large cinematography manual, when the batch is planned, then it is isolated as its own shard even if its chosen level is C.
- AE5. **Failed conversion:** Given any failed conversion, when the batch resumes, then successful outputs are skipped and only failed or explicitly stale items are retried.

---

## Success Criteria

- Every one of the 84 cinema PDFs has a manifest row with a chosen level and reason.
- The smoke set completes for A, C, and B before the full corpus run.
- The full run can be resumed without redoing successful outputs.
- Validation samples show usable Markdown or structured output for each lane.
- Failed or low-quality outputs are isolated in a retry list instead of hidden inside a large log.
- No source PDF or organized folder structure is mutated.

---

## Scope Boundaries

- In scope: Docling conversion strategy, lane selection, batch grouping, resume behavior, output validation, and conversion manifests.
- Out of scope: Knowledge Hub ingest, LightRAG graph import, multimodal image extraction, vector embedding, CAG packs, file renaming, and deletion.
- Out of scope: running level B on every file by default, unless a later dry-run proves runtime and quality make that worthwhile.

---

## Dependencies / Assumptions

- The local Docling launcher exists and supports modes A, B, and C.
- The external source root is the organized Scribd cinema folder.
- The current local probe is enough for requirements, but planning should rerun inventory before execution because the folder may change.
- Quality review can use sampled Markdown and structured outputs rather than inspecting every page manually.

---

## Sources / Research

- Local `docling` skill convention: A is smooth Markdown-first, B is full-power OCR and enrichments, C is hybrid intelligent with Granite plus standard-rich output.
- Local source scan of `Downloads/scribd/cinema`: 84 PDFs, 11,848 known pages, about 1.8 GB total, 9 low text-probe files, and 20 large files.
- Existing DanteDash boundary: current dashboard reads are Knowledge Hub native, and this Docling brainstorm does not change runtime data stores.
