# Interaction contracts

## Chat lifecycle

Bind every stream to user/agent/conversation/task identity. Each bot has one continuing home conversation; each group has one conversation with separate responding bots. Key drafts by conversation. Selecting another chat must not carry the previous draft, text delta, pending approval, desktop or upload into the new view. Capture IDs before awaiting network work and reject stale results.

Create a durable task before streaming. Save its ID per conversation, consume ordered event IDs, resume from the last cursor after a disconnect, and restore pending approvals on reload. End-of-stream without a terminal event is interrupted transport. Stop calls the backend cancel endpoint; aborting fetch only stops observation. Display cancellation errors rather than claiming success.

Groups create one user message and one task per selected responder. Keep a separate stream, approval, tool state and image placeholder per task. Show who is speaking. @everyone is bounded to current members. Stop ends the whole request including helpers. A retried network send keeps its original request ID; a deliberate new request gets a fresh ID. A helper's later result returns to the original conversation exactly once, even when the coordinator already finished.

Keep all original messages readable and searchable while compacting the bot's working context separately. Older-history loading and search hits need exact-message navigation. Do not expose a context-management workflow to the ordinary user. Summaries are fallible; never promise perfect or literally infinite recall.

Enter sends; Shift+Enter inserts a line break. Respect IME composition. Disable send during an unresolved upload, but allow a completed attachment with an explicit default instruction if empty text is permitted. Support immediate visible filename/status and removable pending attachments. A failed upload remains actionable. Never implicitly reuse another bot's files.

Auto-scroll while near the bottom. Reading older messages suppresses auto-scroll; offer a scroll-to-latest action when new content arrives. Preserve scroll position across chunk updates. Copy assistant text with success/failure feedback. Safe markdown may render code, lists, links and tables; raw HTML is disabled. Long code/table blocks scroll within themselves, not the viewport.

## Settings and resources

Bot details allow editing name, instructions, model, and visual identity where implemented. Model choices come from the live runtime account. Never direct a user to nonexistent settings to repair an unavailable model. Saving has pending/error/success feedback and preserves the draft on failure.

Files shown in bot context belong to that bot. Global lists label ownership. Include authenticated download and explicit delete. PDFs and DOCX can advertise text extraction only if the backend provides it; scanned PDFs require OCR and must be reported honestly. Never describe uploaded binary data as automatically understood.

Private memory deletion must send its agent scope. Resource mutations show errors and refresh only the owning context. Learned procedures are private by default, retain source task/evidence/revision, become reusable after successful completion, and have view/disable/delete controls. A saved procedure is reference data, not higher-priority policy or permission to act.

Usage display must normalize actual provider windows. Missing data is unavailable, not unlimited. Show meaningful remaining amount/window/reset when known. Sign-out succeeds only after the server revokes the cookie-backed session; a failed request needs retry.

## Private computer

Every bot receives its own persistent browser profile in a capped environment. Start/resume must be visible and may be callable by the bot when browser access is needed. Shared host credentials/files are not part of that environment. Never substitute another bot's desktop after a stale async response.

A computer panel has unavailable, starting, running, paused, and failed states. Show a real preview or truthful setup state. Expose reconnect/open/pause as appropriate. Browser-only access is not a full unrestricted shell. Keep the authenticated proxy and per-bot ownership check on HTTP, WebSocket, screenshot, and action paths.

Watching keeps a visible computer awake; hidden viewers release their leases. Take control and Return to bot are explicit actions. Bot clicks and screenshots must stop during manual ownership. Inactive desktops sleep and retain their private Chrome profiles. Shared capacity does not mean shared cookies. Never evict another bot's active task or a visible manual session to make room.

## Routines

List only persisted routines. The simple editor asks for a name, instruction, local time and days; timezone is visible or stated clearly. Show paused, working and next scheduled run accurately. Provide run now, pause/resume, edit and remove. Save failures retain entered text. Completion appears in the bot's continuing chat. Do not show invented example routines in a real account.

## Accessibility and phone behavior

Use semantic buttons, tabs/radio groups, inputs, and form labels. Trap focus in true modal overlays, make the underlying app inert, close with Escape, and restore focus to the trigger. Nonmodal resource panels must not trap focus. Touch targets meet 44 px where practical; don't hide primary actions behind hover.

Use dynamic viewport sizing and safe-area insets. Composer remains visible above the keyboard; scroll belongs to the transcript. Back navigation returns to inbox without losing an active run. At 320 px there must be no horizontal page overflow. Status and validation text wrap and remain readable with long bot names.

