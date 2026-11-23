import os


SECRET_KEY = 'test'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
INSTALLED_APPS = ['django_sealed_fields', 'django_sealed_fields.pairing']
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates'}]

if os.environ.get('TEST_DATABASE') == 'sqlite':
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('POSTGRES_DB', 'django_sealed_fields'),
            'USER': os.environ.get('POSTGRES_USER', ''),
            'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
            'HOST': os.environ.get('POSTGRES_HOST', ''),
        },
    }

SEALED_FIELDS_KEY = 'a-development-key-of-enough-length-for-tests'
SEALED_FIELDS_KEY_FALLBACKS = []
