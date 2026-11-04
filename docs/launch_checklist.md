# Royal Cream Dairy: launch checklist (content and configuration)

Set in the production .env (see .env.example):

- PRIVACY_CONTACT_EMAIL: required. `manage.py check` warns in production while it is empty.
- GA_MEASUREMENT_ID (G-XXXXXXXXXX): optional. Analytics stays off until set. After setting it, confirm the
  privacy page mentions analytics and test with Google's Tag Assistant.
- PUBLIC_WHATSAPP_NUMBER: optional public "Chat on WhatsApp" link (international number).
- SOCIAL_FACEBOOK_URL / SOCIAL_TIKTOK_URL: optional (https:// only). Also used as sameAs in structured data.
- GOOGLE_SITE_VERIFICATION: the Search Console verification token (content value only).
- DEFAULT_OG_IMAGE: e.g. images/og-default.png, placed in static/images/ (about 1200x630) for social previews.
- PERSONAL_DATA_RETENTION_MONTHS: default 24. Agree the real period with the owner and an advisor.
- HSTS_SECONDS: leave 0 until HTTPS works end to end, then 3600, then raise. BEHIND_HTTPS_PROXY: see Batch 8 notes.

Before go-live:

- Have a Kenyan lawyer review the privacy policy; check whether the business must register with the ODPC.
- Add real product photos and prices; add testimonials only when genuine.
- Add a logo (replace the text wordmark) and a public contact route.
- Schedule `python manage.py purge_personal_data` monthly (deployment batch adds the cron entry).
- Handle a deletion request: `python manage.py anonymize_customer --phone 07XXXXXXXX --yes`
  (blocked while the customer has an open order). Corrections can be made in /django-admin/ > Customers.