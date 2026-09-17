/* Independent fixture regressions: no production traffic or runtime jobs. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('C:/Users/Work/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const baseURL = process.env.BOT_MODE_URL || 'http://127.0.0.1:5173/bot/';
const out = path.resolve(__dirname, '../../design-research/verification/grok-recovery');
fs.mkdirSync(out, { recursive: true });
const agents = ['Alpha', 'Beta'].map((name, i) => ({ id: `agent-${name.toLowerCase()}`, name, instructions: `${name} fixture`, model: 'gpt-5.6-luna', status: 'active', avatar: 'blob', color: i ? '#2d93fa' : '#8754f5' }));
const conversations = agents.map(a => ({ id: `conversation-${a.name.toLowerCase()}`, agent_id: a.id, title: a.name, kind: 'direct' }));
const entries = agents.map((a, i) => ({ conversation_id: conversations[i].id, agent_id: a.id, coordinator_id: a.id, kind: 'direct', name: a.name, members: [{ agent_id: a.id, name: a.name, role: 'coordinator' }], preview: `${a.name} fixture`, active_tasks: [], unread_count: 0 }));
function gate() { let resolve; const promise = new Promise(r => resolve = r); return { wait: () => promise, release: () => resolve() }; }
const events = (...items) => items.map(([id, type, data]) => `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(data)}\n\n`).join('');
const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
const stream = (route, body) => route.fulfill({ status: 200, contentType: 'text/event-stream', body });
async function until(check, message, timeout = 8000) { const end = Date.now() + timeout; while (Date.now() < end) { if (await check()) return; await new Promise(r => setTimeout(r, 40)); } throw Error(message); }
function fixture(mode) {
  const s = { mode, task: null, posts: 0, cancels: 0, eventCalls: 0, homeCalls: 0, historyFailures: 0, postGate: gate(), homeGate: gate(), streamGate: gate(), recovered: false, completed: false, requests: [], messages: {} };
  for (const c of conversations) s.messages[c.id] = [{ id: `${c.id}-seed`, conversation_id: c.id, role: 'assistant', author_agent_id: c.agent_id, content: `${c.title} is ready`, created_at: 1789632000 }];
  const oldMessage = { id: 'archive-old', conversation_id: 'conversation-alpha', role: 'assistant', author_agent_id: 'agent-alpha', content: 'Archive sentinel from the oldest page.', created_at: 1789000000 };
  if (mode === 'history-page' || mode === 'history-search' || mode === 'history-gap') s.messages['conversation-alpha'] = Array.from({length:100}, (_,i) => ({id:`recent-${i}`,conversation_id:'conversation-alpha',role:'assistant',author_agent_id:'agent-alpha',content:`Recent history message ${i}`,created_at:1789632000+i}));
  s.release = () => { s.postGate.release(); s.homeGate.release(); s.streamGate.release(); };
  s.handler = async route => {
    const req = route.request(), url = new URL(req.url()), endpoint = url.pathname.replace(/^\/bot\/api/, ''), method = req.method();
    s.requests.push(`${method} ${endpoint}`);
    let body = {}; try { body = req.postDataJSON() || {}; } catch {}
    if (endpoint === '/auth/me') return json(route, { authenticated: true, user: { id: 'recovery-owner', name: 'Recovery QA' } });
    if (endpoint === '/bootstrap') return json(route, { chief: agents[0] });
    if (endpoint === '/agents') return json(route, { agents });
    if (endpoint === '/inbox') return json(route, { items: mode === 'home-race' ? [] : entries });
    if (endpoint === '/conversations') return json(route, { conversations: mode === 'home-race' ? [conversations[1]] : conversations });
    if (endpoint === '/runtime/status') return json(route, { runtime: { available: true } });
    if (endpoint === '/runtime/account') return json(route, { connected: true, models: [{ id: 'gpt-5.6-luna', name: 'Luna' }] });
    if (endpoint === '/runtime/usage') return json(route, { usage: {} });
    if (/\/home$/.test(endpoint)) { s.homeCalls++; if (mode === 'home-race') await s.homeGate.wait(); return json(route, { conversation: conversations[0] }); }
    if (endpoint === '/agents/agent-alpha/desktop' && method === 'POST') { s.desktopStarts=(s.desktopStarts||0)+1; await s.postGate.wait(); return json(route,{desktop:{available:true,created:true,running:true,phase:'running',generation:2}}); }
    if (/\/desktop$/.test(endpoint)) return json(route, { desktop: { available: mode === 'desktop-start', created: mode === 'desktop-start', running: false, phase: 'sleeping', generation: 1 } });
    if (/\/routines$/.test(endpoint)) return json(route, { routines: [] });
    if (/\/skills$/.test(endpoint)) return json(route, { skills: [] });
    if (endpoint === '/memory') return json(route, { memory: [] });
    if (endpoint === '/files') return json(route, { files: [] });
    if (endpoint === '/search') return json(route,{matches:[{id:oldMessage.id,message_id:oldMessage.id,conversation_id:oldMessage.conversation_id,name:'Alpha archive',snippet:oldMessage.content}]});
    if (endpoint === '/messages/archive-old') return json(route,{message:oldMessage});
    if (endpoint === '/activity') return json(route, { events: [] });
    if (/\/read$/.test(endpoint)) return json(route, {});
    const messages = endpoint.match(/^\/conversations\/([^/]+)\/messages$/);
    if (messages && method === 'GET') {
      if (url.searchParams.has('before_id')) { s.olderRequests=(s.olderRequests||0)+1; s.lastBeforeId=url.searchParams.get('before_id'); return json(route,{messages: mode === 'history-gap' ? [{...oldMessage,id:'archive-middle',content:'Intervening history remains reachable.',created_at:1789600000}] : [oldMessage]}); }
      if (mode === 'failed-refresh' && s.completed && messages[1] === 'conversation-alpha') { s.historyFailures++; return json(route, { detail: 'Fixture history temporarily unavailable' }, 503); }
      return json(route, { messages: s.messages[messages[1]] || [] });
    }
    if (messages && method === 'POST') {
      s.posts++;
      if (mode === 'early-stop') await s.postGate.wait();
      const message = { id: 'sent-message', conversation_id: messages[1], role: 'user', content: body.content, created_at: 1789632100 };
      s.messages[messages[1]].push(message);
      s.task = { id: 'recovery-task', conversation_id: messages[1], origin_conversation_id: messages[1], agent_id: 'agent-alpha', request_id: 'durable-request', status: 'running' };
      return json(route, { message, task: s.task, tasks: [s.task], request_id: s.task.request_id });
    }
    if (/\/cancel$/.test(endpoint)) { s.cancels++; if (mode === 'early-stop') return json(route, { detail: 'Fixture cancellation unavailable' }, 503); if (s.task) s.task.status = 'cancelled'; return json(route, { tasks: s.task ? [s.task] : [] }); }
    if (/^\/conversations\/[^/]+\/tasks$/.test(endpoint)) return json(route, { tasks: s.task && endpoint.includes(s.task.conversation_id) ? [s.task] : [] });
    if (endpoint === '/tasks/recovery-task') return json(route, { task: s.task });
    if (endpoint === '/tasks/recovery-task/events') {
      const call = ++s.eventCalls;
      if (mode === 'partial-failure') {
        s.task.status = 'failed';
        s.messages['conversation-alpha'].push({id:'saved-partial',conversation_id:'conversation-alpha',role:'assistant',author_agent_id:'agent-alpha',source_task_id:s.task.id,status:'partial',content:'Saved partial answer.',created_at:1789632200});
        return stream(route, events([1,'task.started',{}],[2,'assistant.delta',{text:'Saved partial answer.'}],[3,'task.failed',{message:'Fixture provider stopped unexpectedly.'}]));
      }
      if (mode === 'failed-refresh') { s.completed = true; s.task.status = 'completed'; return stream(route, events([1,'task.started',{}],[2,'assistant.delta',{text:'Verified completion must remain visible.'}],[3,'task.completed',{}])); }
      if (mode === 'replay' || mode === 'terminal-disconnect') {
        if (call === 1) return stream(route, events([1,'task.started',{}],[2,'assistant.delta',{text:'Distinct partial answer.'}]));
        if (call <= 4) return route.abort('failed');
        if (mode === 'replay' && call === 5) { s.recovered = true; return stream(route, events([1,'task.started',{}],[2,'assistant.delta',{text:'Distinct partial answer.'}],[3,'assistant.delta',{text:' Recovered suffix.'}])); }
      }
      await s.streamGate.wait();
      return stream(route, events([99,'task.cancelled',{}]));
    }
    return json(route, { detail: `Unhandled fixture ${method} ${endpoint}` }, 404);
  };
  return s;
}
async function select(page, name) { await page.locator('.grok-inbox-row').filter({ hasText: name }).click(); await page.getByRole('textbox', { name: `Message ${name}`, exact: true }).waitFor(); }
async function send(page) { const box = page.getByRole('textbox', { name: 'Message Alpha', exact: true }); await box.fill('Please perform a harmless fixture check.'); await box.press('Enter'); }
async function run(browser, name, mode, check, report) {
  if (process.env.BOT_RECOVERY_FILTER && !mode.includes(process.env.BOT_RECOVERY_FILTER)) return;
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage(), s = fixture(mode);
  page.setDefaultTimeout(7000);
  await page.route('**/bot/api/**', s.handler);
  try {
    await page.goto(baseURL);
    await page.locator('.grok-inbox-row').first().waitFor();
    await select(page, 'Alpha');
    await check(page, s);
    report.push({ name, passed: true });
  } catch (e) {
    report.push({ name, passed: false, error: e.message });
    await page.screenshot({ path: path.join(out, `${mode}-failed.png`), fullPage: true }).catch(() => {});
  } finally { s.release(); await context.close(); }
}
(async () => {
  const browser = await chromium.launch({ headless: true }), report = [];
  try {
    await run(browser, 'Early Stop cancellation failure stays visible and controllable', 'early-stop', async (page,s) => {
      await send(page); await until(() => s.posts === 1, 'Message POST did not start');
      await page.getByRole('button', { name: 'Stop work', exact: true }).click();
      s.postGate.release(); await until(() => s.cancels > 0, 'Pending Stop did not call cancel');
      await until(async () => /cancellation unavailable|could not stop/i.test(await page.locator('.grok-main').innerText()), 'Cancellation failure is hidden');
      assert(await page.getByRole('button', { name: 'Stop work', exact: true }).isEnabled(), 'Running task lost Stop after cancellation failed');
    }, report);
    await run(browser, 'Reconnect replay does not duplicate streamed text', 'replay', async (page,s) => {
      await send(page);
      await until(async () => (await page.locator('.grok-main').innerText()).includes('Connection lost'), 'Reconnect retries did not exhaust');
      await select(page,'Beta'); await select(page,'Alpha');
      await until(() => s.recovered, 'Reopening did not resume task');
      await until(async () => (await page.locator('.grok-live-task').innerText()).includes('Recovered suffix.'), 'Recovered text not displayed');
      const text = await page.locator('.grok-live-task .grok-message-bubble').innerText();
      assert.equal((text.match(/Distinct partial answer\./g)||[]).length,1,'Replay duplicated old deltas');
    }, report);
    await run(browser, 'Terminal task discovered after disconnect unlocks composer', 'terminal-disconnect', async (page,s) => {
      await send(page);
      await until(async () => (await page.locator('.grok-main').innerText()).includes('Connection lost'), 'Reconnect retries did not exhaust');
      s.task.status='completed';
      s.messages['conversation-alpha'].push({ id:'saved-result', conversation_id:'conversation-alpha', role:'assistant', author_agent_id:'agent-alpha', source_task_id:s.task.id, content:'Durable final answer', created_at:1789632200 });
      await select(page,'Beta'); await select(page,'Alpha');
      await until(async () => await page.getByRole('textbox',{name:'Message Alpha',exact:true}).isEnabled(), 'Completed remote task still blocks composer');
      assert.equal(await page.getByRole('button',{name:'Stop work',exact:true}).count(),0);
      assert(await page.getByText('Durable final answer',{exact:true}).isVisible());
    }, report);
    await run(browser, 'Failed transcript refresh retains completed streamed answer', 'failed-refresh', async (page,s) => {
      await send(page); await page.getByText('Verified completion must remain visible.',{exact:true}).waitFor();
      await until(() => s.historyFailures > 0,'Did not exercise failed history refresh');
      await page.waitForTimeout(3100);
      assert(await page.getByText('Verified completion must remain visible.',{exact:true}).isVisible(),'Completion disappeared before durable history loaded');
    }, report);
    await run(browser, 'Initial home lookup does not override later navigation', 'home-race', async (page,s) => {
      await send(page); await until(() => s.homeCalls>0,'Initial home lookup was not exercised');
      await select(page,'Beta'); s.homeGate.release();
      await until(() => s.posts===1,'Source message did not continue in its own chat');
      await page.waitForTimeout(300);
      assert.equal(await page.locator('.grok-chat-title h1').innerText(),'Beta','Late home lookup stole selection');
      assert(await page.getByRole('textbox',{name:'Message Beta',exact:true}).isEnabled(),'Other chat inherits pending source send state');
    }, report);
    await run(browser, 'Older history can be loaded from the transcript', 'history-page', async (page,s) => {
      await page.getByRole('button',{name:/load earlier|earlier messages/i}).click();
      await until(()=>s.olderRequests>0,'Earlier history did not request a cursor');
      assert(await page.getByText('Archive sentinel from the oldest page.',{exact:true}).isVisible(),'Earlier page not rendered');
    }, report);
    await run(browser, 'Search opens an exact message outside the latest page', 'history-search', async (page,s) => {
      await page.getByRole('textbox',{name:'Search chats',exact:true}).fill('Archive sentinel');
      await page.locator('.grok-search-popover button').filter({hasText:'Alpha archive'}).click();
      await until(async()=>await page.locator('.grok-transcript').getByText('Archive sentinel from the oldest page.',{exact:true}).isVisible(),'Exact old search hit was not inserted or loaded');
    }, report);
    await run(browser, 'Old search hit preserves the contiguous paging cursor', 'history-gap', async (page,s) => {
      await page.getByRole('textbox',{name:'Search chats',exact:true}).fill('Archive sentinel');
      await page.locator('.grok-search-popover button').filter({hasText:'Alpha archive'}).click();
      await until(async()=>await page.locator('.grok-transcript').getByText('Archive sentinel from the oldest page.',{exact:true}).isVisible(),'Old search hit did not load');
      await page.getByRole('button',{name:/load earlier|earlier messages/i}).click();
      await until(()=>s.olderRequests>0,'Earlier history did not request a cursor');
      assert.equal(s.lastBeforeId,'recent-0','Search hit incorrectly became the pagination cursor');
      assert(await page.getByText('Intervening history remains reachable.',{exact:true}).isVisible());
    }, report);
    await run(browser, 'Persisted partial output retains failure feedback without duplicate text', 'partial-failure', async (page,s) => {
      await send(page);
      await page.getByText('Fixture provider stopped unexpectedly.',{exact:true}).waitFor();
      await page.locator('[data-message-id="saved-partial"]').waitFor();
      await page.waitForTimeout(300);
      assert(await page.getByText('Fixture provider stopped unexpectedly.',{exact:true}).isVisible(),'Persisting partial output hid the failure');
      assert.equal(await page.getByText('Saved partial answer.',{exact:true}).count(),1,'Partial output rendered twice');
      assert(await page.getByRole('textbox',{name:'Message Alpha',exact:true}).isEnabled());
    }, report);
    await run(browser, 'Confirmed Stop replaces Stopping with Run stopped', 'stop-label', async (page,s) => {
      await send(page); await until(()=>s.task,'Task was not submitted');
      await page.getByRole('button',{name:'Stop work',exact:true}).click();
      await until(async()=> (await page.locator('.grok-working-line').innerText()).includes('Run stopped'),'Confirmed cancellation did not update the status label');
      assert(!(await page.locator('.grok-working-line').innerText()).includes('Stopping'));
      assert(await page.getByRole('textbox',{name:'Message Alpha',exact:true}).isEnabled());
    }, report);
    await run(browser, 'Terminal polling reconciles a task while its event stream hangs', 'terminal-poll', async (page,s) => {
      await send(page); await until(()=>s.task && s.eventCalls,'Task event stream was not opened');
      s.task.status='cancelled';
      await until(async()=> (await page.locator('.grok-working-line').innerText()).includes('Run stopped'),'Terminal polling did not surface server cancellation',6000);
      assert(await page.getByRole('textbox',{name:'Message Alpha',exact:true}).isEnabled());
    }, report);
    await run(browser, 'Pending desktop start immediately shows Starting computer', 'desktop-start', async (page,s) => {
      await page.getByRole('button',{name:'Toggle details',exact:true}).click();
      await page.getByRole('button',{name:'Start computer',exact:true}).click();
      await until(()=>s.desktopStarts===1,'Desktop start request was not issued');
      assert(await page.getByRole('heading',{name:'Starting computer…',exact:true}).isVisible());
      assert.equal(await page.locator('.grok-desktop-card .grok-status-chip').innerText(),'starting');
      assert(await page.getByRole('button',{name:'Start computer',exact:true}).isDisabled());
      s.postGate.release();
      await page.getByRole('heading',{name:'Computer is ready',exact:true}).waitFor();
    }, report);
  } finally { await browser.close(); }
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({baseURL,fixtureOnly:true,results:report},null,2));
  for (const row of report) console.log(`${row.passed?'PASS':'FAIL'} ${row.name}${row.error?': '+row.error:''}`);
  process.exitCode = report.some(row=>!row.passed)?1:0;
})().catch(e=>{console.error(e);process.exitCode=1;});
