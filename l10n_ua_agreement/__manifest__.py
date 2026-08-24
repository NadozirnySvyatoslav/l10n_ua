{
    'name': 'Ukraine - Agreements (Договори)',
    'version': '19.0.1.1.0',
    'category': 'Sales/Localization',
    'summary': 'Договори з клієнтами: шаблони, додаткові угоди, підпис (sign_oca), '
               'продажі та періодичні рахунки',
    'description': """
Ukraine Agreements (Договори)
=============================

Облік договорів з клієнтами поверх OCA-модулів ``agreement``, ``sign_oca`` та
``contract``:

* Договір зберігається як окремий об'єкт, генерується з шаблону для конкретного
  замовника (друкована форма QWeb);
* Стан договору: Чернетка → На підписанні → Підписаний;
* Електронний підпис через ``sign_oca`` з автоматичним переведенням договору у
  стан «Підписаний» та збереженням підписаного PDF;
* Додаткові угоди як дочірні договори (``parent_agreement_id``);
* Продажі та разові рахунки з договору (через ``agreement_sale``);
* Періодичні (абонентські) рахунки через ``contract.contract``.

Призначено для ФОП та підприємств, що надають послуги за договором.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'agreement',
        'agreement_sale',
        'sign_oca',
        'contract',
    ],
    'data': [
        'data/agreement_type_data.xml',
        'report/agreement_report.xml',
        'report/agreement_report_templates.xml',
        'views/agreement_views.xml',
        'views/agreement_i18n.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
