import type { Condition } from '@contracts/contracts-orders/releases';
type Copy = {
  title:string; lead:string; order:string; open:string; release:string; recover:string; refresh:string;
  loading:string; empty:string; emptyBody:string; unavailable:string; unavailableBody:string; retry:string;
  denied:string; deniedBody:string; pending:string; pendingBody:string; paid_out:string; paidBody:string;
  gross:string; fee:string; net:string; closes:string; reference:string; noDate:string; signIn:string;
  assigned:string; nextAction:string; actions:Record<'review_conditions'|'reconcile_transfer'|'complete',string>;
  simulated:string; ready:string; review:string; support:string; currency:string;
  reasons:Record<Condition,string>;
};
export const COPY:Record<'en'|'ar',Copy> = {
  en:{
    assigned:'Responsible operator',nextAction:'Next action',actions:{review_conditions:'Review current release conditions',reconcile_transfer:'Reconcile the same transfer',complete:'No further transfer action'},
    title:'Seller payouts',lead:'Release retained seller proceeds after buyer protection checks.',
    order:'Order reference',open:'Check conditions',release:'Request simulated payout',recover:'Recover the same transfer',
    refresh:'Refresh conditions',loading:'Checking current release conditions',empty:'Choose an order',
    emptyBody:'Enter the exact order reference to inspect its current release conditions.',
    unavailable:'Payouts unavailable',unavailableBody:'Current payout access is unavailable. Funds remain held. Try again or contact support with the same action reference.',
    retry:'Try again',denied:'Release denied',deniedBody:'Current permission or one or more release conditions is missing. Refresh conditions before another request.',
    pending:'Transfer pending',pendingBody:'The result is not confirmed. Keep this action reference and recover the same transfer. Funds remain reserved.',
    paid_out:'Simulated payout confirmed',paidBody:'The journal confirms one simulated net seller payout.',
    gross:'Held watch price or job amount',fee:'Retained seller commission or business fee',net:'Net seller proceeds',
    closes:'Accepted dispute window closes',reference:'Action reference',noDate:'Receipt not recorded',
    signIn:'Sign in',simulated:'Simulated payments only. Collected fees are never refunded.',
    ready:'Current conditions pass. They will be checked again atomically when release is requested.',
    review:'Operator follow-up due',support:'Contact support',currency:'USD',
    reasons:{
      stale_revision:'The order revision changed. Refresh and review it.',
      binding_changed:'The watch, quote, policy or verified recipient version changed. Refresh and review it.',
      sources_unavailable:'Current source facts are unavailable. Try again; funds remain held.',
      economics_unaccepted:'Accepted economics, fee line or the full dispute-window policy is missing.',
      payment_not_held:'Confirmed paid held funds are required.',
      principal_unavailable:'The complete retained principal is not available for release.',
      refund_active:'A reserved or confirmed refund blocks this release.',
      recipient_unverified:'A current verified recipient belonging to the seller is required.',
      inspection_required:'This private watch needs actual expert custody and a current independent authentication pass.',
      assurance_required:'This business watch needs current platform business assurance.',
      quality_required:'This job needs current quality tests, fit and returned-parts checks by distinct assigned people.',
      receipt_required:'Actual receipt of this watch by the authorized buyer recipient is required.',
      window_open:'The full accepted dispute window has not expired.',
      hold_active:'A dispute or incident hold blocks release. Contact the responsible operator.',
      hold_unknown:'The current hold fence is unknown. Funds remain held.',
      release_exists:'A release already exists. Recover its original action reference.',
    },
  },
  ar:{
    assigned:'المسؤول المكلّف',nextAction:'الخطوة التالية',actions:{review_conditions:'مراجعة شروط التحرير الحالية',reconcile_transfer:'تسوية التحويل نفسه',complete:'لا إجراء إضافياً للتحويل'},
    title:'دفعات البائع',lead:'تحرير صافي مستحقات البائع المحفوظة بعد استيفاء شروط حماية المشتري.',
    order:'مرجع الطلب',open:'فحص الشروط',release:'طلب دفعة محاكاة',recover:'استعادة التحويل نفسه',
    refresh:'تحديث الشروط',loading:'جارٍ فحص شروط التحرير الحالية',empty:'اختر طلباً',
    emptyBody:'أدخل مرجع الطلب الدقيق للاطلاع على شروط تحرير مستحقاته الحالية.',
    unavailable:'الدفعات غير متاحة',unavailableBody:'الوصول الحالي إلى الدفعات غير متاح. تبقى الأموال محتجزة. حاول مجدداً أو تواصل مع الدعم بمرجع العملية نفسه.',
    retry:'حاول مجدداً',denied:'رُفض التحرير',deniedBody:'الصلاحية الحالية أو أحد شروط التحرير غير متوفر. حدّث الشروط قبل تقديم طلب آخر.',
    pending:'التحويل قيد الانتظار',pendingBody:'النتيجة غير مؤكدة. احتفظ بمرجع العملية واستعد التحويل نفسه. تبقى الأموال محجوزة.',
    paid_out:'تأكدت دفعة المحاكاة',paidBody:'يؤكد السجل دفعة محاكاة واحدة بصافي مستحقات البائع.',
    gross:'ثمن الساعة أو مبلغ العمل المحتجز',fee:'عمولة البائع أو رسم المنشأة المحفوظ',net:'صافي مستحقات البائع',
    closes:'تنتهي مهلة النزاع المقبولة',reference:'مرجع العملية',noDate:'لم يُسجّل الاستلام',
    signIn:'تسجيل الدخول',simulated:'الدفعات محاكاة فقط. لا تُردّ الرسوم المحصّلة أبداً.',
    ready:'الشروط الحالية مستوفاة. سيُعاد التحقق منها ضمن المعاملة عند طلب التحرير.',
    review:'موعد متابعة المسؤول',support:'تواصل مع الدعم',currency:'دولار أمريكي',
    reasons:{
      stale_revision:'تغيّر إصدار الطلب. حدّثه وراجعه.',
      binding_changed:'تغيّر إصدار الساعة أو العرض أو السياسة أو المستفيد الموثّق. حدّث البيانات وراجعها.',
      sources_unavailable:'حقائق المصدر الحالية غير متاحة. حاول مجدداً؛ تبقى الأموال محتجزة.',
      economics_unaccepted:'الشروط المالية المقبولة أو بند الرسم أو سياسة مهلة النزاع الكاملة غير متوفرة.',
      payment_not_held:'يلزم دفع مؤكد وأموال محتجزة.',
      principal_unavailable:'أصل المبلغ المحفوظ غير متاح بالكامل للتحرير.',
      refund_active:'مبلغ استرداد محجوز أو مؤكد يمنع هذا التحرير.',
      recipient_unverified:'يلزم مستفيد موثّق حالياً ويخص البائع.',
      inspection_required:'تحتاج هذه الساعة الخاصة إلى حيازة فعلية لدى الخبير ونتيجة مصادقة مستقلة ناجحة وحالية.',
      assurance_required:'تحتاج ساعة المنشأة إلى ضمان منشأة حالي معتمد من المنصة.',
      quality_required:'يحتاج العمل إلى اختبارات جودة وفحص الملاءمة والقطع المعادة بأشخاص مكلّفين مختلفين.',
      receipt_required:'يلزم استلام فعلي لهذه الساعة من المستلم المشتري المخوّل.',
      window_open:'لم تنتهِ مهلة النزاع المقبولة كاملة.',
      hold_active:'يمنع حجز نزاع أو حادث التحرير. تواصل مع المسؤول المكلّف.',
      hold_unknown:'حالة حاجز الحجز الحالي غير معروفة. تبقى الأموال محتجزة.',
      release_exists:'توجد عملية تحرير بالفعل. استعد مرجع عمليتها الأصلي.',
    },
  },
};
