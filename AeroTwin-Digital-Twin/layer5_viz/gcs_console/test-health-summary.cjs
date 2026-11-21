// Run with PLAYWRIGHT_MODULE pointing to the local Playwright installation.
const {buildSync}=require('esbuild');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const code=buildSync({stdin:{resolveDir:__dirname,loader:'tsx',contents:`
import React,{useState} from 'react';import {createRoot} from 'react-dom/client';
import {HealthPage} from './src/pages/detail/Health';
const snap={health:{chi:.975,band:'EXCELLENT',thermal:.983,mechanical:.995,electrical:.985,combustion:.928,assessment:{state:'held',age_s:120,reason:'Engine stopped'}},history:{chi:[.99,.987,.985,.981,.978,.975]},trend:{onset_hours:null,cusum:.02,chi_ema:.975},twin:{reported:{},predicted:{},metadata:{}},efficiency:{},battery:{}};
const limits={chi_bands:[{min:.9,label:'Excellent',instruction:'No action required.'},{min:0,label:'Low',instruction:'Review condition.'}],composite_weights:{thermal:.3,mechanical:.25,electrical:.15,combustion:.3}};
function App(){const [unknown,setUnknown]=useState(false);return <><button onClick={()=>setUnknown(v=>!v)}>Toggle assessment</button><HealthPage commander snap={unknown?{...snap,health:{...snap.health,chi:null,assessment:{state:'assessing',age_s:null,reason:'Waiting for warm engine'}}}:snap} limits={limits}/></>}
createRoot(document.getElementById('root')).render(<App/>);
`},bundle:true,jsx:'automatic',platform:'browser',format:'iife',loader:{'.css':'empty'},write:false}).outputFiles[0].text;
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const css=['src/theme/tokens.css','src/theme/ui.css','src/ui/engine-view.css','src/pages/detail/health-summary.css'].map(p=>fs.readFileSync(path.join(__dirname,p),'utf8')).join('\n');
  await page.setContent('<style>'+css+'body{padding:16px;box-sizing:border-box}#root{height:100%}</style><div id="root"></div>');
  await page.addScriptTag({content:code});
  const more=page.getByRole('button',{name:'View more +',exact:true});await more.waitFor();
  assert.equal(await more.getAttribute('aria-expanded'),'false');
  assert.equal(await page.locator('#health-score-details').count(),0);
  assert.equal(await page.getByText('CUSUM',{exact:true}).count(),0);
  assert.ok(await page.getByText('Held from last warm running, 2 min ago',{exact:true}).isVisible());
  assert.equal(await page.getByRole('img',{name:'Combustion health 92.8 percent',exact:true}).count(),1);
  await more.click();
  await page.locator('#health-score-details').waitFor();
  assert.ok(await page.getByText('CUSUM',{exact:true}).isVisible());
  await page.getByRole('button',{name:'View less −',exact:true}).click();
  assert.equal(await page.locator('#health-score-details').count(),0);
  fs.mkdirSync(path.join(__dirname,'shots'),{recursive:true});
  await page.screenshot({path:path.join(__dirname,'shots/health-summary-wide.png'),fullPage:true});
  for(const width of [1024,768,512]){
   await page.setViewportSize({width,height:900});
   assert.ok(await page.locator('.health-system-cards').evaluate(e=>e.scrollWidth<=e.clientWidth+1),'Overflow at '+width);
  }
  await page.screenshot({path:path.join(__dirname,'shots/health-summary-narrow.png'),fullPage:true});
  await page.getByRole('button',{name:'Toggle assessment',exact:true}).click();
  await page.getByText('Not assessed yet',{exact:true}).waitFor();
  assert.equal(await page.getByRole('img',{name:'Combustion health not assessed',exact:true}).count(),1);
  assert.equal(await page.getByRole('img',{name:'Combustion health 92.8 percent',exact:true}).count(),0);
  assert.deepEqual(errors,[]);
  console.log('PASS: commander summary, held/unknown assessments, accessible disclosure, technical details preserved, and responsive cards.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
