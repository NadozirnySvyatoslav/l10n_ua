# LiqPay API, https://www.liqpay.ua/doc/api/internet_acquiring/checkout
CHECKOUT_URL = 'https://www.liqpay.ua/api/3/checkout'  # Client-Server: the customer's form POST
API_URL = 'https://www.liqpay.ua/api/request'  # Server-Server: refund, status
API_VERSION = 7  # "Версія API. Поточне значення - 7"

# Sandbox keys "always start with the sandbox_ prefix" (https://www.liqpay.ua/doc/api/testing).
SANDBOX_KEY_PREFIX = 'sandbox_'

# "Можливі значення: USD, EUR, UAH. Додаткові валюти можуть бути встановлені за запитом компанії"
SUPPORTED_CURRENCIES = ['UAH', 'USD', 'EUR']

DEFAULT_PAYMENT_METHOD_CODES = {'card', 'visa', 'mastercard'}

# Callback `paytype` -> Odoo payment method code. Other pay types (privat24, apay, gpay, qr...) keep
# the method the customer picked in Odoo.
PAYMENT_METHODS_MAPPING = {
    'card': 'card',
}

# Callback `status`, https://www.liqpay.ua/doc/api/callback and
# https://www.liqpay.ua/doc/api/information/status_payment
STATUS_MAPPING = {
    'done': (
        'success',
        # "Платіж успішний, буде зарахований в щодобовій проводці"
        'wait_compensation',
    ),
    'pending': (
        # Statuses waiting for the customer to confirm the payment.
        '3ds_verify', 'captcha_verify', 'cvv_verify', 'ivr_verify', 'otp_verify',
        'password_verify', 'phone_verify', 'pin_verify', 'senderapp_verify', 'wait_qr',
        'wait_sender', 'p24_verify', 'mp_verify',
        # Other non-final statuses.
        'cash_wait', 'hold_wait', 'invoice_wait', 'prepared', 'processing', 'wait_accept',
        'wait_card', 'wait_lc', 'wait_reserve', 'wait_secure', 'try_again',
    ),
    'error': ('error', 'failure'),
    'reversed': ('reversed',),
}

# Not in the current status list of the docs: the status of payments made with sandbox keys in
# older API versions. Never trusted as a payment unless the provider is in test mode.
SANDBOX_STATUS = 'sandbox'
