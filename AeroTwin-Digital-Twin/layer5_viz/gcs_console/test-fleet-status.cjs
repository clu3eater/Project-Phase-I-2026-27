// node test-fleet-status.cjs
// Optional: set PLAYWRIGHT_MODULE to a Playwright installation and add --browser.
const {buildSync} = require('esbuild');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const entry = `
import React from 'react';
import {FleetStatusDashboard} from './src/pages/home/FleetStatusDashboard';
import {FleetHome} from './src/pages/home/Fleet';
import {OpsProvider} from './src/lib/ops';
export const aircraft = {
 tail:'MALE-01',twin_id:'TEST-001',engine_name:'Test engine',engine_validated:false,on_gcs:true,
 status:'AWAITING INSPECTION',status_detail:'Inspect and sign release',released:false,
 grounding:[],open_defects:[],defects:[],pending_maintenance:[],limitations:{},mission:null,
 sorties:1,ground_runs:2,
 health:{chi:.97,band:'EXCELLENT',engine_hours:.8,hours_since_inspection:.8,tbo_hours:1800,
 tbo_remaining_hours:1799,assessed_utc:'2026-10-22T08:00:00Z',
 subsystems:{thermal:.94,mechanical:.98,combustion:.96,electrical:.99}}
};
export const second={...aircraft,tail:'MALE-02',health:{},sorties:0,ground_runs:0};
export function dashboard(a=aircraft,interval=100) {return <FleetStatusDashboard a={a} interval={interval}/>;}
export function fleet(){return <OpsProvider><FleetHome mode='command'/></OpsProvider>;}
globalThis.fetch=async url=>({ok:true,json:async()=>String(url).endsWith('/board')
 ? {aircraft:[aircraft,second],unit:'UI test squadron',inspection_interval_h:100}
 : String(url).endsWith('/MALE-02') ? second : aircraft});
`;
const opts={bundle:true,write:false,loader:{'.css':'empty'},logLevel:'silent'};
const node=buildSync({...opts,stdin:{contents:entry+`
import {renderToStaticMarkup} from 'react-dom/server';
import assert from 'node:assert/strict';
let html=renderToStaticMarkup(dashboard());
assert.ok(html.includes('99.2 h remaining'));
assert.ok(html.includes('1,799 h remaining'));
assert.ok(html.includes('Thermal health 94.0 percent'));
assert.ok(html.includes('Sorties: 1, Ground runs: 2'));
assert.ok(html.includes('Health assessed'));
assert.ok(html.includes('Awaiting release'));
assert.ok(html.includes('No recorded limitations'));
assert.ok(html.includes('Not allotted'));
assert.ok(!html.includes('NaN'));
html=renderToStaticMarkup(dashboard(second));
assert.ok(html.includes('Not assessed'));
assert.ok(html.includes('No completed runs'));
assert.ok(html.includes('Progress unavailable'));
assert.ok(!html.includes('health 0.0 percent'));
html=renderToStaticMarkup(dashboard({...aircraft,health:{...aircraft.health,hours_since_inspection:108,tbo_remaining_hours:0}}));
assert.ok(html.includes('8 h overdue'));
assert.ok(html.includes('Due now'));
html=renderToStaticMarkup(dashboard({...aircraft,health:{chi:NaN,tbo_hours:0,subsystems:{thermal:1.5}}},0));
assert.ok(!html.includes('NaN'));
assert.ok(!html.includes('Infinity'));
assert.ok(html.includes('Thermal health not assessed'));
console.log('PASS: saved assessments, maintenance arithmetic, missing health, overdue inspection, overhaul due and invalid data.');
`,resolveDir:__dirname,sourcefile:'fleet-status-regression.tsx',loader:'tsx'},platform:'node',format:'esm',banner:{js:`import {createRequire} from 'node:module';const require=createRequire(${JSON.stringify(__filename)});`}});
(async()=>{
 await import('data:text/javascript;base64,'+Buffer.from(node.outputFiles[0].text).toString('base64'));
 if(!process.argv.includes('--browser'))return;
 const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
 const code=buildSync({...opts,stdin:{contents:entry+`
import {createRoot} from 'react-dom/client';
createRoot(document.getElementById('root')).render(fleet());
`,resolveDir:__dirname,sourcefile:'fleet-status-browser.tsx',loader:'tsx'},platform:'browser',format:'iife'}).outputFiles[0].text;
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1150}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const css=['src/theme/tokens.css','src/theme/ui.css','src/pages/home/fleet-status.css'].map(f=>fs.readFileSync(path.join(__dirname,f),'utf8')).join('\n');
  await page.setContent('<html data-ambient="day"><head><style>'+css+'body{margin:0;padding:16px;overflow:auto;height:auto}#root{height:1400px}</style></head><body><div id="root"></div></body></html>');
  await page.addScriptTag({content:code});
  const dashboard=page.getByRole('generic',{name:'MALE-01 status dashboard'});
  await page.locator('[aria-label="MALE-01 status dashboard"]').waitFor();
  await page.getByText('99.2 h remaining',{exact:true}).waitFor();
  assert.equal(await page.locator('.fleet-status-grid').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length),2);
  fs.mkdirSync(path.join(__dirname,'shots'),{recursive:true});
  await page.screenshot({path:path.join(__dirname,'shots/fleet-status-day.png'),fullPage:true});
  await page.evaluate(()=>document.documentElement.removeAttribute('data-ambient'));
  await page.locator('.fleet-status-dashboard').screenshot({path:path.join(__dirname,'shots/fleet-status-night.png')});
  await page.setViewportSize({width:1100,height:1150});
  assert.equal(await page.locator('.fleet-status-grid').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length),2);
  await page.setViewportSize({width:640,height:800});
  assert.equal(await page.locator('.fleet-status-grid').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length),1);
  assert.ok(await page.locator('.fleet-status-dashboard').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  await page.locator('.fleet-status-dashboard').screenshot({path:path.join(__dirname,'shots/fleet-status-narrow.png')});
  await page.getByRole('tab',{name:'Defects',exact:true}).click();
  await page.getByText('No open defects.',{exact:true}).waitFor();
  assert.equal(await page.locator('.fleet-status-dashboard').count(),0);
  await page.getByRole('tab',{name:'Status',exact:true}).click();
  await page.locator('.list-item').filter({hasText:'MALE-02'}).click();
  await page.locator('[aria-label="MALE-02 status dashboard"]').waitFor();
  assert.equal(await page.getByRole('img',{name:'Thermal health not assessed',exact:true}).count(),1);
  assert.equal(await page.getByText('99.2 h remaining',{exact:true}).count(),0);
  await page.getByRole('button',{name:'Engine change',exact:true}).click();
  await page.getByRole('dialog').waitFor();
  assert.deepEqual(errors,[]);
  console.log('PASS: Edge day/night rendering, responsive cards, selected aircraft isolation, tabs and engine change drawer.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
