// Component smoke check, not browser layout QA. Node's native VM needs no npm packages.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const report=JSON.parse(fs.readFileSync(path.join(root,'artifacts/dashboard.json'),'utf8'));
class Element {
  constructor(id){this.id=id;this.innerHTML='';this.textContent='';this.value='';this.disabled=false;this.hidden=true;this.dataset={};this.classes=new Set();this.classList={add:x=>this.classes.add(x),remove:x=>this.classes.delete(x)};}
}
const ids=['crumb','page-title','page-subtitle','overview','model','copilot','open-copilot','dpd30','dpd60','trend','asof','stats','regions','quality','roll-month','roll','model-stats','champion','splits','calibration','queue','ask','answer','answer-mode','question','mode','error'];
const elements=Object.fromEntries(ids.map(id=>[id,new Element(id)]));
elements.question.value='What changed in portfolio delinquency this month?';elements.mode.value='offline';elements.mode.options=[{},{}];
const navs=['overview','model','copilot'].map(tab=>{let e=new Element('nav-'+tab);e.dataset.tab=tab;return e});
const document={getElementById:id=>elements[id],querySelector:selector=>navs.find(n=>selector.includes(n.dataset.tab)),querySelectorAll:selector=>selector==='.nav'?navs:selector==='.tab,.nav'?[...navs,elements.overview,elements.model,elements.copilot]:[]};
let requests=[];
const fetch=async(url,opts)=>{requests.push(url);if(url==='/api/dashboard')return {ok:true,json:async()=>report};if(url==='/api/config')return {ok:true,json:async()=>({openai_available:false})};return {ok:true,json:async()=>({status:'answered',mode:'offline_evidence_template',summary:'Source-backed portfolio evidence.',evidence:[report.evidence[0]],limitations:['Synthetic only.'],elapsed_ms:1})};};
const context=vm.createContext({document,fetch,Intl,Date,Error,console});
vm.runInContext(fs.readFileSync(path.join(root,'web/app.js'),'utf8'),context);
(async()=>{
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(elements.stats.innerHTML,/\$53\.75M/);
  assert.match(elements.stats.innerHTML,/3,466/);
  assert.match(elements.stats.innerHTML,/28\.05%/);
  assert.match(elements.regions.innerHTML,/South/);
  assert.match(elements.roll.innerHTML,/table/);
  assert.match(elements.queue.innerHTML,/SYN-/);
  assert.match(elements.trend.innerHTML,/svg/);
  elements.dpd60.onclick();assert.match(elements.trend.innerHTML,/11\.10%/);
  navs[1].onclick();assert.equal(elements['page-title'].textContent,'Measure what the model can prove.');
  navs[2].onclick();await elements.ask.onclick();
  assert.match(elements.answer.innerHTML,/F-PORTFOLIO/);
  assert.equal(elements['answer-mode'].textContent,'OFFLINE TEMPLATE');
  assert.equal(elements.ask.disabled,false);
  console.log(JSON.stringify({ui_component_smoke:'passed',api_requests:requests.length,scope:'DOM component logic only; no browser layout validation'}));
})().catch(e=>{console.error(e);process.exit(1)});
