// Local browser regression for commander planning; no live station is changed.
const {buildSync}=require('esbuild');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const contents=`
import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import {PlanDrawer,AllotDrawer} from './src/pages/home/MissionPlanning';
const board={mission_types:{TRAINING:{label:'Training sortie',duration_h:2,altitude_ft:8000,throttle_pct:65,environment:'STANDARD'},ISR:{label:'ISR patrol',duration_h:10,altitude_ft:18000,throttle_pct:72,environment:'STANDARD'}},environments:['STANDARD','HOT_WEATHER'],operators:['op.rao'],simulated_cruise_hours:.1,aircraft:[{tail:'MALE-01',twin_id:'SERIAL-001'},{tail:'MALE-02',twin_id:'SERIAL-002'}]};
window.mutations=[];
window.candidates=[{tail:'MALE-01',engine:'Rotax 915 iS',engine_validated:true,eligible:true,recommended:true,problems:[],health:{},assessment:{verdict:'NOT_ASSESSED',success_probability:null,reasons:['No warm loaded run recorded']}},{tail:'MALE-02',engine:'Diesel placeholder',engine_validated:false,eligible:false,problems:['Inspection due'],health:{chi:.8},assessment:{verdict:'NO_GO',success_probability:.25,reasons:['Engine life insufficient'],recommendations:['Shorten mission']}}];
window.fetch=async (url,init)=>{
 if(!init?.method)return {ok:true,json:async()=>window.candidates};
 const payload=JSON.parse(init.body);window.mutations.push({url,payload});
 if(String(url).endsWith('/approve')&&window.mutations.filter(x=>x.url.endsWith('/approve')).length===1)return {ok:false,status:409,text:async()=>JSON.stringify({detail:'Aircraft release changed; refresh assessment'})};
 return {ok:true,text:async()=>JSON.stringify({id:'MSN-TEST',status:'PLANNED',...payload})};
};
function Harness(){const [m,setM]=useState(null);const [done,setDone]=useState('');return <main style={{height:'100vh',position:'relative'}}>{done?<p>{done}</p>:m?<AllotDrawer m={m} board={board} onClose={()=>{}} onDone={setDone}/>:<PlanDrawer board={board} onClose={()=>{}} onPlanned={setM}/>}</main>}
createRoot(document.getElementById('root')).render(<Harness/>);
`;
const code=buildSync({stdin:{contents,resolveDir:__dirname,loader:'tsx'},bundle:true,platform:'browser',format:'iife',jsx:'automatic',loader:{'.css':'empty'},write:false}).outputFiles[0].text;
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const css=['src/theme/tokens.css','src/theme/ui.css','src/pages/home/mission-planning.css'].map(p=>fs.readFileSync(path.join(__dirname,p),'utf8')).join('\n');
  await page.setContent('<style>'+css+'</style><div id="root"></div>');await page.addScriptTag({content:code});
  await page.getByLabel(/^Planned endurance/).fill('0');
  assert.equal(await page.getByRole('button',{name:'Review mission',exact:true}).isDisabled(),true);
  await page.getByLabel(/^Mission task/).selectOption('ISR');
  assert.equal(await page.getByLabel(/^Planned endurance/).inputValue(),'10');
  await page.getByLabel(/^Mission name/).fill('Northern patrol');
  await page.getByRole('button',{name:'Review mission',exact:true}).click();
  assert.equal(await page.evaluate(()=>window.mutations.length),0);
  await page.getByRole('button',{name:'Edit profile',exact:true}).click();
  assert.equal(await page.getByLabel(/^Mission name/).inputValue(),'Northern patrol');
  await page.getByRole('button',{name:'Review mission',exact:true}).click();
  await page.getByRole('button',{name:'Save and compare aircraft',exact:true}).click();
  await page.getByRole('radio',{name:'Select MALE-01',exact:true}).waitFor();
  assert.equal(await page.getByRole('radio',{name:'Select MALE-01',exact:true}).isChecked(),false);
  assert.equal(await page.getByRole('radio',{name:'Select MALE-02',exact:true}).isDisabled(),true);
  assert.equal(await page.getByRole('button',{name:'Review assignment',exact:true}).isDisabled(),true);
  assert.ok(await page.getByText('Inspection due',{exact:true}).isVisible());
  assert.ok(await page.getByText('Engine life insufficient',{exact:true}).isVisible());
  fs.mkdirSync(path.join(__dirname,'shots'),{recursive:true});
  await page.screenshot({path:path.join(__dirname,'shots/mission-aircraft-comparison.png'),fullPage:true});
  await page.getByRole('radio',{name:'Select MALE-01',exact:true}).check();
  await page.getByLabel(/^Assign operator/).selectOption('op.rao');
  await page.getByRole('button',{name:'Review assignment',exact:true}).click();
  assert.ok(await page.getByText('Engine suitability is unknown.',{exact:false}).isVisible());
  assert.equal(await page.evaluate(()=>window.mutations.length),1);
  await page.setViewportSize({width:512,height:800});
  assert.ok(await page.locator('.drawer').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  fs.mkdirSync(path.join(__dirname,'shots'),{recursive:true});
  await page.screenshot({path:path.join(__dirname,'shots/mission-review-narrow.png'),fullPage:true});
  await page.getByRole('button',{name:'Approve assignment',exact:true}).click();
  await page.getByText('Aircraft release changed; refresh assessment',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Refresh assessment',exact:true}).click();
  await page.getByRole('radio',{name:'Select MALE-01',exact:true}).waitFor();
  await page.getByRole('button',{name:'Review assignment',exact:true}).click();
  await page.getByRole('button',{name:'Approve assignment',exact:true}).click();
  await page.getByText('Operator preflight and launch clearance are still required.',{exact:false}).waitFor();
  const mutations=await page.evaluate(()=>window.mutations);
  assert.equal(mutations.length,3);
  assert.equal(mutations[0].payload.duration_h,10);
  assert.equal(mutations[0].payload.altitude_ft,18000);
  assert.equal(mutations[1].payload.tail,'MALE-01');
  assert.equal(mutations[1].payload.operator,'op.rao');
  assert.deepEqual(errors,[]);
  console.log('PASS: numeric validation, preset changes, draft review, explicit aircraft/operator selection, blocked and unknown assessments, server rejection, refresh/retry, and narrow layout.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
