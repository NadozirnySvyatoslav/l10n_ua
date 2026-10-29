import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import {
    checkLibPresent,
    verifyAttached,
    verifyDetached,
} from "@l10n_ua_sign/js/kep_sign_service";

/**
 * Перевірка КЕП-підписів документа в браузері користувача Odoo.
 *
 * Python не вміє ДСТУ 4145, тож підписи, що прийшли з порталу чи поштою,
 * перевіряє бібліотека IIT тут: підпис саме цього файлу, сертифікат і його
 * статус у ЦСК. Приватний ключ не потрібен. Результат — на сервер.
 */
async function kepVerifyAction(env, action) {
    const resId = action.params.res_id;
    const model = "l10n_ua.edo.document";
    const notification = env.services.notification;
    try {
        if (!(await checkLibPresent())) {
            throw new Error(_t("The IIT library is not on the server (l10n_ua_sign/static/src/lib/euscp)."));
        }
        const spec = await env.services.orm.call(model, "kep_verification_data", [resId]);
        const results = [];
        for (const signature of spec.signatures) {
            const result = signature.attached
                ? await verifyAttached(signature.sign_b64, spec.data_b64)
                : await verifyDetached(spec.data_b64, signature.sign_b64);
            results.push({ id: signature.id, valid: result.valid, error: result.error, owner: result.owner });
        }
        const summary = await env.services.orm.call(model, "kep_store_verification", [resId, results]);
        notification.add(
            _t("Valid: %(valid)s, invalid: %(invalid)s.", summary),
            { type: summary.invalid ? "danger" : "success", title: _t("Signatures checked") }
        );
    } catch (e) {
        notification.add((e && (e.data?.message || e.message)) || String(e), {
            type: "danger", title: _t("Signatures not checked"),
        });
    }
    return { type: "ir.actions.client", tag: "soft_reload" };
}

registry.category("actions").add("l10n_ua_edo_kep.verify", kepVerifyAction);
