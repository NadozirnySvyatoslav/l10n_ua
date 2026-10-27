/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";

/**
 * Сервіс клієнтського КЕП-підпису поверх бібліотеки IIT EndUser (euscp).
 *
 * Та сама схема, що на cabinet.tax.gov.ua/login: бібліотека працює у
 * web worker браузера, ключ і пароль не залишають клієнт, сервер отримує лише
 * готові підписи. Запити до ЦСК (сертифікати, OCSP) бібліотека робить напряму,
 * якщо ЦСК це дозволяє (directAccess у CAs.json), інакше — через проксі Odoo.
 *
 * Файли бібліотеки пропрієтарні й лежать поза бандлом/git у
 * static/src/lib/euscp (див. README там). Вантажимо їх ЛІНИВО за URL: worker
 * ~17МБ у web.assets_backend роздув би кожну сторінку.
 *
 * Публічне API:
 *   checkLibPresent()   → чи лежать файли (HEAD, без завантаження)
 *   listCAs()           → ЦСК для вибору
 *   readKey(key, pwd, caName) / getKeySession() / forgetKey()
 *                       → один зчитаний ключ на вкладку, спільний для модулів
 *   signWithKey(spec)   → підписи для kep_submit_signed
 */

export const EUSCP_BASE = "/l10n_ua_sign/static/src/lib/euscp";
export const EUSCP_SCRIPT = `${EUSCP_BASE}/euscp.js`;
export const EUSCP_WORKER = `${EUSCP_BASE}/euscp.worker.js`;
export const CA_SETTINGS_URL = `${EUSCP_BASE}/data/CAs.json`;
export const CA_CERTIFICATES_URL = `${EUSCP_BASE}/data/CACertificates.p7b`;
export const CA_PROXY_URL = "/l10n_ua_sign/ca_proxy";

// EU_ERROR_CERT_NOT_FOUND: ключ виданий не тим ЦСК, що вибрано в діалозі.
export const KEY_CA_MISMATCH = 0x0033;

const REQUIRED_FILES = [EUSCP_SCRIPT, EUSCP_WORKER, CA_SETTINGS_URL, CA_CERTIFICATES_URL];

/** HEAD-перевірка, що файли бібліотеки та ЦСК на місці (без завантаження). */
export async function checkLibPresent() {
    try {
        const responses = await Promise.all(
            REQUIRED_FILES.map((url) => fetch(url, { method: "HEAD" }))
        );
        return responses.every((resp) => resp.ok);
    } catch {
        return false;
    }
}

function loadScript(url) {
    return new Promise((resolve, reject) => {
        if (document.querySelector(`script[data-euscp="${url}"]`)) {
            resolve();
            return;
        }
        const s = document.createElement("script");
        s.src = url;
        s.async = false;
        s.dataset.euscp = url;
        s.onload = () => resolve();
        s.onerror = () => reject(new Error(`Не вдалося завантажити ${url}`));
        document.head.appendChild(s);
    });
}

/**
 * euscp.js — UMD-збірка: підключена звичайним <script>, вона кладе свої
 * експорти (EndUser, EndUserConstants, …) у window.
 */
async function ensureEuscpLoaded() {
    if (!window.EndUser) {
        await loadScript(EUSCP_SCRIPT);
    }
    if (!window.EndUser) {
        throw new Error(_t(
            "Бібліотеку euscp завантажено, але клас EndUser не знайдено — " +
            "перевірте версію файлів у l10n_ua_sign/static/src/lib/euscp."
        ));
    }
}

/**
 * Список ЦСК і їхні сертифікати — у обхід HTTP-кешу браузера.
 *
 * Odoo віддає static із max-age на тиждень: якщо передати бібліотеці URL,
 * після оновлення файлів ЦСК користувачі ще тиждень ініціалізуються зі
 * старими (а несумісний CACertificates.p7b валить Initialize кодом 49,
 * «помилка при роботі з файловим сховищем сертифікатів та СВС»).
 * 'no-cache' перепитує сервер за ETag — незмінений файл коштує лише 304.
 */
async function loadCaData() {
    const load = async (url) => {
        const resp = await fetch(url, { cache: "no-cache" });
        if (!resp.ok) {
            throw new Error(_t("Не вдалося завантажити %s").replace("%s", url));
        }
        return resp;
    };
    const [cas, certificates] = await Promise.all([
        load(CA_SETTINGS_URL).then((resp) => resp.json()),
        load(CA_CERTIFICATES_URL).then((resp) => resp.arrayBuffer()),
    ]);
    return { cas, certificates: new Uint8Array(certificates) };
}

/**
 * ЦСК для вибору в діалозі: ``{name, issuerCNs}``, за назвою.
 *
 * Без вибраного ЦСК бібліотека по черзі перепитує всі ЦСК зі списку, поки
 * не знайде сертифікат ключа, — це довго. ``name`` (перша назва запису) можна
 * передати в ``readKey``: бібліотека шукає ЦСК за будь-якою з ``issuerCNs``.
 */
export async function listCAs() {
    const resp = await fetch(CA_SETTINGS_URL, { cache: "no-cache" });
    if (!resp.ok) {
        return [];
    }
    const cas = await resp.json();
    return cas
        .map((ca) => ({ name: ca.issuerCNs[0], issuerCNs: ca.issuerCNs }))
        .sort((a, b) => a.name.localeCompare(b.name, "uk"));
}

let endUserPromise = null;

/** Один ініціалізований екземпляр EndUser на вкладку (worker дорогий). */
function getEndUser() {
    if (!endUserPromise) {
        endUserPromise = (async () => {
            const [{ cas, certificates }] = await Promise.all([
                loadCaData(),
                ensureEuscpLoaded(),
            ]);
            const libraryTypeJS = window.EndUserConstants?.EndUserLibraryType?.JS ?? 0;
            const eu = new window.EndUser(EUSCP_WORKER, libraryTypeJS);
            await eu.Initialize({
                language: "uk",
                encoding: "UTF-8",
                httpProxyServiceURL: CA_PROXY_URL,
                directAccess: true,
                CAs: cas,
                CACertificates: certificates,
            });
            return eu;
        })().catch((e) => {
            endUserPromise = null;
            throw e;
        });
    }
    return endUserPromise;
}

function b64ToBytes(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) {
        bytes[i] = bin.charCodeAt(i);
    }
    return bytes;
}

function bytesToB64(bytes) {
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(bin);
}

function asciiBytes(text) {
    return Uint8Array.from(text, (ch) => ch.charCodeAt(0) & 0xff);
}

function concatBytes(parts) {
    const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
    let offset = 0;
    for (const part of parts) {
        out.set(part, offset);
        offset += part.length;
    }
    return out;
}

/** Блок транспортного формату ДПС: ASCII-тег, нуль-байт, довжина (4 байти LE), дані. */
export function dpsBlock(tag, payload) {
    const head = new Uint8Array(tag.length + 5);
    head.set(asciiBytes(tag), 0);
    new DataView(head.buffer).setUint32(tag.length + 1, payload.length, true);
    return concatBytes([head, payload]);
}

// EndUserKeyUsage.KeyAgreement у бібліотеці IIT.
const KEY_USAGE_KEY_AGREEMENT = 16;

/** Сертифікат шифрування (узгодження ключів) зчитаного ключа. */
async function ownKeyAgreementCert(eu) {
    const certs = await eu.GetOwnCertificates();
    const cert = (certs || []).find(
        (c) => ((c.infoEx || c.info || {}).keyUsageType & KEY_USAGE_KEY_AGREEMENT) !== 0);
    if (!cert) {
        throw new Error(_t(
            "У ключі немає сертифіката шифрування — ДПС не зможе розшифрувати звіт. " +
            "Потрібен ключ з двома сертифікатами (підпис і шифрування): зверніться до свого ЦСК."
        ));
    }
    return cert.data;
}

/**
 * Транспортний контейнер ДПС для подання звітності (наказ ДПА № 499 від 12.07.2010,
 * вимога API Електронного кабінету до contentBase64):
 *
 *   TRANSPORTABLE\0 len заголовок (FILENAME, EDRPOU…)
 *   CERTCRYPT\0     len сертифікат шифрування відправника
 *   UA1_CRYPT\0     len конверт на сертифікат ДПС від [UA1_SIGN\0 len CAdES(XML)]
 *
 * Голий конверт без цих блоків ДПС не розбирає — відповідь ERROR_DECRYPT.
 */
async function buildDpsTransport(eu, doc, xmlBytes) {
    if (!doc.recipient_cert_b64) {
        throw new Error(_t("Немає сертифіката шифрування ДПС — подання неможливе."));
    }
    const signed = await eu.SignDataInternal(true, xmlBytes, false);
    const signBlock = dpsBlock("UA1_SIGN", signed);
    const envelope = await eu.EnvelopData(
        [b64ToBytes(doc.recipient_cert_b64)], signBlock, false, false, false);
    const header = asciiBytes(
        "PRG_TYPE=Odoo l10n_ua\r\n" +
        "PRG_VER=19.0\r\n" +
        `FILENAME=${doc.filename}\r\n` +
        `EDRPOU=${doc.taxpayer_code || ""}\r\n` +
        "STTYPE=1\r\n"
    );
    return concatBytes([
        dpsBlock("TRANSPORTABLE", header),
        dpsBlock("CERTCRYPT", await ownKeyAgreementCert(eu)),
        dpsBlock("UA1_CRYPT", envelope),
    ]);
}

/**
 * Підписати один документ у потрібному форматі.
 * Сигнатури — з euscp.d.ts пакета @it-enterprise/digital-signature:
 *   SignDataInternal(appendCert, data, asBase64String)
 *   SignData(data, asBase64String) — відкріплений підпис
 *   EnvelopData(recipientsCerts, data, signData, appendCert, asBase64String)
 */
async function signOneDocument(eu, doc) {
    const bytes = b64ToBytes(doc.data_b64);
    const fmt = doc.format || "cades";
    if (fmt === "cades") {
        // CAdES/P7S із вбудованими даними та сертифікатом підписувача.
        return await eu.SignDataInternal(true, bytes, true);
    }
    if (fmt === "cades_detached") {
        // Відкріплений (зовнішній) CAdES: лише підпис із сертифікатом, без даних —
        // так його приймають ЕДО-сервіси (Вчасно: POST /documents/<id>/signatures).
        return await eu.SignData(bytes, true);
    }
    if (fmt === "envelope") {
        if (!doc.recipient_cert_b64) {
            // Сертифікат шифрування отримувача недоступний — лише підпис.
            return await eu.SignDataInternal(true, bytes, true);
        }
        // Спершу підпис, потім шифрування підписаного на сертифікат отримувача.
        const signedBytes = await eu.SignDataInternal(true, bytes, false);
        return await eu.EnvelopData(
            [b64ToBytes(doc.recipient_cert_b64)], signedBytes, false, true, true
        );
    }
    if (fmt === "dps_transport") {
        return bytesToB64(await buildDpsTransport(eu, doc, bytes));
    }
    if (fmt === "asic") {
        if (typeof eu.ASiCSignData === "function") {
            return await eu.ASiCSignData(bytes, true);
        }
        throw new Error(_t("ASiC-підпис недоступний у цій версії бібліотеки."));
    }
    throw new Error(_t("Невідомий формат підпису: %s").replace("%s", fmt));
}

/**
 * Зчитаний ключ — один на вкладку, спільний для всіх модулів.
 *
 * Бібліотека тримає приватний ключ у своєму worker-і, доки не викликати
 * ResetPrivateKey. Тож після перевірки з'єднання синхронізація чи підпис
 * накладної в іншому модулі не просять пароль знову. Ключ забувається через
 * KEY_TTL_MS після останнього використання, кнопкою «Інший ключ» або з
 * закриттям вкладки — на сервер він не потрапляє ніколи.
 */
export const KEY_TTL_MS = 20 * 60 * 1000;

const keySession = {
    eu: null,
    owner: null,
    certs: [],
    expiresAt: 0,
    timer: null,
};

function touchKeySession() {
    clearTimeout(keySession.timer);
    keySession.expiresAt = Date.now() + KEY_TTL_MS;
    keySession.timer = setTimeout(() => forgetKey(), KEY_TTL_MS);
}

/** Зчитаний ключ: ``{owner, certs, expiresAt}`` або null. */
export function getKeySession() {
    if (!keySession.eu || Date.now() >= keySession.expiresAt) {
        return null;
    }
    const { owner, certs, expiresAt } = keySession;
    return { owner, certs, expiresAt };
}

/** Вивантажити ключ із бібліотеки. */
export async function forgetKey() {
    clearTimeout(keySession.timer);
    const lib = keySession.eu;
    Object.assign(keySession, { eu: null, owner: null, certs: [], expiresAt: 0, timer: null });
    if (lib) {
        try {
            await lib.ResetPrivateKey();
        } catch {
            // ключ уже вивантажено — нічого робити
        }
    }
}

/**
 * Зчитати ключ і зробити його ключем вкладки.
 * @param {string|null} caName ЦСК із listCAs(); null — бібліотека
 *     перебирає всі ЦСК (довго). Якщо ключ виданий іншим ЦСК —
 *     помилка з кодом KEY_CA_MISMATCH.
 * @returns {{owner: Object, certs: Array, expiresAt: number}}
 */
export async function readKey(keyBuffer, password, caName = null) {
    if (!keyBuffer) {
        throw new Error(_t("Виберіть файл-ключ (.dat/.jks/.pfx)."));
    }
    if (!password) {
        throw new Error(_t("Введіть пароль до ключа."));
    }
    const lib = await getEndUser();
    await forgetKey();
    const owner = await lib.ReadPrivateKeyBinary(keyBuffer, password, null, caName || null);
    let certs = [];
    try {
        certs = await lib.GetOwnCertificates();
    } catch {
        certs = [];
    }
    Object.assign(keySession, { eu: lib, owner, certs });
    touchKeySession();
    return getKeySession();
}

/**
 * Підписати зчитаним ключем вкладки.
 * @param {{auth_subject?: string, documents: Array}} spec
 * @returns {{auth_signature: (string|null), signed: Object}}
 */
export async function signWithKey(spec) {
    if (!getKeySession()) {
        throw new Error(_t("Спершу зчитайте ключ."));
    }
    const eu = keySession.eu;
    touchKeySession();
    let authSignature = null;
    if (spec.auth_subject) {
        authSignature = await eu.SignDataInternal(true, spec.auth_subject, true);
    }
    const signed = {};
    for (const doc of spec.documents || []) {
        signed[doc.name] = await signOneDocument(eu, doc);
    }
    return { auth_signature: authSignature, signed };
}
