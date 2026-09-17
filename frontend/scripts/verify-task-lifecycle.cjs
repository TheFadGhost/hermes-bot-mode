/*
 * Fixture-only task lifecycle verification for Bot Mode.
 *
 * The fixture deliberately closes an SSE response without a terminal event in
 * a few cases. This keeps the checks focused on durable task recovery instead
 * of making a browser test depend on a live runtime provider.
 *
 * Usage: node scripts/verify-task-lifecycle.cjs
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('C:/Users/Work/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

const baseURL = process.env.BOT_MODE_URL || 'http://127.0.0.1:5175/bot/';
const auditDir = path.resolve(__dirname, '../../design-research/audit-20260916');

const agents = [
  { id: 'agent-alpha', name: 'Alpha', description: 'Keeps a long running plan moving.', color: '#8754f5', avatar: 'blob', is_active: true, memory_scope: 'private', model: 'gpt-5.6-luna' },
  { id: 'agent-beta', name: 'Beta', description: 'Handles a separate workstream.', color: '#2d93fa', avatar: 'drop', is_active: true, memory_scope: 'private', model: 'gpt-5.6-luna' },
];

const conversations = [
  { id: 'conversation-alpha', agent_id: 'agent-alpha', title: 'Alpha work', updated_at: '2026-09-16T09:20:00Z', message_count: 2 },
  { id: 'conversation-beta', agent_id: 'agent-beta', title: 'Beta work', updated_at: '2026-09-16T09:10:00Z', message_count: 2 },
];

function seedMessages() {
  return {
    'conversation-alpha': [
      { id: 'alpha-user', conversation_id: 'conversation-alpha', role: 'user', content: 'Start the long running task.', created_at: '2026-09-16T09:00:00Z', status: 'complete' },
    ],
    'conversation-beta': [
      { id: 'beta-user', conversation_id: 'conversation-beta', role: 'user', content: 'Keep the beta workstream separate.', created_at: '2026-09-16T09:01:00Z', status: 'complete' },
    ],
  };
}

function gate() {
  let released = false;
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return {
    wait: () => released ? Promise.resolve() : promise,
    release: () => { if (!released) { released = true; resolve(); } },
  };
}

function sse(...events) {
  return events.map(({ id, type, data }) => `${id === undefined ? '' : `id: ${id}\n`}event: ${type}\ndata: ${typeof data === 'string' ? data : JSON.stringify(data)}\n\n`).join('');
}

function png1x1() {
  return Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64');
}

function makeFixture(config = {}) {
  const state = {
    messages: seedMessages(),
    tasks: {},
    postCount: 0,
    cancelCalls: [],
    eventRequests: [],
    taskStateChecks: 0,
    persisted: false,
    allowOldAlpha: gate(),
    allowReconnect: gate(),
    allowImageCompletion: gate(),
    releaseAll() {
      state.allowOldAlpha.release();
      state.allowReconnect.release();
      state.allowImageCompletion.release();
      state.createConversationGate?.release();
      state.uploadGate?.release();
    },
    ...config,
  };

  const defaultTask = (id, conversationId, status = 'running') => ({ id, conversation_id: conversationId, status, error_message: null });

  const reply = (route, payload, status = 200) => route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  });

  const eventReply = (route, body) => route.fulfill({
    status: 200,
    headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
    body,
  });

  const handler = async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const endpoint = url.pathname.replace(/^\/bot\/api/, '');
    const method = request.method();
    let body = {};
    try { body = request.postDataJSON() || {}; } catch { body = {}; }

    if (endpoint === '/files/asset-image/download' && method === 'GET') {
      return route.fulfill({ status: 200, contentType: 'image/png', body: png1x1() });
    }
    if (endpoint === '/auth/me' && method === 'GET') return reply(route, { authenticated: true, user: { id: 'fixture-user', name: 'Lifecycle Tester' } });
    if (endpoint === '/agents' && method === 'GET') return reply(route, { agents });
    if (endpoint === '/conversations' && method === 'GET') return reply(route, { conversations });
    if (endpoint === '/conversations' && method === 'POST') {
      state.createConversationCalls = (state.createConversationCalls || 0) + 1;
      if (state.createConversationGate) await state.createConversationGate.wait();
      const conversation = typeof state.newConversation === 'function'
        ? state.newConversation({ state, body, index: state.createConversationCalls })
        : state.newConversation || { id: `conversation-created-${state.createConversationCalls}`, agent_id: 'agent-alpha', title: 'New work', updated_at: '2026-09-16T09:30:00Z', message_count: 0 };
      state.createdConversations = [...(state.createdConversations || []), conversation];
      return reply(route, { conversation });
    }
    if (endpoint === '/memory' && method === 'GET') return reply(route, { memory: [] });
    if (endpoint === '/files' && method === 'GET') return reply(route, { files: [] });
    if (endpoint === '/files' && method === 'POST') {
      state.uploadCalls = (state.uploadCalls || 0) + 1;
      if (state.uploadGate) await state.uploadGate.wait();
      state.uploadDone = true;
      return reply(route, { file: { id: state.uploadId || 'file-stale', name: state.uploadName || 'stale.txt', content_type: 'text/plain', size: 5, status: 'ready' } });
    }
    if (endpoint === '/activity' && method === 'GET') return reply(route, { events: [] });
    if (endpoint === '/runtime/status' && method === 'GET') return reply(route, { runtime: { available: true, provider: 'fixture', model: 'gpt-5.6-luna' } });
    if (endpoint === '/runtime/account' && method === 'GET') return reply(route, { account: { connected: true, type: 'fixture', plan: 'test', models: [{ id: 'gpt-5.6-luna', name: 'GPT 5.6 Luna' }] } });
    if (endpoint === '/runtime/usage' && method === 'GET') return reply(route, { usage: { used: 12, limit: 100, remaining: 88 } });
    if (endpoint === '/onboarding' && method === 'GET') return reply(route, { complete: true, steps: [] });
    if (/^\/agents\/[^/]+\/skills$/.test(endpoint) && method === 'GET') return reply(route, { skills: [] });
    if (/^\/agents\/[^/]+\/desktop$/.test(endpoint) && method === 'GET') return reply(route, { desktop: { available: false, created: false, running: false } });

    const conversationMatch = endpoint.match(/^\/conversations\/([^/]+)\/messages$/);
    if (conversationMatch && method === 'GET') {
      const conversationId = decodeURIComponent(conversationMatch[1]);
      if (state.persisted && conversationId === 'conversation-alpha' && state.persistedMessages) {
        state.messages[conversationId] = state.persistedMessages;
      }
      return reply(route, { messages: state.messages[conversationId] || [] });
    }
    if (conversationMatch && method === 'POST') {
      const conversationId = decodeURIComponent(conversationMatch[1]);
      if (state.rejectMessage) {
        state.rejectedMessageCalls = (state.rejectedMessageCalls || 0) + 1;
        return reply(route, { detail: state.rejectMessageDetail || 'Fixture rejected the task.' }, 422);
      }
      state.postCount += 1;
      const task = state.postTask
        ? state.postTask({ state, conversationId, body, index: state.postCount })
        : defaultTask(`task-${state.postCount}`, conversationId);
      state.tasks[task.id] = task;
      return reply(route, { task });
    }

    const conversationTasksMatch = endpoint.match(/^\/conversations\/([^/]+)\/tasks$/);
    if (conversationTasksMatch && method === 'GET') {
      const conversationId = decodeURIComponent(conversationTasksMatch[1]);
      const tasks = typeof state.conversationTasks === 'function'
        ? state.conversationTasks({ state, conversationId })
        : Object.values(state.tasks).filter((task) => task.conversation_id === conversationId);
      return reply(route, { tasks });
    }

    const eventsMatch = endpoint.match(/^\/tasks\/([^/]+)\/events$/);
    if (eventsMatch && method === 'GET') {
      const taskId = decodeURIComponent(eventsMatch[1]);
      const afterId = Number(url.searchParams.get('after_id') || 0);
      state.eventRequests.push({ taskId, afterId, url: request.url() });
      if (typeof state.events === 'function') {
        const result = await state.events({ state, taskId, afterId, requestNumber: state.eventRequests.filter((item) => item.taskId === taskId).length });
        if (result && result.wait) await result.wait();
        return eventReply(route, result?.body ?? '');
      }
      return eventReply(route, sse({ id: 1, type: 'task.started', data: { task_id: taskId } }));
    }

    const taskMatch = endpoint.match(/^\/tasks\/([^/]+)$/);
    if (taskMatch && method === 'GET') {
      const taskId = decodeURIComponent(taskMatch[1]);
      state.taskStateChecks += 1;
      const task = state.tasks[taskId] || defaultTask(taskId, 'conversation-alpha', 'completed');
      if (typeof state.taskStatus === 'function') task.status = state.taskStatus({ state, taskId, task });
      return reply(route, { task });
    }
    const cancelMatch = endpoint.match(/^\/tasks\/([^/]+)\/cancel$/);
    if (cancelMatch && method === 'POST') {
      const taskId = decodeURIComponent(cancelMatch[1]);
      state.cancelCalls.push(taskId);
      const task = state.tasks[taskId] || defaultTask(taskId, 'conversation-alpha');
      task.status = 'cancelled';
      state.tasks[taskId] = task;
      return reply(route, { task });
    }

    return reply(route, {});
  };

  return { state, handler };
}

async function waitFor(predicate, label, timeout = 7000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`Timed out waiting for ${label}`);
}

async function waitForCount(locator, count, label, timeout = 7000) {
  await waitFor(async () => (await locator.count()) >= count, label, timeout);
}

async function openAlpha(page) {
  await page.goto(baseURL);
  await page.locator('.sidebar').waitFor();
  await page.getByRole('button', { name: 'Open Alpha', exact: true }).click();
  await page.getByRole('textbox', { name: 'Message Alpha', exact: true }).waitFor();
}

async function expectNoStop(page) {
  if (await page.getByRole('button', { name: 'Stop run', exact: true }).count()) throw new Error('Stop remained visible after the task ended.');
}

async function runScenario(browser, name, test, scenarios) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light', reducedMotion: 'reduce' });
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  const errors = [];
  const fixture = makeFixture();
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    await page.route('**/bot/api/**', fixture.handler);
    await test(page, fixture.state);
    if (errors.length) throw new Error(`page errors: ${errors.join(' | ')}`);
    scenarios.push({ name, status: 'passed' });
  } catch (error) {
    scenarios.push({ name, status: 'failed', error: error.message, eventRequests: fixture.state.eventRequests, taskStateChecks: fixture.state.taskStateChecks, cancelCalls: fixture.state.cancelCalls });
  } finally {
    fixture.state.releaseAll();
    await context.close();
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  fs.mkdirSync(auditDir, { recursive: true });
  const scenarios = [];

  await runScenario(browser, 'active task recovers after reload', async (page, state) => {
    state.tasks['task-reload'] = { id: 'task-reload', conversation_id: 'conversation-alpha', status: 'running', error_message: null };
    state.conversationTasks = ({ conversationId }) => conversationId === 'conversation-alpha' ? [state.tasks['task-reload']] : [];
    state.events = ({ taskId }) => ({ body: sse({ id: 1, type: 'task.started', data: { task_id: taskId } }) });
    await openAlpha(page);
    await page.getByRole('button', { name: 'Stop run', exact: true }).waitFor();
    await page.reload();
    await page.getByRole('button', { name: 'Stop run', exact: true }).waitFor();
  }, scenarios);

  await runScenario(browser, 'switching conversations isolates streams and returning recovers Alpha', async (page, state) => {
    state.conversationTasks = ({ conversationId }) => conversationId === 'conversation-alpha' && state.postCount > 0
      ? [{ id: 'task-alpha', conversation_id: conversationId, status: state.persisted ? 'completed' : 'running', error_message: null }]
      : [];
    state.postTask = ({ conversationId }) => ({ id: 'task-alpha', conversation_id: conversationId, status: 'running', error_message: null });
    state.events = async ({ taskId, afterId, requestNumber }) => {
      if (taskId !== 'task-alpha') return { body: sse({ id: 1, type: 'task.completed', data: {} }) };
      if (requestNumber === 1 && afterId === 0) {
        return { wait: state.allowOldAlpha.wait, body: sse({ id: 1, type: 'text', data: { text: 'A leaked data' } }) };
      }
      state.persisted = true;
      return { body: sse(
        { id: 2, type: 'text', data: { text: 'A recovered' } },
        { id: 3, type: 'task.completed', data: {} },
      ) };
    };
    state.persistedMessages = [
      ...state.messages['conversation-alpha'],
      { id: 'alpha-recovered', conversation_id: 'conversation-alpha', role: 'assistant', content: 'A recovered', created_at: '2026-09-16T09:04:00Z', status: 'complete' },
    ];
    await openAlpha(page);
    await page.getByRole('textbox', { name: 'Message Alpha', exact: true }).fill('Run Alpha now');
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await waitFor(() => state.eventRequests.some((item) => item.taskId === 'task-alpha'), 'Alpha event stream');
    await page.getByRole('button', { name: 'Open Beta', exact: true }).click();
    await page.locator('h1').filter({ hasText: 'Beta' }).waitFor();
    state.allowOldAlpha.release();
    await page.getByText('Keep the beta workstream separate.', { exact: true }).waitFor();
    if (await page.getByText('A leaked data', { exact: true }).count()) throw new Error('Alpha stream text contaminated Beta.');
    await page.getByRole('button', { name: 'Open Alpha', exact: true }).click();
    await page.locator('h1').filter({ hasText: 'Alpha' }).waitFor();
    await page.getByText('A recovered', { exact: true }).waitFor();
  }, scenarios);

  await runScenario(browser, 'Stop cancels the task and cancelled status persists', async (page, state) => {
    state.tasks['task-cancel'] = { id: 'task-cancel', conversation_id: 'conversation-alpha', status: 'running', error_message: null };
    state.conversationTasks = ({ conversationId }) => conversationId === 'conversation-alpha' ? [state.tasks['task-cancel']] : [];
    state.events = ({ taskId }) => ({ body: sse({ id: 1, type: 'task.started', data: { task_id: taskId } }) });
    await openAlpha(page);
    await page.getByRole('button', { name: 'Stop run', exact: true }).click();
    await waitFor(() => state.cancelCalls.includes('task-cancel'), 'cancel endpoint');
    if (state.tasks['task-cancel'].status !== 'cancelled') throw new Error('Fixture task did not persist cancelled status.');
    await page.reload();
    await page.getByRole('textbox', { name: 'Message Alpha', exact: true }).waitFor();
    await new Promise((resolve) => setTimeout(resolve, 300));
    await expectNoStop(page);
    const persisted = await page.evaluate(async () => (await fetch('/bot/api/tasks/task-cancel')).json());
    if (persisted.task?.status !== 'cancelled') throw new Error(`Cancelled status was not durable: ${JSON.stringify(persisted)}`);
  }, scenarios);

  await runScenario(browser, 'EOF without terminal reconnects and checks durable status', async (page, state) => {
    state.postTask = ({ conversationId }) => ({ id: 'task-eof', conversation_id: conversationId, status: 'running', error_message: null });
    state.events = async ({ taskId, afterId }) => {
      if (afterId === 0) return { body: sse({ id: 1, type: 'text', data: { text: 'Partial before EOF' } }) };
      state.persisted = true;
      return { wait: state.allowReconnect.wait, body: sse(
        { id: 2, type: 'text', data: { text: 'Recovered after EOF' } },
        { id: 3, type: 'task.completed', data: {} },
      ) };
    };
    state.taskStatus = ({ state: fixtureState }) => fixtureState.persisted ? 'completed' : 'running';
    state.persistedMessages = [
      ...state.messages['conversation-alpha'],
      { id: 'eof-recovered', conversation_id: 'conversation-alpha', role: 'assistant', content: 'Recovered after EOF', created_at: '2026-09-16T09:05:00Z', status: 'complete' },
    ];
    await openAlpha(page);
    await page.getByRole('textbox', { name: 'Message Alpha', exact: true }).fill('Recover after a dropped stream');
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await page.getByText('Partial before EOF', { exact: true }).waitFor();
    await waitFor(() => state.taskStateChecks > 0, 'durable task status check');
    await page.getByText('Reconnecting to your run…', { exact: true }).waitFor();
    state.allowReconnect.release();
    await waitFor(() => state.eventRequests.filter((item) => item.taskId === 'task-eof').length >= 2, 'reconnected SSE request');
    state.persisted = true;
    await page.locator('.message-content').filter({ hasText: 'Recovered after EOF' }).waitFor();
  }, scenarios);

  await runScenario(browser, 'image_generate shows real progress, local preview, and persisted markdown', async (page, state) => {
    state.postTask = ({ conversationId }) => ({ id: 'task-image', conversation_id: conversationId, status: 'running', error_message: null });
    state.events = async ({ taskId, afterId }) => {
      if (afterId === 0) return { body: sse({ id: 1, type: 'tool.started', data: { tool: 'image_generate', prompt: 'A calm studio still life', aspect_ratio: '1:1' } }) };
      return { wait: state.allowImageCompletion.wait, body: sse({ id: 2, type: 'tool.completed', data: { tool: 'image_generate', success: true, result: { file_id: 'asset-image', download_url: '/bot/api/files/asset-image/download', markdown: '![Generated image](/bot/api/files/asset-image/download)' } } }) };
    };
    state.taskStatus = ({ state: fixtureState }) => fixtureState.persisted ? 'completed' : 'running';
    state.persistedMessages = [
      ...state.messages['conversation-alpha'],
      { id: 'image-message', conversation_id: 'conversation-alpha', role: 'assistant', content: '![Generated image](/bot/api/files/asset-image/download)', created_at: '2026-09-16T09:06:00Z', status: 'complete' },
    ];
    await openAlpha(page);
    await page.getByRole('textbox', { name: 'Message Alpha', exact: true }).fill('Generate a visual');
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await page.locator('.image-generation-pending').waitFor();
    await page.getByText('Square', { exact: true }).waitFor();
    await page.getByText('A calm studio still life', { exact: false }).waitFor();
    state.allowImageCompletion.release();
    await waitFor(() => state.eventRequests.filter((item) => item.taskId === 'task-image').length >= 2, 'image completion event');
    await page.locator('.image-generation-result img').waitFor();
    state.persisted = true;
    await page.getByRole('button', { name: 'Open Beta', exact: true }).click();
    await page.getByRole('button', { name: 'Open Alpha', exact: true }).click();
    await page.locator('.message-markdown img[src="/bot/api/files/asset-image/download"]').waitFor();
  }, scenarios);

  await runScenario(browser, 'image aspect variants render real square portrait and landscape states', async (page, state) => {
    const variants = [
      { id: 'square', label: 'Square', ratio: '1:1', orientation: 'square', prompt: 'Square editorial still life' },
      { id: 'portrait', label: 'Portrait', ratio: '2:3', orientation: 'portrait', prompt: 'Portrait editorial still life' },
      { id: 'landscape', label: 'Landscape', ratio: '3:2', orientation: 'landscape', prompt: 'Landscape editorial still life' },
    ];
    state.aspectByTask = {};
    state.finishedTasks = new Set();
    state.postTask = ({ conversationId }) => {
      const variant = state.currentVariant;
      const task = { id: `task-aspect-${variant.id}`, conversation_id: conversationId, status: 'running', error_message: null };
      state.aspectByTask[task.id] = variant;
      return task;
    };
    state.taskStatus = ({ state: fixtureState, taskId }) => fixtureState.finishedTasks.has(taskId) ? 'completed' : 'running';
    state.events = async ({ taskId, afterId }) => {
      const variant = state.aspectByTask[taskId] || state.currentVariant;
      if (afterId === 0) return { body: sse({ id: 1, type: 'tool.started', data: { tool: 'image_generate', prompt: variant.prompt, aspect_ratio: variant.ratio } }) };
      return { wait: state.currentGate.wait, body: sse(
        { id: 2, type: 'tool.completed', data: { tool: 'image_generate', success: true, result: { file_id: 'asset-image', download_url: '/bot/api/files/asset-image/download' } } },
        { id: 3, type: 'task.completed', data: {} },
      ) };
    };
    await openAlpha(page);
    for (const [index, variant] of variants.entries()) {
      state.currentVariant = variant;
      state.currentGate = gate();
      if (index > 0) {
        await waitFor(async () => !(await page.getByRole('button', { name: 'Stop run', exact: true }).count()), 'previous image run cleanup');
      }
      const input = page.getByRole('textbox', { name: 'Message Alpha', exact: true });
      await input.fill(`Generate ${variant.label.toLowerCase()} art`);
      await page.getByRole('button', { name: 'Send message', exact: true }).click();
      const pending = page.locator('.image-generation-pending');
      await pending.waitFor();
      await pending.locator(`.image-generation-surface[data-orientation="${variant.orientation}"]`).waitFor();
      await page.getByText(variant.label, { exact: true }).waitFor();
      await page.getByText(variant.prompt, { exact: false }).waitFor();
      if (index === 0) {
        await page.emulateMedia({ reducedMotion: 'no-preference' });
        const surface = pending.locator('.image-generation-surface');
        await surface.locator('xpath=self::*[@data-motion="dynamic"]').waitFor();
        const before = await surface.evaluate(el => el.style.getPropertyValue('--spot-x'));
        await page.waitForTimeout(180);
        const after = await surface.evaluate(el => el.style.getPropertyValue('--spot-x'));
        if (before === after) throw new Error('Spotlight did not move with motion enabled.');
        await page.emulateMedia({ reducedMotion: 'reduce' });
        await surface.locator('xpath=self::*[@data-motion="static"]').waitFor();
        const still = await surface.evaluate(el => el.style.getPropertyValue('--spot-x'));
        await page.waitForTimeout(180);
        if (still !== await surface.evaluate(el => el.style.getPropertyValue('--spot-x'))) throw new Error('Reduced motion did not stop spotlight movement.');
      }
      await pending.screenshot({ path: path.join(auditDir, `image-generation-${variant.id}.png`) });
      if (index === 0) await pending.screenshot({ path: path.join(auditDir, 'image-generation-reduced-motion.png') });
      state.currentGate.release();
      await waitFor(() => state.eventRequests.filter((item) => item.taskId === `task-aspect-${variant.id}`).length >= 2, `${variant.label} completion event`);
      await page.locator('.image-generation-result').waitFor();
      state.finishedTasks.add(`task-aspect-${variant.id}`);
    }
  }, scenarios);

  await runScenario(browser, 'exhausted reconnect reports an image request failure', async (page, state) => {
    state.postTask = ({ conversationId }) => ({ id: 'task-image-exhausted', conversation_id: conversationId, status: 'running', error_message: null });
    state.events = ({ afterId }) => afterId === 0
      ? { body: sse({ id: 1, type: 'tool.started', data: { tool: 'image_generate', prompt: 'A request that loses its connection', aspect_ratio: '1:1' } }) }
      : { body: '' };
    await openAlpha(page);
    await page.getByRole('textbox', { name: 'Message Alpha', exact: true }).fill('Generate an image while the connection fails');
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await page.locator('.image-generation-pending').waitFor();
    await page.locator('.image-generation-error').waitFor({ timeout: 12000 });
    await page.getByText('Connection lost. Reopen this chat to check the image request.', { exact: true }).waitFor();
    if (state.eventRequests.filter((item) => item.taskId === 'task-image-exhausted').length < 4) throw new Error('Reconnect exhaustion stopped before three retries.');
    if (state.taskStateChecks < 4) throw new Error('Reconnect exhaustion did not verify durable task status on every dropped stream.');
  }, scenarios);

  await runScenario(browser, 'Stop during delayed conversation creation prevents task submission', async (page, state) => {
    state.createConversationGate = gate();
    await openAlpha(page);
    await page.getByRole('button', { name: 'New chat', exact: true }).click();
    const input = page.getByRole('textbox', { name: 'Message Alpha', exact: true });
    const draft = 'Cancel before the conversation is created';
    await input.fill(draft);
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await waitFor(() => state.createConversationCalls > 0, 'conversation creation request');
    await page.getByRole('button', { name: 'Stop run', exact: true }).click();
    state.createConversationGate.release();
    await waitFor(() => (state.createdConversations || []).length === 1, 'delayed conversation response');
    await waitFor(async () => !(await page.getByRole('button', { name: 'Stop run', exact: true }).count()), 'pending run cleanup');
    if (state.postCount !== 0) throw new Error(`Stop submitted ${state.postCount} task message(s) after delayed creation.`);
    if ((await input.inputValue()) !== draft) throw new Error('Draft was lost when stopping before task submission.');
  }, scenarios);

  await runScenario(browser, 'upload response from Alpha cannot attach to Beta after switching', async (page, state) => {
    state.uploadGate = gate();
    state.uploadId = 'file-stale';
    state.uploadName = 'stale.txt';
    await openAlpha(page);
    const input = page.locator('input[type="file"].visually-hidden').first();
    await input.setInputFiles({ name: 'stale.txt', mimeType: 'text/plain', buffer: Buffer.from('stale') });
    await waitFor(() => state.uploadCalls > 0, 'Alpha upload request');
    await page.getByRole('button', { name: 'Open Beta', exact: true }).click();
    await page.locator('h1').filter({ hasText: 'Beta' }).waitFor();
    state.uploadGate.release();
    await waitFor(() => state.uploadDone === true, 'stale upload response');
    await new Promise((resolve) => setTimeout(resolve, 300));
    if (await page.locator('.attachment-chip').count()) throw new Error('Alpha upload appeared in Beta attachment tray.');
    if (await page.getByText('stale.txt', { exact: true }).count()) throw new Error('Alpha upload filename appeared in Beta view.');
  }, scenarios);

  await runScenario(browser, 'cancelling image generation leaves an honest stopped state', async (page, state) => {
    state.postTask = ({ conversationId }) => ({ id: 'task-image-cancel', conversation_id: conversationId, status: 'running', error_message: null });
    state.events = ({ taskId, afterId }) => afterId === 0
      ? { body: sse({ id: 1, type: 'tool.started', data: { tool: 'image_generate' } }) }
      : { body: '' };
    await openAlpha(page);
    await page.getByRole('textbox', { name: 'Message Alpha', exact: true }).fill('Generate and then stop this image');
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await page.locator('.image-generation-pending').waitFor();
    await page.getByRole('button', { name: 'Stop run', exact: true }).click();
    await waitFor(() => state.cancelCalls.includes('task-image-cancel'), 'image cancellation request');
    await page.locator('.image-generation-cancelled').waitFor();
    await page.getByText('Stopped waiting for the image. The provider may still finish this request.', { exact: true }).waitFor();
    if (await page.getByText('Generating image', { exact: true }).count()) throw new Error('Cancelled image still reports that it is generating.');
    const persisted = await page.evaluate(async () => (await fetch('/bot/api/tasks/task-image-cancel')).json());
    if (persisted.task?.status !== 'cancelled') throw new Error(`Cancelled image status was not durable: ${JSON.stringify(persisted)}`);
  }, scenarios);

  await runScenario(browser, 'rejected task submission preserves the composer draft and error', async (page, state) => {
    state.rejectMessage = true;
    state.rejectMessageDetail = 'Fixture rejected the task.';
    await openAlpha(page);
    const draft = 'Keep this draft when the runtime rejects it';
    const input = page.getByRole('textbox', { name: 'Message Alpha', exact: true });
    await input.fill(draft);
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await page.getByText('Fixture rejected the task.', { exact: true }).waitFor();
    if ((await input.inputValue()) !== draft) throw new Error('Rejected task cleared the composer draft.');
    if (state.eventRequests.length) throw new Error('Rejected task opened an event stream.');
    if (!(await page.getByRole('button', { name: 'Send message', exact: true }).isEnabled())) throw new Error('Send stayed disabled after task rejection.');
  }, scenarios);

  await runScenario(browser, 'first send with an attachment restores the tray after rejection', async (page, state) => {
    state.rejectMessage = true;
    state.rejectMessageDetail = 'Fixture rejected the attached task.';
    state.newConversation = ({ index }) => ({ id: `conversation-first-rejected-${index}`, agent_id: 'agent-alpha', title: 'Attached review', updated_at: '2026-09-16T09:50:00Z', message_count: 0 });
    state.uploadId = 'file-first-rejected';
    state.uploadName = 'brief.txt';
    await openAlpha(page);
    await page.getByRole('button', { name: 'New chat', exact: true }).click();
    const fileInput = page.locator('input[type="file"].visually-hidden').first();
    await fileInput.setInputFiles({ name: 'brief.txt', mimeType: 'text/plain', buffer: Buffer.from('brief') });
    await page.getByText('brief.txt', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Send attached files for review', exact: true }).click();
    await page.getByText('Fixture rejected the attached task.', { exact: true }).waitFor();
    await page.locator('.attachment-chip').getByText('brief.txt', { exact: true }).waitFor();
    const input = page.getByRole('textbox', { name: 'Message Alpha', exact: true });
    if (!(await input.inputValue()).includes('Please review these uploaded files')) throw new Error('Rejected first attachment send did not preserve its review prompt.');
    if (state.eventRequests.length) throw new Error('Rejected first attachment send opened an event stream.');
  }, scenarios);

  const failed = scenarios.filter((scenario) => scenario.status === 'failed');
  const report = { baseURL, generatedAt: new Date().toISOString(), passed: failed.length === 0, scenarios };
  fs.writeFileSync(path.join(auditDir, 'task-lifecycle-report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
  if (failed.length) process.exitCode = 1;
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
