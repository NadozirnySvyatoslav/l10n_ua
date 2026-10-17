// forms-watch, Крок 1б: знімок сторінки пакета СКЗ на tax.gov.ua.
//
// Виконувати в РЕАЛЬНОМУ браузері (Claude-in-Chrome `javascript_tool` або
// DevTools Console) на вже відкритій сторінці
//   https://tax.gov.ua/elektronna-zvitnist/spetsializovane-klientske-program/
// curl/WebFetch отримують 403 (Akamai WAF), а fetch() у контексті цієї сторінки
// (той самий origin) проходить. Файли НЕ завантажуються на диск: HEAD дає розмір і
// дату, а перелік змін (.doc, ~80 КБ) читається в пам'яті.
//
// Результат — JSON-рядок. Збережи його як файл (напр. /tmp/skz_snapshot.json) і
// порівняй із baseline:
//   python3 -I docs/tools/forms_watch/skz.py check /tmp/skz_snapshot.json
//
// Перевірено 17.10.2026 на версії 1.34.9.0. Якщо верстка сторінки зміниться і
// `full`/`update` вийдуть порожні — дивись тексти абзаців <p> із «Повна версія …» /
// «Оновлення до … до версії X.Y.Z.W станом на DD.MM.YYYY» і виправ регулярку.
await (async () => {
  const rel = {};
  let kind = null;
  // Абзаци й посилання в порядку документа: заголовок релізу -> .zip -> «Перелік змін» -> .doc
  for (const el of document.querySelectorAll('p, td, li, a[href*="/data/files/"]')) {
    if (el.tagName !== 'A') {
      const t = el.innerText.replace(/\s+/g, ' ').trim();
      const m = t.match(/^(Повна версія|Оновлення до)\D*?(\d+(?:\.\d+){3}) станом на (\d\d)\.(\d\d)\.(\d{4})/);
      if (m) {
        kind = m[1].startsWith('Повна') ? 'full' : 'update';
        rel[kind] = {version: m[2], dated: `${m[5]}-${m[4]}-${m[3]}`};
      }
      continue;
    }
    if (!kind || !/\/data\/files\/\d+\.(zip|doc)$/.test(el.href)) continue;
    const key = el.href.endsWith('.zip') ? 'zip' : 'changelog';
    if (!rel[kind][key]) rel[kind][key] = {url: el.href, label: el.innerText.replace(/\s+/g, ' ').trim()};
    if (key === 'changelog') kind = null;
  }
  for (const r of Object.values(rel)) {
    for (const key of ['zip', 'changelog']) {
      const f = r[key];
      if (!f) continue;
      const h = await fetch(f.url, {method: 'HEAD', credentials: 'include'});
      f.bytes = +h.headers.get('content-length');
      f.last_modified = h.headers.get('last-modified');
    }
  }
  // Перелік змін оновлення: Word .doc, текст — UTF-16LE з offset 0 (cp1251 / offset 1 дають сміття).
  // У ньому лише зміни ОСТАННЬОГО релізу, не накопичувально.
  const cl = rel.update && rel.update.changelog;
  if (cl) {
    const buf = await (await fetch(cl.url, {credentials: 'include'})).arrayBuffer();
    const txt = new TextDecoder('utf-16le').decode(buf);
    const codes = new Set();
    // «J0100130 - …» та скорочений запис «F/J 0500701 …» (обидва типи платника)
    for (const m of txt.matchAll(/(?<![A-Z0-9])([JF])(\d{7})(?!\d)/g)) codes.add(m[1] + m[2]);
    for (const m of txt.matchAll(/(?:F\/J|J\/F)\s*(\d{7})(?!\d)/g)) { codes.add('F' + m[1]); codes.add('J' + m[1]); }
    cl.forms = [...codes].sort();
    cl.lines = (txt.match(/[ -~Ѐ-ӿ«»–—’№]{8,}/g) || [])
      .map(s => s.trim())
      .filter(s => /^(F\/J|J\/F|[JF]\d{7})|наказ|Постанов|Перелік змін/i.test(s))
      .map(s => s.slice(0, 200));
  }
  return JSON.stringify({captured_at: new Date().toISOString(), page: location.href, ...rel}, null, 1);
})()
