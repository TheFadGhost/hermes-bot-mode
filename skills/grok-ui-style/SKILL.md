---
name: grok-ui-style
description: Build, refine, animate, or audit this project's Grok Bot-inspired messenger. Use for its simple desktop and mobile inbox, continuous conversations, bot identities, groups, routines, computer handoff and image generation. Prioritize nontechnical users and current visual references.
---

# Grok UI Style

Make a calm, direct messenger. Personality comes from the bots, clear typography, and precise feedback. The shell stays quiet. User direction and current visual evidence override this recipe.

## Establish the target

1. Inspect the current route and the user's latest screenshots before editing. Read the project's PRODUCT.md and DESIGN.md. Distinguish reference marketing screenshots, fixture screenshots, and live authenticated captures.
2. Default to a two-column messenger with an optional computer/details panel. Support light, dark and system themes. Mobile shows inbox or chat, with an obvious back action. Preserve the colored bot silhouettes.
3. Identify the action the person is trying to complete and the state transitions it requires. Map loading, success, empty, error, cancelled, disconnected, and unauthorized states before adding decoration.
4. Read [visual-system.md](references/visual-system.md) for layout, typography, icons, and surface rules. For bot identity, streaming, or generation, also read [motion-and-state.md](references/motion-and-state.md).
5. For work touching data or navigation, read [interaction-contracts.md](references/interaction-contracts.md). Before shipping, use [verification.md](references/verification.md).

## Strong constraints from this user

- Follow the latest references: a softly rounded, quiet gray selected row is allowed. Earlier absolute bans on rounded selections are superseded. Avoid turning every element into a floating card or pill. Use continuous surfaces and subtle dividers.
- One continuing conversation per bot or group. A new user lands with Chief ready to help. Do not ask a nontechnical person to choose a model, manage context, select a thread, or understand orchestration to send a message.
- Keep memory, files, skills, advanced settings and technical diagnostics behind clearly named details. The primary screen has inbox, chat and composer. Groups have human names, member identities and an obvious @ picker.
- Icons must be rounded, substantial, optically balanced, and recognizable at actual size. Avoid spindly one-pixel line art, sparkle decorations, and unrelated mixed packs. Labels need a little more weight without making every line bold.
- Never decorate every surface with colored glows, gradients, blur, badges, borders, or shadows. Generated-image scanning light is a specific working signal, not a site-wide theme.
- Keep real working states visible until the task ends. A spinner must not claim a response is underway after transport disconnects or continue after backend cancellation completes.
- Empty states describe the current bot and offer one useful next step. Never seed fake inbox conversations, schedules, connectors, or activity into a live account.
- Keep the user's existing bot names, messages, account state, theme preference, and files intact. Test with clearly named QA data.

## Implementation approach

Prefer existing tokens and shared components. Keep icons and avatar geometry in reusable SVG components. Use CSS transform/opacity transitions for small UI feedback; add a motion library only when it solves measured gesture/layout complexity.

Derive bot activity from real task/tool events. Capture owner, agent, conversation, and task identity in async operations; navigation cannot transfer late results to the current view. Treat all remote message content as untrusted; render markdown without raw HTML and resolve assets through authenticated file routes.

## Reference interpretation

The September 17 references establish the current direction: desktop recordings show search, grouped bot rows, compact title, one transcript and bottom composer. The optional third pane shows the actual computer and real routines. The small avatar recording shows a red organic body, dark tilted eyes, a green working dot and occasional surface highlight. Official iOS App Store screenshots use dark marketing panels around mostly light app screens; do not mistake the marketing background for the app theme. Inspect actual screenshots, never claim marketing images prove native behavior.

Start with the simplest complete task: open Chief, type a request, see a truthful working state, read the answer, find an earlier answer. Add optional capability through the plus menu, @ picker and details. A person should be able to describe each visible action in ordinary words. Label ambiguous icons.

If Impeccable is installed, use it for the requested critique, audit, or polish while treating these pinned style constraints as the brief. Do not initiate a new aesthetic questionnaire during an authorized refinement.

## Completion

Run the relevant build and behavior checks. Inspect desktop and narrow mobile captures together, fix identified defects in a batch, then confirm once. Security or correctness defects warrant focused regression checks beyond a visual pass. Report what changed, what was verified live versus mocked, and any remaining dependency or limitation. Avoid claims of perfection.

