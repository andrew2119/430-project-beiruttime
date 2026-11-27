import type { SelectMessages } from '@beirut-time/ui/foundation';
export function selectMessages(locale:'en'|'ar'):SelectMessages {
  return locale==='ar' ? {placeholder:'اختر قيمة',filter:'ابحث في الخيارات',emptyTitle:'لا توجد نتائج',emptyBody:'غيّر البحث لعرض خيارات أخرى.',close:'أغلق الخيارات',loading:'جارٍ تحميل الخيارات…',errorTitle:'الخيارات غير متاحة',errorBody:'حاول تحميل الخيارات مجدداً.',retry:'حاول مجدداً'} : {placeholder:'Choose a value',filter:'Search options',emptyTitle:'No results',emptyBody:'Change the search to find another option.',close:'Close options',loading:'Loading options…',errorTitle:'Options unavailable',errorBody:'Try loading the options again.',retry:'Try again'};
}
