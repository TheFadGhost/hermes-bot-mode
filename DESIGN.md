---
name: Hermes Bot Mode
description: A light, restrained bot messenger with colorful shaped identities and a focused creator.
colors:
  canvas: "#ffffff"
  surface: "#ffffff"
  canvas-raised: "#fafafa"
  surface-soft: "#f1f1f1"
  surface-muted: "#e8e8e8"
  ink: "#242424"
  ink-soft: "#626262"
  ink-muted: "#727272"
  line: "#ededed"
  line-strong: "#d9d9d9"
  sidebar: "#f7f7f7"
  sidebar-raised: "#e7e7e7"
  accent: "#252525"
  accent-ink: "#ffffff"
  accent-strong: "#1970cb"
  creator-blue: "#2d93fa"
  aqua: "#1970cb"
  danger: "#bd3434"
  status-green: "#259d65"
  avatar-cedar: "#996638"
  avatar-coral: "#ff3347"
  avatar-tangerine: "#ff6713"
  avatar-marigold: "#ff9d0a"
  avatar-meadow: "#17c765"
  avatar-teal: "#0eb8b0"
  avatar-sky: "#2d93fa"
  avatar-iris: "#8754f5"
  avatar-pink: "#ff36a0"
  avatar-graphite: "#7a7a7a"
typography:
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI, sans-serif"
    fontSize: "20px"
    fontWeight: 500
    lineHeight: 1.12
    letterSpacing: "-0.025em"
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI, sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.35
rounded:
  xs: "6px"
  sm: "8px"
  md: "10px"
  lg: "12px"
  xl: "15px"
  pill: "24px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  section: "28px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "42px"
  button-secondary:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "42px"
  icon-button:
    backgroundColor: "transparent"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.md}"
    size: "36px"
  input-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "42px"
  message-assistant:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "15px"
    padding: "11px 14px"
  message-user:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.body}"
    rounded: "15px"
    padding: "11px 14px"
---

# Design System: Hermes Bot Mode

## Overview

**Creative North Star: "The Quiet Messenger"**

Hermes is a light, calm workspace that keeps attention on the conversation. The roster, chat, and optional inspector read as one continuous surface: quiet neutrals establish structure while each bot gets a compact, colorful organic identity. Typography is system native, small, and legible, with restrained weight and generous message breathing room.

The creator follows the same restraint in a centered 300px form: one large live avatar, a short color and shape choice, a clear name field, optional details, and a small suggestion rail. Motion is feedback only, generally 140–220ms, and is removed under reduced motion. The user's Grok Bot light messenger references are the visual authority; research captures are evidence, while verification captures are fixtures.

**Key Characteristics:**
- Light messenger canvas with tonal gray layering and a near-black action accent.
- Colorful SVG bot identities built from eight organic contours and consistent eye marks.
- Desktop roster/chat/inspector structure that collapses into an inbox-first mobile flow.
- Centered creator with direct controls and minimal copy.

## Colors

The palette is near-white and gray at rest, with a near-black primary action, blue interaction states, red errors, and saturated avatar colors.

### Primary
- **Ink Accent** ({colors.accent}): Primary buttons and user message bubbles.
- **Interaction Blue** ({colors.accent-strong}): Focus, links, readiness states, and selected creator controls.

### Neutral
- **Canvas White** ({colors.canvas}): Main application and form surface.
- **Raised Canvas** ({colors.canvas-raised}): Inspector and raised page background.
- **Soft Gray** ({colors.surface-soft}): Secondary controls, assistant bubbles, and quiet cards.
- **Muted Gray** ({colors.surface-muted}): Hover and selected tonal fill.
- **Ink** ({colors.ink}): Primary text.
- **Soft Ink** ({colors.ink-soft}): Supporting text and icon controls.
- **Muted Ink** ({colors.ink-muted}): Metadata, hints, and placeholders.
- **Hairline** ({colors.line}): Default dividers and borders.
- **Strong Hairline** ({colors.line-strong}): Composer and field borders.
- **Sidebar Gray** ({colors.sidebar}): Desktop roster background.
- **Sidebar Selected** ({colors.sidebar-raised}): Selected roster and workspace navigation item.

### Named Rules
**The One Accent Rule.** Reserve saturated blue for interaction and state; bot colors belong to bot identity.

## Typography

**Body Font:** Apple system stack (-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI, sans-serif)

**Character:** Native, compact, and readable. Weight carries hierarchy more than large type or decorative display faces.

### Hierarchy
- **Title** (500, 20px, 1.12): Empty-state headings and focused modal or page titles.
- **Body** (400, 14px, 1.5): Conversation content and ordinary explanatory copy.
- **Label** (550–600, 12px, 1.35): Navigation, controls, metadata, and creator labels.
- **Micro label** (400–500, 10–11px): Times, status, and secondary hints.

**The Native Type Rule.** Keep the system stack and let spacing, weight, and tonal contrast create hierarchy.

## Layout

Desktop uses a full-height three-part grid: a fixed 258px roster, a fluid conversation column, and an optional 292px inspector. Without details, the chat expands into the remaining width. At widths below 1100px, the inspector hides and the roster becomes 238px; at 640px and below, the app becomes an inbox-first mobile flow with full-width content.

The mobile inbox shows the first three bots as large quick-access identities, then a compact list. Selecting a bot replaces the inbox with chat; the top bar provides back navigation and access to details. The creator remains a full-height surface and centers its primary form at 300px, expanding to a single column on narrow screens. Common spacing is 4/8/12/16/24px, with 28px message and page breathing room.

## Elevation & Depth

The messenger is flat by default and uses borders and tonal surfaces for structure. Small resource cards may use the nearly invisible 0 2px 8px #00000006 shadow; dialogs use 0 14px 50px #00000018 to separate them from the scrim. Focus is communicated with a blue outline or ring.

**The Flat Surface Rule.** Use tonal layering and hairlines for ordinary hierarchy; reserve a shadow for a floating dialog or a deliberately raised resource card.

## Shapes

The latest September 17 references allow softly rounded gray selected inbox rows. Keep the rest of the list integrated into the sidebar without floating card shadows. Message bubbles use conversational curves; the composer is softly rounded and avatars are organic SVG silhouettes. Creator swatches are circular with visible selection and keyboard focus.

## Components

### Buttons
- **Shape:** 10px corners for standard buttons (42px minimum height); small buttons use 8px.
- **Primary:** Near-black fill, inverse text, 0 16px padding.
- **Hover / Focus:** Primary opacity reduces on hover; controls use a visible 2px blue focus outline. Feedback transitions stay around 140ms.
- **Icon buttons:** Transparent 36px square targets with 9px corners; mobile targets expand to 44px.

### Cards / Containers
- **Corner Style:** 12px for ordinary resource and approval cards; 15–17px for larger cards and suggestions.
- **Background:** White or raised canvas against soft gray and sidebar tones.
- **Shadow Strategy:** Flat at rest; use the Elevation & Depth vocabulary for floating dialogs and rare resource lift.
- **Border:** 1px hairline, strengthened only where a field or preview needs definition.
- **Internal Padding:** 12–18px for compact cards; 24–26px for auth and dialog content.

### Inputs / Fields
- **Style:** White field with a 1px hairline and 9px corners; 42px name inputs and 99px minimum creator textareas.
- **Focus:** Blue border plus a soft 3px blue ring.
- **Error / Disabled:** Red error copy; disabled actions are reduced to 42% opacity.

### Navigation
- **Desktop:** roughly 260–294px roster with readable bot rows, compact search and account footer. Show chat by default and details only when requested. No primary technical tab bar.
- **Mobile:** Full inbox with three featured bots, compact remaining rows, then a 44px-target top bar with back, search, create, and details actions.

### Bot Identity
BotGlyph is the signature component: eight organic contours (blob, orb, capsule, lozenge, peak triangle, hex, cloud, drop) share two white eye marks and draw from a ten-color palette. The server's stored avatar, color, and optional image remain authoritative.

### Creator
The creator is a centered, single-purpose form with an 80px live identity preview, 10 color swatches, 8 shape tiles, a name field, optional expandable instructions, and two suggestion cards. It supports keyboard roving selection and visible focus.

## Do's and Don'ts

### Do:
- **Do** preserve real stored bots, conversations, streamed messages, approvals, files, memory, and computer controls.
- **Do** keep the desktop roster at 258px, the optional inspector at 292px, and the mobile breakpoint at 640px.
- **Do** use the shaped SVG identity family and server-persisted avatar color and shape.
- **Do** keep motion to short feedback transitions and honor `prefers-reduced-motion: reduce`.
- **Do** provide named controls, keyboard access, visible focus, readable contrast, and mobile touch targets.

### Don't:
- **Don't** add controls that imply unimplemented routines, email connectors, group conversations, or voice input.
- **Don't** use research screenshots or verification fixture data as production bot or conversation content.
- **Don't** turn the messenger into a generic dashboard with heavy cards, gradients, or decorative display typography.
- **Don't** canonize the creator's sample suggestions as real stored bots.

## Image creation motion

The supplied September 16 screen recording governs the image placeholder: charcoal canvas in either theme, fine regular dots and a soft traveling spotlight that brightens the dots locally. Caption and actual prompt sit beneath the canvas. Aspect follows the actual request. Stop/failure ends motion; only the saved authenticated image replaces it. See `skills/grok-ui-style/references/motion-and-state.md` for the complete contract.

