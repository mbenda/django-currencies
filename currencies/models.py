from decimal import Decimal, ROUND_UP
from numbers import Number
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from django import forms
from django.template.defaultfilters import capfirst
import requests

CURRENCY_CODE_MAX_LEN = 3

class Price(object):

    def __init__(self, value, currency):
        self.val = Decimal(value)
        self.currency = Currency.objects.normalize_currency(currency)

    def _get_as(self, currency):
        new_val = (self.val / self.currency.factor) * Currency.objects.normalize_currency(currency).factor
        return new_val.quantize(Decimal("0.01"), rounding=ROUND_UP)

    def get_as(self, currency):
        return self._get_as(Currency.objects.normalize_currency(currency))

    def serialize(self, request, currency=None):
        return self._get_as(request.CURRENCY if request is not None else Currency.objects.normalize_currency(currency))

# a price is stored in the db as <floating point numeric value>|<currency code>

# implements a price form field for the Price model
# (adapted from and based on http://djangosnippets.org/snippets/1200/)
class PriceFormField(forms.MultipleChoiceField):
    widget = forms.CheckboxSelectMultiple

    def __init__(self, *args, **kwargs):
        self.max_choices = kwargs.pop('max_choices', 0)
        super(PriceFormField, self).__init__(*args, **kwargs)

    def clean(self, value):
        if not value and self.required:
            raise forms.ValidationError(self.error_messages['required'])
        if value and self.max_choices and len(value) > self.max_choices:
            raise forms.ValidationError('invalid price format %s.' % (value,))
        return value

# implements a multiple-choice model field
# (adapted from http://djangosnippets.org/snippets/1200/, with comments applied, and further improvements)
class PriceField(models.Field):
    __metaclass__ = models.SubfieldBase

    MAX_DIGITS = 16

    def __init__(self, *args, **kwargs):
        # support both list and string as default values
        if 'default' in kwargs:
            kwargs['default'] = self.get_db_prep_value(kwargs['default'])
        kwargs['max_length'] = self.MAX_DIGITS + 1 + 1 + CURRENCY_CODE_MAX_LEN ## 1 for the decimal point, 1 for the | separator
        super(PriceField, self).__init__(*args, **kwargs)

    @classmethod
    def loads(cls, val_str):
        float_str, currency_code = val_str.split('|')
        assert currency_code in Currency.objects.BY_CODES, u"unexpected currency code %s" % (currency_code,)
        return float(float_str), currency_code

    @classmethod
    def dumps(cls, val_tuple):
        float_str, currency_code = val_tuple
        assert isinstance(float_str, Number) and isinstance(currency_code, basestring), "unexpected value format %s"%(val_tuple,)
        assert currency_code in Currency.objects.BY_CODES, u"unexpected currency code %s" % (currency_code,)
        return "|".join(val_tuple)

    def get_internal_type(self):
        return "CharField"

    def formfield(self, **kwargs):
        # don't call super, as that overrides default widget if it has choices
        defaults = {
            'required': not self.blank,
            'label': capfirst(self.verbose_name),
            'help_text': self.help_text }
        if self.has_default():
            defaults['initial'] = self.get_db_prep_value(self.get_default())
        defaults.update(kwargs)
        return PriceFormField(**defaults)

    def get_db_prep_value(self, value, *args, **kwargs):
        if isinstance(value, basestring):
            return value
        elif isinstance(value, (list, tuple)):
            return self.dumps(value)

    def value_to_string(self, obj):
        value = self._get_val_from_obj(obj)
        return self.get_db_prep_value(value)

    def to_python(self, value):
        if isinstance(value, (list, tuple)):
            assert len(value) == 2 and isinstance(value[0], Number) and isinstance(value[1], basestring), "unexpected value format %s"%(value,)
            return Price(value[0], value[1])
        elif isinstance(value, Price):
            return value
        elif not value: # can't return None because it causes trouble in e.g. admin,
            return Price(0, Currency.objects.DEFAULT)
            return

    def contribute_to_class(self, cls, name):
        super(PriceField, self).contribute_to_class(cls, name)

    def validate(self, value, model_instance):
        v, c = self.loads(value)
        return

# make the new field type known to South
from south.modelsinspector import add_introspection_rules
add_introspection_rules([], ["^tools\.models\.MultiSelectField"])

class CurrencyManager(models.Manager):

    @property
    def BY_CODES(self):
        if not hasattr(self, "_codes_dict"):
            all_active = self.filter(is_active=True)
            self._codes_dict = dict([(x.code, x) for x in all_active])
        return self._codes_dict

    @property
    def DEFAULT(self):
        if not hasattr(self, "_default_currency"):
            self._default_currency = self.get(is_default=True)
        return self._default_currency

    def normalize_currency(self, currency):
        return currency if isinstance(currency, Currency) else self.BY_CODES[currency]

    def get_currency_list(self):
        return [x.serialize() for x in self.BY_CODES.values()]

    def update_exchange_rates(self):
        base = self.get(is_base=True)
        response = requests.get('http://www.openexchangerates.org/api/latest.json?app_id={0}&base={1}'.format('2a66770e4dc0488d87d51bc15856e112', base.code))
        if not response.ok:
            raise Exception("failed getting exchange rates from openexchangerates.org")
        json = response.json()
        assert json['base'] == base.code, u"reported base currency is not US dollar"
        for currency in self.all():
            if not currency.code in json['rates']:
                continue
            self.filter(id=currency.id).update(factor=json['rates'][currency.code])

    def get_user_default_currency(self, request):
        print "QWEQWEQWE", request.session.items()
        if hasattr(request, 'session'):
            if 'currency' in request.session:
                print "BLAH", request.session['currency']
                return request.session['currency']
        print "no session"
        currency_code = request.COOKIES.get('currency', None)
        return self.BY_CODES.get(currency_code, self.DEFAULT)

    def get_conversion_rate(self, _from, _to):
        """
        @param _from: the currency in which your amount is denominated
        @param _to: the target currency
        @return: a multiplier by which you should multiply the amount denominated in the _from currency to get the amount in _to currency
        """
        return _to.factor / _from.factor


class Currency(models.Model):
    code = models.CharField(_('code'), max_length=CURRENCY_CODE_MAX_LEN)
    name = models.CharField(_('name'), max_length=35)
    symbol = models.CharField(_('symbol'), max_length=4, blank=True)
    factor = models.DecimalField(_('factor'), max_digits=10, decimal_places=4,
        help_text=_('Specifies the difference of the currency to default one.')) ## the factor to multiply by in order to convert from the base
    is_active = models.BooleanField(_('active'), default=True,
        help_text=_('The currency will be available.'))
    is_base = models.BooleanField(_('base'), default=False,
        help_text=_('Make this the base currency against which rates are calculated.'))
    is_default = models.BooleanField(_('default'), default=False,
        help_text=_('Make this the default user currency.'))

    objects = CurrencyManager()

    class Meta:
        ordering = ('name', )
        verbose_name = _('currency')
        verbose_name_plural = _('currencies')

    def __unicode__(self):
        return self.code

    def save(self, **kwargs):
        # Make sure the base and default currencies are unique
        if self.is_base:
            Currency.objects.filter(is_base=True).update(is_base=False)
        if self.is_default:
            Currency.objects.filter(is_default=True).update(is_default=False)
        super(Currency, self).save(**kwargs)

    def serialize(self):
        return dict(
            name=self.name,
            symbol=self.symbol,
            code=self.code,
            factor=self.factor,
        )
