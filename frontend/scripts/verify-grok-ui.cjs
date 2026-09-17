/* Focused fixture checks for the simplified Hermes messenger shell.
 * Usage: BOT_MODE_URL=http://127.0.0.1:5173/bot/ node scripts/verify-grok-ui.cjs
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { chromium } = require('C:/Users/Work/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

const baseURL = process.env.BOT_MODE_URL || 'http://127.0.0.1:5173/bot/';
const outputDir = path.resolve(__dirname, '../../design-research/verification');
fs.mkdirSync(outputDir, { recursive: true });

const agents = [
  { id: 'agent-alpha', name: 'Alpha', description: 'Coordinates the work.', color: '#8754f5', avatar: 'blob', is_active: true, model: 'gpt-5.6-luna' },
  { id: 'agent-beta', name: 'Beta', description: 'Keeps details moving.', color: '#2d93fa', avatar: 'drop', is_active: true, model: 'gpt-5.6-luna' },
  { id: 'agent-scout', name: 'Scout', description: 'Finds useful context.', color: '#17c765', avatar: 'orb', is_active: true, model: 'gpt-5.6-luna' },
];

const entries = [
  { conversation_id: 'conversation-alpha', kind: 'direct', agent_id: 'agent-alpha', coordinator_id: 'agent-alpha', name: 'Alpha', members: [{ agent_id: 'agent-alpha', name: 'Alpha', role: 'coordinator', color: '#8754f5', avatar: 'blob' }], preview: 'Ready to help', updated_at: '2026-09-17T08:30:00Z', unread_count: 0, pinned: false, archived: false, active_tasks: [] },
  { conversation_id: 'conversation-beta', kind: 'direct', agent_id: 'agent-beta', coordinator_id: 'agent-beta', name: 'Beta', members: [{ agent_id: 'agent-beta', name: 'Beta', role: 'coordinator', color: '#2d93fa', avatar: 'drop' }], preview: 'A separate workstream', updated_at: '2026-09-17T08:20:00Z', unread_count: 2, pinned: true, archived: false, active_tasks: [] },
  { conversation_id: 'conversation-weekend', kind: 'group', agent_id: 'agent-alpha', coordinator_id: 'agent-alpha', name: 'Weekend Crew', members: [{ agent_id: 'agent-alpha', name: 'Alpha', role: 'coordinator', color: '#8754f5', avatar: 'blob' }, { agent_id: 'agent-beta', name: 'Beta', role: 'member', color: '#2d93fa', avatar: 'drop' }, { agent_id: 'agent-scout', name: 'Scout', role: 'member', color: '#17c765', avatar: 'orb' }], preview: 'Planning together', updated_at: '2026-09-17T08:10:00Z', unread_count: 0, pinned: false, archived: false, active_tasks: [] },
];

const messages = {
  'conversation-alpha': [
    { id: 'alpha-1', conversation_id: 'conversation-alpha', role: 'user', content: 'Keep the plan moving.', created_at: '2026-09-17T08:00:00Z', status: 'complete' },
    { id: 'alpha-2', conversation_id: 'conversation-alpha', role: 'assistant', author_agent_id: 'agent-alpha', content: 'I’m ready when you are.', created_at: '2026-09-17T08:01:00Z', status: 'complete' },
  ],
  'conversation-beta': [{ id: 'beta-1', conversation_id: 'conversation-beta', role: 'assistant', author_agent_id: 'agent-beta', content: 'Beta has the details.', created_at: '2026-09-17T08:02:00Z', status: 'complete' }],
  'conversation-weekend': [
    { id: 'weekend-system', conversation_id: 'conversation-weekend', role: 'system', content: 'Chief asked Scout to help.', metadata: { collaboration_handoff: true, child_task_id: 'helper-1', parent_task_id: 'parent-1', helper_agent_id: 'agent-scout' }, created_at: '2026-09-17T08:03:00Z', status: 'complete' },
    { id: 'weekend-answer', conversation_id: 'conversation-weekend', role: 'assistant', author_agent_id: 'agent-beta', source_task_id: 'old-task', content: 'I’ll keep the group aligned.', created_at: '2026-09-17T08:04:00Z', status: 'complete' },
  ],
};

function gate() {
  let released = false;
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { wait: () => released ? Promise.resolve() : promise, release: () => { if (!released) { released = true; resolve(); } } };
}

function sse(...events) {
  return events.map(({ id, type, data }) => `${id === undefined ? '' : `id: ${id}\n`}event: ${type}\ndata: ${typeof data === 'string' ? data : JSON.stringify(data)}\n\n`).join('');
}

function makeFixture(options = {}) {
  const state = {
    postCount: 0,
    postBodies: [],
    tasks: {},
    cancelCalls: [],
    eventRequests: [],
    postGate: null,
    ...options,
  };
  (state.initialTasks || []).forEach((task) => { state.tasks[task.id] = task; });
  const reply = (route, payload, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload) });
  const eventReply = (route, body) => route.fulfill({ status: 200, headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' }, body });
  const handler = async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const endpoint = url.pathname.replace(/^\/bot\/api/, '');
    const method = request.method();
    let body = {};
    try { body = request.postDataJSON() || {}; } catch { body = {}; }

    if (endpoint === '/auth/me' && method === 'GET') return reply(route, { authenticated: true, user: { id: 'fixture-user', name: 'Fixture Tester' } });
    if (endpoint === '/bootstrap' && method === 'POST') return reply(route, { chief: agents[0], conversation: { id: 'conversation-alpha', agent_id: 'agent-alpha' } });
    if (endpoint === '/agents' && method === 'GET') return reply(route, { agents });
    if (endpoint === '/inbox' && method === 'GET') return reply(route, { items: entries });
    if (endpoint === '/conversations' && method === 'GET') return reply(route, { conversations: entries.map((entry) => ({ id: entry.conversation_id, agent_id: entry.agent_id, title: entry.name, updated_at: entry.updated_at })) });
    if (endpoint === '/runtime/status' && method === 'GET') return reply(route, { runtime: { available: true, provider: 'fixture', model: 'gpt-5.6-luna' } });
    if (endpoint === '/runtime/account' && method === 'GET') return reply(route, { account: { connected: true, type: 'fixture', plan: 'test', models: [{ id: 'gpt-5.6-luna', name: 'GPT 5.6 Luna' }] } });
    if (endpoint === '/runtime/usage' && method === 'GET') return reply(route, { usage: { used: 12, limit: 100, remaining: 88 } });
    if (endpoint === '/onboarding' && method === 'GET') return reply(route, { complete: true, steps: [] });
    if (endpoint === '/memory' && method === 'GET') return reply(route, { memory: [] });
    if (endpoint === '/files' && method === 'GET') return reply(route, { files: [] });
    if (endpoint === '/activity' && method === 'GET') return reply(route, { events: [] });
    if (/^\/agents\/[^/]+\/skills$/.test(endpoint) && method === 'GET') return reply(route, { skills: [] });
    if (/^\/agents\/[^/]+\/routines$/.test(endpoint) && method === 'GET') return reply(route, { routines: [] });
    if (/^\/agents\/[^/]+\/desktop$/.test(endpoint) && method === 'GET') return reply(route, { desktop: { available: false, created: false, running: false, phase: 'unavailable', control_mode: 'bot', generation: 1 } });
    if (/^\/agents\/[^/]+\/home$/.test(endpoint) && method === 'GET') return reply(route, { conversation: { id: 'conversation-alpha', agent_id: 'agent-alpha', kind: 'direct' } });

    const search = endpoint === '/search' && method === 'GET';
    if (search) return reply(route, { matches: [{ id: 'match-1', message_id: 'weekend-system', conversation_id: 'conversation-weekend', name: 'Weekend Crew', snippet: 'Chief asked Scout to help.' }] });
    const exact = endpoint.match(/^\/messages\/([^/]+)$/);
    if (exact && method === 'GET') return reply(route, { message: messages['conversation-weekend'].find((item) => item.id === decodeURIComponent(exact[1])) || messages['conversation-weekend'][0] });

    const conversationMatch = endpoint.match(/^\/conversations\/([^/]+)\/messages$/);
    if (conversationMatch && method === 'GET') return reply(route, { messages: messages[decodeURIComponent(conversationMatch[1])] || [] });
    if (conversationMatch && method === 'POST') {
      const conversationId = decodeURIComponent(conversationMatch[1]);
      state.postCount += 1;
      state.postBodies.push({ conversationId, ...body });
      if (state.postGate) await state.postGate.wait();
      const requestId = body.client_request_id || `request-${state.postCount}`;
      const newMessage = { id: `sent-${state.postCount}`, conversation_id: conversationId, role: 'user', content: body.content, created_at: '2026-09-17T08:12:00Z', status: 'complete', request_id: requestId };
      messages[conversationId] = [...(messages[conversationId] || []), newMessage];
      const taskList = conversationId === 'conversation-weekend'
        ? [{ id: `parent-${state.postCount}`, conversation_id: conversationId, origin_conversation_id: conversationId, agent_id: 'agent-alpha', request_id: requestId, status: 'running', phase: 'Thinking' }, { id: `helper-${state.postCount}`, conversation_id: 'helper-private', origin_conversation_id: conversationId, parent_task_id: `parent-${state.postCount}`, agent_id: 'agent-scout', request_id: requestId, status: 'running', phase: 'Searching chat history' }]
        : [{ id: `task-${state.postCount}`, conversation_id: conversationId, agent_id: 'agent-alpha', request_id: requestId, status: 'running', phase: 'Thinking' }];
      taskList.forEach((task) => { state.tasks[task.id] = task; });
      return reply(route, { message: newMessage, tasks: taskList, request_id: requestId });
    }

    const taskListMatch = endpoint.match(/^\/conversations\/([^/]+)\/tasks$/);
    if (taskListMatch && method === 'GET') {
      const conversationId = decodeURIComponent(taskListMatch[1]);
      return reply(route, { tasks: Object.values(state.tasks).filter((task) => task.origin_conversation_id === conversationId || task.conversation_id === conversationId) });
    }
    const cancelRequest = endpoint.match(/^\/conversations\/([^/]+)\/requests\/([^/]+)\/cancel$/);
    if (cancelRequest && method === 'POST') {
      const conversationId = decodeURIComponent(cancelRequest[1]);
      const requestId = decodeURIComponent(cancelRequest[2]);
      state.cancelCalls.push({ conversationId, requestId });
      const cancelled = Object.values(state.tasks).filter((task) => task.origin_conversation_id === conversationId || task.conversation_id === conversationId || task.request_id === requestId).map((task) => ({ ...task, status: 'cancelled' }));
      cancelled.forEach((task) => { state.tasks[task.id] = task; });
      return reply(route, { tasks: cancelled });
    }
    const taskEvents = endpoint.match(/^\/tasks\/([^/]+)\/events$/);
    if (taskEvents && method === 'GET') {
      const taskId = decodeURIComponent(taskEvents[1]);
      state.eventRequests.push({ taskId, afterId: Number(url.searchParams.get('after_id') || 0) });
      if (taskId.startsWith('parent-')) return eventReply(route, sse({ id: 1, type: 'task.started', data: { task_id: taskId } }, { id: 2, type: 'approval', data: { approval_id: `approval-${taskId}`, kind: 'Send', description: 'Send the group update now?' } }));
      return eventReply(route, sse({ id: 1, type: 'task.started', data: { task_id: taskId } }, { id: 2, type: 'turn.started', data: { agent_id: 'agent-scout' } }));
    }
    const taskState = endpoint.match(/^\/tasks\/([^/]+)$/);
    if (taskState && method === 'GET') return reply(route, { task: state.tasks[decodeURIComponent(taskState[1])] || { id: decodeURIComponent(taskState[1]), status: 'running' } });
    if (/^\/conversations\/[^/]+\/read$/.test(endpoint) && method === 'POST') return reply(route, {});

    return reply(route, {});
  };
  return { state, handler };
}

async function waitFor(predicate, label, timeout = 7000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 40));
  }
  throw new Error(`Timed out waiting for ${label}`);
}

async function runScenario(browser, name, fixtureOptions, contextOptions, test, report) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light', reducedMotion: 'no-preference', ...contextOptions });
  if (contextOptions?.theme === 'dark') await context.addInitScript(() => localStorage.setItem('hermes-theme', 'dark'));
  const page = await context.newPage();
  page.setDefaultTimeout(6000);
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  const fixture = makeFixture(fixtureOptions);
  try {
    await page.route('**/bot/api/**', fixture.handler);
    await test(page, fixture.state);
    assert.deepStrictEqual(pageErrors, [], `page errors: ${pageErrors.join(' | ')}`);
    report.push({ name, status: 'passed' });
  } catch (error) {
    try { await page.screenshot({ path: path.join(outputDir, `grok-${name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-failure.png`), fullPage: true, animations: "disabled" }); } catch { /* best effort diagnostics */ }
    report.push({ name, status: 'failed', error: error.message, postCount: fixture.state.postCount, cancelCalls: fixture.state.cancelCalls, eventRequests: fixture.state.eventRequests });
    throw error;
  } finally {
    fixture.state.postGate?.release();
    await context.close();
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const report = [];
  try {
    await runScenario(browser, 'desktop group transcript and details', {}, {}, async (page) => {
      await page.goto(baseURL);
      await page.locator('.grok-inbox-row').first().waitFor();
      await page.locator('.grok-inbox-row').filter({ hasText: 'Weekend Crew' }).click();
      await page.getByRole('textbox', { name: 'Message Weekend Crew', exact: true }).waitFor();
      assert.strictEqual(await page.locator('.grok-handoff-event').count(), 1, 'handoff should be a quiet event');
      assert.strictEqual(await page.locator('.conversation-tabs').count(), 0, 'legacy chat tabs should be absent');
      await page.getByRole('button', { name: 'Toggle details', exact: true }).click();
      await page.getByText('Optional computer', { exact: true }).waitFor();
      await page.screenshot({ path: path.join(outputDir, 'grok-desktop-group.png'), fullPage: true, animations: "disabled" });
    }, report);

    await runScenario(browser, 'group mentions, multistream approval and Stop', {}, {}, async (page, state) => {
      await page.goto(baseURL);
      await page.locator('.grok-inbox-row').filter({ hasText: 'Weekend Crew' }).click();
      const composer = page.getByRole('textbox', { name: 'Message Weekend Crew', exact: true });
      await composer.waitFor();
      await page.getByRole('button', { name: 'Mention a Bot', exact: true }).click();
      await page.getByRole('button', { name: /@Beta/ }).click();
      await composer.fill('@Beta please check this');
      await composer.press('Enter');
      await waitFor(() => state.postCount === 1, 'one group POST');
      assert.deepStrictEqual(state.postBodies[0].mention_agent_ids, ['agent-beta']);
      await page.getByText('Before I do that', { exact: true }).waitFor();
      await waitFor(async () => {
        const count = await page.locator('.grok-live-task').count();
        if (count < 2) return false;
        return true;
      }, 'two visible task streams');
      await page.getByRole('button', { name: 'Stop work', exact: true }).click();
      await waitFor(() => state.cancelCalls.length === 1, 'group request cancellation');
      assert.strictEqual(state.cancelCalls[0].requestId, state.postBodies[0].client_request_id);
      await page.screenshot({ path: path.join(outputDir, 'grok-group-stop.png'), fullPage: true, animations: "disabled" });
    }, report);

    await runScenario(browser, 'initial POST guard and Stop recovery', { postGate: gate() }, {}, async (page, state) => {
      await page.goto(baseURL);
      await page.locator('.grok-inbox-row').filter({ hasText: 'Alpha' }).click();
      const composer = page.getByRole('textbox', { name: 'Message Alpha', exact: true });
      await composer.waitFor();
      await composer.fill('Please start this carefully');
      await composer.press('Enter');
      await composer.press('Enter');
      await waitFor(() => state.postCount === 1, 'single in-flight POST');
      await page.getByRole('button', { name: 'Stop work', exact: true }).click();
      state.postGate.release();
      await waitFor(() => state.cancelCalls.length === 1, 'cancel after POST resolves');
      await waitFor(async () => (await page.locator('.grok-send-button.is-stop').count()) === 0, 'composer recovery');
      assert.strictEqual(await composer.inputValue(), 'Please start this carefully');
      await page.screenshot({ path: path.join(outputDir, 'grok-post-stop-recovery.png'), fullPage: true, animations: "disabled" });
    }, report);

    await runScenario(browser, 'durable task remains reconnectable after transport loss', { initialTasks: [{ id: 'reconnect-task', conversation_id: 'conversation-alpha', agent_id: 'agent-alpha', request_id: 'reconnect-request', status: 'running', phase: 'Working' }] }, {}, async (page, state) => {
      await page.goto(baseURL);
      await page.locator('.grok-inbox-row').filter({ hasText: 'Alpha' }).click();
      await page.getByRole('textbox', { name: 'Message Alpha', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Stop work', exact: true }).waitFor();
      await waitFor(() => page.getByText(/Your run may still be active/).count().then((count) => count > 0), 'recoverable disconnected task', 7000);
      const firstWatchCount = state.eventRequests.filter((item) => item.taskId === 'reconnect-task').length;
      assert.ok(firstWatchCount >= 1, 'durable task should be watched from inbox recovery');
      await page.locator('.grok-inbox-row').filter({ hasText: 'Weekend Crew' }).click();
      await page.locator('.grok-inbox-row').filter({ hasText: 'Alpha' }).click();
      await waitFor(() => state.eventRequests.filter((item) => item.taskId === 'reconnect-task').length > firstWatchCount, 'reattached durable task', 7000);
      await page.screenshot({ path: path.join(outputDir, 'grok-task-reconnectable.png'), fullPage: true, animations: "disabled" });
    }, report);

    await runScenario(browser, '320px dark reduced motion layout', {}, { viewport: { width: 320, height: 720 }, reducedMotion: 'reduce', theme: 'dark' }, async (page) => {
      await page.goto(baseURL);
      await page.locator('.grok-inbox-row').first().waitFor();
      const width = await page.evaluate(() => ({ body: document.body.scrollWidth, root: document.documentElement.scrollWidth, viewport: window.innerWidth }));
      assert.ok(Math.max(width.body, width.root) <= width.viewport + 1, `horizontal overflow at 320px: ${JSON.stringify(width)}`);
      await page.locator('.grok-inbox-row').filter({ hasText: 'Weekend Crew' }).click();
      await page.getByRole('textbox', { name: 'Message Weekend Crew', exact: true }).waitFor();
      const chatWidth = await page.evaluate(() => ({ body: document.body.scrollWidth, root: document.documentElement.scrollWidth, viewport: window.innerWidth }));
      assert.ok(Math.max(chatWidth.body, chatWidth.root) <= chatWidth.viewport + 1, `chat overflow at 320px: ${JSON.stringify(chatWidth)}`);
      assert.strictEqual(await page.locator('[data-theme="dark"]').count(), 1, 'dark theme should be applied');
      await page.screenshot({ path: path.join(outputDir, 'grok-mobile-dark-reduced.png'), fullPage: true, animations: "disabled" });
    }, report);
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(outputDir, 'grok-ui-test-report.json'), JSON.stringify({ baseURL, generated_at: new Date().toISOString(), scenarios: report }, null, 2));
  }
  if (report.some((item) => item.status === 'failed')) process.exitCode = 1;
  console.log(JSON.stringify({ scenarios: report, screenshots: outputDir }, null, 2));
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
