import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import {
    KEY_CA_MISMATCH,
    checkLibPresent,
    listCAs,
    readKey,
    setCaProxyUrl,
    signWithKey,
} from "@l10n_ua_sign/js/kep_sign_service";

/**
 * Підпис документа КЕП контрагентом на порталі (без користувача Odoo).
 *
 * Бібліотека IIT працює в браузері: ключ і пароль не залишають його, на сервер
 * іде лише відкріплений підпис файлу. Запити до ЦСК — через проксі з токеном
 * документа (звичайний проксі l10n_ua_sign — лише для користувачів Odoo).
 */
export class PortalKepSign extends Interaction {
    static selector = ".o_kep_portal";
    dynamicContent = {
        ".o_kep_sign": { "t-on-click.prevent": this.sign },
        ".o_kep_reject": { "t-on-click.prevent": this.reject },
        ".o_kep_upload": { "t-on-click.prevent": this.upload },
    };

    async willStart() {
        if (!this.el.querySelector(".o_kep_sign_card")) {
            return;
        }
        setCaProxyUrl(this.el.dataset.proxyUrl);
        const select = this.el.querySelector(".o_kep_ca");
        const cas = await listCAs().catch(() => []);
        for (const ca of cas) {
            const option = document.createElement("option");
            option.value = ca.name;
            option.textContent = ca.name;
            select.appendChild(option);
        }
    }

    get docUrl() {
        return `/my/edo/${this.el.dataset.docId}`;
    }

    get token() {
        return this.el.dataset.accessToken;
    }

    show(cls, text) {
        for (const name of [".o_kep_error", ".o_kep_status"]) {
            const box = this.el.querySelector(name);
            if (box) {
                box.classList.toggle("d-none", name !== cls || !text);
                if (name === cls) {
                    box.textContent = text || "";
                }
            }
        }
    }

    busy(on) {
        for (const button of this.el.querySelectorAll(".o_kep_sign, .o_kep_reject, .o_kep_upload")) {
            button.disabled = on;
        }
    }

    async sign() {
        const file = this.el.querySelector(".o_kep_key").files[0];
        const password = this.el.querySelector(".o_kep_password").value;
        const caName = this.el.querySelector(".o_kep_ca").value || null;
        if (!file || !password) {
            this.show(".o_kep_error", "Виберіть файл ключа і введіть пароль.");
            return;
        }
        this.busy(true);
        try {
            if (!(await this.waitFor(checkLibPresent()))) {
                throw new Error("Бібліотека підпису недоступна на сервері. Зверніться до відправника документа.");
            }
            this.show(".o_kep_status", "Зчитування ключа…");
            const buffer = new Uint8Array(await this.waitFor(file.arrayBuffer()));
            let key;
            try {
                key = await this.waitFor(readKey(buffer, password, caName));
            } catch (e) {
                if (e && e.code === KEY_CA_MISMATCH) {
                    throw new Error("Ключ видано іншим ЦСК: виберіть «Визначити автоматично» або свій ЦСК.");
                }
                throw e;
            }
            const owner = (key && key.owner) || {};
            this.show(".o_kep_status", `Підписує: ${owner.subjCN || ""}…`);
            const prepared = await this.waitFor(
                rpc(`${this.docUrl}/kep/prepare`, { access_token: this.token }));
            if (prepared.error) {
                throw new Error(prepared.error);
            }
            const { signed } = await this.waitFor(signWithKey({
                documents: [{ name: "document", data_b64: prepared.data_b64, format: "cades_detached" }],
            }));
            const result = await this.waitFor(rpc(`${this.docUrl}/kep/sign`, {
                access_token: this.token, signature: signed.document,
            }));
            if (result.error) {
                throw new Error(result.error);
            }
            this.show(".o_kep_status", "Документ підписано.");
            window.location.reload();
        } catch (e) {
            this.show(".o_kep_error", (e && (e.data?.message || e.message)) || String(e));
        } finally {
            this.busy(false);
        }
    }

    /** Підпис, зроблений деінде (czo.gov.ua/sign): ключ на наш сайт не потрапляє зовсім. */
    async upload() {
        const file = this.el.querySelector(".o_kep_upload_file").files[0];
        if (!file) {
            this.show(".o_kep_error", "Виберіть файл підпису (.p7s або архів ASiC-S).");
            return;
        }
        this.busy(true);
        try {
            this.show(".o_kep_status", "Завантаження підпису…");
            const bytes = new Uint8Array(await this.waitFor(file.arrayBuffer()));
            let binary = "";
            for (let i = 0; i < bytes.length; i += 0x8000) {
                binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
            }
            const result = await this.waitFor(rpc(`${this.docUrl}/kep/upload`, {
                access_token: this.token, filename: file.name, data_b64: btoa(binary),
            }));
            if (result.error) {
                throw new Error(result.error);
            }
            this.show(".o_kep_status", "Підпис прийнято.");
            window.location.reload();
        } catch (e) {
            this.show(".o_kep_error", (e && (e.data?.message || e.message)) || String(e));
        } finally {
            this.busy(false);
        }
    }

    async reject() {
        const reason = this.el.querySelector(".o_kep_reason").value.trim();
        if (!reason) {
            this.show(".o_kep_error", "Вкажіть причину відмови.");
            return;
        }
        this.busy(true);
        try {
            const result = await this.waitFor(rpc(`${this.docUrl}/kep/reject`, {
                access_token: this.token, reason,
            }));
            if (result.error) {
                throw new Error(result.error);
            }
            window.location.reload();
        } catch (e) {
            this.show(".o_kep_error", (e && e.message) || String(e));
        } finally {
            this.busy(false);
        }
    }
}

registry.category("public.interactions").add("l10n_ua_edo_kep.portal_kep_sign", PortalKepSign);
