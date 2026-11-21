// Run: node test-overview.cjs (from this directory).
const {buildSync} = require('esbuild');
const entry = `
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {login, logout} from './src/lib/api';
import {OverviewPage} from './src/pages/Overview';
import assert from 'node:assert/strict';
let loginResponse;
globalThis.fetch = async () => ({ok:true,status:200,json:async()=>loginResponse});
const marker = {authorised:false,scope:'read:prognostics'};
const base = {twin:{metadata:{engine_key:'rotax_915is'},reported:{},alerts:{active:[]}},history:{},health:{},fusion:{},display:{},mission:{},maintenance:marker,rul:marker,survival:marker};
const roles = {
  ROLE_OPERATOR: ['read:telemetry','read:health','read:alerts','read:mission'],
  ROLE_ENGINEER: ['read:telemetry','read:health','read:alerts','read:prognostics'],
  ROLE_MAINTENANCE: ['read:telemetry','read:health','read:alerts','read:prognostics','read:advisory'],
  ROLE_COMMANDER: ['*'],
};
for (const [role, scopes] of Object.entries(roles)) {
 loginResponse = {access_token:'test',role,scopes};
 await login('test-' + role.toLowerCase(),'disposable');
 for (const forecasts of [marker, undefined, null, []]) {
  const html = renderToStaticMarkup(React.createElement(OverviewPage,{
   aircraft:null,airborne:false,snap:{...base,fault_forecast:forecasts},
   canGo:p=>p==='ENGINE',go(){}
  }));
  assert.ok(html.includes('Current engine readings'),role + ': shared readings panel');
  assert.ok(html.includes('engine-overview-metrics'),role + ': shared responsive card styling');
  assert.ok(html.includes('View parameters'),role + ': clear parameters navigation');
  if (!scopes.includes('*') && !scopes.includes('read:prognostics'))
   assert.ok(!html.includes('Faults needing action'),role + ': prognostics remain scoped');
 }
}
loginResponse = {access_token:'test',role:'ROLE_ENGINEER',scopes:roles.ROLE_ENGINEER};
await login('test-engineer','disposable');
const html = renderToStaticMarkup(React.createElement(OverviewPage,{
 aircraft:null,airborne:false,
 snap:{...base,fault_forecast:[{mode:'test_fault',reportable:true,hours_to_action:10}]},
 go(){}
}));
assert.ok(html.includes('10 h'));
logout();
console.log('PASS: redacted, missing, null, empty and authorised forecast rendering.');
`;
const out = buildSync({stdin:{contents:entry,resolveDir:__dirname,sourcefile:'regression.tsx',loader:'tsx'},bundle:true,loader:{'.css':'empty'},platform:'node',format:'esm',banner:{js:"import {createRequire} from 'node:module'; const require = createRequire(" + JSON.stringify(__filename) + ");"},write:false});
import('data:text/javascript;base64,' + Buffer.from(out.outputFiles[0].text).toString('base64')).catch(e=>{console.error(e.message);process.exitCode=1;});
