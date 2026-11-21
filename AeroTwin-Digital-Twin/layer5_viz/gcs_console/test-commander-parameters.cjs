// Real 3D asset + mock telemetry: local-only browser regression.
const {buildSync}=require('esbuild');
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const entry=`
import React from 'react';import {createRoot} from 'react-dom/client';
import {CommanderParameters} from './src/pages/detail/CommanderParameters';
const m=(value,state='VALID')=>({value,state,age_s:state==='STALE'?15:0});
const r={rpm:m(0),cht:{spread:1,cyl_1:m(15),cyl_2:m(16),cyl_3:m(15.5),cyl_4:m(90,'INVALID')},egt:{spread:7,cyl_1:m(21),cyl_2:m(23),cyl_3:m(22),cyl_4:m(19)},oil_temperature:m(17),fuel_flow:m(0),manifold_pressure:m(1.01),vibration:{rms_total:.12,spectral_peaks:{BPFO:1.8},dominant_frequency_hz:9.5},electrical:{bus_voltage:m(26.1,'STALE'),alternator_current:m(.1)},timing:{injection_deviation_max:.2,ignition_deviation_max:.2,injector_duty_pct:m(0),knock_retard_deg:m(0)}};
const snap={twin:{reported:r,predicted:{fault_probability:{}},residuals:{},simulated:{outside_manufacturer_data:['Engine below reference speed']}},fusion:{},history:{cht:[15,16,15.5],cht_pred:[75,75,75]}};
const limits={parameters:{cht:{normal_min:80,normal_max:120,alert_max:130,critical_max:135},egt:{normal_max:900,alert_max:930,critical_max:950},oil_temperature:{normal_min:50,normal_max:110,critical_max:130},bus_voltage:{normal_min:24,normal_max:28,critical_max:30}}};
createRoot(document.getElementById('root')).render(<CommanderParameters snap={snap} limits={limits}/>);
`;
const code=buildSync({stdin:{contents:entry,resolveDir:__dirname,loader:'tsx'},jsx:'automatic',bundle:true,platform:'browser',format:'iife',loader:{'.css':'empty'},write:false}).outputFiles[0].text;
const css=['src/theme/tokens.css','src/theme/ui.css','src/ui/engine-view.css','src/pages/detail/commander-parameters.css'].map(f=>fs.readFileSync(path.join(__dirname,f),'utf8')).join('\n');
const assets=new Set(['rotax915is.glb','component_registry.json','fault_component_matrix.json','fault_registry.json']);
const server=http.createServer((req,res)=>{
 const name=(req.url||'').split('/').pop();
 if((req.url||'').startsWith('/engine3d/')&&assets.has(name)){
  const file=path.join(__dirname,'public/engine3d',name);
  res.writeHead(200,{'Content-Length':fs.statSync(file).size,'Content-Type':name.endsWith('.glb')?'model/gltf-binary':'application/json'});
  if(req.method==='HEAD')res.end();else fs.createReadStream(file).pipe(res);return;
 }
 if(req.url==='/app.js'){res.writeHead(200,{'Content-Type':'application/javascript'});res.end(code);return;}
 res.writeHead(200,{'Content-Type':'text/html'});res.end('<style>'+css+'body{padding:16px;box-sizing:border-box}#root{height:calc(100vh - 32px);display:flex}</style><div id="root"></div><script src="/app.js"></script>');
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({channel:'msedge',headless:true,args:['--enable-unsafe-swiftshader']});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1050}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+server.address().port);
  await page.getByRole('button',{name:'EXPLODE VIEW',exact:true}).waitFor({timeout:60000});
  assert.equal(await page.locator('#commander-engine-view canvas').count(),1);
  const original=await page.locator('#commander-engine-view').boundingBox();
  await page.getByRole('button',{name:'Expand engine',exact:true}).click();
  await page.waitForTimeout(250);
  assert.ok((await page.locator('#commander-engine-view').boundingBox()).width>original.width);
  assert.equal(await page.getByRole('button',{name:'Collapse engine',exact:true}).getAttribute('aria-expanded'),'true');
  // The same canvas survives expansion; WebGL state is not recreated.
  await page.evaluate(()=>window.testCanvas=document.querySelector('#commander-engine-view canvas'));
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(()=>window.testCanvas===document.querySelector('#commander-engine-view canvas')),true);
  await page.getByRole('button',{name:'Show on engine',exact:true}).first().click();
  await page.getByRole('button',{name:'Collapse engine',exact:true}).waitFor();
  await page.keyboard.press('Escape');
  assert.ok(await page.getByText('STALE · 15 s old',{exact:true}).isVisible());
  const cylinder4=page.locator('.commander-cylinder-card').filter({hasText:'Cylinder 4'});
  assert.ok(await cylinder4.getByText(/^INVALID/).isVisible());
  assert.equal(await cylinder4.locator('.engine-metric-value').first().innerText(),'— °C');
  await page.getByRole('button',{name:'View more +',exact:true}).click();
  await page.locator('#parameter-technical-details').waitFor();
  assert.ok(await page.getByText('Outside manufacturer data: Engine below reference speed',{exact:true}).isVisible());
  fs.mkdirSync(path.join(__dirname,'shots'),{recursive:true});
  await page.screenshot({path:path.join(__dirname,'shots/commander-parameters-wide.png'),fullPage:true});
  for(const width of [1100,768,512]){
   await page.setViewportSize({width,height:900});
   await page.waitForTimeout(150);
   assert.ok(await page.locator('.commander-parameter-grid').evaluate(e=>e.scrollWidth<=e.clientWidth+1),'Overflow at '+width);
   await page.getByRole('button',{name:'Expand engine',exact:true}).click();
   await page.waitForTimeout(150);
   assert.ok(await page.locator('#commander-engine-view canvas').evaluate(e=>Math.abs(e.getBoundingClientRect().width-e.parentElement.clientWidth)<2));
   await page.keyboard.press('Escape');
  }
  await page.screenshot({path:path.join(__dirname,'shots/commander-parameters-narrow.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: real engine GLB loads, expand/collapse preserves canvas, cylinder focus, stale/invalid readings, technical disclosure and responsive resize.');
 }finally{await browser.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);server.closeAllConnections();server.close();process.exitCode=1});
