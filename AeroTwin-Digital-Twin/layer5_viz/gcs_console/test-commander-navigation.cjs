// Run with PLAYWRIGHT_MODULE pointing to a Playwright installation.
const { buildSync } = require('esbuild');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
// Reuse the saved-aircraft fixtures from the Fleet regression.
const fixture = fs.readFileSync(path.join(__dirname, 'test-fleet-status.cjs'), 'utf8')
  .match(/const entry = `([\s\S]*?)`;/)[1]
  .replace("unit:'UI test squadron',inspection_interval_h:100", "unit:'UI test squadron',inspection_interval_h:100,missions:[],mission_types:{},tasks:[]");
const contents = fixture + `
import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {OperationsHome} from './src/pages/home/Operations';
import {OverviewPage} from './src/pages/Overview';
import {login} from './src/lib/api';
const originalFetch=globalThis.fetch;
globalThis.fetch=async url=>String(url).endsWith('/auth/login') ?
 {ok:true,json:async()=>({access_token:'test',role:'ROLE_COMMANDER',scopes:['read:health','read:telemetry','read:alerts','read:mission','read:prognostics']})} : originalFetch(url);
const metric=value=>({value,state:'VALID'});
const snapshot={twin:{reported:{coolant_temperature:metric(85),oil_temperature:metric(90),fuel_flow:metric(18),manifold_pressure:metric(1.2),vibration:{rms_total:.2},electrical:{bus_voltage:metric(26)}},alerts:{active:[]}},history:{},health:{thermal:.98,mechanical:.97,electrical:.99,combustion:.95},fusion:{},display:{chi:.975,band:'EXCELLENT',instruction:'No action required.'},mission:{},maintenance:{},rul:{},survival:{}};
function Harness() {
 const [focus,setFocus]=useState(null);
 return <OpsProvider>{focus === 'dashboard' ? <OverviewPage commander snap={snapshot} go={()=>{}}/> : focus ? <><button onClick={()=>setFocus(null)}>Back to Operations</button>
  <FleetHome mode="command" focus={focus}/></> :
  <><button onClick={()=>setFocus('dashboard')}>Engine dashboard</button><OperationsHome go={()=>{}} onAircraft={tail=>setFocus({tail,n:Date.now()})}/></>}</OpsProvider>;
}
login('commander','fixture').then(()=>createRoot(document.getElementById('root')).render(<Harness/>));
`;
const code = buildSync({ stdin: {contents, resolveDir: __dirname, loader: 'tsx'},
  bundle: true, platform: 'browser', format: 'iife', jsx: 'automatic',
  loader: {'.css':'empty'}, write: false }).outputFiles[0].text;
(async () => {
 const browser = await chromium.launch({channel:'msedge',headless:true});
 try {
  const page = await browser.newPage();
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  const css=['src/theme/tokens.css','src/theme/ui.css','src/ui/engine-view.css','src/pages/home/fleet-status.css']
    .map(p=>fs.readFileSync(path.join(__dirname,p),'utf8')).join('\n');
  for (const width of [1536,1024,768,512]) {
   await page.setViewportSize({width,height:800});
   await page.setContent('<style>'+css+'body{padding:12px;box-sizing:border-box}#root{height:100%}</style><div id="root"></div>');
   await page.addScriptTag({content:code});
   await page.getByRole('button',{name:'View Test engine engine details for MALE-02'}).click();
   await page.locator('[aria-label="MALE-02 status dashboard"]').waitFor();
   assert.equal(await page.locator('.list-item[aria-current="true"]').innerText().then(t=>t.includes('MALE-02')),true);
   assert.equal(await page.locator('[aria-label="MALE-01 status dashboard"]').count(),0);
   assert.ok(await page.locator('.fleet-master-detail').evaluate(e=>e.scrollWidth<=e.clientWidth+1), 'Fleet overflow at '+width);
   if (width <= 1200) assert.equal(await page.locator('.fleet-master-detail').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length),1);
   await page.getByRole('button',{name:'Back to Operations'}).click();
   await page.getByRole('button',{name:'View Test engine engine details for MALE-01'}).click();
   await page.locator('[aria-label="MALE-01 status dashboard"]').waitFor();
   await page.getByRole('button',{name:'Back to Operations'}).click();
   await page.getByRole('button',{name:'Engine dashboard',exact:true}).click();
   await page.locator('.overview-dashboard').waitFor();
   assert.equal(await page.locator('.engine-overview-metrics').first().locator('.engine-metric-card').count(),6);
   assert.equal(await page.locator('.engine-metric-value').first().evaluate(e=>getComputedStyle(e).fontSize),'32px');
   assert.equal(await page.locator('.overview-dashboard').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length),width>1200?3:width>650?2:1);
   assert.ok(await page.locator('.overview-dashboard').evaluate(e=>e.scrollWidth<=e.clientWidth+1),'Dashboard overflow at '+width);
   if(width===1536){fs.mkdirSync(path.join(__dirname,'shots'),{recursive:true});await page.screenshot({path:path.join(__dirname,'shots/engine-dashboard-consistent.png'),fullPage:true});}
  }
  assert.deepEqual(errors,[]);
  console.log('PASS: engine links select the correct aircraft; Fleet and dashboard reflow at 1536, 1024, 768 and 512 CSS pixels.');
 } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
