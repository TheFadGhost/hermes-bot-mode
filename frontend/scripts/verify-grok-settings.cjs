/* Fixture verification for the Grok workspace settings and responsive shell. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('C:/Users/Work/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

const baseURL = process.env.BOT_MODE_URL || 'http://127.0.0.1:5173/bot/';
const outputDir = path.resolve(__dirname, '../../design-research/verification/grok-settings');
fs.mkdirSync(outputDir, { recursive: true });

const initialAgents = [
  { id: 'agent-alpha', name: 'Alpha', description: 'Coordinates the family plan.', instructions: 'Coordinates the family plan.', model: 'gpt-5.6-luna', status: 'active', is_active: true, avatar: 'blob', color: '#8754f5' },
  { id: 'agent-beta', name: 'Beta', description: 'Keeps the details moving.', instructions: 'Keeps the details moving.', model: 'gpt-5.6-luna', status: 'active', is_active: true, avatar: 'drop', color: '#2d93fa' },
  { id: 'agent-scout', name: 'Scout', description: 'Finds useful context.', instructions: 'Finds useful context.', model: 'gpt-5.6-luna', status: 'active', is_active: true, avatar: 'orb', color: '#17c765' },
];

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function gate() {
  let released = false;
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { wait: () => released ? Promise.resolve() : promise, release: () => { if (!released) { released = true; resolve(); } } };
}

function makeEntries(agents) {
  const byId = new Map(agents.map((agent) => [agent.id, agent]));
  const direct = (agentId, conversationId, pinned = false) => {
    const agent = byId.get(agentId);
    return {
      conversation_id: conversationId,
      kind: 'direct',
      agent_id: agentId,
      coordinator_id: agentId,
      name: agent.name,
      members: [{ agent_id: agentId, name: agent.name, role: 'coordinator', avatar: agent.avatar, color: agent.color }],
      preview: agent.description,
      updated_at: '2026-09-17T08:30:00Z',
      unread_count: 0,
      pinned,
      archived: false,
      active_tasks: [],
    };
  };
  return [
    direct('agent-alpha', 'conversation-alpha'),
    direct('agent-beta', 'conversation-beta', true),
    {
      conversation_id: 'conversation-weekend',
      kind: 'group',
      agent_id: 'agent-alpha',
      coordinator_id: 'agent-alpha',
      name: 'Weekend Crew',
      members: [
        { agent_id: 'agent-alpha', name: 'Alpha', role: 'coordinator', avatar: 'blob', color: '#8754f5' },
        { agent_id: 'agent-beta', name: 'Beta', role: 'member', avatar: 'drop', color: '#2d93fa' },
        { agent_id: 'agent-scout', name: 'Scout', role: 'member', avatar: 'orb', color: '#17c765' },
      ],
      preview: 'Planning together',
      updated_at: '2026-09-17T08:10:00Z',
      unread_count: 0,
      pinned: false,
      archived: false,
      active_tasks: [],
    },
  ];
}

function makeFixture() {
  const state = {
    agents: clone(initialAgents),
    entries: makeEntries(initialAgents),
    messages: {
      'conversation-alpha': [{ id: 'alpha-ready', conversation_id: 'conversation-alpha', role: 'assistant', author_agent_id: 'agent-alpha', content: 'Alpha is ready.', created_at: '2026-09-17T08:01:00Z' }],
      'conversation-beta': [{ id: 'beta-ready', conversation_id: 'conversation-beta', role: 'assistant', author_agent_id: 'agent-beta', content: 'Beta is ready.', created_at: '2026-09-17T08:02:00Z' }],
      'conversation-weekend': [{ id: 'weekend-ready', conversation_id: 'conversation-weekend', role: 'assistant', author_agent_id: 'agent-alpha', content: 'The group is ready.', created_at: '2026-09-17T08:03:00Z' }],
    },
    account: { connected: true, type: 'fixture', plan: 'test', models: [{ id: 'gpt-5.6-luna', name: 'GPT 5.6 Luna' }, { id: 'gpt-5.6-sol', name: 'GPT 5.6 Sol' }] },
    runtime: { available: true, provider: 'fixture', model: 'gpt-5.6-luna' },
    agentPatches: [],
    groupPatches: [],
    agentCreates: [],
    groupCreates: [],
    accountChecks: 0,
    routines: [
      { id: 'routine-morning', agent_id: 'agent-alpha', name: 'Morning briefing', instruction: 'Review the family plan.', time: '09:00', timezone: 'Europe/London', weekdays: [0, 1, 2, 3, 4], enabled: true },
      { id: 'routine-evening', agent_id: 'agent-alpha', name: 'Evening recap', instruction: 'Summarize anything still open.', time: '18:00', timezone: 'Europe/London', weekdays: [0, 1, 2, 3, 4], enabled: true },
    ],
    routineRuns: [],
    routineDeletes: [],
    heldRoutineGate: gate(),
    requests: [],
    requestCards: {},
    connections: {
      configured: true,
      catalog: [
        { slug: 'google-drive', name: 'Google Drive', description: 'Find and organize shared files.', connected: false },
        { slug: 'github', name: 'GitHub', description: 'Review issues and pull requests.', connected: true },
      ],
      accounts: [{ id: 'account-github', toolkit: 'github', name: 'Dad’s GitHub', status: 'connected' }],
      next_cursor: null,
    },
    connectionLinks: [],
    continuedRequests: [],
    privateSubmissions: [],
    privateFields: {},
    teachings: {},
    teachingPatches: [],
    teachingRuns: [],
    unexpected: [],
  };

  const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  const bodyOf = (request) => {
    try { return request.postDataJSON() || {}; } catch { return {}; }
  };
  const entriesForResponse = () => {
    const byId = new Map(state.agents.map((agent) => [agent.id, agent]));
    return state.entries.map((entry) => {
      if (entry.kind !== 'direct' || !entry.agent_id) return clone(entry);
      const agent = byId.get(entry.agent_id);
      return agent ? { ...clone(entry), name: agent.name, preview: agent.description, members: [{ agent_id: agent.id, name: agent.name, role: 'coordinator', avatar: agent.avatar, color: agent.color }] } : clone(entry);
    });
  };
  const conversationFor = (id) => ({ id, agent_id: state.entries.find((entry) => entry.conversation_id === id)?.agent_id ?? 'agent-alpha', kind: state.entries.find((entry) => entry.conversation_id === id)?.kind ?? 'direct' });

  const handler = async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const endpoint = url.pathname.replace(/^\/bot\/api/, '');
    const method = request.method();
    const body = bodyOf(request);
    state.requests.push({ method, endpoint, body });

    if (endpoint === '/auth/me' && method === 'GET') return json(route, { authenticated: true, user: { id: 'fixture-dad', name: 'Fixture Dad' } });
    if (endpoint === '/bootstrap' && method === 'POST') return json(route, { chief: clone(state.agents[0]), conversation: conversationFor('conversation-alpha') });
    if (endpoint === '/agents' && method === 'GET') return json(route, { agents: clone(state.agents) });
    if (endpoint === '/agents' && method === 'POST') {
      const id = `agent-${String(body.name || 'new-bot').toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
      const created = { id, name: body.name, description: body.instructions || '', instructions: body.instructions || '', model: body.model || 'gpt-5.6-luna', status: 'active', is_active: true, avatar: body.avatar || 'blob', color: body.color || '#2d93fa' };
      state.agents.unshift(created);
      state.agentCreates.push({ ...body, id });
      return json(route, { agent: clone(created) });
    }
    const agentMatch = endpoint.match(/^\/agents\/([^/]+)$/);
    if (agentMatch && method === 'PATCH') {
      const id = decodeURIComponent(agentMatch[1]);
      const current = state.agents.find((agent) => agent.id === id);
      if (!current) return json(route, { detail: 'Agent not found' }, 404);
      Object.assign(current, body);
      if (body.instructions !== undefined) current.description = body.instructions;
      current.instructions = current.description;
      state.agentPatches.push({ id, body: clone(body) });
      return json(route, { agent: clone(current) });
    }
    if (endpoint === '/inbox' && method === 'GET') return json(route, { items: entriesForResponse() });
    if (endpoint === '/conversations' && method === 'GET') return json(route, { conversations: entriesForResponse().map((entry) => ({ id: entry.conversation_id, agent_id: entry.agent_id, title: entry.name, updated_at: entry.updated_at })) });
    const homeMatch = endpoint.match(/^\/agents\/([^/]+)\/home$/);
    if (homeMatch && method === 'GET') return json(route, { conversation: conversationFor(`conversation-${decodeURIComponent(homeMatch[1])}`) });
    if (endpoint === '/runtime/status' && method === 'GET') return json(route, { runtime: clone(state.runtime) });
    if (endpoint === '/runtime/account' && method === 'GET') { state.accountChecks += 1; return json(route, { account: clone(state.account) }); }
    if (endpoint === '/runtime/usage' && method === 'GET') return json(route, { usage: { planType: 'plus', rateLimitsByLimitId: { codex: { primary: { usedPercent: 0, windowDurationMins: 300, resetsAt: '2026-09-17T12:00:00Z' }, secondary: { usedPercent: 3, windowDurationMins: 10080, resetsAt: '2026-09-23T12:00:00Z' } } }, rateLimits: { codex: { primary: { usedPercent: 42, windowDurationMins: 300, resetsAt: '2026-09-17T12:00:00Z' }, secondary: { usedPercent: 62, windowDurationMins: 10080, resetsAt: '2026-09-23T12:00:00Z' } } } } });
    if (endpoint === '/extensions/status' && method === 'GET') return json(route, { connections: { configured: state.connections.configured }, voice: { configured: true, model: 'microsoft/mai-transcribe-2', max_bytes: 10485760, max_seconds: 120 }, private_input: { available: true }, telegram: { configured: false } });
    if (endpoint === '/runtime/login' && method === 'POST') return json(route, { login: { userCode: 'FIXTURE-1234', verificationUrl: 'https://example.com/sign-in' } });

    if (endpoint === '/connections' && method === 'GET') {
      const needle = (url.searchParams.get('q') || '').trim().toLowerCase();
      const catalog = state.connections.catalog.filter((item) => !needle || `${item.name} ${item.description} ${item.slug}`.toLowerCase().includes(needle));
      return json(route, { configured: state.connections.configured, catalog: clone(catalog), accounts: clone(state.connections.accounts), next_cursor: null });
    }
    if (endpoint === '/connections/link' && method === 'POST') {
      state.connectionLinks.push(clone(body));
      return json(route, { url: `https://example.com/connect/${encodeURIComponent(body.toolkit || 'service')}?state=fixture`, expires_at: '2026-09-17T13:00:00Z' });
    }
    const connectionAccountMatch = endpoint.match(/^\/connections\/([^/]+)$/);
    if (connectionAccountMatch && method === 'DELETE') {
      const id = decodeURIComponent(connectionAccountMatch[1]);
      state.connections.accounts = state.connections.accounts.filter((account) => account.id !== id);
      return json(route, { ok: true });
    }

    const desktopMatch = endpoint.match(/^\/agents\/([^/]+)\/desktop$/);
    if (desktopMatch && method === 'GET') return json(route, { desktop: { available: false, created: false, running: false, phase: 'unavailable', control_mode: 'bot', generation: 1 } });
    const routinesMatch = endpoint.match(/^\/agents\/([^/]+)\/routines$/);
    if (routinesMatch && method === 'GET') return json(route, { routines: clone(state.routines.filter((routine) => routine.agent_id === decodeURIComponent(routinesMatch[1]))) });
    const skillsMatch = endpoint.match(/^\/agents\/([^/]+)\/skills$/);
    if (skillsMatch && method === 'GET') return json(route, { skills: [] });
    const privateFieldsMatch = endpoint.match(/^\/agents\/([^/]+)\/private-fields$/);
    if (privateFieldsMatch && method === 'GET') return json(route, { fields: clone(state.privateFields[decodeURIComponent(privateFieldsMatch[1])] || []) });
    if (privateFieldsMatch && method === 'POST') {
      const agentId = decodeURIComponent(privateFieldsMatch[1]);
      const field = { id: `field-${Date.now()}`, label: body.label, purpose: body.purpose, expires_at: null, one_time: !body.remember };
      state.privateFields[agentId] = [field, ...(state.privateFields[agentId] || [])];
      return json(route, { field: clone(field) });
    }
    const privateFieldMatch = endpoint.match(/^\/agents\/([^/]+)\/private-fields\/([^/]+)$/);
    if (privateFieldMatch && method === 'DELETE') {
      const agentId = decodeURIComponent(privateFieldMatch[1]);
      const fieldId = decodeURIComponent(privateFieldMatch[2]);
      state.privateFields[agentId] = (state.privateFields[agentId] || []).filter((field) => field.id !== fieldId);
      return json(route, { ok: true });
    }
    const teachingsMatch = endpoint.match(/^\/agents\/([^/]+)\/teachings$/);
    if (teachingsMatch && method === 'GET') return json(route, { teachings: clone(state.teachings[decodeURIComponent(teachingsMatch[1])] || []) });
    if (teachingsMatch && method === 'POST') {
      const agentId = decodeURIComponent(teachingsMatch[1]);
      const teaching = { id: `teaching-${Date.now()}`, agent_id: agentId, name: body.name, trigger: body.trigger, steps: body.steps || [], notes: body.notes || null, frame_file_ids: body.frame_file_ids || [], status: 'unverified', revision: 1, enabled: true, created_at: '2026-09-17T08:50:00Z', updated_at: '2026-09-17T08:50:00Z', last_task_id: null };
      state.teachings[agentId] = [...(state.teachings[agentId] || []), teaching];
      return json(route, { teaching: clone(teaching) });
    }
    const teachingMatch = endpoint.match(/^\/agents\/([^/]+)\/teachings\/([^/]+)$/);
    if (teachingMatch && method === 'PATCH') {
      const agentId = decodeURIComponent(teachingMatch[1]);
      const teachingId = decodeURIComponent(teachingMatch[2]);
      const current = (state.teachings[agentId] || []).find((item) => item.id === teachingId);
      if (!current) return json(route, { detail: 'Teaching not found' }, 404);
      Object.assign(current, body);
      if (body.steps || body.name || body.trigger || body.notes !== undefined) current.status = body.verified ? 'verified' : 'unverified';
      if (body.verified) current.status = 'verified';
      current.revision = Number(current.revision || 1) + (body.verified ? 0 : 1);
      state.teachingPatches.push({ id: teachingId, body: clone(body) });
      return json(route, { teaching: clone(current) });
    }
    if (teachingMatch && method === 'DELETE') {
      const agentId = decodeURIComponent(teachingMatch[1]);
      const teachingId = decodeURIComponent(teachingMatch[2]);
      state.teachings[agentId] = (state.teachings[agentId] || []).filter((item) => item.id !== teachingId);
      return json(route, { ok: true });
    }
    const teachingRunMatch = endpoint.match(/^\/agents\/([^/]+)\/teachings\/([^/]+)\/run$/);
    if (teachingRunMatch && method === 'POST') {
      const agentId = decodeURIComponent(teachingRunMatch[1]);
      const teachingId = decodeURIComponent(teachingRunMatch[2]);
      state.teachingRuns.push({ id: teachingId, body: clone(body) });
      const conversationId = 'conversation-alpha';
      const message = { id: `teaching-message-${Date.now()}`, conversation_id: conversationId, role: 'assistant', author_agent_id: agentId, content: 'Procedure run started in this chat.', created_at: '2026-09-17T08:55:00Z' };
      return json(route, { conversation: conversationFor(conversationId), message, tasks: [], request_id: body.client_request_id });
    }
    if (endpoint === '/memory' && method === 'GET') return json(route, { memory: [] });
    if (endpoint === '/files' && method === 'GET') return json(route, { files: [] });
    if (endpoint === '/activity' && method === 'GET') return json(route, { events: [] });

    const routinePatch = endpoint.match(/^\/routines\/([^/]+)$/);
    if (routinePatch && method === 'PATCH') {
      const routine = state.routines.find((item) => item.id === decodeURIComponent(routinePatch[1]));
      if (!routine) return json(route, { detail: 'Routine not found' }, 404);
      Object.assign(routine, body);
      return json(route, { routine: clone(routine) });
    }
    if (routinePatch && method === 'DELETE') {
      const id = decodeURIComponent(routinePatch[1]);
      state.routineDeletes.push(id);
      state.routines = state.routines.filter((routine) => routine.id !== id);
      return json(route, {});
    }
    const routineRun = endpoint.match(/^\/routines\/([^/]+)\/run$/);
    if (routineRun && method === 'POST') {
      const id = decodeURIComponent(routineRun[1]);
      state.routineRuns.push({ id, body: clone(body) });
      if (id === 'routine-morning') return json(route, { error: { code: 'already_working', message: 'A run is already in progress.' } }, 409);
      if (id === 'routine-evening') await state.heldRoutineGate.wait();
      return json(route, { request_id: body.client_request_id, tasks: [] });
    }

    if (endpoint === '/groups' && method === 'POST') {
      const id = `conversation-${String(body.name || 'new-group').toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
      const coordinatorId = body.coordinator_id || body.agent_ids?.[0] || 'agent-alpha';
      const members = (body.agent_ids || []).map((agentId) => {
        const agent = state.agents.find((item) => item.id === agentId);
        return { agent_id: agentId, name: agent?.name || agentId, role: agentId === coordinatorId ? 'coordinator' : 'member', avatar: agent?.avatar || null, color: agent?.color || null };
      });
      const created = { id, conversation_id: id, kind: 'group', agent_id: coordinatorId, coordinator_id: coordinatorId, name: body.name, members, preview: 'New group chat', updated_at: '2026-09-17T08:40:00Z', unread_count: 0, pinned: false, archived: false, active_tasks: [] };
      state.entries.unshift(created);
      state.messages[id] = [];
      state.groupCreates.push({ ...body, id });
      return json(route, { conversation: { id, agent_id: coordinatorId, kind: 'group' } });
    }
    const groupMatch = endpoint.match(/^\/groups\/([^/]+)$/);
    if (groupMatch && method === 'PATCH') {
      const id = decodeURIComponent(groupMatch[1]);
      const entry = state.entries.find((item) => item.conversation_id === id);
      if (!entry) return json(route, { detail: 'Group not found' }, 404);
      Object.assign(entry, body);
      state.groupPatches.push({ id, body: clone(body) });
      return json(route, { conversation: clone(entry) });
    }

    const messagesMatch = endpoint.match(/^\/conversations\/([^/]+)\/messages$/);
    if (messagesMatch && method === 'GET') return json(route, { messages: clone(state.messages[decodeURIComponent(messagesMatch[1])] || []) });
    if (messagesMatch && method === 'POST') {
      const conversationId = decodeURIComponent(messagesMatch[1]);
      const message = { id: `sent-${Date.now()}`, conversation_id: conversationId, role: 'user', content: body.content || '', created_at: '2026-09-17T08:45:00Z', status: 'complete', request_id: body.client_request_id };
      state.messages[conversationId] = [...(state.messages[conversationId] || []), message];
      return json(route, { message, tasks: [], request_id: body.client_request_id });
    }
    const requestsMatch = endpoint.match(/^\/conversations\/([^/]+)\/requests$/);
    if (requestsMatch && method === 'GET') return json(route, { requests: clone(state.requestCards[decodeURIComponent(requestsMatch[1])] || []) });
    const privateRequestMatch = endpoint.match(/^\/requests\/([^/]+)\/private$/);
    if (privateRequestMatch && method === 'POST') {
      const id = decodeURIComponent(privateRequestMatch[1]);
      state.privateSubmissions.push({ id, body: clone(body) });
      const request = Object.values(state.requestCards).flat().find((item) => item.id === id);
      if (!request) return json(route, { detail: 'Request not found' }, 404);
      request.status = 'completed';
      return json(route, { request: clone(request) });
    }
    const decisionMatch = endpoint.match(/^\/requests\/([^/]+)\/decision$/);
    if (decisionMatch && method === 'POST') {
      const id = decodeURIComponent(decisionMatch[1]);
      const request = Object.values(state.requestCards).flat().find((item) => item.id === id);
      if (!request) return json(route, { detail: 'Request not found' }, 404);
      request.status = body.decision === 'approve' ? 'executing' : 'denied';
      return json(route, { request: clone(request) });
    }
    const continueMatch = endpoint.match(/^\/requests\/([^/]+)\/continue$/);
    if (continueMatch && method === 'POST') {
      const id = decodeURIComponent(continueMatch[1]);
      const request = Object.values(state.requestCards).flat().find((item) => item.id === id);
      if (!request) return json(route, { detail: 'Request not found' }, 404);
      state.continuedRequests.push(id);
      request.status = 'executing';
      const conversationId = request.conversation_id;
      const message = { id: `continued-${Date.now()}`, conversation_id: conversationId, role: 'assistant', author_agent_id: request.agent_id, content: 'Continuing this approved request.', created_at: '2026-09-17T09:00:00Z' };
      return json(route, { conversation: conversationFor(conversationId), message, tasks: [], request_id: `continue-${id}` });
    }
    const tasksMatch = endpoint.match(/^\/conversations\/([^/]+)\/tasks$/);
    if (tasksMatch && method === 'GET') return json(route, { tasks: [] });
    if (/^\/conversations\/[^/]+\/read$/.test(endpoint) && method === 'POST') return json(route, {});

    state.unexpected.push(`${method} ${endpoint}`);
    return json(route, {});
  };
  return { state, handler };
}

async function waitFor(predicate, label, timeout = 8000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 40));
  }
  throw new Error(`Timed out waiting for ${label}`);
}

async function assertNoHorizontalOverflow(page, label) {
  const dimensions = await page.evaluate(() => ({ body: document.body.scrollWidth, root: document.documentElement.scrollWidth, viewport: window.innerWidth }));
  assert.ok(Math.max(dimensions.body, dimensions.root) <= dimensions.viewport + 1, `${label} overflow: ${JSON.stringify(dimensions)}`);
  return dimensions;
}

async function runScenario(browser, name, contextOptions, test, report) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light', reducedMotion: 'no-preference', ...contextOptions });
  const page = await context.newPage();
  page.setDefaultTimeout(7000);
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  const fixture = makeFixture();
  try {
    await page.route('**/bot/api/**', fixture.handler);
    await test(page, fixture.state);
    assert.deepStrictEqual(pageErrors, [], `page errors: ${pageErrors.join(' | ')}`);
    assert.deepStrictEqual(fixture.state.unexpected, [], `unexpected API calls: ${fixture.state.unexpected.join(' | ')}`);
    report.push({ name, status: 'passed', api: { agentPatches: fixture.state.agentPatches, groupPatches: fixture.state.groupPatches, agentCreates: fixture.state.agentCreates, groupCreates: fixture.state.groupCreates, accountChecks: fixture.state.accountChecks, routineRuns: fixture.state.routineRuns, routineDeletes: fixture.state.routineDeletes } });
  } catch (error) {
    const failure = path.join(outputDir, `grok-${name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-failure.png`);
    try { await page.screenshot({ path: failure, fullPage: true, animations: 'disabled' }); } catch { /* best effort */ }
    report.push({ name, status: 'failed', error: error.message, pageErrors, unexpected: fixture.state.unexpected, requests: fixture.state.requests });
    console.error(`[${name}] ${error.stack || error}`);
  } finally {
    await context.close();
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const report = [];
  try {
    await runScenario(browser, 'desktop settings edit and account status', { viewport: { width: 1440, height: 900 } }, async (page, state) => {
      await page.goto(baseURL);
      await page.locator('.grok-inbox-row').filter({ hasText: 'Alpha' }).waitFor();
      await page.getByRole('button', { name: 'Open Hermes settings', exact: true }).click();
      await page.getByRole('heading', { name: 'Settings', exact: true }).waitFor();
      const settings = page.locator('section[aria-label="Bot settings"]');
      await settings.getByRole('button', { name: 'Edit', exact: true }).click();
      await settings.getByLabel('Name', { exact: true }).fill('North Star');
      await settings.getByLabel('What should this bot do?', { exact: true }).fill('Keep family plans calm, clear, and short.');
      await settings.locator('details').filter({ hasText: 'Appearance' }).locator('summary').click();
      await settings.getByRole('group', { name: 'Bot color' }).getByRole('button', { name: 'Coral', exact: true }).click();
      await settings.locator('details').filter({ hasText: 'Advanced' }).locator('summary').click();
      await settings.getByLabel('Model', { exact: true }).selectOption('gpt-5.6-sol');
      await settings.getByRole('button', { name: 'Save changes', exact: true }).click();
      await page.getByText('Saved', { exact: true }).waitFor();
      assert.strictEqual(state.agentPatches.length, 1, 'one bot edit should be sent');
      assert.deepStrictEqual(state.agentPatches[0].body, { name: 'North Star', instructions: 'Keep family plans calm, clear, and short.', model: 'gpt-5.6-sol', avatar: 'blob', color: '#ff3347' });
      await settings.getByRole('button', { name: 'Show instructions', exact: true }).click();
      await settings.getByText('Keep family plans calm, clear, and short.', { exact: true }).waitFor();
      await settings.getByRole('button', { name: 'Hide instructions', exact: true }).click();
      await settings.getByRole('button', { name: 'Edit', exact: true }).click();
      assert.strictEqual(await settings.getByLabel('Name', { exact: true }).inputValue(), 'North Star');
      assert.strictEqual(await settings.getByLabel('What should this bot do?', { exact: true }).inputValue(), 'Keep family plans calm, clear, and short.');
      await settings.locator('details').filter({ hasText: 'Appearance' }).locator('summary').click();
      await settings.locator('details').filter({ hasText: 'Advanced' }).locator('summary').click();
      assert.strictEqual(await settings.getByLabel('Model', { exact: true }).inputValue(), 'gpt-5.6-sol');
      assert.strictEqual(await settings.getByRole('group', { name: 'Bot color' }).getByRole('button', { name: 'Coral', exact: true }).getAttribute('aria-pressed'), 'true');
      const connection = page.locator('section[aria-label="ChatGPT connection"]');
      await connection.getByText('Connected', { exact: true }).waitFor();
      await connection.getByRole('button', { name: 'Check connection', exact: true }).click();
      await waitFor(() => state.accountChecks >= 2, 'account status refresh');
      const usage = page.locator('section[aria-label="GPT usage"]');
      await usage.getByText('5 hour window', { exact: true }).waitFor();
      await usage.getByText('Weekly window', { exact: true }).waitFor();
      await usage.getByText('100% remaining', { exact: true }).waitFor();
      await usage.getByText('97% remaining', { exact: true }).waitFor();
      assert.strictEqual(await usage.locator('.grok-usage-window').count(), 2, 'by-id usage buckets should take precedence over duplicate legacy buckets');
      assert.strictEqual(await usage.getByText('Usage window 1', { exact: true }).count(), 0, 'usage buckets should have stable labels');
      const motion = page.locator('section[aria-label="Motion"]');
      await motion.getByRole('radio', { name: /System/ }).waitFor();
      await motion.getByRole('radio', { name: /On/ }).click();
      assert.strictEqual(await page.locator('html').getAttribute('data-motion'), 'on');
      assert.notStrictEqual(await motion.locator('.bot-glyph').evaluate((node) => getComputedStyle(node).animationName), 'none', 'explicit motion On should animate the visible preview');
      await motion.getByRole('radio', { name: /Off/ }).click();
      assert.strictEqual(await page.locator('html').getAttribute('data-motion'), 'off');
      assert.strictEqual(await motion.locator('.bot-glyph').evaluate((node) => getComputedStyle(node).animationName), 'none', 'motion Off should stop the preview');
      await motion.getByRole('radio', { name: /System/ }).click();
      await page.screenshot({ path: path.join(outputDir, 'grok-settings-desktop.png'), fullPage: true, animations: 'disabled' });
    }, report);

    await runScenario(browser, 'reduced motion explicit on preview', { viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' }, async (page) => {
      await page.goto(baseURL);
      await page.getByRole('button', { name: 'Open Hermes settings', exact: true }).click();
      const motion = page.locator('section[aria-label="Motion"]');
      await motion.getByRole('radio', { name: /System/ }).waitFor();
      assert.strictEqual(await motion.locator('.bot-glyph').evaluate((node) => getComputedStyle(node).animationName), 'none', 'System should follow reduced motion');
      await motion.getByRole('radio', { name: /On/ }).click();
      assert.strictEqual(await page.locator('html').getAttribute('data-motion'), 'on');
      assert.notStrictEqual(await motion.locator('.bot-glyph').evaluate((node) => getComputedStyle(node).animationName), 'none', 'explicit motion On should override reduced motion for the preview');
      await motion.getByRole('radio', { name: /Off/ }).click();
      assert.strictEqual(await motion.locator('.bot-glyph').evaluate((node) => getComputedStyle(node).animationName), 'none', 'motion Off should stop the preview');
    }, report);

    await runScenario(browser, '2560px settings stays compact and aligned', { viewport: { width: 2560, height: 900 } }, async (page) => {
      await page.goto(baseURL);
      await page.getByRole('button', { name: 'Open Hermes settings', exact: true }).click();
      await page.getByRole('heading', { name: 'Settings', exact: true }).waitFor();
      const widths = await page.locator('.grok-settings-stack > *').evaluateAll((nodes) => nodes.map((node) => Math.round(node.getBoundingClientRect().width)));
      assert.ok(widths.length >= 6 && widths.every((width) => width <= 800), `settings sections should stay compact: ${JSON.stringify(widths)}`);
      assert.ok(Math.max(...widths) - Math.min(...widths) <= 2, `settings sections should share one column: ${JSON.stringify(widths)}`);
      await page.screenshot({ path: path.join(outputDir, 'grok-settings-2560.png'), fullPage: true, animations: 'disabled' });
    }, report);

    await runScenario(browser, 'desktop composer expansions and private request', { viewport: { width: 1440, height: 900 } }, async (page, state) => {
      state.requestCards['conversation-alpha'] = [
        { id: 'request-private', agent_id: 'agent-alpha', conversation_id: 'conversation-alpha', kind: 'private_input', title: 'Supplier portal key', purpose: 'Enter it once so Alpha can finish the supplier update.', status: 'pending', created_at: '2026-09-17T08:45:00Z', expires_at: '2026-09-17T10:00:00Z', data: { label: 'Supplier portal key', destination: 'Supplier portal' } },
        { id: 'request-complete', agent_id: 'agent-alpha', conversation_id: 'conversation-alpha', kind: 'connector_action', title: 'Supplier update finished', purpose: 'The approved update is ready to continue.', status: 'completed', created_at: '2026-09-17T08:40:00Z', data: { toolkit: 'GitHub', tool: 'create_issue' }, result: { safe: true } },
      ];
      await page.goto(baseURL);
      await page.locator('.grok-inbox-row').filter({ hasText: 'Alpha' }).click();
      await page.getByRole('textbox', { name: 'Message Alpha', exact: true }).waitFor();
      const privateCard = page.getByRole('article', { name: 'Supplier portal key' });
      await privateCard.getByRole('button', { name: 'Enter value', exact: true }).waitFor();
      const completeCard = page.getByRole('article', { name: 'Supplier update finished' });
      await completeCard.getByRole('button', { name: 'Continue with Alpha', exact: true }).waitFor();

      await privateCard.getByRole('button', { name: 'Enter value', exact: true }).click();
      const requestPrivateDialog = page.getByRole('dialog', { name: 'Supplier portal key', exact: true });
      await requestPrivateDialog.getByLabel('Value', { exact: true }).fill('fixture-secret-value');
      await requestPrivateDialog.getByRole('button', { name: 'Save and continue', exact: true }).click();
      await waitFor(() => state.privateSubmissions.length === 1, 'private request submission');
      assert.strictEqual(state.privateSubmissions[0].body.value, 'fixture-secret-value');
      assert.ok(!((await page.locator('body').innerText()).includes('fixture-secret-value')), 'private value must leave the visible UI after submission');
      const localStorageValues = await page.evaluate(() => Object.values(localStorage));
      assert.ok(!localStorageValues.some((value) => value.includes('fixture-secret-value')), 'private value must never enter localStorage');

      await page.getByRole('button', { name: 'Open composer actions', exact: true }).click();
      const actions = page.getByRole('listbox', { name: 'Composer actions', exact: true });
      await actions.waitFor();
      await actions.getByRole('option').filter({ hasText: 'Connections' }).click();
      const connections = page.getByRole('dialog', { name: 'Connections', exact: true });
      await connections.getByText('Google Drive', { exact: true }).waitFor();
      await connections.getByText('Dad’s GitHub', { exact: true }).waitFor();
      await connections.getByRole('button', { name: 'Connect', exact: true }).first().click();
      await connections.getByRole('link', { name: /Open sign-in/ }).waitFor();
      assert.deepStrictEqual(state.connectionLinks[0], { toolkit: 'google-drive' });
      await connections.getByRole('button', { name: 'Done', exact: true }).click();

      await page.getByRole('button', { name: 'Open composer actions', exact: true }).click();
      await page.getByRole('listbox', { name: 'Composer actions', exact: true }).getByRole('option').filter({ hasText: 'Private input' }).click();
      const standalonePrivateDialog = page.getByRole('dialog', { name: 'Save a private value', exact: true });
      await standalonePrivateDialog.getByRole('button', { name: 'Cancel', exact: true }).click();

      await privateCard.getByRole('button', { name: 'Continue with Alpha', exact: true }).click();
      await waitFor(() => state.continuedRequests.includes('request-private'), 'completed request continuation');
      await page.getByText('Continuing this approved request.', { exact: true }).waitFor();

      await page.getByRole('button', { name: 'Open composer actions', exact: true }).click();
      await page.getByRole('listbox', { name: 'Composer actions', exact: true }).getByRole('option').filter({ hasText: 'Teach a task' }).click();
      const teaching = page.getByRole('dialog', { name: 'Teach a task', exact: true });
      await teaching.getByLabel('Name', { exact: true }).fill('Prepare supplier update');
      await teaching.getByLabel('When should Chief use it?', { exact: true }).fill('When I ask for a supplier update');
      await teaching.locator('textarea').first().fill('Open the supplier report.');
      await teaching.getByRole('button', { name: 'Add step', exact: true }).click();
      await teaching.locator('textarea').nth(1).fill('Summarize the open items.');
      await teaching.getByRole('button', { name: 'Save procedure', exact: true }).click();
      await waitFor(() => (state.teachings['agent-alpha'] || []).length === 1, 'teaching create request');
      await teaching.waitFor({ state: 'detached' });
      assert.deepStrictEqual(state.teachings['agent-alpha'][0].steps, ['Open the supplier report.', 'Summarize the open items.']);
      await page.screenshot({ path: path.join(outputDir, 'grok-expansion-desktop.png'), fullPage: true, animations: 'disabled' });
    }, report);

    await runScenario(browser, '390px action sheet and slash palette', { viewport: { width: 390, height: 844 } }, async (page, state) => {
      state.teachings['agent-alpha'] = [{ id: 'teaching-morning', agent_id: 'agent-alpha', name: 'Morning supplier update', trigger: 'When I ask for the supplier update', steps: ['Open the report.', 'Tell me what needs attention.'], notes: 'Keep the answer short.', frame_file_ids: [], status: 'unverified', revision: 2, enabled: true, created_at: '2026-09-17T08:20:00Z', updated_at: '2026-09-17T08:20:00Z', last_task_id: null }];
      await page.goto(baseURL);
      await page.locator('.grok-inbox-row').filter({ hasText: 'Alpha' }).click();
      const composer = page.getByRole('textbox', { name: 'Message Alpha', exact: true });
      await composer.waitFor();
      await composer.fill('/');
      await page.getByRole('listbox', { name: 'Slash commands', exact: true }).waitFor();
      await page.getByRole('listbox', { name: 'Slash commands', exact: true }).locator('button').filter({ hasText: '/teach-a-task' }).waitFor();
      await page.keyboard.press('Escape');
      await page.getByRole('button', { name: 'Open composer actions', exact: true }).click();
      const actions = page.getByRole('listbox', { name: 'Composer actions', exact: true });
      await actions.getByRole('option').filter({ hasText: 'Connections' }).click();
      const sheet = page.getByRole('dialog', { name: 'Connections', exact: true });
      await sheet.getByText('Google Drive', { exact: true }).waitFor();
      await assertNoHorizontalOverflow(page, 'mobile connections sheet');
      await page.screenshot({ path: path.join(outputDir, 'grok-expansion-mobile.png'), fullPage: true, animations: 'disabled' });
      await sheet.getByRole('button', { name: 'Done', exact: true }).click();
      await assertNoHorizontalOverflow(page, 'mobile expansion chat');
      assert.ok(state.requests.some((item) => item.endpoint === '/connections'), 'mobile sheet should load connections through the API');
    }, report);

    await runScenario(browser, 'tablet group archive restore and creation', { viewport: { width: 834, height: 1112 } }, async (page, state) => {
      await page.goto(baseURL);
      const groupRow = page.locator('.grok-inbox-row').filter({ hasText: 'Weekend Crew' });
      await groupRow.waitFor();
      await groupRow.click();
      await page.getByRole('textbox', { name: 'Message Weekend Crew', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Chat options', exact: true }).click();
      await page.getByRole('button', { name: 'Archive chat', exact: true }).click();
      await waitFor(() => state.groupPatches.some((item) => item.id === 'conversation-weekend' && item.body.archived === true), 'group archive request');
      await waitFor(() => page.locator('.grok-inbox-row').filter({ hasText: 'Weekend Crew' }).count().then((count) => count === 0), 'archived group should leave active inbox');
      await page.getByRole('button', { name: 'Archived chats', exact: true }).click();
      await page.locator('.grok-inbox-row').filter({ hasText: 'Weekend Crew' }).click();
      await page.getByRole('textbox', { name: 'Message Weekend Crew', exact: true }).waitFor();
      await page.locator('.grok-banner').getByRole('button', { name: 'Restore chat', exact: true }).click();
      await waitFor(() => state.groupPatches.some((item) => item.id === 'conversation-weekend' && item.body.archived === false), 'group restore request');
      await page.screenshot({ path: path.join(outputDir, 'grok-tablet-group-archive-restore.png'), fullPage: true, animations: 'disabled' });

      await page.getByRole('button', { name: 'New chat', exact: true }).click();
      await page.locator('.grok-create-menu').getByRole('button', { name: /^New group chat/ }).click();
      await page.getByRole('heading', { name: 'New group chat', exact: true }).waitFor();
      await page.getByLabel('Group name', { exact: true }).fill('Family Helpers');
      await page.getByRole('button', { name: 'Create group', exact: true }).click();
      await waitFor(() => state.groupCreates.length === 1, 'group creation request');
      await page.getByRole('button', { name: 'Back to chats', exact: true }).click();
      await page.locator('.grok-inbox-row').filter({ hasText: 'Family Helpers' }).waitFor();

      await page.getByRole('button', { name: 'New chat', exact: true }).click();
      await page.locator('.grok-create-menu').getByRole('button', { name: /^New Bot/ }).click();
      await page.getByRole('heading', { name: 'New Bot', exact: true }).waitFor();
      await page.locator('#bot-creator-name').fill('Reading Buddy');
      await page.getByText('Details', { exact: true }).click();
      await page.locator('#bot-creator-description').fill('Reads notes and keeps the next step clear.');
      await page.getByRole('button', { name: 'Get started', exact: true }).click();
      await waitFor(() => state.agentCreates.length === 1, 'bot creation request');
      await page.locator('.grok-inbox-row').filter({ hasText: 'Reading Buddy' }).waitFor();
      assert.deepStrictEqual(state.agentCreates[0], { name: 'Reading Buddy', instructions: 'Reads notes and keeps the next step clear.', model: 'gpt-5.6-luna', status: 'active', avatar: 'blob', color: '#2d93fa', id: 'agent-reading-buddy' });
      await assertNoHorizontalOverflow(page, 'tablet');
    }, report);

    await runScenario(browser, 'routine error recovery and duplicate run guard', { viewport: { width: 1440, height: 900 } }, async (page, state) => {
      await page.goto(baseURL);
      await page.locator('.grok-inbox-row').filter({ hasText: 'Alpha' }).click();
      await page.getByRole('button', { name: 'Toggle details', exact: true }).click();
      const routines = page.locator('section.grok-routines');
      await routines.getByText('Morning briefing', { exact: true }).waitFor();

      const morning = routines.locator('.grok-routine-row').filter({ hasText: 'Morning briefing' });
      await morning.getByRole('button', { name: 'Run', exact: true }).click();
      await page.getByRole('alert').filter({ hasText: 'A run is already in progress.' }).waitFor();
      assert.strictEqual(state.routineRuns.length, 1, 'the rejected routine run should still be recorded');

      await morning.getByRole('button', { name: 'Delete Morning briefing', exact: true }).click();
      await waitFor(() => state.routineDeletes.includes('routine-morning'), 'routine delete request');
      await waitFor(() => routines.locator('.grok-routine-row').filter({ hasText: 'Morning briefing' }).count().then((count) => count === 0), 'deleted routine to disappear');
      assert.strictEqual(await routines.getByRole('alert').count(), 0, 'successful delete should clear the old run error');

      const evening = routines.locator('.grok-routine-row').filter({ hasText: 'Evening recap' });
      const run = evening.getByRole('button', { name: 'Run', exact: true });
      await run.dispatchEvent('click');
      await run.dispatchEvent('click');
      await waitFor(() => state.routineRuns.filter((item) => item.id === 'routine-evening').length === 1, 'one held routine run request');
      assert.strictEqual(state.routineRuns.filter((item) => item.id === 'routine-evening').length, 1, 'rapid duplicate clicks must send one run request');
      assert.equal(await run.isDisabled(), true, 'routine actions should disable while the request is held');
      state.heldRoutineGate.release();
      await waitFor(() => run.isDisabled().then((disabled) => !disabled), 'routine action recovery');
    }, report);

    await runScenario(browser, '390px light inbox and chat', { viewport: { width: 390, height: 844 } }, async (page) => {
      await page.goto(baseURL);
      await page.locator('.grok-inbox-row').filter({ hasText: 'Alpha' }).waitFor();
      await assertNoHorizontalOverflow(page, 'mobile inbox');
      await page.screenshot({ path: path.join(outputDir, 'grok-mobile-390-inbox.png'), fullPage: true, animations: 'disabled' });
      await page.locator('.grok-inbox-row').filter({ hasText: 'Alpha' }).click();
      await page.getByRole('textbox', { name: 'Message Alpha', exact: true }).waitFor();
      await assertNoHorizontalOverflow(page, 'mobile chat');
      const controls = await page.locator('.grok-composer-button, .grok-send-button').evaluateAll((nodes) => nodes.map((node) => { const box = node.getBoundingClientRect(); return { width: box.width, height: box.height }; }));
      assert.ok(controls.every((box) => box.width >= 44 && box.height >= 44), `mobile composer targets too small: ${JSON.stringify(controls)}`);
      await page.screenshot({ path: path.join(outputDir, 'grok-mobile-390-chat.png'), fullPage: true, animations: 'disabled' });
      await page.getByRole('button', { name: 'Back to inbox', exact: true }).click();
      await page.getByRole('button', { name: 'Open Hermes settings', exact: true }).click();
      await page.getByRole('heading', { name: 'Settings', exact: true }).waitFor();
      await page.locator('section[aria-label="Motion"]').waitFor();
      await assertNoHorizontalOverflow(page, 'mobile settings');
      await page.screenshot({ path: path.join(outputDir, 'grok-mobile-390-settings.png'), fullPage: true, animations: 'disabled' });
    }, report);
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(outputDir, 'grok-settings-test-report.json'), JSON.stringify({ baseURL, generated_at: new Date().toISOString(), screenshots: outputDir, scenarios: report }, null, 2));
  }
  console.log(JSON.stringify({ scenarios: report, screenshots: outputDir }, null, 2));
  if (report.some((item) => item.status === 'failed')) process.exitCode = 1;
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
