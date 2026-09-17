# Reference notes

The Hermes UI is reference inspired rather than an exact Grok Bot replica. The supplied seed video and the public Grok Bot site were inspected on 2026-09-16; the observations below are separated from Hermes product decisions.

## Observed in the seed video

At 7:54 / 21:31 in [the supplied YouTube video](https://www.youtube.com/watch?v=NyfYxpXiw_0), a dark desktop Grok Bot window is visible behind a Windows File Explorer window while an agent inspects a `NewThumbs` folder. The interface includes:

- a narrow left sidebar with Search, a 2×2 grid of colorful bot avatars (Klaus, Dan, Becky and Chandler), and a content list with Motion, Views, Miner, Plugins and the signed-in user;
- a central conversation headed “Dev”, a “Dash” message, dark gray rounded bubbles and a composer labeled “Message Dev”;
- a right pane with a “Dev’s screen” preview and a “Create Routine” button;
- bright blue, teal, orange, green and purple bot accents on near-black surfaces, rounded corners, thin dividers and compact sans-serif text.

The foreground File Explorer view shows `Nate - Personal > Documents > NewThumbs` and thumbnail cards such as “Grok Bot Course” and “Zero to Pro”. This confirms the agent-computer workflow. The frame was captured from the live video view; no local image file was saved.

## Observed on grokbot.sh

The public [grokbot.sh board](https://www.grokbot.sh/) is a separate light editorial board with navigation for Houses, Companies, Bloub, Activity, How it works, Blog, For bots and Connect. It includes a “Find a finished bot job” hero, a House 348 block, job feed cards/table toggle, category filters, integration links and a dark-mode switch. The page identifies itself as a community board and says it is not affiliated with xAI or Cursor.

## Inferred for Hermes

- Hermes uses the requested product concepts as a workflow checklist: named bots, private/shared memory, files, runs, approvals, an optional computer and mobile access.
- The shell uses a dark sidebar, spacious chat surface and focused detail panel. This is a Hermes product decision for a family friendly workflow, informed by the observed hierarchy and color density.
- Mobile behavior follows iPhone conventions: safe-area padding, 44px touch targets, bottom navigation and a slide-in bot drawer.

The implementation avoids seeded assistant replies and fabricated runtime status. Empty states, task progress and runtime errors remain explicit until authenticated API data arrives.

