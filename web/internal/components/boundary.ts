import { NAMES, TEXT, VALUES, type ReviewDataMode } from '../../tests/fixtures/worst-case';
import { COPY, type BoardCopy } from './copy';
import type { BoardLocale } from './model';
/** All user-sized review props cross the same boundary in every family. */
export function boardBoundary(mode:ReviewDataMode,locale:BoardLocale) {
  const base = COPY[locale], worst = mode === 'worst' || mode === 'thousand';
  const copy:BoardCopy = {...base,select:{...base.select}};
  const label = `${TEXT.expandedLabel} — ${NAMES.mixed} ${NAMES.emojiOnly}`;
  if (worst) {
    for (const key of ['primary','secondary','quiet','remove','busy','saved','disabled','iconAction','link','displayName','requiredName','placeholder','hint','fieldError','readonly','disabledField','notes','consent','radioOne','radioTwo','alerts','all','auctions','offers','choiceLabel','open','close','nested','popupLabel','menuLabel','menuInspect','menuSave','menuDanger','toastAction','finishLoading','clearToasts','toastRegion','dismissToast','retry','foldLabel','addRow','removeRow','undo','reverse','removeMidway','undoMidway','liveRow','light','dark','playIcon','pendingIcon','activeIcon','repeatNotice','wideWindow','reopen','deliveryStart','deliveryFail','deliveryRelease','photoFirst','photoSecond','photoNone','photoBroken','remount','panorama','portrait','panoramaAlt','portraitAlt','imageAlt','imagePlaceholder','imageBroken','imageReady','imageCredit'] as const) copy[key] = `${base[key]} — ${label}`;
    for (const key of ['toastInfo','toastSuccess','toastWarning','toastError','toastLoading','loadingTitle','emptyTitle','errorTitle','nestedTitle'] as const) copy[key] = `${base[key]} — ${TEXT.titleAtLimit}`;
    for (const key of ['surfaceBody','toastBody','emptyBody','errorBody','loadingBody','cardBody'] as const) copy[key] = `${TEXT.arabicTitle} — ${NAMES.mixed} ${NAMES.emojiOnly}`;
    for (const key of Object.keys(copy.select) as (keyof BoardCopy['select'])[]) copy.select[key] = `${base.select[key]} — ${label}`;
  }
  return {copy,worst,label:worst ? label : base.displayName,name:mode === 'empty' ? '' : mode === 'one' ? NAMES.oneLetter : worst ? NAMES.sellerAtLimit : NAMES.short,title:mode === 'empty' ? base.missing : mode === 'one' ? NAMES.oneLetter : worst ? TEXT.titleAtLimit : TEXT.title,description:mode === 'empty' ? '' : worst ? TEXT.description : TEXT.paragraphs,count:mode === 'empty' ? 0 : mode === 'one' ? 1 : mode === 'thousand' ? 1000 : worst ? VALUES.huge : 3};
}
