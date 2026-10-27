# Бібліотека підпису IIT EndUser (euscp, у браузері)

Сюди потрібно покласти файли бібліотеки клієнтського КЕП-підпису від АТ «ІІТ».
Вони пропрієтарні й не входять до репозиторію (gitignored). Схема та сама, що
на https://cabinet.tax.gov.ua/login: бібліотека працює у web worker браузера,
приватний ключ і пароль не залишають клієнт, сервер отримує лише готові підписи.

## Потрібні файли

```
euscp.js                  # клас EndUser (UMD-збірка)
euscp.worker.js           # web worker із криптографією (~17 МБ)
data/CAs.json             # параметри взаємодії із сумісними ЦСК
data/CACertificates.p7b   # сертифікати сумісних ЦСК
```

Файли вантажаться **ліниво за URL** при першому підписі, а не через
`web.assets_backend`. Шляхи зібрано в `static/src/js/kep_sign_service.js`
(`EUSCP_BASE` і сусідні константи). Досить покласти файли сюди — оновлювати
модуль не треба.

### Звідки взяти

Бібліотека — з npm-пакета `@it-enterprise/digital-signature` (перевірено
версію 1.4.7 від 08.09.2026):

```bash
cd l10n_ua_sign/static/src/lib/euscp
V=1.4.7
curl -fLo euscp.js        "https://cdn.jsdelivr.net/npm/@it-enterprise/digital-signature@$V/euscp/euscp.js"
curl -fLo euscp.worker.js "https://cdn.jsdelivr.net/npm/@it-enterprise/digital-signature@$V/dist/euscp.worker.js"
sha256sum euscp.js euscp.worker.js
# 1.4.7:
# c98b0443209c27610a531eec0064d424d527810cf6f7384e1174ffb8360a61b3  euscp.js
# 5ee4caab852b04b0272722ba2834f7589f0ad76c655247d3f52ee4b161aa4362  euscp.worker.js
```

Список ЦСК — ті самі файли, з якими працює вхід до електронного кабінету ДПС:

```bash
mkdir -p data
curl -fLo data/CAs.json           https://cabinet.tax.gov.ua/ws/api/crypto/public_sign/data/CAs.json
curl -fLo data/CACertificates.p7b https://cabinet.tax.gov.ua/ws/api/crypto/public_sign/data/CACertificates.p7b
```

`CAs.json` там той самий, що на https://iit.com.ua/downloads, а от
`CACertificates.p7b` **брати з кабінету, не з сайту IIT**: вереснева (2026)
збірка з iit.com.ua того ж розміру, але іншої редакції, і бібліотека 1.4.7
на ній падає в `Initialize` з кодом 49 — «Виникла помилка при роботі з
файловим сховищем сертифікатів та СВС». Файли ЦСК оновлюються разом із
появою нових ЦСК; після заміни перевірте ініціалізацію в браузері.

Сервіс завантажує обидва файли в обхід HTTP-кешу (`cache: 'no-cache'`),
тож нові файли підхоплюються без очищення кешу в користувачів.

Опис API: `euscp/euscp.d.ts` у тому ж npm-пакеті та
`EUSignJavaScriptD.doc` на сторінці завантажень IIT.

## ⚠️ Обов'язково: підтримка ДСТУ 7564:2014 («Купина»)

З 01.09.2026 усі нові сертифікати КЕП формуються з гешем ДСТУ 7564:2014, і
кабінет ДПС уже працює на ньому (`/ws/api/crypto/public_sign/hashAlgo` віддає
`DSTU7564`). Криптографія живе **всередині** worker, тож перевіряється сама
збірка:

```bash
grep -ao "EU_CTX_HASH_ALGO_DSTU7564[A-Z0-9_]*" euscp.worker.js | sort -u
```

Збірка **придатна**, якщо команда виводить `EU_CTX_HASH_ALGO_DSTU7564_256`
(версія 1.4.7 — придатна). Якщо перелік обривається на `GOST34311` — ключем
нового зразка підписати не вийде, замініть файли. Відстежується в #194.

Попередня збірка 1.0.3 (файли `euscpm.js`, `euutils.js`, `eusw.js`) була
непридатна і за алгоритмом, і за API (старий `EUSignCP` без класу `EndUser`) —
її більше не використовуємо.

## Доступ до ЦСК: напряму або через проксі Odoo

Під час зчитування ключа бібліотека звертається до ЦСК по сертифікат і його
статус. ЦСК із `"directAccess": true` у `CAs.json` (зокрема КНЕДП ДПС і «Дія»)
приймають запити з браузера напряму. Для решти бібліотека йде через
`/l10n_ua_sign/ca_proxy` (`controllers/ca_proxy.py`): маршрут доступний лише
користувачам Odoo і пропускає запити тільки до хостів ЦСК: з `CAs.json`, з адрес у
сертифікатах `CACertificates.p7b` (OCSP/CRL/caIssuers) і до кореневих органів ЦЗО
(`czo.gov.ua`) та ЗЦ НБУ (`zc.bank.gov.ua`). Останнє потрібне для ключів банківських
КНЕДП: під час підпису бібліотека перевіряє статус сертифіката самого КНЕДП у ЗЦ НБУ.

## Ліцензія

Бібліотека IIT пропрієтарна. Підпис КЕП безкоштовний, але перед
розповсюдженням файлів звірте умови IIT — тримайте їх лише
локально/на своїх серверах, не в публічному репозиторії.
