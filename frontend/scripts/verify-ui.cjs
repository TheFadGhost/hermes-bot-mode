/*
 * Fixture-only UI verification for Bot Mode.
 * Usage: node scripts/verify-ui.cjs
 * The app must already be running at http://127.0.0.1:5174/bot/.
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('C:/Users/Work/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

const baseURL = process.env.BOT_MODE_URL || 'http://127.0.0.1:5174/bot/';
const outputDir = path.resolve(__dirname, '../../design-research/verification');
fs.mkdirSync(outputDir, { recursive: true });

const agents = [
  { id: 'chief-of-staff', name: 'Chief of Staff', description: 'Keeps priorities moving and prepares concise briefs.', color: '#8b5cf6', avatar: 'blob', is_active: true, memory_scope: 'private' },
  { id: 'ea', name: 'EA', description: 'Handles scheduling and follow ups.', color: '#2f8cff', avatar: 'drop', is_active: true, memory_scope: 'private' },
  { id: 'inbox-manager', name: 'Inbox Manager', description: 'Triages email and drafts replies for approval.', color: '#20b486', avatar: 'cloud', is_active: true, memory_scope: 'private' },
  { id: 'sales-outbound', name: 'Sales Outbound', description: 'Queues thoughtful outreach drafts.', color: '#f97316', avatar: 'hex', is_active: true, memory_scope: 'private' },
  { id: 'talent-scout', name: 'Talent Scout', description: 'Finds candidates and prepares shortlists.', color: '#9a6b3f', avatar: 'peak', is_active: true, memory_scope: 'private' },
  { id: 'growth-marketer', name: 'Growth Marketer', description: 'Prepares experiments and campaign updates.', color: '#f59e0b', avatar: 'blob', is_active: true, memory_scope: 'private' },
  { id: 'customer-support', name: 'Customer Support', description: 'Resolves tickets and escalates edge cases.', color: '#ef3357', avatar: 'drop', is_active: true, memory_scope: 'private' },
  { id: 'expense-manager', name: 'Expense Manager', description: 'Codes receipts and flags missing context.', color: '#ec4899', avatar: 'cloud', is_active: true, memory_scope: 'private' },
  { id: 'invoice-collector', name: 'Invoice Collector', description: 'Collects invoices from vendor portals.', color: '#6366f1', avatar: 'hex', is_active: true, memory_scope: 'private' },
];
const conversations = agents.map((agent, i) => ({ id: `conv-${agent.id}`, agent_id: agent.id, title: i === 0 ? 'Morning brief' : 'Latest work', updated_at: `2026-09-16T0${8 - Math.min(i, 3)}:20:00Z`, message_count: 3 }));
const messages = Object.fromEntries(conversations.map((conversation, i) => [conversation.id, [
  { id: `${conversation.id}-1`, conversation_id: conversation.id, role: 'assistant', content: i === 2 ? 'I triaged the inbox and drafted one reply for your review.' : 'Good morning. I have a useful update ready for you.', created_at: '2026-09-16T08:00:00Z', status: 'complete' },
  { id: `${conversation.id}-2`, conversation_id: conversation.id, role: 'user', content: 'Thanks, show me what needs my attention.', created_at: '2026-09-16T08:05:00Z', status: 'complete' },
  { id: `${conversation.id}-3`, conversation_id: conversation.id, role: 'assistant', content: 'Here is the next step. I will wait for your approval before sending anything.', created_at: '2026-09-16T08:06:00Z', status: 'complete' },
]]));

function fixture(initialAgents = agents, capture = {}) {
  let currentAgents = initialAgents.map((agent) => ({ ...agent }));
  const state = { lastCreated: null };
  return async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const endpoint = url.pathname.replace(/^\/bot\/api/, '');
    const method = req.method();
    let body;
    try { body = req.postDataJSON(); } catch { body = {}; }
    const reply = (payload, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload) });
    if (endpoint === '/auth/me') return reply({ authenticated: true, user: { id: 'user-1', name: 'Alex Chen', username: 'alex' } });
    if (endpoint === '/agents' && method === 'GET') return reply({ agents: currentAgents });
    if (endpoint === '/agents' && method === 'POST') {
      const agent = { id: `agent-${Date.now()}`, name: body.name || 'New bot', description: body.instructions || '', color: body.color || '#8b5cf6', avatar: body.avatar || 'blob', is_active: true, memory_scope: body.memory_scope || 'private' };
      currentAgents = [...currentAgents, agent];
      state.lastCreated = { ...agent, body };
      capture.lastCreated = state.lastCreated;
      return reply({ agent });
    }
    if (endpoint === '/conversations' && method === 'GET') return reply({ conversations: conversations.filter((c) => currentAgents.some((a) => a.id === c.agent_id)) });
    if (endpoint.startsWith('/conversations/') && endpoint.endsWith('/messages') && method === 'GET') return reply({ messages: messages[endpoint.split('/')[2]] || [] });
    if (endpoint === '/memory') return reply({ memory: [] });
    if (endpoint === '/files') return reply({ files: [] });
    if (endpoint === '/activity') return reply({ events: [] });
    if (endpoint === '/runtime/status') return reply({ runtime: { available: true, provider: 'fixture', model: 'gpt-5.6-luna' } });
    if (endpoint === '/runtime/account') return reply({ account: { connected: true, type: 'fixture', plan: 'test' } });
    if (endpoint === '/runtime/usage') return reply({ usage: { used: 12, limit: 100, remaining: 88 } });
    if (endpoint === '/onboarding') return reply({ complete: true, steps: [] });
    if (endpoint.startsWith('/agents/') && endpoint.endsWith('/desktop')) return reply({ desktop: { available: false, created: false, running: false } });
    return reply({});
  };
}

async function assertNoOverflow(page, label, errors = []) {
  const result = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: window.innerWidth }));
  if (result.width > result.viewport + 1) throw new Error(`${label}: horizontal overflow ${result.width}px > ${result.viewport}px`);
  if (errors.length) throw new Error(`${label}: page errors: ${errors.join(' | ')}`);
}

async function screenshot(page, name) { await page.screenshot({ path: path.join(outputDir, `${name}.png`), fullPage: true }); }

async function run() {
  const browser = await chromium.launch({ headless: true });
  const report = { baseURL, generatedAt: new Date().toISOString(), scenarios: [], passed: false };
  const record = async (name, fn) => {
    const item = { name, status: 'failed' };
    report.scenarios.push(item);
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light', reducedMotion: 'no-preference' });
    const page = await context.newPage(); page.setDefaultTimeout(5000);
    const errors = []; page.on('pageerror', (error) => errors.push(error.message)); await page.addInitScript(() => { window.__verifyErrors = []; });
    try { const capture = {}; await page.route('**/bot/api/**', fixture(agents, capture)); await fn(page, errors, capture); if (errors.length) throw new Error(`page errors: ${errors.join(' | ')}`); item.status = 'passed'; } catch (error) { item.error = error.message; if (errors.length) item.pageErrors = errors; } finally { await context.close(); }
  };

  await record('desktop populated chat (1440x900)', async (page, errors) => {
    await page.goto(baseURL); await page.locator('.sidebar').waitFor(); await page.getByRole('button', { name: 'Open Chief of Staff' }).click();
    await page.locator('.conversation-tabs').getByText('Morning brief').waitFor(); await assertNoOverflow(page, 'desktop populated', errors); await screenshot(page, 'desktop-populated-chat');
  });
  await record('desktop empty first creation', async (page, errors) => {
    await page.unroute('**/bot/api/**'); await page.route('**/bot/api/**', fixture([])); await page.goto(baseURL);
    await page.getByRole('button', { name: 'New bot' }).click(); await page.getByLabel('Name').fill('Inbox Manager');
    await screenshot(page, 'desktop-empty-first-creation'); await page.getByRole('button', { name: 'Get started' }).click(); await page.locator('h1').filter({ hasText: 'Inbox Manager' }).waitFor(); await assertNoOverflow(page, 'desktop empty', errors);
  });
  await record('mobile home (390x844)', async (page, errors) => {
    await page.setViewportSize({ width: 390, height: 844 }); await page.goto(baseURL); await page.locator('.mobile-home').waitFor(); await page.getByRole('button', { name: 'Open Chief of Staff' }).waitFor();
    for (const name of ['Chief of Staff', 'EA', 'Inbox Manager']) await page.getByRole('button', { name: `Open ${name}` }).waitFor();
    await assertNoOverflow(page, 'mobile home', errors); await screenshot(page, 'mobile-home-390x844');
  });
  await record('mobile selected chat and back navigation', async (page, errors) => {
    await page.setViewportSize({ width: 390, height: 844 }); await page.goto(baseURL); await page.getByRole('button', { name: 'Open Inbox Manager' }).click(); await page.getByText('triaged the inbox').waitFor(); await screenshot(page, 'mobile-selected-chat'); await page.getByRole('button', { name: 'Back to bots' }).click(); await page.locator('.mobile-home').waitFor(); await assertNoOverflow(page, 'mobile back', errors); await screenshot(page, 'mobile-back-navigation');
  });
  await record('mobile new bot creator controls', async (page, errors, capture) => {
    await page.setViewportSize({ width: 390, height: 844 }); await page.goto(baseURL); await page.getByRole('button', { name: 'New bot' }).click(); await page.getByLabel('Name').fill('Night Shift'); await page.getByRole('radio', { name: 'Pink color' }).check(); await page.getByRole('radio', { name: 'Cloud shape' }).check(); await page.waitForTimeout(250); await screenshot(page, 'mobile-new-bot-creator'); await page.getByRole('button', { name: 'Get started' }).click(); await page.locator('.empty-chat h2').filter({ hasText: 'Night Shift' }).waitFor(); if (!capture.lastCreated || capture.lastCreated.body.name !== 'Night Shift' || capture.lastCreated.body.color !== '#ff36a0' || capture.lastCreated.body.avatar !== 'cloud') throw new Error(`creator POST did not preserve selections: ${JSON.stringify(capture.lastCreated?.body)}`); await assertNoOverflow(page, 'mobile creator', errors);
  });
  await record('settings and bot details navigation', async (page, errors) => {
    await page.setViewportSize({ width: 820, height: 1180 }); await page.goto(baseURL); await page.getByRole('button', { name: 'Settings' }).click(); await page.getByRole('heading', { name: 'Settings' }).waitFor(); await screenshot(page, 'tablet-settings');
    await page.setViewportSize({ width: 390, height: 844 }); await page.goto(baseURL); await page.getByRole('button', { name: 'Open Chief of Staff' }).click(); await page.getByRole('button', { name: 'Open bot details' }).click(); await page.locator('.mobile-info-overlay').getByRole('heading', { name: 'Bot details' }).waitFor(); await assertNoOverflow(page, 'mobile details', errors);
  });
  for (const viewport of [{ width: 820, height: 1180, name: 'tablet-820x1180' }, { width: 320, height: 740, name: 'narrow-320x740' }]) {
    await record(viewport.name, async (page, errors) => { await page.setViewportSize(viewport); await page.goto(baseURL); await page.locator('.sidebar:visible, .mobile-home:visible').first().waitFor(); if(viewport.width > 640) await page.locator('.message-content').first().waitFor(); else await page.getByRole('button', {name:'Open Chief of Staff'}).waitFor(); await assertNoOverflow(page, viewport.name, errors); await screenshot(page, viewport.name); });
  }
  await record('drafts, search and disabled send', async (page) => {
    await page.setViewportSize({width:390,height:844}); await page.goto(baseURL);
    await page.getByRole('button',{name:'Open Chief of Staff'}).click();
    const input = page.getByRole('textbox',{name:'Message Chief of Staff'});
    await page.locator('.message-content').first().waitFor();
    if (await page.getByRole('button',{name:'Send message',exact:true}).isEnabled()) throw new Error('Empty send enabled');
    await input.fill('Draft for Chief only'); await page.getByRole('button',{name:'Back to bots'}).click();
    await page.getByRole('button',{name:'Open EA',exact:true}).click();
    if(await page.getByRole('textbox',{name:'Message EA',exact:true}).inputValue()) throw new Error('Draft leaked between bots');
    await page.getByRole('button',{name:'Back to bots'}).click(); await page.getByRole('button',{name:'Open Chief of Staff'}).click();
    await page.locator('.message-content').first().waitFor();
    if(await input.inputValue() !== 'Draft for Chief only') throw new Error('Draft was not preserved');
    await page.getByRole('button',{name:'Back to bots'}).click(); await page.getByRole('button',{name:'Search bots',exact:true}).click();
    await page.getByRole('textbox',{name:'Find a bot'}).fill('no-such-bot'); await page.getByText('No bots found',{exact:true}).waitFor();
  });
  await record('dark and reduced motion', async (page) => { await page.close(); const context = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: 'dark', reducedMotion: 'reduce' }); const dark = await context.newPage(); dark.setDefaultTimeout(5000); await dark.addInitScript(() => localStorage.setItem('hermes-theme', 'dark')); await dark.route('**/bot/api/**', fixture()); await dark.goto(baseURL); await dark.locator('.mobile-home').waitFor(); await assertNoOverflow(dark, 'dark reduced motion'); await screenshot(dark, 'mobile-dark-reduced-motion'); await context.close(); });

  report.passed = report.scenarios.every((scenario) => scenario.status === 'passed');
  fs.writeFileSync(path.join(outputDir, 'verify-ui-report.json'), JSON.stringify(report, null, 2));
  await browser.close();
  if (!report.passed) { console.error(JSON.stringify(report, null, 2)); process.exitCode = 1; } else console.log(`UI verification passed: ${report.scenarios.length} scenarios`);
}
run().catch((error) => { console.error(error); process.exitCode = 1; });
