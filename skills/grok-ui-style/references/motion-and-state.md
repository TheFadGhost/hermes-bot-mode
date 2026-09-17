# Motion and state

Motion tells the person what is happening, what changed, and what they can do next. It should not run indefinitely for personality alone.

## Event-driven state model

| State | Evidence | Visual and accessible feedback |
|---|---|---|
| Idle | No active task | Still bot avatar; ready composer |
| Queued/connecting | Durable task created, no turn start | Small status label, quiet pulse; Stop available once task ID exists |
| Thinking | turn.started, no visible text or active tool | Gentle eye/body movement, green activity dot and a polite status label |
| Typing | assistant.delta | Subtle avatar response; text grows without animating every token individually |
| Using tool | tool.started, no matching completion | Persistent concise action label and restrained avatar motion |
| Generating image | Actual image_generate tool begins | Dark image canvas with fine dots and a moving local spotlight; factual status |
| Awaiting approval | Durable approval event | Motion settles; explicit action/approve/decline controls |
| Completed | task.completed | Brief settle (once), then still; actual output replaces placeholder |
| Cancelled | Server confirms task.cancelled | Settle, explain stopped; retain partial output appropriately |
| Failed | task.error or validated failure | Stop animation, show readable error and retry route |
| Reconnecting | Transport drops before terminal event | Distinct reconnect label; resume task cursor, never fake completion |

The latest task state wins. A late tool event from a finished or different task cannot reactivate the avatar. A tool can run after initial assistant text; keep working feedback until the terminal event. Completion belongs to the server task, not the end of one fetch stream.

## Timing and implementation

Use opacity/transform. Press 90–120 ms with maximum scale change about .02–.03; hover/focus 120–160 ms; small reveal 180–240 ms; dialog/sheet 220–300 ms. A practical ease-out is cubic-bezier(.22,1,.36,1). Keep translations under 8 px for menus/text. Avoid spring overshoot on frequently clicked controls and avoid global transition:all.

Bot working loops around 1.4–2.4 s can move a few pixels or scale the body by at most 3%. Eyes can respond independently using transform-origin. Staggering two eye motions is enough. Never rotate the whole avatar like a loader. No shaking error or confetti completion in routine chat.

Match the September 17 close-up: organic body softly compresses and returns, eyes tilt or blink independently, and a narrow soft highlight occasionally crosses the upper body. Keep the highlight clipped to the silhouette. The green activity dot reflects a real active task, not whether the service is reachable. Use dark eyes when matching the recording; maintain contrast across all colors. Add no permanent idle animation. The effect must read at 28–40 px, with a more expressive 64–80 px creator preview.

## Image generation

Match the supplied recording: a charcoal image canvas in both themes, a fine regular grid of dim dots about 11 px apart, and a soft moving spotlight that brightens only nearby dots. The light travels through the field without washing out the background. Avoid a diagonal shimmer, large bouncing dots, borders around the whole status block and a nested loader card. The 12–14 px corner curve belongs to the image surface.

Use the tool's real aspect ratio, preserving a stable footprint: approximately 205 px square, 166 × 250 px portrait, or 256 × 171 px landscape as reference proportions. Keep a small aspect label in the upper right; show pixel dimensions only when the actual requested output size is known. Put Generating image beneath the canvas, followed by the real quoted prompt in muted text. The reference recording's outer preview frame and format/theme dropdowns are demo controls, not product UI. Announce status once. Never invent percentages or stages based on elapsed time.

The tool must return an authenticated asset/file reference. Replace the placeholder with the actual image on success, expose download and descriptive alt text, and retain the file on reload. A tool result containing an error must replace the placeholder with error text. Stop may stop waiting even if a remote provider cannot cancel its billable job; disclose that limitation accurately in relevant UI copy.

Do not detect generation merely from words such as image in the user's prompt. Don't show generated stock/demo images. Never animate tool arguments or leak private provider URLs/credentials.

## Reduced motion and background activity

Provide System, On and Off in Settings with a small active preview. System follows prefers-reduced-motion; Off always removes loops, sweeps, travel and scale. Explicit On permits gentle motion even when the device asks for reduced motion. Persist the choice on this device and apply it before the first render. Keep CSS and JavaScript motion preferences consistent. Retain static dots, status labels, focus, and instant state updates when motion is reduced. A static working symbol must remain distinguishable from idle. Avoid animations on hidden conversation panels or dozens of sidebar avatars; animate only relevant visible active work. Stop loops when document is hidden where practical.

Test reduced motion and rapid state transitions. Timers need cleanup on unmount and task changes. Use keyed task identity for one-time completion feedback so rerenders don't replay it. Avoid aria-live for every token; announce state changes politely and let the transcript remain selectable and readable.

