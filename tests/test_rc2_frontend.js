const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/static/app.js', 'utf8');
const cardSource = source.slice(source.indexOf('function benchmarkTrackCard('), source.indexOf('async function renderBenchmark('));
const context = {escapeHtml: String, fmt: String};
vm.createContext(context);
vm.runInContext(cardSource, context);
for (const track of ['物理','历史']) {
  const codes = ['chinese','math','english', track === '物理' ? 'physics' : 'history','chemistry','biology','politics','geography'];
  const subjects = [...codes].reverse().map((code,index) => ({code,name:code,average:10+index}));
  const data = {exam:{exam_key:'test'},tracks:{[track]:{grade_averages:{subjects,total:555},subject_lines:subjects.map(item=>({code:item.code,lines:{'特控':item.average+100}})),total_lines:{'特控':500}}}};
  const before = JSON.stringify(data);
  for (const mode of ['averages','lines']) {
    const html = context.benchmarkTrackCard(data, track, mode);
    const positions = codes.map(code=>html.indexOf(`<th>${code}</th>`));
    assert.ok(positions.every((position,index)=>position>=0 && (!index || position>positions[index-1])));
    for (const subject of subjects) {
      assert.ok(html.includes(mode === 'averages' ? `>${subject.average}</td>` : `name="subject:${subject.code}:特控" value="${subject.average+100}"`));
    }
  }
  assert.equal(JSON.stringify(data),before);
}
assert.ok(source.includes('kind === "line_bands" ? escapeHtml(band.display_label) : `分数段${index+1}`'));
assert.ok(source.includes('分数区间</th>${cells(band=>escapeHtml(band.label))}'));
assert.ok(source.includes('人数</th>${cells(band=>fmtInt(band.count))}'));
assert.ok(source.includes('占比</th>${cells(band=>pct(band.rate))}'));
console.log('RC2 frontend: both subject orders/values, line-band headers and original data fields passed');
