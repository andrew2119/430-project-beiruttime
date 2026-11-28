export function configurationSelectionLabel(definition:Record<string,unknown>,locale:'en'|'ar'){
 const label=definition.label;
 if(typeof label==='string')return label;
 if(label&&typeof label==='object'&&locale in label&&typeof (label as Record<string,unknown>)[locale]==='string')return String((label as Record<string,unknown>)[locale]);
 const movementLabel=definition['label_'+locale];
 return typeof movementLabel==='string'?movementLabel:'—';
}
export function configurationField(locale:'en'|'ar',name:string,code:unknown){
 const ar=locale==='ar';
 const dimensions:Record<string,string>=ar?{color:'اللون',material:'المادة',dial:'الميناء',sophistication:'مستوى التخصيص',movement:'الحركة',configuration:'التركيبة',watch_context:'سياق الساعة',brand:'العلامة'}:{color:'Color',material:'Material',dial:'Dial',sophistication:'Sophistication',movement:'Movement',configuration:'Configuration',watch_context:'Watch context',brand:'Brand'};
 const reasons:Record<string,string>=ar?{missing:'يلزم اختيار حالي',stale_option:'تغيّر الخيار؛ راجع النسخة الحالية',stale_revision:'تغيّرت النسخة المحفوظة',other_brand:'اختر خياراً من هذه العلامة',unsupported_base:'الخيار لا يدعم هذه القاعدة',unsupported_mounting:'الحركة لا تدعم التجهيز المختار',parts_unavailable:'القطع غير متوفرة',ambiguous_components:'اختر مكوّناً واحداً لهذه الفئة'}:{missing:'Choose a current selection',stale_option:'Option changed; review its current revision',stale_revision:'Saved revision changed',other_brand:'Choose an option from this brand',unsupported_base:'Option does not support this base',unsupported_mounting:'Movement does not support these fittings',parts_unavailable:'Parts are unavailable',ambiguous_components:'Choose one component for this category'};
 return `${dimensions[name]??(ar?'الاختيارات':'Choices')}: ${reasons[String(code)]??(ar?'راجع الاختيار الحالي':'Review the current selection')}`;
}
