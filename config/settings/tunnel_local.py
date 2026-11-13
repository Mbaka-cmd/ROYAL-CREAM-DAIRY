from config.settings.development import *
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver", ".trycloudflare.com"]
CSRF_TRUSTED_ORIGINS = ["https://*.trycloudflare.com"]
