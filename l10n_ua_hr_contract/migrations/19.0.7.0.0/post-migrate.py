"""Carry the manual staffing pointer over into the native position fields.

`hr.version.staffing_line_id` is derived now: it follows department + job on
the date the version is in force. Whatever a version used to point at is
therefore only preserved if the position fields say the same thing — so where
they are empty, they are filled in from the line the HR officer had chosen.

Where they disagree, the native fields win, as agreed: they are what every
order, П-2 card and report already prints. The disagreement is not swallowed
silently though — it lands in the employee's chatter so it can be reviewed.
"""
import logging
from collections import defaultdict

from odoo import api, SUPERUSER_ID
from odoo.tools import format_date

_logger = logging.getLogger(__name__)

BACKUP = 'hr_version_staffing_backup_19_7_0'


def _table_exists(cr, table):
    cr.execute(
        "SELECT EXISTS (SELECT FROM information_schema.tables "
        "WHERE table_name = %s)", (table,))
    return cr.fetchone()[0]


def migrate(cr, version):
    if not version:
        return

    if not _table_exists(cr, BACKUP):
        _logger.info(
            "l10n_ua_hr_contract 19.0.7.0.0: %s absent, nothing to carry over",
            BACKUP)
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    # Writing a position is a data fix, not an event in the employee's working
    # life: without this the migration would drop a tracking entry into every
    # touched chatter — `department_id`, `job_id` and `job_title` all carry
    # `tracking=True` — and notify their followers of it.
    Version = env['hr.version'].with_context(tracking_disable=True)

    # The company of the job and of the department travel along: `hr.version`
    # declares both fields with `check_company=True`, while `hr.staffing.table`
    # declares neither, so a line may legitimately exist in the table and still
    # be refused by the version. Caught here, that costs one skipped record;
    # left to the ORM, it raises inside the loop and rolls back the whole
    # upgrade with an error that never mentions the staffing table.
    cr.execute("""
        SELECT b.version_id, b.job_title, b.is_custom_job_title,
               s.department_id, s.job_id, s.name,
               d.company_id, j.company_id
        FROM {backup} b
        JOIN hr_staffing_table s ON s.id = b.staffing_line_id
        LEFT JOIN hr_department d ON d.id = s.department_id
        LEFT JOIN hr_job j ON j.id = s.job_id
        WHERE b.staffing_line_id IS NOT NULL
    """.format(backup=BACKUP))
    rows = cr.fetchall()

    # Language of the database, used wherever a company has none of its own.
    # Same chain core follows for a new contact (`res.partner._compute_lang`):
    # without it a Ukrainian installation would get an English note purely
    # because nobody ever set a language on the company's partner.
    installed = env['res.lang'].get_installed()
    db_lang = env.user.lang or (installed[0][0] if installed else 'en_US')

    # `env._()` finds its module by walking the stack back to this file, and a
    # migration script is not imported as `odoo.addons.*` (it is loaded as
    # `odoo.upgrade.<addon>.<version>.<name>`), so every call falls through to
    # the slow path that resolves the module from the file system. These two
    # words depend on the language alone, so they are translated once per
    # language instead of three times per note.
    labels_by_lang = {}

    def _labels(record_with_lang):
        lang = record_with_lang.env.lang
        if lang not in labels_by_lang:
            labels_by_lang[lang] = {
                'department': record_with_lang.env._('department'),
                'job': record_with_lang.env._('job'),
            }
        return labels_by_lang[lang]

    filled = 0
    conflicts = 0
    restored_titles = 0
    skipped = []
    writes = defaultdict(list)
    titles_to_restore = {}

    # Resolved once for the whole batch rather than per row. Browsing a single
    # id gives a recordset of one, and a recordset of one has no prefetch set:
    # every field read below would then be its own query, and the loop would
    # cost a handful of round trips per version. Browsing them together lets
    # the ORM fetch the lot in a few queries, and turns the existence check
    # from one SELECT per row into one for all of them.
    versions = Version.browse(row[0] for row in rows).exists()
    by_id = {version.id: version for version in versions}

    for (version_id, old_title, was_custom_title,
         line_department, line_job, line_name,
         department_company, job_company) in rows:
        record = by_id.get(version_id)
        if not record:
            continue

        company = record.company_id.id
        vals = {}
        divergences = []
        blocked = []
        # Judged per field, not per record: a line whose job belongs to another
        # company can still carry a department this version may keep, and
        # refusing both would throw away a good half of the answer.
        #
        # The company is checked on the branch that writes, and only there. A
        # field that already carries a value is not going to be written at all,
        # so `check_company` can never fire over it — reporting it as blocked
        # would raise an alarm about a record that is perfectly fine, and hide
        # the divergence that is actually worth reading. A record with no
        # company of its own belongs to every one of them.
        if line_department:
            if not record.department_id:
                if department_company and company and department_company != company:
                    blocked.append('department')
                else:
                    vals['department_id'] = line_department
            elif record.department_id.id != line_department:
                divergences.append('department')
        if line_job:
            if not record.job_id:
                if job_company and company and job_company != company:
                    blocked.append('job')
                else:
                    vals['job_id'] = line_job
            elif record.job_id.id != line_job:
                divergences.append('job')

        if vals:
            # Collected rather than written here: versions of the same position
            # carry identical values, so they can share one UPDATE. A write is
            # never a single query — it recomputes the stored job title and
            # cascades into `filled_units` on every staffing line of that job —
            # which makes the difference one of a dozen round trips per version
            # against a dozen per position.
            writes[tuple(sorted(vals.items()))].append(record.id)
            filled += 1
            if was_custom_title and old_title:
                titles_to_restore[record.id] = old_title

        if blocked:
            skipped.append(version_id)
            _logger.warning(
                "l10n_ua_hr_contract 19.0.7.0.0: %s of staffing line \"%s\" not "
                "carried over to version %s — it belongs to another company",
                ' and '.join(blocked), line_name or '', version_id)

        if not (divergences or blocked) or not record.employee_id:
            continue

        # The note is read by an HR officer, so it is written in the language of
        # the company. `_message_log` rather than `message_post`: it writes the
        # note into the chatter and notifies nobody. A data migration has no
        # business mailing followers about records it happened to walk past —
        # and a mail server that is down cannot then abort the upgrade.
        employee = record.employee_id.with_context(
            lang=record.employee_id.company_id.partner_id.lang or db_lang)
        labels = _labels(employee)
        # Same date format the HR officer sees everywhere else — the wage
        # warning on the version formats it the same way.
        line_date = format_date(employee.env, record.date_version)

        if divergences:
            conflicts += 1
            employee._message_log(body=employee.env._(
                'Staffing table: the version of %(date)s used to point at the '
                'line "%(line)s", which disagrees with the card (%(fields)s). '
                'The job and the department on the card were left as they are: '
                'they are what orders and the P-2 card print. Please check that '
                'this is what you expect.',
                date=line_date,
                line=line_name or '',
                fields=', '.join(labels[name] for name in divergences),
            ))

        if blocked:
            employee._message_log(body=employee.env._(
                'Staffing table: the line "%(line)s" of %(date)s was not '
                'carried over to the card because of a company mismatch on: '
                '%(fields)s. The position was left as it is — fix the staffing '
                'table, then set the position by hand.',
                date=line_date,
                line=line_name or '',
                fields=', '.join(labels[name] for name in blocked),
            ))

    for vals_key, version_ids in writes.items():
        Version.browse(version_ids).write(dict(vals_key))

    # Core recomputes job_title from the new position. A title that was typed by
    # hand is legitimate — an employee may present themselves differently from
    # the staffing wording — so it is put back. Read only now: what the title
    # became after the position was written is what decides whether the
    # hand-written one was lost.
    for version_id, old_title in titles_to_restore.items():
        record = by_id[version_id]
        if record.job_title != old_title:
            record.write({'job_title': old_title})
            restored_titles += 1

    if skipped:
        _logger.warning(
            "l10n_ua_hr_contract 19.0.7.0.0: %s versions where a company "
            "mismatch stopped one of the position fields from being carried "
            "over (ids: %s). That field was left empty — fix the staffing "
            "table and set the position by hand. The other field, if any, was "
            "carried over normally.",
            len(skipped), skipped[:50])

    _logger.info(
        "l10n_ua_hr_contract 19.0.7.0.0: filled position fields on %s versions "
        "from the staffing table, restored %s hand-written job titles, "
        "%s divergences reported in chatter",
        filled, restored_titles, conflicts)

    # Versions that used to carry a line and no longer resolve to one: the
    # position is outside the staffing table, or the table has no approved line
    # covering that date. A legitimate state — keeping a staffing table is not
    # mandatory — but worth naming, because for an employee whose wage sits in
    # the table this is exactly where a zero comes from.
    cr.execute(
        'SELECT version_id FROM %s WHERE staffing_line_id IS NOT NULL' % BACKUP)
    candidates = env['hr.version'].browse(
        [row[0] for row in cr.fetchall()]).exists()
    unresolved = candidates.filtered(lambda v: not v.staffing_line_id)
    if unresolved:
        _logger.warning(
            "l10n_ua_hr_contract 19.0.7.0.0: %s versions no longer resolve to "
            "a staffing line (ids: %s)",
            len(unresolved), unresolved.ids[:50])

    # The `staffing_line_id` column is deliberately left in place, and left
    # alone. The field is computed now, so the ORM neither selects nor writes
    # it; a fresh install never creates it, because Odoo builds columns only for
    # stored fields. It therefore survives only in databases that lived through
    # this migration — which is the point: rolling back to the previous code is
    # then a matter of checking that code out, with every pointer still where it
    # was, instead of restoring them from the snapshot table.
    #
    # Nothing may start reading it again. Its values freeze here: a position
    # changed after the migration is not reflected, and deleting a staffing line
    # still nulls the pointer through the foreign key — exactly as it did
    # before, so a rollback finds the state the old code would have produced.

