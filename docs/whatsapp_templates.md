# WhatsApp setup for Royal Cream Dairy

Messages are sent only as approved templates, so they work outside the 24-hour customer-service window.
Create these 7 templates in Meta Business Manager (language must match WHATSAPP_TEMPLATE_LANGUAGE).
Names are the defaults; override any with WHATSAPP_TEMPLATE_<EVENT> in .env.
Variables are positional: {{1}}, {{2}}, ... in exactly this order. Suggested wording is a starting point;
Meta decides approval and may ask for changes. If you change the number of variables, the code must change too.

| Template name | Sent to | Variables (in order) | Suggested body |
|---|---|---|---|
| rc_owner_new_order | Owner | 1 reference, 2 customer name, 3 customer phone, 4 area, 5 items, 6 total | New order {{1}} from {{2}} ({{3}}). Area: {{4}}. Items: {{5}}. Total: KSh {{6}}. Payment: pay on delivery. |
| rc_order_received | Customer | 1 name, 2 reference, 3 total, 4 area | Hello {{1}}, thank you for choosing Royal Cream Dairy. Your order {{2}} has been received. Total: KSh {{3}}. Delivery area: {{4}}. Payment: pay on delivery. We will confirm your order shortly. |
| rc_order_confirmed | Customer | 1 name, 2 reference | Hello {{1}}, your Royal Cream Dairy order {{2}} has been confirmed. |
| rc_order_out_for_delivery | Customer | 1 name, 2 reference | Hello {{1}}, your Royal Cream Dairy order {{2}} is out for delivery. |
| rc_order_completed | Customer | 1 name, 2 reference | Hello {{1}}, your Royal Cream Dairy order {{2}} has been delivered. Thank you for choosing us. |
| rc_order_cancelled | Customer | 1 name, 2 reference | Hello {{1}}, your Royal Cream Dairy order {{2}} has been cancelled. Please contact us if you have any questions. |
| rc_delivery_failed | Customer | 1 name, 2 reference | Hello {{1}}, we could not deliver your Royal Cream Dairy order {{2}}. Please contact us to arrange another delivery. |

## .env values (never commit .env)

    WHATSAPP_ACCESS_TOKEN=        # long-lived token (System User), not the 24h test token
    WHATSAPP_PHONE_NUMBER_ID=
    WHATSAPP_BUSINESS_ACCOUNT_ID=
    WHATSAPP_APP_SECRET=          # Meta app secret: used to verify webhook signatures
    WHATSAPP_VERIFY_TOKEN=        # any long random string you choose; must match the webhook setup
    WHATSAPP_API_VERSION=         # a current Graph API version from Meta's docs, e.g. vNN.0
    OWNER_WHATSAPP_NUMBER=+254... # full international number
    WHATSAPP_TEMPLATE_LANGUAGE=en

## Webhook

- Callback URL: https://royalcreamdairy.co.ke/webhooks/whatsapp/
- Verify token: the WHATSAPP_VERIFY_TOKEN value
- Subscribe to the `messages` field (delivery statuses arrive there)

## Cron (cPanel)

Run every minute (or the shortest interval Truehost allows):
`python scripts/process_notifications.py` using the project virtualenv.

## Operations

- Failed or given-up notifications show in /django-admin/ under Notifications; select them and use "Re-queue".
- Or: `python manage.py requeue_notifications --failed`
- Notifications created while WhatsApp is not configured wait as PENDING and are sent once it is.