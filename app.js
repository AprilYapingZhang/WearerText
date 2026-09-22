'use strict';
(() => {
  const data = window.WEARERTEXT_DATA;
  const config = window.WEARERTEXT_CONFIG;
  const $ = id => document.getElementById(id);
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const text = (id, value) => { $(id).textContent = value; };
  document.querySelectorAll('[data-repo]').forEach(a => { a.href = config.repository; });
  document.querySelectorAll('[data-dataset]').forEach(a => { a.href = `https://huggingface.co/datasets/${config.dataset}`; });
  $('authors').innerHTML = data.authors.map(a => `<span class="author"><a href="https://orcid.org/${escape(a.orcid)}">${escape(a.name)}</a><sup>${escape(a.affiliations)}${a.corresponding ? '†' : ''}</sup></span>`).join(' ');
  text('abstract-text', data.abstract);
  const levels = ['Text Perception', 'Contextual Understanding', 'Wearer-Grounded Reasoning'];
  $('task-grid').innerHTML = levels.map((name, index) => {
    const tasks = data.tasks.filter(t => t.id.startsWith(`L${index + 1}`));
    return `<article class="task-level l${index + 1}"><h3><small>Level ${index + 1}</small>${name}</h3>` + tasks.map(t => `<details><summary><span class="task-id">${escape(t.id)}</span> ${escape(t.name)}</summary><p>${escape(t.definition)}</p><blockquote>${escape(t.example)}</blockquote></details>`).join('') + '</article>';
  }).join('');
  const ids = data.tasks.map(t => t.id);
  $('results-head').innerHTML = '<tr><th class="model-col" rowspan="2" scope="col">Model</th><th colspan="2" scope="colgroup">L1 · Perception</th><th colspan="5" scope="colgroup">L2 · Understanding</th><th colspan="6" scope="colgroup">L3 · Wearer-Grounded Reasoning</th><th class="overall" rowspan="2" scope="col">Overall</th></tr><tr>' + data.tasks.map(t => `<th scope="col" title="${escape(t.name)}">${t.id}<br><small>${escape(t.name.match(/\(([^)]+)\)/)[1])}</small></th>`).join('') + '</tr>';
  const best = Object.fromEntries(ids.map(id => [id, Math.max(...data.leaderboard.map(r => r.scores[id]))]));
  best.overall = Math.max(...data.leaderboard.map(r => r.overall));
  function renderResults() {
    let rows = data.leaderboard.filter(r => $('model-family').value === 'all' || r.group === $('model-family').value);
    if ($('model-sort').value === 'score') rows = [...rows].sort((a, b) => b.overall - a.overall);
    $('results-body').innerHTML = rows.map(r => {
      const group = r.group === 'Closed-source Models' ? '' : r.group.includes('Video') ? 'video' : 'open';
      return `<tr><th class="model-col" scope="row"><span class="group-mark ${group}" title="${escape(r.group)}"></span>${escape(r.model)}</th>` + ids.map(id => `<td class="${r.scores[id] === best[id] ? 'best' : ''}">${r.scores[id].toFixed(1)}</td>`).join('') + `<td class="overall ${r.overall === best.overall ? 'best' : ''}">${r.overall.toFixed(1)}</td></tr>`;
    }).join('');
  }
  $('model-family').addEventListener('change', renderResults);
  $('model-sort').addEventListener('change', renderResults);
  renderResults();
  for (const t of data.tasks) {
    const option = document.createElement('option');
    option.value = t.id; option.textContent = `${t.id} · ${t.name}`;
    $('task-filter').append(option);
  }
  let selected = 0, questions = data.questions;
  const video = $('example-video');
  function renderExample() {
    const row = questions[selected];
    text('qa-count', `${questions.length.toLocaleString()} matches`);
    text('example-index', row ? `${selected + 1} / ${questions.length}` : '0 / 0');
    $('prev-example').disabled = !row || selected === 0;
    $('next-example').disabled = !row || selected === questions.length - 1;
    video.pause();
    video.removeAttribute('src');
    video.removeAttribute('poster');
    if (!row) {
      text('example-task', 'No matches'); text('example-name', 'Try another task or search term.');
      ['example-id', 'example-question', 'example-answer'].forEach(id => text(id, ''));
      $('video-download').hidden = true;
      video.load();
      return;
    }
    text('example-task', `${row.task_id} · Level ${row.level}`);
    text('example-name', row.task_name); text('example-id', row.question_id);
    text('example-question', row.question); text('example-answer', row.answer);
    const base = `https://huggingface.co/datasets/${config.dataset}/resolve/${encodeURIComponent(config.revision)}/`;
    video.src = base + 'preview/' + encodeURIComponent(row.video_path);
    if (row.video_path === 'VID_20250425_153011.mp4') video.poster = 'assets/preview-VID_20250425_153011.png';
    $('video-download').href = base + 'test/' + encodeURIComponent(row.video_path) + '?download=true';
    $('video-download').textContent = 'Download original video ↓';
    $('video-download').hidden = false;
    text('video-status', `${row.video_path} · H.264 display preview; use the original download for evaluation. Loads after dataset publication.`);
  }
  video.addEventListener('error', () => text('video-status', 'Preview unavailable. The dataset may not be published yet, or access/network settings may prevent playback. Download the original video to view it locally.'));
  function filterExamples() {
    const query = $('qa-search').value.toLocaleLowerCase().trim();
    questions = data.questions.filter(r => ($('task-filter').value === 'all' || r.task_id === $('task-filter').value) && `${r.question} ${r.answer} ${r.video_path} ${r.question_id}`.toLocaleLowerCase().includes(query));
    selected = 0; renderExample();
  }
  $('task-filter').addEventListener('change', filterExamples);
  $('qa-search').addEventListener('input', filterExamples);
  $('prev-example').addEventListener('click', () => { if (selected > 0) { selected--; renderExample(); } });
  $('next-example').addEventListener('click', () => { if (selected + 1 < questions.length) { selected++; renderExample(); } });
  renderExample();
  const authors = data.authors.map(a => { const parts = a.name.split(' '); return `${parts.pop()}, ${parts.join(' ')}`; }).join(' and ');
  const bib = `@misc{zhang2026wearertext,\n  title = {${data.title}},\n  author = {${authors}},\n  year = {2026},\n  howpublished = {Project manuscript},\n  url = {${config.repository}}\n}`;
  text('bibtex', bib);
  $('copy-citation').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(bib); text('copy-status', 'BibTeX copied.'); }
    catch { const range = document.createRange(); range.selectNodeContents($('bibtex')); const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range); text('copy-status', 'Text selected. Press Ctrl+C / ⌘C to copy.'); }
  });
})();
