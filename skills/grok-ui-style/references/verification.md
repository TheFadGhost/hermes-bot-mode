# Verification and harsh review

## Separate the evidence

Record live URL/build, browser, viewport, theme, identity of temporary QA data, and whether each check used the real backend or fixtures. A marketing screenshot is a design reference. A mocked browser run checks UI behavior but cannot prove runtime, remote computer, provider billing, or persistence.

## Behavioral checks

1. Create a temporary named QA bot, select color/shape, refresh, and confirm persistence. Check keyboard choices, empty-name validation, and request failure.
2. Send a harmless deterministic prompt. Verify streamed text, completion, transcript after reload, and conversation navigation.
3. Send a longer harmless prompt; Stop during work and verify durable cancelled state. Switch bots during another run; assert no crossed messages, desktop, approvals, drafts, files, or errors.
4. Interrupt SSE or reload during work, then verify recovery and pending approval restoration. Test end-of-stream without terminal event separately.
5. Upload a text file and a document, verify readable content through scoped tools, then download. Delete only QA assets. Test private memory create/read/delete and errors.
6. Edit existing bot instructions and verify they apply on a resumed chat. Model list reflects the runtime; usage missing/exhausted states are truthful.
7. Start the QA computer, inspect a real screenshot, navigate a harmless page, pause/resume, verify persistent profile and ownership boundaries. Do not act on unrelated signed-in accounts.
8. Save a verified QA procedure, complete its source task, retrieve later, disable/delete, and verify another bot cannot read it. Failed tasks cannot promote a procedure.
9. Test image-generation working/success/failure/cancel visuals with fixtures. Only claim real generation verified after an actual provider job and downloaded asset succeed.
10. Sign-out failure must stay honest. Avoid signing out a user's main session during tests; use a separate QA session.

## Visual capture set

Capture desktop about 1440×900, tablet about 820×1000, phone about 390×844 and narrow phone 320 px. Include light/dark, populated chat, inbox, creator, resource/error states, and image working/output if touched. Capture reduced-motion behavior separately. Use actual screenshot inspection, not only automated overflow assertions.

Check baseline alignment, label weight, optical icon balance, row selection, chat measure, visible keyboard focus, touch targets, readable contrast and stable composer height. Quiet rounded selected rows follow the latest reference; avoid repeated floating cards and nested borders. No clipped labels, surprise horizontal scroll, duplicated hidden controls in the accessibility tree or stale side panels.

## Review standard

Prioritize concrete findings: trigger, observed impact, affected code/state, and evidence. Distinguish reproduced defect, verified code path, and hypothesis. Do not call a fixture pass a live pass. Audit functionality and semantics before debating tiny spacing changes.

After implementation, run build and targeted regressions. Perform one combined visual review, batch fixes, then one confirmation. For a requested independent review, give the reviewer the actual diff, current screenshots, and test evidence; ask for remaining defects rather than aesthetic reinvention. Record unresolved limitations and do not label the app perfect.

