const { chromium } = require('C:/Users/Work/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const out = path.resolve(__dirname, '../../design-research/grok-20260917');
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="root"></div><script type="module">
import '/bot/@vite/client';
import RefreshRuntime from '/bot/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window);window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>(type)=>type;window.__vite_plugin_react_preamble_installed__=true;
const React=(await import('/bot/node_modules/.vite/deps/react.js')).default;
const {createRoot}=(await import('/bot/node_modules/.vite/deps/react-dom_client.js')).default;
await import('/bot/src/styles.css');
const {AgentAvatar}=await import('/bot/src/components/BotIdentity.tsx');
const {ImageGenerationCard}=await import('/bot/src/components/ImageGeneration.tsx');
const agent={id:'motion',name:'Chief',avatar:'blob',color:'#ff3347'};
const root=createRoot(document.getElementById('root'));
window.showMotion=(status='working',imageStatus='generating')=>root.render(React.createElement('main',{style:{padding:40,display:'flex',gap:50,alignItems:'start',height:700,background:'white'}},React.createElement(AgentAvatar,{agent,status,size:'large',statusLabel:'Chief is working'}),React.createElement(ImageGenerationCard,{state:{status:imageStatus,prompt:'A quiet garden at sunrise',aspectRatio:'1:1'}})));
window.showMotion();
</script></body></html>`;
(async()=>{
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:650,height:450}});
 const checks=[];page.setDefaultTimeout(8000);page.on('pageerror',e=>console.error(e.message));
 try {
  await page.route('http://127.0.0.1:5173/bot/motion-fixture',r=>r.fulfill({contentType:'text/html',body:html}));
  await page.goto('http://127.0.0.1:5173/bot/motion-fixture');
  await page.locator('.image-generation-surface').waitFor();
  const sample=()=>page.evaluate(()=>({body:getComputedStyle(document.querySelector('.bot-glyph')).transform,eye:getComputedStyle(document.querySelector('.bot-eyes')).fill,spot:document.querySelector('.image-generation-surface').style.getPropertyValue('--spot-x')}));
  const first=await sample();await page.waitForTimeout(550);const second=await sample();
  assert.notEqual(first.body,second.body);assert.notEqual(first.spot,second.spot);assert.equal(second.eye,'rgb(23, 32, 35)');checks.push('Active avatar and local image spotlight move; eyes match dark reference');
  await page.screenshot({path:path.join(out,'motion-reference.png')});
  await page.emulateMedia({reducedMotion:'reduce'});await page.waitForTimeout(100);
  const still=await sample();await page.waitForTimeout(350);const stillAfter=await sample();
  assert.equal(still.body,'none');assert.equal(still.spot,stillAfter.spot);checks.push('Reduced motion stops avatar and image movement');
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.evaluate(()=>window.showMotion('idle','cancelled'));await page.waitForTimeout(100);
  assert.equal(await page.locator('.image-generation-pending').count(),0);
  assert.equal(await page.locator('.bot-glyph').evaluate(el=>getComputedStyle(el).animationName),'none');checks.push('Idle avatar is still; cancelled generation removes the animated surface');
  await page.evaluate(()=>window.showMotion('working'));await page.waitForTimeout(100);
  await page.locator('main').evaluate(el=>el.style.marginTop='1000px');await page.waitForTimeout(150);
  assert.equal(await page.locator('.agent-avatar').getAttribute('data-motion'),'paused');checks.push('Offscreen avatar pauses');
  fs.writeFileSync(path.join(out,'motion-verification.json'),JSON.stringify({source:'actual React components in Chromium fixture',checks},null,2));
  console.log(JSON.stringify(checks));
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
