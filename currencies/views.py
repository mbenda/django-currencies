from django.http import HttpResponseRedirect, HttpResponse
from currencies.models import Currency
from django.utils import simplejson


def set_currency(request):
    if request.method == 'POST':
        currency_code = request.POST.get('currency_code', None)
        next = request.POST.get('next', None)
    else:
        currency_code = request.GET.get('currency', None)
        next = request.GET.get('next', None)

    if not request.is_ajax():
        if not next:
            next = request.META.get('HTTP_REFERER', None)
        if not next:
            next = '/'
        response = HttpResponseRedirect(next)
    else:
        response = HttpResponse(simplejson.dumps({}), mimetype="application/json")

    if currency_code:
        if hasattr(request, 'session'):
            request.session['currency'] = Currency.objects.BY_CODES.get(currency_code, Currency.objects.DEFAULT)
        else:
            response.set_cookie('currency', currency_code)
    return response


