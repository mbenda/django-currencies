from django.conf.urls import patterns, include, url
from currencies.views import set_currency

urlpatterns = patterns('',
                       url(r'^set_currency/$', set_currency, name='currencies_set_currency'),
                       )
