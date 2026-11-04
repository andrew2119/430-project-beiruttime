from .conftest import BRAND


def profile():
    return {'expected_revision':0,'capabilities':['maintenance','cleaning','repair','customization'],
        'contact':'sample@example.invalid','visit_en':'Demo content · Beirut · visits by arrangement only.',
        'visit_ar':'محتوى تجريبي · بيروت · الزيارات بترتيب مسبق فقط.',
        'scope_en':'Sample declared capabilities. Assessment and a separate quote are required; no work or appointment is confirmed.',
        'scope_ar':'قدرات معلنة تجريبية. يلزم التقييم وعرض سعر منفصل؛ لا يتم تأكيد أي عمل أو موعد.','published':True}


def option():
    return {'brand_id':str(BRAND),'expected_revision':0,'label_en':'Automatic · sample caliber','label_ar':'أوتوماتيكية · عيار تجريبي',
        'caliber':'DEMO-A01','cases':['DEMO-CASE-40'],'dials':['DEMO-DIAL-3'],'hands':['DEMO-HANDS-3'],
        'functions':['hours','minutes','seconds'],'quote_minor':25000,'currency':'USD','active':True}
