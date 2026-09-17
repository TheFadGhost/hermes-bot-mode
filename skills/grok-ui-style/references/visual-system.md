# Visual system

## Continuous layout

Desktop is a single surface: 258 px pale sidebar, flexible white conversation, optional 292 px inspector. A one-pixel divider separates columns; outer gutters and decorative panels do not. At intermediate widths around 1100 px, move the inspector to a dismissible overlay. At 640 px and below, show inbox OR conversation with clear back navigation. Never compress all desktop columns into a phone screen.

The first three mobile bots can appear as larger quick access identities; the rest remain compact readable rows. Keep name, useful preview, and time aligned. A selected row can use a quiet gray wash with 8–12 px corners, following the latest recording. Avoid nested borders and floating shadows. Hover cannot obscure selection. Unread, active, disabled and keyboard focus remain distinguishable without relying solely on color.

## Tokens and hierarchy

Default light: canvas #fff, sidebar #f7f7f7, subtle surface #f1f1f1, main ink #242424, secondary ink #626262, muted ink #727272, line #ededed, strong line #d9d9d9. Action blue #1970cb and identity blue #2d93fa have separate roles. Destructive ink #bd3434. Use semantic variables so dark/system themes follow the same hierarchy.

Use system text fonts: -apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI, sans-serif. Body 14 px with 1.5 line-height; mobile chat 15–16 px; inputs on iOS at least 16 px to avoid focus zoom. Functional labels 12–13 px, weight 550–600. Bot names and primary navigation 550–600; supporting previews remain regular. Avoid tiny all-caps labels or heavy body text. Ensure the chosen system font supports the intended weights; 600 is a safe fallback to variable 550.

Use 4/8/12/16/24/28 px spacing. Align surfaces to shared baselines. Names truncate while labels and errors wrap. Give scrolling flex children min-width:0 and min-height:0. Reserve stable layout space for state indicators so text does not jump on every event.

## Icon construction

A coherent 24×24 viewBox, usually 18–20 px visible, with round linecaps and joins; optical stroke around 1.8–2.2 at nominal size. Match stroke visually rather than applying arbitrary thickness to every shape. Use a few subtle filled areas in primary destination icons for character and readable silhouettes. Do not make every icon a monochrome solid blob.

Overview should suggest the bot/profile or conversation, memory a recognizable layered memory/book form, files a folder/document, activity a simple rhythmic trace, and computer a monitor with a substantial foot. Sparkles are not a default Overview metaphor. Keep supporting icon buttons in the same rounded family. Favor familiar action meanings over ornamental novelty.

Do not shrink hit targets to the drawn icon. Aim at least 44×44 px for touch. A 20 px icon can live in a 44 px transparent button. Icon-only controls need explicit accessible names and tooltips where useful. Focus-visible must be distinct from hover/active.

## Bot identities

The eight contours are blob, orb, capsule, lozenge, peak, hex, cloud, drop. Preserve the two slightly tilted eye marks and tune their positions per contour. A stable agent ID determines a fallback; render must never randomize the bot's color or shape. Chosen values persist through reload and updates.

Palette: cedar #996638, coral #ff3347, tangerine #ff6713, marigold #ff9d0a, meadow #17c765, teal #0eb8b0, sky #2d93fa, iris #8754f5, pink #ff36a0, graphite #7a7a7a. Identity colors are expressive assets, not tiny text colors. Selection uses a separate focus/selection ring; all swatches need names.

## Where curves belong

Use curves for bot silhouettes, message bubbles, the composer, compact buttons, selected inbox rows and physical overlays. Keep ordinary settings rows and empty states integrated into their parent surface. Message bubbles can use an asymmetric conversational shape; a live-image placeholder can use a deliberate squircle representing the generating image.

Shadows only explain elevation: modal/sheet, popover, floating control. Main app columns and bot rows have no shadows. Borders separate content; avoid a border nested inside another bordered card.

## Creator

Centered 80 px identity preview, color and shape choices, roughly 300 px name field, optional instructions, one creation action. Desktop color choices fit a single row; phone wraps to five swatches per row with 44 px touch targets. Shape radio navigation supports arrow keys and a single tab stop. Do not focus the phone keyboard on first render. Suggestions should populate real fields, never promise connected email or scheduled work that is unavailable.

