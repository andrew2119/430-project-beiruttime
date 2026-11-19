"""Equivalent minimal email templates; no private source facts enter previews."""
COPY = {
    'en': {
        'confirmation': 'Your confirmation is available.',
        'quote': 'Your quote is available.',
        'ready': 'Your next action is ready for review.',
        'refund': 'Your refund update is available.',
        'receipt-link': 'Your receipt is available.',
        'body': 'Synthetic delivery only. Sign in to review the current record. This message grants no permission and confirms no payment.',
    },
    'ar': {
        'confirmation': 'تأكيدك متاح.',
        'quote': 'عرض السعر الخاص بك متاح.',
        'ready': 'خطوتك التالية جاهزة للمراجعة.',
        'refund': 'تحديث استرداد المبلغ متاح.',
        'receipt-link': 'إيصالك متاح.',
        'body': 'تسليم تجريبي فقط. سجّل الدخول لمراجعة السجل الحالي. لا تمنح هذه الرسالة أي صلاحية ولا تؤكّد أي دفع.',
    },
}


def render(record):
    text = COPY[record['locale']]
    return {'subject': text[record['kind']], 'body': text['body'],
            'direction': 'rtl' if record['locale'] == 'ar' else 'ltr',
            'link': record['authenticated_link'], 'synthetic': True}
