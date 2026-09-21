import base64
import json
import logging
import os

import paramiko

from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


HOST_KEY_POLICIES = {
    'reject': paramiko.RejectPolicy,
    'auto_add': paramiko.AutoAddPolicy,
    'warning': paramiko.WarningPolicy,
}


class L10nUaSupplierPriceImport(models.Model):
    _inherit = 'l10n_ua.supplier.price.import'

    def _do_fetch(self):
        self.ensure_one()
        if self.source_id.fetcher_type == 'sftp':
            return self._fetch_sftp()
        return super()._do_fetch()

    def _fetch_sftp(self):
        self.ensure_one()
        config = self._get_connection_config_sftp()

        host = config['host']
        port = int(config.get('port', 22))
        username = config['username']
        remote_path = config['remote_path']
        password = config.get('password')
        key_file = config.get('key_file')
        key_passphrase = config.get('key_passphrase')
        policy_name = config.get('host_key_policy', 'reject')
        timeout = self.source_id.fetch_timeout

        policy_cls = HOST_KEY_POLICIES.get(policy_name)
        if not policy_cls:
            raise UserError(_(
                "Unknown host_key_policy '%(p)s'. Allowed: %(a)s",
                p=policy_name, a=', '.join(HOST_KEY_POLICIES),
            ))

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(policy_cls())

        try:
            connect_kwargs = {
                'hostname': host,
                'port': port,
                'username': username,
                'timeout': timeout,
                'banner_timeout': timeout,
                'auth_timeout': timeout,
            }
            if key_file:
                connect_kwargs['key_filename'] = key_file
                if key_passphrase:
                    connect_kwargs['passphrase'] = key_passphrase
            elif password:
                connect_kwargs['password'] = password
            else:
                raise UserError(_("SFTP config must include 'password' or 'key_file'."))

            try:
                client.connect(**connect_kwargs)
            except paramiko.AuthenticationException as e:
                raise UserError(_("SFTP authentication failed: %s") % e)
            except (paramiko.SSHException, OSError) as e:
                raise UserError(_("SFTP connection failed: %s") % e)

            try:
                sftp = client.open_sftp()
            except paramiko.SSHException as e:
                raise UserError(_("Cannot open SFTP channel: %s") % e)

            try:
                with sftp.open(remote_path, 'rb') as remote_file:
                    content = remote_file.read()
            except IOError as e:
                raise UserError(_(
                    "Cannot read remote file '%(p)s': %(e)s",
                    p=remote_path, e=e,
                ))
            finally:
                sftp.close()
        finally:
            client.close()

        filename = os.path.basename(remote_path) or 'sftp_download'
        self.write({
            'raw_file': base64.b64encode(content).decode(),
            'raw_filename': filename,
        })

    def _get_connection_config_sftp(self):
        """Strict validation для SFTP-specific config."""
        raw = self.source_id.connection_config
        if not raw:
            raise UserError(_("SFTP source requires connection_config."))
        try:
            config = json.loads(raw)
        except (ValueError, TypeError):
            raise UserError(_(
                "Invalid connection_config JSON on source '%s'",
            ) % self.source_id.name)
        for required in ('host', 'username', 'remote_path'):
            if not config.get(required):
                raise UserError(_(
                    "SFTP config missing required field '%s'",
                ) % required)
        return config
