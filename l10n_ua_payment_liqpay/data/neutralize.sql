-- disable LiqPay payment provider
UPDATE payment_provider
   SET liqpay_private_key = NULL;
