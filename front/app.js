const form = document.querySelector('#upload-form');
const statusNode = document.querySelector('#status');
const resultsNode = document.querySelector('#results');
let result;
let submissionGeneration = 0;
let reviewController;

const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[char]));
const money = (value) => new Intl.NumberFormat('ru-RU', {
  style: 'currency', currency: 'RUB', maximumFractionDigits: 0
}).format(value);
const displayDate = (value) => value.split('-').reverse().join('.');
const evidenceLink = (evidence) => {
  if (!evidence) return '';
  const document = result?.documents.find((item) => item.id === evidence.document_id);
  return `<a class="evidence" href="#document-${document?.id ?? ''}-paragraph-${evidence.paragraph}">${escapeHtml(evidence.filename)}: «${escapeHtml(evidence.quote)}»</a>`;
};
const valueCell = (value, formatter) => value
  ? `${formatter(value.value)}${evidenceLink(value.evidence)}`
  : '<span class="missing">нет данных</span>';

async function loadDefaults() {
  const response = await fetch('/api/config');
  const config = await response.json();
  if (!response.ok) throw new Error(config.error?.message || 'Не удалось загрузить настройки');
  document.querySelector('#review-date').value = config.review_date;
  document.querySelector('#cutoff').value = config.delivery_cutoff;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const generation = ++submissionGeneration;
  reviewController?.abort();
  const controller = new AbortController();
  reviewController = controller;
  const files = [...document.querySelector('#files').files];
  statusNode.textContent = 'Обработка…';
  resultsNode.hidden = true;
  try {
    const documents = await Promise.all(files.map(async (file) => ({
      name: file.name, text: await file.text()
    })));
    if (generation !== submissionGeneration) return;
    const response = await fetch('/api/review', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        review_date: document.querySelector('#review-date').value,
        delivery_cutoff: document.querySelector('#cutoff').value,
        documents
      }),
      signal: controller.signal
    });
    const payload = await response.json();
    if (generation !== submissionGeneration) return;
    if (!response.ok) throw new Error(payload.error?.message || 'Ошибка обработки');
    result = payload;
    render();
    statusNode.textContent = `Обработано документов: ${documents.length}`;
  } catch (error) {
    if (generation !== submissionGeneration || error.name === 'AbortError') return;
    statusNode.textContent = error.message;
  } finally {
    if (generation === submissionGeneration) reviewController = undefined;
  }
});

function render() {
  document.querySelector('#contract-rows').innerHTML = result.contracts.map((contract) => `<tr>
    <td>${escapeHtml(contract.number)}</td>
    <td>${valueCell(contract.supplier, escapeHtml)}</td>
    <td>${valueCell(contract.amount, money)}</td>
    <td>${valueCell(contract.delivery_date, displayDate)}</td>
    <td>${contract.review_flags.map(escapeHtml).join('<br>') || '—'}</td>
  </tr>`).join('');

  const select = document.querySelector('#query-contract');
  select.innerHTML = result.contracts.map((contract) =>
    `<option value="${escapeHtml(contract.number)}">${escapeHtml(contract.number)}</option>`
  ).join('');

  const report = result.delivery_report;
  document.querySelector('#delivery-report').innerHTML = `<div class="report">
    Поставка раньше ${displayDate(report.cutoff)}: <strong>${report.delivery_before.join(', ') || 'нет'}</strong>.<br>
    Несогласованные изменения срока: <strong>${report.unapproved_delivery_changes.join(', ') || 'нет'}</strong>.
  </div>`;

  document.querySelector('#review-items').innerHTML = result.review_items.length
    ? result.review_items.map((item) => `<div class="notice">
      <strong>${escapeHtml(item.filename)}</strong> (${escapeHtml(item.contract_number || 'связь не установлена')})<br>
      ${escapeHtml(item.reason)}
      ${item.amount ? `<br>Предлагаемая сумма: ${money(item.amount.value)}${evidenceLink(item.amount.evidence)}` : ''}
      ${item.delivery_date ? `<br>Предлагаемый срок: ${displayDate(item.delivery_date.value)}${evidenceLink(item.delivery_date.evidence)}` : ''}
    </div>`).join('')
    : '<p>Нет документов, требующих дополнительной проверки.</p>';

  document.querySelector('#documents').innerHTML = result.documents.map((document) => `<article>
    <h3 id="document-${document.id}">${escapeHtml(document.filename)} — ${escapeHtml(document.kind)}, ${escapeHtml(document.status)}</h3>
    ${document.paragraphs.map((paragraph) => `<div class="paragraph" id="document-${document.id}-paragraph-${paragraph.number}"><strong>¶${paragraph.number}</strong> ${escapeHtml(paragraph.text)}</div>`).join('')}
  </article>`).join('');
  resultsNode.hidden = false;
}

function answer(field, formatter, label) {
  const number = document.querySelector('#query-contract').value;
  const contract = result?.contracts.find((item) => item.number === number);
  if (!contract) return;
  const value = contract[field];
  document.querySelector('#query-answer').textContent = `${number}, ${label}: ${value ? formatter(value.value) : 'нет данных'}`;
}
document.querySelector('#query-amount').addEventListener('click', () => answer('amount', money, 'сумма'));
document.querySelector('#query-date').addEventListener('click', () => answer('delivery_date', displayDate, 'срок поставки'));
loadDefaults().catch((error) => { statusNode.textContent = error.message; });
