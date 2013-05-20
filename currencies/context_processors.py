from currencies.models import Currency


def currencies(request):
    if not request.session.get('currency'):
        request.session['currency'] = Currency.objects.DEFAULT

    return {
        'CURRENCY': request.session['currency']
    }
